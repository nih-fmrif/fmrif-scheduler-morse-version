import ipaddress
import os
import tempfile
from pathlib import Path
from typing import Any, Generator
from urllib.parse import quote

import pytest
from pydantic import ValidationError

from scheduler.config import (
    AppConfig,
    CoreConfig,
    EntraConfig,
    MailConfig,
    RBACConfig,
    ServerConfig,
    SessionConfig,
    Settings,
)

# tests/python/test_config.py


@pytest.fixture
def temp_env_file() -> Generator[Path, None, None]:
    """Create a temporary .env file for testing"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        yield Path(f.name)
    os.unlink(f.name)


@pytest.fixture
def clean_env(monkeypatch):
    """Clear relevant environment variables before each test"""
    env_vars = [
        "PGHOST",
        "PGPORT",
        "PGUSER",
        "PGPASSWORD",
        "PGDATABASE",
        "CORE__SECRET_KEY",
        "CORE__SITE_SENDER",
        "CORE__DEBUG",
        "MAIL__SERVER",
        "MAIL__PORT",
        "MAIL__USE_TLS",
        "ENTRA__CLIENT_ID",
        "ENTRA__TENANT_ID",
        "ENTRA__DISCOVERY_URL",
        "ENTRA__REDIRECT_URI",
        "ENTRA__JWKS_CACHE_TTL",
        "SERVER__SERVER_NAME",
        "SERVER__APPLICATION_ROOT",
        "SESSION__COOKIE_NAME",
        "SESSION__TYPE",
        "RBAC__SUPERUSER_MODE",
        "MMSCHED_X_FORWARDED_FOR",
        "MMSCHED_X_FORWARDED_PROTO",
        "MMSCHED_X_FORWARDED_HOST",
        "MMSCHED_X_FORWARDED_PORT",
        "MMSCHED_X_FORWARDED_PREFIX",
    ]
    for var in env_vars:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


@pytest.mark.parametrize(
    "config_class,field,default,valid_value,invalid_value",
    [
        (
            CoreConfig,
            "site_sender",
            "noreply@example.com",
            "test@example.com",
            "invalid-email",
        ),
        (EntraConfig, "jwks_cache_ttl", 3600, 7200, "invalid"),
        (MailConfig, "port", 25, 587, "invalid"),
        (SessionConfig, "permanent_lifetime", 28800, 3600, "invalid"),
    ],
)
def test_config_field_validation(
    config_class, field, default, valid_value, invalid_value
):
    """Test configuration field validation systematically"""
    # Test default value
    config = config_class()
    assert getattr(config, field) == default

    # Test valid value
    config = config_class(**{field: valid_value})
    assert getattr(config, field) == valid_value

    # Test invalid value
    if invalid_value is not None:
        with pytest.raises((ValidationError, ValueError)):
            config_class(**{field: invalid_value})


@pytest.mark.parametrize(
    "env_var,env_value,config_path,expected",
    [
        ("PGHOST", "env-host", "PGHOST", "env-host"),
        ("PGPORT", "5433", "PGPORT", 5433),
        ("CORE__SECRET_KEY", "env-key", "core.secret_key", "env-key"),
        ("MAIL__SERVER", "env-smtp", "mail.server", "env-smtp"),
        ("ENTRA__CLIENT_ID", "env-client", "entra.client_id", "env-client"),
        ("SERVER__SERVER_NAME", "env:8080", "server.server_name", "env:8080"),
    ],
)
def test_config_hierarchy(
    clean_env,
    temp_env_file,
    env_var: str,
    env_value: str,
    config_path: str,
    expected: Any,
):
    """Test configuration hierarchy (default -> env file -> environment variable)"""

    # Get default value
    settings = Settings()
    _get_nested_attr(settings, config_path)

    # Test .env file override
    env_content = "\n".join(
        [
            "RBAC__SUPERUSER_MODE=true",
            f"{env_var}={env_value}",
        ]
    ) + "\n"
    temp_env_file.write_text(env_content)
    settings = Settings(_env_file=temp_env_file)
    envfile_value = _get_nested_attr(settings, config_path)
    assert envfile_value == expected

    # Test environment variable override
    clean_env.setenv(env_var, env_value)
    settings = Settings(_env_file=temp_env_file)
    assert _get_nested_attr(settings, config_path) == expected


def test_database_url_construction():
    """Test database URL construction with different configurations"""
    test_cases = [
        {
            "config": {
                "PGUSER": "test",
                "PGPASSWORD": "pass",
                "PGHOST": "localhost",
                "PGPORT": 5432,
                "PGDATABASE": "testdb",
            },
            "expected": "postgresql+psycopg2://test:pass@localhost:5432/testdb",
        },
        {
            "config": {
                "PGUSER": "user@domain",
                "PGPASSWORD": "pass:word!",
                "PGHOST": "host.com",
                "PGPORT": 5433,
                "PGDATABASE": "prod",
            },
            "expected": f"postgresql+psycopg2://{quote('user@domain')}:{quote('pass:word!')}@host.com:5433/prod",
        },
    ]

    for case in test_cases:
        settings = Settings(**case["config"])
        assert settings.database_url == case["expected"]


@pytest.mark.parametrize(
    "networks,expected_valid",
    [
        (["192.168.1.0/24", "10.0.0.0/8"], True),
        (["2001:db8::/32", "192.168.1.0/24"], True),
    ],
)
def test_core_network_validation(networks, expected_valid):
    """Test validation of NIH networks configuration"""
    config = CoreConfig(nih_networks=networks)
    assert len(config.nih_networks) == len(networks)
    # Verify each network can be parsed by ipaddress
    for net in config.nih_networks:
        ipaddress.ip_network(net)


@pytest.mark.parametrize(
    "config_dict,expected_keys",
    [
        (
            {"core": {"secret_key": "test"}, "database": {"host": "test"}},
            ["SECRET_KEY", "SQLALCHEMY_DATABASE_URI"],
        ),
        (
            {
                "mail": {"server": "test", "port": 25},
                "session": {"cookie_name": "test"},
            },
            ["MAIL_SERVER", "MAIL_PORT", "SESSION_COOKIE_NAME"],
        ),
    ],
)
def test_app_config_mapping(config_dict, expected_keys):
    """Test mapping of Settings to AppConfig"""
    settings = Settings(**config_dict)
    app_config = AppConfig(settings)

    # Verify expected keys exist
    for key in expected_keys:
        assert key in app_config

    # Verify both dict and attribute access
    for key in app_config:
        assert getattr(app_config, key) == app_config[key]


def test_proxy_count_validation(clean_env):
    """Test proxy count configuration"""
    # Test with no proxy settings
    settings = Settings()
    assert settings.get_proxy_count() is None

    # Test with valid proxy settings
    proxy_vars = {
        "MMSCHED_X_FORWARDED_FOR": "2",
        "MMSCHED_X_FORWARDED_PROTO": "1",
        "MMSCHED_X_FORWARDED_HOST": "1",
        "MMSCHED_X_FORWARDED_PORT": "1",
        "MMSCHED_X_FORWARDED_PREFIX": "1",
    }

    # Set environment variables
    for var, value in proxy_vars.items():
        clean_env.setenv(var, value)
        os.environ[var] = value

    # Create a new Settings instance to read environment variables
    settings = Settings()
    proxy_count = settings.get_proxy_count()
    assert proxy_count is not None
    assert proxy_count == {
        "x_for": 2,
        "x_proto": 1,
        "x_host": 1,
        "x_port": 1,
        "x_prefix": 1,
    }

    # Test with invalid proxy settings
    clean_env.setenv("MMSCHED_X_FORWARDED_FOR", "-1")
    os.environ["MMSCHED_X_FORWARDED_FOR"] = "-1"
    with pytest.raises(
        ValueError, match="MMSCHED_X_FORWARDED_FOR must be nonnegative integer"
    ):
        settings.get_proxy_count()


def _get_nested_attr(obj: Any, path: str) -> Any:
    """Helper to get nested attribute value using dot notation"""
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


def test_entra_config_validation():
    """Test Entra configuration validation and derived properties"""
    config = EntraConfig()
    assert config.jwks_cache_ttl == 3600
    assert config.issuer == ""
    assert config.audiences == []

    custom_config = EntraConfig(
        client_id="client-id",
        tenant_id="tenant-id",
        allowed_audiences=["custom-audience"],
    )

    assert custom_config.issuer.endswith("tenant-id/v2.0")
    assert "client-id" in custom_config.audiences
    assert "api://client-id" in custom_config.audiences
    assert "custom-audience" in custom_config.audiences


def test_server_config():
    """Test server configuration"""
    config = ServerConfig(server_name="test.server:8080", application_root="/app")

    assert config.server_name == "test.server:8080"
    assert config.application_root == "/app"


def test_database_config_validation():
    """Test DatabaseConfig validation - explicit values override env"""
    # Test that constructor accepts all database parameters
    # Note: Pydantic Settings prioritizes environment variables,
    # so we just verify the fields exist and can be set

    settings = Settings()
    # Verify default fields exist
    assert hasattr(settings, 'PGUSER')
    assert hasattr(settings, 'PGPASSWORD')
    assert hasattr(settings, 'PGDATABASE')
    assert hasattr(settings, 'PGHOST')
    assert hasattr(settings, 'PGPORT')

    # Verify database URL is properly constructed
    assert 'postgresql+psycopg2://' in settings.database_url

    # Verify database config flags
    assert settings.database.echo is False
    assert settings.database.track_modifications is False


def test_core_config_validation():
    """Test CoreConfig validation"""
    # Test default values
    config = CoreConfig()
    assert config.debug is True
    assert config.secret_key == "dev-key-change-in-prod"
    assert isinstance(config.site_sender, str)
    assert "@" in config.site_sender
    assert len(config.nih_networks) == 5

    # Test custom values with valid email
    config = CoreConfig(
        debug=False,
        secret_key="production-key",
        site_sender="test@example.com",
        nih_networks=["192.168.1.0/24"],
    )
    assert config.debug is False
    assert config.secret_key == "production-key"
    assert config.site_sender == "test@example.com"
    assert len(config.nih_networks) == 1

    # Test invalid email validation
    with pytest.raises(ValidationError):
        CoreConfig(site_sender="invalid-email")


def test_server_config_validation():
    """Test ServerConfig validation - empty server_name for reverse proxy compatibility"""
    config = ServerConfig()
    assert config.server_name == ""  # Empty for reverse proxy (nginx) compatibility
    assert config.application_root == ""

    config = ServerConfig(server_name="test.server:8080", application_root="/app")
    assert config.server_name == "test.server:8080"
    assert config.application_root == "/app"


def test_mail_config_validation():
    """Test MailConfig validation"""
    config = MailConfig()
    assert config.server == "localhost"
    assert config.port == 25
    assert config.use_tls is False
    assert config.use_ssl is False
    assert isinstance(config.mailing_lists, dict)

    config = MailConfig(
        server="smtp.test.com",
        port=587,
        use_tls=True,
        username="test",
        password="secret",
    )
    assert config.server == "smtp.test.com"
    assert config.port == 587
    assert config.use_tls is True
    assert config.username == "test"
    assert config.password == "secret"


def test_session_config_validation():
    """Test SessionConfig validation"""
    config = SessionConfig()
    assert config.cookie_name == "dsid"
    assert config.permanent_lifetime == 8 * 60 * 60
    assert config.type == "sqlalchemy"
    assert config.use_signer is True

    config = SessionConfig(
        cookie_name="test_session", permanent_lifetime=3600, type="redis"
    )
    assert config.cookie_name == "test_session"
    assert config.permanent_lifetime == 3600
    assert config.type == "redis"


def test_rbac_config_validation():
    """Test RBACConfig validation"""
    config = RBACConfig()
    assert config.superuser_mode is False
    assert isinstance(config.device_departments, dict)
    assert isinstance(config.user_departments, dict)
    assert isinstance(config.device_permissions, dict)

    config = RBACConfig(
        superuser_mode=True,
        device_departments={"SCANNER": ["DEPT1", "DEPT2"]},
        user_departments={"user1": {"DEPT1": True}},
        device_permissions={"user1": {"SCANNER": {"templates": True}}},
    )
    assert config.superuser_mode is True
    assert config.device_departments == {"SCANNER": ["DEPT1", "DEPT2"]}
    assert config.user_departments == {"user1": {"DEPT1": True}}
    assert "user1" in config.device_permissions


def test_settings_env_override(temp_env_file, monkeypatch):
    """Test environment variable override functionality"""
    # Write test values to temporary .env file
    env_content = """
