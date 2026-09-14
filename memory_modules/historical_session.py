from __future__ import annotations

import json
import uuid
from typing import Any


MAX_OBSERVATION_TEXT_CHARS = 300_000
MAX_SINGLE_OBSERVATION_CHARS = 16_000


def _observation_content(state: dict[str, Any], text: str, state_index: int) -> str:
    return json.dumps(
        {
            "state_index": state.get("state_index", state_index),
            "url": state.get("url"),
            "accessibility_tree": text,
            "screenshot_reference": state.get("screenshot"),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def build_historical_session_payload(trajectory: dict[str, Any]) -> dict[str, Any]:
    """Convert one LongMemEval trajectory to a paired typed transcript."""
    trajectory_id = str(trajectory["id"])
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [{"type": "text", "text": str(trajectory["goal"])}],
        }
    ]
    states = trajectory["states"]
    if not isinstance(states, list) or not states:
        raise ValueError(f"Trajectory {trajectory_id} has no states")
    per_state_budget = min(
        MAX_SINGLE_OBSERVATION_CHARS,
        max(2_000, MAX_OBSERVATION_TEXT_CHARS // len(states)),
    )
    truncated_state_count = 0
    observations: list[str] = []
    for state_index, state in enumerate(states):
        text = str(state["accessibility_tree"])
        if len(text) > per_state_budget:
            head_chars = int(per_state_budget * 0.7)
            tail_chars = per_state_budget - head_chars
            text = (
                text[:head_chars]
                + "\n...[deterministically truncated by historical-session importer]...\n"
                + text[-tail_chars:]
            )
            truncated_state_count += 1
        observations.append(_observation_content(state, text, state_index))

    tool_index = 0

    def append_tool_exchange(name: str, tool_input: dict[str, Any], result: str) -> None:
        nonlocal tool_index
        tool_use_id = f"longmemeval_{trajectory_id}_{tool_index:04d}"
        tool_index += 1
        messages.append(
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": tool_use_id,
                        "name": name,
                        "input": tool_input,
                    }
                ],
            }
        )
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": result,
                    }
                ],
            }
        )

    first_state_index = states[0].get("state_index", 0)
    append_tool_exchange(
        "browser_observe",
        {"state_index": first_state_index},
        observations[0],
    )
    for state_offset, state in enumerate(states):
        action = state.get("action")
        state_index = state.get("state_index", state_offset)
        if action:
            result = (
                observations[state_offset + 1]
                if state_offset + 1 < len(states)
                else json.dumps(
                    {"outcome": trajectory.get("outcome")},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
            append_tool_exchange(
                "browser_action",
                {"state_index": state_index, "action": str(action)},
                result,
            )
        elif state_offset + 1 < len(states):
            next_state = states[state_offset + 1]
            append_tool_exchange(
                "browser_observe",
                {"state_index": next_state.get("state_index", state_offset + 1)},
                observations[state_offset + 1],
            )

    return {
        "schema": "longmemeval.historical-session.v1",
        "session_id": str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"longmemeval:{trajectory_id}")
        ),
        "trajectory_id": trajectory_id,
        "normalization": {
            "observation_text_budget_chars": MAX_OBSERVATION_TEXT_CHARS,
            "per_state_budget_chars": per_state_budget,
            "truncated_state_count": truncated_state_count,
            "thoughts_included": False,
        },
        "outcome": trajectory.get("outcome"),
        "messages": messages,
    }
