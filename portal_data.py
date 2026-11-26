"""Feishu-backed candidate and alumni portals. Writes are restricted to AR output tables."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

from ar import Client, FeishuError, identifiers, table_path
from build_web import ROOT, TABLES
from credentials import get_credentials
import recommendation_store
import portal_store


WRITE_LOCK = threading.RLock()

class MpLoginError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)
PREFIX = "AR_"
CANDIDATE_FIELDS = ["AR_记录类型", "AR_手机号", "AR_密码摘要", "AR_MP用户ID", "AR_姓名", "AR_简历说明", "AR_推荐状态", "AR_来源记录ID", "AR_更新时间", "AR_提交状态", "AR_已推荐JD", "AR_录用JD"]
ALUMNI_CONTACT_NAME_FIELD = "填写人姓名"
ALUMNI_CONTACT_ROLE_FIELD = "填写人职务"
LEGACY_ALUMNI_CONTACT_FIELD = "填写人与职位"
ALUMNI_FIELDS = ["AR_记录类型", "AR_手机号", "AR_密码摘要", "AR_MP用户ID", "AR_账户ID", "AR_企业名称", "AR_联系人手机号", "AR_岗位名称", "AR_JD正文", "AR_招聘状态", "AR_来源JD", "AR_已录用候选人", "AR_更新时间", ALUMNI_CONTACT_NAME_FIELD, ALUMNI_CONTACT_ROLE_FIELD]
JOB_LOCATION_FIELD = "工作地点"
JOB_ATTENDANCE_FIELD = "出勤方式"
JOB_CATEGORY_FIELD = "岗位类别"
JOB_MIN_DAYS_FIELD = "每周最少到岗天数"
JOB_LATEST_ARRIVAL_FIELD = "最晚到岗日期"
JOB_ATTENDANCE_OPTIONS = ("线上", "线下", "线上线下结合")
JOB_CATEGORY_OPTIONS = ("日常实习", "可转正", "校招", "社职")
JOB_MIN_DAYS_OPTIONS = ("1天", "2天", "3天", "4天", "5天")
JOB_FIELD_SPECS = {
    JOB_LOCATION_FIELD: {"type": 1},
    JOB_ATTENDANCE_FIELD: {"type": 3, "property": {"options": [{"name": value} for value in JOB_ATTENDANCE_OPTIONS]}},
    JOB_CATEGORY_FIELD: {"type": 4, "property": {"options": [{"name": value} for value in JOB_CATEGORY_OPTIONS]}},
    JOB_MIN_DAYS_FIELD: {"type": 3, "property": {"options": [{"name": value} for value in JOB_MIN_DAYS_OPTIONS]}},
    JOB_LATEST_ARRIVAL_FIELD: {"type": 5},
}
CANDIDATE_NAME_FIELD = "姓名"
CANDIDATE_PHONE_FIELD = "手机号/微信号"
SOURCE_CANDIDATE_NAME_FIELD = "姓名"
SOURCE_CANDIDATE_PHONE_FIELD = "手机号/微信号"
BASE_FIELD = "意向base地（eg.北京,上海）"
BASE_OTHER_FIELD = "意向base地（可多选）-其他-补充内容"
CONSENT_FIELD = "是否同意奇绩被投企业与你直接取得联系？"
CONSENT_OTHER_FIELD = "是否同意奇绩被投企业与你直接取得联系？-其他-补充内容"
REQUIRED_CANDIDATE_FIELDS = {
    CANDIDATE_NAME_FIELD, "简历", BASE_FIELD, "意向出勤方式",
    "当前求职类别（多选）", "意向岗位", "最早到岗时间",
    "每周到岗天数", "你是通过什么渠道了解到的招聘信息？若是经人推荐，可填写推荐人姓名",
    CONSENT_FIELD,
}
ALLOWED_WRITES = {"candidate_output", "alumni_output"}
HIDDEN_CANDIDATE_FIELDS = {"来源", BASE_OTHER_FIELD}


def _visible_candidate_schema(schema: list[dict]) -> list[dict]:
    position_options = None
    if portal_store.enabled():
        try:
            from matching_domain import taxonomy
            position_options = [row["label"] for row in taxonomy()]
        except Exception:
            position_options = None
    result = []
    for source in schema:
        if source.get("name") in HIDDEN_CANDIDATE_FIELDS:
            continue
        item = dict(source)
        item["required"] = item.get("name") in REQUIRED_CANDIDATE_FIELDS
        if item.get("name") == "意向岗位" and position_options:
            item["options"] = position_options
        result.append(item)
    return result


def _table(kind: str) -> str:
    if kind not in ALLOWED_WRITES:
        raise ValueError("门户只能写入两张 AR 表")
    table_id = next((item["id"] for item in TABLES if item["kind"] == kind), None)
    if table_id is None:
        raise ValueError(f"门户配置缺少 {kind} 表")
    return table_id


def _client() -> tuple[Client, str]:
    config_json = os.environ.get("AR_CONFIG_JSON")
    config = json.loads(config_json if config_json is not None else (ROOT / "ar.json").read_text(encoding="utf-8"))
    app_token, _ = identifiers(config["base_url"])
    return Client(*get_credentials()), app_token


def _path(app_token: str, kind: str) -> str:
    return table_path(app_token, _table(kind))


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float)):
        return str(value)
    if isinstance(value, list):
        return "、".join(filter(None, (_text(part) for part in value)))
    if isinstance(value, dict):
        return _text(value.get("text") or value.get("name") or value.get("value"))
    return ""


def _field(record: dict, name: str) -> str:
    return _text((record.get("fields") or {}).get(name)).strip()


def refresh_candidate_form_schema(client: Client, app_token: str) -> list[dict]:
    schema = []
    for field in client.pages(_path(app_token, "candidate_output") + "/fields"):
        name, kind = field.get("field_name", ""), field.get("type")
        if not name or name.startswith(PREFIX) or name in HIDDEN_CANDIDATE_FIELDS or name == CONSENT_OTHER_FIELD or kind not in {1, 3, 4, 5, 17}:
            continue
        properties = field.get("property") or {}
        options = [item["name"] for item in properties.get("options", []) if item.get("name")]
        if name == CONSENT_FIELD:
            options = [option for option in options if option != "其他"]
        schema.append({"name": name, "type": kind,
                       "options": options,
                       "required": name in REQUIRED_CANDIDATE_FIELDS,
                       "readonly": name == CANDIDATE_PHONE_FIELD or bool(properties.get("auto_fill"))})
    if portal_store.enabled():
        portal_store.save_schema("candidate_output", schema)
    return _visible_candidate_schema(schema)


def candidate_form_schema(client: Client, app_token: str) -> list[dict]:
    """Describe the SQL-cached candidate form; Feishu refreshes it asynchronously."""
    if portal_store.enabled():
        cached = portal_store.get_schema("candidate_output", max_age_seconds=None)
        if cached is not None:
            return _visible_candidate_schema(cached)
        raise RuntimeError("候选人字段尚未同步到 PostgreSQL，请稍后重试")
    try:
        return refresh_candidate_form_schema(client, app_token)
    except Exception:
        raise


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _records(client: Client, app_token: str, kind: str) -> list[dict]:
    if portal_store.enabled() and kind in ALLOWED_WRITES:
        return [{"record_id": row["local_id"], "fields": dict(row["fields"])} for row in portal_store.list_records(kind)]
    records = list(client.pages(_path(app_token, kind) + "/records"))
    if portal_store.enabled() and kind in ALLOWED_WRITES:
        for record in records:
            portal_store.mirror_record(kind, record)
    return records


def _record(client: Client, app_token: str, kind: str, record_id: str) -> dict:
    if not re.fullmatch(r"(?:rec|local_)[A-Za-z0-9]+", record_id):
        raise ValueError("记录 ID 无效")
    if portal_store.enabled() and kind in ALLOWED_WRITES:
        local = portal_store.get_record(kind, record_id)
        if local:
            return {"record_id": local["local_id"], "fields": dict(local["fields"])}
        raise ValueError("记录不存在")
    value = client.request("GET", _path(app_token, kind) + "/records/" + record_id).get("record")
    if not value:
        raise ValueError("记录不存在")
    if portal_store.enabled() and kind in ALLOWED_WRITES:
        portal_store.mirror_record(kind, value)
    return value


def _create(client: Client, app_token: str, kind: str, fields: dict) -> dict:
    if kind not in ALLOWED_WRITES:
        raise ValueError("写入目标无效")
    if portal_store.enabled():
        row = portal_store.create_record(kind, fields)
        return {"record_id": row["local_id"], "fields": dict(row["fields"])}
    return client.request("POST", _path(app_token, kind) + "/records", body={"fields": fields})["record"]


def _update(client: Client, app_token: str, kind: str, record_id: str, fields: dict) -> dict:
    if kind not in ALLOWED_WRITES:
        raise ValueError("写入目标无效")
    if portal_store.enabled():
        row = portal_store.merge_fields(kind, record_id, fields)
        return {"record_id": row["local_id"], "fields": dict(row["fields"])}
    return client.request("PUT", _path(app_token, kind) + "/records/" + record_id, body={"fields": fields})["record"]


def ensure_schema() -> dict:
    """Idempotently create the portal columns in the two AR output tables."""
    client, app_token = _client()
    result = {}
    with WRITE_LOCK:
        for kind, required in (("candidate_output", CANDIDATE_FIELDS), ("alumni_output", ALUMNI_FIELDS)):
            existing = {item["field_name"]: item for item in client.pages(_path(app_token, kind) + "/fields")}
            base_fields = {CANDIDATE_NAME_FIELD: 1, CANDIDATE_PHONE_FIELD: 1, "简历": 17} if kind == "candidate_output" else {"公司名称（对外展示的名称）": 1, "公司介绍": 1}
            missing_base = [name for name, field_type in base_fields.items() if name not in existing or existing[name].get("type") != field_type]
            if missing_base:
                raise ValueError(f"{kind} 缺少预期字段或类型不符：{', '.join(missing_base)}。请按飞书最新字段名更新门户映射")
            wrong = [name for name in required if name in existing and existing[name].get("type") != 1]
            if wrong:
                raise ValueError(f"{kind} 中已有同名非文本字段：{', '.join(wrong)}")
            created = []
            for name in required:
                if name not in existing:
                    client.request("POST", _path(app_token, kind) + "/fields", body={"field_name": name, "type": 1})
                    created.append(name)
                    time.sleep(0.16)
            if kind == "alumni_output":
                for name, spec in JOB_FIELD_SPECS.items():
                    if name in existing and existing[name].get("type") != spec["type"]:
                        raise ValueError(f"alumni_output 中字段类型不符：{name}")
                    if name not in existing:
                        client.request("POST", _path(app_token, kind) + "/fields", body={"field_name": name, **spec})
                        created.append(name)
                        time.sleep(0.16)
            result[kind] = created
        if portal_store.enabled():
            refresh_candidate_form_schema(client, app_token)
    return result


def _phone(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"1[3-9]\d{9}", value.strip()):
        raise MpLoginError("invalid_phone", "奇绩账号未提供有效的中国大陆手机号")
    return value.strip()


def _password(value: str) -> str:
    if not isinstance(value, str) or len(value) < 5 or len(value) > 200:
        raise ValueError("密码至少 5 位，最多 200 位")
    return value


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    iterations = 500_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds, salt, expected = stored.split("$")
        if algorithm != "pbkdf2_sha256" or not 100_000 <= int(rounds) <= 1_000_000:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


def _kind(role: str) -> str:
    if role not in {"candidate", "alumni"}:
        raise ValueError("账户类型无效")
    return "candidate_output" if role == "candidate" else "alumni_output"


def _account(client: Client, app_token: str, role: str, phone: str) -> dict | None:
    return next((row for row in _records(client, app_token, _kind(role)) if _field(row, "AR_记录类型") == "account" and _field(row, "AR_手机号") == phone), None)


def register(role: str, phone: str, password: str) -> dict:
    phone, password = _phone(phone), _password(password)
    client, app_token = _client()
    with WRITE_LOCK:
        if _account(client, app_token, role, phone):
            raise ValueError("该手机号已注册，请直接登录")
        fields = {"AR_记录类型": "account", "AR_手机号": phone, "AR_密码摘要": _hash_password(password), "AR_更新时间": _now()}
        if role == "candidate":
            fields.update({"AR_推荐状态": "开启", CANDIDATE_PHONE_FIELD: phone})
        else:
            fields["AR_联系人手机号"] = phone
        record = _create(client, app_token, _kind(role), fields)
    return {"id": record["record_id"], "role": role, "phone": phone}


def login(role: str, phone: str, password: str) -> dict:
    phone, password = _phone(phone), _password(password)
    client, app_token = _client()
    account = _account(client, app_token, role, phone)
    if not account or not _verify_password(password, _field(account, "AR_密码摘要")):
        raise ValueError("手机号或密码错误")
    return {"id": account["record_id"], "role": role, "phone": phone}


def login_with_mp(role: str, subject: str, phone: str) -> dict:
    """Bind by mp's stable user ID, never claim an unbound account by phone alone."""
    _kind(role)
    if not isinstance(subject, str) or not subject or len(subject) > 120:
        raise ValueError("mp 用户身份无效")
    phone = _phone(phone)
    client, app_token = _client()
    with WRITE_LOCK:
        rows = [row for row in _records(client, app_token, _kind(role)) if _field(row, "AR_记录类型") == "account"]
        account = next((row for row in rows if _field(row, "AR_MP用户ID") == subject), None)
        if account:
            if _field(account, "AR_手机号") != phone:
                raise MpLoginError("phone_mismatch", "mp 手机号与已绑定账户不一致，请联系管理员核实")
            return {"id": account["record_id"], "role": role, "phone": phone}
        phone_matches = [row for row in rows if _field(row, "AR_手机号") == phone]
        has_unbound_match = len(phone_matches) == 1 and _field(phone_matches[0], "AR_MP用户ID") in (None, "")
        if has_unbound_match:
            record_id = phone_matches[0]["record_id"]
            _update(client, app_token, _kind(role), record_id, {"AR_MP用户ID": subject, "AR_更新时间": _now()})
            return {"id": record_id, "role": role, "phone": phone}
        if phone_matches:
            raise MpLoginError("phone_in_use", "该手机号已有账户，请联系管理员核实并绑定 mp 用户 ID")
        fields = {"AR_记录类型": "account", "AR_手机号": phone, "AR_MP用户ID": subject, "AR_更新时间": _now()}
        if role == "candidate":
            fields.update({"AR_推荐状态": "开启", CANDIDATE_PHONE_FIELD: phone})
        else:
            fields["AR_联系人手机号"] = phone
        record = _create(client, app_token, _kind(role), fields)
        return {"id": record["record_id"], "role": role, "phone": phone}


