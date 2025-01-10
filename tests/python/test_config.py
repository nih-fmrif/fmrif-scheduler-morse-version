import pytest
from scheduler.config import Settings, LDAPConfig, CoreConfig, ServerConfig
import os

def test_default_settings():
    settings = Settings()
    assert settings.ldap.host == "ldap.forumsys.com"
    assert settings.core.debug is True
    assert settings.server.server_name == "127.0.0.1:5000"

def test_env_override():
    os.environ['LDAP_HOST'] = 'test.ldap.com'
    os.environ['SCHEDULER_SECRET_KEY'] = 'test-secret'
    settings = Settings()
    assert settings.ldap.host == 'test.ldap.com'
    assert settings.core.secret_key == 'test-secret'
    
def test_validation():
    settings = Settings()
    # Should pass with defaults
    assert settings.validate() is None
    
    # Test invalid email
    settings.core.site_sender = 'invalid-email'
    assert 'SITE_SENDER must be a valid email address' in settings.validate()

def test_ldap_config():
    config = LDAPConfig()
    assert config.port == 389
    assert config.use_ssl is False
    assert config.token_lifetime == 28800  # 8 hours

def test_core_config():
    config = CoreConfig()
    assert config.debug is True
    assert 'dev-key' in config.secret_key
    assert '@example.com' in config.site_sender

def test_server_config():
    config = ServerConfig()
    assert config.server_name == "127.0.0.1:5000"
    assert config.application_root == "" 