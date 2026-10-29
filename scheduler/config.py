"""
Application configuration management.

This module provides two main configuration interfaces: 1. AppConfig: Settings
loaded directly into Flask app.config 2. Settings: Global application settings
used throughout the codebase

The separation allows for clear distinction between Flask-specific config and
general application settings while maintaining a single source of truth.

Pydantic-settings is used to load the environment variables from the .env file.
- dotenv.load_dotenv() does not work to populate environment variables so we are
  passing the file path in to pydantic

- Nested settings are used. That means configuration are specified by a prefix
  and the separator "__" e.g. DATABASE__HOST=postgres (where DATABASE is the
  nested config class instance)
"""

import logging
import os
from typing import Dict, List, Optional
from urllib.parse import quote

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from scheduler.find_env_file import find_envfile

logger = logging.getLogger(__name__)

# Load environment variables
env_file = find_envfile()
logger.info(f"Loading .env from: {env_file}")

PLACEHOLDER_UUID = "00000000-0000-0000-0000-000000000000"
APP_ENV_DEFAULT = "development"
PRODUCTION_ENVIRONMENTS = {"prod", "production", "stage", "staging"}
DEVELOPMENT_ENVIRONMENTS = {"dev", "development", "local", "test", "testing"}


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


class EntraConfig(BaseModel):
    """Microsoft Entra / Azure AD application configuration."""

    client_id: str = ""
    tenant_id: str = ""
    client_secret: str = (
        ""  # For confidential client token exchange (optional for PKCE public clients)
    )
    discovery_url: str = ""
    redirect_uri: str = ""
    allowed_audiences: List[str] = Field(default_factory=list)
    allowed_algorithms: List[str] = Field(default_factory=lambda: ["RS256"])
    bearer_auto_provision_enabled: bool = False
    bearer_auto_provision_domains: List[str] = Field(default_factory=list)
    bearer_auto_provision_groups: List[str] = Field(default_factory=list)
    scope: str = "openid profile email offline_access"  # OAuth 2.0 OIDC scopes + offline_access for refresh tokens
    jwks_cache_ttl: int = 60 * 60  # seconds

    @field_validator("allowed_algorithms")
    @classmethod
    def validate_allowed_algorithms(cls, value: List[str]) -> List[str]:
        normalized: List[str] = []
        for alg in value:
            token = str(alg).strip().upper()
            if token and token not in normalized:
                normalized.append(token)
        if not normalized:
            raise ValueError(
                "ENTRA__ALLOWED_ALGORITHMS must include at least one value"
            )
        return normalized

    @field_validator("bearer_auto_provision_domains")
    @classmethod
    def normalize_bearer_auto_provision_domains(cls, value: List[str]) -> List[str]:
        normalized: List[str] = []
        for domain in value:
            token = str(domain).strip().lower().lstrip("@")
            if token and token not in normalized:
                normalized.append(token)
        return normalized

    @field_validator("bearer_auto_provision_groups")
    @classmethod
    def normalize_bearer_auto_provision_groups(cls, value: List[str]) -> List[str]:
        normalized: List[str] = []
        for group in value:
            token = str(group).strip().lower()
            if token and token not in normalized:
                normalized.append(token)
        return normalized

    @property
    def issuer(self) -> str:
        """Expected issuer for tokens from this tenant."""
        if not self.tenant_id:
            return ""
        return f"https://login.microsoftonline.com/{self.tenant_id}/v2.0"

    @property
    def audiences(self) -> List[str]:
        """Compute the set of acceptable audiences for JWT validation."""
        audiences = [aud for aud in self.allowed_audiences if aud]
        if self.client_id and self.client_id not in audiences:
            audiences.append(self.client_id)
        api_audience = f"api://{self.client_id}" if self.client_id else ""
        if api_audience and api_audience not in audiences:
            audiences.append(api_audience)
        return audiences


class DatabaseConfig(BaseModel):
    # Required credentials with development defaults
    echo: bool = False
    track_modifications: bool = False


class CoreConfig(BaseModel):
    """Core application settings"""

    debug: bool = True
    secret_key: str = "dev-key-change-in-prod"
    listserv: str = "listserv@example.com"


class ServerConfig(BaseModel):
    """Server configuration settings"""

    server_name: str = (
        ""  # Empty allows Flask to work with reverse proxies (nginx, etc.)
    )
    application_root: str = ""


class MailConfig(BaseModel):
    """Email server configuration"""

    server: str = "localhost"
    port: int = 25
    use_tls: bool = False
    use_ssl: bool = False
    username: str = ""
    password: str = ""
    suppress_send: bool = False
    default_sender: Optional[EmailStr] = None
    mailing_lists: Dict[str, str] = {
        "list 1": "Description of list 1",
        "list 2": "Description of list 2",
    }


class SessionConfig(BaseModel):
    """Flask session configuration"""

    cookie_name: str = "dsid"
    cookie_secure: bool = True
    cookie_httponly: bool = True
    cookie_samesite: str = "Strict"
    permanent_lifetime: int = 8 * 60 * 60  # 8 hours
    type: str = "sqlalchemy"
    use_signer: bool = True
    sqlalchemy_table: str = "site_sessions"

    @field_validator("cookie_samesite")
    @classmethod
    def validate_cookie_samesite(cls, value: str) -> str:
        normalized = value.strip().lower()
        allowed = {"strict", "lax", "none"}
        if normalized not in allowed:
            raise ValueError(
                "SESSION__COOKIE_SAMESITE must be one of: Strict, Lax, None"
            )
        return normalized.capitalize()