def _split_legacy_contact(value: str) -> tuple[str, str]:
    return str(value or "").strip(), ""


def greeting_name(value: str) -> str:
    """Format the welcome-name deterministically; stored contact data is unchanged."""
    name = str(value or "").strip()
    chinese = re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", name)
    if not chinese:
        return name
    try:
        from pypinyin import Style, lazy_pinyin
        text = "".join(lazy_pinyin("".join(chinese[-2:]), style=Style.NORMAL, errors="default", strict=False))
    except ImportError:
        return name
    return text[:1].upper() + text[1:].lower() if text else name


def account_data(identity: dict) -> dict:
    client, app_token = _client()
    row = _record(client, app_token, _kind(identity["role"]), identity["id"])
    if _field(row, "AR_记录类型") != "account" or _field(row, "AR_手机号") != identity["phone"]:
        raise ValueError("账户已失效")
    fields = row.get("fields") or {}
    local = portal_store.get_record(_kind(identity["role"]), identity["id"]) if portal_store.enabled() else None
    sync = {"status": local["sync_state"], "error": local["last_error"], "attempts": local["attempts"]} if local else {"status": "synced", "error": "", "attempts": 0}
    if identity["role"] == "candidate":
        files = fields.get("简历") or []
        schema = candidate_form_schema(client, app_token)
        values = {item["name"]: fields.get(item["name"]) for item in schema}
        values[CANDIDATE_PHONE_FIELD] = identity["phone"]
        status = _field(row, "AR_提交状态")
        submitted = status == "已提交" or (status != "草稿" and all(bool(values.get(item["name"])) for item in schema if item["required"]))
        return {"role": "candidate", "phone": identity["phone"], "name": _field(row, "AR_姓名") or _field(row, CANDIDATE_NAME_FIELD), "description": _field(row, "AR_简历说明"), "enabled": _field(row, "AR_推荐状态") != "停止", "files": [{"name": item.get("name", "简历"), "index": index} for index, item in enumerate(files) if isinstance(item, dict)], "schema": schema, "values": values, "submitted": submitted, "sync": sync}
    contact_name = _field(row, ALUMNI_CONTACT_NAME_FIELD)
    contact_role = _field(row, ALUMNI_CONTACT_ROLE_FIELD)
    if not contact_name or not contact_role:
        legacy_name, legacy_role = _split_legacy_contact(_field(row, LEGACY_ALUMNI_CONTACT_FIELD))
        contact_name = contact_name or legacy_name
        contact_role = contact_role or legacy_role
    return {"role": "alumni", "phone": identity["phone"], "company": _field(row, "AR_企业名称"), "contact_name": contact_name, "display_name": greeting_name(contact_name), "contact_role": contact_role, "contact_title": " · ".join(filter(None, (contact_name, contact_role))), "introduction": _field(row, "公司介绍"), "sync": sync}


