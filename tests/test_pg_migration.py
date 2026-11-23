import sqlite3
import tempfile
import unittest
from pathlib import Path

import ai_history
import migrate_sqlite
import recommendation_store
from tests.pg_test import isolated_schema


class MigrationTests(unittest.TestCase):
    def setUp(self):
        isolated_schema(self)

    def test_import_preserves_rows_ids_and_refuses_reimport(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            with sqlite3.connect(folder / "ai_history.sqlite3") as db:
                db.execute("""CREATE TABLE ai_calls (id INTEGER PRIMARY KEY, started_at TEXT, finished_at TEXT, kind TEXT,
                    target_id TEXT, target_label TEXT, model TEXT, status TEXT, system_prompt TEXT, user_prompt TEXT,
                    raw_response TEXT DEFAULT '', error TEXT DEFAULT '', elapsed_seconds REAL)""")
                db.execute("INSERT INTO ai_calls (id, started_at, kind, target_id, target_label, model, status, system_prompt, user_prompt) VALUES (7, 'now', 'evaluation', 'x', 'name', 'model', 'success', 's', 'private resume')")
            with sqlite3.connect(folder / "recommendations.sqlite3") as db:
                db.execute("""CREATE TABLE recommendations (id TEXT PRIMARY KEY, job_id TEXT, candidate_id TEXT, owner_id TEXT,
                    candidate_name TEXT, candidate_profile TEXT, stars INTEGER, reason TEXT, status TEXT, interest TEXT,
                    created_at TEXT, updated_at TEXT)""")
                db.execute("INSERT INTO recommendations VALUES ('legacy', 'job', 'candidate', 'owner', 'name', 'profile', 4, 'reason', '待反馈', '', 'now', 'now')")
                db.execute("CREATE TABLE feedback_events (id INTEGER PRIMARY KEY, recommendation_id TEXT, from_status TEXT, to_status TEXT, changed_at TEXT)")
                db.execute("INSERT INTO feedback_events VALUES (9, 'legacy', '待反馈', '面试中', 'now')")
            self.assertEqual(migrate_sqlite.migrate(folder), {"ai_calls": 1, "recommendations": 1, "feedback_events": 1})
            self.assertEqual(ai_history.get_call(7)["user_prompt"], "private resume")
            self.assertEqual(recommendation_store.get("legacy")["candidate_id"], "candidate")
            with recommendation_store._connect() as db:
                self.assertEqual(db.execute("SELECT to_status FROM feedback_events WHERE id = 9").fetchone()["to_status"], "面试中")
            next_id, _ = ai_history.start_call("evaluation", "x", "name", "model", "s", "p")
            self.assertEqual(next_id, 8)
            with self.assertRaisesRegex(ValueError, "已有"):
                migrate_sqlite.migrate(folder)

    def test_same_recommendation_is_created_once_concurrently(self):
        from concurrent.futures import ThreadPoolExecutor
        recommendation_store.ensure_schema()
        def create(_):
            return recommendation_store.create("job", "candidate", "owner", "name", "profile", 4, "reason")["id"]
        with ThreadPoolExecutor(max_workers=8) as pool:
            ids = list(pool.map(create, range(16)))
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(len(recommendation_store.all_rows()), 1)


if __name__ == "__main__":
    unittest.main()
