#!/usr/bin/env python3
"""早鸟工作台推送模块自检：摘要构建、收件箱、失败入队与重试上限。

用法：python early_bird/selftest_notify.py
所有产物写入临时目录（EARLY_BIRD_ROOT 重定向），凭据使用假值，不触碰真实邮箱。
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
NOTIFY = SCRIPT_DIR / "notify.py"

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


def run(argv: list[str], root: Path) -> tuple[int, dict | str]:
    env = dict(os.environ)
    env["EARLY_BIRD_ROOT"] = str(root)
    # 假凭据：保证不会真的发信
    env["QQ_EMAIL_FROM"] = "fake@qq.com"
    env["QQ_EMAIL_AUTH_CODE"] = "fake-code"
    env["QQ_EMAIL_TO"] = "fake@qq.com"
    completed = subprocess.run(
        [sys.executable, str(NOTIFY), *argv],
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


def make_fixtures(root: Path) -> None:
    """造一个科技有事件、其余五领域空结果的当日产物。"""
    sys.path.insert(0, str(SCRIPT_DIR))
    import common  # noqa: PLC0415

    os.environ["EARLY_BIRD_ROOT"] = str(root)
    contract = common.load_contract()
    for domain in contract["domains"]:
        base = root / "early_bird" / "热点资讯追踪" / domain["name_cn"]
        (base / "daily").mkdir(parents=True, exist_ok=True)
        slug = domain["domain_slug"]
        if slug == "tech":
            events = [
                {
                    "event_id": "tech-20261107-01",
                    "title": "开源大模型发布预览版权重",
                    "signal_type": "开源生态节点",
                    "happened_at": TEST_DAY,
                    "summary": "开源模型团队放出新一代预览版权重，推理成本下探到新档位。",
                    "why_early_signal": "成本档位下移会改变中小团队选型边界。",
                    "impact": "可能压低同档位闭源 API 定价空间。",
                    "confidence": "high",
                    "sources": [
                        {
                            "url": "https://huggingface.co/blog/x",
                            "domain": "huggingface.co",
                            "publisher": "Hugging Face",
                            "tier": "tier1",
                            "published_at": TEST_DAY,
                            "quote": "预览版权重已开放下载。",
                        },
                        {
                            "url": "https://www.jiqizhixin.com/a",
                            "domain": "jiqizhixin.com",
                            "publisher": "机器之心",
                            "tier": "tier2",
                            "published_at": TEST_DAY,
                            "quote": "多家媒体跟进报道。",
                        },
                        {
                            "url": "https://techcrunch.com/b",
                            "domain": "techcrunch.com",
                            "publisher": "TechCrunch",
                            "tier": "tier2",
                            "published_at": TEST_DAY,
                            "quote": "正式版发布时间未定。",
                        },
                    ],
                }
            ]
        else:
            events = []
        (base / "event_list.json").write_text(json.dumps(events, ensure_ascii=False), encoding="utf-8")
        (base / "daily" / f"{TEST_DAY}.md").write_text(
            f"# 早鸟雷达-{domain['domain']} · {TEST_DAY}\n\n"
            + ("今日共 1 条合格早期信号。" if events else "今日无满足 high 信源要求的合格早期信号。\n"),
            encoding="utf-8",
        )
        domains_seen = {s["domain"] for e in events for s in e["sources"]}
        summary = {
            "date": TEST_DAY,
            "domain": domain["domain"],
            "domain_slug": slug,
            "setup_token": domain["setup_token"],
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
                "independent_domain_count": len(domains_seen),
            },
            "generated_at": f"{TEST_DAY}T08:10:00+08:00",
        }
        (base / "summary.json").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
        state = {
            "date": TEST_DAY,
            "status": "DONE" if events else "EMPTY_SILENT",
            "setup_token": domain["setup_token"],
        }
        (base / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="early_bird_notify_selftest_"))
    print(f"临时工作目录: {root}\n")
    try:
        make_fixtures(root)

        print("[1] status：配置读取与脱敏")
        code, out = run(["status"], root)
        check("status 返回 0", code == 0, f"code={code} out={str(out)[:200]}")
        if isinstance(out, dict):
            check("发件人已配置", out.get("sender_configured") is True, str(out)[:200])
            check("授权码已配置", out.get("auth_code_configured") is True, str(out)[:200])
            check("收件人非空", bool(out.get("recipients")), str(out)[:200])
            check("输出不含授权码明文", "fake-code" not in json.dumps(out, ensure_ascii=False), str(out)[:300])
            check("默认 mode=concise", out.get("mode") == "concise", str(out)[:200])

        print("\n[2] digest：只构建不发送")
        code, out = run(["digest", "--date", TEST_DAY], root)
        check("digest 返回 0", code == 0, f"code={code} out={str(out)[:300]}")
        if isinstance(out, dict):
            check("状态为 built", out.get("status") == "built", str(out)[:200])
            check("should_push 为 true", out.get("should_push") is True, str(out)[:200])
            check("事件总数为 1", out.get("totals", {}).get("event_count") == 1, str(out)[:300])
            check("出报领域 6/6", out.get("totals", {}).get("reported_domains") == 6, str(out)[:300])
            preview = out.get("text_preview", "")
            check("摘要含科技事件标题", "开源大模型发布预览版权重" in preview, preview[:300])
            check("摘要含空结果领域说明", "今日无满足 high 信源要求的合格早期信号" in preview, preview[:300])
            check("摘要含信源门槛说明", "Tier-1" in preview and "独立域名" in preview, preview[:300])
            inbox_latest = root / "early_bird" / "工作台" / "inbox" / "latest.json"
            check("收件箱 latest 已写入", inbox_latest.exists(), str(inbox_latest))
            inbox_day = root / "early_bird" / "工作台" / "inbox" / f"{TEST_DAY}.json"
            check("收件箱当日记录已写入", inbox_day.exists(), str(inbox_day))

        print("\n[3] digest --send：发送失败入队")
        code, out = run(["digest", "--date", TEST_DAY, "--send"], root)
        check("send 返回 0（失败不抛异常）", code == 0, f"code={code} out={str(out)[:300]}")
        if isinstance(out, dict):
            check("状态为 queued", out.get("status") == "queued", str(out)[:300])
            check("错误提示网络或凭据", bool(out.get("error")), str(out)[:300])
            check("返回 queue_id", bool(out.get("queue_id")), str(out)[:300])
            check("返回下次重试时间", bool(out.get("next_retry_at")), str(out)[:300])
            queue_path = root / "early_bird" / "push_queue.json"
            check("队列文件已写入", queue_path.exists(), str(queue_path))
            if queue_path.exists():
                queue = json.loads(queue_path.read_text(encoding="utf-8"))
                check("队列含 1 条", len(queue) == 1, str(queue)[:200])
                check("队列记录含正文", bool(queue[0].get("text")) and bool(queue[0].get("html")), str(queue)[:200])
                check("队列不含授权码", "fake-code" not in json.dumps(queue, ensure_ascii=False), "")

        print("\n[4] retry：未到间隔不重试")
        code, out = run(["retry"], root)
        check("retry 返回 0", code == 0, f"code={code}")
        if isinstance(out, dict):
            check("无重试结果（未到间隔）", out.get("results") == [], str(out)[:200])
            check("队列仍为 1 条", out.get("queue_size") == 1, str(out)[:200])

        print("\n[5] retry --force：达到上限标记 exhausted")
        # 把 max_retries 压到 0，强制重试一次即耗尽
        env_root = root
        code, out = run(["retry", "--force"], env_root)
        check("force retry 返回 0", code == 0, f"code={code}")
        # 默认 max_retries=8，attempts=1 不会耗尽；再跑多次直到耗尽太慢，改为直接改队列验证逻辑
        queue_path = root / "early_bird" / "push_queue.json"
        queue = json.loads(queue_path.read_text(encoding="utf-8"))
        queue[0]["attempts"] = 8
        queue[0]["next_retry_at"] = "2000-01-01T00:00:00"
        queue_path.write_text(json.dumps(queue, ensure_ascii=False), encoding="utf-8")
        code, out = run(["retry"], root)
        check("超上限 retry 返回 0", code == 0, f"code={code}")
        if isinstance(out, dict):
            results = out.get("results", [])
            check("标记 exhausted", any(r.get("status") == "exhausted" for r in results), str(results)[:300])
            check("exhausted 后队列保留记录", out.get("queue_size") == 1, str(out)[:200])

        print("\n[6] 空结果策略")
        # 造一个全空日
        empty_day = "2026-11-06"
        make_empty_day(root, empty_day)
        code, out = run(["digest", "--date", empty_day], root)
        check("全空日 digest 返回 0", code == 0, f"code={code}")
        if isinstance(out, dict):
            check("per_domain 策略下仍应推送", out.get("should_push") is True, str(out)[:300])
            check("主题含无合格信号", "无合格早期信号" in out.get("subject", ""), str(out)[:300])
        # silent 策略
        env = dict(os.environ)
        env["EARLY_BIRD_ROOT"] = str(root)
        env["EARLY_BIRD_PUSH_EMPTY"] = "silent"
        completed = subprocess.run(
            [sys.executable, str(NOTIFY), "digest", "--date", empty_day],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True, env=env, timeout=120, check=False,
        )
        silent_out = json.loads(completed.stdout.strip())
        check("silent 策略下不推送", silent_out.get("should_push") is False, str(silent_out)[:300])
        check("silent 给出跳过原因", bool(silent_out.get("skip_reason")), str(silent_out)[:300])

        print("\n[7] 路由与调度器可导入")
        completed = subprocess.run(
            [sys.executable, "-c", "import src.api.routes.early_bird as m; print(sorted(r.path for r in m.router.routes))"],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=120, check=False,
        )
        check("路由模块可导入", completed.returncode == 0, completed.stderr[-400:])
        check("含 /status 路由", "/user/agent/early-bird/status" in completed.stdout, completed.stdout[:300])
        check("含 /run 路由", "/user/agent/early-bird/run" in completed.stdout, completed.stdout[:300])
        check("含 /push 路由", "/user/agent/early-bird/push" in completed.stdout, completed.stdout[:300])
        check("含 /inbox 路由", "/user/agent/early-bird/inbox" in completed.stdout, completed.stdout[:300])
        completed = subprocess.run(
            [sys.executable, "-c", "import src.early_bird_scheduler as s; print(s._chain_slug([], '聚合'), s._chain_slug([], '科技'))"],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=120, check=False,
        )
        check("调度器模块可导入", completed.returncode == 0, completed.stderr[-400:])
        check("链条名映射正确", completed.stdout.strip() == "aggregate tech", completed.stdout[:100])

    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n" + "=" * 70)
    print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        print("\n失败明细：")
        for item in FAILED:
            print(f"  - {item}")
        return 1
    print("推送模块自检全部通过。")
    return 0


def make_empty_day(root: Path, day: str) -> None:
    sys.path.insert(0, str(SCRIPT_DIR))
    import common  # noqa: PLC0415

    os.environ["EARLY_BIRD_ROOT"] = str(root)
    contract = common.load_contract()
    for domain in contract["domains"]:
        base = root / "early_bird" / "热点资讯追踪" / domain["name_cn"]
        (base / "daily").mkdir(parents=True, exist_ok=True)
        (base / "event_list.json").write_text("[]", encoding="utf-8")
        (base / "daily" / f"{day}.md").write_text(
            f"# 早鸟雷达-{domain['domain']} · {day}\n\n今日无满足 high 信源要求的合格早期信号。\n",
            encoding="utf-8",
        )
        summary = {
            "date": day,
            "domain": domain["domain"],
            "domain_slug": domain["domain_slug"],
            "setup_token": domain["setup_token"],
            "event_count": 0,
            "empty": True,
            "top_events": [],
            "source_stats": {"tier1_count": 0, "tier2_count": 0, "independent_domain_count": 0},
            "generated_at": f"{day}T08:10:00+08:00",
        }
        (base / "summary.json").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
        state = {"date": day, "status": "EMPTY_SILENT", "setup_token": domain["setup_token"]}
        (base / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