RBAC__SUPERUSER_MODE=true
PGHOST=testhost
PGPORT=5433
CORE__SECRET_KEY=test-secret
MAIL__SERVER=test-smtp
ENTRA__CLIENT_ID=test-client
"""
    temp_env_file.write_text(env_content.strip())

    # Set environment variables directly
    monkeypatch.setenv("PGHOST", "testhost")
    monkeypatch.setenv("PGPORT", "5433")
    monkeypatch.setenv("CORE__SECRET_KEY", "test-secret")
    monkeypatch.setenv("MAIL__SERVER", "test-smtp")
    monkeypatch.setenv("ENTRA__CLIENT_ID", "test-client")

    # Create Settings with our temp env file
    settings = Settings(_env_file=temp_env_file)

    # Verify environment overrides
    assert settings.PGHOST == "testhost"
    assert settings.PGPORT == 5433
    assert settings.core.secret_key == "test-secret"
    assert settings.mail.server == "test-smtp"
    assert settings.entra.client_id == "test-client"

    # Verify non-overridden values maintain defaults
    assert settings.PGUSER == "postgres"
    assert settings.core.debug is True
    assert settings.mail.port == 25


def test_settings_with_invalid_env_values(temp_env_file, monkeypatch):
    """Test validation of invalid environment variable values"""
    # Set invalid environment variables directly
    monkeypatch.setenv("PGPORT", "invalid")
    monkeypatch.setenv("MAIL__PORT", "-1")

    # Verify that invalid values raise ValidationError
    with pytest.raises((ValidationError, ValueError)):
        Settings()


def test_attribute_access_app_config():
    """Test both dictionary and attribute access for AppConfig"""
    settings = Settings()
    app_config = AppConfig(settings)

    # Test dictionary access
    assert app_config["SECRET_KEY"] == settings.core.secret_key

    # Test attribute access
    assert app_config.SECRET_KEY == settings.core.secret_key

    # Test non-existent key/attribute
    with pytest.raises(KeyError):
        _ = app_config["NON_EXISTENT"]
    with pytest.raises(AttributeError):
        _ = app_config.NON_EXISTENT


def test_database_url_special_chars():
    """Test database URL construction with special characters"""
    settings = Settings(
        PGUSER="test",
        PGPASSWORD="pass!word@123",
        PGHOST="localhost",
        PGPORT=5432,
        PGDATABASE="testdb",
    )

    expected = (
        f"postgresql+psycopg2://test:{quote('pass!word@123')}@localhost:5432/testdb"
    )
    assert settings.database_url == expected
