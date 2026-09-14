from __future__ import annotations

import json

from memory_modules.historical_session import build_historical_session_payload


def test_normalize_trajectory_builds_paired_internal_message_transcript() -> None:
    trajectory = {
        "id": "trajectory-1",
        "goal": "Find the customer toolbar action.",
        "outcome": "success",
        "states": [
            {
                "state_index": 0,
                "url": "https://example.test/customers",
                "accessibility_tree": "Customers page",
                "screenshot": "screens/0.png",
                "action": "click customer Alice",
            },
            {
                "state_index": 1,
                "url": "https://example.test/customers/alice",
                "accessibility_tree": "Toolbar: Login as Customer",
                "screenshot": "screens/1.png",
                "action": None,
            },
        ],
    }

    payload = build_historical_session_payload(trajectory)

    assert payload["schema"] == "longmemeval.historical-session.v1"
    assert payload["trajectory_id"] == "trajectory-1"
    assert payload["messages"][0] == {
        "role": "user",
        "content": [{"type": "text", "text": trajectory["goal"]}],
    }
    assert [message["role"] for message in payload["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
    ]

    observed_tool_ids: set[str] = set()
    for message in payload["messages"]:
        for block in message["content"]:
            if block["type"] == "tool_use":
                observed_tool_ids.add(block["id"])
            if block["type"] == "tool_result":
                assert block["tool_use_id"] in observed_tool_ids
                observed_tool_ids.remove(block["tool_use_id"])
    assert observed_tool_ids == set()

    final_observation = json.loads(payload["messages"][-1]["content"][0]["content"])
    assert final_observation["state_index"] == 1
    assert final_observation["accessibility_tree"] == "Toolbar: Login as Customer"


def test_normalize_trajectory_session_id_and_payload_are_deterministic() -> None:
    trajectory = {
        "id": "trajectory-2",
        "goal": "Observe the page.",
        "outcome": "success",
        "states": [
            {
                "state_index": 0,
                "url": "https://example.test/",
                "accessibility_tree": "Home",
                "screenshot": "screens/0.png",
                "action": None,
            }
        ],
    }

    assert build_historical_session_payload(trajectory) == build_historical_session_payload(
        trajectory
    )
