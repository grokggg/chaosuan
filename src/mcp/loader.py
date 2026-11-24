from __future__ import annotations

import asyncio
import os
import random
import re
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import yaml
from langchain_core.tools import BaseTool, ToolException
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.interceptors import MCPToolCallRequest, MCPToolCallResult

from src.errors import (
    ErrorAction,
    OperationSafety,
    classify_mcp_error,
    decide_error_action,
    retry_after_seconds,
    tool_error_text,
)
from src.logger import get_logger
from src.mcp.auth import resolve_auth
from src.mcp.names import normalize_mcp_server_name, normalize_mcp_servers_mapping
from src.startup_timing import StartupTimer
from src.statistics import RESOURCE_METADATA_KEY, RESOURCE_TYPE_MCP
from src.tools.deferred import mark_mcp_tools_deferred, mark_tools_deferred, normalize_deferred_keyword
from src.utils import bool_or_false
from src.utils.retry_progress import RetryProgressReporter

logger = get_logger(__name__)

MCP_CONF_PATH = Path(__file__).resolve().with_name("conf.yaml")
_SUPPORTED_TRANSPORTS = {
    "stdio",
    "sse",
    "http",
    "streamable_http",
    "streamable-http",
}
_HTTP_TRANSPORTS = {"http", "streamable_http", "streamable-http"}
_URL_TRANSPORTS = {"sse", *_HTTP_TRANSPORTS}
_DEFAULT_TIMEOUT_SECONDS = 30
_MCP_MAX_ATTEMPTS = 6
_MCP_BACKOFF_MIN_SECONDS = 0.3
_MCP_BACKOFF_MAX_SECONDS = 1.0
_ENV_VAR_PATTERN = re.compile(
    r"\$\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)\}|\$(?P<plain>[A-Za-z_][A-Za-z0-9_]*)|\{(?P<plain_braced>[A-Za-z_][A-Za-z0-9_]*)\}"
)


_MCP_ENV_MAP = {
    "API_KEY": "MCP_API_KEY",
}


def _resolve_env(name: str) -> str | None:
    env_name = _MCP_ENV_MAP.get(name, name)
    value = os.environ.get(env_name, "").strip()
    if value:
        logger.info("Resolved MCP environment variable placeholder=%s env=%s", name, env_name)
    return value or None


async def _mcp_tool_error_interceptor(
    request: MCPToolCallRequest,
    handler: Callable[[MCPToolCallRequest], Awaitable[MCPToolCallResult]],
    *,
    safety_by_tool: dict[tuple[str, str], OperationSafety] | None = None,
    on_retry: Callable[[int, int], None] | None = None,
) -> MCPToolCallResult:
    report_retry = on_retry or RetryProgressReporter().emit
    safety = (safety_by_tool or {}).get(
        (request.server_name, request.name),
        OperationSafety.UNKNOWN,
    )
    for attempt in range(1, _MCP_MAX_ATTEMPTS + 1):
        try:
            return await handler(request)
        except asyncio.CancelledError:
            raise
        except ToolException:
            raise
        except Exception as exc:
            error = classify_mcp_error(
                exc,
                stage="tool",
                server_name=request.server_name,
                tool_name=request.name,
            )
            action = decide_error_action(
                error,
                agent_can_continue=True,
                operation_safety=safety,
            )
            logger.warning(
                "MCP tool call failed server=%s tool=%s attempt=%s/%s error_code=%s safety=%s action=%s",
                request.server_name,
                request.name,
                attempt,
                _MCP_MAX_ATTEMPTS,
                error.error_code,
                safety.value,
                action.value,
            )
            if action is ErrorAction.RETRY and attempt < _MCP_MAX_ATTEMPTS:
                report_retry(attempt, _MCP_MAX_ATTEMPTS - 1)
                await _cancellable_backoff(exc)
                continue
            raise ToolException(tool_error_text(error)) from exc

    raise AssertionError("unreachable")


def _tool_operation_safety(tool: Any) -> OperationSafety:
    metadata = getattr(tool, "metadata", None)
    if not isinstance(metadata, dict):
        return OperationSafety.UNKNOWN
    read_only = metadata.get("readOnlyHint")
    if read_only is True:
        return OperationSafety.READ_ONLY
    if read_only is False:
        return OperationSafety.WRITE
    return OperationSafety.UNKNOWN


