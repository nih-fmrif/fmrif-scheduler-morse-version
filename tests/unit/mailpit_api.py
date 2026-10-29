"""Mailpit API helpers for optional email end-to-end test coverage."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
from urllib import parse, request
from urllib.error import URLError


@dataclass(frozen=True)
class MailpitConfig:
    api_base_url: str
    smtp_host: str
    smtp_port: int


def _parse_port(raw: str, *, default: int) -> int:
    token = (raw or "").strip()
    if not token.isdigit():
        return default
    port = int(token)
    if port < 1 or port > 65535:
        return default
    return port


def mailpit_config_from_env() -> Optional[MailpitConfig]:
    base_url = (os.getenv("MAILPIT_API_BASE_URL", "") or "").strip()
    if base_url == "":
        port = _parse_port(os.getenv("MAILPIT__PORT", ""), default=0)
        if port <= 0:
            return None
        base_url = f"http://127.0.0.1:{port}"
    base_url = base_url.rstrip("/")

    smtp_host = (os.getenv("MAILPIT_SMTP_HOST", "") or "").strip() or "127.0.0.1"
    smtp_port = _parse_port(
        os.getenv("MAILPIT__SMTP_PORT", "") or os.getenv("MAIL__PORT", ""),
        default=1025,
    )

    return MailpitConfig(
        api_base_url=base_url,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
    )


def _request_bytes(
    cfg: MailpitConfig,
    path: str,
    *,
    method: str = "GET",
    timeout_seconds: float = 2.0,
) -> bytes:
    url = f"{cfg.api_base_url}{path}"
    req = request.Request(url, method=method)
    with request.urlopen(req, timeout=timeout_seconds) as response:
        return response.read()


def _request_json(
    cfg: MailpitConfig,
    path: str,
    *,
    method: str = "GET",
    timeout_seconds: float = 2.0,
) -> Dict[str, Any]:
    payload = _request_bytes(
        cfg,
        path,
        method=method,
        timeout_seconds=timeout_seconds,
    )
    body = payload.decode("utf-8", errors="replace")
    data: Any = json.loads(body) if body else {}
    if isinstance(data, dict):
        return data
    return {}


def mailpit_available(cfg: MailpitConfig) -> bool:
    try:
        _request_json(cfg, "/api/v1/info", timeout_seconds=1.5)
    except (URLError, OSError, TimeoutError, json.JSONDecodeError):
        return False
    return True


def clear_mailpit_messages(cfg: MailpitConfig) -> None:
    _request_bytes(cfg, "/api/v1/messages", method="DELETE", timeout_seconds=2.0)


def list_mailpit_messages(cfg: MailpitConfig) -> List[Dict[str, Any]]:
    payload = _request_json(cfg, "/api/v1/messages", timeout_seconds=2.0)
    messages = payload.get("messages", [])
    if isinstance(messages, list):
        return [dict(item) for item in messages if isinstance(item, dict)]
    return []


def get_mailpit_message(cfg: MailpitConfig, message_id: str) -> Dict[str, Any]:
    safe_message_id = parse.quote((message_id or "").strip(), safe="")
    return _request_json(cfg, f"/api/v1/message/{safe_message_id}", timeout_seconds=2.0)


def wait_for_mailpit_message(
    cfg: MailpitConfig,
    predicate: Callable[[Dict[str, Any]], bool],
    *,
    timeout_seconds: float = 10.0,
    poll_interval_seconds: float = 0.2,
) -> Optional[Dict[str, Any]]:
    deadline = time.monotonic() + max(timeout_seconds, 0.1)
    while True:
        for message in list_mailpit_messages(cfg):
            if predicate(message):
                return message

        if time.monotonic() >= deadline:
            return None
        time.sleep(max(poll_interval_seconds, 0.05))
