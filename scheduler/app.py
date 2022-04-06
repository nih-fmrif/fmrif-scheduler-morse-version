import ipaddress
from functools import wraps
from typing import Dict, List, Optional, Tuple, Union

import click
from flask import Flask, abort, g, jsonify, redirect, request, session
from flask.helpers import flash, url_for
from flask.templating import render_template
from flask.wrappers import Response
from flask_session import Session
from itsdangerous.url_safe import URLSafeSerializer

import config
import logic
import message
import model

## Configuration

app = Flask(__name__)

app.config.update(**config.basic_settings(app.debug))


def proxy_fix(app):
    # load info about proxies so we can get correct remote addr
    # see: https://werkzeug.palletsprojects.com/en/2.0.x/middleware/proxy_fix/

    counts = config.proxy_count()
    if counts is not None:
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(app.wsgi_app, **counts)


proxy_fix(app)

with app.open_resource("config.json", "r") as f:
    app.config.update(**config.load_user_settings(app.debug, f))


model.db.init_app(app)
Session(app)
message.mailer.init_app(app)
signer = URLSafeSerializer(app.config["SECRET_KEY"], salt="nih-scheduler")
app.config["URL_SIGNER"] = signer

## Authentication


@app.before_request
def setup_user():
    # user already loaded
    if "user" in g:
        return

    # add a null user so we can exit early and ensure something is always set
    g.user = None

    # we don't need to bother to do anything special for static assets
    if request.endpoint == "static":
        return

    # the logged in user to this site or ""
    user_name = session.get("user_name", "")
    # the logged in user to AD or ""
    sm_user_name = request.headers.get("HTTP_SM_USER", "")

    if sm_user_name == "" and user_name == "":
        # there is no user to load
        return

    # the user to login as, if needed
    login_as = ""

    if sm_user_name != "" and user_name != "":
        # if the SM user name is different than the user we have on file,
        # we log out the old user and log the new one in;
        # otherwise we're still logged in
        if user_name != sm_user_name:
            login_as = sm_user_name
    elif sm_user_name != "" and user_name == "":
        # we're not logged into the site but we are logged into AD
        # so login to the site
        login_as = sm_user_name
    elif sm_user_name == "" and user_name != "":
        # we're logged into the site but AD credentials have gone away.
        # we want to stay logged in, so there's nothing to do here
        # except to continue and load user_name
        pass

    if login_as != "":
        mail = request.headers.get("HTTP_USER_EMAIL", "")
        name = request.headers.get("HTTP_NIH_DISPLAYNAME", "")
        name = logic.discard_user_titles(name)
        session["user_name"] = login_as
        g.user = logic.upsert_user(login_as, mail, name)
        model.db.session.commit()  # ensure these changes even if the rest of the request fails
        app.logger.info("new login for user: %s", login_as)
    else:
        # we are an existing login, just fetch the user object
        g.user = logic.get_user(user_name)
        # it's possible that this can fail if the user record
        # gets deleted while the session is ongoing but then
        # this would return None so it would be the same as being
        # logged out, still avoid inconsistent state by
        # cleaning up the session.
        if g.user is None:
            del session["user_name"]


def login_required(f):
    @wraps(f)
    def protect(*args, **kwargs):
        if g.user is None:
            abort(403, "Access denied: AD login required")
        return f(*args, **kwargs)

    return protect


def in_network_required(f):
    @wraps(f)
    def protect(*args, **kwargs):
        ip = ipaddress.ip_address(request.access_route[-1])
        if not any(ip in addr for addr in app.config["nih_networks"]):
            abort(403, "Access denied: this page is limited to the NIH network")
        return f(*args, **kwargs)

    return protect


def active_user_required(f):
    @wraps(f)
    def protect(*args, **kwargs):
        if g.user is None:
            abort(403, "Access denied: AD login required")
        if not g.user.active:
            abort(403, "Access denied: this page is limited to active users")
        return f(*args, **kwargs)

    return protect


def admin_only(f):
    @wraps(f)
    def protect(*args, **kwargs):
        if not (g.user is not None and g.user.active and logic.is_admin(g.user)):
            abort(403, "Access denied: this page is admin only")
        return f(*args, **kwargs)

    return protect


## Error handlers


def render_error_page(code: int, msg: str, show_login: bool = False) -> Tuple[str, int]:
    data = {
        "code": code,
        "msg": msg,
        "show_login": show_login,
        "login_url_prefix": app.config["SM_LOGIN_URL_PREFIX"],
    }
    return render_template("error.html", **data), code


@app.errorhandler(403)
def access_denied(e):
    # show login if no user object loaded
    show_login = g.user is None
    return render_error_page(403, e.description, show_login=show_login)


@app.errorhandler(404)
def not_found(e):
    return render_error_page(404, "Not found")


## CLI commands


@app.cli.command("force-login")
@click.argument("user")
def force_login_cli(user):
    """Create a login link for USER"""
    u = logic.get_user(user)
    if u is None:
        click.echo(f"no such user {user}")
        return
    token = logic.create_reset_token_for(user)
    click.echo(url_for("force_login", token=token))


