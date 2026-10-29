#!/usr/bin/env python3
"""Smoke-check final response security headers for the externally served edge."""

from __future__ import annotations

import argparse
import os
import sys
from http.client import HTTPResponse
from urllib.parse import urljoin
from urllib.request import Request, urlopen


def _normalize_app_env(value: str | None) -> str:
    normalized = (value or "development").strip().lower().replace("-", "_")
    if normalized in {"", "dev", "development", "local", "test", "testing"}:
        return "development"
    if normalized in {"prod", "production", "stage", "staging"}:
        return "production"
    return normalized


def _default_base_url() -> str:
    if _normalize_app_env(os.getenv("APP_ENV")) != "production":
        return f"http://localhost:{os.getenv('APP_PORT', '5051')}"

    try:
        from scheduler.config import settings
    except Exception as exc:  # pragma: no cover - exercised via script execution
        raise RuntimeError(
            "Could not load application settings while deriving the production "
            "edge target. Ensure ENTRA__REDIRECT_URI is configured as an absolute "
            "URL ending with /auth/callback."
        ) from exc

    try:
        return settings.entra.edge_base_url
    except ValueError as exc:
        raise RuntimeError(
            "Could not derive the production edge target from ENTRA__REDIRECT_URI. "
            "Expected an absolute URL rooted at /auth/callback."
        ) from exc


def _parse_args() -> argparse.Namespace:
    default_base_url = _default_base_url()
    parser = argparse.ArgumentParser(
        description=(
            "Verify that the final served response exposes a single CSP authority "
            "and the expected baseline security headers."
        )
    )
    parser.add_argument(
        "--base-url",
        default=default_base_url,
        help=(
            "Base URL to probe. Defaults to the production edge derived from "
            "ENTRA__REDIRECT_URI, or http://localhost:$APP_PORT outside production."
        ),
    )
    parser.add_argument(
        "--path",
        default="/auth/login",
        help="Request path to probe. Defaults to /auth/login.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Request timeout in seconds. Defaults to 15.",
    )
    return parser.parse_args()


def _header_values(response: HTTPResponse, name: str) -> list[str]:
    values = [
        value.strip()
        for value in response.headers.get_all(name, failobj=[])
        if value and value.strip()
    ]
    if values:
        return values

    value = response.headers.get(name, "").strip()
    return [value] if value else []


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _print_failure(message: str) -> int:
    print(f"edge-security-headers: FAIL {message}", file=sys.stderr)
    return 1


def _runtime_error_message(exc: RuntimeError) -> str:
    return (
        f"{exc}. For production, set ENTRA__REDIRECT_URI to the externally served "
        "callback URL such as https://scheduler.example.test/auth/callback. "
        "Outside production, the script probes http://localhost:$APP_PORT."
    )


def _assert_response_headers(response: HTTPResponse) -> None:
    x_content_type_options = _header_values(response, "X-Content-Type-Options")
    x_frame_options = _header_values(response, "X-Frame-Options")
    referrer_policy = _header_values(response, "Referrer-Policy")
    csp_values = _header_values(response, "Content-Security-Policy")
    csp_report_only_values = _header_values(
        response, "Content-Security-Policy-Report-Only"
    )
    reporting_endpoints = _header_values(response, "Reporting-Endpoints")
    hsts_values = _header_values(response, "Strict-Transport-Security")

    _require(
        x_content_type_options == ["nosniff"],
        f"Expected X-Content-Type-Options=nosniff, got {x_content_type_options!r}.",
    )
    _require(
        x_frame_options == ["DENY"],
        f"Expected X-Frame-Options=DENY, got {x_frame_options!r}.",
    )
    _require(
        referrer_policy == ["strict-origin-when-cross-origin"],
        f"Expected Referrer-Policy=strict-origin-when-cross-origin, got {referrer_policy!r}.",
    )

    total_csp_authorities = len(csp_values) + len(csp_report_only_values)
    _require(
        total_csp_authorities == 1,
        "Expected exactly one CSP authority at the final edge; "
        f"got CSP={csp_values!r} report-only={csp_report_only_values!r}.",
    )

    effective_csp = (csp_values or csp_report_only_values)[0]
    _require(
        "default-src 'self'" in effective_csp,
        f"Expected default-src 'self' in CSP, got {effective_csp!r}.",
    )
    _require(
        "script-src 'self'" in effective_csp,
        f"Expected script-src 'self' in CSP, got {effective_csp!r}.",
    )
    _require(
        "'strict-dynamic'" in effective_csp,
        f"Expected strict-dynamic in CSP, got {effective_csp!r}.",
    )
    _require(
        "script-src" in effective_csp and "'nonce-" in effective_csp,
        f"Expected a substituted script nonce in CSP, got {effective_csp!r}.",
    )
    _require(
        "script-src-attr 'none'" in effective_csp,
        f"Expected script-src-attr 'none' in CSP, got {effective_csp!r}.",
    )
    _require(
        "style-src 'self'" in effective_csp,
        f"Expected style-src 'self' in CSP, got {effective_csp!r}.",
    )
    _require(
        "style-src-attr 'none'" in effective_csp,
        f"Expected style-src-attr 'none' in CSP, got {effective_csp!r}.",
    )
    _require(
        "report-to csp-endpoint" in effective_csp,
        f"Expected report-to csp-endpoint in CSP, got {effective_csp!r}.",
    )
    _require(
        any('csp-endpoint="/csp-report"' in value for value in reporting_endpoints),
        'Expected Reporting-Endpoints to declare csp-endpoint="/csp-report", '
        f"got {reporting_endpoints!r}.",
    )
    _require(
        "'unsafe-inline'" not in effective_csp,
        f"Did not expect unsafe-inline in CSP, got {effective_csp!r}.",
    )
    _require(
        "{nonce}" not in effective_csp,
        f"Found unsubstituted nonce placeholder in CSP: {effective_csp!r}.",
    )

    final_scheme = response.geturl().split(":", 1)[0].lower()
    if final_scheme == "https":
        _require(
            len(hsts_values) == 1 and "max-age=" in hsts_values[0],
            f"Expected HSTS on HTTPS response, got {hsts_values!r}.",
        )
    else:
        _require(
            not hsts_values,
            f"Did not expect HSTS on non-HTTPS response, got {hsts_values!r}.",
        )

    print(f"edge-security-headers: PASS {response.geturl()}")
    print(f"  X-Content-Type-Options: {x_content_type_options[0]}")
    print(f"  X-Frame-Options: {x_frame_options[0]}")
    print(f"  Referrer-Policy: {referrer_policy[0]}")
    print(
        "  CSP authority: "
        + (
            "Content-Security-Policy"
            if csp_values
            else "Content-Security-Policy-Report-Only"
        )
    )
    print(f"  CSP: {effective_csp}")
    print(f"  Reporting-Endpoints: {reporting_endpoints!r}")
    if hsts_values:
        print(f"  Strict-Transport-Security: {hsts_values[0]}")
    else:
        print("  Strict-Transport-Security: <absent>")


def main() -> int:
    try:
        args = _parse_args()
    except RuntimeError as exc:
        return _print_failure(_runtime_error_message(exc))

    url = urljoin(args.base_url.rstrip("/") + "/", args.path.lstrip("/"))

    request = Request(url, headers={"Accept": "text/html"})
    with urlopen(request, timeout=args.timeout) as response:
        _require(
            200 <= response.status < 400,
            f"Expected a successful response from {url}, got {response.status}.",
        )
        _assert_response_headers(response)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        raise SystemExit(_print_failure(str(exc))) from exc
