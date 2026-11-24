import asyncio
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from threading import RLock
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import ProxyHandler, Request, build_opener

from src.logger import get_logger

logger = get_logger(__name__)

ANALYSIS_INTERVAL_SECONDS = 10 * 60
ANALYSIS_WINDOW_SECONDS = 60 * 60
HEARTBEAT_TIMEOUT_SECONDS = 10

_TRACKED_ENDPOINTS = {
    ("POST", "/api/user/agent/chat"): "chat",
    ("POST", "/api/user/agent/stop"): "stop",
    ("PUT", "/api/user/agent/config"): "config",
}
_LATEST_CALLS: dict[str, float | None] = dict.fromkeys(_TRACKED_ENDPOINTS.values())
_LOCK = RLock()

# Execution identity is independent of conversation/message IDs. A completed
# request cannot remove a later request in the same conversation.
_ACTIVE_REQUESTS: set[object] = set()
_REQUEST_ACTIVITY_SEEN = False
_CURRENT_REQUEST: ContextVar[object | None] = ContextVar("active_agent_request", default=None)


@contextmanager
def track_active_request(*, enabled: bool) -> Iterator[None]:
    global _REQUEST_ACTIVITY_SEEN
    if not enabled:
        yield
        return
    request = object()
    _ACTIVE_REQUESTS.add(request)
    _REQUEST_ACTIVITY_SEEN = True
    token = _CURRENT_REQUEST.set(request)
    try:
        yield
    finally:
        _ACTIVE_REQUESTS.discard(request)
        _CURRENT_REQUEST.reset(token)


def finish_active_request() -> None:
    request = _CURRENT_REQUEST.get()
    if request is not None:
        _ACTIVE_REQUESTS.discard(request)


def active_request_count() -> int:
    return len(_ACTIVE_REQUESTS)


def consume_request_activity() -> bool:
    """Check/reset the period marker on the same event loop as request tracking."""
    global _REQUEST_ACTIVITY_SEEN
    active = bool(_ACTIVE_REQUESTS)
    had_activity = _REQUEST_ACTIVITY_SEEN or active
    # Requests still running at this boundary also occupy the next period.
    _REQUEST_ACTIVITY_SEEN = active
    return had_activity


def record_api_call(method: str, path: str, *, timestamp: float | None = None) -> None:
    endpoint = _TRACKED_ENDPOINTS.get((method.upper(), path))
    if endpoint is None:
        return

    now = time.time() if timestamp is None else timestamp
    with _LOCK:
        _LATEST_CALLS[endpoint] = now


def analyze_recent_api_usage(*, window_seconds: int = ANALYSIS_WINDOW_SECONDS) -> dict[str, Any]:
    now = time.time()
    cutoff = now - window_seconds
    with _LOCK:
        latest_calls = dict(_LATEST_CALLS)

    return {
        "windowSeconds": window_seconds,
        "called": {
            endpoint: timestamp is not None and timestamp >= cutoff
            for endpoint, timestamp in latest_calls.items()
        },
        "lastCalledAt": latest_calls,
    }


async def api_usage_monitor_loop(
    *,
    interval_seconds: int = ANALYSIS_INTERVAL_SECONDS,
    window_seconds: int = ANALYSIS_WINDOW_SECONDS,
) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            summary = analyze_recent_api_usage(window_seconds=window_seconds)
            called = summary["called"]
            if any(called.values()):
                status = await asyncio.to_thread(_post_sandbox_heartbeat)
                logger.info("Sandbox heartbeat status=%s", status)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to process API usage heartbeat")


def _post_sandbox_heartbeat() -> str:
    proxy_url = os.getenv("PROXY_URL", "").strip().rstrip("/")
    instance_id = os.getenv("INSTANCE_ID", "").strip()
    namespace = os.getenv("SANDBOX_NAMESPACE", "").strip()
    api_key = os.getenv("PROXY_API_KEY", "").strip()
    if not all((proxy_url, instance_id, namespace, api_key)):
        return "skipped_missing_proxy_env"

    url = (
        f"{proxy_url}/api/v1/sandboxes/{quote(instance_id, safe='')}/heartbeat"
        f"?{urlencode({'namespace': namespace})}"
    )
    request = Request(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(request, timeout=HEARTBEAT_TIMEOUT_SECONDS) as response:
            return str(response.status)
    except HTTPError as exc:
        return str(exc.code)

__all__ = [
    "active_request_count",
    "analyze_recent_api_usage",
    "api_usage_monitor_loop",
    "consume_request_activity",
    "finish_active_request",
    "record_api_call",
    "track_active_request",
]
