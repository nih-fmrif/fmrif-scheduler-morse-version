"""LDAP authentication implementation"""

import secrets
import traceback
from datetime import datetime, timedelta
from typing import Optional, Tuple

import ldap3
from flask import current_app
from ldap3 import ALL, SUBTREE
from ldap3.core.exceptions import LDAPException

from ..config import settings
from .models import LDAPUser


class LDAPClient:
    def __init__(self):
        self.config = settings.ldap
        self._connection = None

    def _get_connection(
        self, user_dn: Optional[str] = None, password: Optional[str] = None
    ) -> Optional[ldap3.Connection]:
        """Get LDAP connection using either bind DN or user credentials"""
        try:
            # For authentication, always create a new connection
            if user_dn and password:
                server = ldap3.Server(
                    self.config.host,
                    port=self.config.port,
                    use_ssl=self.config.use_ssl,
                    get_info=ALL,
                )
                return ldap3.Connection(
                    server,
                    user=user_dn,
                    password=password,
                    authentication="SIMPLE",
                    auto_bind=True,
                )

            # For session validation, use/create persistent connection
            if self._connection is None or not self._connection.bound:
                server = ldap3.Server(
                    self.config.host,
                    port=self.config.port,
                    use_ssl=self.config.use_ssl,
                    get_info=ALL,
                )
                self._connection = ldap3.Connection(
                    server,
                    user=self.config.bind_dn,
                    password=self.config.bind_password,
                    authentication="SIMPLE",
                    auto_bind=True,
                    auto_referrals=False,
                    client_strategy=ldap3.SYNC,
                    pool_name="ldap_pool",
                    pool_size=5,
                    pool_lifetime=300,
                )
            return self._connection

        except Exception as e:
            current_app.logger.error(f"LDAP connection error: {str(e)}")
            self._connection = None
            raise

    def authenticate(
        self, username: str, password: str
    ) -> Tuple[bool, Optional[LDAPUser]]:
        """Authenticate user against LDAP server"""
        try:
            current_app.logger.info("=" * 50)
            current_app.logger.info("[AUTH] Starting authentication process")
            current_app.logger.info(f"[AUTH] Input username: {username}")
            current_app.logger.info(
                f"[AUTH] LDAP Server: {self.config.host}:{self.config.port}"
            )
            current_app.logger.info(f"[AUTH] SSL Enabled: {self.config.use_ssl}")
            current_app.logger.info("=" * 50)

            # Clean and validate username format
            if "@" in username:
                email = username.lower()
                current_app.logger.info(f"[EMAIL] Email format detected: {email}")

                current_app.logger.info(
                    "[CONN] Creating server connection for email lookup"
                )
                server = ldap3.Server(
                    self.config.host,
                    port=self.config.port,
                    use_ssl=self.config.use_ssl,
                    get_info=ldap3.ALL,
                )

                # Log detailed server info
                if server.info:
                    current_app.logger.info(f"[SERVER] Type: {server.info.vendor_name}")
                    current_app.logger.info(
                        f"[SERVER] Version: {server.info.vendor_version}"
                    )
                    current_app.logger.info(f"[SERVER] Schema: {server.schema}")

                current_app.logger.info("[BIND] Attempting anonymous bind")
                conn = ldap3.Connection(
                    server, authentication=ldap3.ANONYMOUS, auto_bind=False
                )

                bind_result = conn.bind()
                current_app.logger.info(f"[BIND] Anonymous bind result: {bind_result}")
                if not bind_result:
                    current_app.logger.error(
                        f"[BIND] Anonymous bind failed: {conn.result}"
                    )
                    return False, None

                search_filter = (
                    f"(&(objectClass={self.config.user_object_class})(mail={email}))"
                )
                current_app.logger.info(
                    f"[SEARCH] Email search filter: {search_filter}"
                )

                conn.search(
                    self.config.base_dn,
                    search_filter,
                    search_scope=ldap3.SUBTREE,
                    attributes=["sAMAccountName"],
                )

                if not conn.entries:
                    current_app.logger.warning("[SEARCH] No user found with email")
                    return False, None

                user_entry = conn.entries[0]
                username = str(user_entry.sAMAccountName)
                current_app.logger.info(f"[SEARCH] Found sAMAccountName: {username}")
            else:
                username = username.lower().replace(".nih", "")
                current_app.logger.info(f"[USER] Using direct username: {username}")

            current_app.logger.info("=" * 50)
            current_app.logger.info("[SEARCH] Starting user search phase")

            server = ldap3.Server(
                self.config.host,
                port=self.config.port,
                use_ssl=self.config.use_ssl,
                get_info=ldap3.ALL,
                mode="IP_V4_PREFERRED",
            )

            # Create connection with specific options for debugging
            conn = ldap3.Connection(
                server,
                authentication=ldap3.ANONYMOUS,
                auto_bind=False,
                receive_timeout=10,  # 10 seconds timeout
                return_empty_attributes=True,  # Show all attributes even if empty
            )

            bind_result = conn.bind()
            current_app.logger.info(f"[BIND] Anonymous bind result: {bind_result}")
            if not bind_result:
                current_app.logger.error(f"[BIND] Anonymous bind failed: {conn.result}")
                return False, None

            # Enhanced user search with more attributes
            search_filter = f"(&(objectClass={self.config.user_object_class})(sAMAccountName={username}))"
            current_app.logger.info(f"[SEARCH] User search filter: {search_filter}")

            # Request additional attributes to understand account status
            search_result = conn.search(
                self.config.base_dn,
                search_filter,
                search_scope=ldap3.SUBTREE,
                attributes=[
                    "distinguishedName",
                    "displayName",
                    "mail",
                    "department",
                    "userAccountControl",  # Account status flags
                    "lockoutTime",  # Account lockout status
                    "pwdLastSet",  # Password last set time
                    "accountExpires",  # Account expiration
                    "lastLogon",  # Last successful login
                    "badPwdCount",  # Failed password attempts
                    "msDS-UserAccountDisabled",  # Account disabled status
                ],
            )

            current_app.logger.info(f"[SEARCH] Search completed: {search_result}")
            current_app.logger.info(f"[SEARCH] Entries found: {len(conn.entries)}")

            if not conn.entries:
                current_app.logger.warning(
                    f"[SEARCH] No user found with sAMAccountName: {username}"
                )
                return False, None

            user_entry = conn.entries[0]

            # Log detailed user account information
            current_app.logger.info("[USER] Found user entry:")
            current_app.logger.info(
                f"[USER] DN: {user_entry.distinguishedName or 'Not Set'}"
            )
            current_app.logger.info(
                f"[USER] Display Name: {user_entry.displayName or 'Not Set'}"
            )
            current_app.logger.info(f"[USER] Email: {user_entry.mail or 'Not Set'}")
            current_app.logger.info(
                f"[USER] Department: {user_entry.department or 'Not Set'}"
            )

            # Enhanced account status logging
            current_app.logger.info("\n[STATUS] === DETAILED ACCOUNT STATUS CHECK ===")

            # Check msDS-UserAccountDisabled attribute first
            if hasattr(user_entry, "msDS-UserAccountDisabled"):
                disabled_status = user_entry["msDS-UserAccountDisabled"].value
                current_app.logger.info(
                    f"[STATUS] msDS-UserAccountDisabled: {disabled_status}"
                )
                if disabled_status:
                    current_app.logger.warning(
                        "[STATUS] Account is explicitly disabled via msDS-UserAccountDisabled"
                    )
            else:
                current_app.logger.info(
                    "[STATUS] msDS-UserAccountDisabled attribute not present"
                )

            # Detailed UAC flag analysis
            try:
                if (
                    hasattr(user_entry, "userAccountControl")
                    and user_entry.userAccountControl
                ):
                    uac = int(user_entry.userAccountControl.value)
                    current_app.logger.info(
                        f"[STATUS] User Account Control (Raw Value): {uac}"
                    )
                    current_app.logger.info("[STATUS] === UAC FLAG ANALYSIS ===")

                    # Define and check all possible UAC flags
                    uac_flags = {
                        0x0002: "ACCOUNTDISABLE",
                        0x0010: "LOCKOUT",
                        0x0020: "PASSWD_NOTREQD",
                        0x0200: "NORMAL_ACCOUNT",
                        0x0800: "INTERDOMAIN_TRUST_ACCOUNT",
                        0x1000: "WORKSTATION_TRUST_ACCOUNT",
                        0x2000: "SERVER_TRUST_ACCOUNT",
                        0x10000: "DONT_EXPIRE_PASSWORD",
                        0x20000: "MNS_LOGON_ACCOUNT",
                        0x40000: "SMARTCARD_REQUIRED",
                        0x80000: "TRUSTED_FOR_DELEGATION",
                        0x100000: "NOT_DELEGATED",
                        0x200000: "USE_DES_KEY_ONLY",
                        0x400000: "DONT_REQ_PREAUTH",
                        0x800000: "PASSWORD_EXPIRED",
                        0x1000000: "TRUSTED_TO_AUTH_FOR_DELEGATION",
                    }

                    for flag_value, flag_name in uac_flags.items():
                        if uac & flag_value:
                            current_app.logger.info(
                                f"[STATUS] Active Flag: {flag_name} (0x{flag_value:x})"
                            )
                            if flag_name == "ACCOUNTDISABLE":
                                current_app.logger.warning(
                                    "[STATUS] Account is disabled via UAC flag"
                                )

                    # Check account type
                    account_type = "Unknown"
                    if uac & 0x0200:
                        account_type = "Normal User Account"
                    elif uac & 0x0800:
                        account_type = "Interdomain Trust Account"
                    elif uac & 0x1000:
                        account_type = "Workstation Trust Account"
                    elif uac & 0x2000:
                        account_type = "Server Trust Account"
                    current_app.logger.info(f"[STATUS] Account Type: {account_type}")

                else:
                    current_app.logger.warning(
                        "[STATUS] No userAccountControl attribute available - cannot determine account status flags"
                    )
            except (ValueError, TypeError) as e:
                current_app.logger.error(
                    f"[STATUS] Error processing userAccountControl: {str(e)}"
                )

            current_app.logger.info("\n[STATUS] === ACCOUNT TIMESTAMPS ===")
            # Enhanced timestamp processing
            windows_tick = 10000000  # Number of 100-nanosecond intervals in a second
            windows_to_unix_epoch = (
                11644473600  # Seconds between Windows and Unix epochs
            )

            def windows_time_to_datetime(windows_time):
                """Convert Windows timestamp to human-readable format"""
                try:
                    if windows_time in (0, 9223372036854775807):  # Never expires
                        return "Never"
                    seconds_since_windows_epoch = int(windows_time) / windows_tick
                    unix_timestamp = seconds_since_windows_epoch - windows_to_unix_epoch
                    return datetime.fromtimestamp(unix_timestamp).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                except (ValueError, TypeError):
                    return "Invalid timestamp"

            # Process and log all relevant timestamps
            timestamp_attrs = {
                "pwdLastSet": "Password Last Set",
                "lastLogon": "Last Logon",
                "lastLogonTimestamp": "Last Logon Timestamp",
                "accountExpires": "Account Expires",
                "badPasswordTime": "Last Bad Password Attempt",
            }

            for attr, desc in timestamp_attrs.items():
                if hasattr(user_entry, attr) and getattr(user_entry, attr):
                    timestamp = getattr(user_entry, attr).value
                    human_time = windows_time_to_datetime(timestamp)
                    current_app.logger.info(
                        f"[STATUS] {desc}: {human_time} (Raw: {timestamp})"
                    )
                else:
                    current_app.logger.info(f"[STATUS] {desc}: Not Available")

            # Enhanced lockout status check
            current_app.logger.info("\n[STATUS] === LOCKOUT STATUS ===")
            if hasattr(user_entry, "lockoutTime") and user_entry.lockoutTime:
                lockout_time = int(user_entry.lockoutTime.value)
                if lockout_time > 0:
                    human_time = windows_time_to_datetime(lockout_time)
                    current_app.logger.warning(
                        f"[STATUS] Account is locked out since: {human_time}"
                    )
                else:
                    current_app.logger.info("[STATUS] Account is not locked out")
            else:
                current_app.logger.info("[STATUS] Lockout status not available")

            if hasattr(user_entry, "badPwdCount"):
                current_app.logger.info(
                    f"[STATUS] Bad password attempts: {user_entry.badPwdCount.value}"
                )

            # Log the exact DN we'll use for binding
            current_app.logger.info("\n[BIND] === BIND ATTEMPT DETAILS ===")
            user_dn = str(user_entry.distinguishedName)
            current_app.logger.info(f"[BIND] Using DN for bind: {user_dn}")
            current_app.logger.info(
                f"[BIND] DN format check: starts with 'CN=' - {user_dn.startswith('CN=')}"
            )
            current_app.logger.info(
                f"[BIND] DN format check: contains ',OU=Users,DC=nih,DC=gov' - {',OU=Users,DC=nih,DC=gov' in user_dn}"
            )

            current_app.logger.info("=" * 50)
            current_app.logger.info("[AUTH] Starting authentication phase")

            # Try authentication with detailed debugging
            auth_conn = ldap3.Connection(
                server,
                user=user_dn,
                password=password,
                authentication=ldap3.SIMPLE,
                read_only=True,
                auto_bind=False,
                receive_timeout=10,
                raise_exceptions=True,  # Raise exceptions for detailed error handling
            )

            try:
                current_app.logger.info("[BIND] Attempting bind with credentials")
                current_app.logger.info(
                    f"[BIND] Connection strategy: {auth_conn.strategy}"
                )
                current_app.logger.info(
                    f"[BIND] Authentication type: {auth_conn.authentication}"
                )

                bind_result = auth_conn.bind()
                current_app.logger.info(f"[BIND] Bind attempt completed: {bind_result}")

                if not bind_result:
                    error_msg = auth_conn.result.get("message", "")
                    desc = auth_conn.result.get("description", "")
                    data = (
                        error_msg.split("data ")[-1].split(",")[0]
                        if "data" in error_msg
                        else "unknown"
                    )

                    # Map common AD error codes to human-readable messages
                    error_codes = {
                        "525": "User not found",
                        "52e": "Invalid credentials (wrong password)",
                        "530": "Not permitted to logon at this time",
                        "531": "Not permitted to logon at this workstation",
                        "532": "Password expired",
                        "533": "Account disabled",
                        "534": "Account not found",
                        "701": "Account expired",
                        "773": "User must reset password",
                        "775": "User account locked",
                    }

                    error_message = error_codes.get(
                        data, "Unknown authentication error"
                    )

                    # Log a structured error message
                    current_app.logger.warning(
                        f"[AUTH] Authentication failed: {error_message}\n"
                        f"Error Code: {data}\n"
                        f"Description: {desc}"
                    )

                    # Add specific handling for common error codes
                    if data == "533":
                        current_app.logger.info(
                            "Error 533"
                            "[AUTH] Account is disabled in Active Directory.\n"
                            "This requires administrator action to enable the account."
                        )
                    elif data == "532":
                        current_app.logger.info(
                            "Error 532"
                            "[AUTH] Password has expired.\n"
                            "User should reset their password through NIH's password portal."
                        )
                    elif data == "775":
                        current_app.logger.info(
                            "Error 775"
                            "[AUTH] Account is locked.\n"
                            "This may be due to too many failed login attempts."
                        )

                    return False, None

            except ldap3.core.exceptions.LDAPOperationResult as e:
                # Handle specific LDAP operation errors (including invalid credentials)
                error_msg = str(e)
                error_data = None

                # Extract error code from the message
                if "data " in error_msg:
                    error_data = error_msg.split("data ")[-1].split(",")[0]

                if error_data == "533":
                    current_app.logger.warning(
                        "Error 533"
                        "[AUTH] Account is disabled.\n"
                        "Status: Account disabled in Active Directory\n"
                        "Action Required: Contact NIH IT support to enable the account"
                    )
                elif error_data == "52e":
                    current_app.logger.warning(
                        "Error 52e"
                        "[AUTH] Invalid credentials.\n"
                        "Status: Password verification failed\n"
                        "Action Required: Verify username and password"
                    )
                else:
                    current_app.logger.warning(
                        f"[AUTH] LDAP operation failed\n"
                        f"Status: {e.description}\n"
                        f"Details: {error_msg}"
                    )
                return False, None

            except ldap3.core.exceptions.LDAPBindError as e:
                # Handle specific LDAP bind errors
                current_app.logger.warning(
                    f"[AUTH] LDAP bind failed\n"
                    f"Status: Connection error during bind\n"
                    f"Details: {str(e)}"
                )
                return False, None

            except Exception as e:
                # Handle truly unexpected errors
                error_type = type(e).__name__
                current_app.logger.error(
                    f"[AUTH] Unexpected authentication error\n"
                    f"Type: {error_type}\n"
                    f"Details: {str(e)}"
                )
                # Only log debug info if explicitly enabled
                if current_app.debug and current_app.config.get(
                    "LDAP_DEBUG_TRACE", False
                ):
                    current_app.logger.debug(
                        f"[AUTH] Debug trace:\n{traceback.format_exc()}"
                    )
                return False, None

            current_app.logger.info("[AUTH] Bind successful!")

            # Get groups
            current_app.logger.info("[GROUPS] Retrieving user groups")
            groups = self._get_user_groups(username)
            current_app.logger.info(f"[GROUPS] Retrieved: {groups}")

            # Create user object
            current_app.logger.info("[TOKEN] Creating authentication token")
            token = secrets.token_urlsafe(32)
            expiry = datetime.utcnow() + timedelta(seconds=self.config.token_lifetime)

            user = LDAPUser(
                username=username,
                display_name=str(user_entry.displayName),
                email=str(user_entry.mail),
                groups=groups,
                token=token,
                token_expiry=expiry,
            )

            current_app.logger.info(
                f"[SUCCESS] Authentication successful for user: {user.username}"
            )
            current_app.logger.info("=" * 50)
            return True, user

        except (LDAPException, Exception) as e:
            current_app.logger.error(
                f"[ERROR] LDAP authentication error:\n"
                f"Error type: {type(e).__name__}\n"
                f"Error message: {str(e)}\n"
                f"Traceback:\n{traceback.format_exc()}"
            )
            return False, None

    def _get_user_groups(self, username: str) -> list[str]:
        """Get list of groups user belongs to"""
        try:
            conn = self._get_connection()
            if not conn:
                return []

            search_filter = f"(&{self.config.group_search_filter}(uniqueMember=uid={username},{self.config.base_dn}))"

            conn.search(
                self.config.group_dn,
                search_filter,
                search_scope=SUBTREE,
                attributes=["cn"],
            )

            groups = [str(entry.cn) for entry in conn.entries]
            return groups

        except (LDAPException, Exception):
            return []

    def validate_token(self, token: str) -> Optional[LDAPUser]:
        """Validate an authentication token"""
        # This would typically check against a token store
        # For now, we'll need to implement token storage
        return None
