"""Local AI connection settings. API secrets stay in Windows Credential Manager."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from credentials import _keyring


CONFIG = Path(__file__).resolve().parent / "ai_config.json"
SERVICE = "AR AI Connection"
ACCOUNT = "api_key"


def _valid_base_url(value: str) -> str:
    value = value.strip().rstrip("/")
    if not value:
        return ""
    parsed = urlsplit(value)
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("请填写不含密钥、查询参数的 API 基础地址")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}):
        raise ValueError("API 地址须使用 HTTPS；本机模型可使用 HTTP")
    if len(value) > 500:
        raise ValueError("API 地址过长")
    if value.endswith("/chat/completions"):
        value = value[: -len("/chat/completions")]
    elif value.endswith("/models"):
        value = value[:-7]
    if not urlsplit(value).path:
        value += "/v1"
    return value


def _get_key() -> str:
    return _keyring().get_password(SERVICE, ACCOUNT) or ""


def read_settings() -> dict:
    try:
        data = json.loads(CONFIG.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    except (OSError, ValueError) as error:
        raise RuntimeError("无法读取本地 AI 设置") from error
    models = data.get("models", [])
    if not isinstance(models, list):
        models = []
    max_concurrency = data.get("max_concurrency", 3)
    if type(max_concurrency) is not int or not 1 <= max_concurrency <= 10:
        max_concurrency = 3
    return {
        "base_url": data.get("base_url", ""),
        "model": data.get("model", ""),
        "models": [item for item in models if isinstance(item, str)][:500],
        "max_concurrency": max_concurrency,
        "has_key": bool(_get_key()),
    }


def save_settings(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("设置格式无效")
    base_url = _valid_base_url(str(payload.get("base_url", "")))
    model = str(payload.get("model", "")).strip()
    if len(model) > 200:
        raise ValueError("模型 ID 过长")
    api_key = payload.get("api_key", "")
    if not isinstance(api_key, str) or len(api_key) > 4096:
        raise ValueError("API Key 格式无效")
    api_key = api_key.strip()
    clear_key = payload.get("clear_key", False)
    if not isinstance(clear_key, bool):
        raise ValueError("清除密钥选项无效")
    if api_key and clear_key:
        raise ValueError("不能同时设置和清除 API Key")
    previous = read_settings()
    max_concurrency = payload.get("max_concurrency", previous["max_concurrency"])
    if type(max_concurrency) is not int or not 1 <= max_concurrency <= 10:
        raise ValueError("打标签并发数必须是 1 到 10 的整数")
    models = previous["models"] if base_url == previous["base_url"] else []
    if model and model not in models:
        models.append(model)
    if api_key:
        _keyring().set_password(SERVICE, ACCOUNT, api_key)
    elif clear_key and previous["has_key"]:
        _keyring().delete_password(SERVICE, ACCOUNT)
    data = {"base_url": base_url, "model": model, "models": models[:500], "max_concurrency": max_concurrency}
    temporary = CONFIG.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, CONFIG)
    return read_settings()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def fetch_models() -> dict:
    settings = read_settings()
    if not settings["base_url"]:
        raise ValueError("请先保存 API 基础地址")
    endpoint = settings["base_url"] + "/models"
    key = _get_key()
    headers = {"Accept": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(endpoint, headers=headers)
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=20) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"获取模型列表失败（HTTP {error.code}）") from None
    except urllib.error.URLError as error:
        raise RuntimeError("无法连接模型列表接口，请检查地址或网络") from None
    if len(raw) > 2 * 1024 * 1024:
        raise RuntimeError("模型列表响应过大")
    try:
        payload = json.loads(raw)
        entries = payload["data"]
        if not isinstance(entries, list):
            raise ValueError
        models = sorted({item["id"].strip() for item in entries if isinstance(item, dict) and isinstance(item.get("id"), str) and 0 < len(item["id"]) <= 200})
    except (ValueError, KeyError, TypeError):
        raise RuntimeError("模型列表格式不兼容，请手动填写模型 ID") from None
    if not models:
        return {"models": [], "endpoint": endpoint}
    data = {"base_url": settings["base_url"], "model": settings["model"], "models": models[:500]}
    temporary = CONFIG.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, CONFIG)
    return {"models": models[:500], "endpoint": endpoint}
