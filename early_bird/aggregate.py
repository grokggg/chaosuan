#!/usr/bin/env python3
"""早鸟工作台聚合器（等价于原 Coze 版 aggregate.py）。

用法：
  python early_bird/aggregate.py snapshot [--date YYYY-MM-DD] [--force]
  python early_bird/aggregate.py status   [--date YYYY-MM-DD]
  python early_bird/aggregate.py domains

行为：
  1. 读取六个领域各自最新的日报产物（daily/YYYY-MM-DD.md + event_list.json + summary.json）；
  2. 渲染工作台 index.html（六领域合并视图 + 信源校验统计）；
  3. 同时保存当日快照 daily/YYYY-MM-DD.html；
  4. 失败时保留上一次 index.html（原子写入，绝不清空旧结果），并把错误追加写入 aggregate.log。
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402

TIER_LABEL = {"tier1": "Tier-1 官方源", "tier2": "Tier-2 主流媒体"}
CONFIDENCE_LABEL = {"high": "高", "medium": "中"}
DOMAIN_ORDER = ["tech", "med", "fin", "consumer", "biz", "talent"]


# --------------------------------------------------------------------------- #
# 数据采集
# --------------------------------------------------------------------------- #
def latest_report_day(domain: dict[str, Any], on_or_before: str) -> str | None:
    """在 daily/ 下找到不晚于 on_or_before 的最新日报日期。"""
    daily_dir = common.domain_dir(domain) / "daily"
    if not daily_dir.exists():
        return None
    days: list[str] = []
    for path in daily_dir.glob("*.md"):
        day = common.parse_date(path.stem)
        if day and path.stem <= on_or_before:
            days.append(path.stem)
    return max(days) if days else None


def collect_domain(contract: dict[str, Any], domain: dict[str, Any], day: str) -> dict[str, Any]:
    """采集单个领域的最新日报数据；任何缺失都记为 issue 而不抛异常。"""
    entry: dict[str, Any] = {
        "name_cn": domain.get("name_cn"),
        "domain": domain.get("domain"),
        "domain_slug": domain.get("domain_slug"),
        "setup_token": domain.get("setup_token"),
        "schedule_time": domain.get("schedule_time"),
        "output_dir": str(common.domain_dir(domain)),
        "requested_date": day,
        "report_date": None,
        "stale": False,
        "status": "missing",
        "event_count": 0,
        "empty": True,
        "events": [],
        "summary": None,
        "report_markdown": None,
        "source_stats": {"tier1_count": 0, "tier2_count": 0, "independent_domain_count": 0},
        "issues": [],
    }

    report_day = latest_report_day(domain, day)
    if not report_day:
        entry["issues"].append("未找到任何日报（daily/*.md）")
        return entry

    entry["report_date"] = report_day
    entry["stale"] = report_day != day
    if entry["stale"]:
        entry["issues"].append(f"最新日报为 {report_day}，早于请求日 {day}（沿用最近一次结果）")

    paths = common.read_paths_for_day(domain, report_day)
    state = common.load_state_for_day(paths, report_day)
    if state:
        entry["status"] = str(state.get("status", "unknown"))

    report_path = paths["report"]
    if report_path.exists():
        try:
            entry["report_markdown"] = report_path.read_text(encoding="utf-8")
        except OSError as exc:
            entry["issues"].append(f"日报读取失败: {exc}")
    else:
        entry["issues"].append(f"日报文件缺失: {report_path}")

    events: list[Any] = []
    if paths["event_list"].exists():
        try:
            loaded = common.read_json(paths["event_list"])
            if isinstance(loaded, list):
                events = [item for item in loaded if isinstance(item, dict)]
            else:
                entry["issues"].append("event_list.json 顶层不是数组")
        except (json.JSONDecodeError, OSError) as exc:
            entry["issues"].append(f"event_list.json 解析失败: {exc}")
    else:
        entry["issues"].append(f"event_list.json 缺失: {paths['event_list']}")

    summary: dict[str, Any] | None = None
    if paths["summary"].exists():
        try:
            loaded_summary = common.read_json(paths["summary"])
            if isinstance(loaded_summary, dict):
                summary = loaded_summary
            else:
                entry["issues"].append("summary.json 顶层不是对象")
        except (json.JSONDecodeError, OSError) as exc:
            entry["issues"].append(f"summary.json 解析失败: {exc}")
    else:
        entry["issues"].append(f"summary.json 缺失: {paths['summary']}")

    entry["summary"] = summary
    entry["events"] = events
    entry["event_count"] = len(events)
    entry["empty"] = len(events) == 0

    # 信源统计：以事件实算为准，summary.source_stats 仅作交叉校验
    domains_seen: set[str] = set()
    computed_tier1 = 0
    computed_tier2 = 0
    for event in events:
        for source in event.get("sources") or []:
            if not isinstance(source, dict):
                continue
            domain_name = common.normalize_domain(source.get("domain") or source.get("url"))
            if domain_name:
                domains_seen.add(domain_name)
            tier = str(source.get("tier", "")).strip().lower()
            if tier == "tier1":
                computed_tier1 += 1
            elif tier == "tier2":
                computed_tier2 += 1

    stats = {
        "tier1_count": computed_tier1,
        "tier2_count": computed_tier2,
        "independent_domain_count": len(domains_seen),
    }
    declared = summary.get("source_stats") if summary else None
    if isinstance(declared, dict):
        for key in stats:
            value = declared.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0 and value != stats[key]:
                entry["issues"].append(
                    f"summary.source_stats.{key}={value} 与事件实算 {stats[key]} 不一致，已采用实算值"
                )
    entry["source_stats"] = stats

    if entry["status"] == "missing" and entry["report_markdown"]:
        entry["status"] = "unknown"
    return entry


def collect_all(contract: dict[str, Any], day: str) -> list[dict[str, Any]]:
    domains = list(contract.get("domains", []))
    order = {slug: index for index, slug in enumerate(DOMAIN_ORDER)}
    domains.sort(key=lambda d: order.get(str(d.get("domain_slug", "")), 99))
    return [collect_domain(contract, domain, day) for domain in domains]


# --------------------------------------------------------------------------- #
# Markdown → HTML（轻量渲染，无第三方依赖）
# --------------------------------------------------------------------------- #
_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_BARE_LINK = re.compile(r"(?<![\(\]\"'>])(https?://[^\s<>\)\"]+)")


def _inline(text: str) -> str:
    escaped = html.escape(text, quote=False)
    escaped = _LINK.sub(lambda m: f'<a href="{html.escape(m.group(2), quote=True)}" target="_blank" '
                                  f'rel="noopener noreferrer">{m.group(1)}</a>', escaped)
    escaped = _BARE_LINK.sub(
        lambda m: m.group(0)
        if m.group(0).startswith('<a href=') or 'rel="noopener noreferrer">' in m.group(0)
        else f'<a href="{html.escape(m.group(0), quote=True)}" target="_blank" rel="noopener noreferrer">'
        f"{m.group(0)}</a>",
        escaped,
    )
    escaped = _INLINE_CODE.sub(r"<code>\1</code>", escaped)
    escaped = _BOLD.sub(r"<strong>\1</strong>", escaped)
    return escaped


def markdown_to_html(markdown_text: str) -> str:
    """把日报 Markdown 渲染为 HTML 片段（支持标题/列表/表格/链接/加粗/代码）。"""
    lines = (markdown_text or "").replace("\r\n", "\n").split("\n")
    out: list[str] = []
    list_stack: list[str] = []
    in_code = False
    in_table = False
    table_header_done = False

    def close_lists() -> None:
        while list_stack:
            out.append(f"</{list_stack.pop()}>")

    def close_table() -> None:
        nonlocal in_table, table_header_done
        if in_table:
            out.append("</tbody></table>")
            in_table = False
            table_header_done = False

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_code:
                out.append("</code></pre>")
                in_code = False
            else:
                close_lists()
                close_table()
                out.append("<pre><code>")
                in_code = True
            continue
        if in_code:
            out.append(html.escape(raw, quote=False))
            continue

        if not stripped:
            close_lists()
            close_table()
            continue

        # 表格
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells if cell):
                table_header_done = True
                continue
            close_lists()
            if not in_table:
                out.append('<table class="md-table"><thead><tr>')
                out.extend(f"<th>{_inline(cell)}</th>" for cell in cells)
                out.append("</tr></thead><tbody>")
                in_table = True
                table_header_done = False
                continue
            out.append("<tr>" + "".join(f"<td>{_inline(cell)}</td>" for cell in cells) + "</tr>")
            continue
        close_table()

        # 标题
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            close_lists()
            level = min(6, len(heading.group(1)) + 2)  # 日报 H1 → 页面 H3
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue

        # 分隔线
        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", stripped):
            close_lists()
            out.append("<hr>")
            continue

        # 引用
        if stripped.startswith(">"):
            close_lists()
            out.append(f"<blockquote>{_inline(stripped.lstrip('> ').strip())}</blockquote>")
            continue

        # 列表
        item = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)$", raw)
        if item:
            indent = len(item.group(1))
            ordered = item.group(2)[0].isdigit()
            tag = "ol" if ordered else "ul"
            depth = 1 + indent // 2
            while len(list_stack) > depth:
                out.append(f"</{list_stack.pop()}>")
            while len(list_stack) < depth:
                out.append(f"<{tag}>")
                list_stack.append(tag)
            if list_stack and list_stack[-1] != tag:
                out.append(f"</{list_stack.pop()}>")
                out.append(f"<{tag}>")
                list_stack.append(tag)
            out.append(f"<li>{_inline(item.group(3))}</li>")
            continue

        close_lists()
        out.append(f"<p>{_inline(stripped)}</p>")

    if in_code:
        out.append("</code></pre>")
    close_lists()
    close_table()
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# HTML 渲染
# --------------------------------------------------------------------------- #
PAGE_CSS = """
:root{--bg:#0f1115;--panel:#171a21;--panel2:#1e222b;--line:#2a2f3a;--text:#e6e8ee;
--muted:#9aa3b2;--accent:#5aa9ff;--ok:#3ddc97;--warn:#ffb454;--err:#ff6b6b;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB",
"Microsoft YaHei",sans-serif;line-height:1.65;font-size:15px}
.wrap{max-width:1180px;margin:0 auto;padding:28px 20px 64px}
header.top{border-bottom:1px solid var(--line);padding-bottom:18px;margin-bottom:22px}
h1{font-size:26px;margin:0 0 6px}
.sub{color:var(--muted);font-size:13px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:20px 0}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}
.kpi .n{font-size:24px;font-weight:600}
.kpi .l{color:var(--muted);font-size:12px;margin-top:2px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px;margin-bottom:26px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}
.card h2{font-size:16px;margin:0 0 4px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.badge{font-size:11px;padding:2px 8px;border-radius:999px;border:1px solid var(--line);
background:var(--panel2);color:var(--muted);white-space:nowrap}
.badge.ok{color:var(--ok);border-color:rgba(61,220,151,.35)}
.badge.empty{color:var(--muted)}
.badge.warn{color:var(--warn);border-color:rgba(255,180,84,.35)}
.badge.err{color:var(--err);border-color:rgba(255,107,107,.35)}
.meta{color:var(--muted);font-size:12px;margin-bottom:10px}
ul.events{margin:8px 0 0;padding-left:18px}
ul.events li{margin-bottom:6px}
.tag{display:inline-block;font-size:11px;color:var(--accent);border:1px solid rgba(90,169,255,.3);
border-radius:4px;padding:0 6px;margin-right:6px}
section.domain{background:var(--panel);border:1px solid var(--line);border-radius:12px;
padding:20px;margin-bottom:18px}
section.domain>h2{font-size:19px;margin:0 0 4px;border-bottom:1px solid var(--line);padding-bottom:10px}
.report{margin-top:14px}
.report h3{font-size:17px;margin:20px 0 8px}
.report h4{font-size:15px;margin:16px 0 6px;color:var(--accent)}
.report h5,.report h6{font-size:14px;margin:14px 0 6px;color:var(--muted)}
.report p{margin:8px 0}
.report ul,.report ol{margin:8px 0;padding-left:22px}
.report a{color:var(--accent);text-decoration:none;word-break:break-all}
.report a:hover{text-decoration:underline}
.report code{background:var(--panel2);padding:1px 5px;border-radius:4px;font-size:13px}
.report pre{background:#0b0d12;border:1px solid var(--line);border-radius:8px;padding:12px;overflow:auto}
.report blockquote{border-left:3px solid var(--line);margin:10px 0;padding:4px 12px;color:var(--muted)}
.md-table{border-collapse:collapse;width:100%;margin:12px 0;font-size:13px}
.md-table th,.md-table td{border:1px solid var(--line);padding:6px 9px;text-align:left}
.md-table th{background:var(--panel2)}
.issues{margin-top:12px;padding:10px 12px;border-radius:8px;background:rgba(255,180,84,.08);
border:1px solid rgba(255,180,84,.25);font-size:13px}
.issues strong{color:var(--warn)}
.issues ul{margin:6px 0 0;padding-left:18px}
.empty-note{color:var(--muted);font-size:13px;margin-top:8px}
footer{margin-top:32px;padding-top:16px;border-top:1px solid var(--line);color:var(--muted);font-size:12px}
"""


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _status_badge(entry: dict[str, Any]) -> str:
    status = str(entry.get("status", "missing"))
    if status in {"DONE", "EMPTY_SILENT"} and not entry.get("issues"):
        cls, text = "ok", {"DONE": "已完成", "EMPTY_SILENT": "空结果·静默"}[status]
    elif status in {"DONE", "EMPTY_SILENT"}:
        cls, text = "warn", "已完成·有告警"
    elif status in {"missing", "unknown"}:
        cls, text = "err", "缺报"
    else:
        cls, text = "warn", f"进行中·{status}"
    if entry.get("stale") and cls == "ok":
        cls, text = "warn", f"沿用 {entry.get('report_date')}"
    return f'<span class="badge {cls}">{_esc(text)}</span>'


def render_overview(entries: list[dict[str, Any]], day: str, generated_at: str) -> str:
    total_events = sum(int(e.get("event_count") or 0) for e in entries)
    reported = sum(1 for e in entries if e.get("report_date"))
    empty_domains = sum(1 for e in entries if e.get("empty") and e.get("report_date"))
    tier1 = sum(int((e.get("source_stats") or {}).get("tier1_count") or 0) for e in entries)
    tier2 = sum(int((e.get("source_stats") or {}).get("tier2_count") or 0) for e in entries)
    domains_seen = sum(int((e.get("source_stats") or {}).get("independent_domain_count") or 0) for e in entries)
    issues = sum(len(e.get("issues") or []) for e in entries)

    kpis = [
        (str(total_events), "合格早期信号"),
        (f"{reported}/{len(entries)}", "领域已出报"),
        (str(empty_domains), "空结果领域"),
        (str(tier1), "Tier-1 官方源引用"),
        (str(tier2), "Tier-2 媒体引用"),
        (str(domains_seen), "独立域名合计"),
        (str(issues), "待处理告警"),
    ]
    kpi_html = "".join(f'<div class="kpi"><div class="n">{_esc(v)}</div><div class="l">{_esc(l)}</div></div>'
                       for v, l in kpis)

    cards: list[str] = []
    for entry in entries:
        events = entry.get("events") or []
        if events:
            items = "".join(
                "<li>"
                f'<span class="tag">{_esc(ev.get("signal_type") or "信号")}</span>'
                f"{_esc(ev.get('title') or '(无标题)')}"
                f' <span class="meta">[{_esc(CONFIDENCE_LABEL.get(str(ev.get("confidence", "")).lower(), ev.get("confidence")))}'
                f"信度 · {len([s for s in (ev.get('sources') or []) if isinstance(s, dict)])} 源]</span>"
                "</li>"
                for ev in events[:6]
            )
            body = f'<ul class="events">{items}</ul>'
            if len(events) > 6:
                body += f'<div class="meta">另有 {len(events) - 6} 条，见下方详情</div>'
        elif entry.get("report_date"):
            body = '<div class="empty-note">今日无满足 high 信源要求的合格早期信号。</div>'
        else:
            body = '<div class="empty-note">尚无日报产物。</div>'

        cards.append(
            '<div class="card">'
            f"<h2>{_esc(entry.get('name_cn'))} {_status_badge(entry)}</h2>"
            f'<div class="meta">日报日期 {_esc(entry.get("report_date") or "—")} · '
            f"调度 {_esc(entry.get('schedule_time') or '—')} · "
            f"事件 {int(entry.get('event_count') or 0)} 条 · "
            f"token {_esc(entry.get('setup_token'))}</div>"
            f"{body}"
            "</div>"
        )

    return (
        '<header class="top">'
        f"<h1>早鸟工作台 · 每日聚合视图</h1>"
        f'<div class="sub">数据日期 {_esc(day)} · 生成于 {_esc(generated_at)} · '
        "信源要求 authority_requirement=high（每事件组 ≥3 独立域名，Tier-1 官方源 ×1 或 Tier-2 主流媒体 ×2）</div>"
        "</header>"
        f'<div class="kpis">{kpi_html}</div>'
        f'<div class="grid">{"".join(cards)}</div>'
    )


def render_domain_sections(entries: list[dict[str, Any]]) -> str:
    sections: list[str] = []
    for entry in entries:
        stats = entry.get("source_stats") or {}
        issues = entry.get("issues") or []
        issue_html = ""
        if issues:
            issue_html = (
                '<div class="issues"><strong>数据告警</strong><ul>'
                + "".join(f"<li>{_esc(item)}</li>" for item in issues)
                + "</ul></div>"
            )
        markdown_text = entry.get("report_markdown") or ""
        report_html = (
            f'<div class="report">{markdown_to_html(markdown_text)}</div>'
            if markdown_text.strip()
            else '<div class="empty-note">日报正文缺失，无法渲染。</div>'
        )
        sections.append(
            f'<section class="domain" id="domain-{_esc(entry.get("domain_slug"))}">'
            f"<h2>{_esc(entry.get('name_cn'))} {_status_badge(entry)}</h2>"
            f'<div class="meta">setup_token {_esc(entry.get("setup_token"))} · '
            f"日报 {_esc(entry.get('report_date') or '—')} · "
            f"事件 {int(entry.get('event_count') or 0)} 条 · "
            f"Tier-1 {int(stats.get('tier1_count') or 0)} / Tier-2 {int(stats.get('tier2_count') or 0)} / "
            f"独立域名 {int(stats.get('independent_domain_count') or 0)} · "
            f"产物目录 {_esc(entry.get('output_dir'))}</div>"
            f"{issue_html}{report_html}"
            "</section>"
        )
    return "".join(sections)


def render_page(entries: list[dict[str, Any]], day: str, generated_at: str, snapshot: bool) -> str:
    nav = "".join(
        f'<a class="badge" href="#domain-{_esc(e.get("domain_slug"))}">{_esc(e.get("domain"))}</a> '
        for e in entries
    )
    kind = "每日快照" if snapshot else "最新工作台"
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>早鸟工作台 · {_esc(day)}</title>
<style>{PAGE_CSS}</style>
</head>
<body>
<div class="wrap">
{render_overview(entries, day, generated_at)}
<div class="sub" style="margin-bottom:18px">快速跳转：{nav}</div>
{render_domain_sections(entries)}
<footer>
{kind} · 数据日期 {_esc(day)} · 生成于 {_esc(generated_at)}<br>
聚合规则：读取六领域最新日报（daily/YYYY-MM-DD.md + event_list.json + summary.json）合并渲染；
渲染失败时保留上一次 index.html，错误写入 aggregate.log。
</footer>
</div>
</body>
</html>
"""


# --------------------------------------------------------------------------- #
# 日志与原子写入
# --------------------------------------------------------------------------- #
def resolve_log() -> Path:
    contract = common.load_contract()
    rel = (contract.get("paths") or {}).get("aggregate_log", "early_bird/aggregate.log")
    return common.resolve(rel)


def append_log(message: str, level: str = "INFO") -> None:
    try:
        path = resolve_log()
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] [{level}] {message}\n")
    except OSError:
        pass


def atomic_write(path: Path, text: str) -> None:
    """原子写入：先写临时文件再 rename，失败时绝不破坏已有文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp.{datetime.now().strftime('%Y%m%d%H%M%S%f')}")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
        os.replace(tmp, path)
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


# --------------------------------------------------------------------------- #
# 命令
# --------------------------------------------------------------------------- #
def workbench_paths() -> dict[str, Path]:
    contract = common.load_contract()
    paths_cfg = contract.get("paths") or {}
    root = common.resolve(paths_cfg.get("workbench_root", "early_bird/工作台"))
    return {
        "root": root,
        "index": root / "index.html",
        "daily_dir": root / "daily",
        "manifest": root / "manifest.json",
    }


def cmd_snapshot(args: argparse.Namespace) -> int:
    day = args.date or common.today_str()
    if not common.parse_date(day):
        print(json.dumps({"status": "error", "message": f"--date 格式非法: {day}"}, ensure_ascii=False))
        return 2

    paths = workbench_paths()
    generated_at = common.now_iso()
    try:
        contract = common.load_contract()
        entries = collect_all(contract, day)
        page = render_page(entries, day, generated_at, snapshot=False)
        snapshot_page = render_page(entries, day, generated_at, snapshot=True)
        if not page.strip() or "<!DOCTYPE html>" not in page:
            raise RuntimeError("渲染结果为空，疑似模板异常")

        paths["root"].mkdir(parents=True, exist_ok=True)
        paths["daily_dir"].mkdir(parents=True, exist_ok=True)

        atomic_write(paths["index"], page)
        snapshot_file = paths["daily_dir"] / f"{day}.html"
        atomic_write(snapshot_file, snapshot_page)

        manifest = {
            "date": day,
            "generated_at": generated_at,
            "index": str(paths["index"]),
            "snapshot": str(snapshot_file),
            "index_bytes": paths["index"].stat().st_size,
            "domains": [
                {
                    "name_cn": e.get("name_cn"),
                    "domain_slug": e.get("domain_slug"),
                    "setup_token": e.get("setup_token"),
                    "report_date": e.get("report_date"),
                    "status": e.get("status"),
                    "event_count": e.get("event_count"),
                    "empty": e.get("empty"),
                    "stale": e.get("stale"),
                    "source_stats": e.get("source_stats"),
                    "issues": e.get("issues"),
                }
                for e in entries
            ],
            "totals": {
                "event_count": sum(int(e.get("event_count") or 0) for e in entries),
                "reported_domains": sum(1 for e in entries if e.get("report_date")),
                "domain_count": len(entries),
                "issue_count": sum(len(e.get("issues") or []) for e in entries),
            },
        }
        atomic_write_json(paths["manifest"], manifest)

        issue_count = manifest["totals"]["issue_count"]
        append_log(
            f"snapshot ok date={day} domains={manifest['totals']['reported_domains']}/{len(entries)} "
            f"events={manifest['totals']['event_count']} issues={issue_count} index={paths['index']}",
            "WARN" if issue_count else "INFO",
        )
        print(json.dumps({"status": "ok", **manifest}, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001
        detail = traceback.format_exc()
        append_log(f"snapshot failed date={day} error={type(exc).__name__}: {exc}\n{detail}", "ERROR")
        kept = paths["index"].exists()
        print(
            json.dumps(
                {
                    "status": "error",
                    "message": f"聚合失败：{type(exc).__name__}: {exc}",
                    "previous_index_kept": kept,
                    "index": str(paths["index"]),
                    "log": str(resolve_log()),
                    "traceback": detail.strip().splitlines()[-6:],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1


def cmd_status(args: argparse.Namespace) -> int:
    day = args.date or common.today_str()
    contract = common.load_contract()
    entries = collect_all(contract, day)
    paths = workbench_paths()
    print(
        json.dumps(
            {
                "status": "ok",
                "date": day,
                "index": str(paths["index"]),
                "index_exists": paths["index"].exists(),
                "index_mtime": (
                    datetime.fromtimestamp(paths["index"].stat().st_mtime).isoformat()
                    if paths["index"].exists()
                    else None
                ),
                "snapshot": str(paths["daily_dir"] / f"{day}.html"),
                "snapshot_exists": (paths["daily_dir"] / f"{day}.html").exists(),
                "domains": [
                    {
                        "name_cn": e.get("name_cn"),
                        "report_date": e.get("report_date"),
                        "status": e.get("status"),
                        "event_count": e.get("event_count"),
                        "empty": e.get("empty"),
                        "stale": e.get("stale"),
                        "source_stats": e.get("source_stats"),
                        "issues": e.get("issues"),
                    }
                    for e in entries
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_domains(_args: argparse.Namespace) -> int:
    contract = common.load_contract()
    rows = []
    for domain in contract.get("domains", []):
        base = common.domain_dir(domain)
        day = latest_report_day(domain, common.today_str())
        rows.append(
            {
                "name_cn": domain.get("name_cn"),
                "domain_slug": domain.get("domain_slug"),
                "setup_token": domain.get("setup_token"),
                "schedule_time": domain.get("schedule_time"),
                "output_dir": str(base),
                "latest_report_date": day,
                "report_path": str(base / "daily" / f"{day}.md") if day else None,
            }
        )
    print(json.dumps({"status": "ok", "domains": rows}, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aggregate.py", description="早鸟工作台聚合渲染器")
    sub = parser.add_subparsers(dest="command", required=True)

    p_snap = sub.add_parser("snapshot", help="聚合六领域最新日报并渲染 index.html + daily 快照")
    p_snap.add_argument("--date", default=None, help="数据日期 YYYY-MM-DD，默认今天")
    p_snap.add_argument("--force", action="store_true", help="保留参数，当前行为始终覆盖渲染")
    p_snap.set_defaults(func=cmd_snapshot)

    p_status = sub.add_parser("status", help="查看各领域日报采集状态与工作台产物")
    p_status.add_argument("--date", default=None, help="数据日期 YYYY-MM-DD，默认今天")
    p_status.set_defaults(func=cmd_status)

    p_domains = sub.add_parser("domains", help="列出六领域目录与最新日报日期")
    p_domains.set_defaults(func=cmd_domains)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