def save_candidate(identity: dict, *, name: str | None = None, description: str | None = None, enabled: bool | None = None, form_fields: dict | None = None, draft: bool = False) -> dict:
    if identity["role"] != "candidate":
        raise ValueError("账户类型无效")
    fields = {"AR_更新时间": _now()}
    if form_fields is not None:
        if not isinstance(form_fields, dict):
            raise ValueError("资料格式无效")
        client, app_token = _client()
        schema = {item["name"]: item for item in candidate_form_schema(client, app_token)}
        for field_name, value in form_fields.items():
            item = schema.get(field_name)
            if not item or item["readonly"] or item["type"] == 17:
                raise ValueError(f"字段不可编辑：{field_name}")
            if item["type"] == 1:
                if not isinstance(value, str) or len(value) > 12000:
                    raise ValueError(f"字段内容无效：{field_name}")
                fields[field_name] = value.strip() or None
            elif item["type"] == 3:
                if not isinstance(value, (str, type(None))) or (value is not None and value != "" and value not in item["options"]):
                    raise ValueError(f"选项无效：{field_name}")
                fields[field_name] = value or None
            elif item["type"] == 4:
                if not isinstance(value, list) or any(option not in item["options"] for option in value):
                    raise ValueError(f"选项无效：{field_name}")
                fields[field_name] = list(dict.fromkeys(value))
            elif item["type"] == 5:
                if value is not None and (type(value) is not int or not 0 < value < 4102444800000):
                    raise ValueError(f"日期无效：{field_name}")
                fields[field_name] = value
        if CANDIDATE_NAME_FIELD in fields:
            name = fields[CANDIDATE_NAME_FIELD] or ""
    if name is not None:
        if not isinstance(name, str) or len(name.strip()) > 80:
            raise ValueError("姓名过长")
        fields.update({"AR_姓名": name.strip(), CANDIDATE_NAME_FIELD: name.strip()})
    if description is not None:
        if not isinstance(description, str) or len(description) > 12000:
            raise ValueError("简历说明过长")
        fields["AR_简历说明"] = description.strip()
    if enabled is not None:
        if type(enabled) is not bool:
            raise ValueError("推荐状态无效")
        fields["AR_推荐状态"] = "开启" if enabled else "停止"
    client, app_token = _client()
    with WRITE_LOCK:
        current = account_data(identity)
        if form_fields is not None:
            if draft:
                if not current["submitted"]:
                    fields["AR_提交状态"] = "草稿"
            else:
                for required_name in (item["name"] for item in current["schema"] if item["required"]):
                    if required_name == "简历":
                        if not current["files"]:
                            raise ValueError("请先上传简历")
                        continue
                    value = fields.get(required_name, current["values"].get(required_name))
                    if value is None or value == "" or value == []:
                        raise ValueError(f"请填写{required_name}")
                fields["AR_提交状态"] = "已提交"
        if portal_store.enabled():
            portal_store.merge_fields("candidate_output", identity["id"], fields)
        else:
            _update(client, app_token, "candidate_output", identity["id"], fields)
    return account_data(identity)


