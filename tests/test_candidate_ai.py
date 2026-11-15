import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ai_settings
import candidate_ai


class FakeKeyring:
    def __init__(self):
        self.values = {}

    def get_password(self, service, account):
        return self.values.get((service, account))

    def set_password(self, service, account, value):
        self.values[(service, account)] = value

    def delete_password(self, service, account):
        self.values.pop((service, account), None)


class CandidateAITests(unittest.TestCase):
    def test_completed_profile_sends_separate_optional_suggestion(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return None
            def read(self, _size):
                return json.dumps({"choices": [{"message": {"content": '{"reply":"好的","fields":{}}'}}]}).encode("utf-8")

        class Opener:
            def open(self, *_args, **_kwargs): return Response()

        schema = [{"name": "姓名", "type": 1, "options": [], "required": True, "readonly": False}]
        settings = {"base_url": "https://example.com/v1", "model": "test-model", "prompt": "引导填写"}
        with patch.object(candidate_ai, "read_settings", return_value=settings), patch.object(candidate_ai, "_key", return_value="test-key"), patch.object(candidate_ai.urllib.request, "build_opener", return_value=Opener()):
            result = candidate_ai.chat_reply([{"role": "user", "content": "还有什么要补充的吗？"}], {}, schema, {"姓名": "测试用户"})
        self.assertEqual(result["missing_required"], [])
        self.assertEqual(len(result["reply_parts"]), 2)
        self.assertIn("核对", result["reply_parts"][0])
        for topic in ("自荐信", "最心仪的校友企业", "具体岗位或方向"):
            self.assertIn(topic, result["reply_parts"][1])

    def test_plain_reply_to_source_question_is_saved_when_model_omits_field(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return None
            def read(self, _size):
                return json.dumps({"choices": [{"message": {"content": '{"reply":"好的","fields":{}}'}}]}).encode("utf-8")

        class Opener:
            def open(self, *_args, **_kwargs): return Response()

        source = "你是通过什么渠道了解到的招聘信息？若是经人推荐，可填写推荐人姓名"
        schema = [
            {"name": "姓名", "type": 1, "options": [], "required": True, "readonly": False},
            {"name": source, "type": 1, "options": [], "required": True, "readonly": False},
            {"name": "来源", "type": 1, "options": [], "required": False, "readonly": False},
            {"name": "简历", "type": 17, "options": [], "required": True, "readonly": False},
        ]
        history = [
            {"role": "assistant", "content": candidate_ai._question_for_field(schema[1])},
            {"role": "user", "content": "参与一次活动看到的"},
        ]
        settings = {"base_url": "https://example.com/v1", "model": "test-model", "prompt": "引导填写"}
        with patch.object(candidate_ai, "read_settings", return_value=settings), patch.object(candidate_ai, "_key", return_value="test-key"), patch.object(candidate_ai.urllib.request, "build_opener", return_value=Opener()):
            result = candidate_ai.chat_reply(history, {}, schema, {"姓名": "测试用户"})
        self.assertEqual(result["fields"][source], "参与一次活动看到的")
        self.assertEqual(result["fields"]["来源"], "参与一次活动看到的")
        self.assertNotIn(source, result["missing_required"])

    def test_greeting_asks_for_name_without_saving_a_guessed_name(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return None
            def read(self, _size):
                return json.dumps({"choices": [{"message": {"content": '{"reply":"已记录姓名，可以提交","fields":{"姓名":"你好"}}'}}]}).encode("utf-8")

        class Opener:
            def open(self, *_args, **_kwargs): return Response()

        schema = [{"name": "姓名", "type": 1, "options": [], "required": True, "readonly": False}]
        settings = {"base_url": "https://example.com/v1", "model": "test-model", "prompt": "引导填写"}
        with patch.object(candidate_ai, "read_settings", return_value=settings), patch.object(candidate_ai, "_key", return_value="test-key"), patch.object(candidate_ai.urllib.request, "build_opener", return_value=Opener()):
            result = candidate_ai.chat_reply([{"role": "user", "content": "你好"}], {}, schema, {})
        self.assertEqual(result["fields"], {})
        self.assertIn("怎么称呼", result["reply"])
        self.assertNotIn("还没确定", result["reply"])

    def test_date_typo_is_normalized(self):
        self.assertEqual(candidate_ai._date_from_answer("2026--11-24"), "2026-11-24")
        self.assertEqual(candidate_ai._date_from_answer("2026年11月24日"), "2026-11-24")
        self.assertIsNone(candidate_ai._date_from_answer("2026-13-24"))

    def test_common_choice_wording_maps_to_feishu_option(self):
        self.assertEqual(candidate_ai._choice("同意", ["是 Yes", "否 No"]), "是 Yes")
        self.assertEqual(candidate_ai._choice("否", ["是 Yes", "否 No"]), "否 No")
        self.assertIsNone(candidate_ai._choice("实习", ["日常实习", "实习转正"]))
        self.assertEqual(candidate_ai._choice("日常", ["日常实习", "实习转正"]), "日常实习")
        self.assertEqual(candidate_ai._choice("转正", ["日常实习", "实习转正"]), "实习转正")

    def test_multiselect_answer_variations(self):
        cases = [
            ("4天或者5天", ["1天", "2天", "3天", "4天", "5天"], ["4天", "5天"]),
            ("日常和转正两个吧", ["日常实习", "实习转正", "校招"], ["日常实习", "实习转正"]),
            ("技术和产品吧", ["技术开发", "产品经理", "设计"], ["技术开发", "产品经理"]),
            ("有哪些选项：1天、2天、3天？", ["1天", "2天", "3天"], []),
            ("11天", ["1天", "2天", "3天"], []),
        ]
        for answer, options, expected in cases:
            with self.subTest(answer=answer):
                self.assertEqual(candidate_ai._choices_in_answer(answer, options), expected)

    def test_short_answer_fills_current_multiselect_when_model_omits_fields(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return None
            def read(self, _size):
                return json.dumps({"choices": [{"message": {"content": '{"reply":"好的","fields":{}}'}}]}).encode("utf-8")
        class Opener:
            def open(self, *_args, **_kwargs): return Response()
        settings = {"base_url": "https://example.com/v1", "model": "test-model", "prompt": "引导填写"}
        with patch.object(candidate_ai, "read_settings", return_value=settings), patch.object(candidate_ai, "_key", return_value="test-key"), patch.object(candidate_ai.urllib.request, "build_opener", return_value=Opener()):
            for name, options, answer, expected in [
                ("当前求职类别（多选）", ["日常实习 ", "实习转正", "校招", "社职", "联创"], "日常和转正两个吧", ["日常实习 ", "实习转正"]),
                ("每周到岗天数", ["1天", "2天", "3天", "4天", "5天"], "4天或者5天", ["4天", "5天"]),
            ]:
                with self.subTest(answer=answer):
                    schema = [{"name": name, "type": 4, "options": options, "required": True, "readonly": False}]
                    result = candidate_ai.chat_reply([{"role": "user", "content": answer}], {}, schema, {})
                    self.assertEqual(result["fields"][name], expected)

    def test_reply_does_not_claim_completion_with_missing_required_fields(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return None
            def read(self, _size):
                return json.dumps({"choices": [{"message": {"content": '{"reply":"资料齐全，可以提交","fields":{"姓名":"测试用户"}}'}}]}).encode("utf-8")

        class Opener:
            def open(self, *_args, **_kwargs): return Response()

        schema = [
            {"name": "姓名", "type": 1, "options": [], "required": True, "readonly": False},
            {"name": "简历", "type": 17, "options": [], "required": True, "readonly": False},
            {"name": "意向出勤方式", "type": 3, "options": ["线上", "线下"], "required": True, "readonly": False},
        ]
        settings = {"base_url": "https://example.com/v1", "model": "test-model", "prompt": "引导填写"}
        with patch.object(candidate_ai, "read_settings", return_value=settings), patch.object(candidate_ai, "_key", return_value="test-key"), patch.object(candidate_ai.urllib.request, "build_opener", return_value=Opener()):
            result = candidate_ai.chat_reply([{"role": "user", "content": "我叫测试用户"}], {}, schema, {})
        self.assertEqual(result["fields"], {"姓名": "测试用户"})
        self.assertEqual(result["missing_required"], ["简历", "意向出勤方式"])
        self.assertNotIn("可以提交", result["reply"])
        self.assertIn("逐题点选", result["reply"])
        self.assertNotIn("你希望怎么出勤", result["reply"])
        self.assertNotIn("上传简历", result["reply"])
        self.assertEqual(len(result["reply_parts"]), 1)

    def test_required_questions_are_split_without_losing_any_field(self):
        schema = [
            {"name": f"必填项{index}", "type": 1, "options": [], "required": True, "readonly": False}
            for index in range(7)
        ]
        parts = candidate_ai._missing_questions(schema, [item["name"] for item in schema], first_round=True)
        self.assertGreater(len(parts), 3)
        for item in schema:
            self.assertIn(item["name"], "\n".join(parts))
        self.assertTrue(all(part.count(". 关于") <= 2 for part in parts))

    def test_followup_lists_only_still_missing_fields(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return None
            def read(self, _size):
                return json.dumps({"choices": [{"message": {"content": '{"reply":"好的","fields":{"意向出勤方式":"线上"}}'}}]}).encode("utf-8")

        class Opener:
            def open(self, *_args, **_kwargs): return Response()

        schema = [
            {"name": "姓名", "type": 1, "options": [], "required": True, "readonly": False},
            {"name": "简历", "type": 17, "options": [], "required": True, "readonly": False},
            {"name": "意向出勤方式", "type": 3, "options": ["线上", "线下"], "required": True, "readonly": False},
            {"name": "最早到岗时间", "type": 5, "options": [], "required": True, "readonly": False},
        ]
        settings = {"base_url": "https://example.com/v1", "model": "test-model", "prompt": "引导填写"}
        with patch.object(candidate_ai, "read_settings", return_value=settings), patch.object(candidate_ai, "_key", return_value="test-key"), patch.object(candidate_ai.urllib.request, "build_opener", return_value=Opener()):
            result = candidate_ai.chat_reply([{"role": "user", "content": "线上就好"}], {}, schema, {"姓名": "测试用户"})
        self.assertEqual(result["fields"], {"意向出勤方式": "线上"})
        self.assertEqual(result["missing_required"], ["简历", "最早到岗时间"])
        self.assertIn("上传简历", result["reply"])
        self.assertIn("最早", result["reply"])
        self.assertNotIn("怎么出勤", result["reply"])

    def test_settings_are_separate_from_matching_ai(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent.parent) as folder:
            candidate_config = Path(folder) / "candidate.json"
            matching_config = Path(folder) / "matching.json"
            matching_config.write_text('{"model":"existing-model"}', encoding="utf-8")
            keyring = FakeKeyring()
            with patch.object(candidate_ai, "CONFIG", candidate_config), patch.object(ai_settings, "CONFIG", matching_config), patch.object(candidate_ai, "_keyring", return_value=keyring):
                saved = candidate_ai.save_settings({"base_url": "https://example.com/v1", "model": "chat-model", "prompt": "引导填写", "api_key": "candidate-secret"})
                self.assertEqual(saved["model"], "chat-model")
                self.assertTrue(saved["has_key"])
                self.assertNotIn("candidate-secret", candidate_config.read_text(encoding="utf-8"))
                self.assertEqual(json.loads(matching_config.read_text(encoding="utf-8"))["model"], "existing-model")
                self.assertEqual(keyring.values[(candidate_ai.SERVICE, candidate_ai.ACCOUNT)], "candidate-secret")
                self.assertNotEqual(candidate_ai.SERVICE, ai_settings.SERVICE)

    def test_chat_requires_separate_configuration(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent.parent) as folder, patch.object(candidate_ai, "CONFIG", Path(folder) / "missing.json"), patch.object(candidate_ai, "_keyring", return_value=FakeKeyring()):
            with self.assertRaisesRegex(ValueError, "尚未配置"):
                candidate_ai.chat_reply([{"role": "user", "content": "你好"}], {}, [], {})


if __name__ == "__main__":
    unittest.main()
