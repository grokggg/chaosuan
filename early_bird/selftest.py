#!/usr/bin/env python3
"""早鸟工作台端到端自检：造样例数据跑通 B1→B4、空结果分支与聚合渲染。

用法：python early_bird/selftest.py
所有产物写入临时目录（通过 EARLY_BIRD_ROOT 重定向），不污染项目目录。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
GUIDE = SCRIPT_DIR / "guide.py"
AGGREGATE = SCRIPT_DIR / "aggregate.py"

TEST_DAY = "2026-11-07"
PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  [PASS] {name}")
    else:
        FAILED.append(f"{name} :: {detail}")
        print(f"  [FAIL] {name} :: {detail}")


def run(script: Path, argv: list[str], root: Path) -> tuple[int, dict | str]:
    env = dict(os.environ)
    env["EARLY_BIRD_ROOT"] = str(root)
    completed = subprocess.run(
        [sys.executable, str(script), *argv],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )
    stdout = (completed.stdout or "").strip()
    try:
        return completed.returncode, json.loads(stdout)
    except json.JSONDecodeError:
        return completed.returncode, stdout or (completed.stderr or "").strip()


def sample_candidates() -> list[dict]:
    return [
        {
            "title": "某开源模型发布预览版权重",
            "url": "https://huggingface.co/blog/preview-release",
            "domain": "huggingface.co",
            "publisher": "Hugging Face",
            "tier": "tier1",
            "published_at": TEST_DAY,
            "focus_tag": "开源模型与工具",
        },
        {
            "title": "开源模型预览版引发开发者关注",
            "url": "https://www.jiqizhixin.com/articles/preview",
            "domain": "jiqizhixin.com",
            "publisher": "机器之心",
            "tier": "tier2",
            "published_at": TEST_DAY,
            "focus_tag": "开源模型与工具",
        },
        {
            "title": "Preview model release coverage",
            "url": "https://techcrunch.com/2026/11/07/preview-model",
            "domain": "techcrunch.com",
            "publisher": "TechCrunch",
            "tier": "tier2",
            "published_at": TEST_DAY,
            "focus_tag": "开源模型与工具",
        },
        {
            "title": "某品牌促销活动（应被排除）",
            "url": "https://example.com/promo",
            "domain": "example.com",
            "publisher": "Example",
            "tier": "unknown",
            "published_at": TEST_DAY,
            "focus_tag": "其他",
        },
    ]


def sample_events() -> list[dict]:
    def source(url: str, domain: str, publisher: str, tier: str) -> dict:
        return {
            "url": url,
            "domain": domain,
            "publisher": publisher,
            "tier": tier,
            "published_at": TEST_DAY,
            "quote": f"{publisher} 报道该模型预览版已开放下载，上下文窗口与推理成本出现明显变化。",
        }

    return [
        {
            "event_id": "tech-20261107-01",
            "title": "开源大模型发布预览版权重，推理成本下探至新档位",
            "signal_type": "开源生态节点",
            "happened_at": TEST_DAY,
            "summary": (
                "开源模型团队于当日放出新一代预览版权重，公开了模型卡与推理基准数据。"
                "相较上一代，预览版在同等硬件下的吞吐提升明显，单 token 推理成本下探到新档位，"
                "并已同步上线主流模型托管平台供开发者下载。多家技术媒体跟进报道，"
                "指出该预览版尚未附带商用许可细则，正式版发布时间未定。"
            ),
            "why_early_signal": (
                "推理成本档位下移会改变中小团队的选型边界，但许可细则未定，市场尚未对此定价。"
            ),
            "impact": "可能压低同档位闭源 API 的定价空间，并带动本地部署与推理框架适配需求。",
            "confidence": "high",
            "sources": [
                source("https://huggingface.co/blog/preview-release", "huggingface.co", "Hugging Face", "tier1"),
                source("https://www.jiqizhixin.com/articles/preview", "jiqizhixin.com", "机器之心", "tier2"),
                source("https://techcrunch.com/2026/11/07/preview-model", "techcrunch.com", "TechCrunch", "tier2"),
            ],
        }
    ]


def bad_events() -> list[dict]:
    """故意不达标的事件：只有 2 个域名且无 tier1/tier2×2。"""
    events = sample_events()
    events[0]["sources"] = events[0]["sources"][:2]
    events[0]["sources"][1]["tier"] = "unknown"
    events[0]["confidence"] = "low"
    return events


def sample_summary(domain_cn: str, slug: str, token: str, events: list[dict]) -> dict:
    domains = {
        s["domain"] for event in events for s in event.get("sources", []) if isinstance(s, dict)
    }
    return {
        "date": TEST_DAY,
        "domain": domain_cn,
        "domain_slug": slug,
        "setup_token": token,
        "event_count": len(events),
        "empty": not events,
        "top_events": [
            {
                "event_id": e["event_id"],
                "title": e["title"],
                "signal_type": e["signal_type"],
                "confidence": e["confidence"],
                "source_domain_count": len({s["domain"] for s in e["sources"]}),
            }
            for e in events
        ],
        "source_stats": {
            "tier1_count": sum(1 for e in events for s in e["sources"] if s["tier"] == "tier1"),
            "tier2_count": sum(1 for e in events for s in e["sources"] if s["tier"] == "tier2"),
            "independent_domain_count": len(domains),
        },
        "generated_at": f"{TEST_DAY}T08:10:00+08:00",
    }


def sample_report(domain_cn: str, day: str, events: list[dict]) -> str:
    if not events:
        return f"# 早鸟雷达-{domain_cn} · {day}\n\n今日无满足 high 信源要求的合格早期信号。\n"
    lines = [
        f"# 早鸟雷达-{domain_cn} · {day}",
        "",
        "## 今日概览",
        "",
        f"今日共 {len(events)} 条合格早期信号，最高优先级为「{events[0]['title']}」。",
        "",
    ]
    for event in events:
        lines += [
            f"## {event['event_id']} {event['title']}",
            "",
            f"**信号类型**：{event['signal_type']} ｜ **信度**：{event['confidence']} ｜ "
            f"**发生日期**：{event['happened_at']}",
            "",
            "### 事实摘要",
            "",
            event["summary"],
            "",
            "### 早期信号价值",
            "",
            event["why_early_signal"],
            "",
            "### 影响面",
            "",
            event["impact"],
            "",
            "### 来源清单",
            "",
        ]
        for index, source in enumerate(event["sources"], 1):
            lines.append(
                f"{index}. {source['publisher']}（{source['domain']}，{source['tier']}，"
                f"{source['published_at']}）{source['url']}"
            )
        lines.append("")
    lines += [
        "## 信源校验",
        "",
        "| 事件 | 独立域名数 | Tier-1 | Tier-2 | 是否达标 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for event in events:
        domains = {s["domain"] for s in event["sources"]}
        tier1 = sum(1 for s in event["sources"] if s["tier"] == "tier1")
        tier2 = sum(1 for s in event["sources"] if s["tier"] == "tier2")
        ok = "是" if (len(domains) >= 3 and (tier1 >= 1 or tier2 >= 2)) else "否"
        lines.append(f"| {event['event_id']} | {len(domains)} | {tier1} | {tier2} | {ok} |")
    lines.append("")
    return "\n".join(lines)


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="early_bird_selftest_"))
    print(f"临时工作目录: {root}\n")
    try:
        # ---------------- guide list ----------------
        print("[1] guide.py list")
        code, out = run(GUIDE, ["list"], root)
        check("list 返回 0", code == 0, f"code={code}")
        check("list 含 6 个领域", isinstance(out, dict) and len(out.get("domains", [])) == 6, str(out)[:200])

        # ---------------- init ----------------
        print("\n[2] guide.py init（科技）")
        code, out = run(GUIDE, ["init", "--setup-token", "setup_0da2e5ce", "--date", TEST_DAY], root)
        check("init 返回 0", code == 0, f"code={code} out={str(out)[:200]}")
        check("init 状态为 INIT", isinstance(out, dict) and out.get("state", {}).get("status") == "INIT", str(out)[:200])
        check("init 返回下一步 B1", isinstance(out, dict) and out.get("next_step", {}).get("step") == "B1", str(out)[:200])
        check("init 含 high 信源规则", isinstance(out, dict) and out.get("domain", {}).get("authority_requirement") == "high", "")

        # ---------------- B1 ----------------
        print("\n[3] B1 候选检索提交")
        base = root / "early_bird" / "热点资讯追踪" / "早鸟雷达-科技"
        write_json(base / "raw_candidates.json", sample_candidates())
        code, out = run(GUIDE, ["submit", "--setup-token", "tech", "--step", "B1", "--date", TEST_DAY], root)
        check("B1 返回 0", code == 0, f"code={code} out={str(out)[:300]}")
        check("B1 后状态 B1_DONE", isinstance(out, dict) and out.get("state", {}).get("status") == "B1_DONE", str(out)[:200])

        # ---------------- B2 失败分支 ----------------
        print("\n[4] B2 校验失败分支（信源不达标）")
        write_json(base / "event_list.json", bad_events())
        code, out = run(GUIDE, ["submit", "--setup-token", "tech", "--step", "B2", "--date", TEST_DAY], root)
        check("B2 不达标返回非 0", code != 0, f"code={code}")
        check("B2 状态未前进", isinstance(out, dict) and out.get("state", {}).get("status") == "B1_DONE", str(out)[:200])
        errors = out.get("errors", []) if isinstance(out, dict) else []
        check("B2 报出独立域名不足", any("独立域名数" in e for e in errors), str(errors)[:300])
        check("B2 报出 unknown 来源不合格", any("unknown 不得作为合格来源" in e for e in errors), str(errors)[:300])
        check("B2 报出 confidence=low", any("confidence" in e for e in errors), str(errors)[:300])

        # ---------------- B2 成功 ----------------
        print("\n[5] B2 校验通过")
        events = sample_events()
        write_json(base / "event_list.json", events)
        code, out = run(GUIDE, ["submit", "--setup-token", "tech", "--step", "B2", "--date", TEST_DAY], root)
        check("B2 返回 0", code == 0, f"code={code} out={str(out)[:300]}")
        check("B2 后状态 B2_DONE", isinstance(out, dict) and out.get("state", {}).get("status") == "B2_DONE", str(out)[:200])
        check("B2 事件数为 1", isinstance(out, dict) and out.get("event_count") == 1, str(out)[:200])

        # ---------------- B3 ----------------
        print("\n[6] B3 日报与摘要")
        (base / "daily").mkdir(parents=True, exist_ok=True)
        (base / "daily" / f"{TEST_DAY}.md").write_text(
            sample_report("科技", TEST_DAY, events), encoding="utf-8"
        )
        write_json(base / "summary.json", sample_summary("科技", "tech", "setup_0da2e5ce", events))
        code, out = run(GUIDE, ["submit", "--setup-token", "tech", "--step", "B3", "--date", TEST_DAY], root)
        check("B3 返回 0", code == 0, f"code={code} out={str(out)[:300]}")
        check("B3 后状态 B3_DONE", isinstance(out, dict) and out.get("state", {}).get("status") == "B3_DONE", str(out)[:200])

        # ---------------- B3 顺序错误 ----------------
        print("\n[7] 步骤顺序保护")
        code, out = run(GUIDE, ["submit", "--setup-token", "tech", "--step", "B1", "--date", TEST_DAY], root)
        check("跳步提交被拒绝", code != 0, f"code={code}")
        check("提示顺序错误", isinstance(out, dict) and "顺序" in str(out.get("message", "")), str(out)[:200])

        # ---------------- B4 ----------------
        print("\n[8] B4 终检归档")
        code, out = run(GUIDE, ["submit", "--setup-token", "tech", "--step", "B4", "--date", TEST_DAY], root)
        check("B4 返回 0", code == 0, f"code={code} out={str(out)[:300]}")
        check("终态为 DONE", isinstance(out, dict) and out.get("state", {}).get("status") == "DONE", str(out)[:200])
        archived = out.get("artifacts", {}).get("archived", []) if isinstance(out, dict) else []
        check("产物已归档", len(archived) >= 3, str(archived)[:300])
        check("归档目录存在", (base / "daily" / TEST_DAY).is_dir(), str(base))

        # ---------------- 终态后拒绝继续 ----------------
        print("\n[9] 终态保护")
        code, out = run(GUIDE, ["submit", "--setup-token", "tech", "--step", "B4", "--date", TEST_DAY], root)
        check("终态后提交被拒绝", code != 0, f"code={code}")
        code, out = run(GUIDE, ["init", "--setup-token", "tech", "--date", TEST_DAY], root)
        check("终态后 init 提示已完成", code == 0 and isinstance(out, dict) and out.get("status") == "already_finished", str(out)[:200])

        # ---------------- 空结果分支 ----------------
        print("\n[10] 空结果分支（医学）")
        med_base = root / "early_bird" / "热点资讯追踪" / "早鸟雷达-医学"
        code, out = run(GUIDE, ["init", "--setup-token", "setup_244e21da", "--date", TEST_DAY], root)
        check("医学 init 返回 0", code == 0, f"code={code}")
        write_json(med_base / "raw_candidates.json", [])
        code, out = run(GUIDE, ["submit", "--setup-token", "med", "--step", "B1", "--date", TEST_DAY], root)
        check("空候选 B1 通过", code == 0, f"code={code} out={str(out)[:200]}")
        write_json(med_base / "event_list.json", [])
        code, out = run(GUIDE, ["submit", "--setup-token", "med", "--step", "B2", "--date", TEST_DAY], root)
        check("空事件 B2 通过", code == 0, f"code={code} out={str(out)[:200]}")
        check("B2 标记 empty_result", isinstance(out, dict) and out.get("empty_result") is True, str(out)[:200])
        check("B2 提示 no_reply", isinstance(out, dict) and "no_reply" in json.dumps(out, ensure_ascii=False), str(out)[:200])
        (med_base / "daily").mkdir(parents=True, exist_ok=True)
        (med_base / "daily" / f"{TEST_DAY}.md").write_text(
            sample_report("医学", TEST_DAY, []), encoding="utf-8"
        )
        write_json(med_base / "summary.json", sample_summary("医学", "med", "setup_244e21da", []))
        code, out = run(GUIDE, ["submit", "--setup-token", "med", "--step", "B3", "--date", TEST_DAY], root)
        check("空结果 B3 通过", code == 0, f"code={code} out={str(out)[:300]}")
        code, out = run(GUIDE, ["submit", "--setup-token", "med", "--step", "B4", "--date", TEST_DAY], root)
        check("空结果 B4 通过", code == 0, f"code={code} out={str(out)[:300]}")
        check("空结果终态 EMPTY_SILENT", isinstance(out, dict) and out.get("state", {}).get("status") == "EMPTY_SILENT", str(out)[:200])

        # ---------------- 其余四领域补齐（供聚合） ----------------
        print("\n[11] 补齐金融/消费/商业/人才日报")
        for token, slug, cn, dir_name in [
            ("setup_ccbd5295", "fin", "金融", "早鸟雷达-金融"),
            ("setup_63c56ee9", "consumer", "消费", "早鸟雷达-消费"),
            ("setup_d93a5b44", "biz", "商业", "早鸟雷达-商业"),
            ("setup_26010b88", "talent", "人才", "早鸟雷达-人才"),
        ]:
            d_base = root / "early_bird" / "热点资讯追踪" / dir_name
            run(GUIDE, ["init", "--setup-token", token, "--date", TEST_DAY], root)
            write_json(d_base / "raw_candidates.json", [])
            run(GUIDE, ["submit", "--setup-token", slug, "--step", "B1", "--date", TEST_DAY], root)
            write_json(d_base / "event_list.json", [])
            run(GUIDE, ["submit", "--setup-token", slug, "--step", "B2", "--date", TEST_DAY], root)
            (d_base / "daily").mkdir(parents=True, exist_ok=True)
            (d_base / "daily" / f"{TEST_DAY}.md").write_text(sample_report(cn, TEST_DAY, []), encoding="utf-8")
            write_json(d_base / "summary.json", sample_summary(cn, slug, token, []))
            code, out = run(GUIDE, ["submit", "--setup-token", slug, "--step", "B3", "--date", TEST_DAY], root)
            check(f"{cn} B3 通过", code == 0, f"code={code} out={str(out)[:200]}")
            code, out = run(GUIDE, ["submit", "--setup-token", slug, "--step", "B4", "--date", TEST_DAY], root)
            check(f"{cn} 终态完成", code == 0, f"code={code} out={str(out)[:200]}")

        # ---------------- 聚合 ----------------
        print("\n[12] aggregate.py snapshot")
        code, out = run(AGGREGATE, ["snapshot", "--date", TEST_DAY], root)
        check("snapshot 返回 0", code == 0, f"code={code} out={str(out)[:400]}")
        index_html = root / "early_bird" / "工作台" / "index.html"
        snapshot_html = root / "early_bird" / "工作台" / "daily" / f"{TEST_DAY}.html"
        check("index.html 已生成", index_html.exists(), str(index_html))
        check("每日快照已生成", snapshot_html.exists(), str(snapshot_html))
        if index_html.exists():
            text = index_html.read_text(encoding="utf-8")
            check("index 含 DOCTYPE", text.startswith("<!DOCTYPE html>"), text[:80])
            check("index 含六领域", all(name in text for name in ["科技", "医学", "金融", "消费", "商业", "人才"]), "")
            check("index 含事件标题", "开源大模型发布预览版权重" in text, "")
            check("index 含信源统计", "Tier-1" in text and "独立域名" in text, "")
            check("index 无未转义脚本", "<script" not in text, "")
            check("index 链接被转义", "&amp;" in text or "https://" in text, "")
        if isinstance(out, dict):
            totals = out.get("totals", {})
            check("聚合事件总数为 1", totals.get("event_count") == 1, str(totals))
            check("六领域均已出报", totals.get("reported_domains") == 6, str(totals))
            check("manifest 已写出", (root / "early_bird" / "工作台" / "manifest.json").exists(), "")

        # ---------------- 聚合容错：单领域产物损坏 ----------------
        print("\n[13] 单领域 summary 损坏时聚合容错并记录告警")
        before = index_html.read_text(encoding="utf-8") if index_html.exists() else ""
        # B4 已归档，该日的有效读取路径是归档副本 daily/<date>/summary.json
        archived_summary = base / "daily" / TEST_DAY / "summary.json"
        check("归档 summary 存在", archived_summary.exists(), str(archived_summary))
        good_summary_text = archived_summary.read_text(encoding="utf-8")
        archived_summary.write_text("{ not valid json", encoding="utf-8")
        log_file = root / "early_bird" / "aggregate.log"
        log_len_before = len(log_file.read_text(encoding="utf-8")) if log_file.exists() else 0
        code, out = run(AGGREGATE, ["snapshot", "--date", TEST_DAY], root)
        after = index_html.read_text(encoding="utf-8") if index_html.exists() else ""
        check("损坏 summary 时 snapshot 仍成功", code == 0, f"code={code} out={str(out)[:300]}")
        check("损坏 summary 后 index 内容未被清空", bool(after.strip()), f"len={len(after)}")
        tech_entry = next(
            (d for d in (out.get("domains", []) if isinstance(out, dict) else []) if d.get("domain_slug") == "tech"),
            {},
        )
        check("损坏领域被标记 issue", bool(tech_entry.get("issues")), str(tech_entry)[:400])
        check("issue 指向 summary 解析失败", any("summary.json" in str(i) for i in tech_entry.get("issues", [])), str(tech_entry)[:400])
        check("事件仍从 event_list 正常读出", tech_entry.get("event_count") == 1, str(tech_entry)[:300])
        check("信源统计回退为实算值", (tech_entry.get("source_stats") or {}).get("tier1_count") == 1, str(tech_entry)[:300])
        check("aggregate.log 已写入", log_file.exists(), str(log_file))
        if log_file.exists():
            log_text = log_file.read_text(encoding="utf-8")
            new_log = log_text[log_len_before:]
            check("日志记录了本次聚合", "snapshot" in new_log, new_log[-300:])
            check("有告警时日志级别为 WARN", "[WARN]" in new_log, new_log[-300:])
            check("告警数写入日志", "issues=1" in new_log or "issues=2" in new_log, new_log[-300:])
        # 恢复
        archived_summary.write_text(good_summary_text, encoding="utf-8")
        code, out = run(AGGREGATE, ["snapshot", "--date", TEST_DAY], root)
        check("恢复后 snapshot 成功", code == 0, f"code={code} out={str(out)[:300]}")
        check("恢复后事件总数回到 1", isinstance(out, dict) and out.get("totals", {}).get("event_count") == 1, str(out)[:300])
        check("恢复后 index 结构一致", index_html.read_text(encoding="utf-8")[:200] == before[:200], "")

        # ---------------- 聚合真正失败时保留旧结果 ----------------
        print("\n[13b] 聚合真正失败时保留旧 index.html 并写日志")
        good_index = index_html.read_text(encoding="utf-8")
        # 把 index.html 换成同名目录，强制原子写入失败
        index_html.unlink()
        index_html.mkdir(parents=True, exist_ok=True)
        sentinel = index_html / "sentinel.txt"
        sentinel.write_text("old", encoding="utf-8")
        log_file = root / "early_bird" / "aggregate.log"
        log_before = log_file.read_text(encoding="utf-8") if log_file.exists() else ""
        code, out = run(AGGREGATE, ["snapshot", "--date", TEST_DAY], root)
        check("写失败时 snapshot 返回非 0", code != 0, f"code={code} out={str(out)[:300]}")
        check("失败时报告 previous_index_kept", isinstance(out, dict) and out.get("previous_index_kept") is True, str(out)[:300])
        check("失败时旧 index 目录未被清空", sentinel.exists(), str(index_html))
        check("失败时指向 aggregate.log", isinstance(out, dict) and "aggregate.log" in str(out.get("log", "")), str(out)[:300])
        log_after = log_file.read_text(encoding="utf-8") if log_file.exists() else ""
        check("失败已写入 aggregate.log", len(log_after) > len(log_before) and "ERROR" in log_after[len(log_before):], log_after[-300:])
        check("失败时无残留 tmp 文件", not list((root / "early_bird" / "工作台").glob("index.html.tmp.*")), "")
        # 恢复为正常文件
        sentinel.unlink()
        index_html.rmdir()
        index_html.write_text(good_index, encoding="utf-8")
        code, out = run(AGGREGATE, ["snapshot", "--date", TEST_DAY], root)
        check("恢复后 snapshot 再次成功", code == 0, f"code={code} out={str(out)[:300]}")
        restored = index_html.read_text(encoding="utf-8")
        check("恢复后 index 结构与失败前一致", restored[:200] == good_index[:200], "")
        check("恢复后事件标题重新出现", "开源大模型发布预览版权重" in restored, "")

        # ---------------- status / domains ----------------
        print("\n[14] aggregate status 与 domains")
        code, out = run(AGGREGATE, ["status", "--date", TEST_DAY], root)
        check("status 返回 0", code == 0, f"code={code}")
        check("status 列出 6 领域", isinstance(out, dict) and len(out.get("domains", [])) == 6, str(out)[:200])
        code, out = run(AGGREGATE, ["domains"], root)
        check("domains 返回 0", code == 0, f"code={code}")
        check("domains 含最新日报日期", isinstance(out, dict) and all(d.get("latest_report_date") for d in out.get("domains", [])), str(out)[:300])

        # ---------------- 非法输入 ----------------
        print("\n[15] 非法输入处理")
        code, out = run(GUIDE, ["init", "--setup-token", "setup_not_exist", "--date", TEST_DAY], root)
        check("未知 token 返回非 0", code != 0, f"code={code}")
        check("未知 token 给出可选列表", isinstance(out, dict) and len(out.get("available", [])) == 6, str(out)[:200])
        code, out = run(GUIDE, ["init", "--setup-token", "tech", "--date", "2026-13-45"], root)
        check("非法日期被拒绝", code != 0, f"code={code}")
        code, out = run(GUIDE, ["status", "--setup-token", "biz", "--date", "2020-01-01"], root)
        check("未初始化日期返回 not_initialized", code == 0 and isinstance(out, dict) and out.get("status") == "not_initialized", str(out)[:200])

    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n" + "=" * 70)
    print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        print("\n失败明细：")
        for item in FAILED:
            print(f"  - {item}")
        return 1
    print("全部自检通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