def remove_candidate_attachment(identity: dict, field_name: str, index: int) -> dict:
    if identity["role"] != "candidate" or type(index) is not int:
        raise ValueError("附件请求无效")
    client, app_token = _client()
    if not any(item["name"] == field_name and item["type"] == 17 for item in candidate_form_schema(client, app_token)):
        raise ValueError("附件字段无效")
    with WRITE_LOCK:
        account_data(identity)
        row = _record(client, app_token, "candidate_output", identity["id"])
        files = (row.get("fields") or {}).get(field_name) or []
        if not 0 <= index < len(files):
            raise ValueError("附件不存在")
        remaining = [{"file_token": item["file_token"]} for position, item in enumerate(files) if position != index and isinstance(item, dict) and item.get("file_token")]
        updates = {field_name: remaining, "AR_更新时间": _now()}
        if portal_store.enabled():
            portal_store.merge_fields("candidate_output", identity["id"], updates)
            portal_store.prune_attachments("candidate_output", identity["id"], field_name,
                                           [item["file_token"] for item in remaining])
        else:
            _update(client, app_token, "candidate_output", identity["id"], updates)
    return account_data(identity)


def save_alumni_company(identity: dict, company: str, contact_name: str | None = None, contact_role: str | None = None) -> dict:
    if identity["role"] != "alumni" or not isinstance(company, str) or not 1 <= len(company.strip()) <= 120:
        raise ValueError("请输入企业名称")
    client, app_token = _client()
    with WRITE_LOCK:
        current = account_data(identity)
        contact_name = current["contact_name"] if contact_name is None else str(contact_name).strip()
        contact_role = current["contact_role"] if contact_role is None else str(contact_role).strip()
        if not 1 <= len(contact_name) <= 120:
            raise ValueError("请填写你的姓名（最多 120 字）")
        if not 1 <= len(contact_role) <= 120:
            raise ValueError("请填写你的职务（最多 120 字）")
        fields = {"AR_企业名称": company.strip(), "公司名称（对外展示的名称）": company.strip(), ALUMNI_CONTACT_NAME_FIELD: contact_name, ALUMNI_CONTACT_ROLE_FIELD: contact_role, "AR_更新时间": _now()}
        if portal_store.enabled():
            portal_store.merge_fields("alumni_output", identity["id"], fields)
        else:
            _update(client, app_token, "alumni_output", identity["id"], fields)
        for row in _records(client, app_token, "alumni_output"):
            if _field(row, "AR_记录类型") == "job" and _field(row, "AR_账户ID") == identity["id"]:
                updates = {"AR_企业名称": company.strip(), "公司名称（对外展示的名称）": company.strip(), "AR_联系人手机号": identity["phone"], ALUMNI_CONTACT_NAME_FIELD: contact_name, ALUMNI_CONTACT_ROLE_FIELD: contact_role}
                if portal_store.enabled():
                    portal_store.merge_fields("alumni_output", row["record_id"], updates)
                else:
                    _update(client, app_token, "alumni_output", row["record_id"], updates)
    return account_data(identity)


