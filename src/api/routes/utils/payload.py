from __future__ import annotations

import json
from typing import Any


def parse_json_payload(value: Any) -> Any:
    if not isinstance(value, str):
        return value

    decoder = json.JSONDecoder()
    stripped = value.strip()
    if not stripped:
        return value
    try:
        payload, _ = decoder.raw_decode(stripped)
        return payload
    except json.JSONDecodeError:
        pass

    for index, char in enumerate(stripped):
        if char != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(stripped[index:])
            return payload
        except json.JSONDecodeError:
            continue
    return value


def parse_json_payload_or_none(value: Any) -> Any:
    payload = parse_json_payload(value)
    return payload if payload is not value else None


__all__ = ["parse_json_payload", "parse_json_payload_or_none"]