class SecurityConfig(BaseModel):
    """Baseline HTTP response header settings."""

    enable_hsts: bool = True
    hsts_max_age: int = 63072000  # 2 years
    hsts_include_subdomains: bool = True
    hsts_preload: bool = False
    frame_options: str = "DENY"
    content_type_options: str = "nosniff"
    referrer_policy: str = "strict-origin-when-cross-origin"
    enable_csp: bool = True
    csp_report_only: bool = False
    csp_policy: str = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'nonce-{nonce}'; "
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


class LoggingConfig(BaseModel):
    """Application logging controls."""

    level: str = "INFO"
    reveal_sensitive_data: bool = False
    redaction_text: str = "[REDACTED]"

    @field_validator("level")
    @classmethod
    def validate_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        if normalized not in allowed:
            raise ValueError(
                "LOGGING__LEVEL must be one of: CRITICAL, ERROR, WARNING, INFO, DEBUG"
            )
        return normalized


class AuthTestProfile(BaseModel):
    """Test-only auth profile for CI/playwright integration."""

    username: str
    email: EmailStr
    display_name: str = ""
    active: bool = True
    admin: bool = False
    groups: List[str] = Field(default_factory=list)
    pi_groups: List[str] = Field(default_factory=list)
    technologist: bool = False
    test_scanner_tech: bool = False


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


class AuthTestConfig(BaseModel):
    """Test-only auth settings used for CI/local integration suites."""

    enabled: bool = False
    shared_secret: str = ""
    seed_groups: str = "DEV"
    profiles: Dict[str, AuthTestProfile] = Field(
        default_factory=_default_auth_test_profiles
    )


class ProxyConfig(BaseModel):
    """Proxy configuration settings"""

    x_forwarded_for: int = 0
    x_forwarded_proto: int = 0
    x_forwarded_host: int = 0
    x_forwarded_port: int = 0
    x_forwarded_prefix: int = 0

    @field_validator("*")
    @classmethod
    def validate_nonnegative(cls, v: int) -> int:
        """Validate that all proxy counts are non-negative"""
        if v < 0:
            raise ValueError("Proxy count must be non-negative")
        return v


class Settings(BaseSettings):
    """Main settings container that coordinates all configuration"""

    app_env: str = Field(default=APP_ENV_DEFAULT, alias="APP_ENV")

    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # To ignore extra fields
        populate_by_name=True,
    )

    # Nested configs
    core: CoreConfig = CoreConfig()
    server: ServerConfig = ServerConfig()
    database: DatabaseConfig = DatabaseConfig()
    mail: MailConfig = MailConfig()
    session: SessionConfig = SessionConfig()
    security: SecurityConfig = SecurityConfig()
    logging: LoggingConfig = LoggingConfig()
    entra: EntraConfig = EntraConfig()
    auth_test: AuthTestConfig = AuthTestConfig()

    """Database connection settings using standard PG* variables"""
    PGHOST: str = "postgres"
    PGPORT: int = 5432
    PGUSER: str = "postgres"
    PGPASSWORD: str = "postgres"
    PGDATABASE: str = "scheduler"

    @property
    def database_url(self) -> str:
        """Generate database URL with proper URL encoding of special characters"""
        return (
            f"postgresql+psycopg2://{quote(self.PGUSER)}:{quote(self.PGPASSWORD)}"
            f"@{self.PGHOST}:{self.PGPORT}/{quote(self.PGDATABASE)}"
        )

    @model_validator(mode="after")
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
        """Get proxy configuration counts from environment variables"""
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
                except ValueError as e:
                    if "must be nonnegative" in str(e):
                        raise
                    raise ValueError(f"{env_var} must be a valid integer")

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
            "SQLALCHEMY_TRACK_MODIFICATIONS": settings.database.track_modifications,
            "MAIL_SERVER": settings.mail.server,
            "MAIL_PORT": settings.mail.port,
            "MAIL_USE_TLS": settings.mail.use_tls,
            "MAIL_USE_SSL": settings.mail.use_ssl,
            "MAIL_USERNAME": settings.mail.username,
            "MAIL_PASSWORD": settings.mail.password,
            "MAIL_SUPPRESS_SEND": settings.mail.suppress_send,
            "MAIL_DEFAULT_SENDER": (
                str(settings.mail.default_sender)
                if settings.mail.default_sender is not None
                else None
            ),
            "SESSION_COOKIE_NAME": settings.session.cookie_name,
            "SESSION_COOKIE_SECURE": settings.session.cookie_secure,
            "SESSION_COOKIE_HTTPONLY": settings.session.cookie_httponly,
            "SESSION_COOKIE_SAMESITE": settings.session.cookie_samesite,
            "PERMANENT_SESSION_LIFETIME": settings.session.permanent_lifetime,
            "SESSION_TYPE": settings.session.type,
            "SESSION_USE_SIGNER": settings.session.use_signer,
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
        }

        # Only set SERVER_NAME if not empty (for reverse proxy compatibility)
        if settings.server.server_name.strip():
            config_dict["SERVER_NAME"] = settings.server.server_name
        # Only set APPLICATION_ROOT if not empty to avoid empty cookie paths
        if settings.server.application_root.strip():
            config_dict["APPLICATION_ROOT"] = settings.server.application_root

        self.update(config_dict)

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(f"'AppConfig' has no attribute '{name}'")


# Create configuration objects for the application
settings = Settings(_env_file=env_file)
app_config = AppConfig(settings)
