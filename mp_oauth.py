"""Server-side OAuth authorization-code exchange against mp's Doorkeeper service."""

import json
import os
import urllib.parse
import urllib.request


def settings():
    base = os.environ.get("MP_OAUTH_URL", "https://build.miracleplus.com").rstrip("/")
    client_id = os.environ.get("MP_OAUTH_CLIENT_ID", "")
    secret = os.environ.get("MP_OAUTH_CLIENT_SECRET", "")
    origin = os.environ.get("AR_PORTAL_ORIGIN", "http://127.0.0.1:38480").rstrip("/")
    local_mp = base.startswith(("http://127.0.0.1:", "http://localhost:"))
    if not ((base.startswith("https://") or local_mp) and client_id and secret and origin.startswith(("https://", "http://127.0.0.1:", "http://localhost:"))):
        raise ValueError("mp OAuth 配置不完整或地址不安全")
    return base, client_id, secret, origin + "/oauth/callback"


def authorization_url(state):
    base, client_id, _, callback = settings()
    return base + "/oauth/authorize?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": callback, "response_type": "code", "scope": "public", "state": state,
    })


def userinfo(code):
    base, client_id, secret, callback = settings()
    body = urllib.parse.urlencode({"grant_type": "authorization_code", "code": code,
                                    "client_id": client_id, "client_secret": secret, "redirect_uri": callback}).encode()
    with urllib.request.urlopen(urllib.request.Request(base + "/oauth/token", data=body), timeout=10) as response:
        token = json.load(response)["access_token"]
    with urllib.request.urlopen(urllib.request.Request(base + "/oauth/userinfo", headers={"Authorization": "Bearer " + token}), timeout=10) as response:
        return json.load(response)
