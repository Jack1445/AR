import copy
import os
import threading
import time
import unittest
from unittest.mock import patch

import portal_data
import portal_store
import portal_sync
import account_admin
import recommendation_store
from tests.pg_test import isolated_schema

JOB_ARGS = {"work_location": "上海", "attendance_mode": "线下", "job_categories": ["社职"], "min_days_per_week": "5天"}
from tests.test_portal_data import FakeClient


class PortalStoreTests(unittest.TestCase):
    def setUp(self):
        isolated_schema(self)
        portal_store.set_sync_notifier(None)
        self.addCleanup(portal_store.set_sync_notifier, None)
        portal_store.ensure_schema()

    def test_queue_notifies_only_after_commit(self):
        observed = []

        def notified():
            observed.append(portal_store.get_record("candidate_output", "recOne"))

        portal_store.set_sync_notifier(notified)
        portal_store.merge_fields("candidate_output", "recOne", {"姓名": "已提交"})
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0]["fields"]["姓名"], "已提交")
        self.assertEqual(observed[0]["sync_state"], "pending")

    def test_failed_record_exposes_next_retry_deadline(self):
        portal_store.mirror_record("candidate_output", {"record_id": "recOne", "fields": {"姓名": "旧值"}})
        pending = portal_store.merge_fields("candidate_output", "recOne", {"姓名": "新值"})
        portal_store.mark_failed("candidate_output", "recOne", pending["version"], "temporary failure")
        delay = portal_store.next_attempt_delay()
        self.assertIsNotNone(delay)
        self.assertGreater(delay, 0)
        self.assertLessEqual(delay, 2.1)

    def test_partial_feishu_update_preserves_complete_account(self):
        full = {"record_id": "recOne", "fields": {
            "AR_记录类型": "account", "AR_手机号": "13800138000", "姓名": "张三"
        }}
        portal_store.mirror_record("candidate_output", full)
        portal_store.mirror_record("candidate_output", {
            "record_id": "recOne", "fields": {"简历": [{"file_token": "fileOne"}]}
        }, partial=True)
        fields = portal_store.get_record("candidate_output", "recOne")["fields"]
        self.assertEqual(fields["AR_记录类型"], "account")
        self.assertEqual(fields["AR_手机号"], "13800138000")
        self.assertEqual(fields["简历"][0]["file_token"], "fileOne")

    def test_delete_records_removes_account_and_preferences(self):
        portal_store.mirror_record("candidate_output", {"record_id": "recOne", "fields": {"AR_记录类型": "account", "AR_手机号": "13800138000"}})
        portal_store.save_preference("recOne", "job_order", ["jobOne"])
        self.assertEqual(portal_store.delete_records("candidate_output", ["recOne"]), 1)
        self.assertIsNone(portal_store.get_record("candidate_output", "recOne"))
        self.assertIsNone(portal_store.get_preference("recOne", "job_order"))
        self.assertEqual(portal_store.pending_deletions()[0]["feishu_record_id"], "recOne")
        self.assertIsNone(portal_store.mirror_record("candidate_output", {
            "record_id": "recOne", "fields": {"AR_记录类型": "account"}
        }))

    def test_update_helper_marks_feishu_response_as_partial(self):
        class PartialUpdateClient(FakeClient):
            def request(self, method, path, body=None):
                result = super().request(method, path, body)
                if method == "PUT":
                    record_id = path.split("/records/")[-1]
                    return {"record": {"record_id": record_id, "fields": body["fields"]}}
                return result

        client = PartialUpdateClient()
        client.fields["candidate_output"].append({"field_name": "AR_记录类型", "type": 1})
        client.fields["candidate_output"].append({"field_name": "AR_手机号", "type": 1})
        full = {"record_id": "recOne", "fields": {"AR_记录类型": "account", "AR_手机号": "13800138000"}}
        client.rows["candidate_output"].append(full)
        portal_store.mirror_record("candidate_output", full)
        with patch.dict(os.environ, {"AR_LOCAL_PRIMARY": "1"}), \
             patch.object(portal_data, "_table", side_effect=lambda kind: kind):
            portal_data._update(client, "app", "candidate_output", "recOne", {"简历": []})
        fields = portal_store.get_record("candidate_output", "recOne")["fields"]
        self.assertEqual(fields["AR_记录类型"], "account")
        self.assertEqual(fields["AR_手机号"], "13800138000")

    def test_event_worker_sleeps_until_triggered(self):
        stop = threading.Event()
        wake = threading.Event()
        first = threading.Event()
        second = threading.Event()
        calls = []

        def sync_once(*_args):
            calls.append(time.monotonic())
            (first if len(calls) == 1 else second).set()
            return {"synced": 0, "failed": 0}

        with patch.object(portal_data, "_client", return_value=(object(), "app")), \
             patch.object(portal_sync, "sync_pending_once", side_effect=sync_once), \
             patch.object(portal_sync, "pull_from_feishu", return_value={}):
            thread = threading.Thread(target=portal_sync.run,
                                      args=(stop, wake, 10, 1000), daemon=True)
            thread.start()
            self.assertTrue(first.wait(1))
            time.sleep(0.1)
            self.assertEqual(len(calls), 1)
            wake.set()
            self.assertTrue(second.wait(1))
            stop.set()
            wake.set()
            thread.join(1)
        self.assertFalse(thread.is_alive())

    def test_pending_local_change_is_not_overwritten_by_stale_feishu_pull(self):
        portal_store.mirror_record("candidate_output", {"record_id": "recOne", "fields": {"姓名": "飞书旧值"}})
        portal_store.merge_fields("candidate_output", "recOne", {"姓名": "本地新值"})
        portal_store.mirror_record("candidate_output", {"record_id": "recOne", "fields": {"姓名": "飞书旧值"}})
        row = portal_store.get_record("candidate_output", "recOne")
        self.assertEqual(row["fields"]["姓名"], "本地新值")
        self.assertEqual(row["sync_state"], "pending")

    def test_multiple_local_changes_are_coalesced_and_version_safe(self):
        portal_store.mirror_record("candidate_output", {"record_id": "recOne", "fields": {"姓名": "旧值"}})
        first = portal_store.merge_fields("candidate_output", "recOne", {"姓名": "新值"})
        second = portal_store.merge_fields("candidate_output", "recOne", {"AR_推荐状态": "停止"})
        self.assertEqual(second["pending_fields"], {"姓名": "新值", "AR_推荐状态": "停止"})
        portal_store.mark_synced("candidate_output", "recOne", first["version"], "recOne")
        self.assertEqual(portal_store.get_record("candidate_output", "recOne")["sync_state"], "pending")
        portal_store.mark_synced("candidate_output", "recOne", second["version"], "recOne")
        row = portal_store.get_record("candidate_output", "recOne")
        self.assertEqual(row["sync_state"], "synced")
        self.assertEqual(row["pending_fields"], {})

    def test_failed_sync_records_error_and_retry(self):
        portal_store.mirror_record("candidate_output", {"record_id": "recOne", "fields": {"姓名": "旧值"}})
        pending = portal_store.merge_fields("candidate_output", "recOne", {"姓名": "新值"})
        portal_store.mark_failed("candidate_output", "recOne", pending["version"], "temporary failure")
        row = portal_store.get_record("candidate_output", "recOne")
        self.assertEqual(row["sync_state"], "failed")
        self.assertEqual(row["attempts"], 1)
        self.assertIn("temporary failure", row["last_error"])
        self.assertIsNotNone(row["next_attempt_at"])

    def test_schema_cache_round_trip(self):
        schema = [{"name": "姓名", "type": 1, "options": [], "required": True, "readonly": False}]
        portal_store.save_schema("candidate_output", schema)
        self.assertEqual(portal_store.get_schema("candidate_output"), schema)

    def test_attachment_cache_round_trip_and_prune(self):
        portal_store.mirror_record("candidate_output", {
            "record_id": "recOne", "fields": {"简历": [{"file_token": "fileOne"}]}
        })
        portal_store.save_attachment("candidate_output", "recOne", "简历", {
            "file_token": "fileOne", "name": "resume.txt", "content_type": "text/plain",
        }, b"resume content")
        cached = portal_store.get_attachment("candidate_output", "recOne", "简历", "fileOne")
        self.assertEqual(cached["content"], b"resume content")
        self.assertEqual(cached["name"], "resume.txt")
        self.assertEqual(portal_store.prune_attachments("candidate_output", "recOne", "简历", []), 1)
        self.assertIsNone(portal_store.get_attachment("candidate_output", "recOne", "简历", "fileOne"))

    def test_feishu_pull_caches_attachment_bytes_in_sql(self):
        class AttachmentClient(FakeClient):
            def download_attachment(self, item, path):
                path.write_bytes(b"downloaded resume")

        client = AttachmentClient()
        client.rows["candidate_output"].append({"record_id": "recOne", "fields": {
            "简历": [{"file_token": "fileOne", "name": "resume.txt"}],
        }})
        with patch.object(portal_data, "_table", side_effect=lambda kind: kind):
            portal_sync.pull_from_feishu(client, "app")
        cached = portal_store.get_attachment("candidate_output", "recOne", "简历", "fileOne")
        self.assertEqual(cached["content"], b"downloaded resume")

    def test_local_attachment_is_committed_before_background_feishu_upload(self):
        class UploadClient(FakeClient):
            def upload_attachment(self, path, _app_token):
                self.uploaded = path.read_bytes()
                return "remoteFileOne"

        client = UploadClient()
        client.fields["candidate_output"].append({"field_name": "AR_记录类型", "type": 1})
        portal_store.merge_fields("candidate_output", "localOne", {"AR_记录类型": "account"})
        portal_store.save_attachment("candidate_output", "localOne", "简历", {
            "file_token": "local_attachment_one", "name": "resume.txt", "content_type": "text/plain",
        }, b"local resume")
        portal_store.merge_fields("candidate_output", "localOne", {
            "简历": [{"file_token": "local_attachment_one", "name": "resume.txt"}],
        })
        self.assertEqual(portal_store.get_attachment(
            "candidate_output", "localOne", "简历", "local_attachment_one")["sync_state"], "pending")
        with patch.object(portal_data, "_table", side_effect=lambda kind: kind):
            result = portal_sync.sync_pending_once(client, "app")
        self.assertEqual(result, {"synced": 2, "failed": 0})
        self.assertEqual(client.uploaded, b"local resume")
        self.assertEqual(client.rows["candidate_output"][0]["fields"]["简历"][0]["file_token"], "remoteFileOne")
        cached = portal_store.get_attachment(
            "candidate_output", "localOne", "简历", "local_attachment_one")
        self.assertEqual(cached["sync_state"], "synced")
        self.assertEqual(cached["feishu_file_token"], "remoteFileOne")

    def test_portal_preference_stays_in_postgres_and_never_enters_sync_queue(self):
        portal_store.save_preference("account-one", "job_order", ["job-b", "job-a"])
        self.assertEqual(portal_store.get_preference("account-one", "job_order"), ["job-b", "job-a"])
        self.assertEqual(portal_store.pending_records(), [])

    def test_sql_schema_cache_is_used_without_calling_feishu(self):
        schema = [{"name": "姓名", "type": 1, "options": [], "required": True, "readonly": False}]
        portal_store.save_schema("candidate_output", schema)

        class OfflineClient:
            def pages(self, _path):
                raise RuntimeError("offline")

        with patch.dict(os.environ, {"AR_LOCAL_PRIMARY": "1"}), \
             patch.object(portal_data, "_table", return_value="candidate_output"):
            self.assertEqual(portal_data.candidate_form_schema(OfflineClient(), "app"), schema)

    def test_feishu_only_source_field_is_hidden_even_in_cached_schema(self):
        schema = [
            {"name": "姓名", "type": 1, "options": [], "required": True, "readonly": False},
            {"name": "来源", "type": 3, "options": ["内部"], "required": False, "readonly": False},
            {"name": "意向投递的目标公司", "type": 1, "options": [], "required": False, "readonly": False},
        ]
        portal_store.save_schema("candidate_output", schema)
        with patch.dict(os.environ, {"AR_LOCAL_PRIMARY": "1"}):
            visible = portal_data.candidate_form_schema(FakeClient(), "app")
        self.assertEqual([item["name"] for item in visible], ["姓名", "意向投递的目标公司"])

    def test_sync_worker_writes_pending_fields_to_feishu(self):
        client = FakeClient()
        client.fields["candidate_output"].append({"field_name": "AR_推荐状态", "type": 1})
        client.rows["candidate_output"].append({"record_id": "recOne", "fields": {"AR_推荐状态": "开启"}})
        portal_store.mirror_record("candidate_output", client.rows["candidate_output"][0])
        portal_store.merge_fields("candidate_output", "recOne", {"AR_推荐状态": "停止"})
        with patch.object(portal_data, "_table", side_effect=lambda kind: kind):
            result = portal_sync.sync_pending_once(client, "app")
        self.assertEqual(result, {"synced": 1, "failed": 0})
        self.assertEqual(client.rows["candidate_output"][0]["fields"]["AR_推荐状态"], "停止")
        self.assertEqual(portal_store.get_record("candidate_output", "recOne")["sync_state"], "synced")

    def test_sync_worker_retries_after_feishu_failure(self):
        class BrokenClient:
            def request(self, *_args, **_kwargs):
                raise RuntimeError("Feishu unavailable")

        portal_store.mirror_record("candidate_output", {"record_id": "recOne", "fields": {"姓名": "旧值"}})
        portal_store.merge_fields("candidate_output", "recOne", {"姓名": "新值"})
        with patch.object(portal_data, "_table", side_effect=lambda kind: kind):
            result = portal_sync.sync_pending_once(BrokenClient(), "app")
        self.assertEqual(result, {"synced": 0, "failed": 1})
        self.assertEqual(portal_store.get_record("candidate_output", "recOne")["sync_state"], "failed")

    def test_sql_delete_is_queued_then_removed_from_feishu(self):
        client = FakeClient()
        remote = {"record_id": "recOne", "fields": {"AR_记录类型": "account", "AR_手机号": "13800138000"}}
        client.rows["candidate_output"].append(copy.deepcopy(remote))
        portal_store.mirror_record("candidate_output", remote)
        portal_store.delete_records("candidate_output", ["recOne"])
        self.assertEqual(len(portal_store.pending_deletions()), 1)
        with patch.object(portal_data, "_table", side_effect=lambda kind: kind):
            self.assertEqual(portal_sync.sync_pending_once(client, "app"), {"synced": 1, "failed": 0})
        self.assertEqual(client.rows["candidate_output"], [])
        self.assertEqual(portal_store.pending_deletions(), [])


