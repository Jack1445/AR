"""Local, per-candidate-per-JD recommendation and interview history."""

from __future__ import annotations

import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


STORE_FILE = Path(__file__).resolve().parent / "recommendations.sqlite3"
LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def _connect():
    db = sqlite3.connect(STORE_FILE, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS recommendations (
        id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL,
        candidate_id TEXT NOT NULL,
        owner_id TEXT NOT NULL DEFAULT '',
        candidate_name TEXT NOT NULL DEFAULT '',
        candidate_profile TEXT NOT NULL DEFAULT '',
        stars INTEGER NOT NULL,
        reason TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT '待反馈',
        interest TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(job_id, candidate_id)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS feedback_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recommendation_id TEXT NOT NULL,
        from_status TEXT NOT NULL,
        to_status TEXT NOT NULL,
        changed_at TEXT NOT NULL
    )""")
    db.commit()
    try:
        with db:
            yield db
    finally:
        db.close()


def get(recommendation_id: str) -> dict | None:
    with LOCK, _connect() as db:
        row = db.execute("SELECT * FROM recommendations WHERE id = ?", (recommendation_id,)).fetchone()
        return dict(row) if row else None


def find(job_id: str, candidate_id: str) -> dict | None:
    with LOCK, _connect() as db:
        row = db.execute("SELECT * FROM recommendations WHERE job_id = ? AND candidate_id = ?", (job_id, candidate_id)).fetchone()
        return dict(row) if row else None


def all_rows() -> list[dict]:
    with LOCK, _connect() as db:
        return [dict(row) for row in db.execute("SELECT * FROM recommendations ORDER BY created_at, id")]


def create(job_id: str, candidate_id: str, owner_id: str, name: str, profile: str, stars: int, reason: str, *, legacy_id: str = '', status: str = '待反馈', interest: str = '') -> dict:
    with LOCK, _connect() as db:
        existing = db.execute("SELECT * FROM recommendations WHERE job_id = ? AND candidate_id = ?", (job_id, candidate_id)).fetchone()
        if existing:
            return dict(existing)
        now = _now()
        record_id = legacy_id or 'local_' + uuid.uuid4().hex
        db.execute("INSERT INTO recommendations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (record_id, job_id, candidate_id, owner_id, name, profile, stars, reason, status, interest, now, now))
        return dict(db.execute("SELECT * FROM recommendations WHERE id = ?", (record_id,)).fetchone())


def set_status(recommendation_id: str, status: str, interest: str | None = None) -> dict:
    with LOCK, _connect() as db:
        previous = db.execute("SELECT status FROM recommendations WHERE id = ?", (recommendation_id,)).fetchone()
        if not previous:
            raise ValueError("推荐记录不存在")
        if interest is None:
            db.execute("UPDATE recommendations SET status = ?, updated_at = ? WHERE id = ?", (status, _now(), recommendation_id))
        else:
            db.execute("UPDATE recommendations SET status = ?, interest = ?, updated_at = ? WHERE id = ?", (status, interest, _now(), recommendation_id))
        if previous["status"] != status:
            db.execute("INSERT INTO feedback_events (recommendation_id, from_status, to_status, changed_at) VALUES (?, ?, ?, ?)", (recommendation_id, previous["status"], status, _now()))
        row = db.execute("SELECT * FROM recommendations WHERE id = ?", (recommendation_id,)).fetchone()
        return dict(row)
