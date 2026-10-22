import copy
import http.client
import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import dify_gateway as gateway
import dify_probe as probe
from test_dify_probe import Handler, SENSITIVE


class EchoHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def echo(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.server.received.append((self.command, self.path, self.headers, body))
        if self.path.endswith("/error"):
            self.send_response(422)
            body = b'{"code":"invalid_param","message":"upstream error"}'
        else:
            self.send_response(200)
        self.send_header("Content-Type", self.headers.get("Content-Type", "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Upstream", "retained")
        self.send_header("Connection", "close, X-Remove")
        self.send_header("X-Remove", "discard")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    do_POST = echo
    do_GET = echo
    do_HEAD = echo
    do_PUT = echo
    do_PATCH = echo
    do_DELETE = echo
    do_OPTIONS = echo


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(self.directory.cleanup)
        self.upstream = ThreadingHTTPServer(("127.0.0.1", 0), EchoHandler)
        self.upstream.received = []
        self.upstream.requests = []
        self.upstream_thread = threading.Thread(target=self.upstream.serve_forever, daemon=True)
        self.upstream_thread.start()
        self.settings = {
            "base": "http://127.0.0.1:" + str(self.upstream.server_port) + "/private/v1",
            "original_key": SENSITIVE, "key": "gw-test-distribution-key", "key_id": "test-key-id",
            "enabled": True, "max_requests": 0, "expires_timestamp": None,
            "max_body_bytes": 1024 * 1024, "timeout": 5,
        }
        self.store = gateway.Store(Path(self.directory.name) / "logs.sqlite3")
        self.server = gateway.GatewayServer(("127.0.0.1", 0), self.settings, self.store)
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.addCleanup(self.stop_servers)

    def stop_servers(self):
        self.server.shutdown()
        self.server.server_close()
        self.upstream.shutdown()
        self.upstream.server_close()
        self.server_thread.join()
        self.upstream_thread.join()

    def call(self, method="POST", path="/v1/echo", body=b"{}", key=None, headers=None, chunks=False):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            request_headers = {"Authorization": "Bearer " + (self.settings["key"] if key is None else key)}
            request_headers.update(headers or {})
            connection.request(method, path, body=body, headers=request_headers, encode_chunked=chunks)
            response = connection.getresponse()
            return response.status, response.read(), response.headers
        finally:
            connection.close()

    def wait_records(self, count):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            records = self.store.recent()
            if len(records) >= count and all(record["elapsed_ms"] is not None for record in records):
                return records
            time.sleep(0.01)
        self.fail("request logs did not finish")

    def test_raw_body_query_and_headers(self):
        body = b'--boundary\r\nContent-Disposition: form-data; name="file"; filename="a.bin"\r\n\r\n\x00\xff\r\n--boundary--\r\n'
        status, returned, headers = self.call(
            path="/v1/files/upload?a=1&a=2&value=%E4%B8%AD", body=body,
            headers={"Content-Type": "multipart/form-data; boundary=boundary", "X-Custom": "retained",
                     "Connection": "close, X-Remove", "X-Remove": "discard"})
        self.assertEqual((status, returned), (200, body))
        method, path, received_headers, received_body = self.upstream.received[0]
        self.assertEqual(path, "/private/v1/files/upload?a=1&a=2&value=%E4%B8%AD")
        self.assertEqual(received_body, body)
        self.assertEqual(received_headers["Authorization"], "Bearer " + SENSITIVE)
        self.assertEqual(received_headers["X-Custom"], "retained")
        self.assertIsNone(received_headers.get("X-Remove"))
        self.assertEqual(headers["X-Upstream"], "retained")
        self.assertIsNone(headers.get("X-Remove"))
        logs = self.wait_records(1)
        self.assertNotIn(SENSITIVE, json.dumps(logs))
        self.assertNotIn("private/v1", json.dumps(logs))
        self.assertEqual(logs[0]["outcome"], "forwarded")

    def test_chunked_request_and_methods(self):
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "GET"):
            status, body, _ = self.call(method=method, body=iter([b"hello", b"world"]), chunks=True)
            self.assertEqual((status, body), (200, b"helloworld"))
        status, body, _ = self.call(method="HEAD", body=None)
        self.assertEqual((status, body), (200, b""))

    def test_upstream_error_preserved(self):
        status, body, _ = self.call(path="/v1/error")
        self.assertEqual(status, 422)
        self.assertEqual(json.loads(body)["code"], "invalid_param")

    def test_upstream_disconnect_returns_502(self):
        class DisconnectHandler(BaseHTTPRequestHandler):
            def handle(self):
                self.connection.close()

        self.upstream.RequestHandlerClass = DisconnectHandler
        self.assertEqual(self.call()[0], 502)

    def test_incomplete_upstream_body_is_detected_by_client(self):
        class TruncatedHandler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Length", "100")
                self.end_headers()
                self.wfile.write(b"partial")

        self.upstream.RequestHandlerClass = TruncatedHandler
        with self.assertRaises(http.client.IncompleteRead):
            self.call()
        logs = self.wait_records(1)
        self.assertIn(logs[0]["outcome"], {"incomplete_response", "connection_interrupted"})

    def test_invalid_key_disabled_expired_and_size_limit(self):
        self.assertEqual(self.call(key="wrong")[0], 401)
        self.settings["enabled"] = False
        self.assertEqual(self.call()[0], 403)
        self.settings["enabled"] = True
        self.settings["expires_timestamp"] = time.time() - 10
        self.assertEqual(self.call()[0], 403)
        self.settings["expires_timestamp"] = None
        self.settings["max_body_bytes"] = 3
        self.assertEqual(self.call(body=b"oversized")[0], 413)
        self.assertEqual(len(self.upstream.received), 0)
        logs = self.wait_records(4)
        self.assertEqual({row["outcome"] for row in logs},
                         {"invalid_key", "key_disabled", "key_expired", "request_too_large"})

    def test_quota_is_atomic_and_persistent(self):
        self.settings["max_requests"] = 3
        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses = list(pool.map(lambda _: self.call()[0], range(8)))
        self.assertEqual(statuses.count(200), 3)
        self.assertEqual(statuses.count(429), 5)
        self.assertEqual(len(self.upstream.received), 3)
        reopened = gateway.Store(Path(self.directory.name) / "logs.sqlite3")
        _, status, _ = reopened.begin(copy.copy(self.settings), True, "POST", "other")
        self.assertEqual(status, 429)

    def test_workflow_probe_through_gateway(self):
        self.upstream.RequestHandlerClass = Handler
        base = "http://127.0.0.1:" + str(self.server.server_port) + "/v1"
        cases, _ = probe.run_target(base, self.settings["key"], {"query": "test"}, 10)
        self.assertTrue(all(case["passed"] for case in cases), cases)
        self.assertLess(cases[2]["first_data_ms"], cases[2]["elapsed_ms"])
        self.assertEqual(len(self.upstream.requests), 4)
        self.assertTrue(all(item[1] == "Bearer " + SENSITIVE for item in self.upstream.requests))
        self.assertTrue(all(item[0].startswith("/private/v1/") for item in self.upstream.requests))
        self.assertEqual(len(self.wait_records(4)), 4)

    def test_unknown_path_cannot_change_upstream_host(self):
        self.assertEqual(self.call(path="http://elsewhere.invalid/v1/run")[0], 404)
        self.assertEqual(len(self.upstream.received), 0)

    def test_generated_distribution_key_persists(self):
        root = Path(self.directory.name)
        (root / "probe.ini").write_text(
            "[dify]\nurl=http://upstream.invalid/v1\nkey=" + SENSITIVE, encoding="utf-8")
        path = root / "gateway.ini"
        path.write_text("[server]\nupstream_config=probe.ini\n[distribution]\nkey=\n", encoding="utf-8")
        first = gateway.load_settings(path)
        second = gateway.load_settings(path)
        self.assertEqual(first["key"], second["key"])
        self.assertTrue(first["key"].startswith("gw-"))
        self.assertNotIn(SENSITIVE, path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
