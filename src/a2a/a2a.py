"""Nacos v3 A2A AgentCard 注册中心集成模块。

将 agent.json 中的 agent 元数据转换为 A2A AgentCard 格式，
注册到 Nacos v3 的 A2A 注册中心。

Nacos v3 部署信息（默认值）：
- 地址: nacos.nacos.svc.cluster.local:8848  (集群内 Service DNS，context-path /nacos)
- 账号: nacos / nacos
- 登录: POST /nacos/v1/auth/login  -> accessToken
- 接口: POST /nacos/v3/admin/ai/a2a  (accessToken 通过请求头传递)

环境变量：
- NACOS_A2A_SERVER_ADDR  Nacos 服务地址
- NACOS_A2A_NAMESPACE   命名空间（默认 public）
- NACOS_A2A_USERNAME    用户名
- NACOS_A2A_PASSWORD    密码
- A2A_ENABLED           是否启用（默认 false）
- DOMAIN                对外域名后缀，用于拼装 Ingress 可达的 AgentCard url
"""

from __future__ import annotations

import json
import os
import socket
from typing import Any

import httpx

from src.logger import get_logger
from src.skills.scanner import load_skill_registry
from src.utils.config import load_agent_config

logger = get_logger(__name__)

# ---- Nacos 连接参数（环境变量可覆盖）----
A2A_ENABLED = os.getenv("A2A_ENABLED", "").strip().lower() in ("true", "1", "yes")
_NACOS_SERVER_ADDR = os.getenv("NACOS_A2A_SERVER_ADDR", "nacos.nacos.svc.cluster.local:8848").strip()
_NACOS_NAMESPACE = os.getenv("NACOS_A2A_NAMESPACE", "").strip()
_NACOS_USERNAME = os.getenv("NACOS_A2A_USERNAME", "nacos").strip()
_NACOS_PASSWORD = os.getenv("NACOS_A2A_PASSWORD", "nacos").strip()
_NACOS_PATH_PREFIX = "/nacos"

# ---- AgentCard 元数据 ----
A2A_PROTOCOL_VERSION = os.getenv("A2A_AGENT_PROTOCOL_VERSION", "1.0.0").strip()
AGENT_METADATA_EXTENSION_URI = "urn:sag-maker:agent-metadata:v1"
_DEFAULT_CAPABILITIES = {
    "streaming": True,
    "pushNotifications": False,
    "stateTransitionHistory": False,
}
_DEFAULT_INPUT_MODES = ["application/json", "text/plain"]
_DEFAULT_OUTPUT_MODES = ["application/json", "text/plain"]


def _build_nacos_url(path: str) -> str:
    """构建 Nacos 运维 API 完整 URL。"""
    addr = _NACOS_SERVER_ADDR.rstrip("/")
    return f"http://{addr}{_NACOS_PATH_PREFIX}{path}"


async def _login(client: httpx.AsyncClient) -> str | None:
    """使用用户名密码登录 Nacos，返回 accessToken。

    未配置用户名/密码时返回 None（表示无需鉴权）。
    """
    if not (_NACOS_USERNAME and _NACOS_PASSWORD):
        return None
    login_url = _build_nacos_url("/v1/auth/login")
    resp = await client.post(
        login_url,
        data={"username": _NACOS_USERNAME, "password": _NACOS_PASSWORD},
    )
    resp.raise_for_status()
    token = resp.json().get("accessToken")
    if not token:
        raise ValueError("Nacos login response missing accessToken")
    return token


# A2A 协议对外暴露相关（经 ex-lb https 网关 -> 集群 Ingress -> 沙箱 8010）
_A2A_PUBLIC_SCHEME = os.getenv("A2A_PUBLIC_SCHEME", "https").strip() or "https"
# A2A 端点统一挂载前缀（与 src/a2a/server.py 的 A2A_ROUTE_PREFIX 保持一致）
_A2A_ROUTE_PREFIX = "/a2a"


def _resolve_public_base() -> str:
    """解析对外可达的基础地址（scheme://host[:port]，不含路径）。

    - HOSTNAME 为沙箱实例的 Pod 主机名（形如 sandbox-<instanceId>）。
    - DOMAIN 为对外域名后缀（由环境变量 DOMAIN 注入，如 sugon.xyz）。
    - INGRESS_PORT 为 ex-lb https 网关端口（由环境变量 INGRESS_PORT 注入，如 58043）。
    该地址经 ex-lb 网关按域名分流到集群 Ingress，可被外部 Nacos 注册中心访问。
    DOMAIN 为空时回退为不带域名后缀（仅内部可达）。
    """
    hostname = os.getenv("HOSTNAME", "").strip() or socket.gethostname()
    domain = os.getenv("DOMAIN", "").strip()
    port = os.getenv("INGRESS_PORT", "").strip()
    host = f"{hostname}.{domain}" if domain else hostname
    if port:
        host = f"{host}:{port}"
    return f"{_A2A_PUBLIC_SCHEME}://{host}"


