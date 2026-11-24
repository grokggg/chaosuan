"""早鸟工作台工具：briefing 流程引导与工作台聚合。

封装 early_bird/guide.py 与 early_bird/aggregate.py 两个脚本，
使智能体可以在对话中直接驱动六领域追踪流程与每日聚合渲染，
校验规则与 CLI 完全一致（共用 early_bird/common.py）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Any

from langchain.tools import tool

from src.utils.workspace import PROJECT_ROOT

EARLY_BIRD_DIR = PROJECT_ROOT / "early_bird"
GUIDE_SCRIPT = EARLY_BIRD_DIR / "guide.py"
AGGREGATE_SCRIPT = EARLY_BIRD_DIR / "aggregate.py"
SCRIPT_TIMEOUT_SECONDS = 180

MAX_OUTPUT_CHARS = 24000


def _run_script(script: Path, argv: list[str]) -> str:
    """运行早鸟脚本并返回其 JSON 输出（失败时返回错误说明）。"""
    if not script.exists():
        return json.dumps(
            {"status": "error", "message": f"脚本不存在: {script}"},
            ensure_ascii=False,
        )
    command = [sys.executable, str(script), *argv]
    try:
        completed = subprocess.run(
            command,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=SCRIPT_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return json.dumps(
            {
                "status": "error",
                "message": f"脚本执行超时（>{SCRIPT_TIMEOUT_SECONDS}s）",
                "command": " ".join(command),
            },
            ensure_ascii=False,
        )
    except OSError as exc:
        return json.dumps(
            {"status": "error", "message": f"脚本启动失败: {exc}", "command": " ".join(command)},
            ensure_ascii=False,
        )

    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    if not stdout:
        return json.dumps(
            {
                "status": "error" if completed.returncode != 0 else "ok",
                "message": "脚本无输出",
                "returncode": completed.returncode,
                "stderr": stderr[-2000:],
            },
            ensure_ascii=False,
        )
    if len(stdout) > MAX_OUTPUT_CHARS:
        stdout = stdout[:MAX_OUTPUT_CHARS] + "\n...(输出已截断)"
    if completed.returncode != 0 and stderr:
        try:
            payload = json.loads(stdout)
            if isinstance(payload, dict):
                payload.setdefault("stderr", stderr[-1500:])
                payload["returncode"] = completed.returncode
                return json.dumps(payload, ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            pass
        return f"{stdout}\n\n[stderr]\n{stderr[-1500:]}"
    return stdout


def _split_args(value: str) -> list[str]:
    import shlex

    try:
        return shlex.split(value or "")
    except ValueError:
        return [part for part in (value or "").split() if part]


@tool(
    "early_bird_briefing",
    description=(
        "早鸟雷达 briefing 流程驱动工具。用于初始化、查询、提交并校验某个领域某日的追踪流程"
        "（B1 候选检索 → B2 筛选与 high 信源校验 → B3 日报撰写 → B4 终检归档 → DONE）。"
        "action=init 初始化并返回领域契约与首步指引；action=next 查看下一步指引；"
        "action=submit 提交某步产物并执行校验（校验失败会返回具体错误项，状态不前进）；"
        "action=status 查看流程状态；action=list 列出六领域 token、时刻表与今日状态。"
        "setup_token 传领域 token（如 setup_0da2e5ce）、英文 slug（tech/med/fin/consumer/biz/talent）"
        "或中文名（科技/医学/金融/消费/商业/人才）。"
    ),
)
def early_bird_briefing(
    action: Annotated[
        str,
        "操作类型，取值：init、next、submit、status、list。",
    ],
    setup_token: Annotated[
        str,
        "领域标识：setup token、英文 slug 或中文领域名。action=list 时可留空。",
    ] = "",
    step: Annotated[
        str,
        "action=submit 时必填，取值 B1、B2、B3、B4。",
    ] = "",
    date: Annotated[
        str,
        "运行日 YYYY-MM-DD，留空表示今天。",
    ] = "",
    file_path: Annotated[
        str,
        "action=submit 且步骤为 B1/B2 时可选：产物 JSON 文件路径，留空则读取标准产物位置。",
    ] = "",
    force: Annotated[
        bool,
        "action=init 时可选：流程已处于终态时是否强制重跑。",
    ] = False,
) -> str:
    """驱动早鸟雷达 briefing 流程并返回脚本的 JSON 结果。"""
    normalized_action = str(action or "").strip().lower()
    if normalized_action not in {"init", "next", "submit", "status", "list"}:
        return json.dumps(
            {
                "status": "error",
                "message": f"action 非法: {action!r}，应为 init/next/submit/status/list",
            },
            ensure_ascii=False,
        )

    argv: list[str] = [normalized_action]
    if normalized_action != "list":
        token = str(setup_token or "").strip()
        if not token:
            return json.dumps(
                {"status": "error", "message": "setup_token 不能为空（action=list 除外）"},
                ensure_ascii=False,
            )
        argv.extend(["--setup-token", token])
    if date and str(date).strip():
        argv.extend(["--date", str(date).strip()])
    if normalized_action == "init":
        argv.extend(["--flow", "briefing"])
        if force:
            argv.append("--force")
    if normalized_action == "submit":
        normalized_step = str(step or "").strip().upper()
        if normalized_step not in {"B1", "B2", "B3", "B4"}:
            return json.dumps(
                {"status": "error", "message": f"step 非法: {step!r}，应为 B1/B2/B3/B4"},
                ensure_ascii=False,
            )
        argv.extend(["--step", normalized_step])
        if file_path and str(file_path).strip():
            argv.extend(["--file", str(file_path).strip()])
    return _run_script(GUIDE_SCRIPT, argv)


@tool(
    "early_bird_aggregate",
    description=(
        "早鸟工作台聚合工具。action=snapshot 读取六领域最新日报"
        "（daily/YYYY-MM-DD.md + event_list.json + summary.json），渲染工作台 index.html "
        "并保存当日快照 daily/YYYY-MM-DD.html；渲染失败时保留上一次 index.html 并把错误写入 aggregate.log。"
        "action=status 查看各领域采集状态与工作台产物；action=domains 列出六领域目录与最新日报日期。"
    ),
)
def early_bird_aggregate(
    action: Annotated[
        str,
        "操作类型，取值：snapshot、status、domains。",
    ] = "snapshot",
    date: Annotated[
        str,
        "数据日期 YYYY-MM-DD，留空表示今天。",
    ] = "",
) -> str:
    """执行早鸟工作台聚合并返回脚本的 JSON 结果。"""
    normalized_action = str(action or "snapshot").strip().lower()
    if normalized_action not in {"snapshot", "status", "domains"}:
        return json.dumps(
            {
                "status": "error",
                "message": f"action 非法: {action!r}，应为 snapshot/status/domains",
            },
            ensure_ascii=False,
        )
    argv: list[str] = [normalized_action]
    if normalized_action != "domains" and date and str(date).strip():
        argv.extend(["--date", str(date).strip()])
    return _run_script(AGGREGATE_SCRIPT, argv)


__all__ = ["early_bird_aggregate", "early_bird_briefing"]