@app.cli.command("deactivate-user")
@click.argument("user")
def deactivate_user(user):
    """mark USER as no longer active"""
    u = logic.get_user(user)
    if u is None:
        click.echo(f"no such user {user}")
        return
    u.active = False
    model.db.session.add(u)
    model.db.session.commit()
    click.echo(f"{user} is now inactive")


@app.cli.command("activate-user")
@click.argument("user")
def activate_user(user):
    """mark USER as active"""
    u = logic.get_user(user)
    if u is None:
        click.echo(f"no such user {user}")
        return
    u.active = True
    model.db.session.add(u)
    model.db.session.commit()
    click.echo(f"{user} is now active")


@app.cli.command("add-admin")
@click.argument("user")
def add_admin(user):
    """add USER as an approved member of the admin group"""
    u = logic.get_user(user)
    if u is None:
        click.echo(f"no such user {user}")
        return
    if not u.active:
        click.echo("only active users may be added to admin group")
    if logic.is_admin(u):
        return  # nothing to do
    logic.add_admin(u)
    model.db.session.commit()
    click.echo(f"{user} is now an admin")


## Route helpers


def my_url() -> str:
    route = request.endpoint
    if not isinstance(route, str):
        abort(500)
    kwargs = request.view_args or {}
    return url_for(route, **kwargs)


# arguably a bad name but always used as return to(route)
# so it makes a lot of sense in context and is very concise
def to(page: str, **kwargs):
    return redirect(url_for(page, **kwargs))


# variant of to that goes to the current url
# useful in forms that can be filled out more than once
# redirecting to self prevents reloading the page from resubmitting the data
def to_form():
    return redirect(my_url())


Breadcrumb_links = Dict[str, List[Tuple[str, str]]]


def breadcrumb(*routes: Union[str, Tuple[str, str]]) -> Breadcrumb_links:
    trail: List[Tuple[str, str]] = [("home", url_for("home"))]
    if len(routes) > 0:
        routes, last = routes[:-1], routes[-1]
        for r in routes:
            assert not isinstance(r, str)
            trail.append(r)
        if isinstance(last, str):
            trail.append((last, my_url()))
        else:
            trail.append(last)
    return {"breadcrumb": trail}


def sr_only_tag(s: str) -> str:
    """replace " [" with "<sr-only>" and "]" with "</sr-only>",
    allowing more compact representation of common pattern."""
    return s.replace(" [", "<sr-only> ").replace("]", "</sr-only>")


Subpage_links = Dict[str, Dict[str, Union[str, List[Tuple[str, str]]]]]


def subpage_nav(title: str, links: List[Tuple[bool, str, str]]) -> Subpage_links:
    shown = [(sr_only_tag(link), href) for (include, link, href) in links if include]
    if len(shown) <= 1:
        return {"subpage_nav": {}}
    return {
        "subpage_nav": {
            "title": sr_only_tag(title),
            "links": shown,
        },
    }


def render_to(template):
    """decorator that applies template to return of wrapped func"""

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            ctx = f(*args, **kwargs)
            if ctx is None:
                ctx = {}
            elif not isinstance(ctx, dict):
                return ctx
            # always inject user into context for login info component
            ctx["user"] = g.user
            return render_template(template + ".html", **ctx)

        return decorated_function

    return decorator


## Routes


@app.route("/robots.txt")
def robots():
    return Response("User-agent: *\nDisallow: /", mimetype="text/plain")


@app.route("/force-login/<token>")
def force_login(token):
    user = logic.get_user_from_token(token)
    if user is None:
        abort(400)
    session["user_name"] = user.id
    g.user = user
    return redirect("/")


@app.route("/")
@login_required
@render_to("index")
def home():
    routes = []
    routes.append(("devices", url_for("devices")))

    active = g.user.active
    memberships = logic.get_memberships(g.user)
    if active and len(memberships) > 0:
        routes.append(("groups", url_for("groups")))

    if active:
        routes.append(("join form", url_for("join_form")))
    routes.append(("list action form", url_for("mailing_lists")))

    return {
        "routes": routes,
        **breadcrumb(),
    }


@app.route("/mailing-lists", methods=["GET", "POST"])
@login_required
@render_to("mailing-lists")
def mailing_lists():
    form = logic.get_mailing_list_form(name=g.user.label, addr=g.user.addr)
    if form.validate_on_submit():
        logic.process_mailing_list_form_submissions(form)
        flash("your mailing list subscription status has been updated")
        return to("home")
    return {
        "form": form,
        "action": my_url(),
        **breadcrumb("list action form"),
    }


def join_form_subnav(user: model.User) -> Subpage_links:
    return subpage_nav(
        "show [which form]",
        [
            (True, "join form", url_for("join_form")),
            (
                logic.show_tech_join_form(g.user),
                "technologist join form",
                url_for("join_form_tech"),
            ),
        ],
    )


