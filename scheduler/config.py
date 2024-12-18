# config.py
import ipaddress
import json
import os
from typing import Any, Dict, Optional

def env(s: str) -> str:
    return os.environ[s]

def env_or(s: str, default: str) -> str:
    return os.environ.get(s, default)

def bool_env(s: str) -> bool:
    return env_or(s, "").lower() not in ("", "false")

def basic_settings(debug: bool) -> Dict[str, Any]:
    cfg: Dict[str, Any] = {}
    cfg.update(
        SERVER_NAME=env("MMSCHED_SERVER_NAME"),
        # config for Flask-Mail
        MAIL_SERVER=env_or("MMSCHED_MAIL_SERVER", "localhost"),
        MAIL_PORT=int(env_or("MMSCHED_MAIL_PORT", "25")),
        MAIL_USE_TLS=bool_env("MMSCHED_MAIL_USE_TLS"),
        MAIL_USE_SSL=bool_env("MMSCHED_MAIL_USE_SSL"),
        MAIL_USERNAME=env("MMSCHED_MAIL_USERNAME"),
        MAIL_PASSWORD=env("MMSCHED_MAIL_PASSWORD"),
        # config for Flask-SQLAlchemy
        SQLALCHEMY_DATABASE_URI=env("MMSCHED_DB_URL"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        # config for Flask-Session
        SESSION_COOKIE_NAME="dsid",
        PERMANENT_SESSION_LIFETIME=8 * 60 * 60,  # 8 hours in seconds
        SESSION_TYPE="sqlalchemy",
        SESSION_USE_SIGNER=True,
        SESSION_SQLALCHEMY_TABLE="site_sessions",
        #-------------------------------------------------------------------------------------------------------
        # Superuser mode configuration
        SUPERUSER_MODE=bool_env("MMSCHED_SUPERUSER_MODE")
        #-------------------------------------------------------------------------------------------------------
    )

    # only set if APPLICATION_ROOT iff there is a nonempty value
    root = env_or("MMSCHED_APPLICATION_ROOT", "")
    if root != "":
        cfg["APPLICATION_ROOT"] = root

    if debug:
        cfg.update(
            SQLALCHEMY_ECHO=True,
            MAIL_SUPPRESS_SEND=True,
        )
    else:
        cfg.update(
            SESSION_COOKIE_SECURE=True,  # no https on dev server
            PREFERRED_URL_SCHEME="https",
        )

    return cfg

# Rest of the file remains unchanged...


def proxy_count() -> Optional[Dict[str, int]]:
    total, count = 0, {
        "For": 0,
        "Proto": 0,
        "Host": 0,
        "Port": 0,
        "Prefix": 0,
    }

    for ev in count.keys():
        nm = f"MMSCHED_X_FORWARDED_{ev.upper()}"
        n = int(os.environ.get(nm, 0))
        if n < 0:
            raise Exception(f"{nm} must be nonnegative integer")
        total += n
        count[ev] = n

    if total > 0:
        return {
            "x_for": count["For"],
            "x_proto": count["Proto"],
            "x_host": count["Host"],
            "x_port": count["Port"],
            "x_prefix": count["Prefix"],
        }

    return None


def load_user_settings(debug: bool, resource) -> Dict[str, Any]:
    # we let any error here crash the app as these all must be set
    out: Dict[str, Any] = {}
    cfg = json.loads(resource.read())
    if not isinstance(cfg, dict):
        raise Exception("config.json needs to be {}")
    if len(cfg) != 6:
        raise Exception("config.json unexpected number of keys, must be 6")

    key = cfg["secret_key"]
    if not isinstance(key, str):
        raise Exception("config.json: secret_key must be string")
    if key == "":
        raise Exception("config.json: secret key must not be empty")
    out["SECRET_KEY"] = key

    # get NIH subnets for checking that remote addr is in the network
    netspec = cfg["nih_networks"]
    if not isinstance(netspec, list):
        raise Exception("config.json: nih_networks needs to be []")
    if len(netspec) == 0:
        raise Exception("config.json: nih_network cannot be empty")
    subnets = [ipaddress.ip_network(sn) for sn in netspec]
    if debug:  # allow localhost in debug mode
        subnets.append(ipaddress.ip_network("127.0.0.1"))
    out["nih_networks"] = subnets

    login_prefix = cfg["siteminder_login_url_prefix"]
    if not isinstance(login_prefix, str):
        raise Exception("config.json: siteminder_login_url_prefix must be string")
    out["SM_LOGIN_URL_PREFIX"] = login_prefix

    sender = cfg["site_default_sender"]
    if not isinstance(sender, str):
        raise Exception("config.json: site_default_sender must be string")
    if "@" not in sender:
        raise Exception("config.json: site_default_sender must be valid email address")
    out["MAIL_DEFAULT_SENDER"] = sender

    ls_addr = cfg["listserv"]
    if not isinstance(ls_addr, str):
        raise Exception("config.json: listserv must be string")
    if "@" not in ls_addr:
        raise Exception("config.json: listserv must be valid email address")
    out["nih_listserv"] = ls_addr

    ml = cfg["mailing_lists"]
    if not isinstance(ml, dict):
        raise Exception("config.js: mailing_lists must be {}")
    for v in ml.values():
        if not isinstance(v, str):
            raise Exception(
                'config.js: mailing_list entries must be "name": "description" pairs'
            )
    out["nih_mailing_lists"] = ml

    return out
