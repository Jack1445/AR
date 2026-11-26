"""PostgreSQL primary mirror and durable Feishu synchronization queue."""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Callable

from psycopg.types.json import Jsonb

from pg_store import connect


KINDS = {"candidate_output", "alumni_output"}
_sync_notifier: Callable[[], None] | None = None
SYNC_ADVISORY_LOCK = 0x415253594E43


def enabled() -> bool:
    return os.environ.get("AR_LOCAL_PRIMARY", "").strip().lower() in {"1", "true", "yes", "on"}


def _kind(value: str) -> str:
    if value not in KINDS:
        raise ValueError("本地门户记录类型无效")
    return value


def _now() -> datetime:
    return datetime.now(timezone.utc)


def set_sync_notifier(notifier: Callable[[], None] | None) -> None:
    """Register the in-process wake-up used after a durable queue commit."""
    global _sync_notifier
    _sync_notifier = notifier


def _notify_sync() -> None:
    notifier = _sync_notifier
    if notifier is not None:
        try:
            notifier()
        except Exception:
            # The PostgreSQL queue is authoritative. A missed in-memory signal
            # is recovered by the worker's fallback scan.
            pass


@contextmanager
def sync_lock():
    """Serialize Feishu queue consumers across the portal and admin processes."""
    with connect() as db:
        acquired = bool(db.execute("SELECT pg_try_advisory_lock(%s) AS locked", (SYNC_ADVISORY_LOCK,)).fetchone()["locked"])
        try:
            yield acquired
        finally:
            if acquired:
                db.execute("SELECT pg_advisory_unlock(%s)", (SYNC_ADVISORY_LOCK,))


