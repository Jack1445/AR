import unittest
from unittest.mock import Mock, patch

import portal_data
import portal_server
import recommendation_store
from ar import FeishuError


class PortalServerStartupTests(unittest.TestCase):
    def test_invalid_feishu_config_does_not_block_http_server(self):
        server = Mock()
        server.serve_forever.side_effect = KeyboardInterrupt
        with (
            patch.object(recommendation_store, "ensure_schema"),
            patch.object(portal_server, "ensure_schema", side_effect=FeishuError("invalid config")),
            patch.object(portal_data, "sync_business_outcomes", side_effect=FeishuError("invalid config")),
            patch.object(portal_server, "ThreadingHTTPServer", return_value=server),
        ):
            portal_server.main()

        server.serve_forever.assert_called_once_with()
        server.server_close.assert_called_once_with()

    def test_missing_output_table_does_not_block_http_server(self):
        server = Mock()
        server.serve_forever.side_effect = KeyboardInterrupt
        with (
            patch.object(recommendation_store, "ensure_schema"),
            patch.object(portal_server, "ensure_schema", side_effect=ValueError("missing candidate_output")),
            patch.object(portal_data, "sync_business_outcomes", side_effect=ValueError("missing candidate_output")),
            patch.object(portal_server, "ThreadingHTTPServer", return_value=server),
        ):
            portal_server.main()

        server.serve_forever.assert_called_once_with()
        server.server_close.assert_called_once_with()
    def test_missing_output_table_reports_configuration_error(self):
        with patch.object(portal_data, "TABLES", []):
            with self.assertRaisesRegex(ValueError, "缺少 candidate_output 表"):
                portal_data._table("candidate_output")


if __name__ == "__main__":
    unittest.main()
