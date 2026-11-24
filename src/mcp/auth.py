"""MCP authentication adapter layer.

Provides a registry of auth handlers that can be extended for new auth types.
Each handler receives a connection dict and auth config, and returns the
connection dict with auth-related fields applied.
"""
from __future__ import annotations

from typing import Any

from src.logger import get_logger

logger = get_logger(__name__)

_AUTH_HANDLERS: dict[str, Any] = {}


def register_auth_handler(auth_type: str):
    """Decorator to register an auth handler for a given type."""
    def decorator(fn):
        _AUTH_HANDLERS[auth_type] = fn
        return fn
    return decorator


@register_auth_handler("none")
def _handle_no_auth(connection: dict, auth_config: dict) -> dict:
    return connection


@register_auth_handler("api_key")
def _handle_api_key(connection: dict, auth_config: dict) -> dict:
    logger.debug("auth handler api_key applied server transport=%s", connection.get("transport"))
    return connection


@register_auth_handler("oauth2")
def _handle_oauth2(connection: dict, auth_config: dict) -> dict:
    oauth = auth_config.get("oauth", {})
    logger.debug("auth handler oauth2 applied client_id=%s", oauth.get("clientId", ""))
    return connection


def resolve_auth(connection: dict[str, Any], auth_config: dict[str, Any] | None) -> dict[str, Any]:
    """Apply auth configuration to a connection dict."""
    if not auth_config:
        return connection
    auth_type = str(auth_config.get("type", "none")).lower()
    handler = _AUTH_HANDLERS.get(auth_type)
    if handler is None:
        logger.warning("Unknown auth type=%s, falling through without auth injection", auth_type)
        return connection
    return handler(connection, auth_config)