def join_form_breadcrumb() -> Breadcrumb_links:
    return breadcrumb(("join form", url_for("join_form")))


@app.route("/join", methods=["GET", "POST"])
@in_network_required
@active_user_required
@render_to("join")
def join_form():
    departments = logic.get_departments_for_join_form(g.user)
    form = logic.JoinForm(departments)
    no_departments = False
    if len(departments) == 0:
        no_departments = True
    if form.validate_on_submit():
        if logic.record_join_form(form, g.user, form.group.data):
            logic.notify_group_pi_of_join_form(g.user, form.group.data)
            flash("your membership request is being processed")
            return to("home")
    return {
        "form": form,
        "action": my_url(),
        "no_departments": no_departments,
        **join_form_subnav(g.user),
        **join_form_breadcrumb(),
    }


@app.route("/join/tech", methods=["GET", "POST"])
@in_network_required
@active_user_required
@render_to("join_tech")
def join_form_tech():
    if not logic.show_tech_join_form(g.user):
        abort(
            403,
            "Only DEV members who have not become technologists already may access this form",
        )
    # we only need to show the form on GET and there's nothing to validate on post:
    # if the browser allowed the form to be submitted, it's good
    if request.method == "POST":
        logic.record_tech_join(g.user)
        model.db.session.commit()
        logic.notify_dev_pi_of_tech_join_form(g.user)
        flash("you are now a technologist")
        return to("home")
    return {
        **join_form_subnav(g.user),
        **join_form_breadcrumb(),
    }


@app.route("/join/approve/<token>", endpoint="join-group-approve")
@app.route("/join/deny/<token>", endpoint="join-group-deny")
@active_user_required
def handle_join_group(token):
    req = logic.read_signed_message(token)

    # make sure token is a real token
    if req is None or len(req) != 3 or req[0] != "join-group":
        abort(400)

    # get the user and group from the token data
    _, uid, gid = req
    u = logic.get_user(uid)
    if u is None or not u.active:
        abort(400)
    grp = logic.get_group(gid)
    if grp is None or not grp.active:
        abort(400)

    # make sure the request is unprocessed
    req = logic.get_join_request(u, grp)
    if req is None:
        flash("this request was previously denied")
        return to("home")

    if req.approved is not None:
        flash("this request was previously approved")
        return to("home")

    # make sure current user is PI of g
    pi = logic.pi_of_group(gid)
    if pi != g.user.id:
        abort(403, f"only the PI of {grp.label} can approve or deny this request")

    approve = request.endpoint == "join-group-approve"

    logic.handle_join_request(approve, req)
    model.db.session.commit()

    if approve:
        flash(f"you have approved {u.id} to be a member of {grp.label}")
    else:
        flash(f"you have denied {u.id} from becoming a member {grp.label}")
    logic.notify_user_of_join_request_outcome(approve, u, grp.label)

    return to("home")


def groups_subpage_nav(is_admin: bool) -> Subpage_links:
    return subpage_nav(
        "show [which groups]",
        [
            (True, "active [groups]", url_for("groups")),
            (
                is_admin,
                "inactive [groups]",
                url_for("groups-inactive"),
            ),
            (is_admin, "add group", url_for("group_add")),
        ],
    )


def groups_breadcrumb() -> Breadcrumb_links:
    return breadcrumb(("groups", url_for("groups")))


@app.route("/groups")
@app.route("/groups/inactive", endpoint="groups-inactive")
@active_user_required
@render_to("groups")
def groups():
    title = "groups"
    memberships = logic.get_memberships(g.user)
    is_admin = "admin" in memberships
    active = request.endpoint == "groups"
    if not active:
        if not is_admin:
            abort(403, "access denied")
        title += " (inactive)"

    groups = []
    if is_admin:
        # admin see all groups with members
        groups = logic.get_all_groups_with_members(active)
    else:
        # nonadmins only see groups they're in
        groups = logic.get_groups(memberships)

    return {
        "title": title,
        "groups": groups,
        **groups_subpage_nav(is_admin),
        **groups_breadcrumb(),
    }


@app.route("/groups/add", methods=["GET", "POST"])
@admin_only
@render_to("group_edit")
def group_add():
    institutes = logic.get_institutes_datalist()
    form = logic.GroupEditForm("", institutes, is_admin=True, create=True)

    if form.validate_on_submit():
        if logic.create_group(form):
            flash("new group added")
            return to("group", the_group=form.id.data)

    return {
        "title": "add new group",
        "form": form,
        "action": my_url(),
        "submit": "create",
        **groups_subpage_nav(True),
        **groups_breadcrumb(),
    }


# shared subpage nav for all group pages
def group_subpage_nav(group: model.Group, su: logic.Group_leader_kind) -> Subpage_links:
    can_edit = "group_pi" in su or "admin" in su
    return subpage_nav(
        "show",
        [
            # view has further protections, but if you can see any of them you can see it
            (True, f"view [{group.label}]", url_for("group", the_group=group.id)),
            (
                group.active and can_edit,
                f"membership [for {group.label}]",
                url_for("group_membership", the_group=group.id),
            ),
            (
                group.active and can_edit,
                f"change PI [of {group.label}]",
                url_for("group_pi", the_group=group.id),
            ),
            (
                can_edit,
                f"edit [{group.label}]",
                url_for("group_edit", the_group=group.id),
            ),
        ],
    )


