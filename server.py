from __future__ import annotations

# Imports are intentionally timed in separate groups before the app is built.
# ruff: noqa: E402
import time

_SERVER_STARTED_AT = time.perf_counter()

import argparse
import asyncio
import logging
import os
import selectors
import socket
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager, suppress

_IMPORT_TIMINGS = [("imports.stdlib", _SERVER_STARTED_AT, time.perf_counter())]

if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

_import_started_at = time.perf_counter()
import uvicorn

_IMPORT_TIMINGS.append(("imports.uvicorn", _import_started_at, time.perf_counter()))
_import_started_at = time.perf_counter()
from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException

_IMPORT_TIMINGS.append(("imports.fastapi", _import_started_at, time.perf_counter()))
_import_started_at = time.perf_counter()
from src.api.agent_report import ReportConfig, agent_report_loop, report_enabled

_IMPORT_TIMINGS.append(("imports.report_config", _import_started_at, time.perf_counter()))
# The process mode is fixed before loading any optional A2A dependencies.
a2a = None
if not report_enabled():
    _import_started_at = time.perf_counter()
    from src.a2a import server as a2a

    _IMPORT_TIMINGS.append(("imports.a2a", _import_started_at, time.perf_counter()))
_import_started_at = time.perf_counter()
from src.agents.manager import AGENTS

_IMPORT_TIMINGS.append(("imports.agent_dependencies", _import_started_at, time.perf_counter()))
_import_started_at = time.perf_counter()
from src.api.request_monitor import api_usage_monitor_loop, record_api_call
from src.api.response import api_error
from src.api.routes.chat import router as chat_router
from src.api.routes.files import router as files_router
from src.api.routes.general import router as general_router
from src.logger import get_logger
from src.middleware.user_memory_middleware import initialize_known_user_memory_files
from src.startup_timing import StartupReadiness, StartupTimer, capture_startup_stages, trace_startup_ssl
from src.utils import AGENT_CONFIG_PATH, ensure_workspace_root, load_agent_config, write_agent_config

_IMPORT_TIMINGS.append(("imports.api_and_utils", _import_started_at, time.perf_counter()))
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8010


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = get_logger(__name__)
startup_timer = StartupTimer(logger, "server", started_at=_SERVER_STARTED_AT)
for _stage, _started_at, _finished_at in _IMPORT_TIMINGS:
    startup_timer.record(_stage, _started_at, _finished_at)


def _apply_agent_name_from_env() -> None:
    agent_name = os.getenv("AGENT_NAME", "").strip()
    if not agent_name:
        return

    config = load_agent_config()
    if config.get("name") == agent_name:
        logger.info("Agent name already matches AGENT_NAME name=%s", agent_name)
        return

    config["name"] = agent_name
    write_agent_config(config, AGENT_CONFIG_PATH)
    logger.info("Updated agent name from AGENT_NAME name=%s path=%s", agent_name, AGENT_CONFIG_PATH)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    with startup_timer.stage("workspace"):
        workspace_root = ensure_workspace_root()
    logger.info("Workspace root ready path=%s", workspace_root)
    with startup_timer.stage("user_memory_files"):
        initialized_memory_users = initialize_known_user_memory_files()
    logger.info("User memory files initialized users=%s", initialized_memory_users)
    with startup_timer.stage("agent_name_config"):
        _apply_agent_name_from_env()
    logger.info("Preloading default agent")
    with startup_timer.stage("default_agent_preload"), trace_startup_ssl(logger):
        await AGENTS.get()
    logger.info("Default agent preloaded")
    api_usage_task = None
    if not report_enabled():
        # Restore the public AgentCard after restart or migration in legacy mode.
        from src.api.routes.chat import _register_a2a_agent_card

        asyncio.create_task(_register_a2a_agent_card())
        api_usage_task = asyncio.create_task(api_usage_monitor_loop(), name="api_usage_monitor")
    # This is the end of FastAPI lifespan initialization, not HTTP readiness.
    # measure_server_startup.py supplies the end-to-end readiness time.
    startup_timer.summary()
    try:
        yield
    finally:
        if api_usage_task is not None:
            api_usage_task.cancel()
            with suppress(asyncio.CancelledError):
                await api_usage_task


app = FastAPI(title="user_agent", lifespan=lifespan)


def _is_sse_path(request: Request) -> bool:
    return request.url.path == "/api/user/agent/chat"


@app.middleware("http")
async def record_api_usage(request: Request, call_next) -> Response:
    try:
        record_api_call(request.method, request.url.path)
    except Exception:
        logger.exception("Failed to record API usage")
    return await call_next(request)


