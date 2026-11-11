import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import match_engine


RULES = {"categories": [{"name": "专业背景", "tags": ["理工"]}, {"name": "行业与技术", "tags": ["LLM"]}, {"name": "岗位方向", "tags": ["技术"]}]}
TEST_TABLES = [{"id": "testCandidateTable", "name": "候选人", "kind": "candidate", "archived": False}]


class MatchingTests(unittest.TestCase):
    def test_pdf_extraction_does_not_open_a_console(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            table_id = TEST_TABLES[0]["id"]
            pdf = Path(folder) / table_id / "attachments" / "resume.pdf"
            pdf.parent.mkdir(parents=True)
            pdf.write_bytes(b"dummy")
            attachments = [{"record_id": "rec1", "file": "attachments/resume.pdf"}]
            with patch.object(match_engine, "DATA", Path(folder)), patch.object(match_engine, "TABLES", TEST_TABLES), patch.object(match_engine, "read_json", return_value=attachments), patch.object(match_engine.shutil, "which", return_value="pdftotext"), patch.object(match_engine.subprocess, "run", return_value=SimpleNamespace(stdout=b"resume text")) as run:
                self.assertEqual(match_engine._resume_text("rec1"), "resume text")
                self.assertEqual(run.call_args.kwargs["creationflags"], getattr(match_engine.subprocess, "CREATE_NO_WINDOW", 0))

    def test_tagging_reuses_unchanged_profile_and_rules(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            with patch.object(match_engine, "STATE_FILE", Path(folder) / "state.json"), patch.object(match_engine, "candidate_profile", return_value="Python 和 LLM 项目经验"), patch.object(match_engine, "_ai_json", return_value={"tags": {"专业背景": ["理工"], "行业与技术": ["LLM"], "岗位方向": ["技术"]}, "summary": "资料有明确证据"}) as ai:
                payload = {"kind": "candidate", "id": "rec1", "rules": RULES}
                first = match_engine.tag_item(payload)
                second = match_engine.tag_item(payload)
                changed_rules = match_engine.tag_item({**payload, "rules": {**RULES, "instructions": "只按明确项目经历归类"}})
                self.assertFalse(first["cached"])
                self.assertTrue(second["cached"])
                self.assertFalse(changed_rules["cached"])
                self.assertEqual(ai.call_count, 2)
                self.assertEqual(second["tags"]["行业与技术"], ["LLM"])

    def test_custom_category_is_used_and_unknown_tags_are_dropped(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            custom = {"categories": [{"name": "语言能力", "tags": ["英语", "日语"]}], "instructions": "只依据明确证据"}
            with patch.object(match_engine, "STATE_FILE", Path(folder) / "state.json"), patch.object(match_engine, "candidate_profile", return_value="英语工作语言"), patch.object(match_engine, "_ai_json", return_value={"tags": {"语言能力": ["英语", "法语"]}, "summary": "明确提到英语"}):
                result = match_engine.tag_item({"kind": "candidate", "id": "rec1", "rules": custom})
                self.assertEqual(result["tags"], {"语言能力": ["英语"]})

    def test_parallel_tags_keep_each_candidate_result(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            with patch.object(match_engine, "STATE_FILE", Path(folder) / "state.json"), patch.object(match_engine, "candidate_profile", side_effect=lambda item_id: f"资料 {item_id}"), patch.object(match_engine, "_ai_json", return_value={"tags": {"专业背景": ["理工"]}, "summary": "有证据"}):
                payloads = [{"kind": "candidate", "id": f"rec{i}", "rules": RULES} for i in range(8)]
                with ThreadPoolExecutor(max_workers=4) as pool:
                    results = list(pool.map(match_engine.tag_item, payloads))
                self.assertEqual(len(results), 8)
                self.assertEqual(len(match_engine.public_state()["candidate_tags"]), 8)

    def test_tag_plan_skips_unchanged_records_and_selects_changed_rules(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            records = [{"record_id": "rec1"}, {"record_id": "rec2"}]
            original_read_json = match_engine.read_json
            with patch.object(match_engine, "STATE_FILE", Path(folder) / "state.json"), patch.object(match_engine, "TABLES", TEST_TABLES), patch.object(match_engine, "read_json", side_effect=lambda path, default: records if str(path).endswith("records.json") else original_read_json(path, default)), patch.object(match_engine, "candidate_profile", side_effect=lambda item_id: "已有资料" if item_id == "rec1" else "新资料"), patch.object(match_engine, "_ai_json", return_value={"tags": {"专业背景": ["理工"], "行业与技术": [], "岗位方向": []}, "summary": "测试"}):
                match_engine.tag_item({"kind": "candidate", "id": "rec1", "rules": RULES})
                plan = match_engine.tag_plan({"kind": "candidate", "rules": RULES})
                self.assertEqual(plan["cached_count"], 1)
                self.assertEqual(plan["pending_ids"], ["rec2"])
                updated = match_engine.tag_plan({"kind": "candidate", "rules": {**RULES, "instructions": "新规则"}})
                self.assertEqual(updated["pending_ids"], ["rec1", "rec2"])

    def test_evaluation_is_saved_per_candidate_and_jd(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            with patch.object(match_engine, "STATE_FILE", Path(folder) / "state.json"), patch.object(match_engine, "candidate_profile", return_value="候选人资料"), patch.object(match_engine, "_job_text", return_value="岗位原文"), patch.object(match_engine, "read_settings", return_value={"model": "mock-model", "base_url": "https://example.com/v1"}), patch.object(match_engine, "_ai_json", return_value={"stars": 4, "reason": "具有相关经历"}) as ai:
                payload = {"job_id": "jd1", "jd_text": "岗位原文", "candidate_id": "rec1", "common_prompt": "公共规则", "job_prompt": "岗位规则"}
                first = match_engine.evaluate_item(payload)
                second = match_engine.evaluate_item(payload)
                changed = match_engine.evaluate_item({**payload, "job_prompt": "新岗位规则"})
                self.assertEqual(first["stars"], 4)
                self.assertTrue(second["cached"])
                self.assertFalse(changed["cached"])
                self.assertEqual(ai.call_count, 2)


if __name__ == "__main__":
    unittest.main()
