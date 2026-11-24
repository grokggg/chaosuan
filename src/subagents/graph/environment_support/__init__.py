from __future__ import annotations

from typing import Any

from src.subagents.graph.environment_support.graph import build_environment_support_graph


def load_graph_subagents() -> list[dict[str, Any]]:
    return [
        {
            "name": "environment-support",
            "description": (
                "仅判断生物信息学和材料科学论文或工作流所需软件、包、数据库和运行时"
                "是否被当前共享存储环境支持；先识别领域，只读取对应领域的环境依赖说明，"
                "并返回支持的软件列表与路径。不支持工业仿真或其他领域。"
                "注意，该子智能体只判断共享存储/public/software中的环境支持性。"
            ),
            "runnable": build_environment_support_graph(),
        }
    ]


__all__ = ["load_graph_subagents"]
