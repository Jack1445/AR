import unittest

from ar import FeishuError
from setup_config import classify_tables, resolve_base_url


class FakeClient:
    def __init__(self, node):
        self.node = node
        self.calls = []

    def request(self, method, path, *, params=None):
        self.calls.append((method, path, params))
        return {"node": self.node}


class SetupConfigTests(unittest.TestCase):
    def test_wiki_bitable_link_resolves_without_using_node_token_as_app_token(self):
        client = FakeClient({"obj_type": "bitable", "obj_token": "baseToken123"})
        result = resolve_base_url(client, "https://example.feishu.cn/wiki/wikiNode123?table=table456&from=copy_link")
        self.assertEqual(result, "https://example.feishu.cn/base/baseToken123?table=table456")
        self.assertEqual(client.calls, [("GET", "/wiki/v2/spaces/get_node", {"token": "wikiNode123", "obj_type": "wiki"})])

    def test_other_wiki_document_is_rejected(self):
        with self.assertRaisesRegex(FeishuError, "不是多维表格"):
            resolve_base_url(FakeClient({"obj_type": "docx", "obj_token": "doc123"}), "https://example.feishu.cn/wiki/wikiNode123")

    def test_maps_five_active_tables_and_excludes_old_archive(self):
        names = ["候选人侧简历收集--外部", "校友JD收集", "AR-校友侧-jiakai", "AR-候选人-jiakai", "校友流转简历", "2026.11.1（仅存档，旧版）候选人侧简历收集--外部"]
        tables = [{"table_id": f"tbl{index}", "name": name} for index, name in enumerate(names)]
        selected = classify_tables(tables)
        self.assertEqual([table["id"] for table in selected], ["tbl0", "tbl1", "tbl2", "tbl3", "tbl4"])
        self.assertEqual([table["kind"] for table in selected], ["candidate", "job", "alumni_output", "candidate_output", "resume_flow"])

    def test_legacy_three_table_base_keeps_archive(self):
        names = ["候选人侧简历收集--外部", "（仅存档，旧版）候选人侧简历收集--外部", "校友JD收集"]
        selected = classify_tables([{"table_id": f"tbl{index}", "name": name} for index, name in enumerate(names)])
        self.assertEqual([table["id"] for table in selected], ["tbl0", "tbl1", "tbl2"])
        self.assertTrue(selected[1]["archived"])


if __name__ == "__main__":
    unittest.main()
