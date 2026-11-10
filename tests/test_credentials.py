import unittest
from unittest.mock import Mock, patch

import credentials


class CredentialTests(unittest.TestCase):
    def test_save_uses_windows_keyring_backend(self):
        backend = Mock()
        with patch.dict("os.environ", {"FEISHU_APP_ID": "cli_test", "FEISHU_APP_SECRET": "secret_test"}), patch.object(credentials, "_keyring", return_value=backend):
            credentials.save_credentials_from_environment()
        backend.set_password.assert_any_call(credentials.SERVICE, "app_id", "cli_test")
        backend.set_password.assert_any_call(credentials.SERVICE, "app_secret", "secret_test")

    def test_saved_credentials_are_used_when_environment_is_empty(self):
        backend = Mock()
        backend.get_password.side_effect = ["cli_test", "secret_test"]
        with patch.dict("os.environ", {"FEISHU_APP_ID": "", "FEISHU_APP_SECRET": ""}), patch.object(credentials, "_keyring", return_value=backend):
            self.assertEqual(credentials.get_credentials(), ("cli_test", "secret_test"))


if __name__ == "__main__":
    unittest.main()
