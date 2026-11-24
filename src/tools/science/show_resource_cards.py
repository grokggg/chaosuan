"""Scientific resource-card selection tools."""

from __future__ import annotations

import json
from typing import Annotated
from uuid import uuid4

from langchain.tools import tool
from pydantic import BaseModel, Field


class QueueCardInput(BaseModel):
    name: str = Field(description=("Queue name to show to the user."))
    description: str = Field(
        description=(
            "Write a concise, clear description of the current queue based on the available queue information."
        )
    )


@tool(
    "show_resource_cards",
    description=(
        "Show queue selection cards to the user after queue information has been retrieved. "
        "Pass every queue from the search results, preserving each queue name and the full "
        "Markdown-formatted queue description."
    ),
)
async def show_resource_cards(
    queues: Annotated[
        list[QueueCardInput],
        ("All retrieved queues. Each item must include name and a well-formatted Markdown description."),
    ],
) -> str:
    """Return queue cards for single-selection UI rendering."""

    options = [
        {
            "value": queue.name,
            "label": {"name": queue.name},
            "selected": False,
            "description": queue.description,
            "type": "queue",
            "id": uuid4().hex[:4],
        }
        for queue in queues
    ]
    return json.dumps(
        {
            "type": "resource_card",
            "optionType": "single",
            "showUserMessage": False,
            "enable": True,
            "options": options,
        },
        ensure_ascii=False,
    )


__all__ = ["QueueCardInput", "show_resource_cards"]