def _expand_env_value(value: str, *, server_name: str, field_name: str) -> str:
    def replace_var(match: re.Match[str]) -> str:
        name = match.group("braced") or match.group("plain") or match.group("plain_braced")
        resolved = _resolve_env(name or "")
        if not resolved:
            env_name = _MCP_ENV_MAP.get(name or "", name or "")
            raise ValueError(f"server '{server_name}' field '{field_name}' requires environment variable {env_name}")
        return resolved

    try:
        return _ENV_VAR_PATTERN.sub(replace_var, value)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"failed to expand environment variables in field '{field_name}'") from exc


def _auth_mode(connection: dict[str, Any]) -> str:
    has_url_auth = bool(_ENV_VAR_PATTERN.search(str(connection.get("url", ""))))
    has_header_auth = bool(connection.get("headers"))
    if has_header_auth and has_url_auth:
        return "url+headers"
    if has_header_auth:
        return "headers"
    if has_url_auth:
        return "url"
    return "none"


def _normalize_transport(raw_transport: Any) -> str:
    if not isinstance(raw_transport, str) or not raw_transport.strip():
        raise ValueError("field 'transport' must be a non-empty string")

    transport = raw_transport.strip()
    if transport == "streamableHttp":
        return "streamable_http"
    return transport


def _normalize_headers(raw_headers: Any, *, server_name: str) -> dict[str, str] | None:
    if raw_headers is None:
        return None
    if not isinstance(raw_headers, dict):
        raise ValueError("field 'headers' must be an object")

    headers: dict[str, str] = {}
    for key, value in raw_headers.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("field 'headers' contains an empty header name")
        if value is None:
            logger.warning(
                "Skipping empty MCP header server=%s header=%s",
                server_name,
                key,
            )
            continue
        headers[key.strip()] = _expand_env_value(
            str(value), server_name=server_name, field_name=f"headers.{key.strip()}"
        )
    return headers


def _normalize_seconds(raw_value: Any, *, field_name: str) -> float:
    if isinstance(raw_value, str):
        raw_value = raw_value.strip()
        try:
            raw_value = float(raw_value)
        except ValueError:
            raise ValueError(f"field '{field_name}' must be a number of seconds") from None
    if isinstance(raw_value, bool) or not isinstance(raw_value, int | float):
        raise ValueError(f"field '{field_name}' must be a number of seconds")
    if raw_value <= 0:
        raise ValueError(f"field '{field_name}' must be greater than 0")
    return float(raw_value)


