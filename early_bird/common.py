"""早鸟工作台共享模块：契约加载、路径解析、状态机与 high 信源校验。

所有脚本（guide.py / aggregate.py）与 src/tools/early_bird.py 共用本模块，
保证 CLI 与工具入口的校验规则完全一致。
"""

from __future__ import annotations

import json
import os
import re
from datetime import date as date_cls
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
CONTRACT_PATH = SCRIPT_DIR / "tracking_contract_v2.json"

FLOW_STEPS: tuple[str, ...] = ("B1", "B2", "B3", "B4")
STEP_TO_STATUS: dict[str, str] = {
    "B1": "B1_DONE",
    "B2": "B2_DONE",
    "B3": "B3_DONE",
    "B4": "DONE",
}
TERMINAL_STATUSES: frozenset[str] = frozenset({"DONE", "EMPTY_SILENT"})

DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
EVENT_ID_RE = re.compile(r"^[a-z0-9]+-\d{8}-\d{2,4}$")
URL_RE = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)

EVENT_REQUIRED_FIELDS: tuple[str, ...] = (
    "event_id",
    "title",
    "signal_type",
    "happened_at",
    "summary",
    "why_early_signal",
    "impact",
    "confidence",
    "sources",
)
SOURCE_REQUIRED_FIELDS: tuple[str, ...] = (
    "url",
    "domain",
    "publisher",
    "tier",
    "published_at",
    "quote",
)
CANDIDATE_REQUIRED_FIELDS: tuple[str, ...] = (
    "title",
    "url",
    "domain",
    "publisher",
    "tier",
    "published_at",
    "focus_tag",
)
SUMMARY_REQUIRED_FIELDS: tuple[str, ...] = (
    "date",
    "domain",
    "domain_slug",
    "setup_token",
    "event_count",
    "empty",
    "top_events",
    "source_stats",
    "generated_at",
)


# --------------------------------------------------------------------------- #
# 基础 IO
# --------------------------------------------------------------------------- #
def resolve(rel: str | Path) -> Path:
    """把契约中的相对路径解析为绝对路径（相对项目根，可用环境变量覆盖）。"""
    path = Path(str(rel))
    if path.is_absolute():
        return path
    override = os.getenv("EARLY_BIRD_ROOT", "").strip()
    root = Path(override) if override else PROJECT_ROOT
    return (root / path).resolve()


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp, path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(tmp, path)