class LocalPrimaryCandidateTests(unittest.TestCase):
    def setUp(self):
        isolated_schema(self)
        self.env = patch.dict(os.environ, {"AR_LOCAL_PRIMARY": "1"})
        self.env.start()
        self.addCleanup(self.env.stop)
        portal_store.ensure_schema()
        recommendation_store.ensure_schema()
        self.client = FakeClient()
        self.client_patch = patch.object(portal_data, "_client", return_value=(self.client, "app"))
        self.table_patch = patch.object(portal_data, "_table", side_effect=lambda kind: kind)
        self.client_patch.start()
        self.table_patch.start()
        self.addCleanup(self.client_patch.stop)
        self.addCleanup(self.table_patch.stop)
        portal_data.ensure_schema()

    def test_candidate_save_returns_from_postgres_before_feishu_sync(self):
        candidate = portal_data.register("candidate", "13800138000", "abcde")
        writes_before = len(self.client.writes)
        saved = portal_data.save_candidate(candidate, name="张三", description="产品经历", enabled=False)
        self.assertEqual(saved["name"], "张三")
        self.assertFalse(saved["enabled"])
        self.assertEqual(saved["sync"]["status"], "pending")
        self.assertEqual(len(self.client.writes), writes_before)
        self.assertEqual(self.client.rows["candidate_output"], [])
        result = portal_sync.sync_pending_once(self.client, "app")
        self.assertEqual(result["synced"], 1)
        remote = self.client.rows["candidate_output"][0]["fields"]
        self.assertEqual(remote["姓名"], "张三")
        self.assertEqual(remote["AR_推荐状态"], "停止")

    def test_recommendation_toggle_coalesces_before_sync(self):
        candidate = portal_data.register("candidate", "13800138000", "abcde")
        portal_data.save_candidate(candidate, enabled=False)
        portal_data.save_candidate(candidate, enabled=True)
        pending = portal_store.pending_records()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["pending_fields"]["AR_推荐状态"], "开启")
        writes_before = len(self.client.writes)
        portal_sync.sync_pending_once(self.client, "app")
        self.assertEqual(len(self.client.writes), writes_before + 1)
        self.assertEqual(self.client.rows["candidate_output"][0]["fields"]["AR_推荐状态"], "开启")

    def test_account_admin_create_and_delete_are_sql_first(self):
        created = account_admin.create_account("candidate", "13800138000", "abcde")
        self.assertTrue(created["id"].startswith("local_"))
        self.assertEqual(self.client.rows["candidate_output"], [])
        portal_sync.sync_pending_once(self.client, "app")
        self.assertEqual(len(self.client.rows["candidate_output"]), 1)

        deleted = account_admin.delete_account("candidate", created["id"], "13800138000")
        self.assertTrue(deleted["deleted"])
        self.assertIsNone(portal_store.get_record("candidate_output", created["id"]))
        self.assertEqual(len(self.client.rows["candidate_output"]), 1)
        portal_sync.sync_pending_once(self.client, "app")
        self.assertEqual(self.client.rows["candidate_output"], [])


