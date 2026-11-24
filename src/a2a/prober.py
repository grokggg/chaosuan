"""A2A AgentCard 探活巡检器（供 K8s CronJob 周期调用）。

从 Nacos v3 A2A 注册中心列出所有 AgentCard，对每张卡的 url 派生的
well-known 发现端点（agent-card.json）做 GET 探活。

判定分两层，避免"链路问题误删卡"：
  - INGRESS_DOWN：连接超时/拒绝/DNS/TLS 失败，或收到 nginx 网关错误
    502/503/504（Ingress 通但后端不可达）。**视为链路层问题，绝不删卡。**
  - APP_UNHEALTHY：能从应用拿到 HTTP 响应，但 agent-card.json 不可用
    （非 2xx 的 4xx、404、或 200 但 body 非法 / name 不匹配）。计入删除判定。
  - ALIVE：200 且 body 可解析、name 匹配。

删除策略：仅当**连续 N 次（默认 2）**探测均为 APP_UNHEALTHY（每次间隔
默认 30 秒）时，才注销该卡（deregister）。任一次出现 INGRESS_DOWN 或
ALIVE 都立即中止删除判定（前者存疑不删、后者已恢复）。

健康检查可整体关闭：A2A_HEALTHCHECK_ENABLED=false 时 CLI 直接空转退出。

设计选型见 test/a2a_health_probe_design.md。复用 src/a2a/a2a.py 的 Nacos
连接与注销逻辑，不重复实现登录/URL 拼接。

用法（CronJob 单轮执行）：
    python -m src.a2a.prober run [--namespace NS] [--no-deregister]
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

from src.a2a.a2a import (
    _NACOS_NAMESPACE,
    _NACOS_SERVER_ADDR,
    _build_nacos_url,
    _login,
    deregister_agent_card,
)
from src.logger import get_logger

logger = get_logger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# ---- 可配置项（环境变量覆盖）----
# 健康检查总开关：false 时 CLI 直接退出、不做任何探测/删除
HEALTHCHECK_ENABLED = _env_bool("A2A_HEALTHCHECK_ENABLED", True)
# 判定删除所需的连续应用层失败次数
FAIL_THRESHOLD = int(os.getenv("A2A_PROBE_FAIL_THRESHOLD", "2").strip() or "2")
# 连续探测的间隔秒数
PROBE_INTERVAL = float(os.getenv("A2A_PROBE_INTERVAL", "30").strip() or "30")
# 单次探测超时秒数
PROBE_TIMEOUT = float(os.getenv("A2A_PROBE_TIMEOUT", "5").strip() or "5")

_WELL_KNOWN_SUFFIX = "/.well-known/agent-card.json"
# nginx 网关错误：Ingress 通但后端不可达，归为链路层，不删卡
_GATEWAY_ERROR_CODES = frozenset({502, 503, 504})

# 单次探测结果
ALIVE = "ALIVE"                # 200 且 name 匹配
APP_UNHEALTHY = "APP_UNHEALTHY"  # 应用有响应但卡不可用（计入删除）
INGRESS_DOWN = "INGRESS_DOWN"  # 链路/网关层不通（绝不删卡）


async def list_agent_cards(
    client: httpx.AsyncClient,
    *,
    namespace: str,
    token: str | None,
) -> list[dict[str, Any]]:
    """从 Nacos 列出指定命名空间下的全部 AgentCard。

    对多种可能的响应结构做健壮解析（data.pageItems / data(list) / 顶层 list）。
    """
    url = _build_nacos_url("/v3/admin/ai/a2a/list")
    headers = {"accessToken": token} if token else {}
    params = {
        "namespaceId": namespace,
        "search": "blur",
        "agentName": "",
        "pageNo": "1",
        "pageSize": "1000",
    }
    resp = await client.get(url, params=params, headers=headers)
    resp.raise_for_status()
    payload = resp.json() if resp.content else {}
    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    if isinstance(data, dict):
        items = data.get("pageItems") or data.get("list") or data.get("result") or []
    elif isinstance(data, list):
        items = data
    else:
        items = []
    return [it for it in items if isinstance(it, dict)]


async def fetch_card_detail(
    client: httpx.AsyncClient,
    *,
    namespace: str,
    name: str,
    token: str | None,
) -> dict[str, Any]:
    """按 name 拉取单卡详情，补全列表接口不返回的 url 字段。

    Nacos v3 A2A 的 list 接口（pageItems）仅含 name/skills/version 等元数据，
    不含探活所需的 url；url 只在详情接口 GET /v3/admin/ai/a2a 的 data.url 中。
    """
    url = _build_nacos_url("/v3/admin/ai/a2a")
    headers = {"accessToken": token} if token else {}
    params = {"namespaceId": namespace, "agentName": name}
    resp = await client.get(url, params=params, headers=headers)
    resp.raise_for_status()
    payload = resp.json() if resp.content else {}
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else {}


def _probe_url_of(card: dict[str, Any]) -> str | None:
    """由 AgentCard.url 派生 well-known 发现端点探活地址。"""
    card_url = (card.get("url") or "").strip()
    if not card_url:
        return None
    return card_url.rstrip("/") + _WELL_KNOWN_SUFFIX


async def probe_once(probe_url: str, expect_name: str) -> str:
    """对发现端点做一次探测，返回 ALIVE / APP_UNHEALTHY / INGRESS_DOWN。

    区分逻辑：
    - 无法拿到任何 HTTP 响应（连接/超时/TLS/DNS）→ INGRESS_DOWN
    - 收到 nginx 网关错误 502/503/504 → INGRESS_DOWN（Ingress 通但后端不可达）
    - 200 且 body.name 匹配（或无期望名）→ ALIVE
    - 其他（4xx/404/200 但 body 非法或 name 不符）→ APP_UNHEALTHY
    """
    try:
        # trust_env=False 禁用环境代理（现网部分节点有代理会导致卡住）；
        # verify=False 兼容 sugon.xyz 自签名证书。
        async with httpx.AsyncClient(
            timeout=PROBE_TIMEOUT, verify=False, trust_env=False
        ) as client:
            resp = await client.get(probe_url)
    except httpx.TransportError as exc:
        logger.info("Probe transport error (ingress down) url=%s err=%s", probe_url, exc)
        return INGRESS_DOWN

    if resp.status_code in _GATEWAY_ERROR_CODES:
        logger.info("Probe gateway error (ingress down) url=%s code=%s", probe_url, resp.status_code)
        return INGRESS_DOWN

    if resp.is_success:
        try:
            got_name = (resp.json() or {}).get("name", "")
        except Exception:
            logger.info("Probe 200 but invalid body url=%s", probe_url)
            return APP_UNHEALTHY
        if not expect_name or got_name == expect_name:
            return ALIVE
        logger.info("Probe name mismatch url=%s expect=%s got=%s", probe_url, expect_name, got_name)
        return APP_UNHEALTHY

    logger.info("Probe app unhealthy url=%s code=%s", probe_url, resp.status_code)
    return APP_UNHEALTHY


async def evaluate_card(card: dict[str, Any]) -> tuple[str, str]:
    """对单张卡做"连续 N 次、间隔 T 秒"的评估，返回 (最终决策, 最后一次状态)。

    最终决策：
    - DELETE  ：连续 FAIL_THRESHOLD 次均为 APP_UNHEALTHY → 应用确不可用，删卡
    - KEEP    ：其余情况（曾 ALIVE，或出现过 INGRESS_DOWN）→ 保留

    出现 INGRESS_DOWN 或 ALIVE 立即短路返回 KEEP，不再继续后续探测。
    """
    probe_url = _probe_url_of(card)
    expect_name = (card.get("name") or "").strip()
    if not probe_url:
        logger.warning("Evaluate skipped: card has empty url name=%s", expect_name)
        return "KEEP", INGRESS_DOWN

    last_status = INGRESS_DOWN
    for attempt in range(1, FAIL_THRESHOLD + 1):
        status = await probe_once(probe_url, expect_name)
        last_status = status
        if status == ALIVE:
            return "KEEP", status          # 已恢复/健康
        if status == INGRESS_DOWN:
            return "KEEP", status          # 链路存疑，绝不删卡
        # APP_UNHEALTHY：继续下一次确认
        if attempt < FAIL_THRESHOLD:
            await asyncio.sleep(PROBE_INTERVAL)

    # 连续 FAIL_THRESHOLD 次均为 APP_UNHEALTHY
    return "DELETE", last_status


async def run_once(
    *,
    namespace: str | None = None,
    deregister_dead: bool = True,
) -> dict[str, int]:
    """执行一轮巡检：列卡 → 逐张评估 → 对判定 DELETE 的卡注销。

    Returns:
        统计字典 {total, alive, app_unhealthy, ingress_down, deleted}。
    """
    if not HEALTHCHECK_ENABLED:
        logger.info("A2A health check disabled (A2A_HEALTHCHECK_ENABLED=false), skip")
        return {"total": 0, "alive": 0, "app_unhealthy": 0, "ingress_down": 0, "deleted": 0}

    ns = (namespace or _NACOS_NAMESPACE or "public").strip()
    stats = {"total": 0, "alive": 0, "app_unhealthy": 0, "ingress_down": 0, "deleted": 0}

    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        token = await _login(client)
        cards = await list_agent_cards(client, namespace=ns, token=token)

        # list 接口不返回 url，逐张拉详情补全（探活依赖 url）。并发拉取。
        async def _fill_url(card: dict[str, Any]) -> None:
            name = (card.get("name") or "").strip()
            if not name or (card.get("url") or "").strip():
                return
            try:
                detail = await fetch_card_detail(client, namespace=ns, name=name, token=token)
            except Exception as exc:
                logger.warning("Fetch card detail failed name=%s err=%s", name, exc)
                return
            if detail.get("url"):
                card["url"] = detail["url"]

        await asyncio.gather(*(_fill_url(c) for c in cards))

    stats["total"] = len(cards)
    logger.info(
        "A2A probe start: namespace=%s total=%d threshold=%d interval=%ss nacos=%s",
        ns, len(cards), FAIL_THRESHOLD, PROBE_INTERVAL, _NACOS_SERVER_ADDR,
    )

    # 卡片间并发评估：每张卡内部"连续 N 次间隔 T 秒"仍串行，但各卡的等待重叠，
    # 单轮总耗时从 ∑(卡×N×T) 降到约 N×T，避免超过 CronJob activeDeadlineSeconds。
    decisions = await asyncio.gather(*(evaluate_card(c) for c in cards))

    for card, (decision, last_status) in zip(cards, decisions, strict=True):
        name = (card.get("name") or "").strip()
        key = {ALIVE: "alive", APP_UNHEALTHY: "app_unhealthy", INGRESS_DOWN: "ingress_down"}[last_status]
        stats[key] += 1
        logger.info("A2A probe result: name=%s decision=%s last=%s", name, decision, last_status)

        if decision == "DELETE" and deregister_dead and name:
            ok = await deregister_agent_card(namespace=ns, name=name)
            if ok:
                stats["deleted"] += 1
                logger.info("Deregistered unhealthy agent card: name=%s", name)
            else:
                logger.error("Failed to deregister unhealthy agent card: name=%s", name)

    logger.info(
        "A2A probe done: total=%d alive=%d app_unhealthy=%d ingress_down=%d deleted=%d",
        stats["total"], stats["alive"], stats["app_unhealthy"], stats["ingress_down"], stats["deleted"],
    )
    return stats


__all__ = [
    "ALIVE", "APP_UNHEALTHY", "INGRESS_DOWN",
    "list_agent_cards", "probe_once", "evaluate_card", "run_once", "fetch_card_detail",
]


def _main() -> int:
    """命令行入口，供 K8s CronJob 单轮调用。

    用法：python -m src.a2a.prober run [--namespace NS] [--no-deregister]
    退出码：巡检完成返回 0；发生未捕获异常返回 1。
    """
    import argparse

    parser = argparse.ArgumentParser(prog="python -m src.a2a.prober")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="执行一轮 AgentCard 探活巡检")
    run_p.add_argument("--namespace", default=None, help="Nacos 命名空间，默认 public")
    run_p.add_argument(
        "--no-deregister",
        action="store_true",
        help="仅探活并打印统计，不注销判定不健康的卡片",
    )
    args = parser.parse_args()

    if args.command == "run":
        try:
            asyncio.run(
                run_once(
                    namespace=args.namespace,
                    deregister_dead=not args.no_deregister,
                )
            )
        except Exception:
            logger.exception("A2A probe run failed")
            return 1
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(_main())
