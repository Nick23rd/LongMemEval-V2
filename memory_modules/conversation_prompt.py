from __future__ import annotations

import json
from typing import Any


MAX_OBSERVATION_TEXT_CHARS = 300_000
MAX_SINGLE_OBSERVATION_CHARS = 16_000


def _truncate_observation(text: str, budget: int) -> tuple[str, bool]:
    if len(text) <= budget:
        return text, False
    head_chars = int(budget * 0.7)
    tail_chars = budget - head_chars
    return (
        text[:head_chars]
        + "\n...[deterministically truncated by conversation-prompt importer]...\n"
        + text[-tail_chars:],
        True,
    )


def build_conversation_prompt(trajectory: dict[str, Any]) -> str:
    """Convert one LongMemEval trajectory to a black-box historical prompt."""
    trajectory_id = str(trajectory["id"])
    states = trajectory["states"]
    if not isinstance(states, list) or not states:
        raise ValueError(f"Trajectory {trajectory_id} has no states")

    per_state_budget = min(
        MAX_SINGLE_OBSERVATION_CHARS,
        max(2_000, MAX_OBSERVATION_TEXT_CHARS // len(states)),
    )
    truncated_state_count = 0
    lines = [
        "This is a completed historical browser work session.",
        "",
        "The original trajectory will not be available to future sessions. Use your native auto-memory to persist durable, reusable environment facts directly supported by the goal, observations, actions, and outcome.",
        "",
        "Save only facts about the external app state, UI workflow, identifiers, settings, results, failure causes, or confirmed exceptions. Do not save benchmark mechanics, run paths, this prompt, the expected answer, or broad memories about the benchmark user, their identity, preferences, or general behavior.",
        "",
        "Prefer a small number of concise memory writes over broad summaries.",
        "",
        f"Trajectory ID: {trajectory_id}",
        "",
        "Goal:",
        str(trajectory["goal"]),
    ]

    for state_offset, state in enumerate(states):
        state_index = state.get("state_index", state_offset)
        observation, truncated = _truncate_observation(
            str(state["accessibility_tree"]),
            per_state_budget,
        )
        if truncated:
            truncated_state_count += 1
        lines.extend(
            [
                "",
                f"Observation {state_index}:",
                f"URL: {state.get('url')}",
                f"Screenshot reference: {state.get('screenshot')}",
                "Accessibility tree:",
                observation,
            ]
        )
        action = state.get("action")
        if action:
            lines.extend(["", f"Action {state_index}:", str(action)])

    lines.extend(
        [
            "",
            "Outcome:",
            json.dumps(trajectory.get("outcome"), ensure_ascii=False),
            "",
            "Normalization:",
            f"observation_text_budget_chars={MAX_OBSERVATION_TEXT_CHARS}",
            f"per_state_budget_chars={per_state_budget}",
            f"truncated_state_count={truncated_state_count}",
            "thoughts_included=false",
        ]
    )
    return "\n".join(lines).strip() + "\n"
