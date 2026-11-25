"""早鸟工作台常驻调度器。

随模板服务启动（server.py lifespan），按 tracking_contract_v2.json 的 schedule
错峰驱动六领域 briefing 与每日聚合，并在聚合后触发邮件推送。

设计要点：
  - 领域链在进程内直接驱动智能体（AGENTS.get + ainvoke），每次运行独立 thread_id，
    不污染用户会话；运行日志落 early_bird/工作台/runs/<date>/<chain>.log。
  - 聚合与推送分别走子进程 / 线程，避免阻塞事件循环。
  - 状态落 early_bird/scheduler_state.json，服务重启后可补跑（catch-up）。
  - 手动触发走 early_bird/scheduler_manual.json 文件队列，路由只写文件，解耦且重启安全。
  - 发送失败的邮件进入 notify 队列，调度器每个 tick 顺带重试。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.logger import get_logger
from src.utils.workspace import PROJECT_ROOT

logger = get_logger(__name__)

EARLY_BIRD_DIR = PROJECT_ROOT / "early_bird"
AGGREGATE_SCRIPT = EARLY_BIRD_DIR / "aggregate.py"
STATE_PATH = EARLY_BIRD_DIR / "scheduler_state.json"
MANUAL_QUEUE_PATH = EARLY_BIRD_DIR / "scheduler_manual.json"
SCHEDULER_LOG = EARLY_BIRD_DIR / "scheduler.log"
RUNS_DIR = EARLY_BIRD_DIR / "工作台" / "runs"

DEFAULT_TICK_SECONDS = 20
DOMAIN_JOB_TIMEOUT_SECONDS = 30 * 60
AGGREGATE_TIMEOUT_SECONDS = 5 * 60
MAX_JOB_ATTEMPTS_PER_DAY = 3
LOCK_PATH = EARLY_BIRD_DIR / "scheduler.lock"

AGGREGATE_CHAIN = "aggregate"

_SCHEDULER_LOCK_FD: int | None = None


def acquire_scheduler_lock() -> bool:
    """进程间单写者锁：同一时刻只允许一个调度循环运行。

    独立守护进程与模板服务内的调度循环竞争同一把锁；持有者崩溃时
    内核自动释放锁，另一方在下一个 tick 接管，实现无感故障切换。
    """
    global _SCHEDULER_LOCK_FD
    if _SCHEDULER_LOCK_FD is not None:
        return True
    import fcntl
    import os

    try:
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    try:
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode("utf-8"))
    except OSError:
        pass
    _SCHEDULER_LOCK_FD = fd
    return True


def scheduler_lock_held_by_us() -> bool:
    return _SCHEDULER_LOCK_FD is not None


# --------------------------------------------------------------------------- #
# 基础 IO
# --------------------------------------------------------------------------- #
def _read_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    import os

    os.replace(tmp, path)


def _log(message: str, level: str = "INFO") -> None:
    try:
        SCHEDULER_LOG.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with SCHEDULER_LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] [{level}] {message}\n")
    except OSError:
        pass
    getattr(logger, "info" if level == "INFO" else "warning")("early_bird_scheduler %s", message)


def _env_flag(name: str, default: bool) -> bool:
    import os

    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw not in {"false", "0", "no", "off"}


def _env_int(name: str, default: int) -> int:
    import os

    try:
        return int((os.getenv(name) or "").strip() or default)
    except ValueError:
        return default


# --------------------------------------------------------------------------- #
# 契约与状态
# --------------------------------------------------------------------------- #
def load_schedule() -> list[dict[str, Any]]:
    contract = _read_json(EARLY_BIRD_DIR / "tracking_contract_v2.json", {})
    schedule = contract.get("schedule") if isinstance(contract, dict) else None
    return schedule if isinstance(schedule, list) else []


def load_state() -> dict[str, Any]:
    return _read_json(STATE_PATH, {})


def save_state(state: dict[str, Any]) -> None:
    _write_json(STATE_PATH, state)


def day_state(state: dict[str, Any], day: str) -> dict[str, Any]:
    return state.setdefault(day, {})


def job_record(state: dict[str, Any], day: str, chain: str) -> dict[str, Any]:
    return day_state(state, day).setdefault(chain, {})


def load_manual_queue() -> list[dict[str, Any]]:
    data = _read_json(MANUAL_QUEUE_PATH, [])
    return data if isinstance(data, list) else []


def save_manual_queue(queue: list[dict[str, Any]]) -> None:
    _write_json(MANUAL_QUEUE_PATH, queue)


def request_manual_run(chain: str, date: str | None = None, push: bool = False) -> dict[str, Any]:
    queue = load_manual_queue()
    record = {
        "chain": chain,
        "date": date or datetime.now().strftime("%Y-%m-%d"),
        "push": bool(push),
        "requested_at": datetime.now().isoformat(),
        "status": "queued",
    }
    queue.append(record)
    save_manual_queue(queue)
    _log(f"manual run queued chain={chain} date={record['date']} push={push}")
    return record


def _recover_stale_manual_queue() -> None:
    """服务重启后把残留的 running 任务回置为 queued，避免任务永久卡死。"""
    queue = load_manual_queue()
    changed = False
    for item in queue:
        if item.get("status") == "running":
            item["status"] = "queued"
            item["requeued_at"] = datetime.now().isoformat()
            changed = True
    if changed:
        save_manual_queue(queue)
        _log("manual queue recovered: stale running items requeued")


# --------------------------------------------------------------------------- #
# 领域链运行（进程内驱动智能体）
# --------------------------------------------------------------------------- #
def _build_domain_prompt(domain: dict[str, Any], day: str) -> str:
    token = domain.get("setup_token")
    name = domain.get("name_cn")
    return (
        f"现在是早鸟雷达-{domain.get('domain')} 的定时 briefing 触发（数据日期 {day}）。\n"
        f"1. 执行 early_bird_briefing(action=\"init\", setup_token=\"{token}\", date=\"{day}\")，"
        f"读取{name}完整追踪契约与首步指引。\n"
        "2. 按 B1→B2→B3→B4 依次执行：每步先产出产物文件，再 submit 校验；"
        "校验未通过时按返回的错误项修正产物后重新提交同一步，直到状态为 DONE 或 EMPTY_SILENT。\n"
        f"3. 产物统一写入 early_bird/热点资讯追踪/{name}/。\n"
        "4. 若 empty_silent=true 且 B2/B3 确认为空结果，仍需完成 B3/B4 空结果日报，然后静默结束。\n"
        "5. 最后只回报：领域、日期、终态、事件数、产物路径。不要输出完整日报正文。"
    )


def _final_text(result: Any) -> str:
    messages = result.get("messages") if isinstance(result, dict) else None
    if not isinstance(messages, list) or not messages:
        return ""
    last = messages[-1]
    content = getattr(last, "content", None)
    if content is None and isinstance(last, dict):
        content = last.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    return str(content or "")


async def run_domain_chain(domain: dict[str, Any], day: str) -> dict[str, Any]:
    from src.agents.manager import AGENTS
    from src.agents.context import AgentRuntimeContext

    slug = str(domain.get("domain_slug") or "unknown")
    started = time.monotonic()
    run_dir = RUNS_DIR / day
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / f"{slug}.log"

    prompt = _build_domain_prompt(domain, day)
    config = {"configurable": {"thread_id": f"scheduler:{slug}:{day}"}}
    context = AgentRuntimeContext(user_id="early-bird-scheduler", conversation_id=f"sched-{slug}-{day}")

    _log(f"domain run start chain={slug} date={day}")
    try:
        agent = await AGENTS.get()
        result = await asyncio.wait_for(
            agent.ainvoke(
                {"messages": [{"role": "user", "content": prompt}]},
                config=config,
                context=context,
            ),
            timeout=DOMAIN_JOB_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - started
        _log(f"domain run timeout chain={slug} date={day} elapsed={elapsed:.0f}s", "WARN")
        log_path.write_text(f"[timeout] {elapsed:.0f}s\n", encoding="utf-8")
        return {"status": "timeout", "chain": slug, "date": day, "elapsed": elapsed}
    except Exception as exc:  # noqa: BLE001
        elapsed = time.monotonic() - started
        _log(f"domain run error chain={slug} date={day} error={type(exc).__name__}: {exc}", "WARN")
        log_path.write_text(f"[error] {type(exc).__name__}: {exc}\n", encoding="utf-8")
        return {"status": "error", "chain": slug, "date": day, "error": str(exc)}

    if isinstance(result, dict) and result.get("__interrupt__"):
        _log(f"domain run interrupted chain={slug} date={day}（出现人工审批中断，标记失败）", "WARN")
        log_path.write_text("[interrupted] pending approval\n", encoding="utf-8")
        return {"status": "interrupted", "chain": slug, "date": day}

    text = _final_text(result)
    elapsed = time.monotonic() - started
    log_path.write_text(text or "(empty reply)", encoding="utf-8")
    _log(f"domain run done chain={slug} date={day} elapsed={elapsed:.0f}s reply_chars={len(text)}")
    return {"status": "done", "chain": slug, "date": day, "elapsed": round(elapsed, 1), "reply": text[:800]}


# --------------------------------------------------------------------------- #
# 聚合与推送
# --------------------------------------------------------------------------- #
async def run_aggregate(day: str) -> dict[str, Any]:
    started = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(AGGREGATE_SCRIPT),
            "snapshot",
            "--date",
            day,
            cwd=str(PROJECT_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=AGGREGATE_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        _log(f"aggregate timeout date={day}", "WARN")
        return {"status": "timeout", "date": day}
    except OSError as exc:
        _log(f"aggregate spawn error date={day} error={exc}", "WARN")
        return {"status": "error", "date": day, "error": str(exc)}

    out = (stdout or b"").decode("utf-8", "replace").strip()
    elapsed = time.monotonic() - started
    try:
        payload = json.loads(out)
    except json.JSONDecodeError:
        payload = {"raw": out[:500], "stderr": (stderr or b"").decode("utf-8", "replace")[:500]}
    status = "done" if proc.returncode == 0 else "error"
    _log(f"aggregate {status} date={day} elapsed={elapsed:.0f}s", "INFO" if status == "done" else "WARN")
    return {"status": status, "date": day, "elapsed": round(elapsed, 1), "detail": payload}


async def run_push(day: str, mode: str | None = None, force: bool = False) -> dict[str, Any]:
    def _do() -> dict[str, Any]:
        sys.path.insert(0, str(EARLY_BIRD_DIR))
        import notify  # noqa: PLC0415

        return notify.push_digest(day, mode, force=force)

    try:
        result = await asyncio.to_thread(_do)
    except Exception as exc:  # noqa: BLE001
        _log(f"push error date={day} error={type(exc).__name__}: {exc}", "WARN")
        return {"status": "error", "date": day, "error": str(exc)}
    _log(f"push {result.get('status')} date={day} subject={result.get('subject')}")
    return result


async def run_retry_queue() -> None:
    def _do() -> dict[str, Any]:
        sys.path.insert(0, str(EARLY_BIRD_DIR))
        import notify  # noqa: PLC0415

        return notify.retry_queue()

    try:
        result = await asyncio.to_thread(_do)
        sent = [r for r in result.get("results", []) if r.get("status") == "sent"]
        if sent:
            _log(f"retry queue sent {len(sent)} pending email(s)")
    except Exception as exc:  # noqa: BLE001
        _log(f"retry queue error: {type(exc).__name__}: {exc}", "WARN")


# --------------------------------------------------------------------------- #
# 单条链调度
# --------------------------------------------------------------------------- #
async def dispatch_chain(chain: str, day: str, push: bool = False) -> dict[str, Any]:
    if chain == AGGREGATE_CHAIN:
        aggregate_result = await run_aggregate(day)
        push_result = await run_push(day) if push else None
        return {"chain": chain, "aggregate": aggregate_result, "push": push_result}

    contract = _read_json(EARLY_BIRD_DIR / "tracking_contract_v2.json", {})
    domains = contract.get("domains") if isinstance(contract, dict) else None
    domain = None
    for item in domains or []:
        if str(item.get("domain_slug")) == chain or str(item.get("setup_token")) == chain:
            domain = item
            break
    if domain is None:
        return {"chain": chain, "status": "unknown_chain"}
    return await run_domain_chain(domain, day)


# --------------------------------------------------------------------------- #
# 主循环
# --------------------------------------------------------------------------- #
def _parse_hhmm(value: str) -> tuple[int, int] | None:
    try:
        hour, minute = str(value).split(":")
        return int(hour), int(minute)
    except (ValueError, AttributeError):
        return None


async def scheduler_loop() -> None:
    tick = max(5, _env_int("EARLY_BIRD_SCHEDULER_TICK_SECONDS", DEFAULT_TICK_SECONDS))
    catchup = _env_flag("EARLY_BIRD_CATCHUP", True)
    _recover_stale_manual_queue()
    _log(f"scheduler loop started tick={tick}s catchup={catchup}")

    while True:
        try:
            await asyncio.sleep(tick)
            if not scheduler_lock_held_by_us():
                if not acquire_scheduler_lock():
                    # 另一个调度实例（守护进程或模板服务）持有锁，本实例待命
                    continue
                _log(f"scheduler lock acquired pid={os.getpid()}")
            if not _env_flag("EARLY_BIRD_SCHEDULER_ENABLED", True):
                continue

            now = datetime.now()
            day = now.strftime("%Y-%m-%d")
            state = load_state()

            # 1) 手动队列优先（仅当存在待处理项时才跳过定时表）
            manual = load_manual_queue()
            pending = [item for item in manual if item.get("status") == "queued"]
            if pending:
                item = pending[0]
                item["status"] = "running"
                save_manual_queue(manual)
                chain = str(item.get("chain") or "")
                target_day = str(item.get("date") or day)
                result = await dispatch_chain(chain, target_day, push=bool(item.get("push")))
                failed = result.get("status") in {"error", "timeout", "interrupted", "unknown_chain"}
                item["status"] = "failed" if failed else "done"
                item["finished_at"] = datetime.now().isoformat()
                item["result"] = {k: v for k, v in result.items() if k != "reply"}
                save_manual_queue(manual)
                push_result = result.get("push")
                if isinstance(push_result, dict):
                    day_state(state, target_day)["push"] = {
                        "status": push_result.get("status"),
                        "subject": push_result.get("subject"),
                        "at": datetime.now().isoformat(),
                    }
                record = job_record(state, target_day, f"manual:{chain}")
                record.update(
                    {
                        "status": "failed" if failed else "done",
                        "finished_at": item["finished_at"],
                        "detail": {k: v for k, v in result.items() if k not in {"reply", "detail"}},
                    }
                )
                save_state(state)
                _log(f"manual run {'failed' if failed else 'done'} chain={chain} date={target_day}")
                continue

            # 2) 定时表
            schedule = load_schedule()
            for entry in schedule:
                chain = str(entry.get("chain") or "")
                hhmm = _parse_hhmm(str(entry.get("time") or ""))
                if not chain or not hhmm:
                    continue
                slug = _chain_slug(schedule, chain)
                due = now.replace(hour=hhmm[0], minute=hhmm[1], second=0, microsecond=0)
                if now < due:
                    continue
                record = job_record(state, day, slug)
                if record.get("status") in {"running", "done"}:
                    continue
                attempts = int(record.get("attempts") or 0)
                if attempts >= MAX_JOB_ATTEMPTS_PER_DAY:
                    if record.get("status") != "gave_up":
                        record["status"] = "gave_up"
                        save_state(state)
                        _log(f"chain {slug} gave up after {attempts} attempts on {day}", "WARN")
                    continue
                if not catchup and now - due > timedelta(minutes=30):
                    record["status"] = "skipped_late"
                    save_state(state)
                    continue

                record["status"] = "running"
                record["attempts"] = attempts + 1
                record["started_at"] = datetime.now().isoformat()
                save_state(state)

                if slug == AGGREGATE_CHAIN:
                    # 聚合链固定带推送：渲染工作台后发送当日摘要邮件
                    result = await dispatch_chain(AGGREGATE_CHAIN, day, push=True)
                    push_result = result.get("push")
                    if isinstance(push_result, dict):
                        day_state(state, day)["push"] = {
                            "status": push_result.get("status"),
                            "subject": push_result.get("subject"),
                            "at": datetime.now().isoformat(),
                        }
                        save_state(state)
                else:
                    result = await dispatch_chain(slug, day)

                record["status"] = "done" if result.get("status") not in {"error", "timeout", "interrupted"} else result.get("status")
                record["finished_at"] = datetime.now().isoformat()
                record["detail"] = {k: v for k, v in result.items() if k not in {"reply", "detail"}}
                save_state(state)

            # 3) 每日推送兜底：聚合已完成但推送缺失/失败时补推一次
            aggregate_record = job_record(state, day, AGGREGATE_CHAIN)
            push_record = day_state(state, day).get("push")
            if (
                aggregate_record.get("status") == "done"
                and not (isinstance(push_record, dict) and push_record.get("status") in {"sent", "queued", "skipped"})
            ):
                push_result = await run_push(day)
                day_state(state, day)["push"] = {
                    "status": push_result.get("status"),
                    "subject": push_result.get("subject"),
                    "at": datetime.now().isoformat(),
                }
                save_state(state)
                _log(f"daily push backfill status={push_result.get('status')} date={day}")

            # 4) 邮件失败队列重试
            await run_retry_queue()
        except asyncio.CancelledError:
            _log("scheduler loop cancelled")
            raise
        except Exception as exc:  # noqa: BLE001
            _log(f"scheduler tick error: {type(exc).__name__}: {exc}", "WARN")
            await asyncio.sleep(tick)


def _chain_slug(schedule: list[dict[str, Any]], chain: str) -> str:
    """把时刻表里的中文链条名映射为 domain_slug 或 aggregate。"""
    if chain == "聚合":
        return AGGREGATE_CHAIN
    mapping = {"科技": "tech", "医学": "med", "金融": "fin", "消费": "consumer", "商业": "biz", "人才": "talent"}
    return mapping.get(chain, chain)


def scheduler_status() -> dict[str, Any]:
    import os

    state = load_state()
    day = datetime.now().strftime("%Y-%m-%d")
    schedule = load_schedule()
    sys.path.insert(0, str(EARLY_BIRD_DIR))
    import notify  # noqa: PLC0415

    return {
        "enabled": _env_flag("EARLY_BIRD_SCHEDULER_ENABLED", True),
        "catchup": _env_flag("EARLY_BIRD_CATCHUP", True),
        "tick_seconds": max(5, _env_int("EARLY_BIRD_SCHEDULER_TICK_SECONDS", DEFAULT_TICK_SECONDS)),
        "today": day,
        "schedule": schedule,
        "today_jobs": state.get(day, {}),
        "manual_queue": load_manual_queue()[-10:],
        "push": notify.config_status(),
        "scheduler_log": str(SCHEDULER_LOG),
        "runs_dir": str(RUNS_DIR),
        "env_scheduler_enabled": os.getenv("EARLY_BIRD_SCHEDULER_ENABLED", "(unset)"),
    }


__all__ = [
    "request_manual_run",
    "run_aggregate",
    "run_push",
    "scheduler_loop",
    "scheduler_status",
]