def group_breadcrumb(group: model.Group) -> Breadcrumb_links:
    return breadcrumb(
        ("groups", url_for("groups")),
        (group.label, url_for("group", the_group=group.id)),
    )


@app.route("/group/<the_group>")
@active_user_required
@render_to("group")
def group(the_group):
    group = logic.get_group(the_group)
    if group is None:
        abort(404)

    su = logic.get_group_leader_kind(g.user, group)

    # inactive groups can only be viewed by admins
    if not (group.active or "admin" in su):
        abort(403)

    members = logic.get_members_of_group(group)

    # must be admin, dev_pi, or member
    if not (len(su) > 0 or any(m == g.user.id for (m, _, _) in members)):
        abort(403)

    return {
        "group": group,
        "members": members,
        "su": su,
        **group_subpage_nav(group, su),
        **group_breadcrumb(group),
    }


@app.route("/group/<the_group>/edit", methods=["GET", "POST"])
@active_user_required
@render_to("group_edit")
def group_edit(the_group):
    group = logic.get_group(the_group)
    if group is None:
        abort(404)

    su = logic.get_group_leader_kind(g.user, group)
    is_admin = "admin" in su

    # only admins and group pi (if group active) can edit
    if not (is_admin or (group.active and "group_pi" in su)):
        abort(403)

    institutes = []
    if is_admin:
        institutes = logic.get_institutes_datalist()
    form = logic.GroupEditForm(group.id, institutes, is_admin=is_admin, obj=group)

    if form.validate_on_submit():
        if logic.update_group(is_admin, group, form):
            flash(f"{group.label} has been updated")
            return to("group", the_group=the_group)

    return {
        "title": f"edit {group.label}",
        "group": group,
        "su": su,
        "form": form,
        "action": my_url(),
        "submit": "save",
        **group_subpage_nav(group, su),
        **group_breadcrumb(group),
    }


@app.route("/group/<the_group>/membership", methods=["GET", "POST"])
@active_user_required
@render_to("group_membership")
def group_membership(the_group):
    group = logic.get_group(the_group)
    if group is None:
        abort(404)

    # cannot work with membership of inactive group, even if admin
    if not group.active:
        abort(403)

    su = logic.get_group_leader_kind(g.user, group)

    if not ("group_pi" in su or "admin" in su):
        abort(403)

    members = logic.get_members_of_group(group, all=True)
    active, pending = [], []
    for m, is_pi, is_active in members:
        if is_active and not is_pi:
            active.append(m)
        elif not is_active:
            pending.append(m)

    form = logic.get_group_membership_form(group, active, pending)

    no_entries = ""
    if len(active) + len(pending) == 0:
        no_entries = "there is no membership data that can be updated for this group"

    if form.validate_on_submit():
        action, u = form.action()
        user = logic.get_user(u)
        if user is None:
            abort(400, f"{u} does not exist in db")
        if action == "rm":
            logic.remove_user_from_group(user, group)
            model.db.session.commit()
            flash(f"{user.id} is no longer a member of {group.label}")
        elif action == "approve" or action == "deny":
            req = logic.get_join_request(user, group)
            if req is not None:
                # if req is None, membership was deleted by someone else
                # between getting the form and submitting it
                approved = action == "approve"
                logic.handle_join_request(approved, req)
                model.db.session.commit()
                logic.notify_user_of_join_request_outcome(approved, user, group.label)
                outcome = "denied membership"
                if approved:
                    outcome = "approved"
                flash(f"{user.id} was {outcome}")

        return to_form()

    return {
        "title": f"edit {group.label} membership",
        "action": my_url(),
        "form": form,
        "no_entries": no_entries,
        **group_subpage_nav(group, su),
        **group_breadcrumb(group),
    }


@app.route("/group/<the_group>/pi", methods=["GET", "POST"])
@active_user_required
@render_to("group_pi")
def group_pi(the_group):
    group = logic.get_group(the_group)
    if group is None:
        abort(404)

    # cannot work with membership of inactive group, even if admin
    if not group.active:
        abort(403)

    su = logic.get_group_leader_kind(g.user, group)

    if not ("group_pi" in su or "admin" in su):
        abort(403)

    all_members = logic.get_members_of_group(group)
    not_pi = []
    for name, is_pi, _ in all_members:
        if not is_pi:
            not_pi.append(name)

    no_entries = ""
    if len(not_pi) == 0:
        no_entries = "no candidates for PI"

    form = logic.GroupPIForm(not_pi)
    if form.validate_on_submit():
        u = logic.process_group_pi_form(group, form)
        if u is not None:
            flash(f"{u.id} is now PI")
            # this is an important enough change to log
            app.logger.info(f"{g.user.id} changed pi of {group.id} to {u.id}")
            if "admin" not in su:
                # if we were the PI but are not now we no longer have access to this page
                # but we're still a member of the group
                return to("group", the_group=group.id)
            return to("group_membership", the_group=group.id)

    return {
        "title": f"change PI of {group.label}",
        "action": my_url(),
        "form": form,
        "no_entries": no_entries,
        **group_subpage_nav(group, su),
        **group_breadcrumb(group),
    }