def list_jobs(identity: dict) -> list[dict]:
    if identity["role"] != "alumni":
        raise ValueError("账户类型无效")
    client, app_token = _client()
    jobs = [{
        "id": row["record_id"], "title": _field(row, "AR_岗位名称"), "body": _field(row, "AR_JD正文"),
        "enabled": _field(row, "AR_招聘状态") != "停止", "source_id": _field(row, "AR_来源JD"),
        "work_location": _field(row, JOB_LOCATION_FIELD), "attendance_mode": _field(row, JOB_ATTENDANCE_FIELD),
        "job_categories": list((row.get("fields") or {}).get(JOB_CATEGORY_FIELD) or []),
        "min_days_per_week": _field(row, JOB_MIN_DAYS_FIELD),
        "latest_arrival_date": _job_date_text((row.get("fields") or {}).get(JOB_LATEST_ARRIVAL_FIELD)),
    } for row in _records(client, app_token, "alumni_output") if _field(row, "AR_记录类型") == "job" and _field(row, "AR_账户ID") == identity["id"]]
    if portal_store.enabled():
        saved_order = portal_store.get_preference(identity["id"], "job_order", [])
        if isinstance(saved_order, list):
            positions = {record_id: index for index, record_id in enumerate(saved_order) if isinstance(record_id, str)}
            jobs = [item[1] for item in sorted(enumerate(jobs), key=lambda item: (positions.get(item[1]["id"], len(positions) + item[0]), item[0]))]
    return jobs


def save_job_order(identity: dict, job_ids: list[str]) -> dict:
    if identity["role"] != "alumni" or not portal_store.enabled():
        raise ValueError("岗位顺序只能保存在本地数据库")
    if not isinstance(job_ids, list) or len(job_ids) > 500 or any(not isinstance(value, str) for value in job_ids):
        raise ValueError("岗位顺序无效")
    order = list(dict.fromkeys(job_ids))
    client, app_token = _client()
    owned = {row["record_id"] for row in _records(client, app_token, "alumni_output")
             if _field(row, "AR_记录类型") == "job" and _field(row, "AR_账户ID") == identity["id"]}
    if any(record_id not in owned for record_id in order):
        raise ValueError("岗位顺序包含无权访问的岗位")
    portal_store.save_preference(identity["id"], "job_order", order)
    return {"job_ids": order}


def _job_date_value(value: str) -> int | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("最晚到岗日期格式无效")
    try:
        date = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone(timedelta(hours=8)))
    except ValueError as error:
        raise ValueError("最晚到岗日期格式无效") from error
    return int(date.timestamp() * 1000)


