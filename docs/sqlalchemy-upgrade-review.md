# SQLAlchemy Upgrade Review

Date: 2026-03-19
Repo state reviewed: `60c9196` (`Adopt explicit SQLAlchemy mapped annotations`)

## Question

Is it worth putting real effort into a clean SQLAlchemy 2.x upgrade here, and what would that effort likely buy us?

## Short Answer

Yes, but I would not treat it as "just bump SQLAlchemy".

The worthwhile part is not only SQLAlchemy 2.x itself. The bigger payoff is reducing the current split between:

- local Pixi / `pyproject.toml` pins: Flask 2.0.3, Flask-SQLAlchemy 2.5.1, SQLAlchemy 1.4.54, Werkzeug 2.0.3
- Debian 12 runtime packages already implied by `Dockerfile.debian-runtime`: Flask 2.2.2, Flask-SQLAlchemy 3.0.3, SQLAlchemy 1.4.46
- Debian 13 packages: Flask 3.1.1, Flask-SQLAlchemy 3.1.1, SQLAlchemy 2.0.40

That version skew is already large enough that "stay where we are" is not really a stable long-term choice. The ORM annotation work just landed in `scheduler/model.py` removes one of the cleanest blockers, but a real upgrade still has application and test-surface cost.

My recommendation is:

1. Do the upgrade, because it improves packaging parity and future maintenance.
2. Do it in stages, not as a single "SQLAlchemy 2 everywhere" jump.
3. Treat Flask / Flask-SQLAlchemy / Werkzeug alignment as part of the same project.

## Current State

### Local development pins

`pyproject.toml` currently pins:

- Flask 2.0.3
- Flask-SQLAlchemy 2.5.1
- SQLAlchemy 1.4.54
- Werkzeug 2.0.3

This is an old stack and it is internally consistent, but it no longer matches the Debian runtime story.

### Debian runtime story

`Dockerfile.debian-runtime` installs distro packages, not the versions from `pyproject.toml`.

On official Debian package pages as of 2026-03-19:

- Debian 12 / bookworm ships Flask 2.2.2, Flask-SQLAlchemy 3.0.3, SQLAlchemy 1.4.46
- Debian 13 / trixie ships Flask 3.1.1, Flask-SQLAlchemy 3.1.1, SQLAlchemy 2.0.40

So the repo already has a real compatibility matrix problem:

- local dev is older than Debian 12
- Debian 12 is newer Flask-SQLAlchemy than local dev
- Debian 13 is fully in SQLAlchemy 2 territory

### What just improved

The recent model change replaced the temporary `__allow_unmapped__` bridge with explicit `Mapped[...]` annotations in `scheduler/model.py`.

That matters because SQLAlchemy's 2.0 migration guide positions `__allow_unmapped__` as a compatibility step for explicitly typed legacy models, not the end state. The current model file is now much closer to the 2.x declarative style while still working on 1.4.

## Repo-Grounded Migration Surface

These are the numbers that matter for this codebase right now:

- `167` references to the legacy `.query` interface across `scheduler/` and `tests/`
- `17` references to `session.query(...)`
- `394` direct `db.session` references
- `1` direct `create_scoped_session` usage in the unit test harness
- `1` explicit `FLASK_ENV` usage in `scheduler/app.py`

What I take from that:

- the repo is not using a tiny SQLAlchemy surface
- there is still a lot of legacy query style, but most of it is not an immediate 2.0 hard blocker
- the bigger practical risk is framework integration and session lifecycle behavior, not only ORM syntax

## What Is Already Fine For SQLAlchemy 2.x

These items look good or at least acceptable:

- Mapped model attributes are now explicit in `scheduler/model.py`
- there are no remaining `Query.get(...)` call sites in the repo
- Flask-SQLAlchemy 3.1 still documents the legacy `Model.query` interface as supported, even though it is legacy
- string SQL already goes through `scheduler.model.execute()`, which wraps raw strings in `sql_text(...)`
- the existing unit and route suites passed after the model annotation change

This means the repo is not starting from a bad place. The likely migration is real work, but not a rewrite.

## Main Upgrade Benefits

### 1. Better environment parity

This is the strongest reason to do it.

Right now the dev lockfile story and the Debian runtime story diverge enough that bugs can hide in version gaps. Upgrading reduces the chance that local tests pass on one framework stack while deployment runs another.

### 2. Cleaner forward compatibility

SQLAlchemy 1.4 is explicitly documented as the legacy line. Staying on it is workable for a while, but it means every future ORM-facing change has to be made with one eye on an older compatibility layer.

### 3. Less ambiguity in ORM behavior

The recent annotation cleanup is part of this. SQLAlchemy 2.x is stricter in useful ways, and the repo now gets more value from that strictness than pain.

### 4. Easier Debian 13 support story

If Debian 13 matters operationally, eventually you either:

- upgrade intentionally in the repo, or
- let distro packaging force the issue indirectly

The first option is easier to control.

## Main Costs And Risks

### 1. This is a framework-stack upgrade, not only an ORM upgrade

Moving to Flask-SQLAlchemy 3.1 means moving into:

- Flask-SQLAlchemy 3.x behavior
- SQLAlchemy 2.x
- newer Flask
- newer Werkzeug

That expands the test surface beyond ORM calls.

### 2. Flask-SQLAlchemy 3.x changes app/session expectations

The Flask-SQLAlchemy 3.0 changelog says:

- session is scoped to the current app context instead of the thread
- an active app context is always required to access `session` and `engine`