def devices_breadcrumb() -> Breadcrumb_links:
    return breadcrumb(("devices", url_for("devices")))


def devices_subpage_nav(is_admin: bool) -> Subpage_links:
    return subpage_nav(
        "show [which devices]",
        [
            (True, "active [devices]", url_for("devices")),
            (
                is_admin,
                "inactive [devices]",
                url_for("devices-inactive"),
            ),
            (is_admin, "add device", url_for("device_add")),
        ],
    )


@app.route("/devices")
@app.route("/devices/inactive", endpoint="devices-inactive")
@login_required
@render_to("devices")
def devices():
    title = "devices"
    is_admin = logic.is_admin(g.user)
    active = request.endpoint == "devices"
    if not active:
        if not is_admin:
            abort(403, "access denied")
        title += " (inactive)"
    devices = logic.get_devices(active)
    return {
        "title": title,
        "devices": devices,
        **devices_subpage_nav(is_admin),
        **devices_breadcrumb(),
    }


@app.route("/device-add", methods=["GET", "POST"])
@admin_only
@render_to("device_edit")
def device_add():
    form = logic.DeviceEditForm(is_admin=True, create=True)

    if form.validate_on_submit():
        device = logic.create_device(form)
        if device is not None:
            flash(f"{device.label} created")
            return to("device", the_device=device.id)

    return {
        "title": "add new device",
        "action": my_url(),
        "submit": "create",
        "form": form,
        **devices_subpage_nav(True),
        **devices_breadcrumb(),
    }


def device_breadcrumb(device: model.Device) -> Breadcrumb_links:
    return breadcrumb(
        ("devices", url_for("devices")),
        (device.label, url_for("device", the_device=device.id)),
    )


def device_subpage_nav(device: model.Device, perms: logic.DevicePerms) -> Subpage_links:
    can = lambda p: perms.admin or (p and device.active)
    edit = can(perms.dev_pi)
    id = device.id
    return subpage_nav(
        f"show",
        [
            (True, "schedule", url_for("device", the_device=id)),
            (can(perms.template), "templates", url_for("device_tmpl", the_device=id)),
            (edit, "groups", url_for("device_groups", the_device=id)),
            (edit, "add group", url_for("device_groups_add", the_device=id)),
            (edit, "users", url_for("device_users", the_device=id)),
            (edit, "edit [{device.label}]", url_for("device_edit", the_device=id)),
        ],
    )


