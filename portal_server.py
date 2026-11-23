"""Separate candidate/alumni HTTP service. No admin or AI configuration routes."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import io
import json
import mimetypes
import os
import re
import secrets
import urllib.error
import tempfile
import threading
import time
import urllib.parse
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from xml.etree import ElementTree

from ar import FeishuError
import mp_oauth
from candidate_ai import chat_reply, parse_resume
from portal_data import (
    MpLoginError, _client, _field, account_data, ensure_schema, feedback,
    list_jobs, list_recommendations, login, login_with_mp, register, save_alumni_company,
    save_candidate, save_job, remove_candidate_attachment,
)


ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "portal"
HOST = os.environ.get("AR_PORTAL_BIND", "127.0.0.1")
PORT = int(os.environ.get("AR_PORTAL_PORT", "38480"))
ORIGIN = os.environ.get("AR_PORTAL_ORIGIN", f"http://127.0.0.1:{PORT}").rstrip("/")
ORIGIN_HOST = urllib.parse.urlparse(ORIGIN).netloc
SESSIONS: dict[str, tuple[dict, float]] = {}
FAILED_LOGINS: dict[str, list[float]] = {}
SESSION_LOCK = threading.RLock()
SESSION_TTL = 12 * 60 * 60
ASSETS = {"index.html", "portal.css", "portal.js", "brand-mark.svg", "talent-wordmark.svg"}


def oauth_state(role: str) -> str:
    payload = f"{role}.{int(time.time())}.{secrets.token_urlsafe(24)}"
    signature = hmac.new(mp_oauth.settings()[2].encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def oauth_role(state: str) -> str | None:
    try:
        role, created, nonce, signature = state.split(".")
        payload = f"{role}.{created}.{nonce}"
        expected = hmac.new(mp_oauth.settings()[2].encode(), payload.encode(), hashlib.sha256).hexdigest()
        if role in {"candidate", "alumni"} and 0 <= time.time() - int(created) <= 600 and hmac.compare_digest(signature, expected):
            return role
    except (ValueError, TypeError):
        pass
    return None


def resume_response(content: bytes, filename: str, download: bool) -> tuple[bytes, str, str]:
    """Return browser-safe preview bytes or the original file for download."""
    if download:
        return content, "application/octet-stream", "attachment"
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return content, "application/pdf", "inline"
    if suffix in {".png", ".jpg", ".jpeg"}:
        return content, "image/png" if suffix == ".png" else "image/jpeg", "inline"
    if suffix == ".txt":
        return content.decode("utf-8-sig", errors="replace").encode("utf-8"), "text/plain; charset=utf-8", "inline"
    if suffix == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                info = archive.getinfo("word/document.xml")
                if info.file_size > 5_000_000:
                    raise ValueError("文档过大，无法预览")
                root = ElementTree.fromstring(archive.read(info))
            paragraphs = ["".join(part.text or "" for part in paragraph.iter() if part.tag.endswith("}t")) for paragraph in root.iter() if paragraph.tag.endswith("}p")]
            preview = "\n".join(paragraph for paragraph in paragraphs if paragraph.strip()) or "此文档没有可提取的文字，请下载原文件查看。"
        except (OSError, ValueError, KeyError, zipfile.BadZipFile, ElementTree.ParseError):
            preview = "无法在线预览这份 DOCX，请点击右上角下载原文件。"
        return preview.encode("utf-8"), "text/plain; charset=utf-8", "inline"
    return "此文件无法在线预览，请点击右上角下载原文件。".encode("utf-8"), "text/plain; charset=utf-8", "inline"


class Handler(BaseHTTPRequestHandler):
    def _allowed(self) -> bool:
        site = self.headers.get("Sec-Fetch-Site")
        navigation = self.command == "GET" and urllib.parse.urlparse(self.path).path in {"/oauth/callback", "/candidate/", "/alumni/"} and self.headers.get("Sec-Fetch-Mode") == "navigate"
        return self.headers.get("Host") == ORIGIN_HOST and (site in {None, "none", "same-origin"} or (navigation and site in {"same-site", "cross-site"}))

    def _send(self, code: int, body: bytes, content_type: str = "application/json; charset=utf-8", cookie: str = "") -> None:
        try:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data: blob:; frame-src 'self' blob:; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, code: int, data: dict | list, cookie: str = "") -> None:
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), cookie=cookie)

    def _cookie(self, token: str, max_age: int) -> str:
        secure = "; Secure" if ORIGIN.startswith("https://") else ""
        return f"AR_PORTAL_SESSION={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}{secure}"

    def _identity(self, role: str | None = None) -> dict:
        cookies = self.headers.get("Cookie", "")
        match = re.search(r"(?:^|;\s*)AR_PORTAL_SESSION=([A-Za-z0-9_-]{40,})", cookies)
        if not match:
            raise PermissionError("请先登录")
        with SESSION_LOCK:
            saved = SESSIONS.get(match.group(1))
            if not saved or saved[1] < time.time():
                SESSIONS.pop(match.group(1), None)
                raise PermissionError("登录已过期，请重新登录")
        identity = saved[0]
        if role and identity["role"] != role:
            raise PermissionError("无权访问")
        return identity

    def _body(self, max_bytes: int = 100_000) -> dict:
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            raise ValueError("请求格式无效")
        length = int(self.headers.get("Content-Length", "0"))
        if not 1 <= length <= max_bytes:
            raise ValueError("请求内容过大或为空")
        payload = json.loads(self.rfile.read(length))
        if not isinstance(payload, dict):
            raise ValueError("请求格式无效")
        return payload

    def _page(self, path: str) -> None:
        file = PUBLIC / path
        if not file.is_file():
            self._send(404, b"Not found", "text/plain")
            return
        body = file.read_bytes()
        self._send(200, body, mimetypes.guess_type(file.name)[0] or "text/plain")

    def _redirect(self, url: str, cookie: str = "") -> None:
        self.send_response(303)
        self.send_header("Location", url)
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def _oauth_callback(self) -> None:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        state = query.get("state", [""])[0]
        browser_state = re.search(r"(?:^|;\s*)AR_OAUTH_STATE=([A-Za-z0-9_.-]{40,})", self.headers.get("Cookie", ""))
        if not browser_state or not secrets.compare_digest(state, browser_state.group(1)):
            self._json(400, {"error": "OAuth 授权状态不匹配，请重新登录"})
            return
        role = oauth_role(state)
        if not role or not query.get("code") or query.get("error"):
            self._json(400, {"error": "OAuth 授权无效或已过期，请重新登录"})
            return
        try:
            info = mp_oauth.userinfo(query["code"][0])
        except (ValueError, KeyError, TypeError, urllib.error.URLError, TimeoutError, FeishuError, OSError):
            self._redirect(f"/{role}/?auth_error=1")
            return
        roles = info.get("roles")
        if role == "alumni" and not (isinstance(roles, list) and "founder_company_hr" in roles):
            self._redirect("/alumni/?auth_error=founder_company_hr_required")
            return
        try:
            identity = login_with_mp(role, info.get("sub"), info.get("phone"))
            account_data(identity)
        except MpLoginError as error:
            self._redirect(f"/{role}/?auth_error={error.code}")
            return
        except (ValueError, KeyError, TypeError, urllib.error.URLError, TimeoutError, FeishuError, OSError):
            self._redirect(f"/{role}/?auth_error=service_error")
            return
        token = secrets.token_urlsafe(32)
        with SESSION_LOCK:
            SESSIONS[token] = (identity, time.time() + SESSION_TTL)
        self._redirect(f"/{role}/", self._cookie(token, SESSION_TTL))

    def do_GET(self) -> None:
        if urllib.parse.urlparse(self.path).path == "/up":
            self._json(200, {"ok": True})
            return
        if not self._allowed():
            self._json(403, {"error": "Forbidden"})
            return
        path = urllib.parse.urlparse(self.path).path
        if path == "/oauth/callback":
            self._oauth_callback()
            return
        if path in {"/candidate/oauth/start", "/alumni/oauth/start"}:
            role = path.split("/")[1]
            try:
                state = oauth_state(role)
                url = mp_oauth.authorization_url(state)
            except ValueError as error:
                self._json(503, {"error": str(error)})
                return
            secure = "; Secure" if ORIGIN.startswith("https://") else ""
            self._redirect(url, f"AR_OAUTH_STATE={state}; Path=/oauth/callback; HttpOnly; SameSite=Lax; Max-Age=600{secure}")
            return
        if path == "/health":
            self._json(200, {"ok": True, "candidate_chat": 12, "local_recommendations": True, "alumni_company_fields": 1, "portal_revision": 15, "mp_oauth": bool(os.environ.get("MP_OAUTH_CLIENT_ID") and os.environ.get("MP_OAUTH_CLIENT_SECRET"))})
            return
        if path in {"/candidate/", "/alumni/"}:
            self._page("index.html")
            return
        if path.startswith("/assets/") and path.removeprefix("/assets/") in ASSETS:
            self._page(path.removeprefix("/assets/"))
            return
        try:
            role = "candidate" if path.startswith("/api/candidate/") else "alumni" if path.startswith("/api/alumni/") else None
            if not role:
                self._json(404, {"error": "Not found"})
                return
            identity = self._identity(role)
            if path.endswith("/me"):
                self._json(200, account_data(identity))
            elif path.endswith("/jobs") and role == "alumni":
                self._json(200, {"items": list_jobs(identity)})
            elif path.endswith("/recommendations") and role == "alumni":
                self._json(200, {"items": list_recommendations(identity)})
            elif path.endswith("/resume") and role == "candidate":
                self._download_resume(identity)
            elif path.endswith("/recommendation-resume") and role == "alumni":
                self._download_recommendation_resume(identity)
            else:
                self._json(404, {"error": "Not found"})
        except PermissionError as error:
            self._json(401, {"error": str(error)})
        except (ValueError, FeishuError) as error:
            self._json(400, {"error": str(error)})
        except Exception:
            self._json(500, {"error": "读取失败，请稍后重试"})

    def _download_resume(self, identity: dict) -> None:
        from ar import safe_name

        client, app_token = _client()
        account_data(identity)
        # Resolve only the authenticated account record in the candidate output table.
        from portal_data import _record as get_record
        row = get_record(client, app_token, "candidate_output", identity["id"])
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        field_name = query.get("field", ["简历"])[0]
        from portal_data import candidate_form_schema

        if not any(item["name"] == field_name and item["type"] == 17 for item in candidate_form_schema(client, app_token)):
            raise ValueError("附件字段无效")
        files = (row.get("fields") or {}).get(field_name) or []
        index = int(query.get("index", ["0"])[0])
        if not 0 <= index < len(files) or not isinstance(files[index], dict):
            raise ValueError("简历不存在")
        item = files[index]
        client.authenticate()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / safe_name(item.get("name") or "resume.pdf")
            client.download_attachment(item, path)
            content = path.read_bytes()
        filename = item.get("name") or "resume.pdf"
        content, content_type, disposition = resume_response(content, filename, query.get("download", ["0"])[0] == "1")
        name = urllib.parse.quote(filename)
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Content-Disposition", f"{disposition}; filename*=UTF-8''{name}")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)

    def _download_recommendation_resume(self, identity: dict) -> None:
        from ar import safe_name, table_path
        from match_engine import _record_location
        import recommendation_store

        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        recommendation_id = query.get("id", [""])[0]
        index = int(query.get("index", ["0"])[0])
        if not any(item["id"] == recommendation_id for item in list_recommendations(identity)):
            raise PermissionError("无权查看这份简历")
        rec = recommendation_store.get(recommendation_id)
        if not rec:
            raise ValueError("推荐记录不存在")
        client, app_token = _client()
        candidate_id = rec["candidate_id"]
        _, table_id = _record_location("candidate", candidate_id)
        record = client.request("GET", table_path(app_token, table_id) + "/records/" + candidate_id).get("record") or {}
        files = (record.get("fields") or {}).get("简历") or []
        if not 0 <= index < len(files) or not isinstance(files[index], dict):
            raise ValueError("简历不存在")
        item = files[index]
        client.authenticate()
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / safe_name(item.get("name") or "resume.pdf")
            client.download_attachment(item, file)
            content = file.read_bytes()
        filename = item.get("name") or "resume.pdf"
        content, content_type, disposition = resume_response(content, filename, query.get("download", ["0"])[0] == "1")
        name = urllib.parse.quote(filename)
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Content-Disposition", f"{disposition}; filename*=UTF-8''{name}")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:
        if not self._allowed() or self.headers.get("Origin") != ORIGIN or self.headers.get("X-AR-Portal") != "1":
            self._json(403, {"error": "Forbidden"})
            return
        path = urllib.parse.urlparse(self.path).path
        role = "candidate" if path.startswith("/api/candidate/") else "alumni" if path.startswith("/api/alumni/") else None
        if not role:
            self._json(404, {"error": "Not found"})
            return
        action = path.rsplit("/", 1)[-1]
        try:
            if action == "logout":
                cookies = self.headers.get("Cookie", "")
                match = re.search(r"(?:^|;\s*)AR_PORTAL_SESSION=([A-Za-z0-9_-]{40,})", cookies)
                with SESSION_LOCK:
                    if match:
                        SESSIONS.pop(match.group(1), None)
                self._json(200, {"ok": True}, self._cookie("", 0))
                return
            payload = self._body(12_000_000 if action == "resume" else 100_000)
            if action in {"register", "login"}:
                if os.environ.get("MP_OAUTH_CLIENT_ID") and os.environ.get("MP_OAUTH_CLIENT_SECRET"):
                    self._json(403, {"error": "请使用奇绩账号登录"})
                    return
                phone = payload.get("phone", "")
                attempt_key = f"{self.client_address[0]}:{role}:{phone}"
                with SESSION_LOCK:
                    recent = [stamp for stamp in FAILED_LOGINS.get(attempt_key, []) if stamp > time.time() - 900]
                    FAILED_LOGINS[attempt_key] = recent
                    if len(recent) >= 8:
                        self._json(429, {"error": "尝试次数过多，请稍后重试"})
                        return
                try:
                    identity = register(role, phone, payload.get("password", "")) if action == "register" else login(role, phone, payload.get("password", ""))
                except ValueError:
                    with SESSION_LOCK:
                        FAILED_LOGINS[attempt_key].append(time.time())
                    raise
                token = secrets.token_urlsafe(32)
                with SESSION_LOCK:
                    SESSIONS[token] = (identity, time.time() + SESSION_TTL)
                    FAILED_LOGINS.pop(attempt_key, None)
                self._json(200, account_data(identity), self._cookie(token, SESSION_TTL))
                return
            identity = self._identity(role)
            if action == "profile" and role == "candidate":
                result = save_candidate(identity, name=payload.get("name"), description=payload.get("description"), enabled=payload.get("enabled"), form_fields=payload.get("fields"))
            elif action == "chat" and role == "candidate":
                me = account_data(identity)
                if me["submitted"]:
                    raise ValueError("资料已提交，可直接在我的简历中修改")
                result = chat_reply(payload.get("messages"), payload.get("draft", {}), me["schema"], me["values"])
                if result["fields"]:
                    saved = dict(result["fields"])
                    for item in me["schema"]:
                        if item["type"] == 5 and isinstance(saved.get(item["name"]), str):
                            from datetime import datetime, timedelta, timezone
                            saved[item["name"]] = int(datetime.strptime(saved[item["name"]], "%Y-%m-%d").replace(tzinfo=timezone(timedelta(hours=8))).timestamp() * 1000)
                    result["profile"] = save_candidate(identity, form_fields=saved, draft=True)
            elif action == "draft" and role == "candidate":
                result = save_candidate(identity, form_fields=payload.get("fields"), draft=True)
            elif action == "remove-attachment" and role == "candidate":
                result = remove_candidate_attachment(identity, payload.get("field", ""), payload.get("index"))
            elif action == "company" and role == "alumni":
                result = save_alumni_company(identity, payload.get("company", ""), payload.get("contact_title"), payload.get("introduction"))
            elif action == "job" and role == "alumni":
                result = save_job(identity, record_id=payload.get("id", ""), title=payload.get("title", ""), body=payload.get("body", ""), enabled=payload.get("enabled", True))
            elif action == "feedback" and role == "alumni":
                result = feedback(identity, payload.get("id", ""), payload.get("status", ""))
            elif action == "resume" and role == "candidate":
                result = self._upload_resume(identity, payload)
            else:
                self._json(404, {"error": "Not found"})
                return
            self._json(200, result)
        except PermissionError as error:
            self._json(401, {"error": str(error)})
        except (ValueError, FeishuError, json.JSONDecodeError, binascii.Error) as error:
            self._json(400, {"error": str(error)})
        except RuntimeError as error:
            self._json(502, {"error": str(error)})
        except Exception:
            self._json(500, {"error": "保存失败，请稍后重试"})

    def _upload_resume(self, identity: dict, payload: dict) -> dict:
        from ar import safe_name
        from portal_data import _update, WRITE_LOCK

        name = payload.get("name", "")
        field_name = payload.get("field", "简历")
        encoded = payload.get("data", "")
        if not isinstance(name, str) or not re.search(r"\.(pdf|docx|txt|png|jpe?g)$", name, re.I) or not isinstance(encoded, str):
            raise ValueError("仅支持 PDF、DOCX、TXT、PNG 或 JPG 文件")
        content = base64.b64decode(encoded, validate=True)
        if not 1 <= len(content) <= 8 * 1024 * 1024:
            raise ValueError("附件大小不能超过 8 MB")
        if name.lower().endswith(".pdf") and not content.startswith(b"%PDF-"):
            raise ValueError("PDF 文件内容无效")
        if name.lower().endswith(".docx") and not content.startswith(b"PK"):
            raise ValueError("DOCX 文件内容无效")
        client, app_token = _client()
        account_data(identity)
        from portal_data import candidate_form_schema

        if not isinstance(field_name, str) or not any(item["name"] == field_name and item["type"] == 17 for item in candidate_form_schema(client, app_token)):
            raise ValueError("附件字段无效")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / safe_name(name)
            path.write_bytes(content)
            client.authenticate()
            token = client.upload_attachment(path, app_token)
        with WRITE_LOCK:
            _update(client, app_token, "candidate_output", identity["id"], {field_name: [{"file_token": token}], "AR_更新时间": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        profile = account_data(identity)
        if payload.get("analyze") is True and field_name == "简历":
            try:
                analysis = parse_resume(content, name, profile["schema"], profile["values"])
                saved = dict(analysis["fields"])
                for item in profile["schema"]:
                    if item["type"] == 5 and isinstance(saved.get(item["name"]), str):
                        from datetime import datetime, timedelta, timezone
                        saved[item["name"]] = int(datetime.strptime(saved[item["name"]], "%Y-%m-%d").replace(tzinfo=timezone(timedelta(hours=8))).timestamp() * 1000)
                if saved:
                    profile = save_candidate(identity, form_fields=saved, draft=True)
                profile["analysis_fields"] = list(saved)
            except (ValueError, RuntimeError) as error:
                profile["analysis_error"] = str(error)
        return profile

    def log_message(self, format: str, *args) -> None:
        pass


def main() -> None:
    from recommendation_store import ensure_schema as ensure_recommendations
    ensure_recommendations()
    try:
        ensure_schema()
    except (ValueError, FeishuError, RuntimeError, OSError) as error:
        print(f"飞书门户初始化失败，配置修复后重启门户即可重试：{error}", flush=True)
    try:
        from portal_data import sync_business_outcomes
        changed = sync_business_outcomes()
        print(f"飞书业务结果已同步：候选人 {changed['candidate_output']} 行，JD {changed['alumni_output']} 行", flush=True)
    except (ValueError, FeishuError, RuntimeError, OSError) as error:
        print(f"飞书业务结果同步失败，可重启门户重试：{error}", flush=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    print(f"候选人端：{ORIGIN}/candidate/", flush=True)
    print(f"校友端：{ORIGIN}/alumni/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