def _normalize_connection(
    server_name: str,
    raw_connection: Any,
    *,
    status_target: dict[str, Any],
    auth_config: dict[str, Any] | None = None,
    timeout_override: Any = None,
) -> dict[str, Any]:
    server_name = normalize_mcp_server_name(server_name)
    if not isinstance(raw_connection, dict):
        raise ValueError("MCP server config must be an object")

    source = dict(raw_connection)
    # Deferred loading is configured at the MCP entry level, not per server.
    source.pop("deferred", None)
    if "transport" not in source and "type" in source:
        source["transport"] = source.pop("type")
    if "url" not in source and "baseUrl" in source:
        source["url"] = source.pop("baseUrl")
    if source.get("timeout") is None:
        source["timeout"] = (
            timeout_override if timeout_override is not None else status_target.get("timeout", _DEFAULT_TIMEOUT_SECONDS)
        )

    transport = _normalize_transport(source.get("transport"))
    if transport not in _SUPPORTED_TRANSPORTS:
        raise ValueError("field 'transport' must be one of: " + ", ".join(sorted(_SUPPORTED_TRANSPORTS)))

    connection: dict[str, Any] = {"transport": transport}
    if transport in _URL_TRANSPORTS:
        url = source.get("url")
        if not isinstance(url, str) or not url.strip():
            raise ValueError(f"field 'url' is required for transport '{transport}'")
        connection["url"] = _expand_env_value(url.strip(), server_name=server_name, field_name="url")
    elif transport == "stdio":
        command = source.get("command")
        args = source.get("args")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("field 'command' is required for transport 'stdio'")
        if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
            raise ValueError("field 'args' must be a list of strings for transport 'stdio'")
        connection["command"] = command.strip()
        connection["args"] = args

    headers = _normalize_headers(source.get("headers"), server_name=server_name)
    if headers is not None:
        connection["headers"] = headers

    timeout_value = source.get("timeout")
    if timeout_value is None:
        timeout_value = _DEFAULT_TIMEOUT_SECONDS
    timeout_seconds = _normalize_seconds(timeout_value, field_name="timeout")
    # Store the timeout for asyncio.wait_for under an internal key so it is
    # never forwarded to MultiServerMCPClient regardless of transport.
    connection["_load_timeout_seconds"] = timeout_seconds
    # Only HTTP-based transports accept a timeout kwarg in the client config.
    # stdio (StdioServerParameters) and sse do not accept it, so we omit it.
    if transport in _HTTP_TRANSPORTS:
        connection["timeout"] = timedelta(seconds=timeout_seconds)

    for field_name in ("sse_read_timeout",):
        if field_name not in source:
            continue
        seconds = _normalize_seconds(source[field_name], field_name=field_name)
        # sse_read_timeout is only meaningful for HTTP-based transports
        if transport in _HTTP_TRANSPORTS:
            connection[field_name] = timedelta(seconds=seconds)

    for field_name in (
        "env",
        "cwd",
        "encoding",
        "encoding_error_handler",
        "terminate_on_close",
    ):
        if field_name in source:
            connection[field_name] = source[field_name]

    # Passthrough unknown fields for forward compatibility
    known_fields = {
        "transport",
        "type",
        "baseUrl",
        "url",
        "command",
        "args",
        "env",
        "headers",
        "timeout",
        "sse_read_timeout",
        "cwd",
        "encoding",
        "encoding_error_handler",
        "terminate_on_close",
    }
    for key, value in source.items():
        if key not in known_fields and key not in connection:
            connection[key] = value

    connection = resolve_auth(connection, auth_config)

    connection["_status_target"] = status_target
    connection["_auth_mode"] = _auth_mode(source)
    return connection


def _normalize_mcp_config(raw_config: Any) -> dict[str, dict[str, Any]]:
    """Parse new-format mcp[] array from agent.json into connection dict."""
    if raw_config in (None, {}, []):
        return {}
    if not isinstance(raw_config, list):
        logger.warning("MCP config must be a list, got %s", type(raw_config).__name__)
        return {}

    connections: dict[str, dict[str, Any]] = {}
    for idx, mcp_entry in enumerate(raw_config):
        if not isinstance(mcp_entry, dict):
            logger.warning("Skipping MCP entry index=%s reason=not a dict", idx)
            continue

        name = str(mcp_entry.get("name", "")).strip()
        if not name:
            logger.warning("Skipping MCP entry index=%s reason=missing name", idx)
            continue

        if not mcp_entry.get("enabled", True):
            logger.info("MCP entry disabled name=%s", name)
            continue

        raw_servers = mcp_entry.get("servers")
        if not isinstance(raw_servers, dict) or not raw_servers:
            logger.warning("Skipping MCP entry name=%s reason=missing or empty servers", name)
            continue
        servers, server_name_errors = normalize_mcp_servers_mapping(raw_servers)
        if server_name_errors:
            mcp_entry["lastError"] = "; ".join(server_name_errors)
            logger.warning(
                "MCP entry has invalid server names name=%s errors=%s",
                name,
                server_name_errors,
            )
        if not servers:
            continue

        auth_config = mcp_entry.get("auth")
        timeout = mcp_entry.get("timeout", _DEFAULT_TIMEOUT_SECONDS)
        deferred = mcp_entry.get("deferred") is True
        description = str(mcp_entry.get("description") or "").strip()

        mcp_entry["available"] = False

        for server_name, raw_connection in servers.items():
            try:
                connection = _normalize_connection(
                    server_name,
                    raw_connection,
                    auth_config=auth_config,
                    timeout_override=timeout,
                    status_target=mcp_entry,
                )
                if deferred:
                    connection["_deferred_mcp_name"] = name
                    connection["_deferred_mcp_description"] = description
                conn_key = f"{name}_{server_name}" if server_name in connections else server_name
                connections[conn_key] = connection
                logger.info(
                    "MCP server normalized name=%s server=%s transport=%s",
                    name,
                    server_name,
                    connection.get("transport"),
                )
            except ValueError as exc:
                logger.warning(
                    "Skipping MCP server name=%s server=%s reason=%s",
                    name,
                    server_name,
                    exc,
                )
                mcp_entry["lastError"] = str(exc)

    return connections


