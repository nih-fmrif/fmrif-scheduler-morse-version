from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, validator
from pydantic_settings import BaseSettings
import ipaddress
from dataclasses import dataclass

class DatabaseConfig(BaseModel):
    url: str = Field(
        default="postgresql://postgres:postgres@localhost:5050/scheduler",
        env='MMSCHED_DB_URL'
    )
    echo: bool = Field(default=False)
    track_modifications: bool = Field(default=False)

class MailConfig(BaseModel):
    server: str = Field("localhost", env='MMSCHED_MAIL_SERVER')
    port: int = Field(25, env='MMSCHED_MAIL_PORT')
    use_tls: bool = Field(False, env='MMSCHED_MAIL_USE_TLS')
    use_ssl: bool = Field(False, env='MMSCHED_MAIL_USE_SSL')
    username: str = Field("", env='MMSCHED_MAIL_USERNAME')
    password: str = Field("", env='MMSCHED_MAIL_PASSWORD')
    suppress_send: bool = False

class SessionConfig(BaseModel):
    cookie_name: str = "dsid"
    permanent_lifetime: int = 8 * 60 * 60  # 8 hours
    type: str = "sqlalchemy"
    use_signer: bool = True
    sqlalchemy_table: str = "site_sessions"

class Settings(BaseSettings):
    # Core settings
    debug: bool = True
    secret_key: str = Field(default="dev-key-change-in-prod", env='SCHEDULER_SECRET_KEY')
    site_sender: str = Field(default="noreply@example.com", env='SCHEDULER_SITE_SENDER')
    listserv: str = Field(default="listserv@example.com", env='SCHEDULER_LISTSERV')
    sm_login_url_prefix: str = Field(
        default='https://auth.example.com/login?TYPE=33554433&GUID=&SMAUTHREASON=0&METHOD=GET&SMAGENTNAME=dummyAgent&TARGET=-SM-',
        env='SCHEDULER_SITEMINDER_PREFIX'
    )
    
    # Server settings
    server_name: str = Field(default="127.0.0.1:5000", env='MMSCHED_SERVER_NAME')  # Make this optional with default
    application_root: str = Field("", env='MMSCHED_APPLICATION_ROOT')
    
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

    # Database settings
    database: DatabaseConfig = DatabaseConfig()
    
    # Mail settings  
    mail: MailConfig = MailConfig()

    # Session settings
    session: SessionConfig = SessionConfig()

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
        if not self.secret_key or self.secret_key == 'dev-key-change-in-prod':
            return "SECRET_KEY must be set in production"
        if not self.site_sender or '@' not in self.site_sender:
            return "SITE_DEFAULT_SENDER must be a valid email"
        if not self.listserv or '@' not in self.listserv:
            return "LISTSERV must be a valid email"
        return None

    class Config:
        env_file = '.env'
        case_sensitive = True
        extra = 'allow'

# Global settings instance
settings = Settings()

# Make settings available to Flask config
config = {
    'SECRET_KEY': settings.secret_key,
    'SERVER_NAME': settings.server_name,
    'APPLICATION_ROOT': settings.application_root,
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
    'NIH_NETWORKS': [ipaddress.ip_network(net) for net in settings.nih_networks],
    'NIH_MAILING_LISTS': settings.mailing_lists,
    'nih_mailing_lists': settings.mailing_lists,
    'SM_LOGIN_URL_PREFIX': settings.sm_login_url_prefix,
    'SITE_DEFAULT_SENDER': settings.site_sender,
    'SUPERUSER_MODE': True if settings.debug else False
}