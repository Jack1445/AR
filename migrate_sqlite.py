"""One-time import of local SQLite history into PostgreSQL; keeps source files intact."""

import sqlite3
from contextlib import closing
from pathlib import Path

import ai_history
import recommendation_store
from pg_store import connect
from psycopg import sql


ROOT = Path(__file__).resolve().parent
TABLES = {
    "ai_history.sqlite3": ("ai_calls",),
    "recommendations.sqlite3": ("recommendations", "feedback_events"),
}


def migrate(directory: Path = ROOT) -> dict[str, int]:
    ai_history.ensure_schema()
    recommendation_store.ensure_schema()
    counts = {}
    with connect() as target:
        for table in ("ai_calls", "recommendations", "feedback_events"):
            existing = target.execute(f"SELECT count(*) AS count FROM {table}").fetchone()["count"]
            if existing:
                raise ValueError(f"{table} 已有 {existing} 行，请先备份并确认目标库为空")
        for filename, tables in TABLES.items():
            source_path = directory / filename
            if not source_path.is_file():
                continue
            with closing(sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)) as source:
                for table in tables:
                    columns = [row[1] for row in source.execute(f"PRAGMA table_info({table})")]
                    if not columns:
                        raise ValueError(f"{source_path} 缺少 {table} 表")
                    rows = source.execute(f"SELECT * FROM {table}").fetchall()
                    placeholders = ", ".join(["%s"] * len(columns))
                    with target.cursor() as cursor:
                        statement = sql.SQL("INSERT INTO {} ({}) VALUES (" + placeholders + ")").format(
                            sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, columns)))
                        cursor.executemany(statement, rows)
                    counts[table] = len(rows)
        for table in ("ai_calls", "feedback_events"):
            target.execute("SELECT setval(pg_get_serial_sequence(%s, 'id'), GREATEST((SELECT COALESCE(max(id), 0) FROM " + table + "), 1), (SELECT count(*) > 0 FROM " + table + "))", (table,))
    return counts


if __name__ == "__main__":
    print(migrate())
