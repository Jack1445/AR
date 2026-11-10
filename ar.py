"""Small Feishu Bitable command line client. Requires Python 3.10+."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parent
API = "https://open.feishu.cn/open-apis"


class FeishuError(Exception):
    pass


def identifiers(base_url: str) -> tuple[str, str | None]:
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".feishu.cn"):
        raise FeishuError("ar.json 中的 base_url 必须是飞书多维表格链接")
    match = re.fullmatch(r"/base/([A-Za-z0-9]+)", parsed.path)
    if not match:
        raise FeishuError("只支持 /base/ 形式的多维表格链接")
    query = urllib.parse.parse_qs(parsed.query)
    table_id = query.get("table", [None])[0]
    if table_id is not None and not re.fullmatch(r"[A-Za-z0-9]+", table_id):
        raise FeishuError("链接中的 table ID 格式不正确")
    return match.group(1), table_id


def safe_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name[:120] or "attachment"


def save_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


class Client:
    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self.token: str | None = None

    def request(self, method: str, path: str, *, params: dict | None = None, body: dict | None = None) -> dict:
        if self.token is None:
            self.authenticate()
        url = API + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", "Bearer " + str(self.token))
        if data is not None:
            req.add_header("Content-Type", "application/json; charset=utf-8")
        try:
            response = self._json(req)
        except FeishuError as error:
            raise FeishuError(f"{method} {path} 失败: {error}") from error
        if response.get("code") != 0:
            raise FeishuError(f"飞书 API 错误 {response.get('code')}: {response.get('msg')}")
        return response.get("data") or {}

    @staticmethod
    def _json(req: urllib.request.Request) -> dict:
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read(1000).decode("utf-8", errors="replace")
            try:
                payload = json.loads(detail)
            except ValueError:
                payload = {}
            if payload.get("code") == 91403:
                raise FeishuError(
                    "飞书返回 91403 Forbidden：当前应用尚未取得目标多维表格的文档权限。"
                    "请在表格右上角「…」→「更多」→「添加文档应用」中添加该应用，"
                    "并授予可阅读或可编辑权限；若开启高级权限，还需授予相应权限。"
                ) from error
            raise FeishuError(f"HTTP {error.code}: {detail}") from error
        except urllib.error.URLError as error:
            raise FeishuError(f"连接飞书失败: {error.reason}") from error

    def authenticate(self) -> None:
        data = json.dumps({"app_id": self.app_id, "app_secret": self.app_secret}).encode("utf-8")
        req = urllib.request.Request(API + "/auth/v3/tenant_access_token/internal", data=data, method="POST")
        req.add_header("Content-Type", "application/json; charset=utf-8")
        response = self._json(req)
        if response.get("code") != 0 or not response.get("tenant_access_token"):
            raise FeishuError(f"获取访问令牌失败 {response.get('code')}: {response.get('msg')}")
        self.token = response["tenant_access_token"]

    def pages(self, path: str, *, params: dict | None = None):
        args = dict(params or {})
        args.setdefault("page_size", 100)
        while True:
            data = self.request("GET", path, params=args)
            yield from data.get("items") or []
            if not data.get("has_more"):
                break
            page_token = data.get("page_token")
            if not page_token:
                raise FeishuError("飞书返回 has_more，但没有 page_token")
            args["page_token"] = page_token

    def download_attachment(self, item: dict, destination: Path) -> None:
        token = item["file_token"]
        source = item.get("url") or f"{API}/drive/v1/medias/{urllib.parse.quote(token)}/download"
        parsed = urllib.parse.urlparse(source)
        if parsed.scheme != "https" or parsed.hostname != "open.feishu.cn" or not parsed.path.startswith("/open-apis/drive/v1/medias/"):
            raise FeishuError("附件下载链接不是飞书素材接口")
        # Advanced-permission tables return an `extra` query argument which may
        # contain raw JSON. Encode it before passing the URL to the HTTP client.
        query = urllib.parse.urlencode(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
        source = urllib.parse.urlunparse(parsed._replace(query=query))
        req = urllib.request.Request(source)
        req.add_header("Authorization", "Bearer " + str(self.token))
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(req, timeout=120) as response, tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as tmp:
                temp_path = Path(tmp.name)
                while chunk := response.read(1024 * 1024):
                    tmp.write(chunk)
            temp_path.replace(destination)
        except (urllib.error.HTTPError, urllib.error.URLError) as error:
            if "temp_path" in locals():
                temp_path.unlink(missing_ok=True)
            raise FeishuError(f"下载附件 {token} 失败: {error}") from error

    def upload_attachment(self, path: Path, app_token: str) -> str:
        if path.stat().st_size > 20 * 1024 * 1024:
            raise FeishuError("当前 attach 命令仅支持不超过 20 MiB 的文件；大文件需要分片上传")
        boundary = "----ar" + uuid.uuid4().hex
        parts = []
        for key, value in {"file_name": path.name, "parent_type": "bitable_file", "parent_node": app_token, "size": str(path.stat().st_size)}.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{safe_name(path.name)}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode())
        parts.append(path.read_bytes())
        parts.append(f"\r\n--{boundary}--\r\n".encode())
        req = urllib.request.Request(API + "/drive/v1/medias/upload_all", data=b"".join(parts), method="POST")
        req.add_header("Authorization", "Bearer " + str(self.token))
        req.add_header("Content-Type", "multipart/form-data; boundary=" + boundary)
        response = self._json(req)
        if response.get("code") != 0:
            raise FeishuError(f"上传附件失败 {response.get('code')}: {response.get('msg')}")
        token = (response.get("data") or {}).get("file_token")
        if not token:
            raise FeishuError("上传成功响应缺少 file_token")
        return token


def attachments(value: object):
    if isinstance(value, dict):
        if isinstance(value.get("file_token"), str):
            yield value
        else:
            for child in value.values():
                yield from attachments(child)
    elif isinstance(value, list):
        for child in value:
            yield from attachments(child)


def table_path(app_token: str, table_id: str) -> str:
    return f"/bitable/v1/apps/{app_token}/tables/{table_id}"


def pull(client: Client, app_token: str, table_ids: list[str], output: Path) -> None:
    for table_id in table_ids:
        prefix = table_path(app_token, table_id)
        fields = list(client.pages(prefix + "/fields"))
        records = list(client.pages(prefix + "/records"))
        folder = output / table_id
        save_json(folder / "fields.json", fields)
        save_json(folder / "records.json", records)
        found = {}
        for record in records:
            for field_name, value in (record.get("fields") or {}).items():
                for item in attachments(value):
                    token = item["file_token"]
                    found.setdefault(token, {"record_id": record.get("record_id"), "field": field_name, **item})
        index = []
        failures = []
        for token, item in found.items():
            filename = safe_name(item.get("name") or token)
            relative = Path("attachments") / f"{token}_{filename}"
            try:
                client.download_attachment(item, folder / relative)
                index.append({"file": str(relative), **item})
            except FeishuError as error:
                failures.append(str(error))
        save_json(folder / "attachments.json", index)
        print(f"{table_id}: {len(fields)} 个字段，{len(records)} 条记录，{len(index)} 个附件 → {folder}")
        if failures:
            raise FeishuError("部分附件下载失败:\n" + "\n".join(failures))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="飞书多维表格本地工具")
    parser.add_argument("--config", type=Path, default=ROOT / "ar.json")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="验证应用和目标表格访问权限")
    sub.add_parser("save-credentials", help="将当前环境变量中的应用凭据保存到 Windows 凭据管理器")
    sub.add_parser("sync", help="检查三张表，仅在有变化时更新本地快照")
    p_pull = sub.add_parser("pull", help="下载字段、记录和附件")
    p_pull.add_argument("--all-tables", action="store_true")
    p_pull.add_argument("--output", type=Path, default=ROOT / "downloads")
    p_set = sub.add_parser("set", help="修改某条记录的一个字段")
    p_set.add_argument("record_id")
    p_set.add_argument("field")
    p_set.add_argument("value", help="普通文本；复杂字段用 --json")
    p_set.add_argument("--json", action="store_true", help="将 value 解析为 JSON")
    p_create = sub.add_parser("create", help="新增记录")
    p_create.add_argument("fields_json", help='JSON 对象，或 @文件路径（从 JSON 文件读取）')
    p_attach = sub.add_parser("attach", help="向现有记录的附件字段追加本地文件")
    p_attach.add_argument("record_id")
    p_attach.add_argument("field")
    p_attach.add_argument("file", type=Path)
    args = parser.parse_args(argv)

    try:
        if args.command == "save-credentials":
            from credentials import save_credentials_from_environment
            save_credentials_from_environment()
            print("飞书应用凭据已保存到 Windows 凭据管理器。")
            return 0
        if args.command == "sync":
            from sync import sync_from_saved_credentials
            result = sync_from_saved_credentials()
            if result["changed"]:
                for item in result["tables"]:
                    if item["changed"]:
                        print(f"{item['name']}: 新增 {item['added']}，修改 {item['edited']}，移除 {item['removed']}")
                print(f"已更新本地数据；新下载附件 {result['downloaded']} 个。")
            else:
                print("飞书数据没有变化，本地文件未改动。")
            return 0
        config = json.loads(args.config.read_text(encoding="utf-8"))
        app_token, table_id = identifiers(config["base_url"])
        from credentials import get_credentials
        app_id, app_secret = get_credentials()
        client = Client(app_id, app_secret)
        client.authenticate()
        if args.command == "check":
            tables = list(client.pages(f"/bitable/v1/apps/{app_token}/tables"))
            print(f"连接成功；可访问 {len(tables)} 个数据表。")
            for table in tables:
                print(f"  {table.get('table_id')}: {table.get('name')}")
            if table_id:
                if table_id not in {table.get("table_id") for table in tables}:
                    raise FeishuError(f"目标数据表 {table_id} 不在可访问的数据表列表中")
                prefix = table_path(app_token, table_id)
                fields = client.request("GET", prefix + "/fields", params={"page_size": 1})
                records = client.request("GET", prefix + "/records", params={"page_size": 1})
                print(f"目标数据表可读取；字段和记录接口已验证（返回 {len(fields.get('items') or [])} 个字段、{len(records.get('items') or [])} 条记录）。")
        elif args.command == "pull":
            if args.all_tables:
                table_ids = [item["table_id"] for item in client.pages(f"/bitable/v1/apps/{app_token}/tables")]
            elif table_id:
                table_ids = [table_id]
            else:
                raise FeishuError("链接缺少 table 参数；请用 --all-tables")
            pull(client, app_token, table_ids, args.output)
            if args.output.resolve() == (ROOT / "downloads").resolve():
                from build_web import build_snapshot
                build_snapshot()
        elif args.command == "create":
            if not table_id:
                raise FeishuError("链接缺少 table 参数")
            raw = Path(args.fields_json[1:]).read_text(encoding="utf-8") if args.fields_json.startswith("@") else args.fields_json
            fields = json.loads(raw)
            if not isinstance(fields, dict):
                raise FeishuError("fields_json 必须是 JSON 对象")
            data = client.request("POST", table_path(app_token, table_id) + "/records", body={"fields": fields})
            print("新增记录:", (data.get("record") or {}).get("record_id"))
        elif args.command == "set":
            if not table_id:
                raise FeishuError("链接缺少 table 参数")
            value = json.loads(args.value) if args.json else args.value
            client.request("PUT", table_path(app_token, table_id) + f"/records/{args.record_id}", body={"fields": {args.field: value}})
            print(f"已更新 {args.record_id} 的 {args.field}")
        elif args.command == "attach":
            if not table_id:
                raise FeishuError("链接缺少 table 参数")
            path = args.file.resolve()
            if not path.is_file():
                raise FeishuError(f"找不到本地文件: {path}")
            record_path = table_path(app_token, table_id) + f"/records/{args.record_id}"
            record = client.request("GET", record_path).get("record") or {}
            current = (record.get("fields") or {}).get(args.field) or []
            if not isinstance(current, list):
                raise FeishuError(f"{args.field} 不是附件列表字段")
            token = client.upload_attachment(path, app_token)
            values = [{"file_token": item["file_token"]} for item in current if isinstance(item, dict) and item.get("file_token")]
            values.append({"file_token": token})
            client.request("PUT", record_path, body={"fields": {args.field: values}})
            print(f"已添加附件 {path.name} 到 {args.record_id} 的 {args.field}")
        return 0
    except (FeishuError, OSError, ValueError, KeyError, RuntimeError) as error:
        print(f"错误: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
