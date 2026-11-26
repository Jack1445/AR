"""Shared SQL-backed matching dictionaries and deterministic normalizers."""

from __future__ import annotations

import re

from psycopg.types.json import Jsonb

from pg_store import connect


POSITION_TAXONOMY = (
    ("tech_rd", "技术研发"),
    ("product", "产品经理"),
    ("design", "设计"),
    ("operations", "运营"),
    ("marketing_bd", "市场&品牌&商务"),
    ("sales", "销售"),
    ("corporate", "职能（人力、财会、法务、行政）"),
    ("content", "内容&创意"),
    ("supply_chain", "供应链&生产"),
)
POSITION_LABELS = [label for _code, label in POSITION_TAXONOMY]
LEGACY_POSITION_LABELS = {
    "技术": "技术研发", "产品": "产品经理", "HR": "职能（人力、财会、法务、行政）",
}
CANDIDATE_LOCATION_FIELDS = ("意向base地（eg.北京,上海）", "意向base地（可多选）", "意向base地（多选）")
JOB_LOCATION_FIELD = "工作地点"

LOCATION_ALIASES = {
    "北京": ("北京", "beijing"), "上海": ("上海", "shanghai"), "深圳": ("深圳", "shenzhen"),
    "杭州": ("杭州", "hangzhou"), "香港": ("香港", "hongkong", "hong kong"),
    "广州": ("广州", "guangzhou", "canton"), "成都": ("成都", "chengdu"), "武汉": ("武汉", "wuhan"),
    "南京": ("南京", "nanjing"), "苏州": ("苏州", "suzhou"), "西安": ("西安", "xi'an", "xian"),
    "重庆": ("重庆", "chongqing"), "天津": ("天津", "tianjin"), "厦门": ("厦门", "xiamen"),
    "海外": ("海外", "overseas", "global"),
}


def ensure_schema() -> None:
    with connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS position_taxonomy (
            code TEXT PRIMARY KEY,
            label TEXT NOT NULL UNIQUE,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            sort_order INTEGER NOT NULL,
            aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""")
        for order, (code, label) in enumerate(POSITION_TAXONOMY, 1):
            db.execute("""INSERT INTO position_taxonomy (code, label, sort_order)
                VALUES (%s, %s, %s)
                ON CONFLICT (code) DO UPDATE SET label = EXCLUDED.label, sort_order = EXCLUDED.sort_order""",
                       (code, label, order))
        db.execute("""CREATE TABLE IF NOT EXISTS portal_record_metadata (
            kind TEXT NOT NULL,
            local_id TEXT NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (kind, local_id)
        )""")


def taxonomy(db=None) -> list[dict]:
    if db is None:
        with connect() as owned:
            return taxonomy(owned)
    return [dict(row) for row in db.execute(
        "SELECT code, label, active, sort_order, aliases FROM position_taxonomy WHERE active ORDER BY sort_order, code"
    )]


def position_maps(db=None) -> tuple[dict[str, str], dict[str, str]]:
    rows = taxonomy(db)
    label_to_code = {row["label"]: row["code"] for row in rows}
    for legacy, canonical in LEGACY_POSITION_LABELS.items():
        if canonical in label_to_code:
            label_to_code[legacy] = label_to_code[canonical]
    for row in rows:
        for alias in row.get("aliases") or []:
            if isinstance(alias, str) and alias:
                label_to_code[alias] = row["code"]
    return label_to_code, {row["code"]: row["label"] for row in rows}


def values(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, dict):
        return values(value.get("text") or value.get("name") or value.get("value"))
    return [part.strip() for part in re.split(r"[、,，;/；|\n]+", str(value)) if part.strip()]


def normalize_locations(value) -> list[str]:
    items = values(value)
    raw = " ".join(items).casefold()
    if not raw:
        return []
    result = [canonical for canonical, aliases in LOCATION_ALIASES.items()
              if any(alias.casefold() in raw for alias in aliases)]
    if any(term in raw for term in ("flexible", "不限地点", "地点不限", "全国均可", "全国可")):
        result.append("*")
    # Free text stays supported: unknown but identical place names can still
    # match deterministically without an AI call or a Feishu option list.
    for item in items:
        lowered = re.sub(r"\s+", "", item).casefold().removesuffix("市")
        if not lowered or any(alias.casefold() in lowered for aliases in LOCATION_ALIASES.values() for alias in aliases):
            continue
        if lowered not in {"flexible", "不限地点", "地点不限", "全国均可", "全国可"}:
            result.append("文本:" + lowered)
    return list(dict.fromkeys(result))


def position_codes(value, label_to_code: dict[str, str] | None = None) -> list[str]:
    if label_to_code is None:
        label_to_code, _ = position_maps()
    return list(dict.fromkeys(label_to_code[item] for item in values(value) if item in label_to_code))


def derive_metadata(kind: str, fields: dict, *, label_to_code: dict[str, str] | None = None) -> dict:
    if kind == "candidate_output":
        location = next((fields.get(name) for name in CANDIDATE_LOCATION_FIELDS if fields.get(name)), "")
        return {
            "normalized_locations": normalize_locations(location),
            "intent_position_codes": position_codes(fields.get("意向岗位"), label_to_code),
        }
    if kind == "alumni_output":
        return {"normalized_locations": normalize_locations(fields.get(JOB_LOCATION_FIELD))}
    return {}


def save_metadata(db, kind: str, local_id: str, fields: dict) -> None:
    label_to_code, _ = position_maps(db)
    metadata = derive_metadata(kind, fields, label_to_code=label_to_code)
    db.execute("""INSERT INTO portal_record_metadata (kind, local_id, metadata, updated_at)
        VALUES (%s, %s, %s, NOW())
        ON CONFLICT (kind, local_id) DO UPDATE SET metadata = EXCLUDED.metadata, updated_at = NOW()""",
               (kind, local_id, Jsonb(metadata)))


def get_metadata(kind: str, local_id: str) -> dict:
    with connect() as db:
        row = db.execute("SELECT metadata FROM portal_record_metadata WHERE kind = %s AND local_id = %s",
                         (kind, local_id)).fetchone()
        return dict(row["metadata"]) if row else {}


def backfill_metadata() -> int:
    count = 0
    with connect() as db:
        label_to_code, _ = position_maps(db)
        for row in db.execute("SELECT kind, local_id, fields FROM portal_records"):
            metadata = derive_metadata(row["kind"], dict(row["fields"]), label_to_code=label_to_code)
            db.execute("""INSERT INTO portal_record_metadata (kind, local_id, metadata, updated_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (kind, local_id) DO UPDATE SET metadata = EXCLUDED.metadata, updated_at = NOW()""",
                       (row["kind"], row["local_id"], Jsonb(metadata)))
            count += 1
    return count