def ensure_schema() -> None:
    with connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS portal_records (
            kind TEXT NOT NULL,
            local_id TEXT NOT NULL,
            feishu_record_id TEXT,
            fields JSONB NOT NULL DEFAULT '{}'::jsonb,
            pending_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
            sync_state TEXT NOT NULL DEFAULT 'synced',
            version BIGINT NOT NULL DEFAULT 0,
            synced_version BIGINT NOT NULL DEFAULT 0,
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TIMESTAMPTZ,
            last_error TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            synced_at TIMESTAMPTZ,
            PRIMARY KEY (kind, local_id),
            UNIQUE (kind, feishu_record_id),
            CHECK (sync_state IN ('synced', 'pending', 'failed'))
        )""")
        db.execute("""CREATE INDEX IF NOT EXISTS portal_records_sync_queue
            ON portal_records (sync_state, next_attempt_at, updated_at)""")
        db.execute("""CREATE TABLE IF NOT EXISTS portal_attachments (
            kind TEXT NOT NULL,
            local_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            file_token TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
            content BYTEA NOT NULL,
            size BIGINT NOT NULL,
            feishu_file_token TEXT,
            sync_state TEXT NOT NULL DEFAULT 'synced',
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TIMESTAMPTZ,
            last_error TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (kind, local_id, field_name, file_token),
            FOREIGN KEY (kind, local_id) REFERENCES portal_records(kind, local_id) ON DELETE CASCADE,
            CHECK (sync_state IN ('synced', 'pending', 'failed'))
        )""")
        db.execute("ALTER TABLE portal_attachments ADD COLUMN IF NOT EXISTS feishu_file_token TEXT")
        db.execute("ALTER TABLE portal_attachments ADD COLUMN IF NOT EXISTS sync_state TEXT NOT NULL DEFAULT 'synced'")
        db.execute("ALTER TABLE portal_attachments ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0")
        db.execute("ALTER TABLE portal_attachments ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ")
        db.execute("ALTER TABLE portal_attachments ADD COLUMN IF NOT EXISTS last_error TEXT NOT NULL DEFAULT ''")
        db.execute("""CREATE TABLE IF NOT EXISTS portal_field_schemas (
            kind TEXT PRIMARY KEY,
            schema JSONB NOT NULL,
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS portal_preferences (
            account_id TEXT NOT NULL,
            preference_key TEXT NOT NULL,
            value JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (account_id, preference_key)
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS portal_deletions (
            kind TEXT NOT NULL,
            local_id TEXT NOT NULL,
            feishu_record_id TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_error TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (kind, local_id)
        )""")
    from matching_domain import backfill_metadata, ensure_schema as ensure_matching_schema
    ensure_matching_schema()
    backfill_metadata()


def mirror_record(kind: str, record: dict, *, partial: bool = False) -> dict | None:
    """Copy a Feishu record locally without overwriting pending local changes.

    Feishu update responses may contain only the fields changed by that request.
    Those responses must be merged into the local snapshot; full list/get results
    replace it so remote deletions can still be reflected locally.
    """
    kind = _kind(kind)
    record_id = str(record.get("record_id") or "")
    fields = record.get("fields") or {}
    if not record_id or not isinstance(fields, dict):
        raise ValueError("飞书记录格式无效")
    with connect() as db:
        tombstone = db.execute("SELECT 1 FROM portal_deletions WHERE kind = %s AND feishu_record_id = %s",
                               (kind, record_id)).fetchone()
        if tombstone:
            return None
        mapped = db.execute("SELECT local_id FROM portal_records WHERE kind = %s AND feishu_record_id = %s", (kind, record_id)).fetchone()
        local_id = mapped["local_id"] if mapped else record_id
        row = db.execute("""INSERT INTO portal_records
                (kind, local_id, feishu_record_id, fields, sync_state, synced_at)
            VALUES (%s, %s, %s, %s, 'synced', NOW())
            ON CONFLICT (kind, local_id) DO UPDATE SET
                feishu_record_id = EXCLUDED.feishu_record_id,
                fields = CASE WHEN %s
                    THEN portal_records.fields || EXCLUDED.fields
                    ELSE EXCLUDED.fields END,
                synced_at = NOW(),
                updated_at = NOW()
            WHERE portal_records.sync_state = 'synced'
            RETURNING *""", (kind, local_id, record_id, Jsonb(fields), partial)).fetchone()
        result = dict(row) if row else get_record(kind, local_id, db=db)
        if result:
            from matching_domain import save_metadata
            save_metadata(db, kind, local_id, dict(result["fields"]))
        return result


def get_record(kind: str, local_id: str, *, db=None) -> dict | None:
    kind = _kind(kind)
    owns_connection = db is None
    if owns_connection:
        context = connect()
        db = context.__enter__()
    try:
        row = db.execute("SELECT * FROM portal_records WHERE kind = %s AND local_id = %s", (kind, local_id)).fetchone()
        return dict(row) if row else None
    finally:
        if owns_connection:
            context.__exit__(None, None, None)


def merge_fields(kind: str, local_id: str, fields: dict, *, feishu_record_id: str | None = None) -> dict:
    """Commit locally and coalesce all unsynced changes for the same record."""
    kind = _kind(kind)
    if not local_id or not isinstance(fields, dict) or not fields:
        raise ValueError("本地保存内容无效")
    with connect() as db:
        current = db.execute("SELECT * FROM portal_records WHERE kind = %s AND local_id = %s FOR UPDATE", (kind, local_id)).fetchone()
        current_fields = dict(current["fields"]) if current else {}
        pending = dict(current["pending_fields"]) if current else {}
        current_fields.update(fields)
        pending.update(fields)
        remote_id = feishu_record_id or (current["feishu_record_id"] if current else None)
        version = int(current["version"] if current else 0) + 1
        row = db.execute("""INSERT INTO portal_records
                (kind, local_id, feishu_record_id, fields, pending_fields, sync_state, version,
                 synced_version, attempts, next_attempt_at, last_error, updated_at)
            VALUES (%s, %s, %s, %s, %s, 'pending', %s, 0, 0, NOW(), '', NOW())
            ON CONFLICT (kind, local_id) DO UPDATE SET
                feishu_record_id = COALESCE(EXCLUDED.feishu_record_id, portal_records.feishu_record_id),
                fields = EXCLUDED.fields,
                pending_fields = EXCLUDED.pending_fields,
                sync_state = 'pending',
                version = EXCLUDED.version,
                attempts = 0,
                next_attempt_at = NOW(),
                last_error = '',
                updated_at = NOW()
            RETURNING *""", (kind, local_id, remote_id, Jsonb(current_fields), Jsonb(pending), version)).fetchone()
        result = dict(row)
        from matching_domain import save_metadata
        save_metadata(db, kind, local_id, dict(result["fields"]))
    # Notify only after the transaction has committed. If the process exits
    # between commit and this signal, the durable fallback scan still finds it.
    _notify_sync()
    return result


def create_record(kind: str, fields: dict) -> dict:
    local_id = "local_" + uuid.uuid4().hex
    return merge_fields(kind, local_id, fields)


def list_records(kind: str) -> list[dict]:
    kind = _kind(kind)
    with connect() as db:
        return [dict(row) for row in db.execute("SELECT * FROM portal_records WHERE kind = %s ORDER BY updated_at, local_id", (kind,))]


def save_attachment(kind: str, local_id: str, field_name: str, item: dict, content: bytes,
                    *, remote_token: str | None = None) -> dict:
    """Keep attachment bytes in SQL so local features never depend on a stale file mirror."""
    kind = _kind(kind)
    token = str((item or {}).get("file_token") or "").strip()
    if not local_id or not field_name or not token or not isinstance(content, bytes) or not content:
        raise ValueError("附件缓存内容无效")
    name = str(item.get("name") or "")[:500]
    content_type = str(item.get("type") or item.get("content_type") or "application/octet-stream")[:200]
    if remote_token is None and not token.startswith("local_attachment_"):
        remote_token = token
    state = "synced" if remote_token else "pending"
    with connect() as db:
        row = db.execute("""INSERT INTO portal_attachments
                (kind, local_id, field_name, file_token, name, content_type, content, size,
                 feishu_file_token, sync_state, next_attempt_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    CASE WHEN %s = 'pending' THEN NOW() ELSE NULL END)
            ON CONFLICT (kind, local_id, field_name, file_token) DO UPDATE SET
                name = EXCLUDED.name,
                content_type = EXCLUDED.content_type,
                content = EXCLUDED.content,
                size = EXCLUDED.size,
                feishu_file_token = COALESCE(EXCLUDED.feishu_file_token, portal_attachments.feishu_file_token),
                sync_state = CASE WHEN COALESCE(EXCLUDED.feishu_file_token, portal_attachments.feishu_file_token) IS NULL
                    THEN 'pending' ELSE 'synced' END,
                next_attempt_at = CASE WHEN COALESCE(EXCLUDED.feishu_file_token, portal_attachments.feishu_file_token) IS NULL
                    THEN NOW() ELSE NULL END,
                last_error = '',
                updated_at = NOW()
            RETURNING kind, local_id, field_name, file_token, name, content_type, size,
                feishu_file_token, sync_state, updated_at""",
            (kind, local_id, field_name, token, name, content_type, content, len(content),
             remote_token, state, state)).fetchone()
        return dict(row)


def get_attachment(kind: str, local_id: str, field_name: str, file_token: str) -> dict | None:
    kind = _kind(kind)
    if not local_id or not field_name or not file_token:
        return None
    with connect() as db:
        row = db.execute("""SELECT kind, local_id, field_name, file_token, name, content_type,
                content, size, feishu_file_token, sync_state, updated_at
            FROM portal_attachments
            WHERE kind = %s AND local_id = %s AND field_name = %s AND file_token = %s""",
            (kind, local_id, field_name, file_token)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["content"] = bytes(result["content"])
        return result


def pending_attachments(limit: int = 25) -> list[dict]:
    with connect() as db:
        rows = db.execute("""SELECT * FROM portal_attachments
            WHERE sync_state IN ('pending', 'failed')
              AND (next_attempt_at IS NULL OR next_attempt_at <= NOW())
            ORDER BY updated_at, kind, local_id, field_name, file_token LIMIT %s""", (limit,)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["content"] = bytes(item["content"])
            result.append(item)
        return result


def mark_attachment_synced(kind: str, local_id: str, field_name: str, file_token: str,
                           feishu_file_token: str) -> None:
    with connect() as db:
        db.execute("""UPDATE portal_attachments SET feishu_file_token = %s, sync_state = 'synced',
                attempts = 0, next_attempt_at = NULL, last_error = '', updated_at = NOW()
            WHERE kind = %s AND local_id = %s AND field_name = %s AND file_token = %s""",
            (feishu_file_token, _kind(kind), local_id, field_name, file_token))


def mark_attachment_failed(kind: str, local_id: str, field_name: str, file_token: str, error: str) -> None:
    with connect() as db:
        row = db.execute("""SELECT attempts FROM portal_attachments
            WHERE kind = %s AND local_id = %s AND field_name = %s AND file_token = %s""",
            (_kind(kind), local_id, field_name, file_token)).fetchone()
        if row:
            attempts = int(row["attempts"]) + 1
            delay = min(300, 2 ** min(attempts, 8))
            db.execute("""UPDATE portal_attachments SET sync_state = 'failed', attempts = %s,
                    next_attempt_at = %s, last_error = %s
                WHERE kind = %s AND local_id = %s AND field_name = %s AND file_token = %s""",
                (attempts, _now() + timedelta(seconds=delay), str(error)[:2000], kind, local_id, field_name, file_token))


def fields_for_feishu(kind: str, local_id: str, fields: dict) -> dict:
    """Replace SQL-local attachment ids with their uploaded Feishu media tokens."""
    kind = _kind(kind)
    with connect() as db:
        rows = db.execute("""SELECT file_token, feishu_file_token FROM portal_attachments
            WHERE kind = %s AND local_id = %s""", (kind, local_id)).fetchall()
    mapping = {row["file_token"]: row["feishu_file_token"] for row in rows if row["feishu_file_token"]}

    def convert(value):
        if isinstance(value, list):
            return [convert(item) for item in value]
        if isinstance(value, dict):
            result = {key: convert(item) for key, item in value.items()}
            token = result.get("file_token")
            if isinstance(token, str) and token.startswith("local_attachment_"):
                if token not in mapping:
                    raise RuntimeError("附件仍在等待同步到飞书")
                return {"file_token": mapping[token]}
            return result
        return value

    return convert(fields)


def prune_attachments(kind: str, local_id: str, field_name: str, keep_tokens: list[str]) -> int:
    kind = _kind(kind)
    tokens = [str(value) for value in keep_tokens if value]
    with connect() as db:
        if tokens:
            result = db.execute("""DELETE FROM portal_attachments
                WHERE kind = %s AND local_id = %s AND field_name = %s
                  AND NOT (file_token = ANY(%s))""", (kind, local_id, field_name, tokens))
        else:
            result = db.execute("DELETE FROM portal_attachments WHERE kind = %s AND local_id = %s AND field_name = %s",
                                (kind, local_id, field_name))
        return result.rowcount


def delete_records(kind: str, local_ids: list[str]) -> int:
    """Delete SQL records first and durably queue their Feishu mirror deletion."""
    kind = _kind(kind)
    ids = list(dict.fromkeys(str(value) for value in local_ids if value))
    if not ids:
        return 0
    with connect() as db:
        rows = db.execute("SELECT local_id, feishu_record_id FROM portal_records WHERE kind = %s AND local_id = ANY(%s)",
                          (kind, ids)).fetchall()
        for row in rows:
            if row["feishu_record_id"]:
                db.execute("""INSERT INTO portal_deletions (kind, local_id, feishu_record_id)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (kind, local_id) DO UPDATE SET
                        feishu_record_id = EXCLUDED.feishu_record_id,
                        attempts = 0, next_attempt_at = NOW(), last_error = ''""",
                           (kind, row["local_id"], row["feishu_record_id"]))
        db.execute("DELETE FROM portal_preferences WHERE account_id = ANY(%s)", (ids,))
        db.execute("DELETE FROM portal_record_metadata WHERE kind = %s AND local_id = ANY(%s)", (kind, ids))
        result = db.execute("DELETE FROM portal_records WHERE kind = %s AND local_id = ANY(%s)", (kind, ids))
        count = result.rowcount
    _notify_sync()
    return count


def pending_deletions(limit: int = 25) -> list[dict]:
    with connect() as db:
        return [dict(row) for row in db.execute("""SELECT * FROM portal_deletions
            WHERE next_attempt_at <= NOW() ORDER BY created_at, kind, local_id LIMIT %s""", (limit,))]


def mark_deletion_synced(kind: str, local_id: str) -> None:
    with connect() as db:
        db.execute("DELETE FROM portal_deletions WHERE kind = %s AND local_id = %s", (_kind(kind), local_id))


def mark_deletion_failed(kind: str, local_id: str, error: str) -> None:
    with connect() as db:
        row = db.execute("SELECT attempts FROM portal_deletions WHERE kind = %s AND local_id = %s",
                         (_kind(kind), local_id)).fetchone()
        if row:
            attempts = int(row["attempts"]) + 1
            delay = min(300, 2 ** min(attempts, 8))
            db.execute("""UPDATE portal_deletions SET attempts = %s, next_attempt_at = %s, last_error = %s
                WHERE kind = %s AND local_id = %s""",
                       (attempts, _now() + timedelta(seconds=delay), str(error)[:2000], kind, local_id))


def pending_records(limit: int = 25) -> list[dict]:
    with connect() as db:
        rows = db.execute("""SELECT * FROM portal_records
            WHERE sync_state IN ('pending', 'failed')
              AND (next_attempt_at IS NULL OR next_attempt_at <= NOW())
            ORDER BY updated_at, kind, local_id LIMIT %s""", (limit,)).fetchall()
        return [dict(row) for row in rows]


def next_attempt_delay() -> float | None:
    """Seconds until the next durable retry is due, or None for an empty queue."""
    with connect() as db:
        row = db.execute("""SELECT EXTRACT(EPOCH FROM (MIN(next_attempt_at) - NOW())) AS delay FROM (
                SELECT next_attempt_at FROM portal_records WHERE sync_state IN ('pending', 'failed')
                UNION ALL SELECT next_attempt_at FROM portal_deletions
                UNION ALL SELECT next_attempt_at FROM portal_attachments WHERE sync_state IN ('pending', 'failed')
            ) queued""").fetchone()
        if not row or row["delay"] is None:
            return None
        return max(0.0, float(row["delay"]))


def mark_synced(kind: str, local_id: str, version: int, feishu_record_id: str) -> dict | None:
    kind = _kind(kind)
    with connect() as db:
        row = db.execute("""UPDATE portal_records SET
                feishu_record_id = %s,
                sync_state = CASE WHEN version = %s THEN 'synced' ELSE 'pending' END,
                pending_fields = CASE WHEN version = %s THEN '{}'::jsonb ELSE pending_fields END,
                synced_version = GREATEST(synced_version, %s),
                attempts = 0,
                next_attempt_at = CASE WHEN version = %s THEN NULL ELSE NOW() END,
                last_error = '',
                synced_at = NOW()
            WHERE kind = %s AND local_id = %s RETURNING *""",
            (feishu_record_id, version, version, version, version, kind, local_id)).fetchone()
        return dict(row) if row else None


def mark_failed(kind: str, local_id: str, version: int, error: str) -> dict | None:
    kind = _kind(kind)
    with connect() as db:
        current = db.execute("SELECT attempts FROM portal_records WHERE kind = %s AND local_id = %s", (kind, local_id)).fetchone()
        if not current:
            return None
        attempts = int(current["attempts"]) + 1
        delay = min(300, 2 ** min(attempts, 8))
        row = db.execute("""UPDATE portal_records SET
                sync_state = CASE WHEN version = %s THEN 'failed' ELSE 'pending' END,
                attempts = CASE WHEN version = %s THEN %s ELSE attempts END,
                next_attempt_at = CASE WHEN version = %s THEN %s ELSE NOW() END,
                last_error = CASE WHEN version = %s THEN %s ELSE last_error END
            WHERE kind = %s AND local_id = %s RETURNING *""",
            (version, version, attempts, version, _now() + timedelta(seconds=delay), version, str(error)[:2000], kind, local_id)).fetchone()
        return dict(row) if row else None


def save_schema(kind: str, schema: list[dict]) -> None:
    kind = _kind(kind)
    with connect() as db:
        db.execute("""INSERT INTO portal_field_schemas (kind, schema, fetched_at) VALUES (%s, %s, NOW())
            ON CONFLICT (kind) DO UPDATE SET schema = EXCLUDED.schema, fetched_at = NOW()""", (kind, Jsonb(schema)))


def get_schema(kind: str, max_age_seconds: int | None = 600) -> list[dict] | None:
    kind = _kind(kind)
    with connect() as db:
        row = db.execute("SELECT schema, fetched_at FROM portal_field_schemas WHERE kind = %s", (kind,)).fetchone()
        if not row:
            return None
        if max_age_seconds is not None and row["fetched_at"] < _now() - timedelta(seconds=max_age_seconds):
            return None
        return list(row["schema"])


def save_preference(account_id: str, key: str, value) -> None:
    """Persist portal-only UI state. This table is never read by the Feishu sync worker."""
    if not isinstance(account_id, str) or not account_id or len(account_id) > 200:
        raise ValueError("账户标识无效")
    if not isinstance(key, str) or not key or len(key) > 100:
        raise ValueError("偏好设置名称无效")
    with connect() as db:
        db.execute("""INSERT INTO portal_preferences (account_id, preference_key, value)
            VALUES (%s, %s, %s)
            ON CONFLICT (account_id, preference_key) DO UPDATE SET
                value = EXCLUDED.value,
                updated_at = NOW()""", (account_id, key, Jsonb(value)))


def get_preference(account_id: str, key: str, default=None):
    if not isinstance(account_id, str) or not account_id or not isinstance(key, str) or not key:
        return default
    with connect() as db:
        row = db.execute("SELECT value FROM portal_preferences WHERE account_id = %s AND preference_key = %s",
                         (account_id, key)).fetchone()
        return row["value"] if row else default


def queue_summary() -> dict:
    with connect() as db:
        rows = db.execute("SELECT sync_state, COUNT(*) AS count FROM portal_records GROUP BY sync_state").fetchall()
        result = {"synced": 0, "pending": 0, "failed": 0}
        result.update({row["sync_state"]: row["count"] for row in rows})
        result["deletions"] = db.execute("SELECT COUNT(*) AS count FROM portal_deletions").fetchone()["count"]
        result["attachments_pending"] = db.execute("""SELECT COUNT(*) AS count FROM portal_attachments
            WHERE sync_state IN ('pending', 'failed')""").fetchone()["count"]
        return result
