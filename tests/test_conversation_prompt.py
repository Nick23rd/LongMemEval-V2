from __future__ import annotations

import pytest

from memory_modules.conversation_prompt import build_conversation_prompt


def test_conversation_prompt_builds_black_box_historical_input() -> None:
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
                "thought": "Do not include private chain of thought.",
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

    prompt = build_conversation_prompt(trajectory)

    assert "This is a completed historical browser work session." in prompt
    assert "Goal:\nFind the customer toolbar action." in prompt
    assert "Observation 0:" in prompt
    assert "URL: https://example.test/customers" in prompt
    assert "Screenshot reference: screens/0.png" in prompt
    assert "Customers page" in prompt
    assert "Action 0:\nclick customer Alice" in prompt
    assert "Observation 1:" in prompt
    assert "Toolbar: Login as Customer" in prompt
    assert "Outcome:\n\"success\"" in prompt
    assert "thoughts_included=false" in prompt
    assert "Do not include private chain of thought." not in prompt
    assert build_conversation_prompt(trajectory) == prompt


def test_conversation_prompt_rejects_empty_states() -> None:
    with pytest.raises(ValueError, match="has no states"):
        build_conversation_prompt(
            {
                "id": "trajectory-empty",
                "goal": "Observe.",
                "outcome": "success",
                "states": [],
            }
        )


def test_conversation_prompt_truncates_long_observations_deterministically() -> None:
    trajectory = {
        "id": "trajectory-long",
        "goal": "Observe the page.",
        "outcome": "success",
        "states": [
            {
                "state_index": 0,
                "url": "https://example.test/",
                "accessibility_tree": "A" * 20_000 + "MIDDLE" + "Z" * 20_000,
                "screenshot": "screens/0.png",
                "action": None,
            }
        ],
    }

    prompt = build_conversation_prompt(trajectory)

    assert "deterministically truncated by conversation-prompt importer" in prompt
    assert "truncated_state_count=1" in prompt
    assert "MIDDLE" not in prompt
    assert prompt == build_conversation_prompt(trajectory)