def _resolve_agent_url() -> str:
    """解析注册到 Nacos 的 AgentCard url（A2A JSON-RPC 交互端点）。

    规则：{scheme}://{HOSTNAME}.{DOMAIN}:{port}/a2a
    该地址即 A2A 协议的 JSON-RPC 交互端点，注册中心据此路由 A2A 调用。
    """
    base = _resolve_public_base()
    prefix = _A2A_ROUTE_PREFIX.rstrip("/")
    return f"{base}{prefix}"


def _resolve_agent_version() -> str:
    """从 A2A 镜像引用中提取 AgentCard.version。"""
    image = os.getenv("A2A_AGENT_IMAGE", "").strip()
    image_name, separator, tag = image.rpartition(":")
    if separator and "/" not in tag and image_name:
        return tag
    return "1.0.0"


def _resolve_agent_name(config: dict[str, Any]) -> str:
    """生成 AgentCard.name。

    规则：{USER}-{repo_name}-{INSTANCE_ID 后四位}，其中 USER、INSTANCE_ID 取自环境变量。
    - base 优先取 config.repo_name，其次 config.name。
      repo_name 为英文标识，可避免中文等非法字符导致 Nacos agentName 校验失败。
    - 环境变量 USER 为空时，退回为不带前缀的 base。
    - 环境变量 INSTANCE_ID 为空时，退回为不带实例后缀。
    """
    base = config.get("repo_name", "").strip() or config.get("name", "").strip()
    if not base:
        return ""
    user = os.getenv("USER", "").strip()
    name = f"{user}-{base}" if user else base
    instance_id = os.getenv("INSTANCE_ID", "").strip()
    if instance_id:
        name = f"{name}-{instance_id[-4:]}"
    return name


def _build_agent_card(config: dict[str, Any], agent_url: str) -> dict[str, Any]:
    """从 agent.json 配置构建 A2A AgentCard。

    映射关系：
    - {env USER}-repo_name-{env INSTANCE_ID 后四位} -> AgentCard.name
    - agent.description  -> AgentCard.description
    - agent.avatar       -> AgentCard.iconUrl
    - agent.welcome_message -> (用于 description 补充)
    - skills/skills.json  -> AgentCard.skills (本地技能，管理端权威来源)
    - agent.mcp           -> AgentCard.skills (MCP 工具)
    """
    name = _resolve_agent_name(config)
    description = config.get("description", "").strip()
    avatar = config.get("avatar", "").strip()
    skills = _build_skills(config)
    capabilities = dict(_DEFAULT_CAPABILITIES)
    raw_business_name = config.get("name")
    business_name = raw_business_name.strip() if isinstance(raw_business_name, str) else ""
    if business_name:
        capabilities["extensions"] = [
            {
                "uri": AGENT_METADATA_EXTENSION_URI,
                "description": "SAG Maker agent business metadata",
                "required": False,
                "params": {
                    "displayName": business_name,
                },
            }
        ]

    card: dict[str, Any] = {
        "protocolVersion": A2A_PROTOCOL_VERSION,
        "name": name,
        "description": description,
        "url": agent_url,
        "preferredTransport": "JSONRPC",
        "version": _resolve_agent_version(),
        "capabilities": capabilities,
        "defaultInputModes": list(_DEFAULT_INPUT_MODES),
        "defaultOutputModes": list(_DEFAULT_OUTPUT_MODES),
        "skills": skills,
    }

    if avatar:
        card["iconUrl"] = avatar

    return card


def _build_skills(config: dict[str, Any]) -> list[dict[str, Any]]:
    """构建 AgentCard skills 列表。

    数据源：
    1. 本地技能：skills/skills.json（管理端增删技能的权威来源，via load_skill_registry）。
       注意 agent.json 的 "skills" 字段仅是技能目录占位（如 ${HOME}/project/skills），
       不能作为技能清单来源。
    2. MCP 工具：agent.json 的 "mcp" 字段。
    """
    skills: list[dict[str, Any]] = []

    # 1. 从 skills.json 构建（本地技能，管理端配置的权威来源）
    for item in load_skill_registry():
        name_en = str(item.get("nameEn", "")).strip()
        if not name_en:
            continue
        name_cn = str(item.get("nameCn", "")).strip()
        skills.append({
            "id": f"skill-{name_en}",
            "name": name_cn or name_en,
            "description": str(item.get("desc", "")).strip(),
            "tags": _extract_skill_tags(item.get("tags")),
        })

    # 2. 从 MCP 配置构建（MCP 工具）
    raw_mcp = config.get("mcp", [])
    if isinstance(raw_mcp, list):
        for item in raw_mcp:
            if not isinstance(item, dict):
                continue
            mcp_name = item.get("name", "")
            if not mcp_name:
                continue
            skills.append({
                "id": f"mcp-{mcp_name}",
                "name": item.get("displayName", mcp_name),
                "description": item.get("description", ""),
                "tags": _extract_skill_tags(item.get("tags")),
            })

    return skills


