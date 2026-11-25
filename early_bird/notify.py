#!/usr/bin/env python3
"""早鸟工作台推送模块：摘要构建 + QQ 邮箱 SMTP 发送 + 失败重试队列 + 站内收件箱。

凭据来源（优先级从高到低）：
  1. 进程环境变量；
  2. config/credentials.env（600 权限，不入库）。

行为约定：
  - 发送失败不丢消息：写入 push_queue.json，按间隔重试，超过上限后保留并标记 exhausted；
  - 无论邮件是否发出，摘要都会写入站内收件箱（early_bird/工作台/inbox/），保证可查；
  - 授权码等敏感值只从环境读取，绝不写入日志、队列或收件箱。

CLI：
  python early_bird/notify.py digest [--date YYYY-MM-DD] [--send] [--mode concise|full|notice]
  python early_bird/notify.py retry
  python early_bird/notify.py test
  python early_bird/notify.py status
"""

from __future__ import annotations

import argparse
import html
import json
import os
import smtplib
import ssl
import sys
import uuid
from datetime import datetime, timedelta
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aggregate  # noqa: E402
import common  # noqa: E402

CREDENTIALS_PATH = common.PROJECT_ROOT / "config" / "credentials.env"
QUEUE_PATH = common.resolve("early_bird/push_queue.json")
INBOX_DIR = common.resolve("early_bird/工作台/inbox")

PUSH_MODES = ("concise", "full", "notice")
EMPTY_POLICIES = ("per_domain", "all_empty", "silent")

STATUS_LABEL = {
    "DONE": "已完成",
    "EMPTY_SILENT": "空结果",
    "missing": "缺报",
    "unknown": "状态未知",
}


# --------------------------------------------------------------------------- #
# 凭据与配置
# --------------------------------------------------------------------------- #
def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def load_push_config() -> dict[str, Any]:
    """合并环境变量与凭据文件，环境变量优先。敏感值不做任何脱敏存储。"""
    file_values = _parse_env_file(CREDENTIALS_PATH)

    def pick(key: str, default: str = "") -> str:
        env_value = (os.getenv(key) or "").strip()
        if env_value:
            return env_value
        return file_values.get(key, default).strip()

    port_raw = pick("QQ_SMTP_PORT", "465")
    try:
        port = int(port_raw)
    except ValueError:
        port = 465
    use_ssl_raw = pick("QQ_SMTP_USE_SSL", "true").lower()
    mode = pick("EARLY_BIRD_PUSH_MODE", "concise").lower()
    if mode not in PUSH_MODES:
        mode = "concise"
    empty_policy = pick("EARLY_BIRD_PUSH_EMPTY", "per_domain").lower()
    if empty_policy not in EMPTY_POLICIES:
        empty_policy = "per_domain"
    try:
        retry_minutes = max(1, int(pick("EARLY_BIRD_PUSH_RETRY_INTERVAL_MINUTES", "15")))
    except ValueError:
        retry_minutes = 15
    try:
        max_retries = max(0, int(pick("EARLY_BIRD_PUSH_MAX_RETRIES", "8")))
    except ValueError:
        max_retries = 8

    return {
        "sender": pick("QQ_EMAIL_FROM"),
        "auth_code": pick("QQ_EMAIL_AUTH_CODE"),
        "recipients": [item.strip() for item in pick("QQ_EMAIL_TO").split(",") if item.strip()],
        "smtp_host": pick("QQ_SMTP_HOST", "smtp.qq.com"),
        "smtp_port": port,
        "use_ssl": use_ssl_raw not in {"false", "0", "no"},
        "mode": mode,
        "empty_policy": empty_policy,
        "retry_minutes": retry_minutes,
        "max_retries": max_retries,
        "scheduler_enabled": pick("EARLY_BIRD_SCHEDULER_ENABLED", "true").lower() not in {"false", "0", "no"},
    }


