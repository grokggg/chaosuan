#!/usr/bin/env python3
"""早鸟工作台调度看门狗。

职责单一：每 60 秒尝试获取 early_bird/scheduler.lock。
  - 能获取到锁 => 当前没有任何调度实例在运行（守护进程已崩溃或从未启动），
    释放锁并拉起 scheduler_daemon.py；
  - 获取不到锁 => 有实例在正常工作，什么都不做。

不依赖 PID 文件，靠内核 flock 语义判断存活，避免 PID 复用误判。

启动：
  setsid nohup python early_bird/scheduler_watchdog.py >> early_bird/watchdog.out 2>&1 &

停止：
  kill $(cat early_bird/watchdog.lock)
"""

from __future__ import annotations

import fcntl
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EARLY_BIRD_DIR = PROJECT_ROOT / "early_bird"
LOCK_PATH = EARLY_BIRD_DIR / "scheduler.lock"
WATCHDOG_LOCK = EARLY_BIRD_DIR / "watchdog.lock"
DAEMON_SCRIPT = EARLY_BIRD_DIR / "scheduler_daemon.py"
DAEMON_OUT = EARLY_BIRD_DIR / "daemon.out"
WATCHDOG_LOG = EARLY_BIRD_DIR / "watchdog.log"

CHECK_INTERVAL_SECONDS = 60
COOLDOWN_SECONDS = 120  # 拉起后冷却，避免崩溃循环


def _log(message: str) -> None:
    try:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with WATCHDOG_LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {message}\n")
    except OSError:
        pass
    print(message, flush=True)


def _scheduler_alive() -> bool:
    """尝试非阻塞加锁：加锁成功说明没有调度实例存活。"""
    try:
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_RDWR, 0o644)
    except OSError:
        return True  # 无法判断时保守认为存活，避免误拉起
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return True  # 锁被持有 => 有实例在运行
    # 加锁成功 => 无实例存活；立即释放
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
    return False


def _spawn_daemon() -> None:
    with DAEMON_OUT.open("ab") as out:
        subprocess.Popen(
            [sys.executable, str(DAEMON_SCRIPT)],
            cwd=str(PROJECT_ROOT),
            stdout=out,
            stderr=out,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    _log("watchdog spawned scheduler_daemon.py")


def main() -> int:
    # 看门狗自身单实例
    try:
        fd = os.open(str(WATCHDOG_LOCK), os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode("utf-8"))
    except OSError:
        print("另一个看门狗已在运行，本进程退出。", flush=True)
        return 0

    _log(f"watchdog started pid={os.getpid()} interval={CHECK_INTERVAL_SECONDS}s")
    last_spawn = 0.0
    while True:
        time.sleep(CHECK_INTERVAL_SECONDS)
        try:
            if _scheduler_alive():
                continue
            now = time.monotonic()
            if now - last_spawn < COOLDOWN_SECONDS:
                continue
            _log("no scheduler instance holds the lock; restarting daemon")
            _spawn_daemon()
            last_spawn = now
        except Exception as exc:  # noqa: BLE001
            _log(f"watchdog tick error: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