def _extract_skill_tags(tags: Any) -> list[str]:
    """从 tag 列表中提取标签名称。"""
    if not isinstance(tags, list):
        return []
    result: list[str] = []
    for tag in tags:
        if isinstance(tag, dict):
            for key in ("nameEn", "nameCn", "name"):
                val = tag.get(key, "")
                if val and isinstance(val, str):
                    result.append(val.strip())
                    break
        elif isinstance(tag, str):
            result.append(tag.strip())
    return result


async def agent_card_exists(
    config_path: str | None = None,
    *,
    namespace: str | None = None,
    name: str | None = None,
) -> bool:
    """查询 Nacos A2A 注册中心是否已存在该 AgentCard。

    Args:
        config_path: agent.json 路径，用于在未显式传入 name 时读取 agent 名称。
        namespace: Nacos 命名空间，默认使用全局配置。
        name: agent 名称，优先级高于从 config 读取。

    Returns:
        存在返回 True；不存在或查询失败返回 False。
    """
    agent_name = (name or "").strip()
    if not agent_name:
        try:
            config = load_agent_config(config_path)
        except Exception:
            logger.exception("Failed to load agent config for A2A existence check")
            return False
        agent_name = _resolve_agent_name(config)
    if not agent_name:
        logger.warning("A2A existence check skipped: agent name is empty")
        return False

    ns = (namespace or _NACOS_NAMESPACE or "public").strip()
    url = _build_nacos_url("/v3/admin/ai/a2a")

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            token = await _login(client)
            headers = {"accessToken": token} if token else {}
            response = await client.get(
                url,
                params={"namespaceId": ns, "agentName": agent_name},
                headers=headers,
            )
            if not response.is_success:
                # 4xx/5xx（含 Agent not found）视为不存在
                return False
            body = response.json()
            return body.get("code") == 0
    except httpx.TransportError as exc:
        logger.error("A2A existence check network error: name=%s error=%s", agent_name, exc)
        return False
    except Exception:
        logger.exception("A2A existence check unexpected error: name=%s", agent_name)
        return False


async def register_agent_card(
    config_path: str | None = None,
    *,
    agent_url: str | None = None,
    namespace: str | None = None,
    update: bool = False,
) -> bool:
    """将 agent 注册（或更新）到 Nacos v3 A2A 注册中心。

    Args:
        config_path: agent.json 路径，默认使用标准路径。
        agent_url: agent 的 A2A 服务地址，默认从环境变量推断。
        namespace: Nacos 命名空间，默认使用全局配置。
        update: True 时使用 PUT 更新已存在的 AgentCard，否则使用 POST 创建。

    Returns:
        注册/更新成功返回 True，失败返回 False。
    """
    if not A2A_ENABLED:
        logger.info("A2A registration disabled (A2A_ENABLED≠true), skipping")
        return False

    try:
        config = load_agent_config(config_path)
    except Exception:
        logger.exception("Failed to load agent config for A2A registration")
        return False

    name = _resolve_agent_name(config)
    if not name:
        logger.warning("A2A registration skipped: agent name is empty")
        return False

    resolved_url = agent_url or _resolve_agent_url()
    agent_card = _build_agent_card(config, resolved_url)
    ns = (namespace or _NACOS_NAMESPACE or "public").strip()

    url = _build_nacos_url("/v3/admin/ai/a2a")
    action = "update" if update else "create"

    logger.info(
        "%s agent card to Nacos: name=%s namespace=%s url=%s nacos=%s",
        action.capitalize(),
        name,
        ns,
        resolved_url,
        _NACOS_SERVER_ADDR,
    )

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            token = await _login(client)
            headers = {"accessToken": token} if token else {}
            request_args = {
                "url": url,
                "data": {
                    "namespaceId": ns,
                    "agentCard": json.dumps(agent_card, ensure_ascii=False),
                },
                "headers": headers,
            }
            response = await (
                client.put(**request_args) if update else client.post(**request_args)
            )
            if response.is_success:
                logger.info(
                    "Agent card %sd successfully: name=%s code=%s",
                    action,
                    name,
                    response.status_code,
                )
                return True
            else:
                logger.error(
                    "Agent card %s failed: name=%s code=%s body=%s",
                    action,
                    name,
                    response.status_code,
                    response.text[:500],
                )
                return False
    except httpx.TransportError as exc:
        logger.error("A2A %s network error: name=%s error=%s", action, name, exc)
        return False
    except Exception:
        logger.exception("A2A %s unexpected error: name=%s", action, name)
        return False


