"""Scientific job-monitor tools."""

from __future__ import annotations

import json
from typing import Annotated

from langchain.tools import tool


@tool(
    "trigger_job_monitor",
    description=(
        "Slurm job monitoring must use either the scnet-job-manager skill or this trigger_job_monitor tool; these are the only "
        "permitted monitoring mechanisms. If scnet-job-manager reports any monitor job error, "
        "invalid monitor state, timeout, connection issue, or other monitoring failure, call "
        "this tool with the known cluster_id and job_id. Do not use sacct, squeue, or similar "
        "scheduler commands for monitoring or for diagnosing the monitoring failure before "
        "calling this tool. This triggers asynchronous job monitoring, stops the "
        "current agent response, and waits for asynchronous job completion feedback."
    ),
)
async def trigger_job_monitor(
    cluster_id: Annotated[
        str,
        "Cluster id of the Slurm job to monitor.",
    ],
    job_id: Annotated[
        str,
        "Job id of the Slurm job to monitor.",
    ],
) -> str:
    """Start asynchronous monitoring for a Slurm job."""

    return json.dumps(
        {
            "success": True,
            "message": "Async job monitoring has started. Wait for the job completion feedback message.",
            "data": {
                "clusterId": cluster_id,
                "jobId": job_id,
                "asyncMonitor": True,
                "terminal": False,
                "agentAction": "stop_response",
                "agentInstruction": (
                    "End the current response after asynchronous job monitoring starts, then "
                    "wait for the job completion feedback before continuing."
                ),
            },
        },
        ensure_ascii=False,
    )


__all__ = ["trigger_job_monitor"]
