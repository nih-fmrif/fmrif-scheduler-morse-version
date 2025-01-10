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

class LDAPConfig(BaseModel):
    """LDAP connection and authentication settings"""
    # Required settings with development defaults
    host: str = Field(
        default="ldap.forumsys.com" if not os.getenv('FLASK_ENV') == 'production' else ...,
        env='LDAP_HOST'
    )
    bind_dn: str = Field(
        default="cn=read-only-admin,dc=example,dc=com" if not os.getenv('FLASK_ENV') == 'production' else ...,
        env='LDAP_BIND_DN'
    )
    bind_password: str = Field(
        default="password" if not os.getenv('FLASK_ENV') == 'production' else ...,
        env='LDAP_BIND_PASSWORD'
    )
    base_dn: str = Field(
        default="dc=example,dc=com" if not os.getenv('FLASK_ENV') == 'production' else ...,
        env='LDAP_BASE_DN'
    )
    
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
        if os.getenv('FLASK_ENV') != 'production':
            default_values = {
                'host': "ldap.forumsys.com",
                'bind_dn': "cn=read-only-admin,dc=example,dc=com",
                'bind_password': "password",
                'base_dn': "dc=example,dc=com"
            }
            
            for field_name, default_value in default_values.items():
                if getattr(values, field_name) == default_value:
                    warnings.warn(
                        f"Using default LDAP {field_name}: {default_value}. "
                        "This is okay for development but must be changed in production."
                    )
        
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
    
class CoreConfig(BaseModel):
    """Core application settings"""
    debug: bool = True
    secret_key: str = Field(
        default="dev-key-change-in-prod" if not os.getenv('FLASK_ENV') == 'production' else ...,
        env='SCHEDULER_SECRET_KEY'
    )
    site_sender: str = Field(
        default="noreply@example.com" if not os.getenv('FLASK_ENV') == 'production' else ...,
        env='SCHEDULER_SITE_SENDER'
    )
    listserv: str = Field(
        default="listserv@example.com" if not os.getenv('FLASK_ENV') == 'production' else ...,
        env='SCHEDULER_LISTSERV'
    )
    sm_login_url_prefix: str = Field(
        default='https://auth.example.com/login?TYPE=33554433&GUID=&SMAUTHREASON=0&METHOD=GET&SMAGENTNAME=dummyAgent&TARGET=-SM-',
        env='SCHEDULER_SITEMINDER_PREFIX'
    )

    @model_validator(mode='after')
    def warn_default_values(cls, values: Any) -> Any:
        if os.getenv('FLASK_ENV') != 'production':
            default_values = {
                'secret_key': "dev-key-change-in-prod",
                'site_sender': "noreply@example.com",
                'listserv': "listserv@example.com"
            }
            
            for field_name, default_value in default_values.items():
                if getattr(values, field_name) == default_value:
                    warnings.warn(
                        f"Using default value for {field_name}. "
                        "This is okay for development but must be changed in production."
                    )
        
        return values

class MailConfig(BaseModel):
    """Email server configuration"""
    server: str = Field("localhost", env='MMSCHED_MAIL_SERVER')
    port: int = Field(25, env='MMSCHED_MAIL_PORT')
    use_tls: bool = Field(False, env='MMSCHED_MAIL_USE_TLS')
    use_ssl: bool = Field(False, env='MMSCHED_MAIL_USE_SSL')
    username: str = Field("", env='MMSCHED_MAIL_USERNAME')
    password: str = Field("", env='MMSCHED_MAIL_PASSWORD')
    suppress_send: bool = False

class SessionConfig(BaseModel):
    """Flask session configuration"""
    cookie_name: str = "dsid"
    permanent_lifetime: int = 8 * 60 * 60  # 8 hours
    type: str = "sqlalchemy"
    use_signer: bool = True
    sqlalchemy_table: str = "site_sessions"

class ServerConfig(BaseModel):
    """Server configuration settings"""
    server_name: str = Field(default="127.0.0.1:5000", env='MMSCHED_SERVER_NAME')
    application_root: str = Field("", env='MMSCHED_APPLICATION_ROOT')
    
class Settings(BaseSettings):
    """
    Main settings container that coordinates all configuration.
    Instantiates and provides access to all config components.
    """
    core: CoreConfig = CoreConfig()
    server: ServerConfig = ServerConfig()
    database: DatabaseConfig = DatabaseConfig()
    mail: MailConfig = MailConfig()
    session: SessionConfig = SessionConfig()
    ldap: LDAPConfig = LDAPConfig()
    # Add superuser mode setting
    superuser_mode: bool = Field(default=False, env='MMSCHED_SUPERUSER_MODE')

    # Network settings
    nih_networks: List[str] = Field(
        default_factory=lambda: [
            "127.0.0.1/32",  # Include localhost in debug mode
            "::1/128",       # IPv6 localhost
            "192.168.0.0/16",
            "10.10.0.0/16", 
            "172.16.0.0/12"
        ],
        env='SCHEDULER_NIH_NETWORKS' 
    )

    # Default mappings (previously in CSV files)
    device_departments: Dict[str, List[str]] = Field(
        default_factory=lambda: {
            'TEST': ['TEST', 'DEV']
        }
    )

    user_departments: Dict[str, Dict[str, bool]] = Field(
        default_factory=lambda: {
            'testuser': {
                'TEST': False,
                'DEV': True
            }
        }
    )

    device_permissions: Dict[str, Dict[str, Dict[str, bool]]] = Field(
        default_factory=lambda: {
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

    # Mailing lists configuration  
    mailing_lists: Dict[str, str] = Field(
        default_factory=lambda: {
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
        total, count = 0, {
            "For": 0,
            "Proto": 0,
            "Host": 0,
            "Port": 0,
            "Prefix": 0,
        }

        for ev in count.keys():
            nm = f"MMSCHED_X_FORWARDED_{ev.upper()}"
            n = int(self.dict().get(nm, 0))
            if n < 0:
                raise ValueError(f"{nm} must be nonnegative integer")
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

    def validate(self) -> Optional[str]:
        required_settings = [
            ('core.secret_key', 'SECRET_KEY'),
            ('core.site_sender', 'SITE_SENDER'),
            ('core.listserv', 'LISTSERV')
        ]
        for attr, name in required_settings:
            value = getattr(self, attr)
            if not value:
                return f"{name} must be set"
            # Email validation for site_sender and listserv
            if name in ['SITE_SENDER', 'LISTSERV'] and '@' not in value:
                return f"{name} must be a valid email address"
        return None

    class Config:
        """
        Pydantic model configuration.
        This class is used implicitly by Pydantic for model configuration.
        """
        env_file = '.env'
        case_sensitive = True
        extra = 'allow'

class AppConfig(dict):
    """
    Flask application configuration with both dictionary and attribute access.
    Allows both config['KEY'] and config.KEY access patterns.
    """
    def __init__(self, settings: 'Settings'):
        super().__init__()
        self.update({
            # Core settings - UPPERCASE for Flask compatibility
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
            'SUPERUSER_MODE': False,
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
        
# Global settings instance
settings = Settings()

app_config = AppConfig(settings)
