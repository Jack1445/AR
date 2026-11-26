import tempfile
import unittest
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import match_engine


RULES = {"categories": [{"name": "专业背景", "tags": ["理工"]}, {"name": "行业与技术", "tags": ["LLM"]}, {"name": "岗位方向", "tags": ["技术"]}]}
TEST_TABLES = [{"id": "testCandidateTable", "name": "候选人", "kind": "candidate", "archived": False}]


def evaluation_result(stars=4):
    return {
        "stars": stars,
        "summary": "具备相关经历，但部分能力仍需核实",
        "details": [{"resume_evidence": "参与相关项目", "jd_requirement": "具备相关项目经验", "analysis": "经历与职责直接对应"}],
    }


class MatchingTests(unittest.TestCase):
    def test_pdf_tool_finds_bundled_runtime_when_path_is_minimal(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            root = Path(folder)
            executable = root / "WindowsApps" / "OpenAI.CodexPrimaryRuntime.v1_1_x64__test" / "dependencies" / "native" / "poppler" / "Library" / "bin" / "pdftoppm.exe"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"")
            with patch.object(match_engine.shutil, "which", return_value=None), \
                 patch.dict(match_engine.os.environ, {"ProgramFiles": str(root)}, clear=False):
                self.assertEqual(match_engine._pdf_tool("pdftoppm"), str(executable))

    def test_pdf_page_images_falls_back_when_poppler_is_not_on_path(self):
        try:
            import pymupdf
        except ImportError:
            self.skipTest("pymupdf is installed from requirements.txt")
        document = pymupdf.open()
        document.new_page().insert_text((72, 72), "resume")
        content = document.tobytes()
        document.close()
        with patch.object(match_engine, "_pdf_tool", return_value=None):
            images = match_engine._pdf_page_images(content)
        self.assertEqual(len(images), 1)
        self.assertTrue(images[0].startswith(b"\xff\xd8"))

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
            with patch.object(match_engine, "STATE_FILE", Path(folder) / "state.json"), patch.object(match_engine, "candidate_tag_profile", return_value="Python 和 LLM 项目经验"), patch.object(match_engine, "_ai_json", return_value={"tags": {"专业背景": ["理工"], "行业与技术": ["LLM"], "岗位方向": ["技术"]}, "summary": "资料有明确证据"}) as ai:
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
            with patch.object(match_engine, "STATE_FILE", Path(folder) / "state.json"), patch.object(match_engine, "candidate_tag_profile", return_value="英语工作语言"), patch.object(match_engine, "_ai_json", return_value={"tags": {"语言能力": ["英语", "法语"]}, "summary": "明确提到英语"}):
                result = match_engine.tag_item({"kind": "candidate", "id": "rec1", "rules": custom})
                self.assertEqual(result["tags"], {"语言能力": ["英语"], "AI 评估岗位": []})

    def test_complete_resume_cannot_save_empty_core_categories(self):
        rules = {"categories": [
            {"name": "专业背景", "tags": ["理工", "经管", "其他"]},
            {"name": "AI 评估岗位", "tags": ["技术研发", "职能（人力、财会、法务、行政）"]},
        ]}
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            with patch.object(match_engine, "STATE_FILE", Path(folder) / "state.json"), \
                 patch.object(match_engine, "candidate_tag_profile", return_value="简历正文：\n会计学专业，财务分析实习"), \
                 patch.object(match_engine, "_ai_json", return_value={"tags": {"专业背景": [], "AI 评估岗位": []}, "summary": "不确定"}):
                with self.assertRaisesRegex(RuntimeError, "已拒绝保存空结果"):
                    match_engine.tag_item({"kind": "candidate", "id": "rec1", "rules": rules})

    def test_parallel_tags_keep_each_candidate_result(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            with patch.object(match_engine, "STATE_FILE", Path(folder) / "state.json"), patch.object(match_engine, "candidate_tag_profile", side_effect=lambda item_id: f"资料 {item_id}"), patch.object(match_engine, "_ai_json", return_value={"tags": {"专业背景": ["理工"]}, "summary": "有证据"}):
                payloads = [{"kind": "candidate", "id": f"rec{i}", "rules": RULES} for i in range(8)]
                with ThreadPoolExecutor(max_workers=4) as pool:
                    results = list(pool.map(match_engine.tag_item, payloads))
                self.assertEqual(len(results), 8)
                self.assertEqual(len(match_engine.public_state()["candidate_tags"]), 8)

    def test_tag_plan_skips_unchanged_records_and_selects_changed_rules(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            records = [{"record_id": "rec1", "fields": {"AR_记录类型": "account", "简历": [{"file_token": "one"}]}}, {"record_id": "rec2", "fields": {"AR_记录类型": "account", "简历": [{"file_token": "two"}]}}, {"record_id": "legacy", "fields": {"简历": [{"file_token": "old"}]}}]
            original_read_json = match_engine.read_json
            ar_tables = [*TEST_TABLES, {"id": "testArCandidateTable", "name": "AR 候选人", "kind": "candidate_output", "archived": False}]
            with patch.object(match_engine, "STATE_FILE", Path(folder) / "state.json"), patch.object(match_engine, "TABLES", ar_tables), patch.object(match_engine, "read_json", side_effect=lambda path, default: records if Path(path).parent.name == "testArCandidateTable" else ([{"record_id": "legacy", "fields": {"简历": [{"file_token": "old"}]}}] if str(path).endswith("records.json") else original_read_json(path, default))), patch.object(match_engine, "candidate_tag_profile", side_effect=lambda item_id: "已有资料" if item_id == "rec1" else "新资料"), patch.object(match_engine, "_ai_json", return_value={"tags": {"专业背景": ["理工"] , "行业与技术": [], "岗位方向": []}, "summary": "测试"}):
                match_engine.tag_item({"kind": "candidate", "id": "rec1", "rules": RULES})
                plan = match_engine.tag_plan({"kind": "candidate", "rules": RULES})
                self.assertEqual(plan["cached_count"], 1)
                self.assertEqual(plan["pending_ids"], ["rec2"])
                updated = match_engine.tag_plan({"kind": "candidate", "rules": {**RULES, "instructions": "新规则"}})
                self.assertEqual(updated["pending_ids"], ["rec1", "rec2"])

    def test_hard_filter_requires_all_six_conditions_and_uses_intent_or_ai_position(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            state_file = Path(folder) / "state.json"
            state_file.write_text(json.dumps({
                "candidate_tags": {"candidate1": {"tags": {"AI 评估岗位": ["产品经理"]}}},
                "job_tags": {"job1:2:hash": {"tags": {"岗位方向": ["产品经理"]}}},
                "evaluations": {},
            }, ensure_ascii=False), encoding="utf-8")
            job = {"fields": {"工作地点": "北京/Beijing", "出勤方式": "线上线下结合", "岗位类别": ["可转正"], "每周最少到岗天数": "4天", "最晚到岗日期": "2026-11-30"}}
            candidate = {"fields": {"意向base地（可多选）": ["北京/Beijing"], "意向出勤方式": "线上远程 Remote", "当前求职类别（多选）": ["实习转正", "联创"], "意向岗位": ["设计"], "最早到岗时间": "2026-11-08", "每周到岗天数": ["3天", "5天"]}}
            with patch.object(match_engine, "STATE_FILE", state_file), patch.object(match_engine, "_record", side_effect=lambda kind, _item_id: job if kind == "job" else candidate):
                result = match_engine.hard_filter_result("job1:2:hash", "candidate1")
            self.assertTrue(result["passed"])
            self.assertEqual(result["failed"], [])

    def test_hard_filter_skips_missing_latest_date_but_ignores_cofounder_category(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            state_file = Path(folder) / "state.json"
            state_file.write_text(json.dumps({
                "candidate_tags": {"candidate1": {"tags": {"AI 评估岗位": ["技术研发"]}}},
                "job_tags": {"job1:2:hash": {"tags": {"岗位方向": ["技术研发"]}}},
                "evaluations": {},
            }, ensure_ascii=False), encoding="utf-8")
            job = {"fields": {"工作地点": "上海/Shanghai", "出勤方式": "线下", "岗位类别": ["日常实习"], "每周最少到岗天数": "4天", "最晚到岗日期": ""}}
            candidate = {"fields": {"意向base地（可多选）": ["上海/Shanghai"], "意向出勤方式": "线下 On-site", "当前求职类别（多选）": ["联创"], "意向岗位": ["技术研发"], "最早到岗时间": "2027-12-01", "每周到岗天数": ["3天"]}}
            with patch.object(match_engine, "STATE_FILE", state_file), patch.object(match_engine, "_record", side_effect=lambda kind, _item_id: job if kind == "job" else candidate):
                result = match_engine.hard_filter_result("job1:2:hash", "candidate1")
            self.assertFalse(result["passed"])
            self.assertEqual(result["failed"], ["岗位类别", "每周到岗天数"])
            arrival = next(item for item in result["checks"] if item["key"] == "arrival")
            self.assertTrue(arrival["passed"])
            self.assertTrue(arrival["skipped"])

    def test_deep_evaluation_rejects_candidate_that_failed_hard_filter(self):
        with patch.object(match_engine, "_job_text", return_value="岗位原文"), patch.object(match_engine, "hard_filter_result", return_value={"passed": False, "failed": ["工作地点", "岗位类别"]}), patch.object(match_engine, "candidate_profile") as profile:
            with self.assertRaisesRegex(ValueError, "工作地点、岗位类别"):
                match_engine.evaluate_item({"job_id": "job1:2:hash", "jd_text": "岗位原文", "candidate_id": "candidate1"})
            profile.assert_not_called()

    def test_evaluation_is_saved_per_candidate_and_jd(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            with patch.object(match_engine, "STATE_FILE", Path(folder) / "state.json"), patch.object(match_engine, "candidate_profile", return_value="候选人资料"), patch.object(match_engine, "_job_text", return_value="岗位原文"), patch.object(match_engine, "hard_filter_result", return_value={"passed": True, "failed": []}), patch.object(match_engine, "read_settings", return_value={"model": "mock-model", "base_url": "https://example.com/v1"}), patch.object(match_engine, "_ai_json", return_value=evaluation_result(4)) as ai, patch("portal_data.publish_recommendation", return_value={"published": True, "record_id": "local_test"}) as publish:
                payload = {"job_id": "jd1", "jd_text": "岗位原文", "candidate_id": "rec1", "common_prompt": "公共规则", "job_prompt": "岗位规则"}
                first = match_engine.evaluate_item(payload)
                second = match_engine.evaluate_item(payload)
                changed = match_engine.evaluate_item({**payload, "job_prompt": "新岗位规则"})
                self.assertEqual(first["stars"], 4)
                self.assertTrue(second["cached"])
                self.assertFalse(changed["cached"])
                self.assertEqual(ai.call_count, 2)
                self.assertEqual(first["recommendation"], "推荐")
                self.assertEqual(first["assessment"]["details"][0]["jd_requirement"], "具备相关项目经验")
                publish.assert_not_called()
                self.assertNotIn("delivery", first)
                self.assertEqual(match_engine.confirm_recommendation(payload)["record_id"], "local_test")
                self.assertEqual(publish.call_args.args[:3], ("jd1", "rec1", 4))
                self.assertEqual(publish.call_args.args[4], "岗位原文")
                self.assertEqual(publish.call_args.kwargs["assessment"]["schema_version"], 2)

    def test_force_evaluation_bypasses_matching_cache(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            with patch.object(match_engine, "STATE_FILE", Path(folder) / "state.json"), \
                 patch.object(match_engine, "candidate_profile", return_value="候选人资料"), \
                 patch.object(match_engine, "_job_text", return_value="岗位原文"), \
                 patch.object(match_engine, "hard_filter_result", return_value={"passed": True, "failed": []}), \
                 patch.object(match_engine, "read_settings", return_value={"model": "mock-model", "base_url": "https://example.com/v1"}), \
                 patch.object(match_engine, "_ai_json", side_effect=[evaluation_result(4), evaluation_result(2)]) as ai:
                payload = {"job_id": "jd1", "jd_text": "岗位原文", "candidate_id": "rec1", "common_prompt": "", "job_prompt": ""}
                first = match_engine.evaluate_item(payload)
                cached = match_engine.evaluate_item(payload)
                refreshed = match_engine.evaluate_item({**payload, "force": True})
            self.assertFalse(first["cached"])
            self.assertTrue(cached["cached"])
            self.assertFalse(refreshed["cached"])
            self.assertEqual(refreshed["stars"], 2)
            self.assertEqual(ai.call_count, 2)

    def test_low_star_evaluation_can_be_manually_confirmed(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            with patch.object(match_engine, "STATE_FILE", Path(folder) / "state.json"), patch.object(match_engine, "candidate_profile", return_value="候选人资料"), patch.object(match_engine, "_job_text", return_value="岗位原文"), patch.object(match_engine, "hard_filter_result", return_value={"passed": True, "failed": []}), patch.object(match_engine, "read_settings", return_value={"model": "mock-model", "base_url": "https://example.com/v1"}), patch.object(match_engine, "_ai_json", return_value=evaluation_result(1)), patch("portal_data.publish_recommendation", return_value={"published": True}) as publish:
                payload = {"job_id": "jd1", "jd_text": "岗位原文", "candidate_id": "rec1", "common_prompt": "", "job_prompt": ""}
                match_engine.evaluate_item(payload)
                publish.assert_not_called()
                self.assertTrue(match_engine.confirm_recommendation(payload)["published"])
                self.assertEqual(publish.call_args.args[:3], ("jd1", "rec1", 1))
                self.assertEqual(publish.call_args.kwargs["assessment"]["recommendation"], "不推荐")

    def test_evaluation_contract_rejects_unstructured_output(self):
        with self.assertRaisesRegex(RuntimeError, "评分依据格式无效"):
            match_engine._normalize_evaluation({"stars": 4, "summary": "看起来匹配", "details": "很优秀"})

    def test_recommendation_level_is_derived_from_stars(self):
        self.assertEqual(match_engine._normalize_evaluation(evaluation_result(5))["recommendation"], "推荐")
        self.assertEqual(match_engine._normalize_evaluation(evaluation_result(3))["recommendation"], "谨慎推荐")
        self.assertEqual(match_engine._normalize_evaluation(evaluation_result(2))["recommendation"], "不推荐")

    def test_evaluation_safely_normalizes_scalar_and_detail_limit(self):
        result = evaluation_result("3")
        result["details"] *= 5
        normalized = match_engine._normalize_evaluation(result)
        self.assertEqual(normalized["stars"], 3)
        self.assertEqual(normalized["recommendation"], "谨慎推荐")
        self.assertEqual(len(normalized["details"]), 3)

    def test_evaluation_requires_at_least_one_detail(self):
        with self.assertRaisesRegex(RuntimeError, "评分依据格式无效"):
            match_engine._normalize_evaluation({"stars": 4, "summary": "核心要求基本匹配", "details": []})

    def test_invalid_evaluation_format_is_retried_once(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            invalid = {"stars": 4, "summary": "格式错误", "details": "不应是文本"}
            with patch.object(match_engine, "STATE_FILE", Path(folder) / "state.json"), \
                 patch.object(match_engine, "candidate_profile", return_value="候选人资料"), \
                 patch.object(match_engine, "_job_text", return_value="岗位原文"), \
                 patch.object(match_engine, "hard_filter_result", return_value={"passed": True, "failed": []}), \
                 patch.object(match_engine, "read_settings", return_value={"model": "mock-model", "base_url": "https://example.com/v1"}), \
                 patch.object(match_engine, "_ai_json", side_effect=[invalid, evaluation_result(4)]) as ai:
                result = match_engine.evaluate_item({"job_id": "jd1", "jd_text": "岗位原文", "candidate_id": "rec1", "common_prompt": "", "job_prompt": ""})
            self.assertEqual(ai.call_count, 2)
            self.assertEqual(result["recommendation"], "推荐")
            self.assertIn("评分依据格式无效", ai.call_args_list[1].args[0])


if __name__ == "__main__":
    unittest.main()
