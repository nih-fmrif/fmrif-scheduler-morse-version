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

import ipaddress
import logging
import os
from typing import Dict, List, Optional
from urllib.parse import quote

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from scheduler.find_env_file import find_envfile

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
env_file = find_envfile()
logger.info(f"Loading .env from: {env_file}")

PLACEHOLDER_UUID = "00000000-0000-0000-0000-000000000000"


class EntraConfig(BaseModel):
    """Microsoft Entra / Azure AD application configuration."""

    client_id: str = ""
    tenant_id: str = ""
    discovery_url: str = ""
    redirect_uri: str = ""
    allowed_audiences: List[str] = Field(default_factory=list)
    scope: str = "openid profile email"  # OAuth 2.0 OIDC scopes for user identity
    jwks_cache_ttl: int = 60 * 60  # seconds

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
    site_sender: EmailStr = "noreply@example.com"
    listserv: str = "listserv@example.com"
    nih_networks: List[str] = [
        "127.0.0.1/32",
        "::1/128",
        "192.168.0.0/16",
        "10.10.0.0/16",
        "172.16.0.0/12",
    ]

    @field_validator("nih_networks")
    @classmethod
    def validate_networks(cls, networks: List[str]) -> List[str]:
        """Validate that each network is a valid IP network"""
        for network in networks:
            try:
                ipaddress.ip_network(network)
            except ValueError as e:
                raise ValueError(f"Invalid network format: {network}") from e
        return networks


class ServerConfig(BaseModel):
    """Server configuration settings"""

    server_name: str = ""  # Empty allows Flask to work with reverse proxies (nginx, etc.)
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
    mailing_lists: Dict[str, str] = {
        "list 1": "Description of list 1",
        "list 2": "Description of list 2",
    }


class SessionConfig(BaseModel):
    """Flask session configuration"""

    cookie_name: str = "dsid"
    permanent_lifetime: int = 8 * 60 * 60  # 8 hours
    type: str = "sqlalchemy"
    use_signer: bool = True
    sqlalchemy_table: str = "site_sessions"


class RBACConfig(BaseModel):
    superuser_mode: bool = False
    device_departments: Dict[str, List[str]] = {"TEST": ["TEST", "DEV"]}
    user_departments: Dict[str, Dict[str, bool]] = {
        "testuser": {"TEST": False, "DEV": True}
    }
    device_permissions: Dict[str, Dict[str, Dict[str, bool]]] = {
        "testuser": {
            "TEST": {
                "templates": True,
                "slot": True,
                "tech": False,
                "medical": False,
                "training": False,
            }
        }
    }


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

    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # To ignore extra fields
    )

    # Nested configs
    core: CoreConfig = CoreConfig()
    server: ServerConfig = ServerConfig()
    database: DatabaseConfig = DatabaseConfig()
    mail: MailConfig = MailConfig()
    session: SessionConfig = SessionConfig()
    entra: EntraConfig = EntraConfig()
    rbac: RBACConfig = RBACConfig()

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
        # SERVER_NAME can be empty (recommended for reverse proxy setups)
        # When empty, Flask accepts requests from any host

        if not self.rbac.superuser_mode:
            missing = []
            if not self.entra.client_id.strip() or self.entra.client_id == PLACEHOLDER_UUID:
                missing.append("ENTRA__CLIENT_ID")
            if not self.entra.tenant_id.strip() or self.entra.tenant_id == PLACEHOLDER_UUID:
                missing.append("ENTRA__TENANT_ID")
            if not self.entra.discovery_url.strip():
                missing.append("ENTRA__DISCOVERY_URL")
            if not self.entra.redirect_uri.strip():
                missing.append("ENTRA__REDIRECT_URI")

            if missing:
                raise ValueError(
                    "Missing required Entra settings when RBAC__SUPERUSER_MODE is false: "
                    + ", ".join(missing)
                )

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
            "SECRET_KEY": settings.core.secret_key,
            "APPLICATION_ROOT": settings.server.application_root,
            "SQLALCHEMY_DATABASE_URI": settings.database_url,
            "SQLALCHEMY_TRACK_MODIFICATIONS": settings.database.track_modifications,
            "MAIL_SERVER": settings.mail.server,
            "MAIL_PORT": settings.mail.port,
            "MAIL_USE_TLS": settings.mail.use_tls,
            "MAIL_USE_SSL": settings.mail.use_ssl,
            "MAIL_USERNAME": settings.mail.username,
            "MAIL_PASSWORD": settings.mail.password,
            "nih_mailing_lists": settings.mail.mailing_lists,
            "SESSION_COOKIE_NAME": settings.session.cookie_name,
            "PERMANENT_SESSION_LIFETIME": settings.session.permanent_lifetime,
            "SESSION_TYPE": settings.session.type,
            "SESSION_USE_SIGNER": settings.session.use_signer,
            "SESSION_SQLALCHEMY_TABLE": settings.session.sqlalchemy_table,
            "SUPERUSER_MODE": settings.rbac.superuser_mode,
            "NIH_NETWORKS": [
                ipaddress.ip_network(net) for net in settings.core.nih_networks
            ],
            "SITE_DEFAULT_SENDER": settings.core.site_sender,
            "ENTRA_CLIENT_ID": settings.entra.client_id,
            "ENTRA_TENANT_ID": settings.entra.tenant_id,
            "ENTRA_DISCOVERY_URL": settings.entra.discovery_url,
            "ENTRA_REDIRECT_URI": settings.entra.redirect_uri,
            "ENTRA_AUDIENCES": settings.entra.audiences,
            "ENTRA_ISSUER": settings.entra.issuer,
            "ENTRA_JWKS_CACHE_TTL": settings.entra.jwks_cache_ttl,
        }

        # Only set SERVER_NAME if not empty (for reverse proxy compatibility)
        if settings.server.server_name.strip():
            config_dict["SERVER_NAME"] = settings.server.server_name

        self.update(config_dict)

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(f"'AppConfig' has no attribute '{name}'")


# Create configuration objects for the application
settings = Settings(_env_file=env_file)
app_config = AppConfig(settings)
