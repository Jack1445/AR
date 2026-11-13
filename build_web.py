"""Build a local-only browser snapshot; generated data.js is gitignored."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "downloads"
PUBLIC = ROOT / "web"


def configured_tables() -> list[dict]:
    """Read table identifiers from the local config, never from committed code."""
    config_path = ROOT / "ar.json"
    if not config_path.is_file():
        return []
    config = json.loads(config_path.read_text(encoding="utf-8"))
    tables = config.get("tables", [])
    if not isinstance(tables, list):
        raise ValueError("ar.json 的 tables 必须是列表")
    result = []
    for table in tables:
        if not isinstance(table, dict) or not all(isinstance(table.get(key), str) and table[key] for key in ("id", "name", "kind")) or table["kind"] not in {"candidate", "job", "alumni_output", "candidate_output", "resume_flow"} or not isinstance(table.get("archived"), bool):
            raise ValueError("ar.json 的数据表配置无效")
        result.append({key: table[key] for key in ("id", "name", "kind", "archived")})
    return result


TABLES = configured_tables()


def read_json(path: Path, default):
    if not path.is_file():
        return default
    with path.open("r", encoding="utf-8") as source:
        return json.load(source)


def catalog() -> dict:
    tables = []
    for config in TABLES:
        folder = DATA / config["id"]
        records_path = folder / "records.json"
        tables.append({
            **config,
            "available": records_path.is_file(),
            "synced_at": datetime.fromtimestamp(records_path.stat().st_mtime).isoformat() if records_path.is_file() else None,
            "fields": read_json(folder / "fields.json", []),
            "records": read_json(records_path, []),
            "attachments": read_json(folder / "attachments.json", []),
        })
    return {"tables": tables}


def clean(value):
    if isinstance(value, list):
        return [clean(item) for item in value]
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items() if key not in {"tmp_url", "url"} or "file_token" not in value}
    return value


def build_snapshot() -> Path:
    payload = clean(catalog())
    target = PUBLIC / "data.js"
    temporary = target.with_suffix(".js.tmp")
    temporary.write_text("window.AR_DATA = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    temporary.replace(target)
    counts = [(item["name"], len(item["records"])) for item in payload["tables"]]
    print("本地网页数据已更新：" + "，".join(f"{name} {count} 条" for name, count in counts))
    return target


if __name__ == "__main__":
    build_snapshot()
