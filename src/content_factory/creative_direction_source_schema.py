"""Expose existing source-path and timing relations in a direction tool schema.

This pure adapter adds no model dispatch and never changes submitted content.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


def constrain_direction_sources(
    schema: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Constrain ordered beats to their source paths, without changing inputs."""
    result = deepcopy(schema)
    beats_schema = result["properties"]["beats"]
    script_beats = context["script"]["beats"]
    if not script_beats:
        raise ValueError("direction context must contain at least one beat")
    prefix = beats_schema.get("prefixItems")
    prototype = beats_schema.get("items")
    if prefix is not None:
        if not isinstance(prefix, list) or len(prefix) != len(script_beats):
            raise ValueError("direction prefix must match complete context beat coverage")
        if not all(isinstance(unit, dict) for unit in prefix):
            raise ValueError("direction prefix items must be beat schemas")
    elif not isinstance(prototype, dict):
        raise ValueError("direction schema must provide a common beat item schema")
    ordered_items = []
    for index, source_beat in enumerate(script_beats):
        unit = deepcopy(prefix[index] if prefix is not None else prototype)
        unit["properties"]["beat_id"] = {"const": source_beat["id"]}
        requirement = unit["properties"]["performance_requirements"]["items"]
        event_path = f"script.beats.{index}.event"
        dialogue_paths = [
            f"script.beats.{index}.dialogue.{dialogue_index}.text"
            for dialogue_index in range(len(source_beat["dialogue"]))
        ]
        requirement["properties"]["stimulus_source"] = {
            "type": "string", "enum": [event_path, *dialogue_paths]
        }
        requirement["properties"]["relation"] = {
            "enum": ["before", "during", "after"]
        }
        # An event is an indivisible action in the current compiler. Dialogue
        # alone can supply a 'during' window; do not imply unsupported parallelism.
        event_relation = {
            "if": {
                "properties": {"stimulus_source": {"const": event_path}},
                "required": ["stimulus_source"],
            },
            "then": {
                "properties": {"relation": {"enum": ["before", "after"]}},
            },
        }
        conditions = requirement.setdefault("allOf", [])
        if event_relation not in conditions:
            conditions.append(event_relation)
        ordered_items.append(unit)
    beats_schema["prefixItems"] = ordered_items
    beats_schema["items"] = False
    beats_schema["minItems"] = len(script_beats)
    beats_schema["maxItems"] = len(script_beats)
    return result