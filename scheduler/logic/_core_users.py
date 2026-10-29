from __future__ import annotations

import datetime
import hashlib
import re
from typing import Any, List, Optional

from flask import g
from flask_wtf import FlaskForm
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.functions import func
from wtforms import fields, validators

from scheduler import model

from ._core_shared import _request_cache_dict
from .rbac_audit_support import EMAIL_STATUS_NONE, EMAIL_STATUS_VALUES, constraint_of

_MAX_USER_ID_LENGTH = 20
_USER_ID_PATTERN = re.compile(r"[^a-z0-9_-]+")


def normalize_name(name: str) -> str:
    if "," in name:
        last, first = [s.strip() for s in name.split(",", 1)]
        return f"{first} {last}"
    return name.strip()


def record_tech_join_request(user: model.User) -> model.Technologist:
    r = model.db.session.get(model.Technologist, user.id)
    if r is None:
        r = model.Technologist(
            user=user.id,
            applied_on=func.now(),
            approved_on=None,
            email_status=EMAIL_STATUS_NONE,
        )
    else:
        r.applied_on = func.now()
        r.approved_on = None
        if (r.email_status or "").strip() not in EMAIL_STATUS_VALUES:
            r.email_status = EMAIL_STATUS_NONE
    model.db.session.add(r)
    return r


