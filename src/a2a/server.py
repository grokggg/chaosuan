from __future__ import annotations

import argparse
import os

import uvicorn
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from starlette.applications import Starlette

from a2a import types as a2a_types
from src.a2a.a2a import _build_agent_card as build_configured_agent_card
from src.a2a.executor import SagMakerA2AExecutor
from src.utils.config import load_agent_config

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8011
DEFAULT_BACKEND = "http://127.0.0.1:8010"

# A2A 协议端点统一挂载在该前缀下，与 Ingress 放行的 /a2a 前缀对齐，
# 从而可经集群 Ingress 对外暴露（AgentCard 发现地址 / JSON-RPC 交互端点）。
A2A_ROUTE_PREFIX = "/a2a"


def default_public_url(*, host: str, port: int) -> str:
    """Return the JSON-RPC URL advertised by the Agent Card."""
    advertised_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    return f"http://{advertised_host}:{port}{A2A_ROUTE_PREFIX}"


def build_agent_card(*, public_url: str) -> a2a_types.AgentCard:
    endpoint_url = public_url.rstrip("/")
    configured_card = build_configured_agent_card(load_agent_config(), endpoint_url)
    capabilities = configured_card.get("capabilities", {})
    configured_extensions = capabilities.get("extensions", [])
    input_modes = configured_card.get("defaultInputModes", [])
    output_modes = configured_card.get("defaultOutputModes", [])
    configured_skills = configured_card.get("skills", [])

    return a2a_types.AgentCard(
        name=str(configured_card.get("name") or "SAG Maker Agent"),
        description=str(configured_card.get("description", "")),
        version=str(configured_card.get("version") or "1.0.0"),
        icon_url=str(configured_card.get("iconUrl", "")),
        default_input_modes=[str(mode) for mode in input_modes],
        default_output_modes=[str(mode) for mode in output_modes],
        capabilities=a2a_types.AgentCapabilities(
            streaming=bool(capabilities.get("streaming", False)),
            push_notifications=bool(capabilities.get("pushNotifications", False)),
            extensions=[
                a2a_types.AgentExtension(
                    uri=str(extension.get("uri") or ""),
                    description=str(extension.get("description") or ""),
                    required=bool(extension.get("required", False)),
                    params=extension.get("params", {}),
                )
                for extension in configured_extensions
                if isinstance(extension, dict)
                and isinstance(extension.get("params"), dict)
            ],
        ),
        supported_interfaces=[
            a2a_types.AgentInterface(
                url=endpoint_url,
                protocol_binding="JSONRPC",
                protocol_version="1.0",
            )
        ],
        skills=[
            a2a_types.AgentSkill(
                id=str(skill.get("id", "")),
                name=str(skill.get("name", "")),
                description=str(skill.get("description", "")),
                tags=[str(tag) for tag in skill.get("tags", [])],
                examples=[str(example) for example in skill.get("examples", [])],
                input_modes=[str(mode) for mode in skill.get("inputModes", [])],
                output_modes=[str(mode) for mode in skill.get("outputModes", [])],
            )
            for skill in configured_skills
            if isinstance(skill, dict)
        ],
    )


def build_routes(*, backend_url: str, public_url: str) -> list:
    """构建 A2A 协议路由（挂载在 A2A_ROUTE_PREFIX 前缀下）。

    可被独立的 A2A server 使用，也可被主应用（8010 FastAPI）挂载，
    使 A2A 端点经 Ingress 的 /a2a 前缀对外可达。

    暴露端点：
    - {prefix}/.well-known/agent-card.json  AgentCard 发现地址（A2A 1.0 标准）
    - {prefix}/.well-known/agent.json       pre-1.0 发现别名（兼容旧消费者）
    - {prefix}                              JSON-RPC 交互端点
    """
    agent_card = build_agent_card(public_url=public_url)
    request_handler = DefaultRequestHandler(
        agent_executor=SagMakerA2AExecutor(backend_url=backend_url),
        task_store=InMemoryTaskStore(),
        agent_card=agent_card,
    )

    async def reload_agent_card(_: a2a_types.AgentCard) -> a2a_types.AgentCard:
        """Reload config and skills for every Agent Card discovery request."""
        return build_agent_card(public_url=public_url)

    prefix = A2A_ROUTE_PREFIX.rstrip("/")
    return [
        *create_agent_card_routes(
            agent_card,
            card_modifier=reload_agent_card,
            card_url=f"{prefix}/.well-known/agent-card.json",
        ),
        # Keep the pre-1.0 discovery alias for existing SAG Maker consumers.
        *create_agent_card_routes(
            agent_card,
            card_modifier=reload_agent_card,
            card_url=f"{prefix}/.well-known/agent.json",
        ),
        *create_jsonrpc_routes(request_handler, prefix),
    ]


def build_app(*, backend_url: str, public_url: str) -> Starlette:
    return Starlette(routes=build_routes(backend_url=backend_url, public_url=public_url))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the SAG Maker A2A server.")
    parser.add_argument("--host", default=os.getenv("A2A_HOST", DEFAULT_HOST), help=f"Host to bind. Default: {DEFAULT_HOST}")
    parser.add_argument(
        "--port",
        default=int(os.getenv("A2A_PORT", DEFAULT_PORT)),
        type=int,
        help=f"Port to bind. Default: {DEFAULT_PORT}",
    )
    parser.add_argument(
        "--backend",
        default=os.getenv("A2A_BACKEND", DEFAULT_BACKEND),
        help=f"SAG Maker backend URL. Default: {DEFAULT_BACKEND}",
    )
    parser.add_argument(
        "--public-url",
        default=os.getenv("A2A_PUBLIC_URL", ""),
        help=(
            "JSON-RPC URL advertised in the A2A AgentCard. "
            "Defaults to http://{host}:{port}/api/a2a."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    public_url = args.public_url.strip() or default_public_url(host=args.host, port=args.port)
    uvicorn.run(build_app(backend_url=args.backend, public_url=public_url), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
