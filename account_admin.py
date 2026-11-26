"""Loopback data-center account administration."""

from __future__ import annotations

from datetime import datetime

import portal_store
import recommendation_store
from portal_data import (_field, register, sync_business_outcomes,
                         ALUMNI_CONTACT_NAME_FIELD, ALUMNI_CONTACT_ROLE_FIELD,
                         CANDIDATE_NAME_FIELD)


KINDS = {"candidate": "candidate_output", "alumni": "alumni_output"}


def _records(kind: str) -> list[dict]:
    return portal_store.list_records(KINDS[kind])


def _account_item(kind: str, row: dict, all_rows: list[dict], recommendations: list[dict]) -> dict:
    fields = dict(row["fields"])
    account_id = row["local_id"]
    if kind == "candidate":
        name = _field({"fields": fields}, "AR_姓名") or _field({"fields": fields}, CANDIDATE_NAME_FIELD)
        related = sum(item["candidate_id"] == account_id for item in recommendations)
        linked = {"recommendations": related, "jobs": 0}
        detail = name or "尚未填写姓名"
    else:
        name = _field({"fields": fields}, ALUMNI_CONTACT_NAME_FIELD)
        company = _field({"fields": fields}, "AR_企业名称") or _field({"fields": fields}, "公司名称（对外展示的名称）")
        jobs = [item for item in all_rows if _field({"fields": item["fields"]}, "AR_记录类型") == "job" and _field({"fields": item["fields"]}, "AR_账户ID") == account_id]
        related = sum(item["owner_id"] == account_id or any(item["job_id"] == job["local_id"] or item["job_id"].startswith(job["local_id"] + ":") for job in jobs) for item in recommendations)
        linked = {"jobs": len(jobs), "recommendations": related}
        detail = " · ".join(value for value in (company, name, _field({"fields": fields}, ALUMNI_CONTACT_ROLE_FIELD)) if value) or "尚未填写企业资料"
    updated = row.get("updated_at")
    return {"id": account_id, "role": kind, "phone": _field({"fields": fields}, "AR_手机号"),
            "name": name, "detail": detail, "linked": linked, "sync_state": row["sync_state"],
            "updated_at": updated.isoformat() if isinstance(updated, datetime) else str(updated or "")}


def list_accounts() -> dict:
    portal_store.ensure_schema()
    recommendations = recommendation_store.all_rows()
    items = []
    for role in ("candidate", "alumni"):
        rows = _records(role)
        for row in rows:
            if _field({"fields": row["fields"]}, "AR_记录类型") == "account":
                items.append(_account_item(role, row, rows, recommendations))
    items.sort(key=lambda item: (item["role"], item["phone"], item["id"]))
    return {"items": items, "counts": {"candidate": sum(item["role"] == "candidate" for item in items),
                                       "alumni": sum(item["role"] == "alumni" for item in items)}}


def create_account(role: str, phone: str, password: str) -> dict:
    if role not in KINDS:
        raise ValueError("账号类型无效")
    identity = register(role, phone, password)
    row = portal_store.get_record(KINDS[role], identity["id"])
    if row is None:
        raise RuntimeError("账号未写入 PostgreSQL")
    return _account_item(role, row, _records(role), recommendation_store.all_rows())


def delete_account(role: str, account_id: str, expected_phone: str) -> dict:
    if role not in KINDS:
        raise ValueError("账号类型无效")
    rows = _records(role)
    account = next((row for row in rows if row["local_id"] == account_id and _field({"fields": row["fields"]}, "AR_记录类型") == "account"), None)
    if account is None:
        raise ValueError("账号不存在或已删除")
    phone = _field({"fields": account["fields"]}, "AR_手机号")
    if not expected_phone or expected_phone != phone:
        raise ValueError("请输入完整手机号确认删除")
    related = []
    job_ids = []
    if role == "alumni":
        related = [row for row in rows if _field({"fields": row["fields"]}, "AR_记录类型") in {"job", "recommendation"} and _field({"fields": row["fields"]}, "AR_账户ID") == account_id]
        job_ids = [row["local_id"] for row in related if _field({"fields": row["fields"]}, "AR_记录类型") == "job"]
    else:
        # Clean up legacy Feishu recommendation rows that directly reference this candidate.
        related = [row for row in portal_store.list_records("alumni_output") if _field({"fields": row["fields"]}, "AR_记录类型") == "recommendation" and _field({"fields": row["fields"]}, "AR_候选人ID") == account_id]

    deleted_recommendations = recommendation_store.delete_related(
        candidate_id=account_id if role == "candidate" else "",
        owner_id=account_id if role == "alumni" else "",
        job_record_ids=job_ids,
    )
    portal_store.delete_records(KINDS[role], [account_id, *[row["local_id"] for row in related]] if role == "alumni" else [account_id])
    if role == "candidate" and related:
        portal_store.delete_records("alumni_output", [row["local_id"] for row in related])
    sync_business_outcomes()
    return {"deleted": True, "id": account_id, "role": role, "jobs": len(job_ids),
            "recommendations": deleted_recommendations}
