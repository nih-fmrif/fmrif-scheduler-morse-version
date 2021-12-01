import ipaddress
from functools import wraps
from typing import Dict, List, Tuple, Union

import click
from flask import Flask, abort, g, redirect, request, session
from flask.helpers import flash, url_for
from flask.templating import render_template
from flask.wrappers import Response
from flask_mail import Mail
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


def active_user(f):
    @wraps(f)
    def protect(*args, **kwargs):
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


## Route helpers


def my_url() -> str:
    route = request.endpoint
    if not isinstance(route, str):
        abort(500)
    kwargs = request.view_args or {}
    return url_for(route, **kwargs)


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


@app.route("/force-login/<token>", methods=["GET"])
def force_login(token):
    user = logic.get_user_from_token(token)
    if user is None:
        abort(400)
    session["user_name"] = user.id
    g.user = user
    return redirect("/")


@app.route("/", methods=["GET"])
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
        return redirect(url_for("home"))
    return {
        "form": form,
        "action": url_for("mailing_lists"),
        **breadcrumb("list action form"),
    }


def join_form_subnav(user: model.User) -> Subpage_links:
    return subpage_nav(
        "Show [which form]",
        [
            (True, "join form", url_for("join_form")),
            (
                logic.show_tech_join_form(g.user),
                "technologist join form",
                url_for("join_form_tech"),
            ),
        ],
    )


@app.route("/join", methods=["GET", "POST"])
@login_required
@in_network_required
@active_user
@render_to("join")
def join_form():
    departments = logic.get_departments_for_join_form(g.user)
    form = logic.JoinForm(departments)
    no_departments = False
    if len(departments) == 0:
        no_departments = True
    if form.validate_on_submit():
        logic.record_join_form(g.user, form.group.data)
        model.db.session.commit()
        logic.notify_group_pi_of_join_form(g.user, form.group.data)
        flash("your membership request is being processed")
        return redirect(url_for("home"))
    return {
        "form": form,
        "action": my_url(),
        "no_departments": no_departments,
        **join_form_subnav(g.user),
        **breadcrumb("join form"),
    }


@app.route("/join/tech", methods=["GET", "POST"])
@login_required
@in_network_required
@active_user
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
        return redirect(url_for("home"))
    return {
        **join_form_subnav(g.user),
        **breadcrumb(("join form", url_for("join_form")), "technologist join form"),
    }


@app.route("/join/approve/<token>", endpoint="join-group-approve", methods=["GET"])
@app.route("/join/deny/<token>", endpoint="join-group-deny", methods=["GET"])
@login_required
@active_user
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

    to_home = redirect(url_for("home"))

    # make sure the request is unprocessed
    req = logic.get_join_request(u, grp)
    if req is None:
        flash("this request was previously denied")
        return to_home

    if req.approved is not None:
        flash("this request was previously approved")
        return to_home

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

    return to_home


def groups_subpage_nav(is_admin: bool) -> Subpage_links:
    return subpage_nav(
        "Show [which groups]",
        [
            (True, "active [groups]", url_for("groups")),
            (
                is_admin,
                "inactive [groups]",
                url_for("groups-inactive"),
            ),
            (is_admin, "new group", url_for("group_add")),
        ],
    )


def groups_breadcrumb() -> Breadcrumb_links:
    return breadcrumb(("groups", url_for("groups")))


@app.route("/groups", methods=["GET"])
@app.route("/groups/inactive", endpoint="groups-inactive", methods=["GET"])
@login_required
@active_user
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
    institutes = logic.get_institutes_for_group_edit_form()
    form = logic.GroupEditForm(institutes, is_admin=True, create=True)

    if form.validate_on_submit():
        if logic.create_group(form):
            flash("new group added")
            return redirect(url_for("group", the_group=form.id.data))

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
        "Show",
        [
            # view has further protections, but if you can see any of them you can see it
            (True, f"view [{group.label}]", url_for("group", the_group=group.id)),
            (
                can_edit,
                f"edit [{group.label}]",
                url_for("group_edit", the_group=group.id),
            ),
            # TODO membership
        ],
    )


def group_breadcrumb(group: model.Group) -> Breadcrumb_links:
    return breadcrumb(
        ("groups", url_for("groups")),
        (group.label, url_for("group", the_group=group.id)),
    )


@app.route("/group/<the_group>")
@login_required
@active_user
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
@login_required
@active_user
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
        institutes = logic.get_institutes_for_group_edit_form()
    form = logic.GroupEditForm(institutes, is_admin=is_admin, obj=group)

    if form.validate_on_submit():
        if logic.update_group(is_admin, group, form):
            flash(f"{group.label} has been updated")
            return redirect(url_for("group", the_group=the_group))

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


@app.route("/devices", methods=["GET"])
@app.route("/devices/inactive", endpoint="devices-inactive", methods=["GET"])
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
        **subpage_nav(
            "Show [which devices]",
            [
                (True, "active [devices]", url_for("devices")),
                (
                    is_admin,
                    "inactive [devices]",
                    url_for("devices-inactive"),
                ),
            ],
        ),
        **breadcrumb(title),
    }


@app.route("/device/<device>")
@login_required
@render_to("device")
def device(device):
    # TODO just need this placeholder route
    return {}
