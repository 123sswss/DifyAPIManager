import contextlib
import io
import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import dify_probe as probe


SENSITIVE = "private-host.internal/app-secret-original"


def stream(events):
    return b"event: ping\n\n" + b"".join(
        ("data: " + json.dumps(event) + "\n\n").encode() for event in events)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_body(self, body, media="application/json"):
        self.send_response(200)
        self.send_header("Content-Type", media)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append((self.path, self.headers["Authorization"], payload))
        data = {"id": SENSITIVE, "status": "succeeded", "outputs": {SENSITIVE: SENSITIVE}}
        if payload["response_mode"] == "streaming":
            body = stream([
                {"event": "workflow_started"},
                {"event": SENSITIVE, "data": {"message": SENSITIVE}},
                {"event": "workflow_finished", "workflow_run_id": SENSITIVE, "data": data},
            ])
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            split_at = body.index(b"\n\n", body.index(b"data:")) + 2
            self.wfile.write(body[:split_at])
            self.wfile.flush()
            time.sleep(0.06)
            self.wfile.write(body[split_at:])
        else:
            self.send_body(json.dumps({"workflow_run_id": SENSITIVE, "data": data}).encode())

    def do_GET(self):
        self.server.requests.append((self.path, self.headers["Authorization"], None))
        self.send_body(json.dumps({"id": SENSITIVE, "status": "succeeded"}).encode())