def parse_date(value: Any) -> date_cls | None:
    """宽松解析 YYYY-MM-DD / ISO8601 / YYYY/MM/DD，失败返回 None。"""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    match = DATE_RE.match(text)
    if not match:
        return None
    try:
        return date_cls(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def normalize_domain(value: Any) -> str:
    """从 URL 或裸域名中提取可比较的主域名（去掉 www. 前缀与端口）。"""
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if "://" not in text:
        text = "http://" + text
    try:
        host = urlparse(text).hostname or ""
    except ValueError:
        return ""
    host = host.strip().lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


# --------------------------------------------------------------------------- #
# 契约
# --------------------------------------------------------------------------- #
def load_contract(path: Path | None = None) -> dict[str, Any]:
    contract_path = Path(path) if path else CONTRACT_PATH
    if not contract_path.exists():
        raise FileNotFoundError(f"追踪契约不存在: {contract_path}")
    contract = read_json(contract_path)
    if not isinstance(contract, dict) or not isinstance(contract.get("domains"), list):
        raise ValueError(f"追踪契约格式非法: {contract_path}")
    return contract


def find_domain(contract: dict[str, Any], key: str) -> dict[str, Any] | None:
    """按 setup_token / domain_slug / 中文名 / 领域名 精确或包含匹配领域。"""
    needle = str(key or "").strip()
    if not needle:
        return None
    low = needle.lower()
    domains: list[dict[str, Any]] = contract.get("domains", [])
    for domain in domains:
        candidates = {
            str(domain.get("setup_token", "")).lower(),
            str(domain.get("domain_slug", "")).lower(),
            str(domain.get("name_cn", "")),
            str(domain.get("domain", "")),
        }
        if low in candidates:
            return domain
    for domain in domains:
        haystack = " ".join(
            [
                str(domain.get("setup_token", "")),
                str(domain.get("domain_slug", "")),
                str(domain.get("name_cn", "")),
                str(domain.get("domain", "")),
            ]
        ).lower()
        if low and low in haystack:
            return domain
    return None


def global_rules(contract: dict[str, Any]) -> dict[str, Any]:
    rules = contract.get("global_rules")
    return rules if isinstance(rules, dict) else {}


def min_domains(contract: dict[str, Any], domain: dict[str, Any]) -> int:
    for source in (domain, global_rules(contract)):
        value = source.get("min_independent_domains_per_event")
        if isinstance(value, int) and value > 0:
            return value
    return 3


def domain_dir(domain: dict[str, Any]) -> Path:
    return resolve(domain["output_dir"])


def artifact_paths(domain: dict[str, Any], day: str) -> dict[str, Path]:
    base = domain_dir(domain)
    return {
        "base": base,
        "state": base / "state.json",
        "candidates": base / "raw_candidates.json",
        "event_list": base / "event_list.json",
        "summary": base / "summary.json",
        "report": base / "daily" / f"{day}.md",
        "archive_dir": base / "daily" / day,
    }


def read_paths_for_day(domain: dict[str, Any], day: str) -> dict[str, Path]:
    """返回读取某日产物时应使用的路径。

    若该日已归档（daily/<date>/ 下有对应文件），优先读归档副本，避免把
    base 层「最新一次运行」的产物误当成历史日期的产物；未归档时回退到 base。
    """
    paths = artifact_paths(domain, day)
    archive_dir: Path = paths["archive_dir"]
    if not archive_dir.is_dir():
        return paths
    resolved = dict(paths)
    for key in ("state", "candidates", "event_list", "summary"):
        candidate = archive_dir / paths[key].name
        if candidate.exists():
            resolved[key] = candidate
    return resolved


# --------------------------------------------------------------------------- #
# 状态机
# --------------------------------------------------------------------------- #
def blank_state(domain: dict[str, Any], day: str, flow: str = "briefing") -> dict[str, Any]:
    return {
        "flow": flow,
        "setup_token": domain.get("setup_token", ""),
        "domain": domain.get("domain", ""),
        "domain_slug": domain.get("domain_slug", ""),
        "name_cn": domain.get("name_cn", ""),
        "date": day,
        "status": "INIT",
        "steps": {
            step: {"status": "pending", "attempts": 0, "errors": [], "finished_at": None}
            for step in FLOW_STEPS
        },
        "event_count": None,
        "empty_silent": bool(domain.get("empty_silent", True)),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "history": [],
    }


def load_state(paths: dict[str, Path]) -> dict[str, Any] | None:
    state_path = paths["state"]
    if not state_path.exists():
        return None
    try:
        state = read_json(state_path)
    except (json.JSONDecodeError, OSError):
        return None
    return state if isinstance(state, dict) else None


def load_state_for_day(paths: dict[str, Path], day: str) -> dict[str, Any] | None:
    """读取状态，且只在状态归属日期与请求日一致时返回。

    state.json 保存的是该领域最近一次运行的状态；查询历史日期时应回退到
    daily/<date>/state.json 归档，避免把今天的状态误报成历史日期的状态。
    """
    state = load_state(paths)
    if state and str(state.get("date", "")) == day:
        return state
    archived_state = paths["archive_dir"] / "state.json"
    if archived_state.exists():
        try:
            archived = read_json(archived_state)
        except (json.JSONDecodeError, OSError):
            return None
        if isinstance(archived, dict) and str(archived.get("date", "")) == day:
            return archived
    return None


def save_state(paths: dict[str, Path], state: dict[str, Any]) -> None:
    state["updated_at"] = now_iso()
    write_json(paths["state"], state)


def current_step(state: dict[str, Any]) -> str | None:
    """返回下一个待完成的步骤；已终态返回 None。"""
    if state.get("status") in TERMINAL_STATUSES:
        return None
    for step in FLOW_STEPS:
        info = state.get("steps", {}).get(step, {})
        if info.get("status") != "passed":
            return step
    return None


def next_step_after(state: dict[str, Any], step: str) -> str | None:
    index = FLOW_STEPS.index(step)
    for candidate in FLOW_STEPS[index + 1 :]:
        info = state.get("steps", {}).get(candidate, {})
        if info.get("status") != "passed":
            return candidate
    return None


# --------------------------------------------------------------------------- #
# 校验
# --------------------------------------------------------------------------- #
class CheckResult:
    """一次步骤校验的结果。"""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "errors": self.errors, "warnings": self.warnings}