class JoinForm(FlaskForm):
    group = fields.StringField(
        label="department",
        validators=[validators.InputRequired()],
        render_kw={"list": "departments", "autocomplete": "off", "spellcheck": "false"},
    )

    def __init__(self, departments, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.departments = departments

    def set_errors_from_exception(self, ex: IntegrityError) -> None:
        prefix, c = constraint_of(ex)
        if prefix == "groupmembers" and c == "deptcode_fkey":
            self.group.errors.append("invalid department selected")


def show_tech_join_form(user: model.User) -> bool:
    if not isinstance(user, model.User):
        return False
    cache = _request_cache_dict("_cached_show_tech_join_form")
    if cache is not None:
        cached = cache.get(user.id)
        if cached is not None:
            return cached

    membership_statement = (
        select(model.Membership.user)
        .where(model.Membership.group == "DEV")
        .where(model.Membership.user == user.id)
        .where(model.Membership.approved.is_(True))
        .where(model.Membership.user_active.is_(True))
        .limit(1)
    )
    value = (
        model.db.session.scalar(membership_statement) is not None
        and model.db.session.get(model.Technologist, user.id) is None
    )
    if cache is not None:
        cache[user.id] = value
    return value


def record_join_form(form: JoinForm, user: model.User, group: str) -> bool:
    r = model.GroupMember(user=user.id, group=group)
    model.db.session.add(r)
    try:
        model.db.session.commit()
    except IntegrityError as ex:
        form.set_errors_from_exception(ex)
        model.db.session.rollback()
        return False
    return True


def add_admin(user: model.User):
    r = model.GroupMember(user=user.id, group="admin", approved=func.now())
    model.db.session.add(r)


def get_join_request(
    user: model.User, group: model.Group
) -> Optional[model.GroupMember]:
    return model.db.session.get(model.GroupMember, (group.id, user.id))


def get_pending_tech_join_request(user: model.User) -> Optional[model.Technologist]:
    req = model.db.session.get(model.Technologist, user.id)
    if req is None:
        return None
    if req.approved_on is not None:
        return None
    return req


def handle_join_request(approved: bool, req: model.GroupMember) -> None:
    if not approved:
        model.db.session.delete(req)
        return

    req.approved = func.now()
    model.db.session.add(req)


def handle_tech_join_request(approved: bool, req: model.Technologist) -> None:
    if not approved:
        model.db.session.delete(req)
        return

    req.approved_on = func.now()
    model.db.session.add(req)


def get_user(user: str) -> Optional[model.User]:
    return model.db.session.get(model.User, user)


def _user_id_from_value(user: Any) -> str:
    return str(getattr(user, "id", "") or "").strip()


def _user_is_active(user: Any) -> bool:
    return bool(getattr(user, "active", False))


def _normalize_user_id(value: str) -> str:
    token = _USER_ID_PATTERN.sub("-", (value or "").strip().lower()).strip("-")
    return token[:_MAX_USER_ID_LENGTH]


def scoped_user_id_from_identifier(identifier: str) -> str:
    normalized_identifier = (identifier or "").strip().lower()
    local_part = normalized_identifier.split("@", 1)[0]
    local_token = _normalize_user_id(local_part) or "user"
    digest = hashlib.sha256(normalized_identifier.encode("utf-8")).hexdigest()[:6]
    max_local_len = _MAX_USER_ID_LENGTH - len(digest) - 1
    if max_local_len <= 0:
        return digest[:_MAX_USER_ID_LENGTH]
    return f"{local_token[:max_local_len]}-{digest}"


def _sync_user_profile(
    user: model.User, normalized_mail: str, normalized_name: str
) -> model.User:
    changed = False
    if normalized_mail and user.addr != normalized_mail:
        user.addr = normalized_mail
        changed = True
    if normalized_name and user.label != normalized_name:
        user.label = normalized_name
        changed = True
    if changed:
        model.db.session.add(user)
    return user


def _try_rekey_user_primary_id(old_id: str, new_id: str) -> bool:
    if old_id == new_id:
        return True
    try:
        with model.db.session.begin_nested():
            record = model.db.session.get(model.User, old_id)
            if record is None or model.db.session.get(model.User, new_id) is not None:
                return False
            record.id = new_id
            model.db.session.flush()
        return True
    except IntegrityError:
        return False


def _rekey_user_foreign_keys(old_id: str, new_id: str) -> None:
    if old_id == new_id:
        return

    memberships = model.db.session.scalars(
        select(model.GroupMember).where(model.GroupMember.user == old_id)
    ).all()
    for row in memberships:
        existing = model.db.session.get(model.GroupMember, (row.group, new_id))
        if existing is not None:
            if existing.approved is None and row.approved is not None:
                existing.approved = row.approved
                model.db.session.add(existing)
            model.db.session.delete(row)
            continue
        row.user = new_id
        model.db.session.add(row)

    primary_memberships = model.db.session.scalars(
        select(model.PrimaryGroupMember).where(model.PrimaryGroupMember.user == old_id)
    ).all()
    for row in primary_memberships:
        existing = model.db.session.get(model.PrimaryGroupMember, (row.group, new_id))
        if existing is not None:
            model.db.session.delete(row)
            continue
        row.user = new_id
        model.db.session.add(row)

    technologist = model.db.session.get(model.Technologist, old_id)
    if technologist is not None:
        if model.db.session.get(model.Technologist, new_id) is not None:
            model.db.session.delete(technologist)
        else:
            technologist.user = new_id
            model.db.session.add(technologist)

    permissions = model.db.session.scalars(
        select(model.UserDevice).where(model.UserDevice.user == old_id)
    ).all()
    for row in permissions:
        existing = model.db.session.get(model.UserDevice, (new_id, row.device))
        if existing is not None:
            existing.templates = bool(existing.templates or row.templates)
            existing.slot = bool(existing.slot or row.slot)
            existing.tech = bool(existing.tech or row.tech)
            existing.medical = bool(existing.medical or row.medical)
            existing.training = bool(existing.training or row.training)
            model.db.session.add(existing)
            model.db.session.delete(row)
            continue
        row.user = new_id
        model.db.session.add(row)

    model.db.session.execute(
        update(model.ScheduleEntry)
        .where(model.ScheduleEntry.user == old_id)
        .values(user=new_id)
    )
    model.db.session.execute(
        update(model.TemplateEntry)
        .where(model.TemplateEntry.user == old_id)
        .values(user=new_id)
    )
    model.db.session.execute(
        update(model.SupportRequest)
        .where(model.SupportRequest.filed_by == old_id)
        .values(filed_by=new_id)
    )
    model.db.session.execute(
        update(model.SupportRequest)
        .where(model.SupportRequest.fulfilled_by == old_id)
        .values(fulfilled_by=new_id)
    )
    model.db.session.execute(
        update(model.SupportRequest)
        .where(model.SupportRequest.modified_by == old_id)
        .values(modified_by=new_id)
    )


def _migrate_user_identity(
    old_user: model.User, new_id: str, normalized_mail: str, normalized_name: str
) -> model.User:
    old_id = old_user.id
    if old_id == new_id:
        return _sync_user_profile(old_user, normalized_mail, normalized_name)

    if _try_rekey_user_primary_id(old_id, new_id):
        # Some test/local DB backends may not enforce ON UPDATE CASCADE consistently.
        # Ensure dependent rows are rewritten even when primary-key rekey succeeds.
        _rekey_user_foreign_keys(old_id, new_id)
        migrated = model.db.session.get(model.User, new_id)
        if migrated is None:
            raise RuntimeError(f"Failed to migrate user id from {old_id} to {new_id}")
        return _sync_user_profile(migrated, normalized_mail, normalized_name)

    target = model.db.session.get(model.User, new_id)
    if target is None:
        model.db.session.execute(
            text(
                """
            insert into tlkpresearcher(researchercode, name, email, active, chg_at)
            values (:user, :name, :mail, :active, :chg_at)
            on conflict (researchercode) do nothing
            """
            ),
            {
                "user": new_id,
                "name": normalized_name or old_user.label or new_id,
                "mail": normalized_mail or old_user.addr or "",
                "active": bool(old_user.active),
                "chg_at": datetime.datetime.utcnow(),
            },
        )
        target = model.db.session.get(model.User, new_id)
        if target is None:
            raise RuntimeError(f"Failed to create migration target user {new_id}")

    _rekey_user_foreign_keys(old_id, new_id)

    stale = model.db.session.get(model.User, old_id)
    if stale is not None and stale.id != new_id:
        try:
            with model.db.session.begin_nested():
                model.db.session.delete(stale)
                model.db.session.flush()
        except IntegrityError:
            stale.addr = ""
            model.db.session.add(stale)

    target = model.db.session.get(model.User, new_id)
    if target is None:
        raise RuntimeError(f"Failed to load migrated user id {new_id}")
    return _sync_user_profile(target, normalized_mail, normalized_name)


def upsert_user(
    user: str, mail: str, name: str, *, migrate_to_requested_id: bool = False
) -> model.User:
    normalized_mail = (mail or "").strip().lower()
    normalized_name = (name or "").strip()
    requested_id = _normalize_user_id(user)
    if not requested_id:
        requested_id = scoped_user_id_from_identifier(normalized_mail)

    # Email is authoritative when present. Reuse any existing record for it.
    if normalized_mail:
        existing_by_mail = model.db.session.scalars(
            select(model.User).where(func.lower(model.User.addr) == normalized_mail)
        ).first()
        if existing_by_mail is not None:
            if migrate_to_requested_id and existing_by_mail.id != requested_id:
                return _migrate_user_identity(
                    existing_by_mail, requested_id, normalized_mail, normalized_name
                )
            return _sync_user_profile(
                existing_by_mail, normalized_mail, normalized_name
            )

    resolved_id = requested_id
    existing_by_id = model.db.session.get(model.User, resolved_id)
    if (
        existing_by_id is not None
        and normalized_mail
        and existing_by_id.addr
        and existing_by_id.addr.strip().lower() != normalized_mail
    ):
        # Existing id belongs to another email; derive a stable scoped id.
        resolved_id = scoped_user_id_from_identifier(normalized_mail)
        existing_by_id = model.db.session.get(model.User, resolved_id)

    if existing_by_id is None:
        model.db.session.execute(
            text(
                """
            insert into tlkpresearcher(researchercode, name, email, active, chg_at)
            values (:user, :name, :mail, :active, :chg_at)
            on conflict (researchercode) do nothing
            """
            ),
            {
                "user": resolved_id,
                "name": normalized_name or resolved_id,
                "mail": normalized_mail,
                "active": True,
                "chg_at": datetime.datetime.utcnow(),
            },
        )
        existing_by_id = model.db.session.get(model.User, resolved_id)

    if existing_by_id is None:
        raise RuntimeError(f"Failed to upsert user record for {resolved_id}")

    return _sync_user_profile(existing_by_id, normalized_mail, normalized_name)


def is_admin(user: Any) -> bool:
    if not _user_is_active(user):
        return False
    return "admin" in get_memberships(user)


def get_memberships(user: Any) -> List[str]:
    user_id = _user_id_from_value(user)
    if user_id == "":
        return []
    if not _user_is_active(user):
        return []

    has_request_context = True
    try:
        request_cache = getattr(g, "_cached_memberships", None)
        request_cache_user_id = str(
            getattr(g, "_cached_memberships_user_id", "") or ""
        ).strip()
        if request_cache is not None and request_cache_user_id == user_id:
            return list(request_cache)
    except RuntimeError:
        has_request_context = False

    cache = _request_cache_dict("_cached_memberships_by_user")
    if cache is not None:
        cached = cache.get(user_id)
        if cached is not None:
            return list(cached)

    membership_statement = (
        select(model.Membership)
        .where(model.Membership.user == user_id)
        .where(model.Membership.user_active)
        .where(model.Membership.group_active)
        .where(model.Membership.approved)
        .order_by(model.Membership.group)
    )
    ms = model.db.session.scalars(membership_statement).all()
    memberships = [m.group for m in ms]

    # Keep the request-scoped cache populated so app-level helpers and downstream
    # callers can reuse the same memberships list.
    if has_request_context:
        setattr(g, "_cached_memberships", memberships)
        setattr(g, "_cached_memberships_user_id", user_id)
    if cache is not None:
        cache[user_id] = memberships

    return memberships


__all__ = [
    "JoinForm",
    "add_admin",
    "get_join_request",
    "get_memberships",
    "get_pending_tech_join_request",
    "get_user",
    "handle_join_request",
    "handle_tech_join_request",
    "is_admin",
    "normalize_name",
    "record_join_form",
    "record_tech_join_request",
    "scoped_user_id_from_identifier",
    "show_tech_join_form",
    "upsert_user",
]
