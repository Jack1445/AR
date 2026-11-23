import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import portal_data
import recommendation_store
from tests.pg_test import isolated_schema


class FakeClient:
    def __init__(self):
        self.rows = {"candidate_output": [], "alumni_output": []}
        self.fields = {"candidate_output": [{"field_name": name, "type": kind} for name, kind in (("姓名", 1), ("手机号/微信号", 1), ("简历", 17))], "alumni_output": [{"field_name": name, "type": 1} for name in ("公司名称（对外展示的名称）", "填写人与职位", "公司介绍")]}
        self.writes = []
        self.counter = 0

    def pages(self, path):
        kind, endpoint = self._path(path)
        return copy.deepcopy(self.fields[kind] if endpoint == "fields" else self.rows[kind])

    @staticmethod
    def _path(path):
        kind = "candidate_output" if "/candidate_output/" in path else "alumni_output"
        endpoint = "fields" if "/fields" in path else "records"
        return kind, endpoint

    def request(self, method, path, body=None):
        kind, endpoint = self._path(path)
        if method != "GET":
            self.writes.append((method, kind, copy.deepcopy(body)))
        if endpoint == "fields":
            assert method == "POST"
            item = {**body, "field_id": f"fld{len(self.fields[kind])}"}
            self.fields[kind].append(item)
            return {"field": item}
        record_id = path.split("/records/")[-1] if "/records/" in path else None
        if method == "GET":
            return {"record": copy.deepcopy(next(row for row in self.rows[kind] if row["record_id"] == record_id))}
        unknown = set(body["fields"]) - {field["field_name"] for field in self.fields[kind]}
        if unknown:
            raise ValueError(f"FieldNameNotFound: {unknown}")
        if method == "POST":
            self.counter += 1
            row = {"record_id": f"rec{self.counter:08d}", "fields": copy.deepcopy(body["fields"])}
            self.rows[kind].append(row)
            return {"record": copy.deepcopy(row)}
        if method == "PUT":
            row = next(row for row in self.rows[kind] if row["record_id"] == record_id)
            row["fields"].update(body["fields"])
            return {"record": copy.deepcopy(row)}
        raise AssertionError(method)


class PortalDataTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(dir=portal_data.ROOT)
        self.addCleanup(folder.cleanup)
        isolated_schema(self)
        recommendation_store.ensure_schema()
        self.client = FakeClient()
        self.client_patch = patch.object(portal_data, "_client", return_value=(self.client, "app"))
        self.table_patch = patch.object(portal_data, "_table", side_effect=lambda kind: kind)
        source_patch = patch.object(portal_data, "TABLES", [{"id": "source", "kind": "candidate", "archived": False}, {"id": "jobs", "kind": "job", "archived": False}])
        self.client_patch.start()
        self.table_patch.start()
        source_patch.start()
        self.addCleanup(self.client_patch.stop)
        self.addCleanup(self.table_patch.stop)
        self.addCleanup(source_patch.stop)
        portal_data.ensure_schema()

    def test_registration_login_and_candidate_controls(self):
        with self.assertRaises(ValueError):
            portal_data.register("candidate", "13800138000", "1234")
        candidate = portal_data.register("candidate", "13800138000", "abcde")
        row = self.client.rows["candidate_output"][0]
        self.assertNotIn("abcde", str(row))
        self.assertEqual(portal_data.login("candidate", "13800138000", "abcde"), candidate)
        with self.assertRaises(ValueError):
            portal_data.login("candidate", "13800138000", "wrong")
        profile = portal_data.save_candidate(candidate, name="张三", description="产品运营经历", enabled=False)
        self.assertEqual(profile["name"], "张三")
        self.assertFalse(profile["enabled"])
        self.assertEqual(row["fields"]["AR_推荐状态"], "停止")
        self.assertTrue(all(kind == "candidate_output" for _, kind, _body in self.client.writes if _body.get("fields", {}).get("AR_记录类型") == "account" or _body.get("fields", {}).get("AR_推荐状态")))

    def test_mp_login_binds_subject_not_phone(self):
        identity = portal_data.login_with_mp("candidate", "mp-user-1", "13800138000")
        self.assertEqual(portal_data.login_with_mp("candidate", "mp-user-1", "13800138000"), identity)
        self.assertEqual(self.client.rows["candidate_output"][0]["fields"]["AR_MP用户ID"], "mp-user-1")
        with self.assertRaises(ValueError):
            portal_data.login_with_mp("candidate", "mp-user-2", "13800138000")
        with self.assertRaises(ValueError):
            portal_data.login_with_mp("candidate", "mp-user-1", "13900139000")
        self.assertEqual(len(self.client.rows["candidate_output"]), 1)

    def test_mp_login_rejects_invalid_phone_with_specific_error(self):
        with self.assertRaises(portal_data.MpLoginError) as raised:
            portal_data.login_with_mp("candidate", "mp-user-1", "")
        self.assertEqual(raised.exception.code, "invalid_phone")

    def test_mp_login_reports_existing_phone_account(self):
        portal_data.register("candidate", "13800138000", "password")
        with self.assertRaises(portal_data.MpLoginError) as raised:
            portal_data.login_with_mp("candidate", "mp-user-1", "13800138000")
        self.assertEqual(raised.exception.code, "phone_in_use")

    def test_mp_login_binds_legacy_account_by_matching_phone(self):
        legacy = portal_data.register("alumni", "13800138000", "abcde")
        identity = portal_data.login_with_mp("alumni", "mp-user-1", "13800138000")
        self.assertEqual(identity, legacy)
        self.assertEqual(self.client.rows["alumni_output"][0]["fields"]["AR_MP用户ID"], "mp-user-1")

    def test_multiple_jobs_ownership_and_feedback(self):
        owner = portal_data.register("alumni", "13800138000", "abcde")
        stranger = portal_data.register("alumni", "13900139000", "abcde")
        portal_data.save_alumni_company(owner, "测试企业")
        one = portal_data.save_job(owner, title="产品经理", body="负责产品设计")
        two = portal_data.save_job(owner, title="运营经理", body="负责用户运营")
        self.assertEqual(len(portal_data.list_jobs(owner)), 2)
        with self.assertRaises(ValueError):
            portal_data.save_job(stranger, record_id=one["id"], title="篡改", body="不允许")
        rec = recommendation_store.create(one["id"] + ":2:hash", "recCandidate01", owner["id"], "候选人", "资料", 4, "适合")
        self.assertEqual(portal_data.list_recommendations(owner)[0]["job_title"], "产品经理")
        self.assertFalse(portal_data.list_recommendations(stranger))
        with self.assertRaises(ValueError):
            portal_data.feedback(stranger, rec["id"], "感兴趣")
        self.assertEqual(portal_data.feedback(owner, rec["id"], "感兴趣")["status"], "面试中")
        self.assertEqual(recommendation_store.get(rec["id"])["interest"], "感兴趣")
        self.assertEqual(portal_data.feedback(owner, rec["id"], "录用")["status"], "录用")
        self.assertEqual(recommendation_store.get(rec["id"])["status"], "录用")
        with self.assertRaises(ValueError):
            portal_data.feedback(owner, rec["id"], "未录用")

    def test_feedback_can_be_revised_and_restored_with_local_history(self):
        owner = portal_data.register("alumni", "13800138000", "abcde")
        portal_data.save_alumni_company(owner, "测试企业")
        job = portal_data.save_job(owner, title="产品经理", body="负责产品设计")
        rec = recommendation_store.create(job["id"] + ":2:hash", "recCandidate02", owner["id"], "候选人", "资料", 4, "适合")
        self.assertEqual(portal_data.feedback(owner, rec["id"], "不感兴趣")["status"], "不感兴趣")
        self.assertEqual(portal_data.feedback(owner, rec["id"], "待反馈")["status"], "待反馈")
        self.assertEqual(recommendation_store.get(rec["id"])["interest"], "")
        self.assertEqual(portal_data.feedback(owner, rec["id"], "感兴趣")["status"], "面试中")
        self.assertEqual(portal_data.feedback(owner, rec["id"], "不感兴趣")["status"], "不感兴趣")
        with recommendation_store._connect() as db:
            history = [row["to_status"] for row in db.execute("SELECT to_status FROM feedback_events WHERE recommendation_id = %s ORDER BY id", (rec["id"],))]
        self.assertEqual(history, ["不感兴趣", "待反馈", "面试中", "不感兴趣"])

    def test_company_contact_and_introduction_use_existing_feishu_fields(self):
        owner = portal_data.register("alumni", "13800138000", "abcde")
        saved = portal_data.save_alumni_company(owner, "NVIDIA", "张三 · 招聘负责人", "研发 AI 产品的团队")
        self.assertEqual(saved["contact_title"], "张三 · 招聘负责人")
        self.assertEqual(saved["introduction"], "研发 AI 产品的团队")
        job = portal_data.save_job(owner, title="产品经理", body="负责产品设计")
        portal_data.save_alumni_company(owner, "NVIDIA", "李四 · HR", "更新后的公司介绍")
        account_row = next(row for row in self.client.rows["alumni_output"] if row["record_id"] == owner["id"])
        job_row = next(row for row in self.client.rows["alumni_output"] if row["record_id"] == job["id"])
        for row in (account_row, job_row):
            self.assertEqual(row["fields"]["填写人与职位"], "李四 · HR")
            self.assertEqual(row["fields"]["公司介绍"], "更新后的公司介绍")
        with self.assertRaisesRegex(ValueError, "联系人"):
            portal_data.save_alumni_company(owner, "NVIDIA", "", "介绍")

    def test_schema_is_idempotent(self):
        self.assertEqual(portal_data.ensure_schema(), {"candidate_output": [], "alumni_output": []})

    def test_legacy_feishu_recommendation_is_copied_locally_without_writing_back(self):
        self.client.fields["alumni_output"].extend({"field_name": name, "type": 1} for name in ("AR_候选人ID", "AR_候选人姓名", "AR_星级", "AR_流程状态", "AR_评估理由", "AR_候选人资料", "AR_意向反馈"))
        owner = portal_data.register("alumni", "13800138000", "abcde")
        portal_data.save_alumni_company(owner, "测试企业")
        job = portal_data.save_job(owner, title="产品经理", body="产品设计")
        legacy = self.client.request("POST", "/alumni_output/records", body={"fields": {"AR_记录类型": "recommendation", "AR_账户ID": owner["id"], "AR_来源JD": job["id"] + ":2:hash", "AR_候选人ID": "recCandidate01", "AR_候选人姓名": "候选人", "AR_星级": "4", "AR_流程状态": "待反馈"}})["record"]
        writes_before = len(self.client.writes)
        self.assertEqual(portal_data.list_recommendations(owner)[0]["id"], legacy["record_id"])
        self.assertEqual(len(self.client.writes), writes_before)
        portal_data.feedback(owner, legacy["record_id"], "感兴趣")
        self.assertEqual(recommendation_store.get(legacy["record_id"])["status"], "面试中")
        self.assertEqual(self.client.rows["alumni_output"][-1]["fields"]["AR_流程状态"], "待反馈")

    def test_candidate_draft_persists_each_field_without_submitting(self):
        candidate = portal_data.register("candidate", "13800138000", "abcde")
        saved = portal_data.save_candidate(candidate, form_fields={"姓名": "测试用户"}, draft=True)
        self.assertEqual(saved["values"]["姓名"], "测试用户")
        self.assertFalse(saved["submitted"])
        self.assertEqual(self.client.rows["candidate_output"][0]["fields"]["AR_提交状态"], "草稿")
        with self.assertRaisesRegex(ValueError, "简历"):
            portal_data.save_candidate(candidate, form_fields={})
        self.client.rows["candidate_output"][0]["fields"]["简历"] = [{"name": "cv.pdf", "file_token": "token"}]
        self.assertFalse(portal_data.account_data(candidate)["submitted"])
        self.assertTrue(portal_data.save_candidate(candidate, form_fields={})["submitted"])

    def test_import_existing_candidate_after_source_field_rename(self):
        candidate = portal_data.register("candidate", "13800138000", "abcde")
        source = {"record_id": "recSource01", "fields": {"姓名": "李四", "手机号/微信号": "13800138000", "简历": []}}
        with patch("build_web.read_json", return_value=[source]):
            result = portal_data.import_existing(candidate)
        self.assertEqual(result["imported"], 1)
        row = self.client.rows["candidate_output"][0]
        self.assertEqual(row["fields"]["姓名"], "李四")
        self.assertEqual(row["fields"]["手机号/微信号"], "13800138000")
        self.assertEqual(row["fields"]["AR_来源记录ID"], "recSource01")

    def test_candidate_form_uses_current_feishu_fields_and_validates_choices(self):
        self.client.fields["candidate_output"].extend([
            {"field_name": "意向岗位", "type": 4, "property": {"options": [{"name": "技术"}, {"name": "运营"}]}},
            {"field_name": "最早到岗时间", "type": 5, "property": {"auto_fill": False}},
            {"field_name": "填写时间", "type": 5, "property": {"auto_fill": True}},
            {"field_name": "自荐信", "type": 17},
        ])
        candidate = portal_data.register("candidate", "13800138000", "abcde")
        self.assertFalse(portal_data.account_data(candidate)["submitted"])
        row = self.client.rows["candidate_output"][0]
        row["fields"]["简历"] = [{"name": "resume.pdf", "file_token": "token"}]
        view = portal_data.account_data(candidate)
        self.assertEqual([field["name"] for field in view["schema"]], ["姓名", "手机号/微信号", "简历", "意向岗位", "最早到岗时间", "填写时间", "自荐信"])
        self.assertTrue(next(field for field in view["schema"] if field["name"] == "填写时间")["readonly"])
        portal_data.save_candidate(candidate, form_fields={"姓名": "张三", "意向岗位": ["技术"], "最早到岗时间": 1760000000000})
        self.assertTrue(portal_data.account_data(candidate)["submitted"])
        self.assertEqual(row["fields"]["AR_提交状态"], "已提交")
        self.assertEqual(row["fields"]["意向岗位"], ["技术"])
        with self.assertRaises(ValueError):
            portal_data.save_candidate(candidate, form_fields={"意向岗位": ["不存在"]})
        with self.assertRaises(ValueError):
            portal_data.save_candidate(candidate, form_fields={"AR_密码摘要": "bad"})

    def test_required_base_conditional_consent_and_attachment_removal(self):
        self.client.fields["candidate_output"].extend([
            {"field_name": portal_data.BASE_FIELD, "type": 4, "property": {"options": [{"name": "北京/Beijing"}, {"name": "其他"}]}},
            {"field_name": portal_data.BASE_OTHER_FIELD, "type": 1},
            {"field_name": portal_data.CONSENT_FIELD, "type": 3, "property": {"options": [{"name": "是 Yes"}, {"name": "否 No"}, {"name": "其他"}]}},
            {"field_name": portal_data.CONSENT_OTHER_FIELD, "type": 1},
        ])
        candidate = portal_data.register("candidate", "13800138000", "abcde")
        row = self.client.rows["candidate_output"][0]
        row["fields"]["简历"] = [{"name": "resume.pdf", "file_token": "token"}]
        schema = portal_data.account_data(candidate)["schema"]
        self.assertNotIn(portal_data.CONSENT_OTHER_FIELD, [item["name"] for item in schema])
        self.assertEqual(next(item["options"] for item in schema if item["name"] == portal_data.CONSENT_FIELD), ["是 Yes", "否 No"])
        with self.assertRaises(ValueError):
            portal_data.save_candidate(candidate, form_fields={"姓名": "张三", portal_data.BASE_FIELD: []})
        portal_data.save_candidate(candidate, form_fields={"姓名": "张三", portal_data.BASE_FIELD: ["其他"], portal_data.BASE_OTHER_FIELD: "海外", portal_data.CONSENT_FIELD: "是 Yes"})
        self.assertEqual(row["fields"][portal_data.BASE_OTHER_FIELD], "海外")
        portal_data.save_candidate(candidate, form_fields={"姓名": "张三", portal_data.BASE_FIELD: ["北京/Beijing"], portal_data.CONSENT_FIELD: "是 Yes"})
        self.assertIsNone(row["fields"][portal_data.BASE_OTHER_FIELD])
        row["fields"][portal_data.BASE_OTHER_FIELD] = "旧补充内容"
        portal_data.save_candidate(candidate, form_fields={"姓名": "张三"})
        self.assertIsNone(row["fields"][portal_data.BASE_OTHER_FIELD])
        portal_data.remove_candidate_attachment(candidate, "简历", 0)
        self.assertEqual(row["fields"]["简历"], [])

    def test_low_star_manual_publication_is_idempotent_and_respects_pause(self):
        owner = portal_data.register("alumni", "13800138000", "abcde")
        portal_data.save_alumni_company(owner, "测试企业")
        job = portal_data.save_job(owner, title="产品经理", body="负责产品设计")
        candidate = portal_data.register("candidate", "13900139000", "abcde")
        portal_data.save_candidate(candidate, name="张三", description="产品经历")
        source = job["id"] + ":2:hash"
        with patch("match_engine._candidate_label", return_value="张三"), patch("match_engine._job_text", return_value="负责产品设计"), patch("match_engine.candidate_profile", return_value="产品经历"):
            first = portal_data.publish_recommendation(source, candidate["id"], 2, "不足", "负责产品设计")
            second = portal_data.publish_recommendation(source, candidate["id"], 4, "适合", "负责产品设计")
            self.assertTrue(first["published"])
            self.assertTrue(second["cached"])
            self.assertEqual(recommendation_store.get(first["record_id"])["stars"], 2)
            self.assertEqual(len(portal_data.list_recommendations(owner)), 1)
            self.assertFalse(any(row["fields"].get("AR_记录类型") == "recommendation" for row in self.client.rows["alumni_output"]))
            portal_data.save_candidate(candidate, enabled=False)
            self.assertEqual(portal_data.publish_recommendation(source, candidate["id"], 4, "适合", "负责产品设计")["reason"], "候选人已停止推荐")
            portal_data.save_candidate(candidate, enabled=True)
            portal_data.save_job(owner, record_id=job["id"], title="产品经理", body="负责产品设计", enabled=False)
            self.assertEqual(portal_data.publish_recommendation(source, candidate["id"], 4, "适合", "负责产品设计")["reason"], "这条 JD 已停止招聘")

    def test_business_outcomes_sync_to_both_ar_tables_and_jobs_show_company(self):
        owner = portal_data.register("alumni", "13800138000", "abcde")
        portal_data.save_alumni_company(owner, "NVIDIA")
        first = portal_data.save_job(owner, title="产品经理", body="产品设计")
        second = portal_data.save_job(owner, title="运营", body="用户运营")
        candidate = portal_data.register("candidate", "13900139000", "abcde")
        portal_data.save_candidate(candidate, name="张三")
        with patch("match_engine._candidate_label", return_value="张三"), patch("match_engine._job_text", return_value="产品设计"), patch("match_engine.candidate_profile", return_value="求职资料"):
            for job in (first, second):
                portal_data.publish_recommendation(job["id"] + ":0:hash", candidate["id"], 1, "本地评估", "产品设计")
        candidate_row = self.client.rows["candidate_output"][-1]
        self.assertIn(first["id"], candidate_row["fields"]["AR_已推荐JD"])
        self.assertIn(second["id"], candidate_row["fields"]["AR_已推荐JD"])
        self.assertEqual(candidate_row["fields"].get("AR_录用JD", ""), "")
        for job in (first, second):
            row = next(row for row in self.client.rows["alumni_output"] if row["record_id"] == job["id"])
            self.assertEqual(row["fields"]["公司名称（对外展示的名称）"], "NVIDIA")
            self.assertEqual(row["fields"]["AR_联系人手机号"], owner["phone"])
            self.assertEqual(row["fields"]["AR_账户ID"], owner["id"])
        rec = recommendation_store.find(first["id"] + ":0:hash", candidate["id"])
        portal_data.feedback(owner, rec["id"], "感兴趣")
        self.assertEqual(candidate_row["fields"].get("AR_录用JD", ""), "")
        portal_data.feedback(owner, rec["id"], "录用")
        self.assertIn(first["id"], candidate_row["fields"]["AR_录用JD"])
        self.assertNotIn(second["id"], candidate_row["fields"]["AR_录用JD"])
        first_row = next(row for row in self.client.rows["alumni_output"] if row["record_id"] == first["id"])
        self.assertIn("张三", first_row["fields"]["AR_已录用候选人"])
        self.assertEqual(portal_data.sync_business_outcomes(), {"candidate_output": 0, "alumni_output": 0})

    def test_negative_feedback_blocks_recommendation_after_jd_revision(self):
        owner = portal_data.register("alumni", "13800138000", "abcde")
        portal_data.save_alumni_company(owner, "测试企业")
        job = portal_data.save_job(owner, title="产品经理", body="产品设计")
        candidate = portal_data.register("candidate", "13900139000", "abcde")
        with patch("match_engine._candidate_label", return_value="张三"), patch("match_engine._job_text", return_value="产品设计"), patch("match_engine.candidate_profile", return_value="求职资料"):
            first = portal_data.publish_recommendation(job["id"] + ":2:old", candidate["id"], 3, "适合", "产品设计")
            portal_data.feedback(owner, first["record_id"], "不感兴趣")
            again = portal_data.publish_recommendation(job["id"] + ":2:new", candidate["id"], 4, "适合", "产品设计")
        self.assertFalse(again["published"])
        self.assertIn("不感兴趣", again["reason"])
        self.assertEqual(len(recommendation_store.all_rows()), 1)


if __name__ == "__main__":
    unittest.main()