@app.route("/device/<the_device>", methods=["GET", "POST"])
@login_required
@render_to("device")
def device(the_device):
    device = logic.get_device(the_device)
    if device is None:
        abort(404)

    perms = logic.get_dev_perms(g.user, device)

    if not (device.active or perms.admin):
        abort(403)

    # get the date, defaulting to today
    date = None
    the_date = request.args.get("start")
    if the_date is not None:
        date = logic.parse_date(the_date)
        if date is None:
            abort(400, f"invalid start: {the_date} (must be YYYY-MM-DD date)")
    date = logic.date_or_today(date)

    # get the number of days to show, defaulting to 7
    days = 7
    the_days = request.args.get("days")
    if the_days is not None:
        days = logic.parse_days(the_days)
        if days is None:
            abort(400, f"invalid days: {the_days} (must be in 1-31)")

    # find the end date of the window to show
    end_date = logic.end_date(date, days)

    entries = logic.schedule_for(device, date, end_date)

    min, max = logic.device_schedule_extreme_dates(device)

    fmt_start_date = logic.fmt_date(date)
    fmt_end_date = logic.fmt_date(end_date)
    fmt_min = ""
    fmt_max = ""
    if min is not None:
        fmt_min = logic.fmt_date(min)
        fmt_max = logic.fmt_date(max)

    # compute which hours to hide by default
    off_hours = logic.off_hours()
    logic.strike_used_off_hours(off_hours, entries)
    off_hour_runs = logic.group_off_hours_into_runs(off_hours)
    off_hour_map = logic.convert_off_hour_runs_into_map(off_hour_runs)

    no_entries = ""
    never_entries = ""
    if len(entries) == 0:
        if min is None:
            never_entries = "this device has not yet had any entries scheduled on it"
        else:
            no_entries = f"no entries scheduled for {fmt_start_date}. All entries are between {fmt_min} and {fmt_max}"

    colors = logic.all_group_colors()

    # need to determine if user can edit this
    support = logic.SupportRequestDatalists([], [], [])
    members_of_groups = {}
    groups = []
    device_groups = logic.all_groups_of_device(device)

    # load any data user may need to edit
    if device.active and perms.edit:
        support = logic.support_request_datalists(device)

        # load all relevant group-member datalists
        if perms.edit_any:
            members_of_groups = logic.all_member_datalists_by_group(device)
            groups = device_groups
        else:
            members_of_groups = logic.member_datalists_by_group_for(device, g.user)
            groups = logic.groups_of_device_for(device, g.user)

    perms_json = {  # the permissions the js needs
        "edit": perms.edit,
        "edit_any": perms.edit_any,
        "tech": perms.tech,
        "medical": perms.medical,
        "training": perms.training,
    }
    groups_json = [id for (id, _) in groups]
    device_groups_json = [id for (id, _) in device_groups]

    top_row, grouped_entries = logic.group_schedule_entries(entries)

    hours = logic.fmt_hours()
    cur_date, cur_hour, cur_minute = logic.db_now()

    form = logic.JsonForm()
    if request.method == "POST":
        if not perms.edit:
            # direct request or user lost edit access between fetching page and submitting form
            abort(403)
        if not form.validate():
            # client response must specify payload
            abort(500)

        data = form.payload.data
        diffs = data["diffs"]
        send_notifications = data["notify"]

        xs, srs, when, errors = logic.verify_scheduler_diffs(
            diffs,
            entries,
            perms,
            support,
            cur_date,
            cur_hour,
            cur_minute,
            groups,
            members_of_groups,
            g.user,
        )
        if errors is not None:
            return jsonify({"errors": errors})

        staged = logic.apply_scheduler_diffs(g.user, xs)

        srs_notes = logic.apply_scheduler_sr_diffs(g.user, srs)

        _, _ = logic.prepare_notifications(send_notifications, when, diffs, srs_notes)

        for s in staged:
            model.db.session.add(s)
        model.db.session.commit()

        return jsonify({"saved": len(staged), "notifications": "TODO"})

    return {
        "device": device,
        "perms": perms,
        "perms_json": perms_json,
        "start_date": fmt_start_date,
        "end_date": fmt_end_date,
        "days": days,
        "top_row": top_row,
        "entries": grouped_entries,
        "min": fmt_min,
        "max": fmt_max,
        "never_entries": never_entries,
        "no_entries": no_entries,
        "support": support,
        "members_of_groups": members_of_groups,
        "groups": groups,
        "groups_json": groups_json,
        "device_groups_json": device_groups_json,
        "off_hours": list(off_hours),
        "off_hour_map": off_hour_map,
        "colors": colors,
        "hours": hours,
        "cur_date": cur_date,
        "cur_hour": cur_hour,
        "form": form,
        **device_breadcrumb(device),
        **device_subpage_nav(device, perms),
    }


@app.route("/json/v1/log/<eid>")
def entry_log(eid):
    if g.user is None:
        abort(403)

    device = logic.get_device_from_schedid(eid)
    if device is None:
        abort(404)

    perms = logic.get_dev_perms(g.user, device)
    if not (device.active or perms.admin):
        abort(403)

    r = logic.get_sched_log_entry(eid)

    return jsonify(r)


@app.route("/device/<the_device>/edit", methods=["GET", "POST"])
@active_user_required
@render_to("device_edit")
def device_edit(the_device):
    device = logic.get_device(the_device)
    if device is None:
        abort(404)

    perms = logic.get_dev_perms(g.user, device)
    can_edit = perms.admin or (perms.dev_pi and device.active)
    if not can_edit:
        abort(403)

    form = logic.DeviceEditForm(is_admin=perms.admin, obj=device)

    if form.validate_on_submit():
        if logic.update_device(perms.admin, device, form):
            flash(f"{device.label} has been updated")
            return to("device", the_device=the_device)

    return {
        "title": f"edit {device.label}",
        "device": device,
        "action": my_url(),
        "submit": "save",
        "form": form,
        **device_breadcrumb(device),
        **device_subpage_nav(device, perms),
    }


def check_device_tmpl_perms(the_device):
    device = logic.get_device(the_device)
    if device is None:
        abort(404)

    perms = logic.get_dev_perms(g.user, device)
    can_edit = perms.admin or (perms.template and device.active)
    if not can_edit:
        abort(403)

    return device, perms


@app.route("/device/<the_device>/templates", methods=["GET", "POST"])
@active_user_required
@render_to("template_apply")
def device_tmpl(the_device):
    device, _ = check_device_tmpl_perms(the_device)

    templates = logic.templates_of_device(device, archived=False)
    codes = [t.id for t in templates]
    start = logic.get_start_day_of(device)
    chg_by = f"user {g.user.id}"
    warn = ""
    if start is None:
        start = logic.next_sunday()
        warn = f"no templates have been published to {device.label} before, so the start date will be {start}"
    no_templates = ""
    if len(templates) == 0:
        no_templates = f"no templates have been created for { device.label } yet"

    form = logic.TemplateApplyForm(codes)
    if form.validate_on_submit():
        errs = logic.validate_templates_before_application(device, form.templates.data)
        if len(errs) > 0:
            for err in errs:
                flash(err, category="error")
        else:
            logic.process_template_apply(form, device, start, chg_by)
            flash("templates applied")
            return to("device", the_device=device.id, start=start)

    return {
        "title": f"apply templates to {device.label}",
        "action": my_url(),
        "form": form,
        "warn": warn,
        "templates": templates,
        "no_templates": no_templates,
        **template_breadcrumb(device),
        **template_subpage_nav(device),
    }


