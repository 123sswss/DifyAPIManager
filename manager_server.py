"""Local management UI and cookie-based authentication, independent of Dify."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import getpass
import hashlib
import hmac
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import secrets
import sqlite3
import time
from urllib.parse import parse_qs, unquote, urlsplit

ROOT = Path(__file__).resolve().parent
ITERATIONS = 600_000
SESSION_SECONDS = 8 * 3600
COOKIE_NAME = "dify_manager_session"
SUPERUSERS = ("crescent039", "123sswss")


class ApiError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


def password_digest(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS).hex()


def validate_password(password):
    if not isinstance(password, str) or not 6 <= len(password) <= 256:
        raise ValueError("密码长度需要为 6–256 个字符")


class AuthStore:
    def __init__(self, path):
        self.path = str(path)
        # Used for unknown and unconfigured accounts to avoid a fast username oracle.
        self.dummy_salt = secrets.token_bytes(16)
        self.dummy_digest = password_digest(secrets.token_urlsafe(32), self.dummy_salt)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    role TEXT NOT NULL CHECK(role IN ('superuser', 'member')),
                    salt TEXT, password_hash TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    csrf TEXT NOT NULL, expires REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS login_attempts (
                    scope TEXT PRIMARY KEY, count INTEGER NOT NULL, started REAL NOT NULL
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def create_user(self, username, role="member", password=None):
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,48}", username):
            raise ValueError("账号名须为 3–48 位字母、数字、下划线、点或短横线")
        if role not in {"superuser", "member"}:
            raise ValueError("无效角色")
        salt, digest = None, None
        if password is not None:
            validate_password(password)
            salt = secrets.token_bytes(16)
            digest = password_digest(password, salt)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT role FROM users WHERE username=?", (username,)).fetchone()
            if existing:
                if existing["role"] != role:
                    raise ValueError("账号已存在且角色不同")
                return False
            if role == "superuser" and db.execute(
                    "SELECT COUNT(*) FROM users WHERE role='superuser'").fetchone()[0] >= 2:
                raise ValueError("当前最多允许两个超级用户")
            db.execute("INSERT INTO users (username, role, salt, password_hash, created_utc) VALUES (?, ?, ?, ?, ?)",
                       (username, role, salt.hex() if salt else None, digest,
                        datetime.now(timezone.utc).isoformat()))
        return True

    def set_password(self, username, password):
        validate_password(password)
        salt = secrets.token_bytes(16)
        digest = password_digest(password, salt)
        with self.connect() as db:
            user = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
            if not user:
                raise ValueError("账号不存在")
            db.execute("UPDATE users SET salt=?, password_hash=? WHERE id=?", (salt.hex(), digest, user["id"]))
            db.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
            db.execute("DELETE FROM login_attempts WHERE scope=?", ("user:" + username.lower(),))

    def reserve_attempt(self, username, ip):
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM login_attempts WHERE started < ?", (now - 300,))
            for scope, limit in (("user:" + username.lower(), 10), ("ip:" + ip, 30)):
                row = db.execute("SELECT count FROM login_attempts WHERE scope=?", (scope,)).fetchone()
                if row and row[0] >= limit:
                    raise ApiError(429, "login_throttled", "尝试次数过多，请 5 分钟后重试")
            for scope in ("user:" + username.lower(), "ip:" + ip):
                db.execute("INSERT INTO login_attempts VALUES (?, 1, ?) ON CONFLICT(scope) DO UPDATE SET count=count+1",
                           (scope, now))

    def login(self, username, password, ip):
        self.reserve_attempt(username, ip)
        with self.connect() as db:
            user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        salt = bytes.fromhex(user["salt"]) if user and user["salt"] else self.dummy_salt
        digest = user["password_hash"] if user and user["password_hash"] else self.dummy_digest
        valid = hmac.compare_digest(password_digest(password, salt), digest)
        if not valid or not user or not user["enabled"] or not user["password_hash"]:
            raise ApiError(401, "invalid_credentials", "账号或密码错误")
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE expires <= ?", (time.time(),))
            db.execute("DELETE FROM login_attempts WHERE scope=?", ("user:" + username.lower(),))
            db.execute("INSERT INTO sessions VALUES (?, ?, ?, ?)",
                       (hashlib.sha256(token.encode()).hexdigest(), user["id"], csrf, time.time() + SESSION_SECONDS))
        return token, {"user": {"username": user["username"], "role": user["role"]}, "csrf": csrf}

    def session(self, token):
        if not token or len(token) > 128:
            return None
        with self.connect() as db:
            row = db.execute("""SELECT u.id, u.username, u.role, s.csrf FROM sessions s
                JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>? AND u.enabled=1""",
                (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
            return dict(row) if row else None

    def logout(self, token):
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))

    def users(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("""SELECT username, role, enabled,
                password_hash IS NOT NULL AS password_ready, created_utc FROM users ORDER BY id""")]


def gateway_data(path, days="today", status="all"):
    """Read only the existing gateway's sanitized metadata; never create its DB."""
    if days not in {"today", "week", "month"} or status not in {"all", "success", "client", "server"}:
        raise ApiError(400, "invalid_filter", "筛选条件无效")
    if not path.is_file():
        return {"available": False, "records": [], "total": None, "summary": None}
    start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    start -= timedelta(days={"today": 0, "week": 6, "month": 29}[days])
    where = "started_utc >= ?"
    params = [start.astimezone(timezone.utc).isoformat()]
    if status != "all":
        where += " AND http_status >= ? AND http_status < ?"
        low = {"success": 200, "client": 400, "server": 500}[status]
        params.extend((low, low + 100))
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=3)
    try:
        db.row_factory = sqlite3.Row
        total = db.execute("SELECT COUNT(*) FROM requests WHERE " + where, params).fetchone()[0]
        rows = db.execute("SELECT id, started_utc, method, endpoint, http_status, outcome, elapsed_ms "
                          "FROM requests WHERE " + where + " ORDER BY id DESC LIMIT 100", params)
        records = [dict(row) for row in rows]
        today = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        count, completed, average = db.execute("""SELECT COUNT(*), SUM(outcome='forwarded'), AVG(elapsed_ms)
            FROM requests WHERE started_utc>=?""", (today.astimezone(timezone.utc).isoformat(),)).fetchone()
        return {"available": True, "records": records, "total": total,
                "summary": {"requests": count, "completion_rate": round(completed / count * 100, 1) if count else None,
                            "average_ms": round(average) if average is not None else None}}
    finally:
        db.close()


class ManagerServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, store, gateway_database=None, dist=None, secure_cookie=False):
        self.store = store
        self.gateway_database = Path(gateway_database or ROOT / "gateway.sqlite3")
        self.dist = Path(dist or ROOT / "frontend" / "dist").resolve()
        self.secure_cookie = secure_cookie
        super().__init__(address, ManagerHandler)

    def handle_error(self, request, client_address):
        print("manager_request_error")


class ManagerHandler(BaseHTTPRequestHandler):
    server_version = "DifyManager"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *args):
        pass

    def send_error(self, code, message=None, explain=None):
        self.json_response(code, {"message": "请求无效"})

    def respond(self, status, body, content_type="application/json; charset=utf-8", cookie=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def json_response(self, status, body, cookie=None):
        self.respond(status, json.dumps(body, ensure_ascii=False).encode(), cookie=cookie)

    def cookie(self, token, max_age=SESSION_SECONDS):
        value = f"{COOKIE_NAME}={token}; Path=/api; HttpOnly; SameSite=Strict; Max-Age={max_age}"
        return value + ("; Secure" if self.server.secure_cookie else "")

    def token(self):
        try:
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            return cookies[COOKIE_NAME].value if COOKIE_NAME in cookies else ""
        except CookieError:
            return ""

    def require_user(self, admin=False):
        user = self.server.store.session(self.token())
        if user is None:
            raise ApiError(401, "login_required", "请先登录")
        if admin and user["role"] != "superuser":
            raise ApiError(403, "admin_required", "仅超级用户可访问")
        return user

    def read_json(self):
        # Custom header + JSON prevents cross-origin form submission, including login CSRF.
        if self.headers.get("X-Requested-With") != "DifyManager":
            raise ApiError(403, "invalid_origin", "请求来源无效")
        origin = self.headers.get("Origin")
        if origin and urlsplit(origin).netloc != self.headers.get("Host"):
            raise ApiError(403, "invalid_origin", "请求来源无效")
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise ApiError(403, "invalid_origin", "请求来源无效")
        if self.headers.get_content_type() != "application/json" or self.headers.get("Transfer-Encoding"):
            raise ApiError(400, "invalid_request", "请求格式无效")
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not lengths[0].isdigit() or not 0 < int(lengths[0]) <= 4096:
            raise ApiError(400, "invalid_request", "请求大小无效")
        try:
            value = json.loads(self.rfile.read(int(lengths[0])))
        except (ValueError, UnicodeError):
            raise ApiError(400, "invalid_request", "请求格式无效") from None
        if not isinstance(value, dict):
            raise ApiError(400, "invalid_request", "请求格式无效")
        return value

    def dispatch(self):
        parsed = urlsplit(self.path)
        path = parsed.path
        if self.command == "POST":
            body = self.read_json()
            if path == "/api/auth/login":
                username, password = body.get("username"), body.get("password")
                if (not isinstance(username, str) or not isinstance(password, str)
                        or not 1 <= len(username) <= 48 or not 1 <= len(password) <= 256):
                    raise ApiError(400, "invalid_credentials_format", "请输入账号和密码")
                token, result = self.server.store.login(username.strip(), password, self.client_address[0])
                self.json_response(200, result, self.cookie(token))
                return
            user = self.require_user()
            if not hmac.compare_digest(self.headers.get("X-CSRF-Token", "").encode(), user["csrf"].encode()):
                raise ApiError(403, "invalid_csrf", "请求已失效，请刷新页面")
            if path == "/api/auth/logout":
                self.server.store.logout(self.token())
                self.json_response(200, {"ok": True}, self.cookie("", 0))
                return
        elif self.command == "GET":
            if path == "/api/auth/me":
                user = self.require_user()
                self.json_response(200, {"user": {"username": user["username"], "role": user["role"]}, "csrf": user["csrf"]})
                return
            if path.startswith("/api/admin/"):
                self.require_user(admin=True)
                if path == "/api/admin/users":
                    self.json_response(200, {"users": self.server.store.users()})
                    return
                if path == "/api/admin/logs":
                    query = parse_qs(parsed.query)
                    self.json_response(200, gateway_data(self.server.gateway_database,
                                       query.get("days", ["today"])[0], query.get("status", ["all"])[0]))
                    return
            if not path.startswith("/api/"):
                requested = (self.server.dist / unquote(path).lstrip("/")).resolve() if path != "/" else self.server.dist / "index.html"
                if not requested.is_relative_to(self.server.dist) or not requested.is_file():
                    raise ApiError(404, "not_found", "页面不存在，请先构建前端")
                self.respond(200, requested.read_bytes(), mimetypes.guess_type(str(requested))[0] or "application/octet-stream")
                return
        raise ApiError(404, "not_found", "接口不存在")

    def handle_request(self):
        try:
            self.dispatch()
        except ApiError as error:
            self.json_response(error.status, {"code": error.code, "message": error.message})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except sqlite3.Error:
            self.json_response(503, {"message": "数据存储暂不可用"})

    do_GET = handle_request
    do_POST = handle_request


def read_password():
    password = getpass.getpass("设置密码（至少 6 个字符）：")
    validate_password(password)
    if not hmac.compare_digest(password.encode(), getpass.getpass("再次输入密码：").encode()):
        raise ValueError("两次密码不一致")
    return password


def main():
    parser = argparse.ArgumentParser(description="Dify 管理平台与账号初始化")
    parser.add_argument("--database", type=Path, default=ROOT / "manager.sqlite3")
    parser.add_argument("--gateway-database", type=Path, default=ROOT / "gateway.sqlite3")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--secure-cookie", action="store_true", help="HTTPS 部署时启用")
    commands = parser.add_mutually_exclusive_group()
    commands.add_argument("--init-superusers", action="store_true")
    commands.add_argument("--set-password", metavar="USERNAME")
    commands.add_argument("--create-user", metavar="USERNAME")
    args = parser.parse_args()
    store = AuthStore(args.database)
    if args.init_superusers:
        for username in SUPERUSERS:
            created = store.create_user(username, "superuser")
            print(username + ("：已创建，待设置密码" if created else "：已存在，保留原密码"))
        return
    if args.set_password:
        store.set_password(args.set_password, read_password())
        print("密码已设置，旧登录会话已失效。")
        return
    if args.create_user:
        if not store.create_user(args.create_user, password=read_password()):
            raise ValueError("账号已存在")
        print("普通用户已创建。")
        return
    server = ManagerServer((args.host, args.port), store, args.gateway_database, secure_cookie=args.secure_cookie)
    print(f"管理平台：http://{args.host}:{args.port}，按 Ctrl+C 停止。", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("管理服务已停止。")
    except (ValueError, sqlite3.Error) as error:
        print(str(error) if isinstance(error, ValueError) else "账号数据库访问失败")
        raise SystemExit(2)
