#!/usr/bin/env python3
"""早鸟雷达 briefing 引导脚本（等价于原 Coze 版 guide.py）。

用法：
  python early_bird/guide.py init   --flow briefing --setup-token setup_0da2e5ce [--date YYYY-MM-DD]
  python early_bird/guide.py next   --setup-token setup_0da2e5ce [--date YYYY-MM-DD]
  python early_bird/guide.py submit --setup-token setup_0da2e5ce --step B1 [--date YYYY-MM-DD]
  python early_bird/guide.py status --setup-token setup_0da2e5ce [--date YYYY-MM-DD]
  python early_bird/guide.py list

流程：init → B1（候选检索）→ B2（筛选与 high 信源校验）→ B3（日报撰写）→ B4（终检归档）→ DONE
任一步校验未通过时状态不前进，脚本输出具体失败项与修正提示；修正产物后重新 submit 同一步即可。
若 setup contract 标记 empty_silent=true 且 B2/B3 确认为空结果，状态置为 EMPTY_SILENT 并静默结束。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402

RULE_BAR = "=" * 78


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _fail(message: str, **extra: Any) -> int:
    _emit({"status": "error", "message": message, **extra})
    return 2


def _load(token: str, day: str | None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Path], str] | int:
    contract = common.load_contract()
    domain = common.find_domain(contract, token)
    if not domain:
        return _fail(
            f"未找到 setup-token 对应的领域: {token}",
            available=[
                {"setup_token": d.get("setup_token"), "domain": d.get("domain"), "name_cn": d.get("name_cn")}
                for d in contract.get("domains", [])
            ],
        )
    resolved_day = day or common.today_str()
    if not common.parse_date(resolved_day):
        return _fail(f"--date 格式非法，应为 YYYY-MM-DD: {resolved_day}")
    paths = common.artifact_paths(domain, resolved_day)
    return contract, domain, paths, resolved_day


def _domain_brief(contract: dict[str, Any], domain: dict[str, Any]) -> dict[str, Any]:
    rules = common.global_rules(contract)
    return {
        "name_cn": domain.get("name_cn"),
        "domain": domain.get("domain"),
        "domain_slug": domain.get("domain_slug"),
        "setup_token": domain.get("setup_token"),
        "schedule_time": domain.get("schedule_time"),
        "output_dir": str(common.domain_dir(domain)),
        "authority_requirement": domain.get("authority_requirement") or rules.get("authority_requirement"),
        "min_independent_domains_per_event": common.min_domains(contract, domain),
        "source_rule": rules.get("source_rule"),
        "uncertainty_policy": rules.get("uncertainty_policy"),
        "no_fabrication": rules.get("no_fabrication"),
        "empty_silent": bool(domain.get("empty_silent", rules.get("empty_silent_default", True))),
        "definition": domain.get("definition"),
        "include": domain.get("include", []),
        "exclude": domain.get("exclude", []),
        "focus": domain.get("focus", []),
        "signal_types": domain.get("signal_types", []),
        "sources": domain.get("sources", {}),
        "search_seeds": domain.get("search_seeds", []),
        "single_source_policy": domain.get("single_source_policy"),
    }


def _step_instruction(
    contract: dict[str, Any],
    domain: dict[str, Any],
    paths: dict[str, Path],
    day: str,
    step: str,
) -> dict[str, Any]:
    flow = contract.get("briefing_flow", {})
    definitions = flow.get("step_definitions", {})
    spec = definitions.get(step, {})
    token = domain.get("setup_token", "")
    instruction: dict[str, Any] = {
        "step": step,
        "title": spec.get("title", ""),
        "goal": spec.get("goal", ""),
        "artifacts": [],
        "schema": spec.get("schema") or spec.get("summary_schema"),
        "markdown_requirements": spec.get("markdown_requirements"),
        "validation": spec.get("validation"),
        "min_items": spec.get("min_items"),
        "on_empty": spec.get("on_empty"),
        "submit_command": f'python early_bird/guide.py submit --setup-token "{token}" --step {step} --date {day}',
    }
    if step == "B1":
        instruction["artifacts"] = [str(paths["candidates"])]
        instruction["howto"] = [
            "使用 web_search 工具，围绕本领域 search_seeds 执行 6-10 轮检索，freshness 建议 oneDay 或 oneWeek。",
            "只收集 24-48 小时内的候选，不做质量筛选；每条必须记录真实 url、主域名、发布机构、tier、发布日期。",
            "tier 判定：官方来源（官网/官方账号/监管/交易所/上市公司公告）= tier1；契约 tier2 列表内主流媒体 = tier2；无法确认 = unknown。",
            "禁止编造链接或日期；无法确认发布日期的候选直接丢弃。",
            f"把候选数组写入 {paths['candidates']}（UTF-8 JSON 数组），然后执行 submit。",
        ]
    elif step == "B2":
        instruction["artifacts"] = [str(paths["event_list"])]
        instruction["howto"] = [
            "读取 B1 候选，按 include 保留、按 exclude 剔除，把同一事件的多个报道聚成一个事件组。",
            f"每个事件组必须满足：独立主域名 ≥ {common.min_domains(contract, domain)}，且 Tier-1 官方源 ×1 或 Tier-2 主流媒体 ×2。",
            "同一媒体集团下的子站算同一域名；来源或时间不确定的事件一律不提交。",
            "confidence 只允许 high/medium；low 直接丢弃。",
            f"把合格事件数组写入 {paths['event_list']}，然后执行 submit。",
            "若过滤后无合格事件，写入空数组 [] 并 submit，脚本会引导进入空结果分支。",
        ]
    elif step == "B3":
        instruction["artifacts"] = [str(paths["report"]), str(paths["summary"])]
        instruction["howto"] = [
            f"基于 {paths['event_list']} 撰写日报，写入 {paths['report']}（Markdown）。",
            f"首行标题：# {domain.get('name_cn', '')} · {day}",
            "包含「今日概览」「逐事件详情（事实摘要/早期信号价值/影响面/编号来源清单）」「信源校验」三部分。",
            "空结果日只写一行：今日无满足 high 信源要求的合格早期信号。不得填充凑数内容。",
            f"同时写入结构化摘要 {paths['summary']}，字段见 schema。",
        ]
    else:
        instruction["artifacts"] = []
        instruction["howto"] = [
            "无需产出新文件；脚本会复核 B1-B3 全部产物的一致性、完整性与 high 信源硬规则。",
            "通过后状态置为 DONE，当日产物自动归档到 daily/<date>/，聚合器即可读取。",
        ]
    return instruction


def _state_view(state: dict[str, Any], paths: dict[str, Path]) -> dict[str, Any]:
    steps = state.get("steps", {})
    return {
        "name_cn": state.get("name_cn"),
        "domain_slug": state.get("domain_slug"),
        "setup_token": state.get("setup_token"),
        "date": state.get("date"),
        "status": state.get("status"),
        "event_count": state.get("event_count"),
        "empty_silent": state.get("empty_silent"),
        "steps": {
            step: {
                "status": steps.get(step, {}).get("status", "pending"),
                "attempts": steps.get(step, {}).get("attempts", 0),
                "finished_at": steps.get(step, {}).get("finished_at"),
                "last_errors": steps.get(step, {}).get("errors", [])[:8],
            }
            for step in common.FLOW_STEPS
        },
        "artifacts": {key: str(value) for key, value in paths.items() if key != "archive_dir"},
        "updated_at": state.get("updated_at"),
    }


def cmd_init(args: argparse.Namespace) -> int:
    loaded = _load(args.setup_token, args.date)
    if isinstance(loaded, int):
        return loaded
    contract, domain, paths, day = loaded

    existing = common.load_state_for_day(paths, day)
    if existing and existing.get("status") in common.TERMINAL_STATUSES and not args.force:
        _emit(
            {
                "status": "already_finished",
                "message": f"{domain.get('name_cn')} {day} 的 briefing 已处于终态 {existing.get('status')}，"
                "如需重跑请加 --force",
                "state": _state_view(existing, paths),
            }
        )
        return 0

    state = common.blank_state(domain, day, args.flow)
    if existing:
        state["history"] = list(existing.get("history", [])) + [
            {"event": "reinit", "from_status": existing.get("status"), "at": common.now_iso()}
        ]
    common.save_state(paths, state)
    paths["base"].mkdir(parents=True, exist_ok=True)
    (paths["base"] / "daily").mkdir(parents=True, exist_ok=True)

    step = common.current_step(state) or "B1"
    _emit(
        {
            "status": "ok",
            "flow": args.flow,
            "message": f"已初始化 {domain.get('name_cn')} {day} 的 {args.flow} 流程，当前待办步骤 {step}",
            "domain": _domain_brief(contract, domain),
            "state": _state_view(state, paths),
            "next_step": _step_instruction(contract, domain, paths, day, step),
            "flow_overview": {
                "steps": common.FLOW_STEPS,
                "status_machine": contract.get("briefing_flow", {}).get("status_machine"),
                "terminal_status": contract.get("briefing_flow", {}).get("terminal_status"),
                "retry_policy": contract.get("briefing_flow", {}).get("retry_policy"),
            },
            "reply_policy": {
                "empty_silent": bool(domain.get("empty_silent", True)),
                "rule": "完成后只重复脚本要求的信息（状态、事件数、产物路径），不要把完整日报正文直接发给用户。",
            },
        }
    )
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    loaded = _load(args.setup_token, args.date)
    if isinstance(loaded, int):
        return loaded
    contract, domain, paths, day = loaded
    state = common.load_state_for_day(paths, day)
    if not state:
        return _fail(
            f"尚未初始化，请先执行 init：python early_bird/guide.py init --flow briefing "
            f'--setup-token "{domain.get("setup_token")}" --date {day}'
        )
    step = common.current_step(state)
    if step is None:
        _emit(
            {
                "status": "finished",
                "message": f"{domain.get('name_cn')} {day} 已处于终态 {state.get('status')}",
                "state": _state_view(state, paths),
            }
        )
        return 0
    _emit(
        {
            "status": "ok",
            "message": f"下一步：{step}",
            "state": _state_view(state, paths),
            "next_step": _step_instruction(contract, domain, paths, day, step),
        }
    )
    return 0


def cmd_submit(args: argparse.Namespace) -> int:
    loaded = _load(args.setup_token, args.date)
    if isinstance(loaded, int):
        return loaded
    contract, domain, paths, day = loaded
    state = common.load_state_for_day(paths, day)
    if not state:
        return _fail("尚未初始化，请先执行 init")

    step = args.step
    expected = common.current_step(state)
    if expected is None:
        return _fail(
            f"流程已处于终态 {state.get('status')}，无法继续提交；如需重跑请执行 init --force",
            state=_state_view(state, paths),
        )
    if step != expected:
        return _fail(
            f"步骤顺序错误：当前应提交 {expected}，收到 {step}",
            state=_state_view(state, paths),
        )

    payload: Any = None
    if step in {"B1", "B2"}:
        artifact = paths["candidates"] if step == "B1" else paths["event_list"]
        if args.file:
            artifact = Path(args.file).expanduser()
            if not artifact.is_absolute():
                artifact = (common.PROJECT_ROOT / artifact).resolve()
        if not artifact.exists():
            return _fail(
                f"{step} 产物不存在: {artifact}",
                hint=common.step_artifact_hint(step),
                state=_state_view(state, paths),
            )
        try:
            payload = common.read_json(artifact)
        except (json.JSONDecodeError, OSError) as exc:
            return _fail(f"{step} 产物解析失败: {exc}", path=str(artifact))
        # 允许 --file 指向别处：同步到标准产物位置
        target = paths["candidates"] if step == "B1" else paths["event_list"]
        if artifact.resolve() != target.resolve():
            common.write_json(target, payload)

    validator = common.STEP_VALIDATORS[step]
    result = validator(paths, payload, contract, domain, day)

    step_state = state.setdefault("steps", {}).setdefault(step, {"status": "pending", "attempts": 0, "errors": []})
    step_state["attempts"] = int(step_state.get("attempts", 0)) + 1
    step_state["errors"] = result.errors[:20]

    if not result.ok:
        common.save_state(paths, state)
        _emit(
            {
                "status": "validation_failed",
                "step": step,
                "message": f"{step} 校验未通过，共 {len(result.errors)} 项错误；状态未前进，请按提示修正后重新提交同一步骤",
                "errors": result.errors,
                "warnings": result.warnings,
                "retry_command": f'python early_bird/guide.py submit --setup-token "{domain.get("setup_token")}" '
                f"--step {step} --date {day}",
                "state": _state_view(state, paths),
            }
        )
        return 1

    step_state["status"] = "passed"
    step_state["errors"] = []
    step_state["finished_at"] = common.now_iso()
    state.setdefault("history", []).append(
        {"event": f"{step}_passed", "attempts": step_state["attempts"], "at": common.now_iso()}
    )

    # 事件计数
    event_count: int | None = None
    if paths["event_list"].exists():
        try:
            events = common.read_json(paths["event_list"])
            event_count = len(events) if isinstance(events, list) else None
        except (json.JSONDecodeError, OSError):
            event_count = None
    if event_count is not None:
        state["event_count"] = event_count

    empty_result = event_count == 0
    empty_silent = bool(domain.get("empty_silent", True))
    if empty_result:
        state["empty"] = True
    next_step = common.next_step_after(state, step)

    new_status = common.STEP_TO_STATUS.get(step, state.get("status", "INIT"))
    if step == "B4":
        # 空结果且契约允许静默时，终态为 EMPTY_SILENT 而非 DONE
        new_status = "EMPTY_SILENT" if (empty_result and empty_silent) else "DONE"
        state["finished_at"] = common.now_iso()
    state["status"] = new_status
    common.save_state(paths, state)
    if step == "B4":
        # 状态落盘后再归档，保证 daily/<date>/state.json 记录的是终态
        state["archived"] = common.archive_artifacts(paths, day)
        common.save_state(paths, state)

    if step == "B2" and empty_result:
        _emit(
            {
                "status": "ok",
                "step": step,
                "step_status": "passed",
                "message": f"{step} 校验通过（空结果），状态更新为 {state['status']}",
                "warnings": result.warnings,
                "event_count": 0,
                "empty_result": True,
                "empty_silent": empty_silent,
                "required_followup": {
                    "note": "空结果日仍必须完成 B3/B4：产出 daily/<date>.md（一行无合格信号说明）与 "
                    "summary.json（empty=true, event_count=0），否则聚合器会判定该领域缺报。",
                    "final_status": "EMPTY_SILENT" if empty_silent else "DONE",
                    "reply_policy": "no_reply：终态为 EMPTY_SILENT 时不要向用户输出日报正文，也不要寒暄。",
                },
                "state": _state_view(state, paths),
                "next_step": _step_instruction(contract, domain, paths, day, next_step) if next_step else None,
            }
        )
        return 0

    payload_out: dict[str, Any] = {
        "status": "ok",
        "step": step,
        "step_status": "passed",
        "message": f"{step} 校验通过，状态更新为 {state['status']}",
        "warnings": result.warnings,
        "event_count": state.get("event_count"),
        "state": _state_view(state, paths),
    }
    if state["status"] == "DONE":
        payload_out["finished"] = True
        payload_out["artifacts"] = {
            "report": str(paths["report"]),
            "event_list": str(paths["event_list"]),
            "summary": str(paths["summary"]),
            "archived": state.get("archived", []),
        }
        payload_out["reply_policy"] = (
            "只重复脚本要求的信息：领域、日期、状态 DONE、事件数、产物路径。不要把完整日报正文发给用户。"
        )
    elif next_step:
        payload_out["next_step"] = _step_instruction(contract, domain, paths, day, next_step)
    _emit(payload_out)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    loaded = _load(args.setup_token, args.date)
    if isinstance(loaded, int):
        return loaded
    _contract, domain, paths, day = loaded
    state = common.load_state_for_day(paths, day)
    if not state:
        _emit(
            {
                "status": "not_initialized",
                "message": f"{domain.get('name_cn')} {day} 尚未初始化",
                "domain": domain.get("name_cn"),
                "artifacts": {key: str(value) for key, value in paths.items() if key != "archive_dir"},
            }
        )
        return 0
    _emit({"status": "ok", "state": _state_view(state, paths)})
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    contract = common.load_contract()
    rules = common.global_rules(contract)
    rows = []
    for domain in contract.get("domains", []):
        base = common.domain_dir(domain)
        state = common.load_state_for_day(common.artifact_paths(domain, common.today_str()), common.today_str())
        rows.append(
            {
                "name_cn": domain.get("name_cn"),
                "domain_slug": domain.get("domain_slug"),
                "setup_token": domain.get("setup_token"),
                "schedule_time": domain.get("schedule_time"),
                "output_dir": str(base),
                "today_status": (state or {}).get("status", "not_initialized"),
                "today_event_count": (state or {}).get("event_count"),
            }
        )
    _emit(
        {
            "status": "ok",
            "workspace": contract.get("workspace_name"),
            "contract_version": contract.get("contract_version"),
            "global_rules": rules,
            "domains": rows,
            "schedule": contract.get("schedule", []),
        }
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="guide.py",
        description="早鸟雷达 briefing 流程引导与校验脚本",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser, require_token: bool = True) -> None:
        p.add_argument(
            "--setup-token",
            required=require_token,
            help="领域 setup token，如 setup_0da2e5ce；也可传领域 slug 或中文名",
        )
        p.add_argument("--date", default=None, help="运行日 YYYY-MM-DD，默认今天")

    p_init = sub.add_parser("init", help="初始化某领域某日的 briefing 流程")
    add_common(p_init)
    p_init.add_argument("--flow", default="briefing", help="流程名，默认 briefing")
    p_init.add_argument("--force", action="store_true", help="已终态时强制重跑")
    p_init.set_defaults(func=cmd_init)

    p_next = sub.add_parser("next", help="查看下一步指引")
    add_common(p_next)
    p_next.set_defaults(func=cmd_next)

    p_submit = sub.add_parser("submit", help="提交并校验某一步产物")
    add_common(p_submit)
    p_submit.add_argument("--step", required=True, choices=list(common.FLOW_STEPS), help="步骤 B1/B2/B3/B4")
    p_submit.add_argument("--file", default=None, help="B1/B2 可选：产物 JSON 路径，默认读标准产物位置")
    p_submit.set_defaults(func=cmd_submit)

    p_status = sub.add_parser("status", help="查看某领域某日流程状态")
    add_common(p_status)
    p_status.set_defaults(func=cmd_status)

    p_list = sub.add_parser("list", help="列出全部领域、token、时刻表与今日状态")
    p_list.set_defaults(func=cmd_list)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except FileNotFoundError as exc:
        return _fail(str(exc))
    except Exception as exc:  # noqa: BLE001
        return _fail(f"脚本执行异常: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