def _non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_candidates(
    payload: Any,
    contract: dict[str, Any],
    domain: dict[str, Any],
    day: str,
) -> CheckResult:
    """B1：候选信号清单校验（允许空数组，走空结果分支）。"""
    result = CheckResult()
    if not isinstance(payload, list):
        result.error("raw_candidates.json 顶层必须是数组")
        return result

    run_day = parse_date(day) or date_cls.today()
    horizon = run_day + timedelta(days=1)
    focus = [str(item) for item in domain.get("focus", [])]

    if not payload:
        result.warn("候选清单为空数组：B2 必须同样提交空 event_list.json，最终状态将为 EMPTY_SILENT")
        return result

    min_items = 1
    step_def = contract.get("briefing_flow", {}).get("step_definitions", {}).get("B1", {})
    if isinstance(step_def.get("min_items"), int):
        min_items = max(1, step_def["min_items"])
    if len(payload) < min_items:
        result.warn(f"候选数量 {len(payload)} 少于建议值 {min_items}，覆盖度可能不足")

    seen_urls: set[str] = set()
    for index, item in enumerate(payload, 1):
        label = f"候选#{index}"
        if not isinstance(item, dict):
            result.error(f"{label} 必须是对象")
            continue
        for field in CANDIDATE_REQUIRED_FIELDS:
            if not _non_empty_str(item.get(field)):
                result.error(f"{label} 字段 {field} 缺失或为空")
        url = str(item.get("url", "")).strip()
        if url and not URL_RE.match(url):
            result.error(f"{label} url 非法（必须是 http/https 链接）: {url[:80]}")
        if url:
            if url in seen_urls:
                result.warn(f"{label} url 重复: {url[:80]}")
            seen_urls.add(url)
        derived = normalize_domain(url)
        declared = normalize_domain(item.get("domain"))
        if derived and declared and derived != declared:
            result.error(f"{label} domain({declared}) 与 url 主域名({derived}) 不一致")
        tier = str(item.get("tier", "")).strip().lower()
        if tier not in {"tier1", "tier2", "unknown"}:
            result.error(f"{label} tier 只能是 tier1/tier2/unknown，当前: {tier or '(空)'}")
        published = parse_date(item.get("published_at"))
        if not published:
            result.error(f"{label} published_at 无法解析为日期: {item.get('published_at')!r}")
        elif published > horizon:
            result.error(f"{label} published_at 晚于运行日+1（{horizon}），疑似时间错误")
        if focus and _non_empty_str(item.get("focus_tag")):
            tag = str(item["focus_tag"]).strip()
            if not any(tag in entry or entry in tag for entry in focus):
                result.warn(f"{label} focus_tag 未命中契约 focus 方向: {tag}")
    return result


