import datetime
import secrets
from typing import Any, Optional

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.ext.declarative import DeclarativeMeta
from sqlalchemy.sql import func

db = SQLAlchemy()

# this is only needed to avoid confusing mypy
Model: DeclarativeMeta = db.Model

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
        onupdate=func.now(),
        nullable=False,
    )

    addr: str = db.Column("email", db.Text(), nullable=False, default="")


def upsert_user(user: str, mail: str, name: str) -> User:
    # upsert the user to ensure the record exists
    db.session.execute(
        "insert into tlkpresearcher(researchercode) values (:user) on conflict do nothing",
        {
            "user": user,
        },
    )
    # load the user
    u = User.query.get(user)

    # if the mail and/or display name have changed, update them
    # as long as the new values are not empty.
    add = False
    if mail != "" and u.addr != mail:
        u.addr = mail
        add = True
    if name != "" and u.label != name:
        u.label = name
        add = True
    if add:
        db.session.add(u)

    return u


def get_user(user: str) -> Optional[User]:
    return User.query.get(user)


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

    dept: Optional[str] = db.Column(
        "deptcode", db.String(10), db.ForeignKey("tlkpdept.deptcode"), nullable=True
    )
    user: Optional[str] = db.Column(
        "researchercode", db.String(20), db.ForeignKey("tlkpresearcher.researchercode")
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

    _group: Optional[str] = db.Column(
        "deptcode", db.String(10), db.ForeignKey("tlkpdept.deptcode"), nullable=False
    )
    _user: Optional[str] = db.Column(
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

    group = db.relationship(
        "Group",
        lazy="joined",
        uselist=False,
        primaryjoin="ScheduleEntry._group == Group.id",
    )
    user = db.relationship(
        "User",
        lazy="joined",
        uselist=False,
        primaryjoin="ScheduleEntry._user == User.id",
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

    approve1: Any = db.Column("approve1", db.DateTime(timezone=True), nullable=True)
    approve2: Any = db.Column("approve2", db.DateTime(timezone=True), nullable=True)

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


class SchedLogEntry(Model):
    """SchedLogEntry is a view that should always be used with a specified id"""

    __tablename__ = "app_log_json"

    id: int = db.Column("schedid", db.Integer(), primary_key=True)
    entries: Any = db.Column("entries", db.JSON(), nullable=True)


class ResetTokens(Model):
    __tablename__ = "reset_tokens"

    token: str = db.Column("token", db.String(), primary_key=True)
    for_user: str = db.Column(
        "for_user",
        db.String(20),
        db.ForeignKey("tlkpresearcher.researchercode"),
        nullable=False,
    )
    issued: Any = db.Column(
        "issued", db.DateTime(), db.FetchedValue(for_update=False), nullable=False
    )

    user: User = db.relationship("User", lazy="joined")


def create_reset_token_for(user: str) -> str:
    token = secrets.token_urlsafe(64)
    t = ResetTokens(token=token, for_user=user)
    # this can technically fail if we happen to generate the same token twice
    # but the odds against that are so great that it would actually be cool
    # if it happened
    db.session.add(t)
    # this is only expected to be called from cli so save it now
    # let any fk errors bubble up
    db.session.commit()
    return token


def get_user_from_token(token: str) -> Optional[User]:
    # delete all old tokens before we check
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    ResetTokens.query.filter(ResetTokens.issued < yesterday).delete()
    # see if the token exists
    rt = ResetTokens.query.get(token)
    if rt is None:
        return None
    # if it does grab the user and delete the token
    user = rt.user
    db.session.delete(rt)
    db.session.commit()
    return user
