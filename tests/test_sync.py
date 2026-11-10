import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ar
import sync


class FakeClient:
    def __init__(self, records):
        self.records = records

    def pages(self, path):
        if path.endswith("/fields"):
            return iter([{"field_id": "fld1", "field_name": "姓名 2", "type": 1}])
        if path.endswith("/records"):
            return iter(self.records)
        raise AssertionError(path)

    def download_attachment(self, item, path):
        raise AssertionError("This test has no attachments")


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.table = {"id": "tblTest", "name": "测试表", "kind": "candidate", "archived": False}
        self.root = tempfile.TemporaryDirectory(dir=ar.ROOT)
        self.output = Path(self.root.name)
        self.folder = self.output / self.table["id"]
        self.folder.mkdir()
        ar.save_json(self.folder / "fields.json", [{"field_id": "fld1", "field_name": "姓名 2", "type": 1}])
        ar.save_json(self.folder / "records.json", [{"record_id": "rec1", "fields": {"姓名 2": "测试"}}])
        ar.save_json(self.folder / "attachments.json", [])
        self.tables_patch = patch.object(sync, "TABLES", [self.table])
        self.build_patch = patch.object(sync, "build_snapshot")
        self.tables_patch.start()
        self.build = self.build_patch.start()

    def tearDown(self):
        self.tables_patch.stop()
        self.build_patch.stop()
        self.root.cleanup()

    def test_unchanged_data_does_not_write_files(self):
        before = {name: (self.folder / name).stat().st_mtime_ns for name in ("fields.json", "records.json", "attachments.json")}
        client = FakeClient([{"record_id": "rec1", "fields": {"姓名 2": "测试"}}])
        result = sync.sync_once(client, "base", self.output)
        after = {name: (self.folder / name).stat().st_mtime_ns for name in before}
        self.assertFalse(result["changed"])
        self.assertEqual(before, after)
        self.build.assert_not_called()

    def test_changed_record_updates_snapshot_once(self):
        client = FakeClient([{"record_id": "rec1", "fields": {"姓名 2": "新名字"}}])
        result = sync.sync_once(client, "base", self.output)
        self.assertTrue(result["changed"])
        self.assertEqual(result["tables"][0]["edited"], 1)
        self.assertEqual(json.loads((self.folder / "records.json").read_text(encoding="utf-8"))[0]["fields"]["姓名 2"], "新名字")
        self.build.assert_called_once()
        self.build.reset_mock()
        second = sync.sync_once(client, "base", self.output)
        self.assertFalse(second["changed"])
        self.build.assert_not_called()

    def test_temporary_attachment_urls_do_not_count_as_change(self):
        first = [{"record_id": "rec1", "fields": {"简历": [{"file_token": "box1", "name": "cv.pdf", "url": "old"}]}}]
        second = [{"record_id": "rec1", "fields": {"简历": [{"file_token": "box1", "name": "cv.pdf", "url": "new"}]}}]
        self.assertTrue(sync.same_records(first, second))


if __name__ == "__main__":
    unittest.main()