def validate_events(
    payload: Any,
    contract: dict[str, Any],
    domain: dict[str, Any],
    day: str,
) -> CheckResult:
    """B2：合格事件列表校验，执行 high 信源硬规则。"""
    result = CheckResult()
    if not isinstance(payload, list):
        result.error("event_list.json 顶层必须是数组")
        return result

    if not payload:
        result.warn("event_list.json 为空数组：B3 日报必须写明「今日无合格早期信号」，最终状态 EMPTY_SILENT")
        return result

    required_domains = min_domains(contract, domain)
    signal_types = [str(item) for item in domain.get("signal_types", [])]
    tier2_registry = [str(item).strip().lower() for item in (domain.get("sources") or {}).get("tier2", [])]
    run_day = parse_date(day) or date_cls.today()
    horizon = run_day + timedelta(days=1)
    seen_ids: set[str] = set()

    for index, event in enumerate(payload, 1):
        if not isinstance(event, dict):
            result.error(f"事件#{index} 必须是对象")
            continue
        event_id = str(event.get("event_id", "")).strip()
        label = f"事件[{event_id or index}]"

        for field in EVENT_REQUIRED_FIELDS:
            value = event.get(field)
            if field == "sources":
                if not isinstance(value, list) or not value:
                    result.error(f"{label} sources 必须是非空数组")
            elif not _non_empty_str(value):
                result.error(f"{label} 字段 {field} 缺失或为空")

        if event_id:
            if event_id in seen_ids:
                result.error(f"{label} event_id 重复")
            seen_ids.add(event_id)
            if not EVENT_ID_RE.match(event_id):
                result.warn(f"{label} event_id 建议格式 <slug>-YYYYMMDD-NN，当前: {event_id}")

        confidence = str(event.get("confidence", "")).strip().lower()
        if confidence not in {"high", "medium"}:
            result.error(f"{label} confidence 只能是 high/medium（low 不得提交），当前: {confidence or '(空)'}")

        signal_type = str(event.get("signal_type", "")).strip()
        if signal_types and signal_type and signal_type not in signal_types:
            result.warn(f"{label} signal_type 未在契约 signal_types 中: {signal_type}")

        happened = parse_date(event.get("happened_at"))
        if not happened:
            result.error(f"{label} happened_at 无法解析为日期: {event.get('happened_at')!r}")
        elif happened > horizon:
            result.error(f"{label} happened_at 晚于运行日+1（{horizon}），时间不确定不得提交")

        sources = event.get("sources")
        if not isinstance(sources, list) or not sources:
            continue

        domains_seen: set[str] = set()
        tier1_count = 0
        tier2_count = 0
        for s_index, source in enumerate(sources, 1):
            s_label = f"{label} 来源#{s_index}"
            if not isinstance(source, dict):
                result.error(f"{s_label} 必须是对象")
                continue
            for field in SOURCE_REQUIRED_FIELDS:
                if not _non_empty_str(source.get(field)):
                    result.error(f"{s_label} 字段 {field} 缺失或为空")
            url = str(source.get("url", "")).strip()
            if url and not URL_RE.match(url):
                result.error(f"{s_label} url 非法（必须是 http/https 链接）: {url[:80]}")
            derived = normalize_domain(url)
            declared = normalize_domain(source.get("domain"))
            if declared:
                domains_seen.add(declared)
            elif derived:
                domains_seen.add(derived)
            if derived and declared and derived != declared:
                result.error(f"{s_label} domain({declared}) 与 url 主域名({derived}) 不一致")
            tier = str(source.get("tier", "")).strip().lower()
            if tier == "tier1":
                tier1_count += 1
            elif tier == "tier2":
                tier2_count += 1
                publisher = str(source.get("publisher", "")).strip().lower()
                if tier2_registry and publisher and not any(
                    publisher in entry or entry in publisher for entry in tier2_registry
                ):
                    result.warn(
                        f"{s_label} 被标为 tier2 但发布机构「{source.get('publisher')}」不在本领域 tier2 信源清单内；"
                        "如确属主流媒体请将其加入契约 tier2 清单，否则应降为 unknown 并补充清单内来源"
                    )
            else:
                result.error(f"{s_label} tier 只能是 tier1/tier2，unknown 不得作为合格来源（当前: {tier or '(空)'}）")
            published = parse_date(source.get("published_at"))
            if not published:
                result.error(f"{s_label} published_at 无法解析为日期: {source.get('published_at')!r}")
            elif published > horizon:
                result.error(f"{s_label} published_at 晚于运行日+1（{horizon}），时间不确定不得提交")

        if len(domains_seen) < required_domains:
            result.error(
                f"{label} 独立域名数 {len(domains_seen)} < 要求 {required_domains}"
                f"（authority_requirement=high）；已识别域名: {sorted(domains_seen)}"
            )
        if not (tier1_count >= 1 or tier2_count >= 2):
            result.error(
                f"{label} 信源等级不达标：需 Tier-1 官方源 ×1 或 Tier-2 主流媒体 ×2，"
                f"当前 tier1={tier1_count} tier2={tier2_count}"
            )

        summary_text = str(event.get("summary", ""))
        if summary_text and not (60 <= len(summary_text) <= 600):
            result.warn(f"{label} summary 长度 {len(summary_text)} 字，建议 120-250 字")
    return result