@app.route("/device/<the_device>/groups", methods=["GET", "POST"])
@active_user_required
@render_to("device_groups")
def device_groups(the_device):
    device = logic.get_device(the_device)
    if device is None:
        abort(404)

    perms = logic.get_dev_perms(g.user, device)
    can_edit = perms.admin or (perms.dev_pi and device.active)
    if not can_edit:
        abort(403)

    related = logic.groups_of_device(device)
    none = ""
    if len(related) == 0:
        none = "no departments are assigned to this device"
    form = logic.get_device_groups_form(related)

    if form.validate_on_submit():
        dept = form.which()
        if dept != "":
            logic.remove_group_from_device(dept, device.id)
            model.db.session.commit()
            return to_form()

    return {
        "title": f"manage departments of {device.label}",
        "device": device,
        "none": none,
        "action": my_url(),
        "form": form,
        **device_breadcrumb(device),
        **device_subpage_nav(device, perms),
    }


@app.route("/device/<the_device>/groups/add", methods=["GET", "POST"])
@active_user_required
@render_to("device_groups_add")
def device_groups_add(the_device):
    device = logic.get_device(the_device)
    if device is None:
        abort(404)

    perms = logic.get_dev_perms(g.user, device)
    can_edit = perms.admin or (perms.dev_pi and device.active)
    if not can_edit:
        abort(403)

    departments = logic.groups_not_of_device(device)
    none = ""
    if len(departments) == 0:
        none = "all departments have been added"
    form = logic.AddGroupToDeviceForm(departments)
    if form.validate_on_submit():
        if logic.process_add_group_to_device_form(device.id, form):
            return to("device_groups", the_device=device.id)

    return {
        "title": f"add department to {device.label}",
        "device": device,
        "none": none,
        "action": my_url(),
        "form": form,
        **device_breadcrumb(device),
        **device_subpage_nav(device, perms),
    }


@app.route("/device/<the_device>/users")
@active_user_required
@render_to("device_users")
def device_users(the_device):
    device = logic.get_device(the_device)
    if device is None:
        abort(404)

    perms = logic.get_dev_perms(g.user, device)
    can_edit = perms.admin or (perms.dev_pi and device.active)
    if not can_edit:
        abort(403)

    active, inactive = logic.get_dev_members_for_device(device)

    return {
        "title": f"manage DEV users of {device.label}",
        "device": device,
        "active": active,
        "inactive": inactive,
        **device_breadcrumb(device),
        **device_subpage_nav(device, perms),
    }


@app.route("/device/<the_device>/users/<the_user>", methods=["GET", "POST"])
@active_user_required
@render_to("device_user")
def device_user(the_device, the_user):
    device = logic.get_device(the_device)
    if device is None:
        abort(404)

    perms = logic.get_dev_perms(g.user, device)
    can_edit = perms.admin or (perms.dev_pi and device.active)
    if not can_edit:
        abort(403)

    dev_user = logic.get_user(the_user)
    if dev_user is None or not dev_user.active:
        abort(404)

    dev, tech = logic.get_dev_tech_status(dev_user)
    if not dev:
        abort(404)

    new, obj = logic.get_user_device_special_perms(dev_user, device)

    form = logic.DeviceUserForm(new, tech, obj=obj)
    if form.validate_on_submit():
        action = form.action()
        if action == "rm":
            model.db.session.delete(obj)
        else:
            form.populate(obj)
            model.db.session.add(obj)
        model.db.session.commit()
        return to("device_users", the_device=device.id)

    title = f"manage {dev_user.id} permissions for {device.label}"
    if new:
        title = f"add {dev_user.id} permissions for {device.label}"
    return {
        "title": title,
        "device": device,
        "dev_user": dev_user,
        "action": my_url(),
        "form": form,
        **device_breadcrumb(device),
        **device_subpage_nav(device, perms),
    }


def template_breadcrumb(
    device: model.Device, tmpl: Optional[model.Template] = None
) -> Breadcrumb_links:
    out = [
        ("devices", url_for("devices")),
        (device.label, url_for("device", the_device=device.id)),
        ("templates", url_for("device_tmpl", the_device=device.id)),
    ]
    if tmpl is not None:
        out.append(
            (
                f"edit {tmpl.label}",
                url_for(
                    "device_tmpl_schedule_edit",
                    the_device=device.id,
                    the_template=tmpl.id,
                ),
            )
        )
    return breadcrumb(*out)


