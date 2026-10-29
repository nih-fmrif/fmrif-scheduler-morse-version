"""Admin configuration and RBAC CSV import/export helpers."""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql import func
from werkzeug.datastructures import FileStorage

from scheduler import config, model

ADMIN_SETTING_KEY_LISTSERV = "core.listserv"
ADMIN_SETTING_KEY_DEFAULT_SENDER = "mail.default_sender"
ADMIN_SETTING_KEY_MAILING_LISTS = "mail.mailing_lists"
ADMIN_SETTINGS_TABLE_NAME = "app_settings"

USER_DEPT_IMPORT_KIND = "user-dept"
DEV_DEPT_IMPORT_KIND = "dev-dept"
DEVPERM_IMPORT_KIND = "devperm"

ADMIN_IMPORT_KINDS = (
    USER_DEPT_IMPORT_KIND,
    DEV_DEPT_IMPORT_KIND,
    DEVPERM_IMPORT_KIND,
)

CSV_HEADERS: Dict[str, Tuple[str, ...]] = {
    USER_DEPT_IMPORT_KIND: ("usr", "dept", "pi"),
    DEV_DEPT_IMPORT_KIND: ("dev", "dept"),
    DEVPERM_IMPORT_KIND: (
        "usr",
        "dev",
        "templates",
        "slot",
        "technologist",
        "medical",
        "training",
    ),
}


def admin_settings_available() -> bool:
    """Return whether the app settings table exists."""
    try:
        return inspect(model.db.engine).has_table(ADMIN_SETTINGS_TABLE_NAME)
    except Exception:
        return False


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def get_admin_setting(key: str, default: str = "") -> str:
    if not admin_settings_available():
        return default
    try:
        row = model.get(model.AppSetting, key)
    except SQLAlchemyError:
        return default
    if row is None or row.value is None:
        return default
    return str(row.value)


def set_admin_setting(
    key: str,
    value: str,
    *,
    updated_by: Optional[str] = None,
) -> bool:
    if not admin_settings_available():
        return False
    row = model.get(model.AppSetting, key)
    if row is None:
        row = model.AppSetting(key=key)
    row.value = _normalize_text(value)
    row.updated_by = _normalize_text(updated_by) or None
    model.db.session.add(row)
    return True


def get_admin_listserv() -> str:
    return _normalize_text(
        get_admin_setting(ADMIN_SETTING_KEY_LISTSERV, config.settings.core.listserv)
    )


def get_admin_default_sender() -> str:
    return _normalize_text(
        get_admin_setting(
            ADMIN_SETTING_KEY_DEFAULT_SENDER,
            str(config.settings.mail.default_sender)
            if config.settings.mail.default_sender is not None
            else "",
        )
    )


def _coerce_mailings(raw: Any) -> Dict[str, str]:
    if not isinstance(raw, dict):
        return dict(config.settings.mail.mailing_lists)
    out: Dict[str, str] = {}
    for name, desc in raw.items():
        if not isinstance(name, str):
            continue
        normalized_name = name.strip()
        if normalized_name == "":
            continue
        out[normalized_name] = "" if desc is None else str(desc)
    return out


def get_admin_mailing_lists() -> Dict[str, str]:
    raw = get_admin_setting(
        ADMIN_SETTING_KEY_MAILING_LISTS,
        json.dumps(config.settings.mail.mailing_lists, sort_keys=True),
    )
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        parsed = config.settings.mail.mailing_lists
    return _coerce_mailings(parsed)


def format_admin_mailing_lists_for_form() -> str:
    return json.dumps(get_admin_mailing_lists(), sort_keys=True, indent=2)


def parse_admin_mailing_lists(raw_text: str) -> Dict[str, str]:
    payload = _normalize_text(raw_text)
    if payload == "":
        return {}
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as ex:
        raise ValueError(f"mailing lists must be valid JSON: {ex}") from ex
    if not isinstance(parsed, dict):
        raise ValueError("mailing lists must be a JSON object")
    normalized = _coerce_mailings(parsed)
    if not normalized and parsed:
        raise ValueError("mailing lists must contain at least one non-empty key")
    return normalized


