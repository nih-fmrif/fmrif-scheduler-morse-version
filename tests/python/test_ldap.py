import socket

import ldap3
import pytest

from scheduler.config import settings


def can_connect_to_ldap(host=None):
    """Check if we can reach the LDAP server"""
    host = host or settings.ldap.host
    try:
        sock = socket.create_connection((host, settings.ldap.port), timeout=2)
        sock.close()
        return True
    except (socket.timeout, socket.error):
        return False


@pytest.fixture
def ldap_connection():
    """Fixture to create and teardown LDAP connection"""
    if not can_connect_to_ldap():
        pytest.skip("Cannot connect to LDAP server - Are you on NIH network/VPN?")

    server = ldap3.Server(
        settings.ldap.host,
        port=settings.ldap.port,
        use_ssl=settings.ldap.use_ssl,
        get_info=ldap3.ALL,
    )

    conn = ldap3.Connection(server)

    yield conn

    # Cleanup
    try:
        conn.unbind()
    except Exception:
        pass


@pytest.mark.ldap
@pytest.mark.skipif(
    not can_connect_to_ldap(),
    reason="LDAP server not reachable - Are you on NIH network/VPN?",
)
class TestLDAPConnection:
    """Test suite for LDAP authentication"""

    def test_anonymous_bind(self, ldap_connection):
        """Test anonymous binding to LDAP server"""
        try:
            result = ldap_connection.bind()
            assert result, "Anonymous bind failed"
        except ldap3.core.exceptions.LDAPException as e:
            pytest.fail(f"Anonymous bind failed: {str(e)}")

    @pytest.mark.parametrize(
        "test_user",
        [
            "rodgersleejg",  # Known test user
            "roopchansinghv",  # Another known test user
        ],
    )
    def test_user_search(self, ldap_connection, test_user):
        """Test user search and basic attribute retrieval"""
        # First bind anonymously
        ldap_connection.bind()

        # Search for user
        search_filter = f"(samaccountname={test_user})"
        try:
            result = ldap_connection.search(
                settings.ldap.base_dn,
                search_filter,
                attributes=settings.ldap.required_user_attrs,
            )

            # Verify search was successful
            assert result, f"Search failed for {test_user}"

            # Verify we got exactly one entry
            assert len(ldap_connection.entries) == 1, (
                f"Expected 1 result, got {len(ldap_connection.entries)}"
            )

            # Get the user entry
            user = ldap_connection.entries[0]

            # Verify required attributes are present
            for attr in settings.ldap.required_user_attrs:
                assert hasattr(user, attr), (
                    f"Required attribute {attr} missing from user data"
                )
                assert getattr(user, attr), f"Required attribute {attr} is empty"

            # Verify department is present (we don't care about specific value)
            assert hasattr(user, "department"), "Department attribute missing"

            # Verify account status is present
            assert hasattr(user, "msDS-UserAccountDisabled"), (
                "Account status attribute missing"
            )

        except ldap3.core.exceptions.LDAPException as e:
            pytest.fail(f"LDAP search failed: {str(e)}")

    @pytest.mark.parametrize("backup_host", settings.ldap.backup_hosts)
    def test_redundant_servers(self, backup_host):
        """Test connection to all redundant LDAP servers"""
        if not can_connect_to_ldap(backup_host):
            pytest.skip(f"Cannot connect to backup server {backup_host}")

        server = ldap3.Server(
            backup_host,
            port=settings.ldap.port,
            use_ssl=settings.ldap.use_ssl,
            get_info=ldap3.ALL,
        )

        conn = ldap3.Connection(server)

        try:
            result = conn.bind()
            assert result, f"Failed to bind to {backup_host}"
        except ldap3.core.exceptions.LDAPException as e:
            pytest.fail(f"Connection to {backup_host} failed: {str(e)}")
        finally:
            conn.unbind()


# Register the LDAP mark to avoid warning
def pytest_configure(config):
    """Register LDAP marker"""
    config.addinivalue_line("markers", "ldap: mark test as requiring LDAP connectivity")
