"""
Application configuration management.

This module provides two main configuration interfaces:
1. AppConfig: Settings loaded directly into Flask app.config
2. Settings: Global application settings used throughout the codebase

The separation allows for clear distinction between Flask-specific config
and general application settings while maintaining a single source of truth.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, validator
from pydantic_settings import BaseSettings
import ipaddress
from dataclasses import dataclass

class LDAPConfig(BaseModel):
    """LDAP connection and authentication settings"""
    host: str = Field(default="ldap.forumsys.com", env='LDAP_HOST')
    port: int = Field(default=389, env='LDAP_PORT')
    use_ssl: bool = Field(default=False, env='LDAP_USE_SSL')
    bind_dn: str = Field(default="cn=read-only-admin,dc=example,dc=com", env='LDAP_BIND_DN')
    bind_password: str = Field(default="password", env='LDAP_BIND_PASSWORD')
    base_dn: str = Field(default="dc=example,dc=com", env='LDAP_BASE_DN')
    user_dn_template: str = Field(default="uid={username},dc=example,dc=com", env='LDAP_USER_DN_TEMPLATE')
    group_dn: str = Field(default="ou=groups,dc=example,dc=com", env='LDAP_GROUP_DN')
    user_search_filter: str = Field(default="(objectClass=person)", env='LDAP_USER_FILTER')
    group_search_filter: str = Field(default="(objectClass=groupOfUniqueNames)", env='LDAP_GROUP_FILTER')
    token_lifetime: int = Field(default=28800, env='LDAP_TOKEN_LIFETIME') # 8 hours in seconds

class DatabaseConfig(BaseModel):
    """Database connection and behavior settings"""
    user: str = Field(default="postgres", env='POSTGRES_USER')
    password: str = Field(default="postgres", env='POSTGRES_PASSWORD') 
    db: str = Field(default="scheduler", env='POSTGRES_DB')
    host: str = Field(default="localhost", env='POSTGRES_HOST')
    port: int = Field(default=5050, env='POSTGRES_PORT')
    echo: bool = Field(default=False)
    track_modifications: bool = Field(default=False)

    @property
    def url(self) -> str:
        return f"postgresql+psycopg2://{self.user}:{self.password}@{self.host}:{self.port}/{self.db}"

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

class CoreConfig(BaseModel):
    """Core application settings"""
    debug: bool = True
    secret_key: str = Field(default="dev-key-change-in-prod", env='SCHEDULER_SECRET_KEY')
    site_sender: str = Field(default="noreply@example.com", env='SCHEDULER_SITE_SENDER')
    listserv: str = Field(default="listserv@example.com", env='SCHEDULER_LISTSERV')
    sm_login_url_prefix: str = Field(
        default='https://auth.example.com/login?TYPE=33554433&GUID=&SMAUTHREASON=0&METHOD=GET&SMAGENTNAME=dummyAgent&TARGET=-SM-',
        env='SCHEDULER_SITEMINDER_PREFIX'
    )

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
        """Validate required configuration values"""
        if not self.core.secret_key or self.core.secret_key == 'dev-key-change-in-prod':
            return "SECRET_KEY must be set in production"
        if not self.core.site_sender or '@' not in self.core.site_sender:
            return "SITE_DEFAULT_SENDER must be a valid email"
        if not self.core.listserv or '@' not in self.core.listserv:
            return "LISTSERV must be a valid email"
        return None

    class Config:
        """
        Pydantic model configuration.
        This class is used implicitly by Pydantic for model configuration.
        """
        env_file = '.env'
        case_sensitive = True
        extra = 'allow'

# Global settings instance
settings = Settings()

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
            'SUPERUSER_MODE': True if settings.core.debug else False,
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

app_config = AppConfig(settings)