def set_admin_listserv(value: str, *, updated_by: Optional[str] = None) -> bool:
    return set_admin_setting(
        ADMIN_SETTING_KEY_LISTSERV,
        _normalize_text(value),
        updated_by=updated_by,
    )


def set_admin_default_sender(value: str, *, updated_by: Optional[str] = None) -> bool:
    return set_admin_setting(
        ADMIN_SETTING_KEY_DEFAULT_SENDER,
        _normalize_text(value),
        updated_by=updated_by,
    )


def set_admin_mailing_lists(
    values: Dict[str, str],
    *,
    updated_by: Optional[str] = None,
) -> bool:
    normalized = _coerce_mailings(values)
    return set_admin_setting(
        ADMIN_SETTING_KEY_MAILING_LISTS,
        json.dumps(normalized, sort_keys=True, indent=2),
        updated_by=updated_by,
    )


def _read_csv_rows(
    file_obj: FileStorage, required_fields: Sequence[str]
) -> List[Dict[str, str]]:
    if not isinstance(file_obj, FileStorage):
        raise ValueError("upload must be a CSV file")
    raw = file_obj.read()
    if not isinstance(raw, (bytes, bytearray)):
        raise ValueError("upload could not be read as bytes")
    try:
        raw_text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as ex:
        raise ValueError("upload must be UTF-8 encoded") from ex
    try:
        file_obj.seek(0)
    except (AttributeError, IOError):
        pass
    reader = csv.DictReader(io.StringIO(raw_text, newline=""))
    fieldnames = [
        name.strip() for name in (reader.fieldnames or []) if name is not None
    ]
    missing = [field for field in required_fields if field not in fieldnames]
    if missing:
        raise ValueError("CSV is missing required columns: " + ", ".join(missing))
    rows: List[Dict[str, str]] = []
    for row in reader:
        normalized = {
            field: _normalize_text(row.get(field, "")) for field in required_fields
        }
        if all(value == "" for value in normalized.values()):
            continue
        rows.append(normalized)
    return rows


def parse_admin_mapping_file(kind: str, file_obj: FileStorage) -> List[Dict[str, str]]:
    required = CSV_HEADERS.get(kind)
    if required is None:
        raise ValueError(f"invalid mapping kind: {kind}")
    return _read_csv_rows(file_obj, required)