def validate_report(
    paths: dict[str, Path],
    contract: dict[str, Any],
    domain: dict[str, Any],
    day: str,
) -> CheckResult:
    """B3：日报 Markdown 与 summary.json 校验。"""
    result = CheckResult()
    report_path: Path = paths["report"]
    summary_path: Path = paths["summary"]

    if not report_path.exists():
        result.error(f"日报缺失: {report_path}")
        report_text = ""
    else:
        report_text = report_path.read_text(encoding="utf-8").strip()
        if not report_text:
            result.error(f"日报为空文件: {report_path}")

    if not summary_path.exists():
        result.error(f"summary.json 缺失: {summary_path}")
        return result
    try:
        summary = read_json(summary_path)
    except (json.JSONDecodeError, OSError) as exc:
        result.error(f"summary.json 解析失败: {exc}")
        return result
    if not isinstance(summary, dict):
        result.error("summary.json 顶层必须是对象")
        return result

    for field in SUMMARY_REQUIRED_FIELDS:
        if field not in summary or summary[field] is None or summary[field] == "":
            result.error(f"summary.json 字段 {field} 缺失或为空")

    events: list[Any] = []
    if paths["event_list"].exists():
        try:
            loaded = read_json(paths["event_list"])
            events = loaded if isinstance(loaded, list) else []
        except (json.JSONDecodeError, OSError) as exc:
            result.error(f"event_list.json 解析失败: {exc}")

    if str(summary.get("date", "")).strip() != day:
        result.error(f"summary.json.date={summary.get('date')!r} 与运行日 {day} 不一致")
    if str(summary.get("domain_slug", "")).strip() != str(domain.get("domain_slug", "")):
        result.error(
            f"summary.json.domain_slug={summary.get('domain_slug')!r} "
            f"应为 {domain.get('domain_slug')!r}"
        )
    if str(summary.get("setup_token", "")).strip() != str(domain.get("setup_token", "")):
        result.error("summary.json.setup_token 与契约不一致")

    count = summary.get("event_count")
    if not isinstance(count, int) or isinstance(count, bool):
        result.error(f"summary.json.event_count 必须是整数，当前: {count!r}")
    elif count != len(events):
        result.error(f"summary.json.event_count={count} 与 event_list.json 长度 {len(events)} 不一致")

    empty_flag = summary.get("empty")
    if not isinstance(empty_flag, bool):
        result.error(f"summary.json.empty 必须是布尔值，当前: {empty_flag!r}")
    else:
        if empty_flag and len(events) != 0:
            result.error("summary.json.empty=true 但 event_list.json 非空")
        if not empty_flag and len(events) == 0:
            result.error("summary.json.empty=false 但 event_list.json 为空")

    top_events = summary.get("top_events")
    if not isinstance(top_events, list):
        result.error("summary.json.top_events 必须是数组")
    elif events and not top_events:
        result.error("有合格事件时 summary.json.top_events 不得为空")
    else:
        valid_ids = {str(e.get("event_id", "")) for e in events if isinstance(e, dict)}
        for t_index, top in enumerate(top_events, 1):
            if not isinstance(top, dict):
                result.error(f"top_events#{t_index} 必须是对象")
                continue
            for field in ("event_id", "title"):
                if not _non_empty_str(top.get(field)):
                    result.error(f"top_events#{t_index} 字段 {field} 缺失或为空")
            top_id = str(top.get("event_id", "")).strip()
            if valid_ids and top_id and top_id not in valid_ids:
                result.error(f"top_events#{t_index} event_id={top_id} 在 event_list.json 中不存在")

    stats = summary.get("source_stats")
    if not isinstance(stats, dict):
        result.error("summary.json.source_stats 必须是对象")
    else:
        for field in ("tier1_count", "tier2_count", "independent_domain_count"):
            value = stats.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                result.error(f"summary.json.source_stats.{field} 必须是非负整数，当前: {value!r}")
        if isinstance(stats.get("tier1_count"), int) and isinstance(stats.get("tier2_count"), int):
            expected_tier1 = sum(
                1
                for event in events
                if isinstance(event, dict)
                for src in event.get("sources", []) or []
                if isinstance(src, dict) and str(src.get("tier", "")).lower() == "tier1"
            )
            expected_tier2 = sum(
                1
                for event in events
                if isinstance(event, dict)
                for src in event.get("sources", []) or []
                if isinstance(src, dict) and str(src.get("tier", "")).lower() == "tier2"
            )
            if stats["tier1_count"] != expected_tier1:
                result.warn(
                    f"source_stats.tier1_count={stats['tier1_count']} 与事件来源统计 {expected_tier1} 不一致"
                )
            if stats["tier2_count"] != expected_tier2:
                result.warn(
                    f"source_stats.tier2_count={stats['tier2_count']} 与事件来源统计 {expected_tier2} 不一致"
                )

    if report_text:
        expected_title = f"早鸟雷达-{domain.get('domain', '')}"
        first_line = report_text.splitlines()[0].strip()
        if expected_title not in first_line:
            result.warn(f"日报首行标题建议包含「{expected_title}」，当前: {first_line[:60]}")
        if day not in report_text:
            result.warn(f"日报正文未出现运行日 {day}")
        if not events and len(report_text) > 400:
            result.warn("空结果日日报过长，疑似填充凑数内容；只应写一行无合格信号说明")
    return result