class LocalPrimaryAlumniTests(unittest.TestCase):
    def setUp(self):
        isolated_schema(self)
        self.env = patch.dict(os.environ, {"AR_LOCAL_PRIMARY": "1"})
        self.env.start()
        self.addCleanup(self.env.stop)
        portal_store.ensure_schema()
        recommendation_store.ensure_schema()
        self.client = FakeClient()
        self.client_patch = patch.object(portal_data, "_client", return_value=(self.client, "app"))
        self.table_patch = patch.object(portal_data, "_table", side_effect=lambda kind: kind)
        self.client_patch.start()
        self.table_patch.start()
        self.addCleanup(self.client_patch.stop)
        self.addCleanup(self.table_patch.stop)
        portal_data.ensure_schema()

    def test_company_and_new_job_are_created_locally_then_synced(self):
        owner = portal_data.register("alumni", "13800138000", "abcde")
        writes_before = len(self.client.writes)
        company = portal_data.save_alumni_company(owner, "测试企业", "张三", "HR")
        job = portal_data.save_job(owner, title="产品经理", body="负责产品设计", **JOB_ARGS)
        self.assertEqual(company["company"], "测试企业")
        self.assertTrue(job["id"].startswith("local_"))
        self.assertEqual(len(self.client.writes), writes_before)
        self.assertEqual(len(portal_store.pending_records()), 2)
        self.assertEqual(self.client.rows["alumni_output"], [])

        result = portal_sync.sync_pending_once(self.client, "app")
        self.assertEqual(result, {"synced": 2, "failed": 0})
        remote_account = next(row for row in self.client.rows["alumni_output"] if row["fields"].get("AR_记录类型") == "account")
        remote_job = next(row for row in self.client.rows["alumni_output"] if row["fields"].get("AR_记录类型") == "job")
        self.assertEqual(remote_account["fields"]["AR_企业名称"], "测试企业")
        self.assertEqual(remote_account["fields"]["填写人姓名"], "张三")
        self.assertEqual(remote_account["fields"]["填写人职务"], "HR")
        self.assertEqual(remote_job["fields"]["AR_岗位名称"], "产品经理")
        self.assertEqual(remote_job["fields"][portal_data.JOB_LOCATION_FIELD], JOB_ARGS["work_location"])
        self.assertEqual(remote_job["fields"][portal_data.JOB_ATTENDANCE_FIELD], JOB_ARGS["attendance_mode"])
        self.assertEqual(remote_job["fields"][portal_data.JOB_CATEGORY_FIELD], JOB_ARGS["job_categories"])
        self.assertEqual(remote_job["fields"][portal_data.JOB_MIN_DAYS_FIELD], JOB_ARGS["min_days_per_week"])
        mapped = portal_store.get_record("alumni_output", job["id"])
        self.assertEqual(mapped["feishu_record_id"], remote_job["record_id"])

        portal_sync.pull_from_feishu(self.client, "app")
        local_jobs = [row for row in portal_store.list_records("alumni_output") if row["fields"].get("AR_记录类型") == "job"]
        self.assertEqual(len(local_jobs), 1)
        self.assertEqual(local_jobs[0]["local_id"], job["id"])

    def test_job_order_is_account_scoped_sql_only_and_controls_listing(self):
        owner = portal_data.register("alumni", "13800138000", "abcde")
        portal_data.save_alumni_company(owner, "测试企业", "张三", "HR")
        first = portal_data.save_job(owner, title="产品", body="产品 JD", **JOB_ARGS)
        second = portal_data.save_job(owner, title="技术", body="技术 JD", **JOB_ARGS)
        third = portal_data.save_job(owner, title="运营", body="运营 JD", **JOB_ARGS)
        pending_before = [row["local_id"] for row in portal_store.pending_records()]
        writes_before = len(self.client.writes)
        saved = portal_data.save_job_order(owner, [second["id"], first["id"]])
        self.assertEqual(saved["job_ids"], [second["id"], first["id"]])
        self.assertEqual([job["id"] for job in portal_data.list_jobs(owner)], [second["id"], first["id"], third["id"]])
        self.assertEqual([row["local_id"] for row in portal_store.pending_records()], pending_before)
        self.assertEqual(len(self.client.writes), writes_before)

    def test_hiring_feedback_never_waits_for_feishu_schema(self):
        owner = portal_data.register("alumni", "13800138000", "abcde")
        portal_data.save_alumni_company(owner, "测试企业", "张三", "HR")
        job = portal_data.save_job(owner, title="产品经理", body="负责产品设计", **JOB_ARGS)
        candidate = portal_data.register("candidate", "13900139000", "abcde")
        rec = recommendation_store.create(job["id"] + ":2:hash", candidate["id"], owner["id"], "候选人", "资料", 4, "适合")
        writes_before = len(self.client.writes)
        portal_data.feedback(owner, rec["id"], "感兴趣")
        with patch.object(portal_data, "ensure_schema", side_effect=AssertionError("must not call Feishu schema")):
            saved = portal_data.feedback(owner, rec["id"], "录用")
        self.assertEqual(saved["status"], "录用")
        self.assertEqual(len(self.client.writes), writes_before)
        self.assertGreaterEqual(len(portal_store.pending_records()), 2)


if __name__ == "__main__":
    unittest.main()
