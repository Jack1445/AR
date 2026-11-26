"""Build the AR admin catalog from PostgreSQL, the system of record."""

from __future__ import annotations

from datetime import datetime

from build_web import DATA, TABLES, read_json
import portal_store
from portal_data import JOB_FIELD_SPECS


KINDS = ("candidate_output", "alumni_output")


def _table(kind: str) -> dict:
    return next(item for item in TABLES if item["kind"] == kind and not item["archived"])


def _iso(value) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value or "")


def _field_schema(kind: str, records: list[dict]) -> list[dict]:
    cached = portal_store.get_schema(kind, max_age_seconds=None) or []
    by_name = {}
    for item in cached:
        name = item.get("name") or item.get("field_name")
        if name:
            by_name[name] = {"field_name": name, "type": item.get("type", 1)}
    if kind == "alumni_output":
        for name, spec in JOB_FIELD_SPECS.items():
            by_name.setdefault(name, {"field_name": name, "type": spec.get("type", 1)})
    for row in records:
        for name in row["fields"]:
            by_name.setdefault(name, {"field_name": name, "type": 1})
    return list(by_name.values())


def catalog() -> dict:
    tables = []
    for kind in KINDS:
        source = _table(kind)
        rows = portal_store.list_records(kind)
        records = [{
            "record_id": row["local_id"],
            "feishu_record_id": row.get("feishu_record_id"),
            "fields": dict(row["fields"]),
            "created_time": 0,
            "updated_time": _iso(row.get("updated_at")),
            "sync_state": row.get("sync_state", "synced"),
        } for row in rows]
        newest = max((_iso(row.get("updated_at")) for row in rows), default="")
        tables.append({
            "id": source["id"], "name": source["name"], "kind": kind,
            "archived": False, "available": True, "synced_at": newest,
            "source": "postgresql", "fields": _field_schema(kind, records),
            "records": records,
            # Downloaded files remain a transport cache; record metadata is SQL-only.
            "attachments": read_json(DATA / source["id"] / "attachments.json", []),
        })
    return {"tables": tables, "queue": portal_store.queue_summary(), "source": "postgresql"}
