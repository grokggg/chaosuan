"""Deferred cards for recommended SCNet computing resources."""

from __future__ import annotations

import json
from typing import Annotated

from langchain.tools import tool
from pydantic import BaseModel, Field

from src.tools.deferred import deferred


class Resources(BaseModel):
    """A recommended computing resource returned by scnet-job-manager."""

    name: str = Field(description=("Resource name."))
    id: str = Field(description=("Resource goods ID."))
    processor: str = Field(description=("Processor specification."))
    memory: str = Field(description=("Memory specification."))
    price: str = Field(description=("Formatted resource price."))
    url: str = Field(description=("Resource detail URL."))
    description: str = Field(
        description=(
            "Generate an easy-to-read description based on the specifications and recommended software, rather than simply repeating the parameters."
        )
    )


@deferred("recommand_resource_card")
@tool(
    "show_recommand_resource_cards",
    description=(
        "After the scnet-job-manager Skill retrieves recommended SCNet resources, show the recommended "
        "resources and a link for the user to browse more resources."
    ),
)
async def show_recommand_resource_cards(
    resources: Annotated[
        list[Resources],
        ("Recommended resources returned by scnet-job-manager, preserving their original order."),
    ],
    searchUrl: Annotated[
        str,
        ("SCNet search URL used to browse more computing resources."),
    ],
) -> str:
    """Return recommended-resource cards for UI rendering."""

    options = [
        {
            "value": "",
            "label": {
                "name": resource.name,
                "processor": resource.processor,
                "memory": resource.memory,
                "price": resource.price,
                "url": resource.url,
            },
            "selected": False,
            "description": resource.description,
            "type": "queue",
            "id": resource.id,
        }
        for resource in resources
    ]
    options.append(
        {
            "value": "",
            "label": {"url": searchUrl},
            "selected": False,
            "description": "查看更多资源",
            "type": "url",
            "id": "",
        }
    )

    return json.dumps(
        {
            "type": "resource_card",
            "title": "请访问推荐的计算资源",
            "description": "请从推荐的计算资源中选择开通，在完成后继续计算流程",
            "optionType": "link",
            "showUserMessage": False,
            "enable": True,
            "confirm": {"content": "已完成资源开通，继续执行计算流程"},
            "options": options,
        },
        ensure_ascii=False,
    )


__all__ = ["Resources", "show_recommand_resource_cards"]