def template_subpage_nav(device: model.Device) -> Subpage_links:
    url = lambda name: url_for(f"device_tmpl{name}", the_device=device.id)
    return subpage_nav(
        "templates",
        [
            (True, "apply", url("")),
            (True, "active", url("_list")),
            (True, "inactive", url("_archive")),
            (True, "add template", url("_add")),
        ],
    )


@app.route("/device/<the_device>/templates/list")
@active_user_required
@render_to("templates_list")
def device_tmpl_list(the_device):
    device, _ = check_device_tmpl_perms(the_device)
    templates = logic.templates_of_device(device, archived=False)
    return {
        "title": f"templates of {device.label}",
        "device": device,
        "templates": templates,
        **template_breadcrumb(device),
        **template_subpage_nav(device),
    }


@app.route("/device/<the_device>/templates/archive")
@active_user_required
@render_to("templates_list")
def device_tmpl_archive(the_device):
    device, _ = check_device_tmpl_perms(the_device)
    templates = logic.templates_of_device(device, archived=True)
    return {
        "title": f"archived templates of {device.label}",
        "device": device,
        "templates": templates,
        **template_breadcrumb(device),
        **template_subpage_nav(device),
    }


@app.route("/device/<the_device>/templates/add", methods=["GET", "POST"])
@active_user_required
@render_to("templates_metadata_edit")
def device_tmpl_add(the_device):
    device, _ = check_device_tmpl_perms(the_device)

    templates = logic.all_templates_of_device(device)
    form = logic.TemplateMetadataForm(device, templates, create=True)
    if form.validate_on_submit():
        ok, id = logic.create_template(form, device)
        if ok:
            return to(
                "device_tmpl_schedule_edit",
                the_device=form.device.id,
                the_template=id,
            )

    return {
        "title": f"add template to {device.label}",
        "device": device,
        "form": form,
        "action": my_url(),
        "submit": "create",
        **template_breadcrumb(device),
        **template_subpage_nav(device),
    }


def template_single_subpage_nav(
    device: model.Device, tmpl: model.Template
) -> Subpage_links:
    entry = lambda lbl, url: (
        True,
        lbl,
        url_for(f"device_tmpl_{url}_edit", the_device=device.id, the_template=tmpl.id),
    )
    return subpage_nav(
        "edit template",
        [
            entry("schedule", "schedule"),
            entry("metadata", "metadata"),
        ],
    )


@app.route(
    "/device/<the_device>/templates/edit/<the_template>", methods=["GET", "POST"]
)
@active_user_required
@render_to("templates")
def device_tmpl_schedule_edit(the_device, the_template):
    device, _ = check_device_tmpl_perms(the_device)
    tmpl = logic.get_template(device, the_template)
    if tmpl is None:
        abort(404)

    entries = logic.get_template_entries(device, tmpl)
    institutes = logic.get_institutes_datalist()
    members_of_groups = logic.all_member_datalists_by_group(device)
    groups = logic.all_groups_of_device(device)
    device_groups_json = [id for (id, _) in groups]
    grouped_entries = logic.group_template_entries(entries)
    colors = logic.all_group_colors()
    hours = logic.fmt_hours()

    form = logic.JsonForm()
    if request.method == "POST":
        if not form.validate():
            # client response must specify payload
            abort(500)
        diffs = form.payload.data["diffs"]

        staged, errors = logic.verify_and_prep_template_diffs(
            diffs, entries, institutes, groups, members_of_groups
        )
        if errors is not None:
            return jsonify({"errors": errors})

        for s in staged:
            model.db.session.add(s)
        model.db.session.commit()
        return jsonify({"saved": len(staged)})

    return {
        "title": f"edit template schedule {device.label}/{tmpl.label}",
        "entries": grouped_entries,
        "institutes": institutes,
        "groups": groups,
        "device_groups_json": device_groups_json,
        "members_of_groups": members_of_groups,
        "colors": colors,
        "hours": hours,
        "form": form,
        **template_breadcrumb(device, tmpl),
        **template_single_subpage_nav(device, tmpl),
    }


@app.route(
    "/device/<the_device>/templates/edit-metadata/<the_template>",
    methods=["GET", "POST"],
)
@active_user_required
@render_to("templates_metadata_edit")
def device_tmpl_metadata_edit(the_device, the_template):
    device, _ = check_device_tmpl_perms(the_device)
    tmpl = logic.get_template(device, the_template)
    if tmpl is None:
        abort(404)

    form = logic.TemplateMetadataForm(device, [], create=False, obj=tmpl)
    if form.validate_on_submit():
        if logic.process_update_template_metadata(form, tmpl):
            return to(
                "device_tmpl_schedule_edit",
                the_device=form.device.id,
                the_template=tmpl.id,
            )

    return {
        "title": f"edit template {device.label}/{tmpl.label}",
        "device": device,
        "template": tmpl,
        "form": form,
        "action": my_url(),
        "submit": "save",
        **template_breadcrumb(device, tmpl),
        **template_single_subpage_nav(device, tmpl),
    }
