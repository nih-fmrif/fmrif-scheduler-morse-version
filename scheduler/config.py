"""
Application configuration management.

This module provides two main configuration interfaces:
1. AppConfig: Settings loaded directly into Flask app.config
2. Settings: Global application settings used throughout the codebase

The separation allows for clear distinction between Flask-specific config and
general application settings while maintaining a single source of truth.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import SplitResult, quote, urlsplit, urlunsplit

from dotenv import dotenv_values
from email_validator import EmailNotValidError, validate_email

from scheduler.find_env_file import find_envfile

logger = logging.getLogger(__name__)

# Load environment variables
env_file = find_envfile()
logger.info(f"Loading .env from: {env_file}")

PLACEHOLDER_UUID = "00000000-0000-0000-0000-000000000000"
APP_ENV_DEFAULT = "development"
PRODUCTION_ENVIRONMENTS = {"prod", "production", "stage", "staging"}
DEVELOPMENT_ENVIRONMENTS = {"dev", "development", "local", "test", "testing"}
AUTH_CALLBACK_PATH = "/auth/callback"
_NESTED_SETTING_NAMES = frozenset(
    {
        "core",
        "server",
        "database",
        "mail",
        "session",
        "security",
        "logging",
        "entra",
        "auth_test",
    }
)


def normalize_app_env(value: str | None) -> str:
    normalized = (value or APP_ENV_DEFAULT).strip().lower().replace("-", "_")
    if normalized in {"", "dev"}:
        return "development"
    if normalized in PRODUCTION_ENVIRONMENTS:
        return "production"
    if normalized in DEVELOPMENT_ENVIRONMENTS:
        return "development"
    return normalized


def _is_mailpit_configured_for(env: str, mail_server: str) -> bool:
    if env != "production":
        return False
    if mail_server.strip().lower() == "mailpit":
        return True
    mailpit_variables = ("MAILPIT__PORT", "MAILPIT__SMTP_PORT", "MAILPIT_API_BASE_URL")
    return any(
        var in os.environ and str(os.environ.get(var, "")).strip()
        for var in mailpit_variables
    )


def parse_entra_redirect_uri(value: str) -> SplitResult:
    redirect_uri = value.strip()
    if not redirect_uri:
        raise ValueError("ENTRA__REDIRECT_URI must not be empty")

    parsed = urlsplit(redirect_uri)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(
            "ENTRA__REDIRECT_URI must be an absolute http(s) URL ending with "
            f"{AUTH_CALLBACK_PATH}"
        )

    if parsed.path != AUTH_CALLBACK_PATH:
        raise ValueError(
            f"ENTRA__REDIRECT_URI must use the root callback path {AUTH_CALLBACK_PATH}"
        )

    return parsed


def derive_entra_edge_base_url(value: str) -> str:
    parsed = parse_entra_redirect_uri(value)
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    raise ValueError(f"Invalid boolean value: {value!r}")


def _coerce_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a valid integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a valid integer") from exc


def _coerce_nonnegative_int(value: Any, field_name: str) -> int:
    parsed = _coerce_int(value, field_name)
    if parsed < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return parsed


def _coerce_positive_int(value: Any, field_name: str) -> int:
    parsed = _coerce_int(value, field_name)
    if parsed <= 0:
        raise ValueError(f"{field_name} must be greater than 0")
    return parsed


def _coerce_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def normalize_email_address(value: Any, *, field_name: str) -> str:
    text = _coerce_str(value).strip()
    if not text:
        raise ValueError(f"{field_name} must be a valid email address")
    try:
        validated = validate_email(text, check_deliverability=False)
    except EmailNotValidError as exc:
        raise ValueError(f"{field_name} must be a valid email address") from exc
    normalized = getattr(validated, "normalized", None) or getattr(
        validated, "email", None
    )
    if not normalized:
        raise ValueError(f"{field_name} must be a valid email address")
    return str(normalized)


def _normalize_optional_email(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    text = _coerce_str(value).strip()
    if not text:
        return None
    return normalize_email_address(text, field_name=field_name)


def _coerce_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        normalized = value.strip()
        if normalized == "":
            return []
        if normalized.startswith("["):
            parsed = json.loads(normalized)
            if not isinstance(parsed, list):
                raise ValueError("Expected a JSON list")
            return [_coerce_str(item) for item in parsed]
        return [item.strip() for item in normalized.split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [
            _coerce_str(item).strip() for item in value if _coerce_str(item).strip()
        ]
    raise ValueError(f"Expected a list-like value, got {type(value).__name__}")


def _coerce_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        normalized = value.strip()
        if normalized == "":
            return {}
        try:
            parsed = json.loads(normalized)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field_name} must be valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"{field_name} must be a JSON object")
        return {str(key): item for key, item in parsed.items()}
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    raise ValueError(f"{field_name} must be a mapping")


def _deep_merge(target: dict[str, Any], source: Mapping[str, Any]) -> None:
    for key, value in source.items():
        if (
            key in target
            and isinstance(target[key], dict)
            and isinstance(value, Mapping)
        ):
            _deep_merge(target[key], value)
        else:
            target[key] = value


def _set_nested_value(target: dict[str, Any], path: list[str], value: Any) -> None:
    current = target
    for part in path[:-1]:
        next_value = current.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[path[-1]] = value


def _load_env_file_values(path: str | os.PathLike[str] | None) -> dict[str, str]:
    if path is None:
        return {}
    env_path = Path(path)
    if not env_path.is_file():
        return {}
    parsed = dotenv_values(env_path)
    return {
        str(key): str(value)
        for key, value in parsed.items()
        if key is not None and value is not None
    }


def _raw_values_from_env(source: Mapping[str, str]) -> dict[str, Any]:
    raw: dict[str, Any] = {}
    for key, value in source.items():
        if key == "APP_ENV":
            raw["app_env"] = value
            continue
        if key in {"PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE"}:
            raw[key] = value
            continue
        if "__" not in key:
            continue
        parts = key.split("__")
        root = parts[0].lower()
        if root not in _NESTED_SETTING_NAMES:
            continue
        path = [root] + [part.lower() for part in parts[1:]]
        if path == ["database", "idle_in_transaction_session_timeout_ms"]:
            path[-1] = "idle_in_transaction_timeout_ms"
        elif path == ["database", "startup_check_enabled"]:
            path[-1] = "startup_check"
        _set_nested_value(raw, path, value)
    return raw


def _normalize_explicit_values(values: Mapping[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in values.items():
        if key == "_env_file":
            continue
        if key == "APP_ENV":
            normalized["app_env"] = value
            continue
        if key == "app_env":
            normalized["app_env"] = value
            continue
        if key in {"PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE"}:
            normalized[key] = value
            continue
        if key in _NESTED_SETTING_NAMES:
            if is_dataclass(value):
                normalized[key] = asdict(value)
            elif isinstance(value, Mapping):
                normalized[key] = dict(value)
            else:
                raise ValueError(f"{key} must be provided as a mapping")
    return normalized


def _instantiate_section(section_cls: type[Any], value: Any) -> Any:
    if isinstance(value, section_cls):
        return value
    if value is None:
        return section_cls()
    if not isinstance(value, Mapping):
        raise ValueError(f"{section_cls.__name__} must be provided as a mapping")
    allowed = {field_def.name for field_def in fields(section_cls)}
    filtered = {key: item for key, item in value.items() if key in allowed}
    return section_cls(**filtered)


@dataclass
class EntraConfig:
    """Microsoft Entra / Azure AD application configuration."""

    client_id: str = ""
    tenant_id: str = ""
    client_secret: str = ""
    discovery_url: str = ""
    redirect_uri: str = ""
    allowed_audiences: List[str] = field(default_factory=list)
    allowed_algorithms: List[str] = field(default_factory=lambda: ["RS256"])
    bearer_auto_provision_enabled: bool = False
    bearer_auto_provision_domains: List[str] = field(default_factory=list)
    bearer_auto_provision_groups: List[str] = field(default_factory=list)
    scope: str = "openid profile email offline_access"
    jwks_cache_ttl: int = 60 * 60

    def __post_init__(self) -> None:
        self.client_id = _coerce_str(self.client_id)
        self.tenant_id = _coerce_str(self.tenant_id)
        self.client_secret = _coerce_str(self.client_secret)
        self.discovery_url = _coerce_str(self.discovery_url)
        self.redirect_uri = _coerce_str(self.redirect_uri).strip()
        self.allowed_audiences = [
            item
            for item in (
                _coerce_str(v).strip()
                for v in _coerce_string_list(self.allowed_audiences)
            )
            if item
        ]
        self.allowed_algorithms = self._normalize_allowed_algorithms(
            _coerce_string_list(self.allowed_algorithms)
        )
        self.bearer_auto_provision_enabled = _coerce_bool(
            self.bearer_auto_provision_enabled
        )
        self.bearer_auto_provision_domains = self._normalize_domains(
            _coerce_string_list(self.bearer_auto_provision_domains)
        )
        self.bearer_auto_provision_groups = self._normalize_groups(
            _coerce_string_list(self.bearer_auto_provision_groups)
        )
        self.scope = _coerce_str(self.scope)
        self.jwks_cache_ttl = _coerce_int(self.jwks_cache_ttl, "ENTRA__JWKS_CACHE_TTL")
        if self.redirect_uri:
            parse_entra_redirect_uri(self.redirect_uri)

    @staticmethod
    def _normalize_allowed_algorithms(value: list[str]) -> list[str]:
        normalized: list[str] = []
        for alg in value:
            token = _coerce_str(alg).strip().upper()
            if token and token not in normalized:
                normalized.append(token)
        if not normalized:
            raise ValueError(
                "ENTRA__ALLOWED_ALGORITHMS must include at least one value"
            )
        return normalized

    @staticmethod
    def _normalize_domains(value: list[str]) -> list[str]:
        normalized: list[str] = []
        for domain in value:
            token = _coerce_str(domain).strip().lower().lstrip("@")
            if token and token not in normalized:
                normalized.append(token)
        return normalized

    @staticmethod
    def _normalize_groups(value: list[str]) -> list[str]:
        normalized: list[str] = []
        for group in value:
            token = _coerce_str(group).strip().lower()
            if token and token not in normalized:
                normalized.append(token)
        return normalized

    @property
    def issuer(self) -> str:
        if not self.tenant_id:
            return ""
        return f"https://login.microsoftonline.com/{self.tenant_id}/v2.0"

    @property
    def audiences(self) -> List[str]:
        audiences = [aud for aud in self.allowed_audiences if aud]
        if self.client_id and self.client_id not in audiences:
            audiences.append(self.client_id)
        api_audience = f"api://{self.client_id}" if self.client_id else ""
        if api_audience and api_audience not in audiences:
            audiences.append(api_audience)
        return audiences

    @property
    def edge_base_url(self) -> str:
        if not self.redirect_uri:
            return ""
        return derive_entra_edge_base_url(self.redirect_uri)


@dataclass
class DatabaseConfig:
    echo: bool = False
    track_modifications: bool = False
    pool_size: int = 5
    max_overflow: int = 10
    pool_timeout: int = 30
    pool_recycle: int = 1800
    connect_timeout: int = 10
    statement_timeout_ms: int = 60000
    lock_timeout_ms: int = 10000
    idle_in_transaction_timeout_ms: int = 60000
    application_name: str = "fmrif-scheduler"
    slow_query_threshold_ms: int = 500
    startup_check: bool = True

    def __post_init__(self) -> None:
        self.echo = _coerce_bool(self.echo)
        self.track_modifications = _coerce_bool(self.track_modifications)
        self.pool_size = _coerce_positive_int(self.pool_size, "DATABASE__POOL_SIZE")
        self.max_overflow = _coerce_nonnegative_int(
            self.max_overflow, "DATABASE__MAX_OVERFLOW"
        )
        self.pool_timeout = _coerce_positive_int(
            self.pool_timeout, "DATABASE__POOL_TIMEOUT"
        )
        self.pool_recycle = _coerce_positive_int(
            self.pool_recycle, "DATABASE__POOL_RECYCLE"
        )
        self.connect_timeout = _coerce_positive_int(
            self.connect_timeout, "DATABASE__CONNECT_TIMEOUT"
        )
        self.statement_timeout_ms = _coerce_nonnegative_int(
            self.statement_timeout_ms, "DATABASE__STATEMENT_TIMEOUT_MS"
        )
        self.lock_timeout_ms = _coerce_nonnegative_int(
            self.lock_timeout_ms, "DATABASE__LOCK_TIMEOUT_MS"
        )
        self.idle_in_transaction_timeout_ms = _coerce_nonnegative_int(
            self.idle_in_transaction_timeout_ms,
            "DATABASE__IDLE_IN_TRANSACTION_TIMEOUT_MS",
        )
        self.application_name = _coerce_str(self.application_name).strip()
        if not self.application_name:
            raise ValueError("DATABASE__APPLICATION_NAME must not be empty")
        self.slow_query_threshold_ms = _coerce_nonnegative_int(
            self.slow_query_threshold_ms, "DATABASE__SLOW_QUERY_THRESHOLD_MS"
        )
        self.startup_check = _coerce_bool(self.startup_check)

    @property
    def connect_args(self) -> dict[str, Any]:
        options = [
            f"-c statement_timeout={self.statement_timeout_ms}",
            f"-c lock_timeout={self.lock_timeout_ms}",
            (
                "-c idle_in_transaction_session_timeout="
                f"{self.idle_in_transaction_timeout_ms}"
            ),
            f"-c application_name={self.application_name}",
        ]
        return {
            "connect_timeout": self.connect_timeout,
            "options": " ".join(options),
        }

    @property
    def sqlalchemy_engine_options(self) -> dict[str, Any]:
        return {
            "pool_size": self.pool_size,
            "max_overflow": self.max_overflow,
            "pool_timeout": self.pool_timeout,
            "pool_recycle": self.pool_recycle,
            "pool_pre_ping": True,
            "connect_args": self.connect_args,
            "pool_reset_on_return": "rollback",
        }

    @property
    def engine_options(self) -> Dict[str, Any]:
        return self.sqlalchemy_engine_options

    @property
    def idle_in_transaction_session_timeout_ms(self) -> int:
        return self.idle_in_transaction_timeout_ms

    @property
    def startup_check_enabled(self) -> bool:
        return self.startup_check


@dataclass
class CoreConfig:
    """Core application settings"""

    debug: bool = True
    secret_key: str = "dev-key-change-in-prod"
    listserv: str = "listserv@example.com"

    def __post_init__(self) -> None:
        self.debug = _coerce_bool(self.debug)
        self.secret_key = _coerce_str(self.secret_key)
        self.listserv = _coerce_str(self.listserv)


@dataclass
class ServerConfig:
    """Server configuration settings"""

    server_name: str = ""

    def __post_init__(self) -> None:
        self.server_name = _coerce_str(self.server_name)


@dataclass
class MailConfig:
    """Email server configuration"""

    server: str = "localhost"
    port: int = 25
    use_tls: bool = False
    use_ssl: bool = False
    username: str = ""
    password: str = ""
    suppress_send: bool = False
    default_sender: Optional[str] = None
    mailing_lists: Dict[str, str] = field(
        default_factory=lambda: {
            "list 1": "Description of list 1",
            "list 2": "Description of list 2",
        }
    )

    def __post_init__(self) -> None:
        self.server = _coerce_str(self.server)
        self.port = _coerce_int(self.port, "MAIL__PORT")
        self.use_tls = _coerce_bool(self.use_tls)
        self.use_ssl = _coerce_bool(self.use_ssl)
        self.username = _coerce_str(self.username)
        self.password = _coerce_str(self.password)
        self.suppress_send = _coerce_bool(self.suppress_send)
        self.default_sender = _normalize_optional_email(
            self.default_sender, field_name="MAIL__DEFAULT_SENDER"
        )
        self.mailing_lists = {
            _coerce_str(key): _coerce_str(value)
            for key, value in _coerce_mapping(
                self.mailing_lists, "MAIL__MAILING_LISTS"
            ).items()
        }


@dataclass
class SessionConfig:
    """Flask session configuration"""

    cookie_name: str = "dsid"
    cookie_secure: bool = True
    cookie_httponly: bool = True
    cookie_samesite: str = "Strict"
    permanent_lifetime: int = 8 * 60 * 60
    type: str = "sqlalchemy"
    sqlalchemy_table: str = "site_sessions"

    def __post_init__(self) -> None:
        self.cookie_name = _coerce_str(self.cookie_name)
        self.cookie_secure = _coerce_bool(self.cookie_secure)
        self.cookie_httponly = _coerce_bool(self.cookie_httponly)
        self.cookie_samesite = self._normalize_cookie_samesite(self.cookie_samesite)
        self.permanent_lifetime = _coerce_int(
            self.permanent_lifetime, "SESSION__PERMANENT_LIFETIME"
        )
        self.type = _coerce_str(self.type)
        self.sqlalchemy_table = _coerce_str(self.sqlalchemy_table)

    @staticmethod
    def _normalize_cookie_samesite(value: Any) -> str:
        normalized = _coerce_str(value).strip().lower()
        allowed = {"strict", "lax", "none"}
        if normalized not in allowed:
            raise ValueError(
                "SESSION__COOKIE_SAMESITE must be one of: Strict, Lax, None"
            )
        return normalized.capitalize()


@dataclass
class SecurityConfig:
    """Baseline HTTP response header settings."""

    enable_hsts: bool = True
    hsts_max_age: int = 63072000
    hsts_include_subdomains: bool = True
    hsts_preload: bool = False
    frame_options: str = "DENY"
    content_type_options: str = "nosniff"
    referrer_policy: str = "strict-origin-when-cross-origin"
    enable_csp: bool = True
    csp_report_only: bool = False
    csp_policy: str = (
        "default-src 'self'; "
        "script-src 'self' 'nonce-{nonce}' 'strict-dynamic'; "
        "script-src-attr 'none'; "
        "style-src 'self'; "
        "style-src-attr 'none'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    )
    auth_rate_limit_enabled: bool = True
    auth_rate_limit_window_seconds: int = 60
    auth_rate_limit_max_requests: int = 30

    def __post_init__(self) -> None:
        self.enable_hsts = _coerce_bool(self.enable_hsts)
        self.hsts_max_age = _coerce_int(self.hsts_max_age, "SECURITY__HSTS_MAX_AGE")
        self.hsts_include_subdomains = _coerce_bool(self.hsts_include_subdomains)
        self.hsts_preload = _coerce_bool(self.hsts_preload)
        self.frame_options = _coerce_str(self.frame_options)
        self.content_type_options = _coerce_str(self.content_type_options)
        self.referrer_policy = _coerce_str(self.referrer_policy)
        self.enable_csp = _coerce_bool(self.enable_csp)
        self.csp_report_only = _coerce_bool(self.csp_report_only)
        self.csp_policy = self._validate_csp_policy(self.csp_policy)
        self.auth_rate_limit_enabled = _coerce_bool(self.auth_rate_limit_enabled)
        self.auth_rate_limit_window_seconds = _coerce_int(
            self.auth_rate_limit_window_seconds,
            "SECURITY__AUTH_RATE_LIMIT_WINDOW_SECONDS",
        )
        self.auth_rate_limit_max_requests = _coerce_int(
            self.auth_rate_limit_max_requests,
            "SECURITY__AUTH_RATE_LIMIT_MAX_REQUESTS",
        )

    @staticmethod
    def _validate_csp_policy(value: Any) -> str:
        normalized = _coerce_str(value).strip()
        lowered = normalized.lower()
        if "report-uri" in lowered or "report-to" in lowered:
            raise ValueError(
                "SECURITY__CSP_POLICY must not define report-uri/report-to; "
                "the app injects Reporting API directives and headers."
            )
        return normalized


@dataclass
class LoggingConfig:
    """Application logging controls."""

    level: str = "INFO"
    reveal_sensitive_data: bool = False
    redaction_text: str = "[REDACTED]"

    def __post_init__(self) -> None:
        self.level = self._normalize_level(self.level)
        self.reveal_sensitive_data = _coerce_bool(self.reveal_sensitive_data)
        self.redaction_text = _coerce_str(self.redaction_text)

    @staticmethod
    def _normalize_level(value: Any) -> str:
        normalized = _coerce_str(value).strip().upper()
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        if normalized not in allowed:
            raise ValueError(
                "LOGGING__LEVEL must be one of: CRITICAL, ERROR, WARNING, INFO, DEBUG"
            )
        return normalized


@dataclass
class AuthTestProfile:
    """Test-only auth profile for CI/playwright integration."""

    username: str
    email: str
    display_name: str = ""
    active: bool = True
    admin: bool = False
    groups: List[str] = field(default_factory=list)
    pi_groups: List[str] = field(default_factory=list)
    technologist: bool = False
    test_scanner_tech: bool = False

    def __post_init__(self) -> None:
        self.username = _coerce_str(self.username)
        self.email = normalize_email_address(
            self.email, field_name="AUTH_TEST__PROFILES__EMAIL"
        )
        self.display_name = _coerce_str(self.display_name)
        self.active = _coerce_bool(self.active)
        self.admin = _coerce_bool(self.admin)
        self.groups = _coerce_string_list(self.groups)
        self.pi_groups = _coerce_string_list(self.pi_groups)
        self.technologist = _coerce_bool(self.technologist)
        self.test_scanner_tech = _coerce_bool(self.test_scanner_tech)


def _default_auth_test_profiles() -> Dict[str, AuthTestProfile]:
    return {
        "admin": AuthTestProfile(
            username="test-admin",
            email="test-admin@example.com",
            display_name="Test Admin",
            active=True,
            admin=True,
            groups=["admin"],
        ),
        "member": AuthTestProfile(
            username="test-member",
            email="test-member@example.com",
            display_name="Test Member",
            active=True,
            admin=False,
            groups=[],
        ),
        "dev": AuthTestProfile(
            username="test-dev",
            email="test-dev@example.com",
            display_name="Test Dev",
            active=True,
            admin=False,
            groups=["DEV"],
        ),
        "dev_pi": AuthTestProfile(
            username="test-dev-pi",
            email="test-dev-pi@example.com",
            display_name="Test DEV PI",
            active=True,
            admin=False,
            groups=["DEV"],
            pi_groups=["DEV"],
        ),
        "tech": AuthTestProfile(
            username="test-tech",
            email="test-tech@example.com",
            display_name="Test Tech",
            active=True,
            admin=False,
            groups=["DEV"],
            technologist=True,
            test_scanner_tech=True,
        ),
        "inactive": AuthTestProfile(
            username="test-inactive",
            email="test-inactive@example.com",
            display_name="Test Inactive",
            active=False,
            admin=False,
            groups=[],
        ),
    }


@dataclass
class AuthTestConfig:
    """Test-only auth settings used for CI/local integration suites."""

    enabled: bool = False
    shared_secret: str = ""
    seed_groups: str = "DEV"
    profiles: Dict[str, AuthTestProfile] = field(
        default_factory=_default_auth_test_profiles
    )

    def __post_init__(self) -> None:
        self.enabled = _coerce_bool(self.enabled)
        self.shared_secret = _coerce_str(self.shared_secret)
        self.seed_groups = _coerce_str(self.seed_groups)
        self.profiles = self._normalize_profiles(self.profiles)

    @staticmethod
    def _normalize_profiles(value: Any) -> Dict[str, AuthTestProfile]:
        raw_profiles = _coerce_mapping(value, "AUTH_TEST__PROFILES")
        normalized: dict[str, AuthTestProfile] = {}
        for key, item in raw_profiles.items():
            if isinstance(item, AuthTestProfile):
                normalized[str(key)] = item
                continue
            if not isinstance(item, Mapping):
                raise ValueError("AUTH_TEST__PROFILES entries must be mappings")
            normalized[str(key)] = AuthTestProfile(**dict(item))
        return normalized


@dataclass
class ProxyConfig:
    """Proxy configuration settings"""

    x_forwarded_for: int = 0
    x_forwarded_proto: int = 0
    x_forwarded_host: int = 0
    x_forwarded_port: int = 0
    x_forwarded_prefix: int = 0

    def __post_init__(self) -> None:
        self.x_forwarded_for = self._validate_nonnegative(
            self.x_forwarded_for, "MMSCHED_X_FORWARDED_FOR"
        )
        self.x_forwarded_proto = self._validate_nonnegative(
            self.x_forwarded_proto, "MMSCHED_X_FORWARDED_PROTO"
        )
        self.x_forwarded_host = self._validate_nonnegative(
            self.x_forwarded_host, "MMSCHED_X_FORWARDED_HOST"
        )
        self.x_forwarded_port = self._validate_nonnegative(
            self.x_forwarded_port, "MMSCHED_X_FORWARDED_PORT"
        )
        self.x_forwarded_prefix = self._validate_nonnegative(
            self.x_forwarded_prefix, "MMSCHED_X_FORWARDED_PREFIX"
        )

    @staticmethod
    def _validate_nonnegative(value: Any, field_name: str) -> int:
        parsed = _coerce_int(value, field_name)
        if parsed < 0:
            raise ValueError("Proxy count must be non-negative")
        return parsed


class Settings:
    """Main settings container that coordinates all configuration."""

    def __init__(
        self, _env_file: str | os.PathLike[str] | None = ".env", **kwargs: Any
    ):
        raw: dict[str, Any] = {}
        _deep_merge(raw, _raw_values_from_env(_load_env_file_values(_env_file)))
        _deep_merge(raw, _raw_values_from_env(os.environ))
        _deep_merge(raw, _normalize_explicit_values(kwargs))

        self.app_env = normalize_app_env(
            _coerce_str(raw.get("app_env", APP_ENV_DEFAULT))
        )

        self.core = _instantiate_section(CoreConfig, raw.get("core"))
        self.server = _instantiate_section(ServerConfig, raw.get("server"))
        self.database = _instantiate_section(DatabaseConfig, raw.get("database"))
        self.mail = _instantiate_section(MailConfig, raw.get("mail"))
        self.session = _instantiate_section(SessionConfig, raw.get("session"))
        self.security = _instantiate_section(SecurityConfig, raw.get("security"))
        self.logging = _instantiate_section(LoggingConfig, raw.get("logging"))
        self.entra = _instantiate_section(EntraConfig, raw.get("entra"))
        self.auth_test = _instantiate_section(AuthTestConfig, raw.get("auth_test"))

        self.PGHOST = _coerce_str(raw.get("PGHOST", "postgres"))
        self.PGPORT = _coerce_int(raw.get("PGPORT", 5432), "PGPORT")
        self.PGUSER = _coerce_str(raw.get("PGUSER", "postgres"))
        self.PGPASSWORD = _coerce_str(raw.get("PGPASSWORD", "postgres"))
        self.PGDATABASE = _coerce_str(raw.get("PGDATABASE", "scheduler"))

        self.validate_required_settings()

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{quote(self.PGUSER)}:{quote(self.PGPASSWORD)}"
            f"@{self.PGHOST}:{self.PGPORT}/{quote(self.PGDATABASE)}"
        )

    def validate_required_settings(self) -> "Settings":
        app_env = normalize_app_env(self.app_env)
        self.app_env = app_env

        if app_env == "development":
            if not self.auth_test.enabled:
                self.auth_test.enabled = True
            if not self.core.debug:
                self.core.debug = True
            if self.session.cookie_secure:
                self.session.cookie_secure = False
            if self.auth_test.enabled and not self.auth_test.shared_secret.strip():
                self.auth_test.shared_secret = "dev-auth-test-secret"

        if app_env == "production":
            if self.auth_test.enabled:
                raise ValueError(
                    "AUTH_TEST__ENABLED must be false when APP_ENV is production"
                )

            missing = []
            if (
                not self.entra.client_id.strip()
                or self.entra.client_id == PLACEHOLDER_UUID
            ):
                missing.append("ENTRA__CLIENT_ID")
            if (
                not self.entra.tenant_id.strip()
                or self.entra.tenant_id == PLACEHOLDER_UUID
            ):
                missing.append("ENTRA__TENANT_ID")
            if not self.entra.discovery_url.strip():
                missing.append("ENTRA__DISCOVERY_URL")
            if not self.entra.redirect_uri.strip():
                missing.append("ENTRA__REDIRECT_URI")

            if missing:
                raise ValueError(
                    "Missing required Entra settings when APP_ENV is production: "
                    + ", ".join(missing)
                )
            _ = self.entra.edge_base_url
            if self.core.debug:
                raise ValueError("CORE__DEBUG must be false when APP_ENV is production")
            if (
                not self.core.secret_key.strip()
                or self.core.secret_key == "dev-key-change-in-prod"
            ):
                raise ValueError(
                    "CORE__SECRET_KEY must be set to a non-default value "
                    "when APP_ENV is production"
                )
            if not self.session.cookie_secure:
                raise ValueError(
                    "SESSION__COOKIE_SECURE must be true when APP_ENV is production"
                )
            if _is_mailpit_configured_for(app_env, self.mail.server):
                raise ValueError(
                    "Mailpit configuration is not allowed when APP_ENV is production"
                )

        if self.auth_test.enabled and not self.auth_test.shared_secret.strip():
            raise ValueError(
                "AUTH_TEST__SHARED_SECRET is required when AUTH_TEST__ENABLED is true"
            )

        if self.mail.default_sender is None:
            raise ValueError("MAIL__DEFAULT_SENDER is required")

        return self

    def get_proxy_count(self) -> Optional[Dict[str, int]]:
        proxy_vars = {
            "x_for": "MMSCHED_X_FORWARDED_FOR",
            "x_proto": "MMSCHED_X_FORWARDED_PROTO",
            "x_host": "MMSCHED_X_FORWARDED_HOST",
            "x_port": "MMSCHED_X_FORWARDED_PORT",
            "x_prefix": "MMSCHED_X_FORWARDED_PREFIX",
        }

        counts = {}
        for key, env_var in proxy_vars.items():
            if env_var in os.environ:
                try:
                    value = int(os.environ[env_var])
                    if value < 0:
                        raise ValueError(f"{env_var} must be nonnegative integer")
                    counts[key] = value
                except ValueError as exc:
                    if "must be nonnegative" in str(exc):
                        raise
                    raise ValueError(f"{env_var} must be a valid integer") from exc

        return counts if counts else None


class AppConfig(dict):
    """Flask application configuration with dictionary and attribute access"""

    def __init__(self, settings: Settings):
        super().__init__()
        config_dict = {
            "APP_ENV": settings.app_env,
            "SECRET_KEY": settings.core.secret_key,
            "DEBUG": settings.core.debug,
            "SQLALCHEMY_DATABASE_URI": settings.database_url,
            "SQLALCHEMY_ENGINE_OPTIONS": settings.database.sqlalchemy_engine_options,
            "SQLALCHEMY_TRACK_MODIFICATIONS": settings.database.track_modifications,
            "MAIL_SERVER": settings.mail.server,
            "MAIL_PORT": settings.mail.port,
            "MAIL_USE_TLS": settings.mail.use_tls,
            "MAIL_USE_SSL": settings.mail.use_ssl,
            "MAIL_USERNAME": settings.mail.username,
            "MAIL_PASSWORD": settings.mail.password,
            "MAIL_SUPPRESS_SEND": settings.mail.suppress_send,
            "MAIL_DEFAULT_SENDER": settings.mail.default_sender,
            "SESSION_COOKIE_NAME": settings.session.cookie_name,
            "SESSION_COOKIE_SECURE": settings.session.cookie_secure,
            "SESSION_COOKIE_HTTPONLY": settings.session.cookie_httponly,
            "SESSION_COOKIE_SAMESITE": settings.session.cookie_samesite,
            "PERMANENT_SESSION_LIFETIME": settings.session.permanent_lifetime,
            "SESSION_TYPE": settings.session.type,
            "SESSION_SQLALCHEMY_TABLE": settings.session.sqlalchemy_table,
            "ENTRA_CLIENT_ID": settings.entra.client_id,
            "ENTRA_TENANT_ID": settings.entra.tenant_id,
            "ENTRA_DISCOVERY_URL": settings.entra.discovery_url,
            "ENTRA_REDIRECT_URI": settings.entra.redirect_uri,
            "ENTRA_AUDIENCES": settings.entra.audiences,
            "ENTRA_ALLOWED_ALGORITHMS": settings.entra.allowed_algorithms,
            "ENTRA_ISSUER": settings.entra.issuer,
            "ENTRA_JWKS_CACHE_TTL": settings.entra.jwks_cache_ttl,
            "AUTH_TEST_ENABLED": settings.auth_test.enabled,
            "AUTH_TEST_SHARED_SECRET": settings.auth_test.shared_secret,
            "SECURITY_ENABLE_HSTS": settings.security.enable_hsts,
            "SECURITY_HSTS_MAX_AGE": settings.security.hsts_max_age,
            "SECURITY_HSTS_INCLUDE_SUBDOMAINS": settings.security.hsts_include_subdomains,
            "SECURITY_HSTS_PRELOAD": settings.security.hsts_preload,
            "SECURITY_FRAME_OPTIONS": settings.security.frame_options,
            "SECURITY_CONTENT_TYPE_OPTIONS": settings.security.content_type_options,
            "SECURITY_REFERRER_POLICY": settings.security.referrer_policy,
            "SECURITY_ENABLE_CSP": settings.security.enable_csp,
            "SECURITY_CSP_REPORT_ONLY": settings.security.csp_report_only,
            "SECURITY_CSP_POLICY": settings.security.csp_policy,
            "SECURITY_AUTH_RATE_LIMIT_ENABLED": settings.security.auth_rate_limit_enabled,
            "SECURITY_AUTH_RATE_LIMIT_WINDOW_SECONDS": settings.security.auth_rate_limit_window_seconds,
            "SECURITY_AUTH_RATE_LIMIT_MAX_REQUESTS": settings.security.auth_rate_limit_max_requests,
            "LOG_LEVEL": settings.logging.level,
            "LOG_REVEAL_SENSITIVE_DATA": settings.logging.reveal_sensitive_data,
            "LOG_REDACTION_TEXT": settings.logging.redaction_text,
            "DATABASE_SLOW_QUERY_THRESHOLD_MS": settings.database.slow_query_threshold_ms,
            "DATABASE_STARTUP_CHECK": settings.database.startup_check,
            "DATABASE_STARTUP_CHECK_ENABLED": settings.database.startup_check,
        }

        if settings.server.server_name.strip():
            config_dict["SERVER_NAME"] = settings.server.server_name

        self.update(config_dict)

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(f"'AppConfig' has no attribute '{name}'") from exc


# Create configuration objects for the application
settings = Settings(_env_file=env_file)
app_config = AppConfig(settings)
