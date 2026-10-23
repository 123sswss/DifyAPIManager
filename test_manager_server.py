import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

import manager_server as manager
import dify_gateway as gateway


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.store = manager.AuthStore(self.root / "accounts.sqlite3")
        self.store.create_user("admin-one", "superuser", "Admin test password 123")
        self.store.create_user("admin-two", "superuser")
        self.store.create_user("ordinary-user", password="Member test password 123")
        self.dist = self.root / "dist"
        self.dist.mkdir()
        (self.dist / "index.html").write_text("<h1>login</h1>", encoding="utf-8")
        self.server = manager.ManagerServer(("127.0.0.1", 0), self.store,
                                            self.root / "gateway.sqlite3", self.dist)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def call(self, path, body=None, cookie=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        request_headers = {"Content-Type": "application/json", "X-Requested-With": "DifyManager"}
        if cookie:
            request_headers["Cookie"] = cookie
        request_headers.update(headers or {})
        try:
            connection.request("POST" if body is not None else "GET", path,
                               body=json.dumps(body).encode() if body is not None else None,
                               headers=request_headers)
            response = connection.getresponse()
            payload = response.read()
            data = json.loads(payload) if "application/json" in response.getheader("Content-Type", "") else payload
            return response.status, data, response.headers
        finally:
            connection.close()

    def login(self, member=False):
        name, password = (("ordinary-user", "Member test password 123") if member
                          else ("admin-one", "Admin test password 123"))
        status, body, headers = self.call("/api/auth/login", {"username": name, "password": password})
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0], body

    def test_admin_login_cookie_session_and_logout(self):
        cookie, login = self.login()
        status, result, headers = self.call("/api/auth/me", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertEqual(result, login)
        self.assertEqual(result["user"]["role"], "superuser")
        self.assertEqual(headers["Cache-Control"], "no-store")
        status, users, _ = self.call("/api/admin/users", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertEqual(len(users["users"]), 3)
        self.assertNotIn("password_hash", json.dumps(users))
        self.assertNotIn("salt", json.dumps(users))
        self.assertEqual(self.call("/api/auth/logout", {}, cookie)[0], 403)
        self.assertEqual(self.call("/api/auth/logout", {}, cookie,
                                   {"X-CSRF-Token": login["csrf"]})[0], 200)
        self.assertEqual(self.call("/api/auth/me", cookie=cookie)[0], 401)

    def test_member_cannot_read_any_admin_data(self):
        cookie, result = self.login(member=True)
        self.assertEqual(result["user"]["role"], "member")
        self.assertEqual(self.call("/api/admin/users", cookie=cookie)[0], 403)
        self.assertEqual(self.call("/api/admin/logs", cookie=cookie)[0], 403)
        self.assertEqual(self.call("/api/admin/users")[0], 401)
        self.assertEqual(self.call("/api/admin/logs")[0], 401)

    def test_credentials_pending_unknown_and_disabled(self):
        for name, password in (("admin-one", "wrong"), ("unknown", "wrong"), ("admin-two", "wrong")):
            status, result, _ = self.call("/api/auth/login", {"username": name, "password": password})
            self.assertEqual((status, result["message"]), (401, "账号或密码错误"))
        cookie, _ = self.login()
        with self.store.connect() as db:
            db.execute("UPDATE users SET enabled=0 WHERE username='admin-one'")
        self.assertEqual(self.call("/api/auth/me", cookie=cookie)[0], 401)

    def test_password_hash_and_reset_revoke_sessions(self):
        cookie, _ = self.login()
        self.store.set_password("admin-one", "Replacement test password 123")
        self.assertEqual(self.call("/api/auth/me", cookie=cookie)[0], 401)
        self.assertEqual(self.call("/api/auth/login", {"username": "admin-one", "password": "Admin test password 123"})[0], 401)
        status, _, headers = self.call("/api/auth/login", {"username": "admin-one", "password": "Replacement test password 123"})
        self.assertEqual(status, 200)
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM users WHERE username='admin-one'").fetchone()
            self.assertNotEqual(row["password_hash"], "Replacement test password 123")
            self.assertEqual(len(row["salt"]), 32)
            session = db.execute("SELECT token_hash FROM sessions").fetchone()
            self.assertNotIn(session[0], headers["Set-Cookie"])

    def test_rate_limit_persists_across_store_instances(self):
        for _ in range(10):
            self.store.reserve_attempt("someone", "127.0.0.1")
        another_store = manager.AuthStore(self.root / "accounts.sqlite3")
        with self.assertRaises(manager.ApiError) as error:
            another_store.reserve_attempt("someone", "127.0.0.1")
        self.assertEqual(error.exception.status, 429)
        with self.store.connect() as db:
            db.execute("UPDATE login_attempts SET started=?", (time.time() - 301,))
        another_store.reserve_attempt("someone", "127.0.0.1")

    def test_expired_sessions(self):
        cookie, _ = self.login()
        with self.store.connect() as db:
            db.execute("UPDATE sessions SET expires=?", (time.time() - 1,))
        self.assertEqual(self.call("/api/auth/me", cookie=cookie)[0], 401)

    def test_bootstrap_idempotent_and_two_admin_limit(self):
        self.assertFalse(self.store.create_user("ADMIN-ONE", "superuser"))
        with self.assertRaises(ValueError):
            self.store.create_user("third-admin", "superuser")
        with self.assertRaises(ValueError):
            self.store.set_password("admin-two", "short")
        self.store.set_password("admin-two", "Abc123")
        self.assertEqual(self.call("/api/auth/login", {"username": "admin-two", "password": "Abc123"})[0], 200)

    def test_cross_origin_and_invalid_payload_rejected(self):
        body = {"username": "admin-one", "password": "Admin test password 123"}
        self.assertEqual(self.call("/api/auth/login", body, headers={"Origin": "https://elsewhere.example"})[0], 403)
        self.assertEqual(self.call("/api/auth/login", body, headers={"X-Requested-With": ""})[0], 403)
        self.assertEqual(self.call("/api/auth/login", ["invalid"])[0], 400)
        self.assertEqual(self.call("/api/auth/login", {"username": {}, "password": []})[0], 400)

    def test_same_origin_with_proxy_preserved_host(self):
        body = {"username": "admin-one", "password": "Admin test password 123"}
        status, _, _ = self.call("/api/auth/login", body, headers={
            "Host": "127.0.0.1:5174", "Origin": "http://127.0.0.1:5174",
            "Sec-Fetch-Site": "same-origin",
        })
        self.assertEqual(status, 200)
        status, _, _ = self.call("/api/auth/login", body, headers={
            "Host": "127.0.0.1:5174", "Origin": "https://elsewhere.example",
            "Sec-Fetch-Site": "cross-site",
        })
        self.assertEqual(status, 403)

    def test_static_files_do_not_expose_database(self):
        self.assertEqual(self.call("/")[0], 200)
        for path in ("/../accounts.sqlite3", "/%2e%2e/accounts.sqlite3", "/manager_server.py"):
            self.assertEqual(self.call(path)[0], 404)

    def test_gateway_metadata_is_read_only_and_filtered(self):
        cookie, _ = self.login()
        status, data, _ = self.call("/api/admin/logs", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertFalse(data["available"])
        self.assertFalse(self.server.gateway_database.exists())
        store = gateway.Store(self.server.gateway_database)
        with store.connect() as db:
            for status, outcome in ((200, "forwarded"), (403, "invalid_key")):
                db.execute("INSERT INTO requests (started_utc, method, endpoint, http_status, outcome, elapsed_ms) VALUES (?, 'POST', 'workflow_run', ?, ?, 120)",
                           (manager.datetime.now(manager.timezone.utc).isoformat(), status, outcome))
        status, data, _ = self.call("/api/admin/logs?days=today&status=success", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["summary"]["requests"], 2)
        self.assertEqual(data["summary"]["completion_rate"], 50)
        self.assertEqual(self.call("/api/admin/logs?days=invalid", cookie=cookie)[0], 400)

    def test_secure_cookie_option(self):
        self.server.secure_cookie = True
        _, _, headers = self.call("/api/auth/login", {"username": "admin-one", "password": "Admin test password 123"})
        self.assertIn("; Secure", headers["Set-Cookie"])


if __name__ == "__main__":
    unittest.main()
