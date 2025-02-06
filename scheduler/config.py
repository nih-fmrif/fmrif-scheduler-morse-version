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
# TODO: need to rewrite db host and port when in container, remove traces of DATABASE__
import logging
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, validator, model_validator, EmailStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import ipaddress
from dataclasses import dataclass
import os
import warnings
from pathlib import Path
from dotenv import load_dotenv
from scheduler.find_env_file import find_envfile
from urllib.parse import quote

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
env_file = find_envfile()

class LDAPConfig(BaseModel):
    """LDAP connection and authentication settings"""
    # Required settings with development defaults
    host: str = "ldap.forumsys.com"
    bind_dn: str = "cn=read-only-admin,dc=example,dc=com"
    bind_password: str = "password"
    base_dn: str = "dc=example,dc=com"

    # Optional settings with sensible defaults
    port: int = 389
    use_ssl: bool = False
    user_dn_template: str = "uid={username},dc=example,dc=com"
    group_dn: str = "ou=groups,dc=example,dc=com"
    user_search_filter: str = "(objectClass=person)"
    group_search_filter: str = "(objectClass=groupOfUniqueNames)"
    token_lifetime: int = 28800

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
    login_url_prefix: str = "https://auth.example.com/login"
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
    server_name: str = "localhost:5051"
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
        "list 2": "Description of list 2"
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
    device_departments: Dict[str, List[str]] = {'TEST': ['TEST', 'DEV']}
    user_departments: Dict[str, Dict[str, bool]] = {'testuser': {'TEST': False, 'DEV': True}}
    device_permissions: Dict[str, Dict[str, Dict[str, bool]]] = {
        'testuser': {
            'TEST': {
                'templates': True,
                'slot': True,
                'tech': False,
                'medical': False,
                'training': False
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
        extra="ignore"  # To ignore extra fields
    )

    # Nested configs
    core: CoreConfig = CoreConfig()
    server: ServerConfig = ServerConfig()
    database: DatabaseConfig = DatabaseConfig()
    mail: MailConfig = MailConfig()
    session: SessionConfig = SessionConfig()
    ldap: LDAPConfig = LDAPConfig()
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

    def get_proxy_count(self) -> Optional[Dict[str, int]]:
        """Get proxy configuration counts from environment variables"""
        proxy_vars = {
            "x_for": "MMSCHED_X_FORWARDED_FOR",
            "x_proto": "MMSCHED_X_FORWARDED_PROTO",
            "x_host": "MMSCHED_X_FORWARDED_HOST",
            "x_port": "MMSCHED_X_FORWARDED_PORT",
            "x_prefix": "MMSCHED_X_FORWARDED_PREFIX"
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
        self.update({
            'SECRET_KEY': settings.core.secret_key,
            'SERVER_NAME': settings.server.server_name,
            'APPLICATION_ROOT': settings.server.application_root,
            'SQLALCHEMY_DATABASE_URI': settings.database_url,
            'SQLALCHEMY_TRACK_MODIFICATIONS': settings.database.track_modifications,
            'MAIL_SERVER': settings.mail.server,
            'MAIL_PORT': settings.mail.port,
            'MAIL_USE_TLS': settings.mail.use_tls,
            'MAIL_USE_SSL': settings.mail.use_ssl,
            'MAIL_USERNAME': settings.mail.username,
            'MAIL_PASSWORD': settings.mail.password,
            'nih_mailing_lists': settings.mail.mailing_lists,
            'SESSION_COOKIE_NAME': settings.session.cookie_name,
            'PERMANENT_SESSION_LIFETIME': settings.session.permanent_lifetime,
            'SESSION_TYPE': settings.session.type,
            'SESSION_USE_SIGNER': settings.session.use_signer,
            'SESSION_SQLALCHEMY_TABLE': settings.session.sqlalchemy_table,
            'SUPERUSER_MODE': settings.rbac.superuser_mode,
            'NIH_NETWORKS': [ipaddress.ip_network(net) for net in settings.core.nih_networks],
            'LOGIN_URL_PREFIX': settings.core.login_url_prefix,
            'SITE_DEFAULT_SENDER': settings.core.site_sender,
        })

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(f"'AppConfig' has no attribute '{name}'")

# Create configuration objects for the application
settings = Settings(_env_file=env_file)
app_config = AppConfig(settings)