def _job_date_text(value) -> str:
    if value in (None, ""):
        return ""
    try:
        timestamp = int(value)
        if timestamp < 10_000_000_000:
            timestamp *= 1000
        return datetime.fromtimestamp(timestamp / 1000, timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return ""


def save_job(identity: dict, *, record_id: str = "", title: str, body: str, work_location: str,
             attendance_mode: str, job_categories: list[str], min_days_per_week: str,
             latest_arrival_date: str = "", enabled: bool = True) -> dict:
    valid = (
        identity["role"] == "alumni"
        and isinstance(title, str) and 1 <= len(title.strip()) <= 120
        and isinstance(body, str) and 1 <= len(body.strip()) <= 12000
        and isinstance(work_location, str) and 1 <= len(work_location.strip()) <= 200
        and attendance_mode in JOB_ATTENDANCE_OPTIONS
        and isinstance(job_categories, list) and bool(job_categories)
        and all(isinstance(value, str) and value in JOB_CATEGORY_OPTIONS for value in job_categories)
        and min_days_per_week in JOB_MIN_DAYS_OPTIONS
        and type(enabled) is bool
    )
    if not valid:
        raise ValueError("请完整填写所有岗位必填信息")
    categories = list(dict.fromkeys(job_categories))
    latest_date = _job_date_value(latest_arrival_date)
    client, app_token = _client()
    account = account_data(identity)
    if not account["company"] or not account["contact_name"] or not account["contact_role"]:
        raise ValueError("请先完善企业名称、姓名和职务")
    fields = {"AR_岗位名称": title.strip(), "AR_JD正文": body.strip(), "AR_招聘状态": "招聘中" if enabled else "停止", "AR_更新时间": _now(), "AR_企业名称": account["company"], "公司名称（对外展示的名称）": account["company"], "AR_联系人手机号": identity["phone"], ALUMNI_CONTACT_NAME_FIELD: account["contact_name"], ALUMNI_CONTACT_ROLE_FIELD: account["contact_role"], "公司介绍": account["introduction"], JOB_LOCATION_FIELD: work_location.strip(), JOB_ATTENDANCE_FIELD: attendance_mode, JOB_CATEGORY_FIELD: categories, JOB_MIN_DAYS_FIELD: min_days_per_week, JOB_LATEST_ARRIVAL_FIELD: latest_date}
    with WRITE_LOCK:
        if record_id:
            existing = _record(client, app_token, "alumni_output", record_id)
            if _field(existing, "AR_记录类型") != "job" or _field(existing, "AR_账户ID") != identity["id"]:
                raise ValueError("无权修改这条 JD")
            if portal_store.enabled():
                result = {"record_id": record_id, "fields": portal_store.merge_fields("alumni_output", record_id, fields)["fields"]}
            else:
                result = _update(client, app_token, "alumni_output", record_id, fields)
        else:
            fields.update({"AR_记录类型": "job", "AR_账户ID": identity["id"]})
            if portal_store.enabled():
                local = portal_store.create_record("alumni_output", fields)
                result = {"record_id": local["local_id"], "fields": local["fields"]}
            else:
                result = _create(client, app_token, "alumni_output", fields)
    return {"id": result["record_id"], "title": title.strip(), "body": body.strip(), "enabled": enabled,
            "work_location": work_location.strip(), "attendance_mode": attendance_mode,
            "job_categories": categories, "min_days_per_week": min_days_per_week,
            "latest_arrival_date": latest_arrival_date or ""}


def update_job_status(identity: dict, record_id: str, enabled: bool) -> dict:
    if identity["role"] != "alumni" or type(enabled) is not bool:
        raise ValueError("岗位状态无效")
    client, app_token = _client()
    with WRITE_LOCK:
        existing = _record(client, app_token, "alumni_output", record_id)
        if _field(existing, "AR_记录类型") != "job" or _field(existing, "AR_账户ID") != identity["id"]:
            raise ValueError("无权修改这条 JD")
        fields = {"AR_招聘状态": "招聘中" if enabled else "停止", "AR_更新时间": _now()}
        if portal_store.enabled():
            portal_store.merge_fields("alumni_output", record_id, fields)
        else:
            _update(client, app_token, "alumni_output", record_id, fields)
    return {"id": record_id, "enabled": enabled}


def list_recommendations(identity: dict) -> list[dict]:
    if identity["role"] != "alumni":
        raise ValueError("账户类型无效")
    client, app_token = _client()
    rows = _records(client, app_token, "alumni_output")
    jobs = {row["record_id"]: row for row in rows if _field(row, "AR_记录类型") == "job" and _field(row, "AR_账户ID") == identity["id"]}
    source_ids = {_field(row, "AR_来源JD"): row for row in jobs.values() if _field(row, "AR_来源JD")}
    migrate_legacy_recommendations(rows)
    result = []
    for row in recommendation_store.all_rows():
        source_id = row["job_id"]
        linked = jobs.get(source_id.split(":")[0]) or source_ids.get(source_id) or next((job for ref, job in source_ids.items() if source_id.startswith(ref + ":")), None)
        if row["owner_id"] != identity["id"] and not linked:
            continue
        if row["status"] == "撤回":
            continue
        candidate_id = row["candidate_id"]
        try:
            from match_engine import _record as local_record

            resume_count = len((local_record("candidate", candidate_id).get("fields") or {}).get("简历") or [])
        except (ValueError, StopIteration):
            resume_count = 0
        result.append({"id": row["id"], "job_id": linked["record_id"] if linked else source_id, "job_title": _field(linked, "AR_岗位名称") if linked else "岗位推荐", "candidate_name": row["candidate_name"], "candidate_profile": row["candidate_profile"], "resume_count": resume_count, "stars": row["stars"], "reason": row["reason"], "assessment": row.get("assessment") or {}, "status": row["status"]})
    return result


def migrate_legacy_recommendations(rows: list[dict] | None = None) -> None:
    """Copy old process rows into SQLite; never mutate the historical Feishu rows."""
    if rows is None:
        client, app_token = _client()
        rows = _records(client, app_token, "alumni_output")
    for row in rows:
        if _field(row, "AR_记录类型") != "recommendation":
            continue
        source_id = _field(row, "AR_来源JD")
        candidate_id = _field(row, "AR_候选人ID")
        if not source_id or not candidate_id:
            continue
        recommendation_store.create(source_id, candidate_id, _field(row, "AR_账户ID"), _field(row, "AR_候选人姓名"), _field(row, "AR_候选人资料"), int(_field(row, "AR_星级") or 0), _field(row, "AR_评估理由"), legacy_id=row["record_id"], status=_field(row, "AR_流程状态") or "待反馈", interest=_field(row, "AR_意向反馈"))


def sync_business_outcomes() -> dict:
    """Rebuild useful Feishu summaries from the local per-JD process history."""
    with WRITE_LOCK:
        # The portal startup validates the remote schema once. User actions must
        # not wait for Feishu: in local-primary mode this method only updates the
        # durable PostgreSQL mirror and wakes the background sync worker.
        if not portal_store.enabled():
            ensure_schema()
        client, app_token = _client()
        alumni_rows = _records(client, app_token, "alumni_output")
        candidate_rows = _records(client, app_token, "candidate_output")
        migrate_legacy_recommendations(alumni_rows)
        accounts = {row["record_id"]: row for row in alumni_rows if _field(row, "AR_记录类型") == "account"}
        jobs = [row for row in alumni_rows if _field(row, "AR_记录类型") == "job"]
        candidates = {row["record_id"]: row for row in candidate_rows if _field(row, "AR_记录类型") == "account"}
        source_candidates = {_field(row, "AR_来源记录ID"): row for row in candidates.values() if _field(row, "AR_来源记录ID")}
        by_candidate: dict[str, dict[str, tuple[dict, bool]]] = {}
        by_job: dict[str, dict[str, dict]] = {}
        for item in recommendation_store.all_rows():
            if item["status"] == "撤回":
                continue
            job = next((row for row in jobs if item["job_id"].split(":")[0] == row["record_id"] or _field(row, "AR_来源JD") and (item["job_id"] == _field(row, "AR_来源JD") or item["job_id"].startswith(_field(row, "AR_来源JD") + ":"))), None)
            if job is None:
                continue
            candidate = candidates.get(item["candidate_id"]) or source_candidates.get(item["candidate_id"])
            if candidate is not None:
                entries = by_candidate.setdefault(candidate["record_id"], {})
                prior = entries.get(job["record_id"])
                entries[job["record_id"]] = (job, item["status"] == "录用" or bool(prior and prior[1]))
            if item["status"] == "录用":
                by_job.setdefault(job["record_id"], {})[item["candidate_id"]] = candidate or {"record_id": item["candidate_id"], "fields": {"AR_姓名": item["candidate_name"]}}

        changed = {"candidate_output": 0, "alumni_output": 0}
        for row in jobs:
            account = accounts.get(_field(row, "AR_账户ID"))
            updates = {}
            if account:
                company = _field(account, "AR_企业名称") or _field(account, "公司名称（对外展示的名称）")
                phone = _field(account, "AR_手机号")
                contact_name = _field(account, ALUMNI_CONTACT_NAME_FIELD)
                contact_role = _field(account, ALUMNI_CONTACT_ROLE_FIELD)
                if not contact_name or not contact_role:
                    legacy_name, legacy_role = _split_legacy_contact(_field(account, LEGACY_ALUMNI_CONTACT_FIELD))
                    contact_name, contact_role = contact_name or legacy_name, contact_role or legacy_role
                for field, value in (("AR_企业名称", company), ("公司名称（对外展示的名称）", company), ("AR_联系人手机号", phone), (ALUMNI_CONTACT_NAME_FIELD, contact_name), (ALUMNI_CONTACT_ROLE_FIELD, contact_role), ("公司介绍", _field(account, "公司介绍"))):
                    if value and _field(row, field) != value:
                        updates[field] = value
            labels = []
            for candidate in by_job.get(row["record_id"], {}).values():
                name = _field(candidate, "AR_姓名") or _field(candidate, CANDIDATE_NAME_FIELD) or "候选人"
                labels.append(f"{name}（{candidate['record_id']}）")
            hired = "\n".join(sorted(labels))
            if _field(row, "AR_已录用候选人") != hired:
                updates["AR_已录用候选人"] = hired
            if updates:
                if portal_store.enabled():
                    portal_store.merge_fields("alumni_output", row["record_id"], updates)
                else:
                    _update(client, app_token, "alumni_output", row["record_id"], updates)
                changed["alumni_output"] += 1

        for candidate_id, entries in by_candidate.items():
            row = candidates[candidate_id]
            labels = []
            hired_labels = []
            for job, hired in entries.values():
                account = accounts.get(_field(job, "AR_账户ID"))
                company = (_field(account, "AR_企业名称") or _field(account, "公司名称（对外展示的名称）")) if account else ""
                company = company or _field(job, "AR_企业名称") or _field(job, "公司名称（对外展示的名称）")
                label = f"{company} · {_field(job, 'AR_岗位名称')}（{job['record_id']}）"
                labels.append(label)
                if hired:
                    hired_labels.append(label)
            updates = {}
            for field, value in (("AR_已推荐JD", "\n".join(sorted(labels))), ("AR_录用JD", "\n".join(sorted(hired_labels)))):
                if _field(row, field) != value:
                    updates[field] = value
            if updates:
                if portal_store.enabled():
                    portal_store.merge_fields("candidate_output", candidate_id, updates)
                else:
                    _update(client, app_token, "candidate_output", candidate_id, updates)
                changed["candidate_output"] += 1
        return changed


def import_existing(identity: dict) -> dict:
    """Copy only source records whose contact field contains this account's phone."""
    from build_web import DATA, read_json
    from match_engine import JOB_FIELDS

    client, app_token = _client()
    if identity["role"] == "candidate":
        source_id = next(item["id"] for item in TABLES if item["kind"] == "candidate" and not item["archived"])
        records = read_json(DATA / source_id / "records.json", [])
        matches = [row for row in records if identity["phone"] in re.findall(r"(?<!\d)1[3-9]\d{9}(?!\d)", _field(row, SOURCE_CANDIDATE_PHONE_FIELD))]
        if len(matches) != 1:
            return {"imported": 0, "message": "没有找到唯一的同手机号简历"}
        source = matches[0]
        current = _record(client, app_token, "candidate_output", identity["id"])
        if _field(current, "AR_来源记录ID") == source["record_id"]:
            return {"imported": 0, "message": "这份简历已经导入"}
        destination_fields = {field["field_name"] for field in client.pages(_path(app_token, "candidate_output") + "/fields")}
        copied = {name: value for name, value in (source.get("fields") or {}).items() if name in destination_fields and not name.startswith(PREFIX) and name not in {"填写时间"}}
        copied.update({CANDIDATE_NAME_FIELD: _field(source, SOURCE_CANDIDATE_NAME_FIELD), CANDIDATE_PHONE_FIELD: _field(source, SOURCE_CANDIDATE_PHONE_FIELD), "AR_来源记录ID": source["record_id"], "AR_姓名": _field(source, SOURCE_CANDIDATE_NAME_FIELD), "AR_更新时间": _now()})
        with WRITE_LOCK:
            _update(client, app_token, "candidate_output", identity["id"], copied)
        return {"imported": 1, "message": "简历已导入"}
    source_id = next(item["id"] for item in TABLES if item["kind"] == "job" and not item["archived"])
    records = read_json(DATA / source_id / "records.json", [])
    existing = {_field(row, "AR_来源JD") for row in _records(client, app_token, "alumni_output") if _field(row, "AR_记录类型") == "job" and _field(row, "AR_账户ID") == identity["id"]}
    account_company = account_data(identity)["company"]
    imported = 0
    with WRITE_LOCK:
        for row in records:
            contacts = re.findall(r"(?<!\d)1[3-9]\d{9}(?!\d)", _field(row, "联系方式"))
            if identity["phone"] not in contacts:
                continue
            company = _field(row, "公司名称（对外展示的名称）")
            if company and not account_company:
                _update(client, app_token, "alumni_output", identity["id"], {"AR_企业名称": company, "公司名称（对外展示的名称）": company, "AR_更新时间": _now()})
                account_company = company
            for index, field in enumerate(JOB_FIELDS):
                body = _field(row, field)
                ref = f"{row['record_id']}:{index}"
                if not body or ref in existing:
                    continue
                title = next((line.strip() for line in body.splitlines() if line.strip()), f"岗位 {index + 1}")[:120]
                effective_company = company or account_company
                account = account_data(identity)
                _create(client, app_token, "alumni_output", {"AR_记录类型": "job", "AR_账户ID": identity["id"], "AR_企业名称": effective_company, "公司名称（对外展示的名称）": effective_company, "AR_联系人手机号": identity["phone"], ALUMNI_CONTACT_NAME_FIELD: account["contact_name"], ALUMNI_CONTACT_ROLE_FIELD: account["contact_role"], "公司介绍": account["introduction"], "AR_岗位名称": title, "AR_JD正文": body[:12000], "AR_招聘状态": "招聘中", "AR_来源JD": ref, "AR_更新时间": _now()})
                existing.add(ref)
                imported += 1
    return {"imported": imported, "message": f"已导入 {imported} 条 JD" if imported else "没有找到新的同手机号 JD"}


FLOW = {
    "待反馈": {"感兴趣", "不感兴趣"},
    "面试中": {"录用", "未录用", "不感兴趣", "待反馈"},
    "录用": {"面试中", "未录用", "不感兴趣", "待反馈"},
    "未录用": {"面试中", "录用", "不感兴趣", "待反馈"},
    "不感兴趣": {"感兴趣", "待反馈"},
}


def feedback(identity: dict, recommendation_id: str, status: str) -> dict:
    if identity["role"] != "alumni":
        raise ValueError("账户类型无效")
    with WRITE_LOCK:
        if not any(item["id"] == recommendation_id for item in list_recommendations(identity)):
            raise ValueError("无权反馈这条推荐")
        row = recommendation_store.get(recommendation_id)
        current = row["status"] if row else "待反馈"
        if current == status == "录用":
            sync_business_outcomes()
            return {"id": recommendation_id, "status": status}
        if status not in FLOW.get(current, set()):
            raise ValueError("当前状态不能执行此操作")
        stored = "面试中" if status == "感兴趣" else status
        recommendation_store.set_status(recommendation_id, stored, status if status in {"感兴趣", "不感兴趣"} else "" if status == "待反馈" else None)
        if current == "录用" or stored == "录用":
            sync_business_outcomes()
    return {"id": recommendation_id, "status": stored}


def publish_recommendation(job_id: str, candidate_id: str, stars: int, reason: str, jd_text: str, *, assessment: dict | None = None) -> dict:
    """Persist a manually confirmed match once, regardless of AI star rating."""
    from match_engine import _candidate_label, _job_text, candidate_profile

    client, app_token = _client()
    source = job_id.split(":")
    if len(source) < 3:
        raise ValueError("JD 标识无效")
    _job_text(job_id, jd_text)
    profile = candidate_profile(candidate_id)
    name = _candidate_label(candidate_id)
    with WRITE_LOCK:
        candidate_rows = [row for row in _records(client, app_token, "candidate_output") if _field(row, "AR_记录类型") == "account" and (row.get("record_id") == candidate_id or _field(row, "AR_来源记录ID") == candidate_id)]
        if not candidate_rows:
            raise ValueError("候选人未在 AR 候选人表中找到，请先同步数据")
        if any(_field(row, "AR_推荐状态") == "停止" for row in candidate_rows):
            return {"published": False, "reason": "候选人已停止推荐"}
        rows = _records(client, app_token, "alumni_output")
        matching_jobs = [row for row in rows if _field(row, "AR_记录类型") == "job" and (row["record_id"] == source[0] or _field(row, "AR_来源JD") and job_id.startswith(_field(row, "AR_来源JD") + ":"))]
        if not matching_jobs:
            raise ValueError("JD 未在 AR 校友表中找到，请先同步数据")
        if any(_field(row, "AR_招聘状态") == "停止" for row in matching_jobs):
            return {"published": False, "reason": "这条 JD 已停止招聘"}
        stable_job_id = job_id.rsplit(":", 1)[0]
        blocked = next((row for row in recommendation_store.all_rows()
                        if row["candidate_id"] == candidate_id
                        and row["job_id"].rsplit(":", 1)[0] == stable_job_id
                        and row["status"] in {"不感兴趣", "未录用"}), None)
        if blocked:
            return {"published": False, "reason": f"校友已将这位候选人标记为{blocked['status']}，不能再次推荐给此 JD"}
        existing = recommendation_store.find(job_id, candidate_id)
        if not existing:
            legacy = next((row for row in rows if _field(row, "AR_记录类型") == "recommendation" and _field(row, "AR_来源JD") == job_id and _field(row, "AR_候选人ID") == candidate_id), None)
            if legacy:
                existing = recommendation_store.create(job_id, candidate_id, _field(legacy, "AR_账户ID"), _field(legacy, "AR_候选人姓名"), _field(legacy, "AR_候选人资料"), int(_field(legacy, "AR_星级") or 0), _field(legacy, "AR_评估理由"), legacy_id=legacy["record_id"], status=_field(legacy, "AR_流程状态") or "待反馈", interest=_field(legacy, "AR_意向反馈"))
        if existing:
            sync_business_outcomes()
            return {"published": True, "cached": True, "record_id": existing["id"]}
        owner = next((_field(row, "AR_账户ID") for row in rows if _field(row, "AR_记录类型") == "job" and (row["record_id"] == source[0] or job_id.startswith(_field(row, "AR_来源JD") + ":") and _field(row, "AR_来源JD"))), "")
        result = recommendation_store.create(job_id, candidate_id, owner, name, profile[:12000], stars, reason[:12000], assessment=assessment)
        sync_business_outcomes()
    return {"published": True, "cached": False, "record_id": result["id"]}
