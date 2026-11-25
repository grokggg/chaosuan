"""早鸟工作台自动化接口：状态查询、手动触发、立即推送、测试邮件、收件箱。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.api.response import api_error
from src.early_bird_scheduler import (
    AGGREGATE_CHAIN,
    request_manual_run,
    run_push,
    scheduler_status,
)
from src.logger import get_logger
from src.utils.workspace import PROJECT_ROOT

logger = get_logger(__name__)

router = APIRouter(prefix="/user/agent/early-bird", tags=["early-bird"])

EARLY_BIRD_DIR = PROJECT_ROOT / "early_bird"
INBOX_DIR = EARLY_BIRD_DIR / "工作台" / "inbox"

VALID_CHAINS = {"tech", "med", "fin", "consumer", "biz", "talent", AGGREGATE_CHAIN}
VALID_MODES = {"concise", "full", "notice"}


class ManualRunRequest(BaseModel):
    chain: str = Field(description="领域 slug（tech/med/fin/consumer/biz/talent）或 aggregate")
    date: str | None = Field(default=None, description="数据日期 YYYY-MM-DD，默认今天")
    push: bool = Field(default=False, description="完成后是否立即推送邮件（aggregate 链固定推送）")


class PushRequest(BaseModel):
    date: str | None = Field(default=None, description="数据日期 YYYY-MM-DD，默认今天")
    mode: str | None = Field(default=None, description="concise/full/notice，默认取凭据文件配置")
    force: bool = Field(default=False, description="忽略空结果策略强制发送")


def _ok(data: Any) -> dict[str, Any]:
    return {"code": 0, "msg": "success", "data": data}


@router.get("/status")
async def get_scheduler_status() -> dict[str, Any]:
    try:
        return _ok(scheduler_status())
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to read early-bird scheduler status")
        return api_error(code=500, msg=f"failed to read scheduler status: {exc}")


@router.post("/run")
async def post_manual_run(request: ManualRunRequest) -> dict[str, Any]:
    chain = (request.chain or "").strip().lower()
    if chain not in VALID_CHAINS:
        return api_error(code=400, msg=f"chain 非法: {request.chain!r}，可选 {sorted(VALID_CHAINS)}")
    date = (request.date or "").strip() or None
    if date:
        import re

        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            return api_error(code=400, msg=f"date 格式非法，应为 YYYY-MM-DD: {date}")
    record = request_manual_run(chain, date, push=request.push)
    return _ok(record)


@router.post("/push")
async def post_push(request: PushRequest) -> dict[str, Any]:
    mode = (request.mode or "").strip().lower() or None
    if mode and mode not in VALID_MODES:
        return api_error(code=400, msg=f"mode 非法: {request.mode!r}，可选 {sorted(VALID_MODES)}")
    day = (request.date or "").strip() or None
    try:
        result = await run_push(day or _today(), mode, force=request.force)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to push early-bird digest")
        return api_error(code=500, msg=f"push failed: {exc}")
    return _ok(result)


@router.post("/push/test")
async def post_push_test() -> dict[str, Any]:
    def _do() -> dict[str, Any]:
        import sys

        sys.path.insert(0, str(EARLY_BIRD_DIR))
        import notify  # noqa: PLC0415

        return notify.send_test_email()

    try:
        result = await asyncio.to_thread(_do)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to send early-bird test email")
        return api_error(code=500, msg=f"test email failed: {exc}")
    return _ok(result)


@router.get("/push/retry")
async def get_push_retry(force: bool = False) -> dict[str, Any]:
    def _do() -> dict[str, Any]:
        import sys

        sys.path.insert(0, str(EARLY_BIRD_DIR))
        import notify  # noqa: PLC0415

        return notify.retry_queue(force=force)

    try:
        result = await asyncio.to_thread(_do)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to retry early-bird push queue")
        return api_error(code=500, msg=f"retry failed: {exc}")
    return _ok(result)


@router.get("/inbox")
async def get_inbox(date: str | None = None) -> dict[str, Any]:
    day = (date or "").strip()
    path: Path = INBOX_DIR / (f"{day}.json" if day else "latest.json")
    if not path.exists():
        if day:
            return api_error(code=404, msg=f"收件箱无 {day} 的记录: {path}")
        return _ok({"entries": [], "message": "收件箱暂无记录"})
    try:
        import json

        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return api_error(code=500, msg=f"failed to read inbox: {exc}")
    return _ok(payload)


def _today() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d")


__all__ = ["router"]
