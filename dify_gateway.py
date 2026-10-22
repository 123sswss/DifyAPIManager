import argparse
import configparser
import hashlib
import hmac
import http.client
import json
import secrets
import socket
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from dify_probe import ProbeError, error_category, normalize_url


HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "proxy-connection",
}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def read_ini(path):
    config = configparser.ConfigParser(interpolation=None)
    try:
        with path.open(encoding="utf-8-sig") as source:
            config.read_file(source)
    except (OSError, UnicodeError, configparser.Error):
        raise ProbeError("config_file_unreadable_or_invalid_ini") from None
    return config


def load_settings(path):
    config = read_ini(path)
    try:
        upstream_file = path.parent / config.get("server", "upstream_config")
        upstream = read_ini(upstream_file)
        base = normalize_url(upstream.get("dify", "url"))
        original_key = upstream.get("dify", "key").strip()
        if not original_key or any(character.isspace() for character in original_key):
            raise ProbeError("dify_key_invalid")
        settings = {
            "host": config.get("server", "host", fallback="0.0.0.0").strip(),
            "port": config.getint("server", "port", fallback=8787),
            "timeout": config.getint("server", "upstream_timeout", fallback=180),
            "max_body_bytes": config.getint("server", "max_body_mb", fallback=64) * 1024 * 1024,
            "database": path.parent / config.get("server", "database", fallback="gateway.sqlite3"),
            "enabled": config.getboolean("distribution", "enabled", fallback=True),
            "max_requests": config.getint("distribution", "max_requests", fallback=0),
            "expires_at": config.get("distribution", "expires_at", fallback="").strip(),
            "base": base, "original_key": original_key,
        }
        if (not 1 <= settings["port"] <= 65535 or not 1 <= settings["timeout"] <= 3600
                or not 1 <= settings["max_body_bytes"] <= 1024 * 1024 * 1024
                or settings["max_requests"] < 0):
            raise ProbeError("gateway_settings_out_of_range")
        settings["expires_timestamp"] = None
        if settings["expires_at"]:
            expiry = datetime.fromisoformat(settings["expires_at"].replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                raise ProbeError("expiry_timezone_required")
            settings["expires_timestamp"] = expiry.timestamp()
        key = config.get("distribution", "key", fallback="").strip()
        if not key:
            key = "gw-" + secrets.token_urlsafe(32)
            config.set("distribution", "key", key)
            with path.open("w", encoding="utf-8") as target:
                config.write(target)
        if any(character.isspace() for character in key) or key == original_key:
            raise ProbeError("distribution_key_invalid")
        settings["key"] = key
        settings["key_id"] = hashlib.sha256(key.encode()).hexdigest()
        return settings
    except (configparser.Error, ValueError, OSError):
        raise ProbeError("gateway_config_invalid") from None


class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS usage (
                    key_id TEXT PRIMARY KEY, accepted INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_utc TEXT NOT NULL, key_id TEXT,
                    method TEXT NOT NULL, endpoint TEXT NOT NULL,
                    http_status INTEGER, outcome TEXT NOT NULL,
                    elapsed_ms INTEGER, response_bytes INTEGER NOT NULL DEFAULT 0
                );
            """)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def begin(self, settings, authenticated, method, endpoint):
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            status, outcome = 200, "forwarding"
            key_id = settings["key_id"] if authenticated else None
            if not authenticated:
                status, outcome = 401, "invalid_key"
            elif not settings["enabled"]:
                status, outcome = 403, "key_disabled"
            elif (settings["expires_timestamp"] is not None
                  and time.time() >= settings["expires_timestamp"]):
                status, outcome = 403, "key_expired"
            else:
                connection.execute("INSERT OR IGNORE INTO usage VALUES (?, 0)", (key_id,))
                used = connection.execute("SELECT accepted FROM usage WHERE key_id = ?", (key_id,)).fetchone()[0]
                if settings["max_requests"] and used >= settings["max_requests"]:
                    status, outcome = 429, "quota_exhausted"
                else:
                    connection.execute("UPDATE usage SET accepted = accepted + 1 WHERE key_id = ?", (key_id,))
            cursor = connection.execute(
                "INSERT INTO requests (started_utc, key_id, method, endpoint, http_status, outcome) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (utc_now(), key_id, method, endpoint, status if status != 200 else None, outcome))
            return cursor.lastrowid, status, outcome

    def finish(self, request_id, status, outcome, elapsed_ms, response_bytes):
        with self.connect() as connection:
            connection.execute(
                "UPDATE requests SET http_status=?, outcome=?, elapsed_ms=?, response_bytes=? WHERE id=?",
                (status, outcome, elapsed_ms, response_bytes, request_id))

    def recent(self):
        with self.connect() as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(
                "SELECT id, started_utc, method, endpoint, http_status, outcome, elapsed_ms, response_bytes "
                "FROM requests ORDER BY id DESC LIMIT 100")]


def endpoint_label(path):
    route = path.split("?", 1)[0]
    if route == "/v1/workflows/run":
        return "workflow_run"
    if route.startswith("/v1/workflows/run/"):
        return "workflow_detail"
    if route == "/v1/chat-messages":
        return "chat_messages"
    if route.startswith("/v1/datasets"):
        return "knowledge"
    if route.startswith("/v1/files"):
        return "files"
    return "other"


def filtered_headers(headers, excluded):
    connection_tokens = set()
    for value in headers.get_all("Connection", []):
        connection_tokens.update(token.strip().lower() for token in value.split(","))
    return [(name, value) for name, value in headers.items()
            if name.lower() not in HOP_HEADERS | excluded | connection_tokens]


class GatewayServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, settings, store):
        self.settings = settings
        self.store = store
        super().__init__(address, GatewayHandler)

    def handle_error(self, request, client_address):
        print("gateway_request_error")


class GatewayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "DifyGateway"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def log_message(self, *args):
        pass

    def send_error(self, code, message=None, explain=None):
        self.send_json(code, "invalid_http_request")

    def send_json(self, status, code):
        payload = json.dumps({"code": code, "message": code, "status": status}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        if self.command != "HEAD":
            self.wfile.write(payload)
            self.wfile.flush()

    def read_body(self, target):
        lengths = self.headers.get_all("Content-Length", [])
        encodings = self.headers.get_all("Transfer-Encoding", [])
        limit = self.server.settings["max_body_bytes"]
        if len(lengths) > 1 or len(encodings) > 1 or (lengths and encodings):
            raise ProbeError("invalid_request_framing")
        total = 0
        if encodings:
            if encodings[0].lower().strip() != "chunked":
                raise ProbeError("unsupported_transfer_encoding")
            while True:
                line = self.rfile.readline(8193)
                if len(line) > 8192 or not line.endswith(b"\r\n"):
                    raise ProbeError("invalid_request_framing")
                try:
                    size = int(line.split(b";", 1)[0].strip(), 16)
                except ValueError:
                    raise ProbeError("invalid_request_framing") from None
                if size < 0:
                    raise ProbeError("invalid_request_framing")
                if size == 0:
                    trailer_bytes = 0
                    while True:
                        trailer = self.rfile.readline(8193)
                        trailer_bytes += len(trailer)
                        if not trailer.endswith(b"\r\n") or trailer_bytes > 65536:
                            raise ProbeError("invalid_request_framing")
                        if trailer == b"\r\n":
                            break
                    break
                if total + size > limit:
                    raise ProbeError("request_too_large")
                self.copy_exact(target, size)
                total += size
                if self.rfile.read(2) != b"\r\n":
                    raise ProbeError("invalid_request_framing")
        elif lengths:
            try:
                total = int(lengths[0])
            except ValueError:
                raise ProbeError("invalid_request_framing") from None
            if total < 0:
                raise ProbeError("invalid_request_framing")
            if total > limit:
                raise ProbeError("request_too_large")
            self.copy_exact(target, total)
        target.seek(0)
        return total

    def copy_exact(self, target, size):
        remaining = size
        while remaining:
            chunk = self.rfile.read(min(65536, remaining))
            if not chunk:
                raise ProbeError("incomplete_request")
            target.write(chunk)
            remaining -= len(chunk)

    def forward(self):
        self.close_connection = True
        started = time.monotonic()
        request_id = None
        response_started = False
        status = 502
        outcome = "upstream_error"
        sent_bytes = 0
        upstream_connection = None
        try:
            settings = self.server.settings
            authorizations = self.headers.get_all("Authorization", [])
            scheme, _, supplied = (authorizations[0] if len(authorizations) == 1 else "").partition(" ")
            authenticated = (scheme.lower() == "bearer" and
                             hmac.compare_digest(supplied.encode(), settings["key"].encode()))
            request_id, status, outcome = self.server.store.begin(
                settings, authenticated, self.command, endpoint_label(self.path))
            if status != 200:
                self.send_json(status, outcome)
                return
            if not (self.path == "/v1" or self.path.startswith("/v1/") or self.path.startswith("/v1?")):
                status, outcome = 404, "unknown_gateway_path"
                self.send_json(status, outcome)
                return
            parsed = urlsplit(settings["base"])
            upstream_path = parsed.path.rstrip("/") + self.path[len("/v1"):]
            if not upstream_path or upstream_path.startswith("?"):
                upstream_path = "/" + upstream_path
            connection_type = (http.client.HTTPSConnection if parsed.scheme == "https"
                               else http.client.HTTPConnection)
            with tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b") as body:
                size = self.read_body(body)
                upstream_connection = connection_type(parsed.hostname, parsed.port, timeout=settings["timeout"])
                upstream_connection.putrequest(self.command, upstream_path, skip_accept_encoding=True)
                for name, value in filtered_headers(self.headers, {"authorization", "host", "content-length", "expect"}):
                    upstream_connection.putheader(name, value)
                upstream_connection.putheader("Authorization", "Bearer " + settings["original_key"])
                if size or self.command in {"POST", "PUT", "PATCH"}:
                    upstream_connection.putheader("Content-Length", str(size))
                upstream_connection.putheader("Connection", "close")
                upstream_connection.endheaders()
                while True:
                    chunk = body.read(65536)
                    if not chunk:
                        break
                    upstream_connection.send(chunk)
                response = upstream_connection.getresponse()
                status = response.status
                has_body = self.command != "HEAD" and status not in {204, 304} and status >= 200
                self.send_response_only(status)
                for name, value in filtered_headers(response.headers, {"content-length"}):
                    self.send_header(name, value)
                if self.command == "HEAD" and response.getheader("Content-Length") is not None:
                    self.send_header("Content-Length", response.getheader("Content-Length"))
                if has_body:
                    self.send_header("Transfer-Encoding", "chunked")
                self.send_header("Connection", "close")
                self.end_headers()
                response_started = True
                if has_body:
                    while True:
                        chunk = response.read1(65536)
                        if not chunk:
                            break
                        self.wfile.write(format(len(chunk), "x").encode() + b"\r\n" + chunk + b"\r\n")
                        self.wfile.flush()
                        sent_bytes += len(chunk)
                    if response.length not in (None, 0):
                        raise ProbeError("incomplete_response")
                    self.wfile.write(b"0\r\n\r\n")
                    self.wfile.flush()
                outcome = "forwarded"
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            outcome = "connection_interrupted"
            if not response_started:
                status = 502
                try:
                    self.send_json(status, outcome)
                except OSError:
                    pass
        except Exception as error:
            outcome = error_category(error)
            if not response_started:
                if outcome == "request_too_large":
                    status = 413
                elif outcome in {"invalid_request_framing", "unsupported_transfer_encoding", "incomplete_request"}:
                    status = 400
                elif isinstance(error, sqlite3.Error):
                    status, outcome = 503, "log_storage_error"
                elif isinstance(error, (socket.timeout, TimeoutError)):
                    status = 504
                else:
                    status = 502
                try:
                    self.send_json(status, outcome)
                except OSError:
                    pass
        finally:
            if upstream_connection is not None:
                upstream_connection.close()
            if request_id is not None:
                try:
                    self.server.store.finish(request_id, status, outcome,
                                             round((time.monotonic() - started) * 1000), sent_bytes)
                except sqlite3.Error:
                    print("log_storage_error")

    do_GET = forward
    do_POST = forward
    do_PUT = forward
    do_PATCH = forward
    do_DELETE = forward
    do_HEAD = forward
    do_OPTIONS = forward


def main():
    parser = argparse.ArgumentParser(description="最简 Dify 分发网关")
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().with_suffix(".ini"))
    parser.add_argument("--logs", action="store_true", help="显示最近 100 条脱敏调用记录")
    args = parser.parse_args()
    settings = load_settings(args.config.resolve())
    store = Store(settings["database"])
    if args.logs:
        print(json.dumps(store.recent(), ensure_ascii=False, indent=2))
        return
    server = GatewayServer((settings["host"], settings["port"]), settings, store)
    print("网关已启动，端口：" + str(settings["port"]), flush=True)
    print("本机分发 URL：http://127.0.0.1:" + str(settings["port"]) + "/v1", flush=True)
    print("分发 Key：" + settings["key"], flush=True)
    print("其他内网机器请将 127.0.0.1 替换为这台机器的内网 IP。按 Ctrl+C 停止。", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("网关已停止。")
    except Exception as error:
        print("网关中止，诊断类别：" + error_category(error))
        raise SystemExit(2)
