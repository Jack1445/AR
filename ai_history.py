"""Local audit trail for actual AI calls. Prompts may contain resume data."""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


HISTORY_FILE = Path(__file__).resolve().parent / "ai_history.sqlite3"
KINDS = {"candidate_tag", "job_tag", "evaluation"}


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(HISTORY_FILE, timeout=15)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("""CREATE TABLE IF NOT EXISTS ai_calls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        kind TEXT NOT NULL,
        target_id TEXT NOT NULL,
        target_label TEXT NOT NULL,
        model TEXT NOT NULL,
        status TEXT NOT NULL,
        system_prompt TEXT NOT NULL,
        user_prompt TEXT NOT NULL,
        raw_response TEXT NOT NULL DEFAULT '',
        error TEXT NOT NULL DEFAULT '',
        elapsed_seconds REAL
    )""")
        with connection:
            yield connection
    finally:
        connection.close()


def start_call(kind: str, target_id: str, target_label: str, model: str, system_prompt: str, user_prompt: str) -> tuple[int, float]:
    if kind not in KINDS:
        raise ValueError("未知 AI 分析类型")
    started = time.monotonic()
    with _connect() as connection:
        row = connection.execute(
            "INSERT INTO ai_calls (started_at, kind, target_id, target_label, model, status, system_prompt, user_prompt) VALUES (?, ?, ?, ?, ?, 'running', ?, ?)",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"), kind, target_id, target_label, model, system_prompt, user_prompt),
        )
        return int(row.lastrowid), started


def finish_call(call_id: int, started: float, status: str, raw_response: str = "", error: str = "") -> None:
    if status not in {"success", "failed"}:
        raise ValueError("未知 AI 请求状态")
    with _connect() as connection:
        connection.execute(
            "UPDATE ai_calls SET finished_at = ?, status = ?, raw_response = ?, error = ?, elapsed_seconds = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"), status, raw_response, error, round(time.monotonic() - started, 2), call_id),
        )


def list_calls(before_id: int | None = None, kind: str = "", limit: int = 30) -> dict:
    if kind and kind not in KINDS:
        raise ValueError("未知 AI 分析类型")
    if before_id is not None and before_id < 1:
        raise ValueError("记录 ID 无效")
    limit = max(1, min(limit, 100))
    conditions = []
    values: list = []
    if before_id is not None:
        conditions.append("id < ?")
        values.append(before_id)
    if kind:
        conditions.append("kind = ?")
        values.append(kind)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, started_at, finished_at, kind, target_id, target_label, model, status, elapsed_seconds, error FROM ai_calls"
            + where + " ORDER BY id DESC LIMIT ?", (*values, limit + 1),
        ).fetchall()
    return {"items": [dict(row) for row in rows[:limit]], "has_more": len(rows) > limit}


def get_call(call_id: int) -> dict | None:
    if call_id < 1:
        raise ValueError("记录 ID 无效")
    with _connect() as connection:
        row = connection.execute("SELECT * FROM ai_calls WHERE id = ?", (call_id,)).fetchone()
    return dict(row) if row else None
