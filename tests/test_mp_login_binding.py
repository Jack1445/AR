import unittest
from unittest.mock import patch

import portal_data


class MemoryFeishuClient:
    def __init__(self, rows):
        self.rows = rows
        self.writes = []

    def pages(self, _path):
        return list(self.rows)

    def request(self, method, path, body=None):
        record = self.rows[0]
        self.writes.append((method, path, body))
        if method == "PUT":
            record["fields"].update(body["fields"])
            return {"record": record}
        raise AssertionError(f"unexpected request: {method}")


class MpLoginBindingTests(unittest.TestCase):
    def test_matching_phone_binds_existing_unbound_candidate(self):
        row = {"record_id": "recLegacy001", "fields": {"AR_记录类型": "account", "AR_手机号": "13800138000"}}
        client = MemoryFeishuClient([row])
        with patch.object(portal_data, "_client", return_value=(client, "app")), patch.object(portal_data, "_records", side_effect=lambda _client, _app, _kind: client.rows):
            identity = portal_data.login_with_mp("candidate", "mp-user-1", "13800138000")

        self.assertEqual(identity, {"id": "recLegacy001", "role": "candidate", "phone": "13800138000"})
        self.assertEqual(row["fields"]["AR_MP用户ID"], "mp-user-1")
        self.assertEqual([write[0] for write in client.writes], ["PUT"])

    def test_matching_phone_does_not_overwrite_another_mp_binding(self):
        row = {"record_id": "recLegacy001", "fields": {"AR_记录类型": "account", "AR_手机号": "13800138000", "AR_MP用户ID": "mp-user-original"}}
        client = MemoryFeishuClient([row])
        with patch.object(portal_data, "_client", return_value=(client, "app")), patch.object(portal_data, "_records", side_effect=lambda _client, _app, _kind: client.rows):
            with self.assertRaises(portal_data.MpLoginError) as raised:
                portal_data.login_with_mp("candidate", "mp-user-new", "13800138000")

        self.assertEqual(raised.exception.code, "phone_in_use")
        self.assertEqual(row["fields"]["AR_MP用户ID"], "mp-user-original")
        self.assertEqual(client.writes, [])

    def test_ambiguous_phone_matches_are_not_auto_bound(self):
        rows = [
            {"record_id": "recLegacy001", "fields": {"AR_记录类型": "account", "AR_手机号": "13800138000"}},
            {"record_id": "recLegacy002", "fields": {"AR_记录类型": "account", "AR_手机号": "13800138000"}},
        ]
        client = MemoryFeishuClient(rows)
        with patch.object(portal_data, "_client", return_value=(client, "app")), patch.object(portal_data, "_records", side_effect=lambda _client, _app, _kind: client.rows):
            with self.assertRaises(portal_data.MpLoginError) as raised:
                portal_data.login_with_mp("candidate", "mp-user-1", "13800138000")

        self.assertEqual(raised.exception.code, "phone_in_use")
        self.assertTrue(all(not row["fields"].get("AR_MP用户ID") for row in rows))
        self.assertEqual(client.writes, [])

    def test_alumni_unique_phone_match_binds_unbound_account(self):
        row = {"record_id": "recLegacy001", "fields": {"AR_记录类型": "account", "AR_手机号": "13800138000"}}
        client = MemoryFeishuClient([row])
        with patch.object(portal_data, "_client", return_value=(client, "app")), patch.object(portal_data, "_records", side_effect=lambda _client, _app, _kind: client.rows):
            identity = portal_data.login_with_mp("alumni", "mp-user-1", "13800138000")

        self.assertEqual(identity, {"id": "recLegacy001", "role": "alumni", "phone": "13800138000"})
        self.assertEqual(row["fields"]["AR_MP用户ID"], "mp-user-1")
        self.assertEqual([write[0] for write in client.writes], ["PUT"])


if __name__ == "__main__":
    unittest.main()
