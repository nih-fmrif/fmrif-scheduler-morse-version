import json

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from scheduler.auth import jwt_utils
from scheduler.config import EntraConfig, settings
from scheduler.logic.core import scoped_user_id_from_identifier


@pytest.fixture(autouse=True)
def reset_jwks_cache(monkeypatch):
    """Reset JWKS cache before each test to avoid cross-test bleed."""
    monkeypatch.setattr(jwt_utils, "_CACHE", jwt_utils._JWKSCache())


def _build_test_token(
    audience: str, issuer: str, kid: str = "test-key"
) -> tuple[str, dict]:
    """Create a signed JWT and matching JWKS entry."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(public_key))
    jwk["kid"] = kid
    jwk["alg"] = "RS256"

    token = jwt.encode(
        {"email": "contact002@example.org", "aud": audience, "iss": issuer},
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )
    return token, jwk


def test_verify_jwt_with_mock_jwks(monkeypatch):
    tenant_id = "tenant-id"
    config = EntraConfig(
        client_id="client-id",
        tenant_id=tenant_id,
        discovery_url="https://example.test/.well-known/openid-configuration",
    )
    issuer = config.issuer
    token, jwk = _build_test_token(audience="api://client-id", issuer=issuer)

    monkeypatch.setattr(settings, "entra", config)
    monkeypatch.setattr(
        jwt_utils,
        "_fetch_openid_configuration",
        lambda discovery_url, cache_ttl: {"jwks_uri": "https://example.test/jwks"},
    )
    monkeypatch.setattr(jwt_utils, "_fetch_jwks", lambda jwks_uri, cache_ttl: [jwk])

    claims, error = jwt_utils.verify_jwt(token)

    assert error is None
    assert claims is not None
    assert claims["email"] == "contact002@example.org"
    assert claims["aud"] == "api://client-id"


def test_verify_jwt_rejects_wrong_audience(monkeypatch):
    config = EntraConfig(
        client_id="client-id",
        tenant_id="tenant-id",
        discovery_url="https://example.test/.well-known/openid-configuration",
    )
    issuer = config.issuer
    token, jwk = _build_test_token(audience="other-audience", issuer=issuer)

    monkeypatch.setattr(settings, "entra", config)
    monkeypatch.setattr(
        jwt_utils,
        "_fetch_openid_configuration",
        lambda discovery_url, cache_ttl: {"jwks_uri": "https://example.test/jwks"},
    )
    monkeypatch.setattr(jwt_utils, "_fetch_jwks", lambda jwks_uri, cache_ttl: [jwk])

    claims, error = jwt_utils.verify_jwt(token)

    assert claims is None
    assert error is not None


def test_verify_jwt_rejects_disallowed_algorithm(monkeypatch):
    config = EntraConfig(
        client_id="client-id",
        tenant_id="tenant-id",
        discovery_url="https://example.test/.well-known/openid-configuration",
        allowed_algorithms=["RS256"],
    )
    issuer = config.issuer
    token, jwk = _build_test_token(audience="api://client-id", issuer=issuer)

    monkeypatch.setattr(settings, "entra", config)
    monkeypatch.setattr(
        jwt_utils,
        "_fetch_openid_configuration",
        lambda discovery_url, cache_ttl: {"jwks_uri": "https://example.test/jwks"},
    )
    monkeypatch.setattr(jwt_utils, "_fetch_jwks", lambda jwks_uri, cache_ttl: [jwk])
    monkeypatch.setattr(
        jwt_utils.jwt,
        "get_unverified_header",
        lambda _: {"kid": "test-key", "alg": "HS256"},
    )

    claims, error = jwt_utils.verify_jwt(token)

    assert claims is None
    assert error is not None
    assert "Unsupported token signing algorithm" in error


def test_extract_bearer_token():
    auth_header = "Bearer abc.def.ghi"
    assert jwt_utils.extract_bearer_token(auth_header) == "abc.def.ghi"
    assert jwt_utils.extract_bearer_token("Basic something") is None
    assert jwt_utils.extract_bearer_token(None) is None


def test_user_from_claims_requires_preferred_username():
    with pytest.raises(ValueError, match="preferred_username"):
        jwt_utils.user_from_claims({})
    with pytest.raises(ValueError, match="preferred_username"):
        jwt_utils.user_from_claims({"email": "contact003@example.org"})


def test_user_from_claims_rejects_invalid_preferred_username_email(monkeypatch):
    errors: list[str] = []
    monkeypatch.setattr(
        jwt_utils,
        "_log_error",
        lambda message, *args: errors.append(message % args if args else message),
    )

    with pytest.raises(ValueError, match="valid email"):
        jwt_utils.user_from_claims({"preferred_username": "not-an-email"})

    assert any("not a valid email address" in error for error in errors)


def test_user_from_claims_uses_preferred_username_only():
    claims = {"preferred_username": "contact003@example.org", "name": "Tester"}
    user = jwt_utils.user_from_claims(claims)

    assert user.username == scoped_user_id_from_identifier("contact003@example.org")
    assert user.email == "contact003@example.org"
    assert user.display_name == "Tester"
