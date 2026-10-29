"""RBAC CSV import/export helpers."""

from __future__ import annotations

import csv
import io
from typing import Dict, List, Sequence, Tuple

from sqlalchemy import and_, delete, select
from sqlalchemy.sql import func
from werkzeug.datastructures import FileStorage

from scheduler import model

from ._admin_config_settings import _normalize_text

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


def _read_csv_text(
    raw_text: str, required_fields: Sequence[str]
) -> List[Dict[str, str]]:
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
    return _read_csv_text(raw_text, required_fields)


def parse_admin_mapping_file(kind: str, file_obj: FileStorage) -> List[Dict[str, str]]:
    required = CSV_HEADERS.get(kind)
    if required is None:
        raise ValueError(f"invalid mapping kind: {kind}")
    return _read_csv_rows(file_obj, required)


def parse_admin_mapping_text(kind: str, raw_text: str) -> List[Dict[str, str]]:
    required = CSV_HEADERS.get(kind)
    if required is None:
        raise ValueError(f"invalid mapping kind: {kind}")
    return _read_csv_text(str(raw_text or ""), required)


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
        users = set(
            model.db.session.scalars(
                select(model.User.id).where(model.User.id.in_(list(user_ids)))
            ).all()
        )
        missing_users = sorted(user_ids - set(users))
        if missing_users:
            errors.append("unknown users: " + ", ".join(missing_users))
    if dept_ids:
        depts = set(
            model.db.session.scalars(
                select(model.Group.id).where(model.Group.id.in_(list(dept_ids)))
            ).all()
        )
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
        devices = set(
            model.db.session.scalars(
                select(model.Device.id).where(model.Device.id.in_(list(dev_ids)))
            ).all()
        )
        missing_devs = sorted(dev_ids - set(devices))
        if missing_devs:
            errors.append("unknown devices: " + ", ".join(missing_devs))
    if dept_ids:
        depts = set(
            model.db.session.scalars(
                select(model.Group.id).where(model.Group.id.in_(list(dept_ids)))
            ).all()
        )
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
        users = set(
            model.db.session.scalars(
                select(model.User.id).where(model.User.id.in_(list(user_ids)))
            ).all()
        )
        missing_users = sorted(user_ids - set(users))
        if missing_users:
            errors.append("unknown users: " + ", ".join(missing_users))
    if dev_ids:
        devices = set(
            model.db.session.scalars(
                select(model.Device.id).where(model.Device.id.in_(list(dev_ids)))
            ).all()
        )
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
    model.db.session.execute(delete(model.PrimaryGroupMember))
    model.db.session.execute(delete(model.GroupMember))
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
    model.db.session.execute(delete(model.DeviceGroup))
    for row in rows:
        model.db.session.add(model.DeviceGroup(device=row["dev"], group=row["dept"]))
    return len(rows)


def apply_devperm_rows(rows: List[Dict[str, str]]) -> int:
    model.db.session.execute(delete(model.UserDevice))
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
        rows = [
            (str(usr), str(dept), "pi" if pi == usr else "")
            for usr, dept, pi in model.db.session.execute(
                select(
                    model.GroupMember.user,
                    model.GroupMember.group,
                    model.PrimaryGroupMember.user,
                )
                .outerjoin(
                    model.PrimaryGroupMember,
                    and_(
                        model.PrimaryGroupMember.user == model.GroupMember.user,
                        model.PrimaryGroupMember.group == model.GroupMember.group,
                    ),
                )
                .order_by(model.GroupMember.group, model.GroupMember.user)
            ).all()
        ]
        return headers, rows
    if kind == DEV_DEPT_IMPORT_KIND:
        headers = ("dev", "dept")
        rows = [
            (str(device_id), str(group_id))
            for device_id, group_id in model.db.session.execute(
                select(model.DeviceGroup.device, model.DeviceGroup.group).order_by(
                    model.DeviceGroup.group, model.DeviceGroup.device
                )
            ).all()
        ]
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
            for usr, device, templates, slot, tech, medical, training in model.db.session.execute(
                select(
                    model.UserDevice.user,
                    model.UserDevice.device,
                    model.UserDevice.templates,
                    model.UserDevice.slot,
                    model.UserDevice.tech,
                    model.UserDevice.medical,
                    model.UserDevice.training,
                ).order_by(model.UserDevice.user, model.UserDevice.device)
            ).all()
        ]
        return headers, rows
    raise ValueError(f"invalid mapping kind: {kind}")


def format_admin_mapping_rows_for_form(kind: str) -> str:
    headers, rows = export_mapping_rows(kind)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return out.getvalue()


__all__ = [
    "ADMIN_IMPORT_KINDS",
    "DEVPERM_IMPORT_KIND",
    "DEV_DEPT_IMPORT_KIND",
    "USER_DEPT_IMPORT_KIND",
    "apply_import_rows",
    "export_mapping_rows",
    "format_admin_mapping_rows_for_form",
    "parse_admin_mapping_file",
    "parse_admin_mapping_text",
    "validate_import_rows",
]
