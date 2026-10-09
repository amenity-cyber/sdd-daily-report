"""本机 Mock 联调入口：python web_server.py --port 8765。"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from shared.logger import get_logger
from shared.storage import ReportStorage
from web_backend.service import ReportService

PROJECT_ROOT = Path(__file__).resolve().parent
logger = get_logger("web_server")
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


def create_server(host: str, port: int, service: ReportService) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            logger.info(fmt % args)

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
            try:
                if path == "/api/health":
                    self.json_response(200, {"status": "ok", "mode": "mock"})
                elif path == "/api/reports":
                    self.json_response(200, {"reports": service.list_reports()})
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
            if urlsplit(self.path).path != "/api/reports":
                self.json_response(405, {"error": "此接口不支持该请求方法"})
                return
            # 同源页面生成请求；拒绝浏览器从其他站点发来的写操作。
            origin = self.headers.get("Origin")
            if origin and origin != f"http://{self.headers.get('Host')}":
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
            try:
                self.json_response(200, {"report": service.create_report()})
            except Exception:
                logger.exception("本地 Mock 日报生成失败")
                self.json_response(500, {"error": "生成失败，请稍后重试"})

        def unsupported_method(self):
            self.json_response(405, {"error": "此接口不支持该请求方法"})

        do_PUT = unsupported_method
        do_DELETE = unsupported_method
        do_PATCH = unsupported_method
        do_OPTIONS = unsupported_method
        do_HEAD = unsupported_method

    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(description="智能日报本地 Mock 联调服务")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", type=Path, default=PROJECT_ROOT / "data" / "web_reports.db")
    args = parser.parse_args()
    server = create_server("127.0.0.1", args.port, ReportService(ReportStorage(args.db)))
    print(f"本地 Mock 日报服务：http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
