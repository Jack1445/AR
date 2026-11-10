"""Keep Feishu credentials out of the browser and project files."""

from __future__ import annotations

import os


SERVICE = "AR Feishu Bitable"


def _keyring():
    try:
        import keyring
    except ImportError as error:
        raise RuntimeError("缺少 keyring：请在 Conda PowerShell 运行 python -m pip install keyring") from error
    return keyring


def get_credentials() -> tuple[str, str]:
    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")
    if app_id and app_secret:
        return app_id, app_secret
    keyring = _keyring()
    app_id = keyring.get_password(SERVICE, "app_id")
    app_secret = keyring.get_password(SERVICE, "app_secret")
    if not app_id or not app_secret:
        raise RuntimeError("尚未保存飞书凭据。请在已设置环境变量的 Conda PowerShell 中运行 python ar.py save-credentials")
    return app_id, app_secret


def save_credentials_from_environment() -> None:
    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")
    if not app_id or not app_secret:
        raise RuntimeError("当前终端没有 FEISHU_APP_ID 和 FEISHU_APP_SECRET；请先按 README 设置")
    keyring = _keyring()
    keyring.set_password(SERVICE, "app_id", app_id)
    keyring.set_password(SERVICE, "app_secret", app_secret)
