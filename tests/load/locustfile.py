from __future__ import annotations

import json
import os
import time
from itertools import count
from pathlib import Path
from threading import Lock

from locust import HttpUser, between, events, task
from requests import Response

from scheduler.load_test_support import (
    Assignment,
    classify_scheduler_save,
    extract_csrf_token,
    extract_first_assignment,
    jump_day,
    synthetic_slot_id,
)

_USER_COUNTER = count(1)
_WAIT_MIN_SECONDS = float(os.getenv("LOAD_WAIT_MIN_SECONDS", "0.5"))
_WAIT_MAX_SECONDS = float(os.getenv("LOAD_WAIT_MAX_SECONDS", "2.0"))
_WRITE_OFFSET_DAYS = int(os.getenv("LOAD_WRITE_OFFSET_DAYS", "0"))
_READ_START = os.getenv("LOAD_READ_START", "2035-03-10")
_UNIQUE_START = jump_day(
    os.getenv("LOAD_UNIQUE_START", "2036-01-10"), _WRITE_OFFSET_DAYS
)
_CONFLICT_START = jump_day(
    os.getenv("LOAD_CONFLICT_START", "2035-05-10"), _WRITE_OFFSET_DAYS
)
_DEVICE_ID = os.getenv("LOAD_DEVICE", "d")
_CONFLICT_WINDOW_SECONDS = max(5, int(os.getenv("LOAD_CONFLICT_WINDOW_SECONDS", "30")))
_SEND_NOTIFICATIONS = (
    os.getenv("LOAD_SEND_NOTIFICATIONS", "false").strip().lower() == "true"
)
_PASS_NAME = os.getenv("LOAD_PASS_NAME", "load")
_RESULTS_DIR = Path(os.getenv("LOAD_RESULTS_DIR", "test-results"))
_OUTCOME_LOCK = Lock()
_WRITE_OUTCOMES = {
    "saved": 0,
    "conflict": 0,
    "error": 0,
    "noop": 0,
}
_NOTIFICATION_OUTCOMES = {
    "success": 0,
    "skipped": 0,
    "failed": 0,
    "address": 0,
}
_UNEXPECTED_NOTIFICATION_OUTCOMES: dict[str, int] = {}
_UNIQUE_SLOT_COUNTER = count(0)


def _session_key(actor_index: int) -> str:
    return f"l{actor_index:05x}"[-6:]


def _hour_window(actor_index: int) -> str:
    first_hour = 8 + (actor_index % 4)
    return ",".join(str(hour) for hour in range(first_hour, first_hour + 4))


def _record_write_outcome(outcome: str) -> None:
    with _OUTCOME_LOCK:
        _WRITE_OUTCOMES[outcome] = _WRITE_OUTCOMES.get(outcome, 0) + 1


def _record_notification_outcomes(payload: dict[str, object]) -> None:
    notifications = payload.get("notifications")
    if not isinstance(notifications, list):
        return
    with _OUTCOME_LOCK:
        for row in notifications:
            if not isinstance(row, dict):
                continue
            msg = str(row.get("msg", "")).strip().lower()
            if msg in _NOTIFICATION_OUTCOMES:
                _NOTIFICATION_OUTCOMES[msg] += 1
            elif msg:
                _UNEXPECTED_NOTIFICATION_OUTCOMES[msg] = (
                    _UNEXPECTED_NOTIFICATION_OUTCOMES.get(msg, 0) + 1
                )


@events.quitting.add_listener
def _write_outcome_summary(environment, **_kwargs) -> None:
    _RESULTS_DIR.mkdir(exist_ok=True)
    summary = {
        "pass_name": _PASS_NAME,
        "send_notifications": _SEND_NOTIFICATIONS,
        "write_outcomes": dict(_WRITE_OUTCOMES),
        "notification_outcomes": dict(_NOTIFICATION_OUTCOMES),
        "unexpected_notification_outcomes": dict(_UNEXPECTED_NOTIFICATION_OUTCOMES),
    }
    output = _RESULTS_DIR / f"locust-moderate-{_PASS_NAME}-outcomes.json"
    output.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