def config_status(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """返回可安全展示的配置状态（不含授权码）。"""
    cfg = config or load_push_config()
    return {
        "credentials_file": str(CREDENTIALS_PATH),
        "credentials_file_exists": CREDENTIALS_PATH.exists(),
        "sender_configured": bool(cfg.get("sender")),
        "auth_code_configured": bool(cfg.get("auth_code")),
        "recipients": cfg.get("recipients", []),
        "smtp_host": cfg.get("smtp_host"),
        "smtp_port": cfg.get("smtp_port"),
        "use_ssl": cfg.get("use_ssl"),
        "mode": cfg.get("mode"),
        "empty_policy": cfg.get("empty_policy"),
        "retry_minutes": cfg.get("retry_minutes"),
        "max_retries": cfg.get("max_retries"),
        "scheduler_enabled": cfg.get("scheduler_enabled"),
        "queue_size": len(load_queue()),
    }


# --------------------------------------------------------------------------- #
# 摘要构建
# --------------------------------------------------------------------------- #
def _domain_line(entry: dict[str, Any], mode: str) -> list[str]:
    name = entry.get("name_cn") or entry.get("domain") or "?"
    status = str(entry.get("status") or "missing")
    events = entry.get("events") or []
    report_date = entry.get("report_date")
    stale = "（沿用 %s）" % report_date if entry.get("stale") and report_date else ""
    label = STATUS_LABEL.get(status, status)

    lines = [f"【{name}】{label}{stale} · 事件 {len(events)} 条"]
    if not events:
        if report_date:
            lines.append("  今日无满足 high 信源要求的合格早期信号。")
        else:
            lines.append("  无日报产物（缺报）。")
        return lines

    top = events if mode == "full" else events[:3]
    for event in top:
        title = str(event.get("title") or "(无标题)")
        signal = str(event.get("signal_type") or "信号")
        sources = [s for s in (event.get("sources") or []) if isinstance(s, dict)]
        domains = {common.normalize_domain(s.get("domain") or s.get("url")) for s in sources}
        lines.append(f"  · [{signal}] {title}（{len(domains)} 独立域名）")
        if mode == "full":
            summary = str(event.get("summary") or "").strip()
            if summary:
                lines.append(f"    摘要：{summary}")
            why = str(event.get("why_early_signal") or "").strip()
            if why:
                lines.append(f"    早期信号价值：{why}")
            for index, source in enumerate(sources, 1):
                lines.append(
                    f"    {index}. {source.get('publisher')}（{source.get('domain')}，"
                    f"{source.get('tier')}，{source.get('published_at')}）{source.get('url')}"
                )
    if mode != "full" and len(events) > 3:
        lines.append(f"  …另有 {len(events) - 3} 条，详见工作台页面。")
    return lines


def build_digest(day: str, mode: str | None = None) -> dict[str, Any]:
    """构建某日推送摘要。返回 subject/text/html/entries/should_push。"""
    cfg = load_push_config()
    effective_mode = (mode or cfg["mode"]).lower()
    if effective_mode not in PUSH_MODES:
        effective_mode = "concise"

    contract = common.load_contract()
    entries = aggregate.collect_all(contract, day)
    total_events = sum(int(e.get("event_count") or 0) for e in entries)
    reported = sum(1 for e in entries if e.get("report_date"))
    issue_count = sum(len(e.get("issues") or []) for e in entries)

    should_push = True
    skip_reason = None
    if total_events == 0:
        policy = cfg["empty_policy"]
        if policy == "silent":
            should_push = False
            skip_reason = "empty_policy=silent：空结果日不推送"
        elif policy == "all_empty":
            should_push = reported > 0
            skip_reason = None if should_push else "六领域均无日报，且 empty_policy=all_empty"

    subject = (
        f"早鸟工作台 · {day} · {total_events} 条早期信号"
        f"（{reported}/{len(entries)} 领域出报）"
    )
    if total_events == 0 and should_push:
        subject = f"早鸟工作台 · {day} · 今日无合格早期信号（{reported}/{len(entries)} 领域出报）"

    text_lines = [
        f"早鸟工作台每日推送 · 数据日期 {day}",
        f"生成时间 {common.now_iso()}",
        f"合格早期信号 {total_events} 条 ｜ 出报领域 {reported}/{len(entries)} ｜ 待处理告警 {issue_count}",
        "信源门槛：每事件组 ≥3 独立域名，Tier-1 官方源 ×1 或 Tier-2 主流媒体 ×2",
        "",
    ]
    for entry in entries:
        text_lines.extend(_domain_line(entry, effective_mode))
        text_lines.append("")
    if issue_count:
        text_lines.append("待处理告警：")
        for entry in entries:
            for issue in entry.get("issues") or []:
                text_lines.append(f"  - {entry.get('name_cn')}：{issue}")
        text_lines.append("")
    workbench = common.resolve("early_bird/工作台/index.html")
    text_lines.append(f"工作台页面：{workbench}")
    text_lines.append("（本邮件由早鸟工作台定时任务自动发送；空结果不代表任务未运行。）")
    text_body = "\n".join(text_lines)

    html_body = _digest_html(day, entries, total_events, reported, issue_count, effective_mode, workbench)
    return {
        "date": day,
        "mode": effective_mode,
        "subject": subject,
        "text": text_body,
        "html": html_body,
        "should_push": should_push,
        "skip_reason": skip_reason,
        "totals": {
            "event_count": total_events,
            "reported_domains": reported,
            "domain_count": len(entries),
            "issue_count": issue_count,
        },
        "entries": [
            {
                "name_cn": e.get("name_cn"),
                "domain_slug": e.get("domain_slug"),
                "status": e.get("status"),
                "report_date": e.get("report_date"),
                "event_count": e.get("event_count"),
                "stale": e.get("stale"),
                "issues": e.get("issues"),
            }
            for e in entries
        ],
    }


def _digest_html(
    day: str,
    entries: list[dict[str, Any]],
    total_events: int,
    reported: int,
    issue_count: int,
    mode: str,
    workbench: Path,
) -> str:
    rows = []
    for entry in entries:
        events = entry.get("events") or []
        status = str(entry.get("status") or "missing")
        label = STATUS_LABEL.get(status, status)
        if entry.get("stale") and entry.get("report_date"):
            label += f"（沿用 {entry.get('report_date')}）"
        color = "#2e7d32" if status in {"DONE", "EMPTY_SILENT"} and not entry.get("issues") else (
            "#c62828" if status in {"missing", "unknown"} else "#ef6c00"
        )
        detail = ""
        if events:
            items = events if mode == "full" else events[:3]
            detail = "<br>".join(
                f"· [{html.escape(str(e.get('signal_type') or '信号'))}] {html.escape(str(e.get('title') or ''))}"
                for e in items
            )
            if mode != "full" and len(events) > 3:
                detail += f"<br>…另有 {len(events) - 3} 条"
        elif entry.get("report_date"):
            detail = "今日无满足 high 信源要求的合格早期信号。"
        else:
            detail = "无日报产物（缺报）。"
        rows.append(
            "<tr>"
            f"<td style='padding:8px;border:1px solid #ddd;white-space:nowrap'>"
            f"<b>{html.escape(str(entry.get('name_cn') or ''))}</b><br>"
            f"<span style='color:{color};font-size:12px'>{html.escape(label)}</span></td>"
            f"<td style='padding:8px;border:1px solid #ddd;text-align:center'>{len(events)}</td>"
            f"<td style='padding:8px;border:1px solid #ddd;font-size:13px'>{detail}</td>"
            "</tr>"
        )
    issues_html = ""
    if issue_count:
        items = []
        for entry in entries:
            for issue in entry.get("issues") or []:
                items.append(f"<li>{html.escape(str(entry.get('name_cn')))}：{html.escape(str(issue))}</li>")
        issues_html = (
            "<p style='color:#c62828'><b>待处理告警</b></p><ul style='font-size:13px'>"
            + "".join(items)
            + "</ul>"
        )
    return f"""<div style="font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;font-size:14px;color:#222">
<h2 style="margin:0 0 4px">早鸟工作台 · {html.escape(day)}</h2>
<p style="color:#666;font-size:12px;margin:0 0 12px">
合格早期信号 <b>{total_events}</b> 条 ｜ 出报领域 <b>{reported}/{len(entries)}</b> ｜ 告警 <b>{issue_count}</b> ｜
信源门槛：≥3 独立域名 + Tier-1×1 或 Tier-2×2</p>
<table style="border-collapse:collapse;width:100%">
<tr style="background:#f5f5f5">
<th style="padding:8px;border:1px solid #ddd;text-align:left">领域</th>
<th style="padding:8px;border:1px solid #ddd">事件数</th>
<th style="padding:8px;border:1px solid #ddd;text-align:left">要点</th>
</tr>
{''.join(rows)}
</table>
{issues_html}
<p style="font-size:12px;color:#666;margin-top:12px">
工作台页面：<code>{html.escape(str(workbench))}</code><br>
本邮件由早鸟工作台定时任务自动发送；空结果不代表任务未运行。</p>
</div>"""


# --------------------------------------------------------------------------- #
# 发送与队列
# --------------------------------------------------------------------------- #
def _connect(config: dict[str, Any]) -> smtplib.SMTP:
    host = config["smtp_host"]
    port = int(config["smtp_port"])
    if config["use_ssl"]:
        context = ssl.create_default_context()
        client = smtplib.SMTP_SSL(host, port, timeout=30, context=context)
    else:
        client = smtplib.SMTP(host, port, timeout=30)
        client.ehlo()
        client.starttls(context=ssl.create_default_context())
        client.ehlo()
    client.login(config["sender"], config["auth_code"])
    return client


def send_email(subject: str, text_body: str, html_body: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config or load_push_config()
    missing = [
        name
        for name, value in (
            ("sender", cfg.get("sender")),
            ("auth_code", cfg.get("auth_code")),
            ("recipients", cfg.get("recipients")),
        )
        if not value
    ]
    if missing:
        return {
            "ok": False,
            "error": f"凭据不完整，缺少: {', '.join(missing)}；请检查 {CREDENTIALS_PATH}",
        }

    message = MIMEMultipart("alternative")
    message["Subject"] = Header(subject, "utf-8")
    message["From"] = formataddr(("早鸟工作台", cfg["sender"]))
    message["To"] = ", ".join(cfg["recipients"])
    message.attach(MIMEText(text_body, "plain", "utf-8"))
    message.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        client = _connect(cfg)
        try:
            client.sendmail(cfg["sender"], cfg["recipients"], message.as_string())
        finally:
            try:
                client.quit()
            except smtplib.SMTPException:
                pass
        return {"ok": True, "recipients": cfg["recipients"]}
    except smtplib.SMTPAuthenticationError as exc:
        return {
            "ok": False,
            "error": f"SMTP 认证失败（授权码可能已失效，请到 QQ 邮箱设置重新生成并更新 {CREDENTIALS_PATH}）: {exc}",
        }
    except OSError as exc:
        return {"ok": False, "error": f"网络不可达或连接失败: {type(exc).__name__}: {exc}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"发送异常: {type(exc).__name__}: {exc}"}


def load_queue() -> list[dict[str, Any]]:
    if not QUEUE_PATH.exists():
        return []
    try:
        data = common.read_json(QUEUE_PATH)
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def save_queue(queue: list[dict[str, Any]]) -> None:
    common.write_json(QUEUE_PATH, queue)


def enqueue(item: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    queue = load_queue()
    now = datetime.now()
    record = {
        "id": item.get("id") or uuid.uuid4().hex[:12],
        "created_at": item.get("created_at") or common.now_iso(),
        "date": item.get("date"),
        "subject": item.get("subject"),
        "text": item.get("text"),
        "html": item.get("html"),
        "attempts": int(item.get("attempts") or 0),
        "last_error": item.get("last_error"),
        "next_retry_at": (now + timedelta(minutes=int(config["retry_minutes"]))).isoformat(),
        "status": "pending",
    }
    queue.append(record)
    save_queue(queue)
    return record


def retry_queue(force: bool = False) -> dict[str, Any]:
    config = load_push_config()
    queue = load_queue()
    now = datetime.now()
    results: list[dict[str, Any]] = []
    remaining: list[dict[str, Any]] = []

    for record in queue:
        if record.get("status") == "exhausted":
            remaining.append(record)
            continue
        next_retry = record.get("next_retry_at")
        if not force and next_retry:
            try:
                if datetime.fromisoformat(next_retry) > now:
                    remaining.append(record)
                    continue
            except ValueError:
                pass
        outcome = send_email(record["subject"], record["text"], record["html"], config)
        record["attempts"] = int(record.get("attempts") or 0) + 1
        record["last_error"] = None if outcome["ok"] else outcome.get("error")
        if outcome["ok"]:
            record["status"] = "sent"
            record["sent_at"] = common.now_iso()
            results.append({"id": record["id"], "status": "sent", "attempts": record["attempts"]})
            continue
        if record["attempts"] > int(config["max_retries"]):
            record["status"] = "exhausted"
            results.append({"id": record["id"], "status": "exhausted", "attempts": record["attempts"]})
            remaining.append(record)
        else:
            record["next_retry_at"] = (now + timedelta(minutes=int(config["retry_minutes"]))).isoformat()
            results.append({"id": record["id"], "status": "retry_scheduled", "attempts": record["attempts"]})
            remaining.append(record)

    save_queue(remaining)
    return {"results": results, "queue_size": len(remaining)}


# --------------------------------------------------------------------------- #
# 收件箱与推送主流程
# --------------------------------------------------------------------------- #
def write_inbox(digest: dict[str, Any], send_result: dict[str, Any] | None) -> Path:
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "date": digest["date"],
        "generated_at": common.now_iso(),
        "subject": digest["subject"],
        "text": digest["text"],
        "html": digest["html"],
        "mode": digest["mode"],
        "should_push": digest["should_push"],
        "skip_reason": digest.get("skip_reason"),
        "totals": digest["totals"],
        "entries": digest["entries"],
        "send": send_result,
    }
    path = INBOX_DIR / f"{digest['date']}.json"
    common.write_json(path, entry)
    common.write_json(INBOX_DIR / "latest.json", entry)
    return path


def push_digest(day: str, mode: str | None = None, force: bool = False) -> dict[str, Any]:
    """构建摘要 → 写收件箱 → 发邮件（失败入队重试）。"""
    config = load_push_config()
    digest = build_digest(day, mode)
    if not digest["should_push"] and not force:
        inbox = write_inbox(digest, None)
        return {
            "status": "skipped",
            "reason": digest.get("skip_reason") or "按空结果策略不推送",
            "inbox": str(inbox),
            "subject": digest["subject"],
            "totals": digest["totals"],
        }

    send_result = send_email(digest["subject"], digest["text"], digest["html"], config)
    if not send_result["ok"]:
        record = enqueue(digest, config)
        inbox = write_inbox(digest, {**send_result, "queued": True, "queue_id": record["id"]})
        return {
            "status": "queued",
            "error": send_result.get("error"),
            "queue_id": record["id"],
            "next_retry_at": record["next_retry_at"],
            "inbox": str(inbox),
            "subject": digest["subject"],
            "totals": digest["totals"],
        }

    inbox = write_inbox(digest, send_result)
    return {
        "status": "sent",
        "recipients": send_result.get("recipients"),
        "inbox": str(inbox),
        "subject": digest["subject"],
        "totals": digest["totals"],
    }


def send_test_email() -> dict[str, Any]:
    config = load_push_config()
    subject = f"早鸟工作台 · 推送通道测试 · {common.today_str()}"
    text = (
        "这是一封测试邮件，用于验证早鸟工作台的 SMTP 推送通道。\n"
        f"发件人：{config.get('sender') or '(未配置)'}\n"
        f"收件人：{', '.join(config.get('recipients') or []) or '(未配置)'}\n"
        f"SMTP：{config.get('smtp_host')}:{config.get('smtp_port')} "
        f"({'SSL' if config.get('use_ssl') else 'STARTTLS'})\n"
        "收到本邮件说明凭据与网络均正常。"
    )
    html_body = f"<p>{html.escape(text).replace(chr(10), '<br>')}</p>"
    result = send_email(subject, text, html_body, config)
    if not result["ok"]:
        result["hint"] = (
            "若错误为网络不可达：当前沙箱出网受限，邮件会在队列中等待重试；"
            "若为认证失败：请到 QQ 邮箱设置重新生成授权码并更新 config/credentials.env。"
        )
    return result


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="notify.py", description="早鸟工作台推送模块")
    sub = parser.add_subparsers(dest="command", required=True)

    p_digest = sub.add_parser("digest", help="构建并（可选）发送某日摘要")
    p_digest.add_argument("--date", default=None)
    p_digest.add_argument("--send", action="store_true", help="实际发送（默认只构建并写收件箱）")
    p_digest.add_argument("--mode", default=None, choices=list(PUSH_MODES))
    p_digest.add_argument("--force", action="store_true", help="忽略空结果策略强制发送")

    p_retry = sub.add_parser("retry", help="重试失败队列")
    p_retry.add_argument("--force", action="store_true", help="忽略重试间隔立即重试")

    sub.add_parser("test", help="发送测试邮件")
    sub.add_parser("status", help="查看推送配置与队列状态")
    args = parser.parse_args(argv)

    if args.command == "digest":
        day = args.date or common.today_str()
        if args.send:
            payload = push_digest(day, args.mode, force=args.force)
        else:
            digest = build_digest(day, args.mode)
            inbox = write_inbox(digest, None)
            payload = {
                "status": "built",
                "inbox": str(inbox),
                "subject": digest["subject"],
                "should_push": digest["should_push"],
                "skip_reason": digest.get("skip_reason"),
                "totals": digest["totals"],
                "text_preview": digest["text"][:1200],
            }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.command == "retry":
        print(json.dumps(retry_queue(force=args.force), ensure_ascii=False, indent=2))
        return 0
    if args.command == "test":
        print(json.dumps(send_test_email(), ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(config_status(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
