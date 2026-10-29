#!/usr/bin/env python3
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from urllib.error import URLError
from urllib.parse import urljoin, urlparse
from urllib.request import urlopen


@dataclass(frozen=True)
class LoadPass:
    name: str
    suppress_mail: bool
    write_offset_days: int
    send_notifications: bool


def server_command(host: str, port: int) -> Sequence[str]:
    server_kind = os.getenv("LOAD_APP_SERVER", "gunicorn").strip().lower()
    if server_kind == "flask":
        return ["flask", "run", "--host", host, "--port", str(port)]
    if server_kind == "gunicorn":
        workers = os.getenv("LOAD_GUNICORN_WORKERS", "4").strip() or "4"
        worker_class = os.getenv("LOAD_GUNICORN_WORKER_CLASS", "sync").strip() or "sync"
        timeout = os.getenv("LOAD_GUNICORN_TIMEOUT", "120").strip() or "120"
        command = [
            "gunicorn",
            "--bind",
            f"{host}:{port}",
            "--workers",
            workers,
            "--worker-class",
            worker_class,
            "--timeout",
            timeout,
            "--access-logfile",
            "-",
            "--error-logfile",
            "-",
            "scheduler.wsgi:app",
        ]
        threads = os.getenv("LOAD_GUNICORN_THREADS", "").strip()
        if threads:
            command[1:1] = ["--threads", threads]
        return command
    raise SystemExit("LOAD_APP_SERVER must be one of: gunicorn, flask")


def normalize_base_url() -> str:
    raw = (
        os.getenv("TEST_BASE_URL")
        or f"http://localhost:{os.getenv('APP_PORT', '5051')}"
    ).strip()
    return raw.rstrip("/")


def wait_for_server(url: str, *, timeout_seconds: int = 120) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=2) as response:
                if 200 <= response.status < 500:
                    return
        except URLError:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for app server readiness at {url}")


def terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=10)
        return
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def parse_profile() -> list[LoadPass]:
    token = os.getenv("LOAD_PROFILE", "both").strip().lower()
    write_spacing_days = int(os.getenv("LOAD_PASS_WRITE_SPACING_DAYS", "3650"))
    if token == "both":
        return [
            LoadPass(
                name="scheduler",
                suppress_mail=True,
                write_offset_days=0,
                send_notifications=False,
            ),
            LoadPass(
                name="notify",
                suppress_mail=False,
                write_offset_days=write_spacing_days,
                send_notifications=True,
            ),
        ]
    if token == "scheduler":
        return [
            LoadPass(
                name="scheduler",
                suppress_mail=True,
                write_offset_days=0,
                send_notifications=False,
            )
        ]
    if token == "notify":
        return [
            LoadPass(
                name="notify",
                suppress_mail=False,
                write_offset_days=0,
                send_notifications=True,
            )
        ]
    raise SystemExit("LOAD_PROFILE must be one of: both, scheduler, notify")


def run_locust_pass(
    repo_root: Path,
    results_dir: Path,
    parsed_base_url,
    *,
    base_env: dict[str, str],
    load_pass: LoadPass,
) -> int:
    env = base_env.copy()
    env["MAIL__SUPPRESS_SEND"] = "true" if load_pass.suppress_mail else "false"
    env["LOAD_WRITE_OFFSET_DAYS"] = str(load_pass.write_offset_days)
    env["LOAD_SEND_NOTIFICATIONS"] = "true" if load_pass.send_notifications else "false"
    env["LOAD_PASS_NAME"] = load_pass.name
    env["LOAD_RESULTS_DIR"] = str(results_dir)
    report_prefix = results_dir / f"locust-moderate-{load_pass.name}"
    command = [
        sys.executable,
        "-m",
        "locust",
        "-f",
        str(repo_root / "tests" / "load" / "locustfile.py"),
        "--headless",
        "--host",
        f"{parsed_base_url.scheme}://{parsed_base_url.hostname or 'localhost'}:{parsed_base_url.port or 5051}",
        "--users",
        os.getenv("LOAD_USERS", "10"),
        "--spawn-rate",
        os.getenv("LOAD_SPAWN_RATE", "2"),
        "--run-time",
        os.getenv("LOAD_RUN_TIME", "5m"),
        "--stop-timeout",
        "30",
        "--only-summary",
        "--exit-code-on-error",
        "1",
        "--html",
        str(report_prefix.with_suffix(".html")),
        "--csv",
        str(report_prefix),
    ]
    print(
        f"=== Running load pass: {load_pass.name} "
        f"(mail_suppressed={'true' if load_pass.suppress_mail else 'false'}, "
        f"send_notifications={'true' if load_pass.send_notifications else 'false'}, "
        f"write_offset_days={load_pass.write_offset_days}) ===",
        flush=True,
    )
    return subprocess.call(command, cwd=repo_root, env=env)


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    results_dir = repo_root / "test-results"
    results_dir.mkdir(exist_ok=True)

    base_url = normalize_base_url()
    parsed = urlparse(base_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 5051
    readiness_url = urljoin(f"{parsed.scheme}://{host}:{port}", "/robots.txt")

    env = os.environ.copy()
    env["FLASK_APP"] = env.get("FLASK_APP", "scheduler.app:create_app")

    server = subprocess.Popen(
        list(server_command(host, port)),
        cwd=repo_root,
        env=env,
    )

    try:
        wait_for_server(readiness_url)
        exit_codes = [
            run_locust_pass(
                repo_root,
                results_dir,
                parsed,
                base_env=env,
                load_pass=load_pass,
            )
            for load_pass in parse_profile()
        ]
        return 0 if all(code == 0 for code in exit_codes) else 1
    finally:
        terminate_process(server)


if __name__ == "__main__":
    raise SystemExit(main())
