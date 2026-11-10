"""Compare Feishu tables with local snapshots and write only actual changes."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from ar import Client, attachments, safe_name, save_json, table_path
from build_web import DATA, TABLES, build_snapshot, read_json


def stable(value):
    if isinstance(value, dict):
        return {key: stable(part) for key, part in sorted(value.items()) if key not in {"url", "tmp_url"} or "file_token" not in value}
    if isinstance(value, list):
        return [stable(part) for part in value]
    return value


def same_fields(left: list, right: list) -> bool:
    key = lambda item: str(item.get("field_id", ""))
    return stable(sorted(left, key=key)) == stable(sorted(right, key=key))


def same_records(left: list, right: list) -> bool:
    key = lambda item: str(item.get("record_id", ""))
    return stable(sorted(left, key=key)) == stable(sorted(right, key=key))


def same_index(left: list, right: list) -> bool:
    key = lambda item: str(item.get("file_token", ""))
    return stable(sorted(left, key=key)) == stable(sorted(right, key=key))


def record_diff(old: list, new: list) -> dict:
    old_by_id = {item.get("record_id"): stable(item) for item in old}
    new_by_id = {item.get("record_id"): stable(item) for item in new}
    old_ids, new_ids = set(old_by_id), set(new_by_id)
    return {
        "added": len(new_ids - old_ids),
        "removed": len(old_ids - new_ids),
        "edited": sum(old_by_id[key] != new_by_id[key] for key in old_ids & new_ids),
    }


def existing_file(folder: Path, entry: dict) -> Path | None:
    relative = entry.get("file")
    if not isinstance(relative, str):
        return None
    candidate = (folder / relative).resolve()
    return candidate if candidate.is_relative_to(folder.resolve()) and candidate.is_file() else None


def sync_once(client: Client, app_token: str, output: Path = DATA) -> dict:
    """Fetch first, then download and commit changed tables. No-op if unchanged."""
    output.mkdir(parents=True, exist_ok=True)
    plans = []
    for table in TABLES:
        table_id = table["id"]
        prefix = table_path(app_token, table_id)
        fields = list(client.pages(prefix + "/fields"))
        records = list(client.pages(prefix + "/records"))
        folder = output / table_id
        old_fields = read_json(folder / "fields.json", [])
        old_records = read_json(folder / "records.json", [])
        old_index = read_json(folder / "attachments.json", [])
        old_by_token = {entry.get("file_token"): entry for entry in old_index}
        found = {}
        for record in records:
            for field_name, value in (record.get("fields") or {}).items():
                for item in attachments(value):
                    found.setdefault(item["file_token"], {"record_id": record.get("record_id"), "field": field_name, **item})
        index = []
        downloads = []
        for token, item in found.items():
            previous = old_by_token.get(token)
            previous_file = existing_file(folder, previous) if previous else None
            relative = Path(previous["file"]) if previous_file else Path("attachments") / f"{safe_name(token)}_{safe_name(item.get('name') or token)}"
            if not previous_file:
                downloads.append((item, folder / relative))
            index.append({"file": str(relative), **item})
        data_changed = not same_fields(old_fields, fields) or not same_records(old_records, records) or not (folder / "records.json").is_file() or not (folder / "fields.json").is_file()
        index_changed = not same_index(old_index, index)
        plans.append({
            "table": table,
            "folder": folder,
            "fields": fields,
            "records": records,
            "index": index,
            "downloads": downloads,
            "data_changed": data_changed,
            "index_changed": index_changed,
            "diff": record_diff(old_records, records),
        })

    if not any(plan["data_changed"] or plan["index_changed"] or plan["downloads"] for plan in plans):
        return {"changed": False, "tables": [{"id": plan["table"]["id"], "name": plan["table"]["name"], "changed": False, "count": len(plan["records"]), **plan["diff"]} for plan in plans], "downloaded": 0}

    staged = []
    with tempfile.TemporaryDirectory(dir=output) as stage_dir:
        for plan in plans:
            for item, destination in plan["downloads"]:
                stage_path = Path(stage_dir) / plan["table"]["id"] / destination.name
                client.download_attachment(item, stage_path)
                staged.append((stage_path, destination))
        for source, destination in staged:
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.replace(destination)

    for plan in plans:
        folder = plan["folder"]
        if plan["data_changed"]:
            save_json(folder / "fields.json", plan["fields"])
            save_json(folder / "records.json", plan["records"])
        if plan["index_changed"]:
            save_json(folder / "attachments.json", plan["index"])
    if any(plan["data_changed"] or plan["index_changed"] for plan in plans):
        build_snapshot()
    return {
        "changed": True,
        "tables": [{"id": plan["table"]["id"], "name": plan["table"]["name"], "changed": bool(plan["data_changed"] or plan["index_changed"] or plan["downloads"]), "count": len(plan["records"]), **plan["diff"]} for plan in plans],
        "downloaded": len(staged),
    }


def sync_from_saved_credentials() -> dict:
    from credentials import get_credentials
    from ar import ROOT, identifiers

    config = json.loads((ROOT / "ar.json").read_text(encoding="utf-8"))
    app_token, _ = identifiers(config["base_url"])
    client = Client(*get_credentials())
    client.authenticate()
    return sync_once(client, app_token)
