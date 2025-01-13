"""
Application configuration management.

This module provides two main configuration interfaces:
1. AppConfig: Settings loaded directly into Flask app.config
2. Settings: Global application settings used throughout the codebase

The separation allows for clear distinction between Flask-specific config
and general application settings while maintaining a single source of truth.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, validator, model_validator
from pydantic_settings import BaseSettings
import ipaddress
from dataclasses import dataclass
import os
import warnings

class BaseAppSettings(BaseSettings):
    """Base settings class with common configuration"""
    class Config:
        env_file = '.env'
        env_file_encoding = 'utf-8'
        case_sensitive = True
        extra = 'allow'

    def warn_if_default(self, field_name: str, default_value: Any, context: str = ""):
        """Utility method to warn about default values in development"""
        if os.getenv('FLASK_ENV') != 'production':
            current_value = getattr(self, field_name)
            if current_value == default_value:
                prefix = f"{context} " if context else ""
                warnings.warn(
                    f"Using default {prefix}{field_name}: {default_value}. "
                    "This is okay for development but must be changed in production."
                )

class LDAPConfig(BaseAppSettings):
    """LDAP connection and authentication settings"""
    # Required settings with development defaults
    host: str = Field(default="ldap.forumsys.com", env='LDAP_HOST')
    bind_dn: str = Field(default="cn=read-only-admin,dc=example,dc=com", env='LDAP_BIND_DN')
    bind_password: str = Field(default="password", env='LDAP_BIND_PASSWORD')
    base_dn: str = Field(default="dc=example,dc=com", env='LDAP_BASE_DN')
    
    # Optional settings with sensible defaults
    port: int = Field(default=389, env='LDAP_PORT')
    use_ssl: bool = Field(default=False, env='LDAP_USE_SSL')
    user_dn_template: str = Field(default="uid={username},dc=example,dc=com", env='LDAP_USER_DN_TEMPLATE')
    group_dn: str = Field(default="ou=groups,dc=example,dc=com", env='LDAP_GROUP_DN')
    user_search_filter: str = Field(default="(objectClass=person)", env='LDAP_USER_FILTER')
    group_search_filter: str = Field(default="(objectClass=groupOfUniqueNames)", env='LDAP_GROUP_FILTER')
    token_lifetime: int = Field(default=28800, env='LDAP_TOKEN_LIFETIME')

    @model_validator(mode='after')
    def warn_default_values(cls, values: Any) -> Any:
        for field in ['host', 'bind_dn', 'bind_password', 'base_dn']:
            values.warn_if_default(field, getattr(values, field), "LDAP")
        return values

class DatabaseConfig(BaseModel):
    """Database connection and behavior settings"""
    # Required credentials with development defaults
    user: str = Field(
        default="postgres" if not os.getenv('FLASK_ENV') == 'production' else ...,
        env='POSTGRES_USER'
    )
    password: str = Field(
        default="postgres" if not os.getenv('FLASK_ENV') == 'production' else ...,
        env='POSTGRES_PASSWORD'
    )
    db: str = Field(
        default="scheduler" if not os.getenv('FLASK_ENV') == 'production' else ...,
        env='POSTGRES_DB'
    )
    # Optional with development-friendly defaults
    host: str = Field(default="localhost", env='POSTGRES_HOST')
    port: int = Field(default=5050, env='POSTGRES_PORT')
    echo: bool = Field(default=False)
    track_modifications: bool = Field(default=False)

    @model_validator(mode='after')
    def warn_default_values(cls, values: Any) -> Any:
        if os.getenv('FLASK_ENV') != 'production':
            default_values = {
                'user': "postgres",
                'password': "postgres",
                'db': "scheduler"
            }
            
            for field_name, default_value in default_values.items():
                if getattr(values, field_name) == default_value:
                    warnings.warn(
                        f"Using default database {field_name}: {default_value}. "
                        "This is okay for development but must be changed in production."
                    )
        
        return values

    @property
    def url(self) -> str:
        return f"postgresql+psycopg2://{self.user}:{self.password}@{self.host}:{self.port}/{self.db}"
    
class CoreConfig(BaseAppSettings):
    """Core application settings"""
    debug: bool = Field(default=True, env='FLASK_DEBUG')
    secret_key: str = Field(default="dev-key-change-in-prod", env='SCHEDULER_SECRET_KEY')
    site_sender: str = Field(default="noreply@example.com", env='SCHEDULER_SITE_SENDER')
    listserv: str = Field(default="listserv@example.com", env='SCHEDULER_LISTSERV')
    sm_login_url_prefix: str = Field(
        default='https://auth.example.com/login?TYPE=33554433&GUID=&SMAUTHREASON=0&METHOD=GET&SMAGENTNAME=dummyAgent&TARGET=-SM-',
        env='SCHEDULER_SITEMINDER_PREFIX'
    )

    @model_validator(mode='after')
    def warn_default_values(cls, values: Any) -> Any:
        for field in ['secret_key', 'site_sender', 'listserv']:
            values.warn_if_default(field, getattr(values, field))
        return values

class ServerConfig(BaseAppSettings):
    """Server configuration settings"""
    server_name: str = Field(default="127.0.0.1:5000", env='MMSCHED_SERVER_NAME')
    application_root: str = Field(default="", env='MMSCHED_APPLICATION_ROOT')

class MailConfig(BaseAppSettings):
    """Email server configuration"""
    server: str = Field(default="localhost", env='MMSCHED_MAIL_SERVER')
    port: int = Field(default=25, env='MMSCHED_MAIL_PORT')
    use_tls: bool = Field(default=False, env='MMSCHED_MAIL_USE_TLS')
    use_ssl: bool = Field(default=False, env='MMSCHED_MAIL_USE_SSL')
    username: str = Field(default="", env='MMSCHED_MAIL_USERNAME')
    password: str = Field(default="", env='MMSCHED_MAIL_PASSWORD')
    suppress_send: bool = Field(default=False)

class SessionConfig(BaseAppSettings):
    """Flask session configuration"""
    cookie_name: str = Field(default="dsid")
    permanent_lifetime: int = Field(default=8 * 60 * 60)  # 8 hours
    type: str = Field(default="sqlalchemy")
    use_signer: bool = Field(default=True)
    sqlalchemy_table: str = Field(default="site_sessions")
    
class Settings(BaseAppSettings):
    """Main settings container that coordinates all configuration"""
    # Nested configs
    core: CoreConfig = Field(default_factory=CoreConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    mail: MailConfig = Field(default_factory=MailConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    ldap: LDAPConfig = Field(default_factory=LDAPConfig)

    # Direct settings
    superuser_mode: bool = Field(default=False, env='MMSCHED_SUPERUSER_MODE')
    nih_networks: List[str] = Field(
        default=[
            "127.0.0.1/32",
            "::1/128",
            "192.168.0.0/16",
            "10.10.0.0/16", 
            "172.16.0.0/12"
        ],
        env='SCHEDULER_NIH_NETWORKS'
    )

    # Default mappings
    device_departments: Dict[str, List[str]] = Field(
        default={'TEST': ['TEST', 'DEV']}
    )
    user_departments: Dict[str, Dict[str, bool]] = Field(
        default={'testuser': {'TEST': False, 'DEV': True}}
    )
    device_permissions: Dict[str, Dict[str, Dict[str, bool]]] = Field(
        default={
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
    )
    mailing_lists: Dict[str, str] = Field(
        default={
            "list 1": "Description of list 1",
            "list 2": "Description of list 2"
        }
    )

    @validator('nih_networks', pre=True)
    def parse_networks(cls, v):
        if isinstance(v, str):
            return v.split(',')
        return v

    def get_proxy_count(self) -> Optional[Dict[str, int]]:
        """Get proxy configuration counts"""
        count = {key: 0 for key in ["For", "Proto", "Host", "Port", "Prefix"]}
        
        for key in count:
            env_var = f"MMSCHED_X_FORWARDED_{key.upper()}"
            value = int(self.dict().get(env_var, 0))
            if value < 0:
                raise ValueError(f"{env_var} must be nonnegative integer")
            count[key] = value

        total = sum(count.values())
        if total > 0:
            return {
                f"x_{k.lower()}": v 
                for k, v in count.items()
            }
        return None

    def validate(self) -> Optional[str]:
        """Validate critical settings"""
        required_settings = [
            ('core.secret_key', 'SECRET_KEY'),
            ('core.site_sender', 'SITE_SENDER'),
            ('core.listserv', 'LISTSERV')
        ]
        for attr_path, name in required_settings:
            parts = attr_path.split('.')
            value = self
            for part in parts:
                value = getattr(value, part)
            
            if not value:
                return f"{name} must be set"
            if name in ['SITE_SENDER', 'LISTSERV'] and '@' not in value:
                return f"{name} must be a valid email address"
        return None

class AppConfig(dict):
    """Flask application configuration with dictionary and attribute access"""
    def __init__(self, settings: Settings):
        super().__init__()
        self.update({
            'SECRET_KEY': settings.core.secret_key,
            'SERVER_NAME': settings.server.server_name,
            'APPLICATION_ROOT': settings.server.application_root,
            'SQLALCHEMY_DATABASE_URI': settings.database.url,
            'SQLALCHEMY_TRACK_MODIFICATIONS': settings.database.track_modifications,
            'MAIL_SERVER': settings.mail.server,
            'MAIL_PORT': settings.mail.port,
            'MAIL_USE_TLS': settings.mail.use_tls,
            'MAIL_USE_SSL': settings.mail.use_ssl,
            'MAIL_USERNAME': settings.mail.username,
            'MAIL_PASSWORD': settings.mail.password,
            'SESSION_COOKIE_NAME': settings.session.cookie_name,
            'PERMANENT_SESSION_LIFETIME': settings.session.permanent_lifetime,
            'SESSION_TYPE': settings.session.type,
            'SESSION_USE_SIGNER': settings.session.use_signer,
            'SESSION_SQLALCHEMY_TABLE': settings.session.sqlalchemy_table,
            'SUPERUSER_MODE': settings.superuser_mode,
            'NIH_NETWORKS': [ipaddress.ip_network(net) for net in settings.nih_networks],
            'nih_mailing_lists': settings.mailing_lists,
            'SM_LOGIN_URL_PREFIX': settings.core.sm_login_url_prefix,
            'SITE_DEFAULT_SENDER': settings.core.site_sender,
            })

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(f"'AppConfig' has no attribute '{name}'")
   
# Global instances
settings = Settings()

app_config = AppConfig(settings)