def _read_static_mcp_servers_config(config_path: Path = MCP_CONF_PATH) -> tuple[dict[str, Any], float]:
    if not config_path.exists():
        return {}, _DEFAULT_TIMEOUT_SECONDS

    try:
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.warning("Skipping static MCP config path=%s reason=%s", config_path, exc)
        return {}, _DEFAULT_TIMEOUT_SECONDS

    if not isinstance(payload, dict):
        logger.warning("Skipping static MCP config path=%s reason=root must be an object", config_path)
        return {}, _DEFAULT_TIMEOUT_SECONDS

    mcp_payload = payload.get("mcp", payload)
    if not isinstance(mcp_payload, dict):
        logger.warning("Skipping static MCP config path=%s reason=field 'mcp' must be an object", config_path)
        return {}, _DEFAULT_TIMEOUT_SECONDS

    raw_timeout = mcp_payload.get("timeout_seconds", mcp_payload.get("timeout", _DEFAULT_TIMEOUT_SECONDS))
    try:
        timeout_seconds = _normalize_seconds(raw_timeout, field_name="mcp.timeout_seconds")
    except ValueError as exc:
        logger.warning("Static MCP config has invalid timeout path=%s reason=%s", config_path, exc)
        timeout_seconds = _DEFAULT_TIMEOUT_SECONDS

    servers = mcp_payload.get("servers", {})
    if not isinstance(servers, dict):
        logger.warning("Skipping static MCP servers path=%s reason=field 'mcp.servers' must be an object", config_path)
        return {}, timeout_seconds
    return servers, timeout_seconds


def _normalize_static_mcp_config(config_path: Path = MCP_CONF_PATH) -> dict[str, dict[str, Any]]:
    raw_servers, timeout_seconds = _read_static_mcp_servers_config(config_path)
    if not raw_servers:
        return {}

    connections: dict[str, dict[str, Any]] = {}
    for server_name, raw_connection in raw_servers.items():
        status_target: dict[str, Any] = {
            "name": str(server_name),
            "timeout": timeout_seconds,
            "available": False,
            "source": "src/mcp/conf.yaml",
        }
        try:
            normalized_server_name = normalize_mcp_server_name(server_name)
            if not isinstance(raw_connection, dict):
                raise ValueError("MCP server config must be an object")
            source = dict(raw_connection)
            tool_config = _normalize_static_tool_config(source.pop("tools", None))
            connection = _normalize_connection(
                normalized_server_name,
                source,
                status_target=status_target,
            )
            # Static catalog tools use their remote names throughout the Agent.
            connection["_tool_name_prefix"] = False
            if tool_config:
                connection["_static_tool_config"] = tool_config
            connections[normalized_server_name] = connection
        except ValueError as exc:
            logger.warning("Skipping invalid static MCP server server=%s reason=%s", server_name, exc)
    return connections


def _normalize_static_tool_config(raw_config: Any) -> dict[str, dict[str, Any]]:
    """Parse per-tool deferred categories without forwarding them to MCP."""
    if raw_config is None:
        return {}
    if not isinstance(raw_config, dict):
        raise ValueError("field 'tools' must be an object keyed by remote tool name")
    normalized: dict[str, dict[str, Any]] = {}
    for tool_name, config in raw_config.items():
        if not isinstance(tool_name, str) or not tool_name.strip() or not isinstance(config, dict):
            raise ValueError("field 'tools' requires non-empty tool names and object values")
        normalized[tool_name] = {
            "keyword": normalize_deferred_keyword(config.get("deferred")),
        }
    return normalized


def _configure_static_tools(
    tools: list[BaseTool], *, server_name: str, connection: dict[str, Any]
) -> list[BaseTool]:
    tool_config = connection.get("_static_tool_config", {})
    if not tool_config:
        return tools
    remote_names = {tool.name for tool in tools}
    missing = tool_config.keys() - remote_names
    if missing:
        raise ValueError(f"MCP server '{server_name}' did not return configured tools: {', '.join(sorted(missing))}")
    configured: list[BaseTool] = []
    for tool in tools:
        config = tool_config.get(tool.name, {})
        configured.extend(mark_tools_deferred([tool], config.get("keyword")))
    return configured


