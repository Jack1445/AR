import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ai_settings


class FakeKeyring:
    def __init__(self):
        self.values = {}

    def get_password(self, service, account):
        return self.values.get((service, account))

    def set_password(self, service, account, value):
        self.values[(service, account)] = value

    def delete_password(self, service, account):
        self.values.pop((service, account), None)


class AISettingsTests(unittest.TestCase):
    def test_connection_uses_current_form_values_without_saving(self):
        requests = []

        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return None
            def read(self, _size): return b'{"choices":[{"message":{"content":"ok"}}]}'

        class Opener:
            def open(self, request, timeout):
                requests.append((request, timeout))
                return Response()

        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            config = Path(folder) / "ai_config.json"
            keyring = FakeKeyring()
            with patch.object(ai_settings, "CONFIG", config), patch.object(ai_settings, "_keyring", return_value=keyring), patch.object(ai_settings.urllib.request, "build_opener", return_value=Opener()):
                result = ai_settings.test_connection({"base_url": "https://example.com/v1", "model": "draft-model", "api_key": "draft-key"})
            self.assertTrue(result["ok"])
            self.assertEqual(result["model"], "draft-model")
            self.assertFalse(config.exists())
            self.assertFalse(keyring.values)
            request, timeout = requests[0]
            self.assertEqual(request.full_url, "https://example.com/v1/chat/completions")
            self.assertEqual(request.get_header("Authorization"), "Bearer draft-key")
            self.assertEqual(json.loads(request.data)["model"], "draft-model")
            self.assertEqual(timeout, 30)

    def test_api_key_is_saved_only_in_keyring(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            keyring = FakeKeyring()
            with patch.object(ai_settings, "CONFIG", Path(folder) / "ai_config.json"), patch.object(ai_settings, "_keyring", return_value=keyring):
                result = ai_settings.save_settings({"base_url": "https://example.com/v1", "model": "sample-model", "api_key": "private-key"})
                self.assertTrue(result["has_key"])
                self.assertNotIn("api_key", result)
                self.assertNotIn("private-key", ai_settings.CONFIG.read_text(encoding="utf-8"))
                self.assertEqual(json.loads(ai_settings.CONFIG.read_text(encoding="utf-8"))["model"], "sample-model")
                self.assertEqual(keyring.get_password(ai_settings.SERVICE, ai_settings.ACCOUNT), "private-key")

    def test_invalid_connection_address_is_rejected(self):
        self.assertEqual(ai_settings._valid_base_url("https://example.com"), "https://example.com/v1")
        self.assertEqual(ai_settings._valid_base_url("https://example.com/v1/models"), "https://example.com/v1")
        for url in ["http://example.com/v1", "https://user:pass@example.com/v1", "https://example.com/v1?key=secret"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                ai_settings._valid_base_url(url)

    def test_tag_concurrency_is_bounded_and_persisted(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            with patch.object(ai_settings, "CONFIG", Path(folder) / "ai_config.json"), patch.object(ai_settings, "_keyring", return_value=FakeKeyring()):
                self.assertEqual(ai_settings.read_settings()["max_concurrency"], 3)
                saved = ai_settings.save_settings({"base_url": "https://example.com/v1", "model": "sample-model", "max_concurrency": 4})
                self.assertEqual(saved["max_concurrency"], 4)
                self.assertEqual(json.loads(ai_settings.CONFIG.read_text(encoding="utf-8"))["max_concurrency"], 4)
                for invalid in (0, 11, 2.5, True, "3"):
                    with self.subTest(value=invalid), self.assertRaises(ValueError):
                        ai_settings.save_settings({"base_url": "https://example.com/v1", "model": "sample-model", "max_concurrency": invalid})


if __name__ == "__main__":
    unittest.main()
