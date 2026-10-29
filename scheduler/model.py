from typing import Any, Optional

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text as sql_text
from sqlalchemy.orm import DeclarativeMeta, Mapped
from sqlalchemy.sql import func

db = SQLAlchemy()

# Explicit Mapped[...] annotations satisfy SQLAlchemy 2.x declarative checks
# while keeping the existing db.Column/db.relationship style compatible with 1.4.
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

    id: Mapped[str] = db.Column("instcode", db.String(5), primary_key=True)
    label: Mapped[str] = db.Column("inst", db.String(20), nullable=False, default="")
    active: Mapped[bool] = db.Column(
        "active", db.Boolean(), nullable=False, default=True
    )


class User(Model):
    __tablename__ = "tlkpresearcher"

    id: Mapped[str] = db.Column("researchercode", db.String(20), primary_key=True)
    label: Mapped[str] = db.Column("name", db.Text(), nullable=False, default="")
    active: Mapped[bool] = db.Column(
        "active", db.Boolean(), nullable=False, default=True
    )
    modified: Mapped[Any] = db.Column(
        "chg_at",
        db.DateTime(),
        db.FetchedValue(for_update=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    addr: Mapped[str] = db.Column("email", db.Text(), nullable=False, default="")


class Group(Model):
    __tablename__ = "tlkpdept"

    id: Mapped[str] = db.Column("deptcode", db.String(10), primary_key=True)
    label: Mapped[str] = db.Column(
        "dept_short", db.String(20), nullable=False, default=""
    )
    description: Mapped[str] = db.Column(
        "dept", db.String(75, collation="en-US-x-icu"), nullable=False, default=""
    )
    active: Mapped[bool] = db.Column(
        "iscurrent", db.Boolean(), nullable=False, default=True
    )

    inst: Mapped[Optional[str]] = db.Column(
        "inst", db.String(7), db.ForeignKey("tlkpinst.instcode"), nullable=True
    )
    addr: Mapped[str] = db.Column("email", db.Text(), nullable=False, default="")
    link: Mapped[str] = db.Column("link", db.Text(), nullable=False, default="")

    color: Mapped[str] = db.Column(
        "color", db.String(7), nullable=False, default="#000000"
    )

    has_membership: Mapped[bool] = db.Column(
        "ismain", db.Boolean(), nullable=False, default=True
    )
    is_joinable: Mapped[bool] = db.Column(
        "joinable", db.Boolean(), nullable=False, default=True
    )
    is_archivable: Mapped[bool] = db.Column(
        "archivable", db.Boolean(), nullable=False, default=True
    )
    is_scheduleable: Mapped[bool] = db.Column(
        "scheduleable", db.Boolean(), nullable=False, default=True
    )

    department: Mapped[bool] = db.Column(
        "department",
        db.Boolean(),
        db.FetchedValue(for_update=False),
    )


class Device(Model):
    __tablename__ = "tlkpscanner"

    id: Mapped[str] = db.Column("scannercode", db.String(5), primary_key=True)
    label: Mapped[str] = db.Column("scanner", db.String(25), nullable=False)
    description: Mapped[str] = db.Column(
        "descrip", db.Text(collation="en-US-x-icu"), nullable=False, default=""
    )
    active: Mapped[bool] = db.Column(
        "active", db.Boolean(), nullable=False, default=True
    )

    addr: Mapped[str] = db.Column("mailinglist", db.Text(), nullable=False, default="")
    tech_addr: Mapped[str] = db.Column(
        "techaddr", db.Text(), nullable=False, default=""
    )
    med_addr: Mapped[str] = db.Column("medaddr", db.Text(), nullable=False, default="")
    train_addr: Mapped[str] = db.Column(
        "trainaddr", db.Text(), nullable=False, default=""
    )


class Template(Model):
    __tablename__ = "tbltemplates"

    id: Mapped[str] = db.Column("templatecode", db.String(1))
    device: Mapped[str] = db.Column(
        "scannercode", db.String(5), db.ForeignKey("tlkpscanner.scannercode")
    )
    label: Mapped[str] = db.Column(
        "template", db.String(25), nullable=False, default=""
    )
    description: Mapped[str] = db.Column(
        "comments", db.Text(collation="en-US-x-icu"), nullable=False, default=""
    )
    hidden: Mapped[bool] = db.Column(
        "hidden", db.Boolean(), nullable=False, default=False
    )

    __table_args__ = (db.PrimaryKeyConstraint("templatecode", "scannercode"),)


class TemplateEntry(Model):
    __tablename__ = "tbltemplate"

    id: Mapped[int] = db.Column("templateid", db.Integer(), primary_key=True)
    device: Mapped[str] = db.Column(
        "scannercode",
        db.String(5),
        db.ForeignKey("tlkpscanner.scannercode"),
        nullable=False,
    )
    template: Mapped[str] = db.Column("templatecode", db.String(1), nullable=False)

    dow: Mapped[int] = db.Column("dow", db.Integer(), nullable=False)
    hour: Mapped[int] = db.Column("hour", db.Integer(), nullable=False)

    group: Mapped[Optional[str]] = db.Column(
        "deptcode", db.String(10), db.ForeignKey("tlkpdept.deptcode"), nullable=True
    )
    user: Mapped[Optional[str]] = db.Column(
        "researchercode",
        db.String(20),
        db.ForeignKey("tlkpresearcher.researchercode"),
        nullable=True,
    )
    inst: Mapped[Optional[str]] = db.Column(
        "instcode", db.String(5), db.ForeignKey("tlkpinst.instcode"), nullable=True
    )


class SupportKind(Model):
    """SupportKind represents an enum and should never be changed
    and never needs to be referenced directly"""

    __tablename__ = "supportkind"

    id: Mapped[int] = db.Column("supportkind", db.Integer(), primary_key=True)
    label: Mapped[str] = db.Column("label", db.Text(), nullable=False)


class SupportRequest(Model):
    __tablename__ = "support"

    schedid: Mapped[int] = db.Column(
        "schedid", db.Integer(), db.ForeignKey("tblsched.schedid")
    )
    supportkind: Mapped[int] = db.Column(
        "supportkind", db.Integer(), db.ForeignKey("supportkind.supportkind")
    )
    modified_by: Mapped[str] = db.Column(
        "chg_by",
        db.String(20),
        db.ForeignKey("tlkpresearcher.researchercode"),
        nullable=False,
    )
    modified: Mapped[Any] = db.Column(
        "chg_at",
        db.DateTime(timezone=True),
        db.FetchedValue(for_update=False),
        nullable=False,
        onupdate=func.now(),
    )

    filed_by: Mapped[str] = db.Column(
        "filed_by",
        db.String(20),
        db.ForeignKey("tlkpresearcher.researchercode"),
        nullable=False,
    )
    fulfilled_by: Mapped[Optional[str]] = db.Column(
        "fulfilled_by",
        db.String(20),
        db.ForeignKey("tlkpresearcher.researchercode"),
        nullable=True,
    )

    approved: Mapped[Optional[bool]] = db.Column(
        "approved", db.Boolean(), nullable=True
    )
    note: Mapped[str] = db.Column("note", db.Text(), nullable=False, default="")

    kind: Mapped[SupportKind] = db.relationship(
        "SupportKind", lazy="joined", viewonly=True
    )  # always load the support with the request

    __table_args__ = (db.PrimaryKeyConstraint("schedid", "supportkind"),)


class ScheduleEntry(Model):
    __tablename__ = "tblsched"

    id: Mapped[int] = db.Column("schedid", db.Integer(), primary_key=True)
    modified: Mapped[Optional[Any]] = db.Column(
        "chg_at",
        db.DateTime(),
        db.FetchedValue(for_update=False),
        onupdate=func.now(),
    )
    modified_by: Mapped[str] = db.Column("chg_by", db.String(30), nullable=False)

    device: Mapped[str] = db.Column(
        "scannercode", db.String(5), db.ForeignKey("tlkpdept.deptcode"), nullable=False
    )
    template: Mapped[int] = db.Column(
        "templateid",
        db.Integer(),
        db.ForeignKey("tbltemplate.templateid"),
        nullable=False,
    )

    date: Mapped[Any] = db.Column("scheddate", db.Date(), nullable=False)
    dow: Mapped[int] = db.Column("scheddow", db.Integer(), nullable=False)
    hour: Mapped[int] = db.Column("schedhour", db.Integer(), nullable=False)

    group: Mapped[str] = db.Column(
        "deptcode", db.String(10), db.ForeignKey("tlkpdept.deptcode"), nullable=False
    )
    user: Mapped[str] = db.Column(
        "researchercode",
        db.String(20),
        db.ForeignKey("tlkpresearcher.researchercode"),
        nullable=False,
    )
    orig_group: Mapped[str] = db.Column(
        "orig_deptcode",
        db.String(10),
        db.ForeignKey("tlkpdept.deptcode"),
        nullable=False,
    )
    orig_inst: Mapped[str] = db.Column(
        "orig_instcode",
        db.String(20),
        db.ForeignKey("tlkpinst.instcode"),
        nullable=False,
    )

    # Note we're marking this as a fetched value even though it is not
    # to avoid it being included in generated insert/update statements
    used: Mapped[Optional[bool]] = db.Column(
        "time_used",
        db.Boolean(),
        server_default=db.FetchedValue(),
        server_onupdate=db.FetchedValue(),
        nullable=False,
    )

    requests: Mapped[list["SupportRequest"]] = db.relationship(
        "SupportRequest",
        lazy="joined",
        uselist=True,
        primaryjoin="ScheduleEntry.id==SupportRequest.schedid",
    )


class Membership(Model):
    """Membership is a view over user membership sufficient for all membership queries.

    Some of the underlying relations are also exposed to sqlalchemy but only for CRUD operations."""

    __tablename__ = "membership"

    group: Mapped[str] = db.Column("group", db.String(10))
    user: Mapped[str] = db.Column("user", db.String(20))

    pi: Mapped[bool] = db.Column("pi", db.Boolean(), nullable=False)
    approved: Mapped[bool] = db.Column("approved", db.Boolean(), nullable=False)
    email_status: Mapped[str] = db.Column("email_status", db.String(10), nullable=False)
    group_active: Mapped[bool] = db.Column("group_active", db.Boolean(), nullable=False)
    user_active: Mapped[bool] = db.Column("user_active", db.Boolean(), nullable=False)

    __table_args__ = (db.PrimaryKeyConstraint("group", "user"),)


class GroupMember(Model):
    """GroupMember is only meant for insert/update/delete. Use Membership for queries."""

    __tablename__ = "groupmembers"

    group: Mapped[str] = db.Column(
        "deptcode", db.String(10), db.ForeignKey("tlkpdept.deptcode")
    )
    user: Mapped[str] = db.Column(
        "researchercode", db.String(20), db.ForeignKey("tlkpresearcher.researchercode")
    )

    approved: Mapped[Any] = db.Column(
        "approved", db.DateTime(timezone=True), nullable=True
    )
    email_status: Mapped[str] = db.Column(
        "email_status", db.String(10), nullable=False, default="none"
    )

    __table_args__ = (db.PrimaryKeyConstraint("deptcode", "researchercode"),)


class PrimaryGroupMember(Model):
    """PrimaryGroupMember is only for insert and delete. Use Membership for queries."""

    __tablename__ = "primarygroupmember"

    group: Mapped[str] = db.Column(
        "deptcode", db.String(10), db.ForeignKey("tlkpdept.deptcode")
    )
    user: Mapped[str] = db.Column(
        "researchercode", db.String(20), db.ForeignKey("tlkpresearcher.researchercode")
    )

    __table_args__ = (db.PrimaryKeyConstraint("deptcode", "researchercode"),)


class Technologist(Model):
    __tablename__ = "technologist"
    user: Mapped[str] = db.Column(
        "researchercode",
        db.String(20),
        db.ForeignKey("tlkpresearcher.researchercode"),
        primary_key=True,
    )
    applied_on: Mapped[Any] = db.Column(
        "applied_on", db.DateTime(timezone=True), nullable=False, default=func.now()
    )
    approved_on: Mapped[Any] = db.Column(
        "approved_on", db.DateTime(timezone=True), nullable=True
    )
    email_status: Mapped[str] = db.Column(
        "email_status", db.String(10), nullable=False, default="none"
    )


class DeviceGroup(Model):
    __tablename__ = "devicegroup"

    device: Mapped[str] = db.Column(
        "scannercode", db.String(5), db.ForeignKey("tlkpscanner.scannercode")
    )
    group: Mapped[str] = db.Column(
        "deptcode", db.String(10), db.ForeignKey("tlkpdept.deptcode")
    )

    __table_args__ = (db.PrimaryKeyConstraint("scannercode", "deptcode"),)


class UserDevice(Model):
    __tablename__ = "userdevice"

    user: Mapped[str] = db.Column(
        "researchercode", db.String(20), db.ForeignKey("tlkpresearcher.researchercode")
    )
    device: Mapped[str] = db.Column(
        "scannercode", db.String(5), db.ForeignKey("tlkpscanner.scannercode")
    )

    templates: Mapped[bool] = db.Column("templates", db.Boolean(), nullable=False)
    slot: Mapped[bool] = db.Column("slot", db.Boolean(), nullable=False)
    tech: Mapped[bool] = db.Column("tech", db.Boolean(), nullable=False)
    medical: Mapped[bool] = db.Column("medical", db.Boolean(), nullable=False)
    training: Mapped[bool] = db.Column("training", db.Boolean(), nullable=False)

    __table_args__ = (db.PrimaryKeyConstraint("researchercode", "scannercode"),)


class RbacAuditLog(Model):
    __tablename__ = "rbac_audit_log"

    id: Mapped[int] = db.Column("auditid", db.BigInteger(), primary_key=True)
    occurred_at: Mapped[Any] = db.Column(
        "occurred_at",
        db.DateTime(timezone=True),
        db.FetchedValue(for_update=False),
        nullable=False,
        server_default=func.now(),
    )

    action: Mapped[str] = db.Column("action", db.Text(), nullable=False)
    actor: Mapped[str] = db.Column("actor", db.String(20), nullable=False)
    ip: Mapped[Optional[str]] = db.Column("ip_addr", db.String(64), nullable=True)
    where_path: Mapped[str] = db.Column("where_path", db.Text(), nullable=False)
    how: Mapped[str] = db.Column("how", db.String(32), nullable=False)
    what: Mapped[str] = db.Column("what", db.Text(), nullable=False)

    group: Mapped[Optional[str]] = db.Column("deptcode", db.Text(), nullable=True)
    device: Mapped[Optional[str]] = db.Column("scannercode", db.Text(), nullable=True)
    user: Mapped[Optional[str]] = db.Column("researchercode", db.Text(), nullable=True)
    requester: Mapped[Optional[str]] = db.Column(
        "requestercode", db.Text(), nullable=True
    )


class EmailAuditLog(Model):
    __tablename__ = "email_audit_log"

    id: Mapped[int] = db.Column("auditid", db.BigInteger(), primary_key=True)
    occurred_at: Mapped[Any] = db.Column(
        "occurred_at",
        db.DateTime(timezone=True),
        db.FetchedValue(for_update=False),
        nullable=False,
        server_default=func.now(),
    )

    action: Mapped[str] = db.Column("action", db.Text(), nullable=False)
    actor: Mapped[str] = db.Column("actor", db.String(20), nullable=False)
    ip: Mapped[Optional[str]] = db.Column("ip_addr", db.String(64), nullable=True)
    where_path: Mapped[str] = db.Column("where_path", db.Text(), nullable=False)
    how: Mapped[str] = db.Column("how", db.String(32), nullable=False)
    status: Mapped[str] = db.Column("status", db.String(16), nullable=False)
    recipient: Mapped[str] = db.Column("recipient", db.Text(), nullable=False)
    subject: Mapped[str] = db.Column("subject", db.Text(), nullable=False)
    details: Mapped[str] = db.Column("details", db.Text(), nullable=False)
    issue_key: Mapped[Optional[str]] = db.Column("issue_key", db.Text(), nullable=True)
    issue_state: Mapped[str] = db.Column("issue_state", db.String(16), nullable=False)

    group: Mapped[Optional[str]] = db.Column("deptcode", db.Text(), nullable=True)
    device: Mapped[Optional[str]] = db.Column("scannercode", db.Text(), nullable=True)
    user: Mapped[Optional[str]] = db.Column("researchercode", db.Text(), nullable=True)
    requester: Mapped[Optional[str]] = db.Column(
        "requestercode", db.Text(), nullable=True
    )


class NotificationIncident(Model):
    __tablename__ = "notification_incident"

    issue_key: Mapped[str] = db.Column("issue_key", db.Text(), primary_key=True)
    issue_type: Mapped[str] = db.Column("issue_type", db.Text(), nullable=False)
    category: Mapped[str] = db.Column("category", db.Text(), nullable=False)
    severity: Mapped[str] = db.Column("severity", db.String(16), nullable=False)
    title: Mapped[str] = db.Column("title", db.Text(), nullable=False)
    detail: Mapped[str] = db.Column("detail", db.Text(), nullable=False)
    href: Mapped[Optional[str]] = db.Column("href", db.Text(), nullable=True)
    link_label: Mapped[str] = db.Column(
        "link_label", db.Text(), nullable=False, default=""
    )

    active: Mapped[bool] = db.Column(
        "active", db.Boolean(), nullable=False, default=True
    )
    state: Mapped[str] = db.Column(
        "state", db.String(16), nullable=False, default="open"
    )
    state_note: Mapped[str] = db.Column(
        "state_note", db.Text(), nullable=False, default=""
    )
    state_changed_by: Mapped[Optional[str]] = db.Column(
        "state_changed_by", db.String(20), nullable=True
    )
    state_changed_at: Mapped[Any] = db.Column(
        "state_changed_at",
        db.DateTime(timezone=True),
        db.FetchedValue(for_update=False),
        nullable=False,
        server_default=func.now(),
    )
    ignored_until: Mapped[Optional[Any]] = db.Column(
        "ignored_until", db.DateTime(timezone=True), nullable=True
    )

    first_seen_at: Mapped[Any] = db.Column(
        "first_seen_at",
        db.DateTime(timezone=True),
        db.FetchedValue(for_update=False),
        nullable=False,
        server_default=func.now(),
    )
    last_seen_at: Mapped[Any] = db.Column(
        "last_seen_at",
        db.DateTime(timezone=True),
        db.FetchedValue(for_update=False),
        nullable=False,
        server_default=func.now(),
    )
    last_detected_at: Mapped[Optional[Any]] = db.Column(
        "last_detected_at", db.DateTime(timezone=True), nullable=True
    )
    last_resolved_at: Mapped[Optional[Any]] = db.Column(
        "last_resolved_at", db.DateTime(timezone=True), nullable=True
    )
    occurrence_count: Mapped[int] = db.Column(
        "occurrence_count", db.Integer(), nullable=False, default=1
    )
    fingerprint: Mapped[str] = db.Column(
        "fingerprint", db.Text(), nullable=False, default=""
    )


class SchedLogEntry(Model):
    """SchedLogEntry is a view that should always be used with a specified id"""

    __tablename__ = "app_log_json"

    id: Mapped[int] = db.Column("schedid", db.Integer(), primary_key=True)
    entries: Mapped[Any] = db.Column("entries", db.JSON(), nullable=True)


class OAuthState(Model):
    """Temporary OAuth state storage for server-side login flow."""

    __tablename__ = "oauth_state"

    state: Mapped[str] = db.Column("state", db.String(128), primary_key=True)
    nonce: Mapped[str] = db.Column("nonce", db.String(128), nullable=False)
    redirect_next: Mapped[Optional[str]] = db.Column(
        "redirect_next", db.Text(), nullable=True
    )
    code_verifier: Mapped[Optional[str]] = db.Column(
        "code_verifier", db.String(128), nullable=True
    )
    created_at: Mapped[Any] = db.Column(
        "created_at",
        db.DateTime(timezone=True),
        db.FetchedValue(for_update=False),
        nullable=False,
        server_default=func.now(),
    )


class AppSetting(Model):
    __tablename__ = "app_settings"

    key: Mapped[str] = db.Column("key", db.String(128), primary_key=True)
    value: Mapped[str] = db.Column("value", db.Text(), nullable=False, default="")
    updated_at: Mapped[Any] = db.Column(
        "updated_at",
        db.DateTime(timezone=True),
        db.FetchedValue(for_update=False),
        nullable=False,
        server_default=func.now(),
    )
    updated_by: Mapped[Optional[str]] = db.Column(
        "updated_by", db.String(20), nullable=True
    )


class AppErrorEvent(Model):
    __tablename__ = "app_error_event"

    id: Mapped[int] = db.Column("eventid", db.BigInteger(), primary_key=True)
    reference_id: Mapped[str] = db.Column(
        "reference_id", db.String(32), nullable=False, unique=True
    )
    occurred_at: Mapped[Any] = db.Column(
        "occurred_at",
        db.DateTime(timezone=True),
        db.FetchedValue(for_update=False),
        nullable=False,
        server_default=func.now(),
    )

    actor: Mapped[str] = db.Column("actor", db.String(20), nullable=False)
    ip: Mapped[Optional[str]] = db.Column("ip_addr", db.String(64), nullable=True)
    user_agent: Mapped[str] = db.Column(
        "user_agent", db.Text(), nullable=False, default=""
    )
    method: Mapped[str] = db.Column("method", db.String(8), nullable=False)
    where_path: Mapped[str] = db.Column("where_path", db.Text(), nullable=False)
    endpoint: Mapped[Optional[str]] = db.Column("endpoint", db.Text(), nullable=True)
    status_code: Mapped[int] = db.Column(
        "status_code", db.Integer(), nullable=False, default=500
    )
    exception_type: Mapped[str] = db.Column("exception_type", db.Text(), nullable=False)
    exception_message: Mapped[str] = db.Column(
        "exception_message", db.Text(), nullable=False
    )
    fingerprint: Mapped[str] = db.Column("fingerprint", db.Text(), nullable=False)
    request_context: Mapped[Any] = db.Column(
        "request_context", db.JSON(), nullable=False
    )
    stack_trace: Mapped[str] = db.Column("stack_trace", db.Text(), nullable=False)


class CspViolationEvent(Model):
    __tablename__ = "csp_violation_event"

    id: Mapped[int] = db.Column("eventid", db.BigInteger(), primary_key=True)
    occurred_at: Mapped[Any] = db.Column(
        "occurred_at",
        db.DateTime(timezone=True),
        db.FetchedValue(for_update=False),
        nullable=False,
        server_default=func.now(),
    )

    report_type: Mapped[str] = db.Column("report_type", db.String(32), nullable=False)
    actor: Mapped[str] = db.Column("actor", db.String(20), nullable=False)
    ip: Mapped[Optional[str]] = db.Column("ip_addr", db.String(64), nullable=True)
    user_agent: Mapped[str] = db.Column(
        "user_agent", db.Text(), nullable=False, default=""
    )
    document_uri: Mapped[str] = db.Column(
        "document_uri", db.Text(), nullable=False, default=""
    )
    referrer: Mapped[Optional[str]] = db.Column("referrer", db.Text(), nullable=True)
    blocked_uri: Mapped[Optional[str]] = db.Column(
        "blocked_uri", db.Text(), nullable=True
    )
    violated_directive: Mapped[str] = db.Column(
        "violated_directive", db.Text(), nullable=False, default=""
    )
    effective_directive: Mapped[Optional[str]] = db.Column(
        "effective_directive", db.Text(), nullable=True
    )
    original_policy: Mapped[Optional[str]] = db.Column(
        "original_policy", db.Text(), nullable=True
    )
    source_file: Mapped[Optional[str]] = db.Column(
        "source_file", db.Text(), nullable=True
    )
    line_number: Mapped[Optional[int]] = db.Column(
        "line_number", db.Integer(), nullable=True
    )
    column_number: Mapped[Optional[int]] = db.Column(
        "column_number", db.Integer(), nullable=True
    )
    disposition: Mapped[str] = db.Column("disposition", db.String(16), nullable=False)
    status_code: Mapped[Optional[int]] = db.Column(
        "status_code", db.Integer(), nullable=True
    )
    script_sample: Mapped[Optional[str]] = db.Column(
        "script_sample", db.Text(), nullable=True
    )
    report_body: Mapped[Any] = db.Column("report_body", db.JSON(), nullable=False)
