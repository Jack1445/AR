import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import ai_history
import match_engine
from tests.pg_test import isolated_schema


class FakeResponse:
    def __init__(self, content):
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return json.dumps({"choices": [{"message": {"content": self.content}}]}).encode("utf-8")


class FakeOpener:
    def __init__(self, content):
        self.content = content
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        return FakeResponse(self.content)


class AIHistoryTests(unittest.TestCase):
    def setUp(self):
        isolated_schema(self)
        ai_history.ensure_schema()

    def test_actual_prompts_and_raw_reply_are_saved_without_api_key(self):
        opener = FakeOpener('```json\n{"stars":4,"reason":"匹配"}\n```')
        with patch.object(match_engine, "read_settings", return_value={"base_url": "https://example.com/v1", "model": "test-model"}), patch.object(match_engine, "_get_key", return_value="secret-value"), patch.object(match_engine.urllib.request, "build_opener", return_value=opener):
            result = match_engine._ai_json("评分说明", "JD 与简历", kind="evaluation", target_id="jd|person", target_label="测试候选人")
        self.assertEqual(result["stars"], 4)
        row = ai_history.get_call(ai_history.list_calls()["items"][0]["id"])
        sent = json.loads(opener.requests[0].data)
        self.assertEqual(row["system_prompt"], sent["messages"][0]["content"])
        self.assertEqual(row["user_prompt"], sent["messages"][1]["content"])
        self.assertEqual(row["raw_response"], opener.content)
        self.assertEqual(row["status"], "success")
        self.assertNotIn("secret-value", json.dumps(row))

    def test_invalid_reply_is_visible_as_failed_request(self):
        with patch.object(match_engine, "read_settings", return_value={"base_url": "https://example.com/v1", "model": "test-model"}), patch.object(match_engine, "_get_key", return_value="key"), patch.object(match_engine.urllib.request, "build_opener", return_value=FakeOpener("not json")):
            with self.assertRaisesRegex(RuntimeError, "JSON"):
                match_engine._ai_json("规则", "资料", kind="candidate_tag", target_id="person", target_label="测试")
        row = ai_history.get_call(ai_history.list_calls()["items"][0]["id"])
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["raw_response"], "not json")
        self.assertTrue(row["error"])

    def test_concurrent_calls_keep_separate_records(self):
        def write(index):
            call_id, started = ai_history.start_call("candidate_tag", str(index), str(index), "model", "system", f"user-{index}")
            ai_history.finish_call(call_id, started, "success", f"reply-{index}")
        with ThreadPoolExecutor(max_workers=10) as executor:
            list(executor.map(write, range(20)))
        self.assertEqual(len(ai_history.list_calls()["items"]), 20)
        self.assertEqual({item["raw_response"] for item in (ai_history.get_call(row["id"]) for row in ai_history.list_calls()["items"])}, {f"reply-{index}" for index in range(20)})


if __name__ == "__main__":
    unittest.main()
