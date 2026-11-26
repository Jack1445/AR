import os
import unittest
from unittest.mock import patch

import match_store
import match_engine
import matching_domain
import portal_store
import sql_catalog
from tests.pg_test import isolated_schema


class LocationNormalizationTests(unittest.TestCase):
    def test_known_and_free_text_locations_are_deterministic(self):
        self.assertEqual(matching_domain.normalize_locations("北京, 上海市"), ["北京", "上海"])
        self.assertEqual(matching_domain.normalize_locations("长沙市"), ["文本:长沙"])


class SqlMatchingDomainTests(unittest.TestCase):
    def setUp(self):
        isolated_schema(self)
        self.env = patch.dict(os.environ, {"AR_LOCAL_PRIMARY": "1"})
        self.env.start()
        self.addCleanup(self.env.stop)
        portal_store.ensure_schema()
        match_store.ensure_schema()

    def test_metadata_uses_current_text_base_field_and_position_codes(self):
        portal_store.merge_fields("candidate_output", "candidate-one", {
            "意向base地（eg.北京,上海）": "北京、长沙",
            "意向岗位": ["技术研发", "产品经理"],
        })
        metadata = matching_domain.get_metadata("candidate_output", "candidate-one")
        self.assertEqual(metadata["normalized_locations"], ["北京", "文本:长沙"])
        self.assertEqual(metadata["intent_position_codes"], ["tech_rd", "product"])

    def test_match_artifacts_round_trip_in_sql(self):
        match_store.replace_state({
            "candidate_tags": {"candidate-one": {"position_codes": ["tech_rd"]}},
            "job_tags": {}, "evaluations": {},
        })
        self.assertEqual(match_store.state()["candidate_tags"]["candidate-one"]["position_codes"], ["tech_rd"])

    def test_candidate_tag_profile_reads_resume_bytes_from_sql(self):
        portal_store.merge_fields("candidate_output", "candidate-one", {
            "AR_记录类型": "account",
            "简历": [{"file_token": "resume-one", "name": "resume.txt"}],
        })
        portal_store.save_attachment("candidate_output", "candidate-one", "简历", {
            "file_token": "resume-one", "name": "resume.txt", "content_type": "text/plain",
        }, "经济学专业，具有财务分析和数据分析项目经历".encode("utf-8"))
        profile = match_engine.candidate_tag_profile("candidate-one")
        self.assertIn("简历正文", profile)
        self.assertIn("经济学专业", profile)

    def test_missing_sql_attachment_is_not_silently_treated_as_empty_resume(self):
        portal_store.merge_fields("candidate_output", "candidate-one", {
            "AR_记录类型": "account",
            "简历": [{"file_token": "missing", "name": "resume.pdf"}],
        })
        with self.assertRaisesRegex(ValueError, "尚未同步到本地数据库"):
            match_engine.candidate_tag_profile("candidate-one")

    def test_admin_catalog_reads_portal_records_from_sql(self):
        portal_store.merge_fields("candidate_output", "candidate-one", {
            "AR_记录类型": "account", "姓名": "测试候选人", "简历": [{"file_token": "x"}],
        })
        portal_store.merge_fields("alumni_output", "job-one", {
            "AR_记录类型": "job", "AR_企业名称": "测试企业", "AR_JD正文": "测试 JD",
        })
        result = sql_catalog.catalog()
        candidate_table = next(item for item in result["tables"] if item["kind"] == "candidate_output")
        self.assertEqual(candidate_table["source"], "postgresql")
        self.assertEqual(candidate_table["records"][0]["record_id"], "candidate-one")
        self.assertEqual(candidate_table["records"][0]["fields"]["姓名"], "测试候选人")

    def test_hard_filter_reads_records_and_position_codes_from_sql(self):
        portal_store.merge_fields("candidate_output", "candidate-one", {
            "AR_记录类型": "account",
            "意向base地（eg.北京,上海）": "北京",
            "意向出勤方式": "线上线下结合",
            "当前求职类别（多选）": ["社职"],
            "意向岗位": ["产品经理"],
            "最早到岗时间": "2026-11-01",
            "每周到岗天数": "5天",
        })
        portal_store.merge_fields("alumni_output", "job-one", {
            "AR_记录类型": "job", "AR_JD正文": "产品岗位",
            "工作地点": "北京", "出勤方式": "线下", "岗位类别": ["社职"],
            "最晚到岗日期": "2026-11-08", "每周最少到岗天数": "4天",
        })
        match_store.replace_state({
            "candidate_tags": {"candidate-one": {"tags": {}, "position_codes": ["tech_rd"]}},
            "job_tags": {"job-one:2:0": {"tags": {}, "position_codes": ["product"]}},
            "evaluations": {},
        })
        result = match_engine.hard_filter_result("job-one:2:0", "candidate-one")
        self.assertTrue(result["passed"])
        self.assertEqual(result["failed"], [])


if __name__ == "__main__":
    unittest.main()
