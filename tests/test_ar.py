import json
import tempfile
import unittest
from pathlib import Path

import ar


class FakeClient:
    def pages(self, path):
        if path.endswith("/fields"):
            return iter([{"field_id": "fld1", "field_name": "附件"}])
        if path.endswith("/records"):
            return iter([
                {"record_id": "rec1", "fields": {"附件": [{"file_token": "file1", "name": "notes.pdf"}]}},
                {"record_id": "rec2", "fields": {"附件": [{"file_token": "file1", "name": "notes.pdf"}]}},
            ])
        raise AssertionError(path)

    def download_attachment(self, item, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"file content")


class ArTests(unittest.TestCase):
    def test_target_identifiers(self):
        self.assertEqual(
            ar.identifiers("https://example.feishu.cn/base/exampleAppToken?table=exampleTableId&view=exampleView"),
            ("exampleAppToken", "exampleTableId"),
        )

    def test_pull_keeps_records_and_downloads_unique_attachments(self):
        with tempfile.TemporaryDirectory(dir=ar.ROOT) as directory:
            ar.pull(FakeClient(), "base1", ["table1"], Path(directory))
            folder = Path(directory) / "table1"
            self.assertEqual(len(json.loads((folder / "records.json").read_text(encoding="utf-8"))), 2)
            self.assertEqual((folder / "attachments" / "file1_notes.pdf").read_bytes(), b"file content")
            self.assertEqual(len(json.loads((folder / "attachments.json").read_text(encoding="utf-8"))), 1)


if __name__ == "__main__":
    unittest.main()