@app.exception_handler(HTTPException)
async def standard_http_exception_handler(request: Request, exc: HTTPException) -> Response:
    if _is_sse_path(request):
        return await http_exception_handler(request, exc)

    detail = exc.detail if isinstance(exc.detail, str) else "request failed"
    return JSONResponse(
        status_code=exc.status_code,
        content=api_error(code=exc.status_code, msg=detail),
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def standard_validation_exception_handler(request: Request, exc: RequestValidationError) -> Response:
    if _is_sse_path(request):
        return await request_validation_exception_handler(request, exc)

    return JSONResponse(
        status_code=422,
        content=api_error(code=422, msg="request validation failed", data=exc.errors()),
    )


app.include_router(chat_router, prefix="/api")
app.include_router(files_router, prefix="/api")
app.include_router(general_router, prefix="/api")


def _loop_factory():
    if os.name == "nt":
        return asyncio.SelectorEventLoop(selectors.SelectSelector())
    return asyncio.new_event_loop()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the user agent and A2A servers.")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Host to bind. Default: {DEFAULT_HOST}")
    parser.add_argument("--port", default=DEFAULT_PORT, type=int, help=f"Port to bind. Default: {DEFAULT_PORT}")
    parser.add_argument(
        "--a2a-host",
        default=os.getenv("A2A_HOST", "0.0.0.0"),
        help="A2A host to bind. Default: 0.0.0.0 (ignored in subagent mode)",
    )
    parser.add_argument(
        "--a2a-port",
        default=int(os.getenv("A2A_PORT", "8011")) if a2a is not None else 8011,
        type=int,
        help="A2A port to bind. Default: 8011 (ignored in subagent mode)",
    )
    parser.add_argument(
        "--a2a-backend",
        default=os.getenv("A2A_BACKEND", ""),
        help="Agent backend URL used by A2A. Defaults to the agent server started by this command.",
    )
    parser.add_argument(
        "--a2a-public-url",
        default=os.getenv("A2A_PUBLIC_URL", ""),
        help=("JSON-RPC URL advertised in the A2A AgentCard. Defaults to http://{a2a-host}:{a2a-port}/api/a2a."),
    )
    return parser.parse_args()


class _StartupTimedServer(uvicorn.Server):
    """Record readiness only after lifespan and listening sockets are ready."""

    def __init__(
        self,
        config: uvicorn.Config,
        *,
        readiness: StartupReadiness,
        name: str,
        report_ready: asyncio.Event | None = None,
    ) -> None:
        super().__init__(config)
        self._startup_readiness = readiness
        self._startup_name = name
        self._report_ready = report_ready

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets=sockets)
        if self.started and not self.should_exit:
            self._startup_readiness.mark_started(self._startup_name)
            if self._report_ready is not None and self._startup_readiness.reported:
                self._report_ready.set()


class _SecondaryServer(_StartupTimedServer):
    """Uvicorn server whose signals are managed by the primary server."""

    @contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


async def _serve(
    agent_server: uvicorn.Server,
    a2a_server: uvicorn.Server | None = None,
    *,
    report_config: ReportConfig | None = None,
    report_ready: asyncio.Event | None = None,
) -> None:
    if report_config is not None and report_ready is None:
        raise ValueError("Manager reporting requires a readiness event")
    servers = (agent_server,) if a2a_server is None else (agent_server, a2a_server)
    tasks = tuple(asyncio.create_task(server.serve()) for server in servers)
    report_task = (
        asyncio.create_task(agent_report_loop(report_config, report_ready), name="agent_manager_report")
        if report_config is not None
        else None
    )
    watched = (*tasks, report_task) if report_task is not None else tasks
    try:
        await asyncio.wait(watched, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for server in servers:
            server.should_exit = True
        if report_task is not None:
            report_task.cancel()
        results = await asyncio.gather(*watched, return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
            raise result


def _connect_host(host: str) -> str:
    return "127.0.0.1" if host in {"0.0.0.0", "::"} else host


def main() -> None:
    args = _parse_args()
    report_config = ReportConfig.from_environment()
    report_ready = asyncio.Event() if report_config is not None else None
    logger.info("Starting agent server on %s:%s", args.host, args.port)
    if a2a is None:
        logger.info("Subagent mode enabled (SBX_REPORT_ENABLED=true); A2A disabled")
    else:
        backend_url = args.a2a_backend.strip() or f"http://{_connect_host(args.host)}:{args.port}"
        a2a_public_url = args.a2a_public_url.strip() or a2a.default_public_url(
            host=args.a2a_host,
            port=args.a2a_port,
        )
        logger.info(
            "Starting A2A server on %s:%s (backend=%s, public_url=%s)",
            args.a2a_host,
            args.a2a_port,
            backend_url,
            a2a_public_url,
        )
    with capture_startup_stages() as stages:
        stages.update({("server", name): duration for name, duration in startup_timer.stages})
        readiness = StartupReadiness(
            logger,
            started_at=_SERVER_STARTED_AT,
            servers=("agent",) if a2a is None else ("agent", "a2a"),
            stage_durations=stages,
        )
        with startup_timer.stage("server_setup" if a2a is None else "server_and_a2a_setup"):
            agent_server = _StartupTimedServer(
                uvicorn.Config(app, host=args.host, port=args.port, reload=False),
                readiness=readiness,
                name="agent",
                report_ready=report_ready,
            )
            a2a_server = None
            if a2a is not None:
                a2a_server = _SecondaryServer(
                    uvicorn.Config(
                        a2a.build_app(backend_url=backend_url, public_url=a2a_public_url),
                        host=args.a2a_host,
                        port=args.a2a_port,
                        reload=False,
                    ),
                    readiness=readiness,
                    name="a2a",
                    report_ready=report_ready,
                )
        with asyncio.Runner(loop_factory=_loop_factory) as runner:
            runner.run(_serve(agent_server, a2a_server, report_config=report_config, report_ready=report_ready))


if __name__ == "__main__":
    main()
