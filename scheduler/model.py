from typing import Any, Optional

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text as sql_text
from sqlalchemy.ext.declarative import DeclarativeMeta
from sqlalchemy.sql import func

db = SQLAlchemy()

# this is only needed to avoid confusing mypy
Model: DeclarativeMeta = db.Model


def get(entity: Any, ident: Any) -> Any:
    return db.session.get(entity, ident)


def execute(statement: Any, *args: Any, **kwargs: Any) -> Any:
    if isinstance(statement, str):
        statement = sql_text(statement)
    return db.session.execute(statement, *args, **kwargs)


# This file contains the reflection of the schema into sqlalchemy
# The reflection is not 1:1.
# - Deprecated tables and columns are left out
# - names have been changed to make things more regular
# - some views are included instead of the underlying tables


class Inst(Model):
    __tablename__ = "tlkpinst"

    id: str = db.Column("instcode", db.String(5), primary_key=True)
    label: str = db.Column("inst", db.String(20), nullable=False, default="")
    active: bool = db.Column("active", db.Boolean(), nullable=False, default=True)


class User(Model):
    __tablename__ = "tlkpresearcher"

    id: str = db.Column("researchercode", db.String(20), primary_key=True)
    label: str = db.Column("name", db.Text(), nullable=False, default="")
    active: bool = db.Column("active", db.Boolean(), nullable=False, default=True)
    modified: Any = db.Column(
        "chg_at",
        db.DateTime(),
        db.FetchedValue(for_update=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    addr: str = db.Column("email", db.Text(), nullable=False, default="")


class Group(Model):
    __tablename__ = "tlkpdept"

    id: str = db.Column("deptcode", db.String(10), primary_key=True)
    label: str = db.Column("dept_short", db.String(20), nullable=False, default="")
    description: str = db.Column(
        "dept", db.String(75, collation="en-US-x-icu"), nullable=False, default=""
    )
    active: bool = db.Column("iscurrent", db.Boolean(), nullable=False, default=True)

    inst: Optional[str] = db.Column(
        "inst", db.String(7), db.ForeignKey("tlkpinst.instcode"), nullable=True
    )
    addr: str = db.Column("email", db.Text(), nullable=False, default="")
    link: str = db.Column("link", db.Text(), nullable=False, default="")

    color: str = db.Column("color", db.String(7), nullable=False, default="#000000")

    has_membership: bool = db.Column(
        "ismain", db.Boolean(), nullable=False, default=True
    )
    is_joinable: bool = db.Column(
        "joinable", db.Boolean(), nullable=False, default=True
    )
    is_archivable: bool = db.Column(
        "archivable", db.Boolean(), nullable=False, default=True
    )
    is_scheduleable: bool = db.Column(
        "scheduleable", db.Boolean(), nullable=False, default=True
    )

    department: bool = db.Column(
        "department",
        db.Boolean(),
        db.FetchedValue(for_update=False),
    )


class Device(Model):
    __tablename__ = "tlkpscanner"

    id: str = db.Column("scannercode", db.String(5), primary_key=True)
    label: str = db.Column("scanner", db.String(25), nullable=False)
    description: str = db.Column(
        "descrip", db.Text(collation="en-US-x-icu"), nullable=False, default=""
    )
    active: bool = db.Column("active", db.Boolean(), nullable=False, default=True)

    addr: str = db.Column("mailinglist", db.Text(), nullable=False, default="")
    tech_addr: str = db.Column("techaddr", db.Text(), nullable=False, default="")
    med_addr: str = db.Column("medaddr", db.Text(), nullable=False, default="")
    train_addr: str = db.Column("trainaddr", db.Text(), nullable=False, default="")


class Template(Model):
    __tablename__ = "tbltemplates"

    id: str = db.Column("templatecode", db.String(1))
    device: str = db.Column(
        "scannercode", db.String(5), db.ForeignKey("tlkpscanner.scannercode")
    )
    label: str = db.Column("template", db.String(25), nullable=False, default="")
    description: str = db.Column(
        "comments", db.Text(collation="en-US-x-icu"), nullable=False, default=""
    )
    hidden: bool = db.Column("hidden", db.Boolean(), nullable=False, default=False)

    __table_args__ = (db.PrimaryKeyConstraint("templatecode", "scannercode"),)


class TemplateEntry(Model):
    __tablename__ = "tbltemplate"

    id: str = db.Column("templateid", db.Integer(), primary_key=True)
    device: str = db.Column(
        "scannercode",
        db.String(5),
        db.ForeignKey("tlkpscanner.scannercode"),
        nullable=False,
    )
    template: str = db.Column("templatecode", db.String(1), nullable=False)

    dow: int = db.Column("dow", db.Integer(), nullable=False)
    hour: int = db.Column("hour", db.Integer(), nullable=False)

    group: Optional[str] = db.Column(
        "deptcode", db.String(10), db.ForeignKey("tlkpdept.deptcode"), nullable=True
    )
    user: Optional[str] = db.Column(
        "researchercode",
        db.String(20),
        db.ForeignKey("tlkpresearcher.researchercode"),
        nullable=True,
    )
    inst: Optional[str] = db.Column(
        "instcode", db.String(5), db.ForeignKey("tlkpinst.instcode"), nullable=True
    )


class SupportKind(Model):
    """SupportKind represents an enum and should never be changed
    and never needs to be referenced directly"""

    __tablename__ = "supportkind"

    id: int = db.Column("supportkind", db.Integer(), primary_key=True)
    label: str = db.Column("label", db.Text(), nullable=False)


class SupportRequest(Model):
    __tablename__ = "support"

    schedid: int = db.Column("schedid", db.Integer(), db.ForeignKey("tblsched.schedid"))
    supportkind: int = db.Column(
        "supportkind", db.Integer(), db.ForeignKey("supportkind.supportkind")
    )
    modified_by: str = db.Column(
        "chg_by",
        db.String(20),
        db.ForeignKey("tlkpresearcher.researchercode"),
        nullable=False,
    )
    modified: Any = db.Column(
        "chg_at",
        db.DateTime(timezone=True),
        db.FetchedValue(for_update=False),
        nullable=False,
        onupdate=func.now(),
    )

    filed_by: str = db.Column(
        "filed_by",
        db.String(20),
        db.ForeignKey("tlkpresearcher.researchercode"),
        nullable=False,
    )
    fulfilled_by: str = db.Column(
        "fulfilled_by",
        db.String(20),
        db.ForeignKey("tlkpresearcher.researchercode"),
        nullable=True,
    )

    approved: Optional[bool] = db.Column("approved", db.Boolean(), nullable=True)
    note: str = db.Column("note", db.Text(), nullable=False, default="")

    kind: SupportKind = db.relationship(
        "SupportKind", lazy="joined", viewonly=True
    )  # always load the support with the request

    __table_args__ = (db.PrimaryKeyConstraint("schedid", "supportkind"),)


class ScheduleEntry(Model):
    __tablename__ = "tblsched"

    id: int = db.Column("schedid", db.Integer(), primary_key=True)
    modified: Optional[Any] = db.Column(
        "chg_at",
        db.DateTime(),
        db.FetchedValue(for_update=False),
        onupdate=func.now(),
    )
    modified_by: Optional[str] = db.Column("chg_by", db.String(30), nullable=False)

    device: str = db.Column(
        "scannercode", db.String(5), db.ForeignKey("tlkpdept.deptcode"), nullable=False
    )
    template: Optional[int] = db.Column(
        "templateid",
        db.Integer(),
        db.ForeignKey("tbltemplate.templateid"),
        nullable=False,
    )

    date: Any = db.Column("scheddate", db.Date(), nullable=False)
    dow: int = db.Column("scheddow", db.Integer(), nullable=False)
    hour: int = db.Column("schedhour", db.Integer(), nullable=False)

    group: Optional[str] = db.Column(
        "deptcode", db.String(10), db.ForeignKey("tlkpdept.deptcode"), nullable=False
    )
    user: Optional[str] = db.Column(
        "researchercode",
        db.String(20),
        db.ForeignKey("tlkpresearcher.researchercode"),
        nullable=False,
    )
    orig_group: Optional[str] = db.Column(
        "orig_deptcode",
        db.String(10),
        db.ForeignKey("tlkpdept.deptcode"),
        nullable=False,
    )
    orig_inst: Optional[str] = db.Column(
        "orig_instcode",
        db.String(20),
        db.ForeignKey("tlkpinst.instcode"),
        nullable=False,
    )

    # Note we're marking this as a fetched value even though it is not
    # to avoid it being included in generated insert/update statements
    used: Optional[bool] = db.Column(
        "time_used",
        db.Boolean(),
        server_default=db.FetchedValue(),
        server_onupdate=db.FetchedValue(),
        nullable=False,
    )

    requests = db.relationship(
        "SupportRequest",
        lazy="joined",
        uselist=True,
        primaryjoin="ScheduleEntry.id==SupportRequest.schedid",
    )


class Membership(Model):
    """Membership is a view over user membership sufficient for all membership queries.

    Some of the underlying relations are also exposed to sqlalchemy but only for CRUD operations."""

    __tablename__ = "membership"

    group: str = db.Column("group", db.String(10))
    user: str = db.Column("user", db.String(20))

    pi: bool = db.Column("pi", db.Boolean(), nullable=False)
    approved: bool = db.Column("approved", db.Boolean(), nullable=False)
    email_status: str = db.Column("email_status", db.String(10), nullable=False)
    group_active: bool = db.Column("group_active", db.Boolean(), nullable=False)
    user_active: bool = db.Column("user_active", db.Boolean(), nullable=False)

    __table_args__ = (db.PrimaryKeyConstraint("group", "user"),)


class GroupMember(Model):
    """GroupMember is only meant for insert/update/delete. Use Membership for queries."""

    __tablename__ = "groupmembers"

    group: str = db.Column(
        "deptcode", db.String(10), db.ForeignKey("tlkpdept.deptcode")
    )
    user: str = db.Column(
        "researchercode", db.String(20), db.ForeignKey("tlkpresearcher.researchercode")
    )

    approved: Any = db.Column("approved", db.DateTime(timezone=True), nullable=True)
    email_status: str = db.Column(
        "email_status", db.String(10), nullable=False, default="none"
    )

    __table_args__ = (db.PrimaryKeyConstraint("deptcode", "researchercode"),)


class PrimaryGroupMember(Model):
    """PrimaryGroupMember is only for insert and delete. Use Membership for queries."""

    __tablename__ = "primarygroupmember"

    group: str = db.Column(
        "deptcode", db.String(10), db.ForeignKey("tlkpdept.deptcode")
    )
    user: str = db.Column(
        "researchercode", db.String(20), db.ForeignKey("tlkpresearcher.researchercode")
    )

    __table_args__ = (db.PrimaryKeyConstraint("deptcode", "researchercode"),)


class Technologist(Model):
    __tablename__ = "technologist"
    user: str = db.Column(
        "researchercode",
        db.String(20),
        db.ForeignKey("tlkpresearcher.researchercode"),
        primary_key=True,
    )
    applied_on: Any = db.Column(
        "applied_on", db.DateTime(timezone=True), nullable=False, default=func.now()
    )
    approved_on: Any = db.Column(
        "approved_on", db.DateTime(timezone=True), nullable=True
    )
    email_status: str = db.Column(
        "email_status", db.String(10), nullable=False, default="none"
    )


class DeviceGroup(Model):
    __tablename__ = "devicegroup"

    device: str = db.Column(
        "scannercode", db.String(5), db.ForeignKey("tlkpscanner.scannercode")
    )
    group: str = db.Column(
        "deptcode", db.String(10), db.ForeignKey("tlkpdept.deptcode")
    )

    __table_args__ = (db.PrimaryKeyConstraint("scannercode", "deptcode"),)


class UserDevice(Model):
    __tablename__ = "userdevice"

    user: str = db.Column(
        "researchercode", db.String(20), db.ForeignKey("tlkpresearcher.researchercode")
    )
    device: str = db.Column(
        "scannercode", db.String(5), db.ForeignKey("tlkpscanner.scannercode")
    )

    templates: bool = db.Column("templates", db.Boolean(), nullable=False)
    slot: bool = db.Column("slot", db.Boolean(), nullable=False)
    tech: bool = db.Column("tech", db.Boolean(), nullable=False)
    medical: bool = db.Column("medical", db.Boolean(), nullable=False)
    training: bool = db.Column("training", db.Boolean(), nullable=False)

    __table_args__ = (db.PrimaryKeyConstraint("researchercode", "scannercode"),)


class RbacAuditLog(Model):
    __tablename__ = "rbac_audit_log"

    id: int = db.Column("auditid", db.BigInteger(), primary_key=True)
    occurred_at: Any = db.Column(
        "occurred_at",
        db.DateTime(timezone=True),
        db.FetchedValue(for_update=False),
        nullable=False,
        server_default=func.now(),
    )

    action: str = db.Column("action", db.Text(), nullable=False)
    actor: str = db.Column("actor", db.String(20), nullable=False)
    ip: Optional[str] = db.Column("ip_addr", db.String(64), nullable=True)
    where_path: str = db.Column("where_path", db.Text(), nullable=False)
    how: str = db.Column("how", db.String(32), nullable=False)
    what: str = db.Column("what", db.Text(), nullable=False)

    group: Optional[str] = db.Column("deptcode", db.Text(), nullable=True)
    device: Optional[str] = db.Column("scannercode", db.Text(), nullable=True)
    user: Optional[str] = db.Column("researchercode", db.Text(), nullable=True)
    requester: Optional[str] = db.Column("requestercode", db.Text(), nullable=True)


class EmailAuditLog(Model):
    __tablename__ = "email_audit_log"

    id: int = db.Column("auditid", db.BigInteger(), primary_key=True)
    occurred_at: Any = db.Column(
        "occurred_at",
        db.DateTime(timezone=True),
        db.FetchedValue(for_update=False),
        nullable=False,
        server_default=func.now(),
    )

    action: str = db.Column("action", db.Text(), nullable=False)
    actor: str = db.Column("actor", db.String(20), nullable=False)
    ip: Optional[str] = db.Column("ip_addr", db.String(64), nullable=True)
    where_path: str = db.Column("where_path", db.Text(), nullable=False)
    how: str = db.Column("how", db.String(32), nullable=False)
    status: str = db.Column("status", db.String(16), nullable=False)
    recipient: str = db.Column("recipient", db.Text(), nullable=False)
    subject: str = db.Column("subject", db.Text(), nullable=False)
    details: str = db.Column("details", db.Text(), nullable=False)
    issue_key: Optional[str] = db.Column("issue_key", db.Text(), nullable=True)
    issue_state: str = db.Column("issue_state", db.String(16), nullable=False)

    group: Optional[str] = db.Column("deptcode", db.Text(), nullable=True)
    device: Optional[str] = db.Column("scannercode", db.Text(), nullable=True)
    user: Optional[str] = db.Column("researchercode", db.Text(), nullable=True)
    requester: Optional[str] = db.Column("requestercode", db.Text(), nullable=True)


class NotificationIncident(Model):
    __tablename__ = "notification_incident"

    issue_key: str = db.Column("issue_key", db.Text(), primary_key=True)
    issue_type: str = db.Column("issue_type", db.Text(), nullable=False)
    category: str = db.Column("category", db.Text(), nullable=False)
    severity: str = db.Column("severity", db.String(16), nullable=False)
    title: str = db.Column("title", db.Text(), nullable=False)
    detail: str = db.Column("detail", db.Text(), nullable=False)
    href: Optional[str] = db.Column("href", db.Text(), nullable=True)
    link_label: str = db.Column("link_label", db.Text(), nullable=False, default="")

    active: bool = db.Column("active", db.Boolean(), nullable=False, default=True)
    state: str = db.Column("state", db.String(16), nullable=False, default="open")
    state_note: str = db.Column("state_note", db.Text(), nullable=False, default="")
    state_changed_by: Optional[str] = db.Column(
        "state_changed_by", db.String(20), nullable=True
    )
    state_changed_at: Any = db.Column(
        "state_changed_at",
        db.DateTime(timezone=True),
        db.FetchedValue(for_update=False),
        nullable=False,
        server_default=func.now(),
    )
    ignored_until: Optional[Any] = db.Column(
        "ignored_until", db.DateTime(timezone=True), nullable=True
    )

    first_seen_at: Any = db.Column(
        "first_seen_at",
        db.DateTime(timezone=True),
        db.FetchedValue(for_update=False),
        nullable=False,
        server_default=func.now(),
    )
    last_seen_at: Any = db.Column(
        "last_seen_at",
        db.DateTime(timezone=True),
        db.FetchedValue(for_update=False),
        nullable=False,
        server_default=func.now(),
    )
    last_detected_at: Optional[Any] = db.Column(
        "last_detected_at", db.DateTime(timezone=True), nullable=True
    )
    last_resolved_at: Optional[Any] = db.Column(
        "last_resolved_at", db.DateTime(timezone=True), nullable=True
    )
    occurrence_count: int = db.Column(
        "occurrence_count", db.Integer(), nullable=False, default=1
    )
    fingerprint: str = db.Column("fingerprint", db.Text(), nullable=False, default="")


class SchedLogEntry(Model):
    """SchedLogEntry is a view that should always be used with a specified id"""

    __tablename__ = "app_log_json"

    id: int = db.Column("schedid", db.Integer(), primary_key=True)
    entries: Any = db.Column("entries", db.JSON(), nullable=True)


class OAuthState(Model):
    """Temporary OAuth state storage for server-side login flow."""

    __tablename__ = "oauth_state"

    state: str = db.Column("state", db.String(128), primary_key=True)
    nonce: str = db.Column("nonce", db.String(128), nullable=False)
    redirect_next: Optional[str] = db.Column("redirect_next", db.Text(), nullable=True)
    code_verifier: Optional[str] = db.Column(
        "code_verifier", db.String(128), nullable=True
    )
    created_at: Any = db.Column(
        "created_at",
        db.DateTime(timezone=True),
        db.FetchedValue(for_update=False),
        nullable=False,
        server_default=func.now(),
    )


class AppSetting(Model):
    __tablename__ = "app_settings"

    key: str = db.Column("key", db.String(128), primary_key=True)
    value: str = db.Column("value", db.Text(), nullable=False, default="")
    updated_at: Any = db.Column(
        "updated_at",
        db.DateTime(timezone=True),
        db.FetchedValue(for_update=False),
        nullable=False,
        server_default=func.now(),
    )
    updated_by: Optional[str] = db.Column("updated_by", db.String(20), nullable=True)