def _merge_mcp_connections(
    static_connections: dict[str, dict[str, Any]],
    configured_connections: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    connections = dict(static_connections)
    for server_name, connection in configured_connections.items():
        connection_name = server_name
        if connection_name in connections:
            status_target = connection.get("_status_target")
            prefix = status_target.get("name") if isinstance(status_target, dict) else "agent_json"
            connection_name = f"{prefix}_{server_name}"
        connections[connection_name] = connection
    return connections


def _connection_timeout_seconds(connection: dict[str, Any]) -> float:
    # Prefer the internal field set during normalization; fall back to the
    # client-facing timeout for backwards-compatible connections.
    if "_load_timeout_seconds" in connection:
        return float(connection["_load_timeout_seconds"])
    timeout = connection.get("timeout", _DEFAULT_TIMEOUT_SECONDS)
    if isinstance(timeout, timedelta):
        return timeout.total_seconds()
    return float(timeout)


_STDIO_SSE_BLOCKED_FIELDS = frozenset({"timeout", "sse_read_timeout"})


def _build_client_connection(connection: dict[str, Any]) -> dict[str, Any]:
    """Build the connection dict to pass to MultiServerMCPClient.

    Strips internal (_-prefixed) fields. For stdio and sse transports also
    removes timeout-related keys that their underlying SDK does not accept.
    """
    transport = connection.get("transport", "")
    strip_timeout = transport not in _HTTP_TRANSPORTS
    result = {}
    for key, value in connection.items():
        if key.startswith("_"):
            continue
        if strip_timeout and key in _STDIO_SSE_BLOCKED_FIELDS:
            continue
        result[key] = value
    return result


def _configure_mcp_tools(tools: list[BaseTool]) -> list[BaseTool]:
    configured: list[BaseTool] = []
    for tool in tools:

        def handle_tool_error(exc: BaseException) -> str:
            return tool_error_text(classify_mcp_error(exc, stage="tool"))

        configured.append(
            tool.model_copy(
                update={
                    "handle_tool_error": handle_tool_error,
                    "handle_validation_error": True,
                }
            )
        )
    return configured


def _mark_mcp_resource_tools(
    tools: list[BaseTool],
    *,
    server_name: str,
    connection: dict[str, Any],
) -> list[BaseTool]:
    status_target = connection.get("_status_target")
    mcp_name = str(status_target.get("name") or "") if isinstance(status_target, dict) else server_name
    source_id = str(status_target.get("sourceId") or "") if isinstance(status_target, dict) else ""
    built_in = bool_or_false(status_target.get("builtIn")) if isinstance(status_target, dict) else False
    marked: list[BaseTool] = []
    for tool in tools:
        marked.append(
            tool.model_copy(
                update={
                    "metadata": {
                        **(tool.metadata or {}),
                        RESOURCE_METADATA_KEY: {
                            "type": RESOURCE_TYPE_MCP,
                            "name": mcp_name,
                            "id": source_id,
                            "tool": tool.name,
                            "builtIn": built_in,
                        },
                    }
                }
            )
        )
    return marked


async def _load_server_tools(
    server_name: str,
    connection: dict[str, Any],
    *,
    timeout_seconds: float,
) -> list[BaseTool]:
    client_connection = _build_client_connection(connection)
    safety_by_tool: dict[tuple[str, str], OperationSafety] = {}

    async def tool_interceptor(
        request: MCPToolCallRequest,
        handler: Callable[[MCPToolCallRequest], Awaitable[MCPToolCallResult]],
    ) -> MCPToolCallResult:
        return await _mcp_tool_error_interceptor(
            request,
            handler,
            safety_by_tool=safety_by_tool,
        )

    tool_name_prefix = connection.get("_tool_name_prefix", True)
    client = MultiServerMCPClient(
        {server_name: client_connection},
        tool_name_prefix=tool_name_prefix,
        tool_interceptors=[tool_interceptor],
    )
    tools = await asyncio.wait_for(
        client.get_tools(server_name=server_name),
        timeout=timeout_seconds,
    )
    prefix = f"{server_name}_"
    for tool in tools:
        tool_name = str(tool.name)
        raw_tool_name = tool_name.removeprefix(prefix) if tool_name_prefix else tool_name
        safety_by_tool[(server_name, raw_tool_name)] = _tool_operation_safety(tool)
    configured_tools = _mark_mcp_resource_tools(
        _configure_static_tools(_configure_mcp_tools(tools), server_name=server_name, connection=connection),
        server_name=server_name,
        connection=connection,
    )
    deferred_mcp_name = connection.get("_deferred_mcp_name")
    if not isinstance(deferred_mcp_name, str):
        return configured_tools
    return mark_mcp_tools_deferred(
        configured_tools,
        name=deferred_mcp_name,
        description=str(connection.get("_deferred_mcp_description") or ""),
    )


async def _cancellable_backoff(exc: BaseException | None = None) -> float:
    server_delay = retry_after_seconds(exc) if exc is not None else None
    delay = (
        server_delay if server_delay is not None else random.uniform(_MCP_BACKOFF_MIN_SECONDS, _MCP_BACKOFF_MAX_SECONDS)
    )
    await asyncio.sleep(delay)
    return delay


async def _load_server_tools_with_retry(
    server_name: str,
    connection: dict[str, Any],
    *,
    timeout_seconds: float,
    on_retry: Callable[[int, int], None] | None = None,
) -> list[BaseTool]:
    report_retry = on_retry or RetryProgressReporter().emit
    for attempt in range(1, _MCP_MAX_ATTEMPTS + 1):
        try:
            timing = StartupTimer(logger, f"mcp.{server_name}")
            with timing.stage(f"get_tools_attempt_{attempt}"):
                return await _load_server_tools(server_name, connection, timeout_seconds=timeout_seconds)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = classify_mcp_error(exc, stage="get_tools", server_name=server_name)
            action = decide_error_action(error, agent_can_continue=False)
            logger.warning(
                "MCP get_tools attempt failed server=%s attempt=%s/%s error_code=%s action=%s",
                server_name,
                attempt,
                _MCP_MAX_ATTEMPTS,
                error.error_code,
                action.value,
            )
            if attempt >= _MCP_MAX_ATTEMPTS or action is not ErrorAction.RETRY:
                raise
            report_retry(attempt, _MCP_MAX_ATTEMPTS - 1)
            await _cancellable_backoff(exc)


async def load_configured_mcp_tools(raw_config: Any) -> list[BaseTool]:
    static_connections = _normalize_static_mcp_config()
    configured_connections = _normalize_mcp_config(raw_config)
    connections = _merge_mcp_connections(static_connections, configured_connections)
    if not connections:
        return []

    logger.info(
        "Loading MCP tools static_servers=%s configured_servers=%s total_servers=%s",
        list(static_connections),
        list(configured_connections),
        list(connections),
    )

    tasks = {
        server_name: asyncio.create_task(
            _load_server_tools_with_retry(
                server_name,
                connection,
                timeout_seconds=_connection_timeout_seconds(connection),
            )
        )
        for server_name, connection in connections.items()
    }

    tools: list[BaseTool] = []
    connected_count = 0
    failed_count = 0
    for server_name, task in tasks.items():
        connection = connections[server_name]
        status_target = connection.get("_status_target")
        auth_mode = connection.get("_auth_mode", "none")
        try:
            server_tools = await task
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failed_count += 1
            error = classify_mcp_error(exc, stage="get_tools", server_name=server_name)
            error_msg = error.message
            logger.warning(
                "Failed to load MCP tools server=%s transport=%s auth=%s error_code=%s reason=%s",
                server_name,
                connection.get("transport"),
                auth_mode,
                error.error_code,
                error_msg,
            )
            logger.debug(
                "MCP tools load traceback server=%s",
                server_name,
                exc_info=True,
            )
            if isinstance(status_target, dict):
                status_target["lastError"] = error_msg
            continue

        connected_count += 1
        if isinstance(status_target, dict):
            status_target["available"] = True
            status_target["lastError"] = None
        logger.info(
            "Loaded MCP tools server=%s transport=%s auth=%s count=%s",
            server_name,
            connection.get("transport"),
            auth_mode,
            len(server_tools),
        )
        tools.extend(server_tools)

    logger.info("MCP load complete connected=%s failed=%s total_tools=%s", connected_count, failed_count, len(tools))
    return tools