def validate_user_dept_rows(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    seen_pairs = set()
    pi_by_dept: Dict[str, str] = {}
    errors: List[str] = []
    for row in rows:
        usr = row.get("usr", "")
        dept = row.get("dept", "")
        pi = row.get("pi", "").lower()
        if usr == "":
            errors.append("row has empty usr")
            continue
        if dept == "":
            errors.append(f"user-dept row missing dept for user {usr}")
            continue
        if pi not in {"", "pi"}:
            errors.append(f"{usr},{dept}: invalid pi marker '{pi}'")
            continue
        pair = (usr, dept)
        if pair in seen_pairs:
            errors.append(f"duplicate user-dept pair {usr},{dept}")
            continue
        seen_pairs.add(pair)
        if pi == "pi":
            existing_pi = pi_by_dept.get(dept, "")
            if existing_pi and existing_pi != usr:
                errors.append(f"department {dept} has multiple PI users")
                continue
            pi_by_dept[dept] = usr
        normalized.append({"usr": usr, "dept": dept, "pi": pi})
    user_ids = {row["usr"] for row in normalized}
    dept_ids = {row["dept"] for row in normalized}
    if user_ids:
        users = {
            row[0]
            for row in model.User.query.with_entities(model.User.id).filter(
                model.User.id.in_(list(user_ids))
            )
        }
        missing_users = sorted(user_ids - set(users))
        if missing_users:
            errors.append("unknown users: " + ", ".join(missing_users))
    if dept_ids:
        depts = {
            row[0]
            for row in model.Group.query.with_entities(model.Group.id).filter(
                model.Group.id.in_(list(dept_ids))
            )
        }
        missing_depts = sorted(dept_ids - set(depts))
        if missing_depts:
            errors.append("unknown departments: " + ", ".join(missing_depts))
    if errors:
        raise ValueError("\n".join(errors))
    return normalized


def validate_dev_dept_rows(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    seen_pairs = set()
    errors: List[str] = []
    for row in rows:
        dev = row.get("dev", "")
        dept = row.get("dept", "")
        if dev == "":
            errors.append("row has empty dev")
            continue
        if dept == "":
            errors.append(f"dev-dept row for device {dev} missing dept")
            continue
        pair = (dev, dept)
        if pair in seen_pairs:
            errors.append(f"duplicate device-department pair {dev},{dept}")
            continue
        seen_pairs.add(pair)
        normalized.append({"dev": dev, "dept": dept})
    dev_ids = {row["dev"] for row in normalized}
    dept_ids = {row["dept"] for row in normalized}
    if dev_ids:
        devices = {
            row[0]
            for row in model.Device.query.with_entities(model.Device.id).filter(
                model.Device.id.in_(list(dev_ids))
            )
        }
        missing_devs = sorted(dev_ids - set(devices))
        if missing_devs:
            errors.append("unknown devices: " + ", ".join(missing_devs))
    if dept_ids:
        depts = {
            row[0]
            for row in model.Group.query.with_entities(model.Group.id).filter(
                model.Group.id.in_(list(dept_ids))
            )
        }
        missing_depts = sorted(dept_ids - set(depts))
        if missing_depts:
            errors.append("unknown departments: " + ", ".join(missing_depts))
    if errors:
        raise ValueError("\n".join(errors))
    return normalized


def validate_devperm_rows(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    seen_pairs = set()
    errors: List[str] = []
    allowed = {"y", "n"}
    for row in rows:
        usr = row.get("usr", "")
        dev = row.get("dev", "")
        templates = row.get("templates", "").lower()
        slot = row.get("slot", "").lower()
        technologist = row.get("technologist", "").lower()
        medical = row.get("medical", "").lower()
        training = row.get("training", "").lower()
        if usr == "":
            errors.append("row has empty usr")
            continue
        if dev == "":
            errors.append(f"devperm row for user {usr} missing dev")
            continue
        values = {
            "templates": templates,
            "slot": slot,
            "technologist": technologist,
            "medical": medical,
            "training": training,
        }
        if any(value not in allowed for value in values.values()):
            bad = [
                f"{key}={value}"
                for key, value in values.items()
                if value not in allowed
            ]
            errors.append(f"{usr},{dev}: invalid permissions ({', '.join(bad)})")
            continue
        if all(value == "n" for value in values.values()):
            errors.append(f"{usr},{dev}: no permissions granted")
            continue
        pair = (usr, dev)
        if pair in seen_pairs:
            errors.append(f"duplicate user-device pair {usr},{dev}")
            continue
        seen_pairs.add(pair)
        normalized.append(
            {
                "usr": usr,
                "dev": dev,
                "templates": templates,
                "slot": slot,
                "technologist": technologist,
                "medical": medical,
                "training": training,
            }
        )
    user_ids = {row["usr"] for row in normalized}
    dev_ids = {row["dev"] for row in normalized}
    if user_ids:
        users = {
            row[0]
            for row in model.User.query.with_entities(model.User.id).filter(
                model.User.id.in_(list(user_ids))
            )
        }
        missing_users = sorted(user_ids - set(users))
        if missing_users:
            errors.append("unknown users: " + ", ".join(missing_users))
    if dev_ids:
        devices = {
            row[0]
            for row in model.Device.query.with_entities(model.Device.id).filter(
                model.Device.id.in_(list(dev_ids))
            )
        }
        missing_devs = sorted(dev_ids - set(devices))
        if missing_devs:
            errors.append("unknown devices: " + ", ".join(missing_devs))
    if errors:
        raise ValueError("\n".join(errors))
    return normalized


def validate_import_rows(kind: str, rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    if kind == USER_DEPT_IMPORT_KIND:
        return validate_user_dept_rows(rows)
    if kind == DEV_DEPT_IMPORT_KIND:
        return validate_dev_dept_rows(rows)
    if kind == DEVPERM_IMPORT_KIND:
        return validate_devperm_rows(rows)
    raise ValueError(f"invalid mapping kind: {kind}")


def apply_user_dept_rows(rows: List[Dict[str, str]]) -> int:
    model.PrimaryGroupMember.query.delete()
    model.GroupMember.query.delete()
    for row in rows:
        model.db.session.add(
            model.GroupMember(user=row["usr"], group=row["dept"], approved=func.now())
        )
        if row.get("pi") == "pi":
            model.db.session.add(
                model.PrimaryGroupMember(user=row["usr"], group=row["dept"])
            )
    return len(rows)


def apply_dev_dept_rows(rows: List[Dict[str, str]]) -> int:
    model.DeviceGroup.query.delete()
    for row in rows:
        model.db.session.add(model.DeviceGroup(device=row["dev"], group=row["dept"]))
    return len(rows)


def apply_devperm_rows(rows: List[Dict[str, str]]) -> int:
    model.UserDevice.query.delete()
    for row in rows:
        model.db.session.add(
            model.UserDevice(
                user=row["usr"],
                device=row["dev"],
                templates=row["templates"] == "y",
                slot=row["slot"] == "y",
                tech=row["technologist"] == "y",
                medical=row["medical"] == "y",
                training=row["training"] == "y",
            )
        )
    return len(rows)


def apply_import_rows(kind: str, rows: List[Dict[str, str]]) -> int:
    if kind == USER_DEPT_IMPORT_KIND:
        return apply_user_dept_rows(rows)
    if kind == DEV_DEPT_IMPORT_KIND:
        return apply_dev_dept_rows(rows)
    if kind == DEVPERM_IMPORT_KIND:
        return apply_devperm_rows(rows)
    raise ValueError(f"invalid mapping kind: {kind}")


def export_mapping_rows(kind: str) -> Tuple[Tuple[str, ...], List[Tuple[str, ...]]]:
    if kind == USER_DEPT_IMPORT_KIND:
        headers = ("usr", "dept", "pi")
        query = model.execute(
            """
            select
                gm.researchercode as usr,
                gm.deptcode as dept,
                coalesce(pgm.researchercode, '') as pi
            from groupmembers gm
            left join primarygroupmember pgm
                on pgm.researchercode = gm.researchercode
                and pgm.deptcode = gm.deptcode
            order by gm.deptcode, gm.researchercode
            """
        )
        rows = [
            (str(row.usr), str(row.dept), "pi" if row.pi == row.usr else "")
            for row in query.fetchall()
        ]
        return headers, rows
    if kind == DEV_DEPT_IMPORT_KIND:
        headers = ("dev", "dept")
        query = model.DeviceGroup.query.with_entities(
            model.DeviceGroup.device,
            model.DeviceGroup.group,
        ).order_by(model.DeviceGroup.group, model.DeviceGroup.device)
        rows = [(str(device_id), str(group_id)) for device_id, group_id in query.all()]
        return headers, rows
    if kind == DEVPERM_IMPORT_KIND:
        headers = (
            "usr",
            "dev",
            "templates",
            "slot",
            "technologist",
            "medical",
            "training",
        )
        query = model.UserDevice.query.with_entities(
            model.UserDevice.user,
            model.UserDevice.device,
            model.UserDevice.templates,
            model.UserDevice.slot,
            model.UserDevice.tech,
            model.UserDevice.medical,
            model.UserDevice.training,
        ).order_by(model.UserDevice.user, model.UserDevice.device)
        rows = [
            (
                str(usr),
                str(device),
                "y" if bool(templates) else "n",
                "y" if bool(slot) else "n",
                "y" if bool(tech) else "n",
                "y" if bool(medical) else "n",
                "y" if bool(training) else "n",
            )
            for usr, device, templates, slot, tech, medical, training in query.all()
        ]
        return headers, rows
    raise ValueError(f"invalid mapping kind: {kind}")


__all__ = [
    "ADMIN_IMPORT_KINDS",
    "admin_settings_available",
    "apply_import_rows",
    "format_admin_mailing_lists_for_form",
    "get_admin_default_sender",
    "get_admin_listserv",
    "get_admin_mailing_lists",
    "parse_admin_mailing_lists",
    "parse_admin_mapping_file",
    "set_admin_default_sender",
    "set_admin_listserv",
    "set_admin_mailing_lists",
    "validate_import_rows",
    "export_mapping_rows",
]
