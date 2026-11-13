"""Create or verify the local Feishu table map during first-time setup."""

from __future__ import annotations

import argparse
import json
import re
from urllib.parse import parse_qs, urlencode, urlparse

from ar import Client, FeishuError, ROOT, identifiers, save_json, table_path
from credentials import get_credentials


def resolve_base_url(client: Client, url: str) -> str:
    """Turn a Wiki Bitable node link into the canonical /base/ URL."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".feishu.cn"):
        raise FeishuError("请输入飞书多维表格链接")
    if re.fullmatch(r"/base/[A-Za-z0-9]+", parsed.path):
        identifiers(url)
        return url
    wiki = re.fullmatch(r"/wiki/([A-Za-z0-9]+)", parsed.path)
    if not wiki:
        raise FeishuError("只支持 /base/ 多维表格链接或 /wiki/ 知识库多维表格链接")
    try:
        node = client.request("GET", "/wiki/v2/spaces/get_node", params={"token": wiki.group(1), "obj_type": "wiki"}).get("node") or {}
    except FeishuError as error:
        raise FeishuError("无法解析知识库链接；请确认应用已开通「查看知识库」API 权限，并能访问该知识库页面。" + str(error)) from error
    if node.get("obj_type") != "bitable" or not re.fullmatch(r"[A-Za-z0-9]+", str(node.get("obj_token", ""))):
        raise FeishuError("该知识库链接指向的不是多维表格；请打开目标多维表格页面后复制链接")
    table_id = parse_qs(parsed.query).get("table", [None])[0]
    query = "?" + urlencode({"table": table_id}) if table_id else ""
    resolved = f"https://{parsed.hostname}/base/{node['obj_token']}{query}"
    identifiers(resolved)
    print("已将知识库链接解析为多维表格链接。")
    return resolved


def classify_tables(tables: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {"current": [], "archived": [], "job": []}
    for table in tables:
        name = table.get("name", "")
        if "候选" in name or "简历" in name:
            group = "archived" if any(word in name for word in ("旧版", "存档", "归档", "历史")) else "current"
        elif "jd" in name.casefold() or "岗位" in name or "招聘需求" in name:
            group = "job"
        else:
            continue
        groups[group].append(table)

    def choose(group: str) -> dict | None:
        items = groups[group]
        if len(items) == 1:
            return items[0]
        if not items:
            return None
        def score(item: dict) -> int:
            name = item.get("name", "")
            if group == "job":
                return 2 if "校友JD收集" in name else 1 if "JD收集" in name else 0
            return (2 if "候选人侧简历收集" in name else 0) + (1 if "外部" in name else 0)
        highest = max(score(item) for item in items)
        preferred = [item for item in items if score(item) == highest]
        return preferred[0] if highest > 0 and len(preferred) == 1 else None

    selected = {group: choose(group) for group in groups}
    outputs = {
        "alumni_output": next((table for table in tables if table.get("name") == "AR-校友侧-jiakai"), None),
        "candidate_output": next((table for table in tables if table.get("name") == "AR-候选人-jiakai"), None),
        "resume_flow": next((table for table in tables if table.get("name") == "校友流转简历"), None),
    }
    use_five = any(outputs.values())
    required = ("current", "job") if use_five else ("current", "archived", "job")
    if any(selected[group] is None for group in required) or (use_five and not all(outputs.values())):
        found = "、".join(table.get("name", "") for table in tables)
        raise FeishuError(f"无法自动识别目标数据表；实际表格：{found}。请手动配置 ar.json。")
    mapped = [
        {"id": selected["current"]["table_id"], "name": selected["current"]["name"], "kind": "candidate", "archived": False},
        {"id": selected["job"]["table_id"], "name": selected["job"]["name"], "kind": "job", "archived": False},
    ]
    if use_five:
        mapped.extend({"id": outputs[kind]["table_id"], "name": outputs[kind]["name"], "kind": kind, "archived": False} for kind in outputs)
    else:
        mapped.insert(1, {"id": selected["archived"]["table_id"], "name": selected["archived"]["name"], "kind": "candidate", "archived": True})
    return mapped


def configure(base_url: str | None) -> None:
    path = ROOT / "ar.json"
    previous_count = 0
    if path.is_file():
        config = json.loads(path.read_text(encoding="utf-8"))
        previous_count = len(config.get("tables", []))
        print("沿用现有的 ar.json 数据表配置。")
    else:
        if not base_url:
            raise FeishuError("首次配置需要提供飞书多维表格链接")
        config = {"base_url": base_url.strip()}
    app_id, app_secret = get_credentials()
    client = Client(app_id, app_secret)
    client.authenticate()
    original_url = config["base_url"]
    config["base_url"] = resolve_base_url(client, original_url)
    app_token, target_table = identifiers(config["base_url"])
    found = list(client.pages(f"/bitable/v1/apps/{app_token}/tables"))
    by_id = {table["table_id"]: table for table in found}
    if target_table and target_table not in by_id:
        raise FeishuError("链接指定的数据表不在应用可访问的表格中")
    if path.is_file():
        mapped = config.get("tables", [])
        if not isinstance(mapped, list) or len(mapped) not in (3, 5) or any(not isinstance(table, dict) or table.get("id") not in by_id for table in mapped):
            raise FeishuError("ar.json 中的数据表与当前飞书应用不一致")
        detected = classify_tables(found)
        if len(mapped) == 3 and len(detected) == 5:
            mapped = detected
            config["tables"] = mapped
            print("已将旧的三表配置升级为新的五表配置。")
    else:
        mapped = classify_tables(found)
        config["tables"] = mapped
    for table in mapped:
        prefix = table_path(app_token, table["id"])
        client.request("GET", prefix + "/fields", params={"page_size": 1})
        client.request("GET", prefix + "/records", params={"page_size": 1})
        print(f"已验证：{table['name']}")
    if not path.is_file() or config["base_url"] != original_url or len(mapped) != previous_count:
        save_json(path, config)
        print("已保存本机 ar.json。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url")
    args = parser.parse_args()
    try:
        configure(args.base_url)
    except (FeishuError, ValueError, KeyError, OSError) as error:
        parser.exit(1, f"配置失败：{error}\n")