class ProbeTests(unittest.TestCase):
    def test_ini_literal_values_bom_and_unicode(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            config_path = Path(directory) / "config.ini"
            config_path.write_text(
                '[dify]\nurl = http://localhost/prefix%20/v1\nkey = app-%secret#value\n'
                'inputs = {"query":"中文 100% #原样 ;保留"}\n', encoding="utf-8-sig")
            targets, inputs = probe.load_config(config_path, False)
            self.assertEqual(targets, [("direct", "http://localhost/prefix%20/v1", "app-%secret#value")])
            self.assertEqual(inputs, {"query": "中文 100% #原样 ;保留"})

    def test_ini_errors_are_sanitized(self):
        configurations = [
            ("[dify\n" + SENSITIVE, "config_file_unreadable_or_invalid_ini"),
            ("[dify]\nurl = " + SENSITIVE, "dify_url_invalid"),
            ('[dify]\nurl = http://localhost/v1\nkey = fake\ninputs = ' + SENSITIVE,
             "dify_inputs_invalid_json"),
            ('[dify]\nurl = http://localhost/v1\nkey = fake\ninputs = []',
             "dify_inputs_must_be_object"),
        ]
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            config_path = Path(directory) / "config.ini"
            for contents, expected in configurations:
                config_path.write_text(contents, encoding="utf-8")
                with self.assertRaises(probe.ProbeError) as caught:
                    probe.load_config(config_path, False)
                self.assertEqual(probe.error_category(caught.exception), expected)
                self.assertNotIn(SENSITIVE, str(caught.exception))
            with self.assertRaisesRegex(probe.ProbeError, "config_file_missing"):
                probe.load_config(Path(directory) / "missing.ini", False)

    def test_normalize_paths(self):
        self.assertEqual(probe.normalize_url("http://localhost/prefix/v1/workflows/run"),
                         "http://localhost/prefix/v1")
        self.assertEqual(probe.normalize_url("https://localhost/v1/"), "https://localhost/v1")

    def test_invalid_urls(self):
        for value in ("file:///tmp/key", "http://user:password@localhost/v1", "http://localhost/?secret=1"):
            with self.assertRaises(probe.ProbeError):
                probe.normalize_url(value)

    def test_sse_failure_at_http_200(self):
        summary, _ = probe.parse_sse(stream([
            {"event": "workflow_started"},
            {"event": "workflow_finished", "data": {"status": "failed", "error": SENSITIVE}},
        ]))
        self.assertTrue(summary["failure_event"])
        self.assertNotIn(SENSITIVE, json.dumps(summary))

    def test_sse_malformed_and_truncated(self):
        summary, _ = probe.parse_sse(b"data: invalid\n\ndata: {}")
        self.assertEqual(summary["malformed_events"], 1)
        self.assertTrue(summary["incomplete_frame"])

    def test_sse_multiline_crlf(self):
        summary, _ = probe.parse_sse(
            b'data: {"event":\r\ndata: "workflow_started"}\r\n\r\n')
        self.assertTrue(summary["workflow_started"])

    def test_sse_single_newline_is_incomplete(self):
        summary, _ = probe.parse_sse(b'data: {"event":"workflow_finished"}\n')
        self.assertTrue(summary["incomplete_frame"])
        self.assertFalse(summary["workflow_finished"])

    def test_error_text_is_omitted(self):
        self.assertEqual(probe.error_category(OSError(SENSITIVE)), "connection_error")
        self.assertEqual(probe.error_category(ValueError(SENSITIVE)), "unexpected_error")

    def test_shape_omits_names_and_values(self):
        self.assertNotIn(SENSITIVE, json.dumps(probe.shape({SENSITIVE: [SENSITIVE, 7, None]})))

    def test_full_mock_run_and_report_privacy(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.requests = []
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            base = "http://127.0.0.1:" + str(server.server_port) + "/prefix/v1"
            with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
                stdout = io.StringIO()
                config_path = Path(directory) / "dify_probe.ini"
                config_path.write_text(
                    "[dify]\nurl = " + base + "\nkey = " + SENSITIVE
                    + "\ninputs = " + json.dumps({SENSITIVE: SENSITIVE})
                    + "\n[gateway]\nurl = " + base + "\nkey = " + SENSITIVE, encoding="utf-8")
                with patch("sys.argv", ["dify_probe.py", "--gateway"]), \
                        patch.object(probe, "__file__", str(Path(directory) / "dify_probe.py")), \
                        contextlib.redirect_stdout(stdout):
                    self.assertEqual(probe.main(), 0)
                report_text = next(Path(directory).glob("dify-report-*.json")).read_text(encoding="utf-8")
                for private_value in (SENSITIVE, base, "127.0.0.1", "prefix"):
                    self.assertNotIn(private_value, report_text + stdout.getvalue())
                report = json.loads(report_text)
                self.assertTrue(report["all_cases_passed"])
                self.assertTrue(report["comparison"]["streaming"]["output_value_equal"])
                streamed = report["targets"]["direct"][2]
                self.assertLess(streamed["first_data_ms"], streamed["elapsed_ms"])
                self.assertEqual(len(server.requests), 8)
                self.assertEqual(server.requests[0][0], "/prefix/v1/workflows/run")
                self.assertEqual(server.requests[0][1], "Bearer " + SENSITIVE)
                self.assertEqual(server.requests[0][2]["inputs"], {SENSITIVE: SENSITIVE})
        finally:
            server.shutdown()
            server.server_close()
            worker.join()

    def test_wrong_content_type_fails_streaming(self):
        payload = json.dumps({"workflow_run_id": "id", "data": {
            "status": "succeeded", "outputs": {"answer": "ok"}}}).encode()
        meta = {"http_status": 200, "content_type": "application/json", "transport_complete": True}
        with patch.object(probe, "request", return_value=(meta, payload)):
            cases, _ = probe.run_target("http://localhost/v1", "fake", {}, 10)
        self.assertTrue(cases[0]["passed"])
        self.assertFalse(cases[2]["passed"])

    def test_truncated_http_body_is_detected(self):
        class TruncatedHandler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", "100")
                self.end_headers()
                self.wfile.write(b"{}")

        server = ThreadingHTTPServer(("127.0.0.1", 0), TruncatedHandler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            meta, _ = probe.request("http://127.0.0.1:" + str(server.server_port),
                                    "fake", "/", None, False, 3)
            self.assertFalse(meta["transport_complete"])
            self.assertEqual(meta["error"], "incomplete_response")
        finally:
            server.shutdown()
            server.server_close()
            worker.join()


if __name__ == "__main__":
    unittest.main()