class SchedulerLoadUser(HttpUser):
    wait_time = between(_WAIT_MIN_SECONDS, _WAIT_MAX_SECONDS)

    def on_start(self) -> None:
        self.actor_index = next(_USER_COUNTER)
        self.session_key = _session_key(self.actor_index)
        self.shared_secret = os.getenv("AUTH_TEST__SHARED_SECRET", "").strip()
        if not self.shared_secret:
            raise RuntimeError("AUTH_TEST__SHARED_SECRET must be set for load testing.")

        self.authenticate()
        self.assignment = self.discover_assignment()

    def on_stop(self) -> None:
        self.client.delete(
            "/auth/test/session",
            headers={"X-Test-Auth-Secret": self.shared_secret},
            name="/auth/test/session[delete]",
        )

    def authenticate(self) -> None:
        auth_ok = False
        with self.client.post(
            "/auth/test/session",
            headers={
                "X-Test-Auth-Secret": self.shared_secret,
                "Content-Type": "application/json",
            },
            json={
                "profile": "admin",
                "reset_profile_state": True,
                "session_key": self.session_key,
            },
            name="/auth/test/session[post]",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(
                    f"mock auth failed ({response.status_code}): {response.text[:200]}"
                )
            else:
                response.success()
                auth_ok = True

        if not auth_ok:
            raise RuntimeError("Mock auth session setup failed.")

        shell_ok = False
        with self.client.get("/", name="/", catch_response=True) as response:
            if response.status_code != 200:
                response.failure(f"home page failed ({response.status_code})")
            elif (
                'class="user-menu"' in response.text
                and "logout" in response.text.lower()
            ):
                response.success()
                shell_ok = True
            else:
                response.failure(
                    "authenticated shell markers were not visible after mock auth"
                )

        if not shell_ok:
            raise RuntimeError(
                "Authenticated app shell was not visible after mock auth."
            )

    def discover_assignment(self) -> Assignment:
        _, html_text = self.fetch_editor_page(_READ_START, name="/device/[discover]")
        assignment = extract_first_assignment(html_text)
        if assignment is None:
            raise RuntimeError(
                f"Unable to discover a schedulable assignment for device {_DEVICE_ID}."
            )
        return assignment

    def fetch_editor_page(self, start: str, *, name: str) -> tuple[str, str]:
        with self.client.get(
            f"/device/{_DEVICE_ID}?start={start}&days=2",
            name=name,
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"editor page failed ({response.status_code})")
                return "", ""
            csrf_token = extract_csrf_token(response.text)
            if not csrf_token:
                response.failure("editor page did not expose a csrf_token")
                return "", ""
            response.success()
            return csrf_token, response.text

    def submit_scheduler_diff(
        self,
        *,
        start: str,
        slot_date: str,
        hour: int,
        request_name: str,
        allow_conflict: bool,
    ) -> None:
        csrf_token, _ = self.fetch_editor_page(start, name="/device/[write-page]")
        if not csrf_token:
            return

        slot_id = synthetic_slot_id(slot_date, hour)
        diff = {
            "id": slot_id,
            "date": slot_date,
            "hour": hour,
            "group": ["", self.assignment.group],
            "member": ["", self.assignment.member],
        }

        with self.client.post(
            f"/device/{_DEVICE_ID}?start={start}&days=2",
            json={
                "csrf_token": csrf_token,
                "payload": {"diffs": [diff], "notify": _SEND_NOTIFICATIONS},
            },
            name=request_name,
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(
                    f"save failed ({response.status_code}): {response.text[:200]}"
                )
                return

            payload = self.parse_json_response(response)
            if payload is None:
                return

            outcome = classify_scheduler_save(payload, slot_id)
            _record_write_outcome(outcome)
            _record_notification_outcomes(payload)
            if outcome == "saved":
                response.success()
                return
            if allow_conflict and outcome == "conflict":
                response.success()
                return
            response.failure(f"unexpected save outcome={outcome}: {payload}")

    @staticmethod
    def parse_json_response(response: Response) -> dict[str, object] | None:
        try:
            payload = response.json()
        except ValueError:
            response.failure(f"response was not valid json: {response.text[:200]}")
            return None

        if not isinstance(payload, dict):
            response.failure(f"response json was not an object: {payload!r}")
            return None
        return payload

    @task(4)
    def read_device_page(self) -> None:
        self.client.get(
            f"/device/{_DEVICE_ID}?start={_READ_START}&days=7",
            name="/device/[page]",
        )

    @task(6)
    def read_schedule_rows(self) -> None:
        hours = _hour_window(self.actor_index)
        with self.client.get(
            f"/json/v1/device/{_DEVICE_ID}/schedule-rows?start={_READ_START}&days=7&hours={hours}",
            name="/json/v1/device/[schedule-rows]",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"schedule rows failed ({response.status_code})")
                return
            try:
                payload = response.json()
            except ValueError:
                response.failure(
                    f"schedule rows returned invalid json: {response.text[:200]}"
                )
                return
            rows = payload.get("rows") if isinstance(payload, dict) else None
            if not isinstance(rows, list) or len(rows) == 0:
                response.failure(f"schedule rows payload missing rows: {payload!r}")
                return
            response.success()

    @task(2)
    def read_next_day(self) -> None:
        with self.client.get(
            f"/json/v1/device/{_DEVICE_ID}/schedule-next-day?start={_READ_START}&direction=1",
            name="/json/v1/device/[schedule-next-day]",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"next day failed ({response.status_code})")
                return
            try:
                payload = response.json()
            except ValueError:
                response.failure(
                    f"next day returned invalid json: {response.text[:200]}"
                )
                return
            if not isinstance(payload, dict) or "date" not in payload:
                response.failure(f"next day payload missing date: {payload!r}")
                return
            response.success()

    @task(2)
    def write_unique_slot(self) -> None:
        slot_index = next(_UNIQUE_SLOT_COUNTER)
        start = jump_day(_UNIQUE_START, slot_index)
        hour = 8 + ((self.actor_index + slot_index) % 4)
        self.submit_scheduler_diff(
            start=start,
            slot_date=start,
            hour=hour,
            request_name="/device/[write-unique]",
            allow_conflict=False,
        )

    @task(1)
    def write_conflict_slot(self) -> None:
        bucket = int(time.time() // _CONFLICT_WINDOW_SECONDS)
        start = jump_day(_CONFLICT_START, bucket % 45)
        hour = 8 + (bucket % 3)
        self.submit_scheduler_diff(
            start=start,
            slot_date=start,
            hour=hour,
            request_name="/device/[write-conflict]",
            allow_conflict=True,
        )
