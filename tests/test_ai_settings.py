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


if __name__ == "__main__":
    unittest.main()
