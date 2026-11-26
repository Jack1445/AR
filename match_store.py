"""SQL persistence for AI tags and per-JD evaluation artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from psycopg.types.json import Jsonb

from pg_store import connect


BUCKETS = ("candidate_tags", "job_tags", "evaluations")


def ensure_schema() -> None:
    with connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS match_artifacts (
            bucket TEXT NOT NULL,
            item_key TEXT NOT NULL,
            payload JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (bucket, item_key),
            CHECK (bucket IN ('candidate_tags', 'job_tags', 'evaluations'))
        )""")


def migrate_legacy(path: Path | None = None) -> int:
    """Import the old JSON state once; an existing SQL row always wins."""
    path = path or Path(__file__).with_name("match_state.json")
    if not path.is_file():
        return 0
    try:
        legacy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    imported = 0
    with connect() as db:
        for bucket in BUCKETS:
            items = legacy.get(bucket) if isinstance(legacy.get(bucket), dict) else {}
            for key, payload in items.items():
                result = db.execute("""INSERT INTO match_artifacts (bucket, item_key, payload)
                    VALUES (%s, %s, %s) ON CONFLICT (bucket, item_key) DO NOTHING""",
                    (bucket, key, Jsonb(payload)))
                imported += result.rowcount
    return imported


def state() -> dict:
    result = {bucket: {} for bucket in BUCKETS}
    with connect() as db:
        for row in db.execute("SELECT bucket, item_key, payload FROM match_artifacts"):
            result[row["bucket"]][row["item_key"]] = dict(row["payload"])
    return result


def replace_state(value: dict) -> None:
    with connect() as db:
        for bucket in BUCKETS:
            current = value.get(bucket) if isinstance(value.get(bucket), dict) else {}
            keys = list(current)
            if keys:
                db.execute("DELETE FROM match_artifacts WHERE bucket = %s AND NOT (item_key = ANY(%s))", (bucket, keys))
            else:
                db.execute("DELETE FROM match_artifacts WHERE bucket = %s", (bucket,))
            for key, payload in current.items():
                db.execute("""INSERT INTO match_artifacts (bucket, item_key, payload, updated_at)
                    VALUES (%s, %s, %s, NOW())
                    ON CONFLICT (bucket, item_key) DO UPDATE SET payload = EXCLUDED.payload, updated_at = NOW()""",
                           (bucket, key, Jsonb(payload)))
