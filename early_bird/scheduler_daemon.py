#!/usr/bin/env python3
"""早鸟工作台调度守护进程入口。

独立于模板服务运行，保证自动化链路在模板进程未重启（旧代码无调度循环）时
也能立即生效。与模板服务内的调度循环通过文件锁互斥：

  - 先抢到 early_bird/scheduler.lock 的实例运行，另一个待命；
  - 持有者崩溃或退出时内核释放锁，待命方在下一个 tick 自动接管。

启动：
  setsid nohup python early_bird/scheduler_daemon.py >> early_bird/daemon.out 2>&1 &

停止：
  kill $(cat early_bird/scheduler.lock)
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.early_bird_scheduler import (  # noqa: E402
    acquire_scheduler_lock,
    scheduler_loop,
)
from src.early_bird_scheduler import _log  # noqa: E402


def main() -> int:
    if not acquire_scheduler_lock():
        print("另一个调度实例已持有锁，本进程退出。", flush=True)
        return 0

    _log(f"daemon started pid={os.getpid()}")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _shutdown(signum, _frame) -> None:  # noqa: ANN001
        _log(f"daemon received signal {signum}, shutting down")
        for task in asyncio.all_tasks(loop):
            task.cancel()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        loop.run_until_complete(scheduler_loop())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        _log(f"daemon stopped pid={os.getpid()}")
        loop.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
