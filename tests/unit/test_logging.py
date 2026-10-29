import logging

from flask import Flask

from scheduler.logging import SensitiveDataFilter, configure_app_logging, redact_string


def test_redact_string_masks_query_and_bearer_tokens():
    message = (
        "callback url=/auth/callback?code=abc123&state=xyz "
        "Authorization: Bearer eyJhbGciOi..."
    )
    redacted = redact_string(message)
    assert "abc123" not in redacted
    assert "xyz" not in redacted
    assert "eyJhbGciOi" not in redacted
    assert "[REDACTED]" in redacted


def test_sensitive_data_filter_redacts_mapping_args():
    logger = logging.getLogger("test-sensitive-filter")
    record = logger.makeRecord(
        name="test-sensitive-filter",
        level=logging.INFO,
        fn=__file__,
        lno=1,
        msg="payload=%s",
        args=({"access_token": "secret-token", "status": "ok"},),
        exc_info=None,
    )

    redact_filter = SensitiveDataFilter()
    assert redact_filter.filter(record) is True
    rendered = record.getMessage()
    assert "secret-token" not in rendered
    assert "[REDACTED]" in rendered
    assert "ok" in rendered


def test_sensitive_data_filter_can_be_disabled():
    logger = logging.getLogger("test-sensitive-filter-disabled")
    record = logger.makeRecord(
        name="test-sensitive-filter-disabled",
        level=logging.INFO,
        fn=__file__,
        lno=1,
        msg="Authorization: Bearer top-secret-token",
        args=(),
        exc_info=None,
    )

    redact_filter = SensitiveDataFilter(reveal_sensitive_data=True)
    assert redact_filter.filter(record) is True
    assert "top-secret-token" in record.getMessage()


def test_configure_app_logging_installs_filter():
    app = Flask(__name__)
    app.config.update(
        LOG_LEVEL="DEBUG",
        LOG_REVEAL_SENSITIVE_DATA=False,
        LOG_REDACTION_TEXT="[MASKED]",
    )

    configure_app_logging(app)

    assert any(isinstance(f, SensitiveDataFilter) for f in app.logger.filters)