This repo already uses app contexts correctly in many places, but the test harness directly manipulates `model.db.session` and uses `create_scoped_session()` in `tests/unit/conftest.py`. I would expect some test-harness churn here.

### 3. There is still a large legacy query surface

`Model.query` is not a hard blocker because Flask-SQLAlchemy still supports it as a legacy interface, but it is technical debt that will keep showing up in review and future upgrades. If the team wants "fully modern SQLAlchemy style", that is a second project after the version bump.

### 4. There is at least one known Flask cleanup item

`scheduler/app.py` still sets `FLASK_ENV`. Flask 2.3 removed:

- `FLASK_ENV`
- `app.env`
- `before_first_request`
- `json_encoder` / `json_decoder`

This repo does not appear to use most of those removed APIs, which is good, but `FLASK_ENV` is a real cleanup item.

## Effort Estimate

These are rough engineering estimates, not promises.

### Option A: Minimal parity step

Goal:

- move local dev from Flask 2.0 / Flask-SQLAlchemy 2.5 to Debian-12-like versions
- keep SQLAlchemy on 1.4 for one more step

Expected work:

- update dependency pins
- fix Flask 2.2 / Werkzeug 2.2+ issues
- adjust any test harness assumptions around app/session context

Estimate:

- 0.5 to 1.5 days

Pros:

- lower risk
- closes the local-vs-Debian-12 mismatch
- isolates Flask-SQLAlchemy 3.x behavior changes from SQLAlchemy 2.x behavior changes

Cons:

- still leaves the actual SQLAlchemy 2 jump for later
- still not Debian-13 parity

### Option B: Full SQLAlchemy 2 / Debian-13 parity step

Goal:

- align with Flask 3.1.x
- align with Flask-SQLAlchemy 3.1.x
- align with SQLAlchemy 2.0.x

Expected work:

- dependency pin updates
- fix `FLASK_ENV` usage
- validate app-context-dependent DB access
- repair any breakage from Flask / Werkzeug removals
- re-run unit, route, and likely integration suites

Estimate:

- 2 to 5 days

Pros:

- one deliberate upgrade instead of repeated partial churn
- strong parity with Debian 13
- better long-term maintenance position

Cons:

- more simultaneous moving parts
- more likely to create unrelated-looking breakage in tests and auth/session behavior

### Option C: Full version upgrade plus query-style modernization

Goal:

- do Option B
- also reduce or replace most legacy `Model.query` and `session.query(...)` usage with `select(...)` / `session.execute(...)`

Estimate:

- 1 to 2 weeks depending on how broad the cleanup is expected to be

Pros:

- best long-term code health
- least future friction from SQLAlchemy legacy APIs

Cons:

- much larger review surface
- higher regression risk
- not necessary to get onto SQLAlchemy 2.x

## Recommendation

I would spend the effort, but I would not do Option C immediately.

The best tradeoff here looks like:

1. Upgrade local dev to the Flask-SQLAlchemy 3 line and close the Debian mismatch.
2. Move to SQLAlchemy 2.x in the same project only if the app/test harness stays stable in step 1.
3. Leave broad query modernization for follow-up work once the version upgrade is settled.

If schedule is tight, I would still do at least Option A. The current dependency split is wide enough that it is already a maintenance risk.

If the real target is Debian 13 compatibility, I would go straight to Option B and accept that it is a small project, not a patch.

## Suggested Upgrade Plan

### Phase 1

- update `pyproject.toml` pins to a Flask-SQLAlchemy 3-compatible stack
- remove `FLASK_ENV` usage from `scheduler/app.py`
- run `pixi run test-unit`, `pixi run test-routes`, and targeted integration smoke

Exit criteria:

- local stack behaves like Debian 12 or newer
- no harness issues from app-context/session changes

### Phase 2

- move SQLAlchemy to 2.0.x and Flask-SQLAlchemy to 3.1.x
- run with `SQLALCHEMY_WARN_20=1` during validation
- fix any remaining RemovedIn20-style behavior issues

Exit criteria:

- unit and route suites pass cleanly
- no SQLAlchemy 2 migration warnings in the exercised paths

### Phase 3

- gradually replace high-churn `Model.query` and `session.query(...)` call sites with `select(...)` patterns
- prioritize hot paths and code that is already being edited for feature work

Exit criteria:

- no large, forced migration later
- future ORM changes happen on 2.x-native patterns

## Sources

Official dependency and migration notes used for this review:

- SQLAlchemy 2.0 migration guide: <https://docs.sqlalchemy.org/en/20/changelog/migration_20.html>
- SQLAlchemy 1.4 typing / `Mapped[...]` guidance: <https://docs.sqlalchemy.org/en/14/orm/extensions/mypy.html>
- Flask-SQLAlchemy changes: <https://flask-sqlalchemy.palletsprojects.com/en/stable/changes/>
- Flask-SQLAlchemy legacy query interface: <https://flask-sqlalchemy.palletsprojects.com/en/stable/legacy-query/>
- Flask changes: <https://flask.palletsprojects.com/en/stable/changes/>
- Debian bookworm package pages:
  - <https://packages.debian.org/bookworm/python3-flask>
  - <https://packages.debian.org/bookworm/python3-flask-sqlalchemy>
  - <https://packages.debian.org/bookworm/python3-sqlalchemy>
- Debian trixie package pages:
  - <https://packages.debian.org/trixie/python3-flask>
  - <https://packages.debian.org/trixie/python3-flask-sqlalchemy>
  - <https://packages.debian.org/trixie/python3-sqlalchemy>
