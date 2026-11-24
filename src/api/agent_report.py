"""Opt-in manager reports; all HTTP work runs outside the event loop."""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from src.api.request_monitor import active_request_count, consume_request_activity
from src.logger import get_logger

logger = get_logger(__name__)

REPORT_INTERVAL_SECONDS = 5 * 60
REPORT_TIMEOUT_SECONDS = 10
STARTUP_REPORT_ATTEMPTS = 3


def report_enabled() -> bool:
    return os.getenv("SBX_REPORT_ENABLED", "").strip().lower() == "true"


@dataclass(frozen=True)
class ReportConfig:
    url: str
    token: str = field(repr=False)
    agent_id: str

    @classmethod
    def from_environment(cls) -> ReportConfig | None:
        if not report_enabled():
            return None
        names = ("AGENT_MANAGER_REPORT_URL", "AGENT_MANAGER_REPORT_TOKEN", "AGENT_MANAGER_REPORT_AGENT_ID")
        values = [os.getenv(name, "").strip() for name in names]
        missing = [name for name, value in zip(names, values, strict=True) if not value]
        if missing:
            raise ValueError("Missing manager report configuration: " + ", ".join(missing))
        url, token, agent_id = values
        try:
            parsed = urlsplit(url)
            valid = (
                parsed.scheme in {"http", "https"}
                and parsed.hostname
                and parsed.port != 0
                and parsed.username is None
                and parsed.password is None
                and parsed.path in {"", "/"}
                and not parsed.query
                and not parsed.fragment
            )
        except ValueError:
            valid = False
        if not valid or any(c in url + token + agent_id for c in "\r\n\x00"):
            raise ValueError("Invalid manager report configuration")
        config = cls(url.rstrip("/") + "/api/v1/user-agent/report", token, agent_id)
        # Tool subprocesses must not inherit the manager's report credential.
        os.environ.pop("AGENT_MANAGER_REPORT_TOKEN", None)
        return config


def _send_report(config: ReportConfig, reason: str, active_requests: int) -> int | None:
    """Run the request, response handling and diagnostics in the worker thread."""
    started = time.monotonic()
    status = None
    error = None
    try:
        request = Request(
            config.url,
            data=json.dumps({"status": "RUNNING", "agentId": config.agent_id}).encode("utf-8"),
            headers={"Authorization": f"Bearer {config.token}", "Content-Type": "application/json"},
            method="POST",
        )
        with build_opener(ProxyHandler({})).open(request, timeout=REPORT_TIMEOUT_SECONDS) as response:
            status = response.status
    except HTTPError as exc:
        status = exc.code
        exc.close()
    except Exception as exc:
        # Exception text can contain request details; never log credentials.
        error = type(exc).__name__
    log = logger.info if status == 200 else logger.warning
    log(
        "Agent manager report reason=%s active_requests=%s status=%s error=%s elapsed_ms=%.3f",
        reason, active_requests, status, error, (time.monotonic() - started) * 1000,
    )
    return status


async def agent_report_loop(
    config: ReportConfig,
    ready: asyncio.Event,
    *,
    interval_seconds: float = REPORT_INTERVAL_SECONDS,
    startup_attempts: int = STARTUP_REPORT_ATTEMPTS,
    retry_delay_seconds: float = 1,
) -> None:
    await ready.wait()
    for attempt in range(startup_attempts):
        status = await asyncio.to_thread(_send_report, config, "startup", active_request_count())
        if status == 200:
            break
        retryable = status is None or 500 <= status < 600
        if not retryable or attempt == startup_attempts - 1:
            raise RuntimeError(f"Agent manager startup report failed (status={status})")
        await asyncio.sleep(retry_delay_seconds * (attempt + 1))
    next_check = time.monotonic() + interval_seconds
    while True:
        await asyncio.sleep(max(0, next_check - time.monotonic()))
        had_activity = consume_request_activity()
        count = active_request_count()
        # Schedule before HTTP so its duration does not extend the next period.
        next_check = time.monotonic() + interval_seconds
        if had_activity:
            await asyncio.to_thread(_send_report, config, "recent_activity", count)
