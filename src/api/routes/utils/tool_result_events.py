from __future__ import annotations

from typing import Any

from src.api.routes.utils.payload import parse_json_payload
from src.middleware.tool_handoff_middleware import (
    extract_job_monitor_data,
    extract_job_terminal_data,
)


def extract_job_monitor_event(
    *,
    conversation_id: str,
    tool_result: Any,
    tool_record: dict[str, Any] | None,
    task_id: str | None = None,
) -> dict[str, Any] | None:
    result_payload = parse_json_payload(tool_result)
    if not isinstance(result_payload, dict):
        return None

    data = extract_job_monitor_data(result_payload)
    if data is None:
        return None

    job_id = data.get("jobId") or data.get("job_id")
    cluster_id = data.get("clusterId") or data.get("cluster_id")

    arguments = tool_record.get("arguments") if tool_record else None
    parsed_arguments = parse_json_payload(arguments) if isinstance(arguments, str) else None
    if isinstance(parsed_arguments, dict):
        cluster_id = cluster_id or parsed_arguments.get("clusterId") or parsed_arguments.get("cluster_id")
        job_id = job_id or parsed_arguments.get("jobId") or parsed_arguments.get("job_id")

    command = parsed_arguments.get("command") if isinstance(parsed_arguments, dict) else None
    if isinstance(command, str):
        cluster_id = cluster_id or extract_cli_option(command, "cluster-id")
        job_id = job_id or extract_cli_option(command, "job-id")

    if not cluster_id or not job_id:
        return None

    return {
        "type": "job-monitor",
        "conversationId": conversation_id,
        "clusterId": str(cluster_id),
        "jobId": str(job_id),
        "taskId": task_id,
        "enable": True,
    }


def extract_job_terminal_notice(
    *,
    conversation_id: str,
    tool_result: Any,
    tool_record: dict[str, Any] | None,
) -> dict[str, Any] | None:
    result_payload = parse_json_payload(tool_result)
    if not isinstance(result_payload, dict):
        return None

    data = extract_job_terminal_data(result_payload)
    if data is None:
        return None

    job_id = data.get("jobId") or data.get("job_id")
    cluster_id = data.get("clusterId") or data.get("cluster_id")

    arguments = tool_record.get("arguments") if tool_record else None
    parsed_arguments = parse_json_payload(arguments) if isinstance(arguments, str) else arguments
    if isinstance(parsed_arguments, dict):
        cluster_id = cluster_id or parsed_arguments.get("clusterId") or parsed_arguments.get("cluster_id")
        job_id = job_id or parsed_arguments.get("jobId") or parsed_arguments.get("job_id")

    command = parsed_arguments.get("command") if isinstance(parsed_arguments, dict) else None
    if isinstance(command, str):
        cluster_id = cluster_id or extract_cli_option(command, "cluster-id")
        job_id = job_id or extract_cli_option(command, "job-id")

    if not cluster_id or not job_id:
        return None

    return {
        "type": "job-terminal-notice",
        "conversationId": conversation_id,
        "clusterId": str(cluster_id),
        "jobId": str(job_id),
    }


def extract_cli_option(command: str, name: str) -> str | None:
    parts = command.split()
    flag = f"--{name}"
    for index, part in enumerate(parts[:-1]):
        if part == flag:
            return parts[index + 1].strip("\"'")
    return None


__all__ = [
    "extract_cli_option",
    "extract_job_monitor_event",
    "extract_job_terminal_notice",
]