def validate_final(
    paths: dict[str, Path],
    contract: dict[str, Any],
    domain: dict[str, Any],
    day: str,
) -> CheckResult:
    """B4：三件产物一致性与完整性终检。"""
    result = CheckResult()
    for key in ("report", "event_list", "summary"):
        path: Path = paths[key]
        if not path.exists():
            result.error(f"终检失败：产物缺失 {path}")
        elif path.stat().st_size == 0:
            result.error(f"终检失败：产物为空文件 {path}")

    if result.errors:
        return result

    try:
        events = read_json(paths["event_list"])
    except (json.JSONDecodeError, OSError) as exc:
        result.error(f"event_list.json 解析失败: {exc}")
        return result
    if not isinstance(events, list):
        result.error("event_list.json 顶层必须是数组")
        return result

    report_text = paths["report"].read_text(encoding="utf-8")
    for event in events:
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("event_id", "")).strip()
        title = str(event.get("title", "")).strip()
        if event_id and event_id not in report_text and title and title not in report_text:
            result.error(f"日报未引用事件 {event_id or title[:30]}（event_id 与标题均未出现）")

    # 复核 B2 硬规则，防止 B3 阶段被改写
    recheck = validate_events(events, contract, domain, day)
    for message in recheck.errors:
        result.error(f"终检复核未通过：{message}")
    for message in recheck.warnings:
        result.warn(message)
    return result


STEP_VALIDATORS = {
    "B1": lambda paths, payload, contract, domain, day: validate_candidates(payload, contract, domain, day),
    "B2": lambda paths, payload, contract, domain, day: validate_events(payload, contract, domain, day),
    "B3": lambda paths, payload, contract, domain, day: validate_report(paths, contract, domain, day),
    "B4": lambda paths, payload, contract, domain, day: validate_final(paths, contract, domain, day),
}


def step_artifact_hint(step: str) -> str:
    return {
        "B1": "raw_candidates.json",
        "B2": "event_list.json",
        "B3": "daily/<date>.md + summary.json",
        "B4": "（无新产物，对 B1-B3 全部产物做终检）",
    }.get(step, "")


def archive_artifacts(paths: dict[str, Path], day: str) -> list[str]:
    """把当日 latest 产物归档到 daily/<date>/ 下，返回归档文件列表。"""
    archive_dir: Path = paths["archive_dir"]
    archive_dir.mkdir(parents=True, exist_ok=True)
    archived: list[str] = []
    for key in ("state", "candidates", "event_list", "summary"):
        source: Path = paths[key]
        if source.exists():
            target = archive_dir / source.name
            target.write_bytes(source.read_bytes())
            archived.append(str(target))
    return archived
