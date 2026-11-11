"""Create or verify the local Feishu table map during first-time setup."""

from __future__ import annotations

import argparse
import json

from ar import Client, FeishuError, ROOT, identifiers, save_json, table_path
from credentials import get_credentials


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
    if any(len(items) != 1 for items in groups.values()):
        found = "、".join(table.get("name", "") for table in tables)
        raise FeishuError(f"无法自动识别当前候选人、历史候选人和校友 JD 各一张表；实际表格：{found}。请手动配置 ar.json。")
    return [
        {"id": groups["current"][0]["table_id"], "name": groups["current"][0]["name"], "kind": "candidate", "archived": False},
        {"id": groups["archived"][0]["table_id"], "name": groups["archived"][0]["name"], "kind": "candidate", "archived": True},
        {"id": groups["job"][0]["table_id"], "name": groups["job"][0]["name"], "kind": "job", "archived": False},
    ]


def configure(base_url: str | None) -> None:
    path = ROOT / "ar.json"
    if path.is_file():
        config = json.loads(path.read_text(encoding="utf-8"))
        print("沿用现有的 ar.json 数据表配置。")
    else:
        if not base_url:
            raise FeishuError("首次配置需要提供飞书多维表格链接")
        config = {"base_url": base_url.strip()}
    app_token, target_table = identifiers(config["base_url"])
    app_id, app_secret = get_credentials()
    client = Client(app_id, app_secret)
    client.authenticate()
    found = list(client.pages(f"/bitable/v1/apps/{app_token}/tables"))
    by_id = {table["table_id"]: table for table in found}
    if target_table and target_table not in by_id:
        raise FeishuError("链接指定的数据表不在应用可访问的表格中")
    if path.is_file():
        mapped = config.get("tables", [])
        if not isinstance(mapped, list) or len(mapped) != 3 or any(not isinstance(table, dict) or table.get("id") not in by_id for table in mapped):
            raise FeishuError("ar.json 中的三张数据表与当前飞书应用不一致")
    else:
        mapped = classify_tables(found)
        config["tables"] = mapped
    for table in mapped:
        prefix = table_path(app_token, table["id"])
        client.request("GET", prefix + "/fields", params={"page_size": 1})
        client.request("GET", prefix + "/records", params={"page_size": 1})
        print(f"已验证：{table['name']}")
    if not path.is_file():
        save_json(path, config)
        print("已生成本机 ar.json。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url")
    args = parser.parse_args()
    try:
        configure(args.base_url)
    except (FeishuError, ValueError, KeyError, OSError) as error:
        parser.exit(1, f"配置失败：{error}\n")
