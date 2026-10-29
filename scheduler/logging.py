"""Central logging configuration with optional sensitive-data redaction."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any, Iterable

_DEFAULT_REDACTION_TEXT = "[REDACTED]"
_DEFAULT_SENSITIVE_KEYS = frozenset(
    {
        "access_token",
        "id_token",
        "refresh_token",
        "client_secret",
        "code_verifier",
        "password",
        "authorization",
        "x_test_auth_secret",
        "cookie",
        "set_cookie",
        "state",
        "code",
    }
)

_BEARER_TOKEN_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]+=*")
_QUERY_VALUE_PATTERN = re.compile(
    r"(?i)([?&](?:access_token|id_token|refresh_token|client_secret|code_verifier|state|code|password)=)([^&#\s]+)"
)
_KEY_VALUE_PATTERN = re.compile(
    r'(?i)(["\']?(?:access_token|id_token|refresh_token|client_secret|code_verifier|password|authorization|x-test-auth-secret|x_test_auth_secret|cookie|set-cookie|set_cookie|state|code)["\']?\s*[:=]\s*["\']?)([^"\'\s,};&]+)'
)


def _normalize_key(value: str) -> str:
    return value.strip().lower().replace("-", "_")


def redact_string(value: str, redaction_text: str = _DEFAULT_REDACTION_TEXT) -> str:
    """Redact sensitive values embedded in a log message string."""
    out = _BEARER_TOKEN_PATTERN.sub(f"Bearer {redaction_text}", value)
    out = _QUERY_VALUE_PATTERN.sub(lambda m: f"{m.group(1)}{redaction_text}", out)
    out = _KEY_VALUE_PATTERN.sub(lambda m: f"{m.group(1)}{redaction_text}", out)
    return out


def redact_value(
    value: Any,
    *,
    redaction_text: str = _DEFAULT_REDACTION_TEXT,
    sensitive_keys: Iterable[str] | None = None,
) -> Any:
    """Recursively redact sensitive values embedded in strings and mappings."""

    normalized_keys = {
        _normalize_key(key) for key in (sensitive_keys or _DEFAULT_SENSITIVE_KEYS)
    }

    def _redact(inner: Any) -> Any:
        if isinstance(inner, str):
            return redact_string(inner, redaction_text)
        if isinstance(inner, Mapping):
            return {
                key: (
                    redaction_text
                    if _normalize_key(str(key)) in normalized_keys
                    else _redact(item)
                )
                for key, item in inner.items()
            }
        if isinstance(inner, tuple):
            return tuple(_redact(item) for item in inner)
        if isinstance(inner, list):
            return [_redact(item) for item in inner]
        if isinstance(inner, set):
            return {_redact(item) for item in inner}
        return inner

    return _redact(value)


class SensitiveDataFilter(logging.Filter):
    """Redact sensitive data from log records unless explicitly disabled."""

    def __init__(
        self,
        *,
        reveal_sensitive_data: bool = False,
        redaction_text: str = _DEFAULT_REDACTION_TEXT,
        sensitive_keys: Iterable[str] | None = None,
    ) -> None:
        super().__init__()
        keys = sensitive_keys or _DEFAULT_SENSITIVE_KEYS
        self._reveal_sensitive_data = reveal_sensitive_data
        self._redaction_text = redaction_text
        self._sensitive_keys = {_normalize_key(k) for k in keys}

    def _redact_keyed_value(self, key: Any, value: Any) -> Any:
        if _normalize_key(str(key)) in self._sensitive_keys:
            return self._redaction_text
        return self._redact_value(value)

    def _redact_value(self, value: Any) -> Any:
        return redact_value(
            value,
            redaction_text=self._redaction_text,
            sensitive_keys=self._sensitive_keys,
        )

    def filter(self, record: logging.LogRecord) -> bool:
        if self._reveal_sensitive_data:
            return True

        record.msg = self._redact_value(record.msg)
        if isinstance(record.args, Mapping):
            record.args = {
                k: self._redact_keyed_value(k, v) for k, v in record.args.items()
            }
        elif isinstance(record.args, tuple):
            record.args = tuple(self._redact_value(v) for v in record.args)
        elif record.args:
            record.args = self._redact_value(record.args)
        return True


def _install_filter(target: Any, redact_filter: SensitiveDataFilter) -> None:
    if any(isinstance(existing, SensitiveDataFilter) for existing in target.filters):
        return
    target.addFilter(redact_filter)


def configure_app_logging(app: Any) -> None:
    """Apply app-wide logging level and sensitive-data redaction policy."""
    level_name = str(app.config.get("LOG_LEVEL", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)

    app.logger.setLevel(level)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    if not root_logger.handlers:
        logging.basicConfig(level=level)

    redact_filter = SensitiveDataFilter(
        reveal_sensitive_data=bool(app.config.get("LOG_REVEAL_SENSITIVE_DATA", False)),
        redaction_text=str(
            app.config.get("LOG_REDACTION_TEXT", _DEFAULT_REDACTION_TEXT)
        ),
    )

    _install_filter(app.logger, redact_filter)
    _install_filter(root_logger, redact_filter)

    for handler in app.logger.handlers:
        _install_filter(handler, redact_filter)
        handler.setLevel(level)

    for handler in root_logger.handlers:
        _install_filter(handler, redact_filter)
        handler.setLevel(level)

    if app.config.get("LOG_REVEAL_SENSITIVE_DATA"):
        app.logger.warning("Sensitive log redaction is disabled by configuration")
