"""本机日报联调入口：python web_server.py --port 8765（可选 --mock）。"""
from __future__ import annotations

import argparse
import base64
import binascii
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from shared.logger import get_logger
from shared.storage import ReportStorage
from web_backend.service import ReportService
from web_backend.real_adapter import RealExternalAdapter

PROJECT_ROOT = Path(__file__).resolve().parent
logger = get_logger("web_server")
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


def create_server(
    host: str,
    port: int,
    service: ReportService,
    *,
    auth_user: str | None = None,
    auth_password: str | None = None,
) -> ThreadingHTTPServer:
    auth_user = os.environ.get("WEB_AUTH_USER", "") if auth_user is None else auth_user
    auth_password = os.environ.get("WEB_AUTH_PASSWORD", "") if auth_password is None else auth_password
    if bool(auth_user) != bool(auth_password):
        raise ValueError("WEB_AUTH_USER 和 WEB_AUTH_PASSWORD 必须同时配置")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            logger.info(fmt % args)

        def is_authorized(self) -> bool:
            if not auth_user:
                return True
            scheme, _, encoded = (self.headers.get("Authorization") or "").partition(" ")
            if scheme.lower() != "basic" or not encoded:
                return False
            try:
                username, password = base64.b64decode(encoded, validate=True).decode("utf-8").split(":", 1)
            except (binascii.Error, UnicodeDecodeError, ValueError):
                return False
            return hmac.compare_digest(username, auth_user) and hmac.compare_digest(password, auth_password)

        def require_auth(self) -> bool:
            if self.is_authorized():
                return True
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="Smart Daily Report", charset="UTF-8"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False

        def respond(self, status: int, body: bytes, content_type: str):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def json_response(self, status: int, payload: dict):
            self.respond(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/healthz":
                self.respond(200, b"ok", "text/plain; charset=utf-8")
                return
            if not self.require_auth():
                return
            try:
                if path == "/api/health":
                    self.json_response(200, {
                        "status": "ok", "mode": service.mode,
                        "source": service.source_label,
                        "sources": getattr(service.adapter, "sources", {}),
                    })
                elif path == "/api/reports":
                    self.json_response(200, {"reports": service.list_reports()})
                elif path == "/api/analytics":
                    self.json_response(200, {"analytics": service.analytics()})
                elif path.startswith("/api/reports/"):
                    report = service.get_report(path.removeprefix("/api/reports/"))
                    self.json_response(200, {"report": report}) if report else self.json_response(404, {"error": "日报不存在"})
                elif path in STATIC_FILES:
                    filename, content_type = STATIC_FILES[path]
                    target = PROJECT_ROOT / "web_ui" / filename
                    if target.is_file():
                        self.respond(200, target.read_bytes(), content_type)
                    else:
                        self.json_response(404, {"error": "页面资源不存在"})
                else:
                    self.json_response(404, {"error": "请求路径不存在"})
            except Exception:
                logger.exception("读取日报或静态资源失败")
                self.json_response(500, {"error": "读取失败，请稍后重试"})

        def do_POST(self):
            if not self.require_auth():
                return
            path = urlsplit(self.path).path
            email_prefix = "/api/reports/"
            is_email = path.startswith(email_prefix) and path.endswith("/email")
            if path != "/api/reports" and not is_email:
                self.json_response(405, {"error": "此接口不支持该请求方法"})
                return
            # 同源页面生成请求；拒绝浏览器从其他站点发来的写操作。
            port = self.server.server_port
            allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
            render_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip().lower()
            if render_host:
                allowed_hosts.add(render_host)
            public_url = os.environ.get("PUBLIC_BASE_URL", "").strip()
            if public_url:
                public_host = urlsplit(public_url).netloc.lower()
                if public_host:
                    allowed_hosts.add(public_host)
            host = (self.headers.get("Host") or "").lower()
            origin = (self.headers.get("Origin") or "").lower()
            allowed_origins = {f"http://{value}" for value in allowed_hosts}
            if render_host:
                allowed_origins.add(f"https://{render_host}")
            if public_url:
                allowed_origins.add(public_url.rstrip("/").lower())
            if host not in allowed_hosts or (origin and origin not in allowed_origins):
                self.json_response(403, {"error": "仅支持同源请求"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > 65536 or self.headers.get("Transfer-Encoding"):
                    raise ValueError("invalid length")
                body = self.rfile.read(length)
                if body and json.loads(body.decode("utf-8")) != {}:
                    raise ValueError("expected empty object")
            except (ValueError, UnicodeDecodeError):
                self.json_response(400, {"error": "请求体需为空或空 JSON 对象"})
                return
            if is_email:
                report_id = path[len(email_prefix):-len("/email")].strip("/")
                try:
                    if service.send_email(report_id):
                        self.json_response(200, {"sent": True})
                    else:
                        self.json_response(502, {"error": "邮件发送失败，请检查邮件配置和服务日志"})
                except FileExistsError as error:
                    self.json_response(409, {"error": str(error)})
                except RuntimeError as error:
                    self.json_response(409, {"error": str(error)})
                except LookupError:
                    self.json_response(404, {"error": "日报不存在"})
                except Exception:
                    logger.exception("发送日报邮件失败")
                    self.json_response(502, {"error": "邮件发送失败，请检查邮件配置和服务日志"})
                return
            try:
                self.json_response(200, {"report": service.create_report()})
            except Exception:
                logger.exception("日报生成失败")
                self.json_response(500, {"error": "生成失败，请稍后重试"})

        def unsupported_method(self):
            if not self.require_auth():
                return
            self.json_response(405, {"error": "此接口不支持该请求方法"})

        do_PUT = unsupported_method
        do_DELETE = unsupported_method
        do_PATCH = unsupported_method
        do_OPTIONS = unsupported_method
        do_HEAD = unsupported_method

    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(description="智能日报本地联调服务")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8765")))
    parser.add_argument("--db", type=Path, default=Path(os.environ.get("DATABASE_PATH", str(PROJECT_ROOT / "data" / "web_reports.db"))))
    parser.add_argument("--mock", action="store_true", help="使用演示数据，不连接真实服务或发送邮件")
    args = parser.parse_args()
    if os.environ.get("APP_ENV") == "production" and not (os.environ.get("WEB_AUTH_USER") and os.environ.get("WEB_AUTH_PASSWORD")):
        parser.error("生产环境必须设置 WEB_AUTH_USER 和 WEB_AUTH_PASSWORD")
    adapter = None if args.mock else RealExternalAdapter(PROJECT_ROOT / "config.yaml", PROJECT_ROOT / ".env")
    service = ReportService(ReportStorage(args.db), adapter)
    server = create_server(args.host, args.port, service)
    display_host = "127.0.0.1" if args.host == "0.0.0.0" else args.host
    print(f"{'Mock ' if args.mock else ''}日报服务：http://{display_host}:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
