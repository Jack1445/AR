"""Loopback-only AR website with a Feishu sync button."""

from __future__ import annotations

import json
import mimetypes
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from build_web import DATA, PUBLIC, TABLES, build_snapshot, read_json
from ai_settings import fetch_models, read_settings, save_settings
from match_engine import evaluate_item, public_state, tag_item, tag_plan
from sync import sync_from_saved_credentials


HOST = "127.0.0.1"
PORT = 38479
SYNC_LOCK = threading.Lock()
ASSETS = {"index.html", "styles.css", "theme.css", "app.js", "match.js", "data.js", "favicon.svg"}
TABLE_IDS = {table["id"] for table in TABLES}


class Handler(BaseHTTPRequestHandler):
    def _allowed_host(self) -> bool:
        return self.headers.get("Host") == f"{HOST}:{self.server.server_port}" and self.headers.get("Sec-Fetch-Site") in {None, "none", "same-origin"}

    def _headers(self, status: int, content_type: str, size: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()

    def _bytes(self, status: int, body: bytes, content_type: str = "text/plain; charset=utf-8") -> None:
        try:
            self._headers(status, content_type, len(body))
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # The browser may cancel a long AI request while the server finishes it.
            pass

    def _json(self, status: int, value: dict) -> None:
        self._bytes(status, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _file(self, path: Path, content_type: str | None = None) -> None:
        if not path.is_file():
            self._bytes(404, b"Not found")
            return
        content_type = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self._headers(200, content_type, path.stat().st_size)
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                self.wfile.write(chunk)

    def do_GET(self) -> None:
        if not self._allowed_host():
            self._bytes(403, b"Forbidden")
            return
        path = urllib.parse.unquote(urllib.parse.urlparse(self.path).path)
        if path == "/health":
            self._json(200, {"ok": True})
            return
        if path == "/api/ai-config":
            try:
                self._json(200, read_settings())
            except Exception:
                self._json(500, {"error": "无法读取本地 AI 设置"})
            return
        if path == "/api/match-state":
            try:
                self._json(200, public_state())
            except Exception:
                self._json(500, {"error": "无法读取本地匹配记录"})
            return
        asset = path.lstrip("/") or "index.html"
        if "/" not in asset and asset in ASSETS:
            self._file(PUBLIC / asset)
            return
        if path.startswith("/downloads/"):
            parts = Path(path.lstrip("/")).parts
            if len(parts) >= 4 and parts[1] in TABLE_IDS:
                table_id = parts[1]
                relative = Path(*parts[2:])
                folder = DATA / table_id
                target = (folder / relative).resolve()
                index = read_json(folder / "attachments.json", [])
                allowed = {str(Path(item.get("file", "")).as_posix()) for item in index}
                if target.is_relative_to(folder.resolve()) and relative.as_posix() in allowed:
                    self._file(target)
                    return
        self._bytes(404, b"Not found")

    def do_POST(self) -> None:
        if not self._allowed_host() or self.headers.get("Origin") != f"http://{HOST}:{self.server.server_port}":
            self._bytes(403, b"Forbidden")
            return
        if self.path in {"/api/match-tag", "/api/match-tag-plan", "/api/match-evaluate"}:
            if self.headers.get("X-AR-Match") != "1" or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                self._bytes(403, b"Forbidden")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if length < 1 or length > 160000:
                self._json(400, {"error": "匹配请求内容无效"})
                return
            try:
                payload = json.loads(self.rfile.read(length))
                result = tag_plan(payload) if self.path == "/api/match-tag-plan" else tag_item(payload) if self.path == "/api/match-tag" else evaluate_item(payload)
                self._json(200, result)
            except (ValueError, json.JSONDecodeError) as error:
                self._json(400, {"error": str(error)})
            except RuntimeError as error:
                self._json(502, {"error": str(error)})
            except Exception:
                self._json(500, {"error": "AI 处理失败，请检查本地服务与模型设置"})
            return
        if self.path == "/api/ai-config" or self.path == "/api/ai-models":
            if self.headers.get("X-AR-Config") != "1":
                self._bytes(403, b"Forbidden")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if self.path == "/api/ai-config":
                if length < 1 or length > 8192 or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    self._json(400, {"error": "设置内容格式无效"})
                    return
                try:
                    payload = json.loads(self.rfile.read(length))
                    self._json(200, save_settings(payload))
                except (ValueError, json.JSONDecodeError) as error:
                    self._json(400, {"error": str(error)})
                except Exception:
                    self._json(500, {"error": "无法保存 AI 设置，请检查本机凭据管理器"})
                return
            if length != 0:
                self._json(400, {"error": "获取模型列表不需要请求内容"})
                return
            try:
                self._json(200, fetch_models())
            except (ValueError, RuntimeError) as error:
                self._json(400, {"error": str(error)})
            except Exception:
                self._json(500, {"error": "无法获取模型列表"})
            return
        if self.path != "/api/sync" or self.headers.get("X-AR-Sync") != "1":
            self._bytes(403, b"Forbidden")
            return
        if self.headers.get("Content-Length", "0") != "0":
            self._bytes(400, b"Unexpected request body")
            return
        if not SYNC_LOCK.acquire(blocking=False):
            self._json(409, {"error": "正在检查飞书更新，请稍候。"})
            return
        try:
            self._json(200, sync_from_saved_credentials())
        except Exception as error:
            self._json(500, {"error": str(error)})
        finally:
            SYNC_LOCK.release()

    def log_message(self, format: str, *args) -> None:
        # Access logs could contain local attachment filenames or record IDs.
        pass


def main() -> None:
    if not (PUBLIC / "data.js").is_file():
        build_snapshot()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    print(f"AR 本地网页：http://{HOST}:{PORT}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