async def deregister_agent_card(
    config_path: str | None = None,
    *,
    namespace: str | None = None,
    name: str | None = None,
) -> bool:
    """从 Nacos v3 A2A 注册中心删除该 agent 的 AgentCard（级联删除）。

    在删除智能体（沙箱实例）时调用，同步移除注册中心残留的 AgentCard，
    避免 url 指向已销毁 Ingress 的失效卡片。

    Args:
        config_path: agent.json 路径，用于在未显式传入 name 时计算 agent 名称。
        namespace: Nacos 命名空间，默认使用全局配置。
        name: agent 名称，优先级高于从 config 读取。

    Returns:
        删除成功、目标不存在、A2A 未开启或无从确定卡名（无卡可删）均视为
        “确保卡不存在”的目的已达成，返回 True；仅在 Nacos 删除请求真正失败
        （非 2xx/404）或网络异常时返回 False。

    说明：本函数由删除实例的 finalizer hook 调用，退出码决定 hook 成败。
    “禁用/无卡名/读不到配置”本质是无需注销或无卡可删，必须视为幂等成功，
    否则会让 hook exitCode=1 触发 BlockFinalizer，使实例永久卡在 Deleting。
    """
    if not A2A_ENABLED:
        logger.info("A2A deregistration disabled (A2A_ENABLED≠true), skipping")
        return True

    agent_name = (name or "").strip()
    if not agent_name:
        try:
            config = load_agent_config(config_path)
        except Exception:
            logger.exception("Failed to load agent config for A2A deregistration")
            return True
        agent_name = _resolve_agent_name(config)
    if not agent_name:
        logger.warning("A2A deregistration skipped: agent name is empty (nothing to delete)")
        return True

    ns = (namespace or _NACOS_NAMESPACE or "public").strip()
    url = _build_nacos_url("/v3/admin/ai/a2a")

    logger.info(
        "Delete agent card from Nacos: name=%s namespace=%s nacos=%s",
        agent_name,
        ns,
        _NACOS_SERVER_ADDR,
    )

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            token = await _login(client)
            headers = {"accessToken": token} if token else {}
            response = await client.delete(
                url,
                params={"namespaceId": ns, "agentName": agent_name},
                headers=headers,
            )
            if response.is_success:
                logger.info(
                    "Agent card deleted successfully: name=%s code=%s",
                    agent_name,
                    response.status_code,
                )
                return True
            # 目标不存在（404 或 Nacos "Agent not found"）视为幂等成功
            body_text = response.text or ""
            if response.status_code == 404 or "not found" in body_text.lower():
                logger.info(
                    "Agent card already absent, treat delete as success: name=%s code=%s",
                    agent_name,
                    response.status_code,
                )
                return True
            logger.error(
                "Agent card delete failed: name=%s code=%s body=%s",
                agent_name,
                response.status_code,
                body_text[:500],
            )
            return False
    except httpx.TransportError as exc:
        logger.error("A2A delete network error: name=%s error=%s", agent_name, exc)
        return False
    except Exception:
        logger.exception("A2A delete unexpected error: name=%s", agent_name)
        return False


__all__ = [
    "A2A_ENABLED",
    "A2A_PROTOCOL_VERSION",
    "AGENT_METADATA_EXTENSION_URI",
    "agent_card_exists",
    "deregister_agent_card",
    "register_agent_card",
]


def _main() -> int:
    """命令行入口，供 finalizer hook 在删除实例时调用。

    用法：python -m src.a2a.a2a deregister [--name NAME] [--namespace NS]
    退出码：成功（含目标已不存在的幂等场景）返回 0，失败返回 1。
    """
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(prog="python -m src.a2a.a2a")
    sub = parser.add_subparsers(dest="command", required=True)
    dereg = sub.add_parser("deregister", help="从 Nacos 删除本实例的 AgentCard")
    dereg.add_argument("--name", default=None, help="agent 名称，默认按环境变量+agent.json 推断")
    dereg.add_argument("--namespace", default=None, help="Nacos 命名空间，默认 public")
    args = parser.parse_args()

    if args.command == "deregister":
        ok = asyncio.run(
            deregister_agent_card(namespace=args.namespace, name=args.name)
        )
        return 0 if ok else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(_main())
