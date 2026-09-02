import json
from pathlib import Path

from memory_modules.memory import MEMORY_TYPES

ClaudeCodeMemory = MEMORY_TYPES["claude_code"]


def test_claude_code_is_registered() -> None:
    assert MEMORY_TYPES["claude_code"] is ClaudeCodeMemory


def test_claude_command_and_working_directory() -> None:
    memory = object.__new__(ClaudeCodeMemory)
    memory.codex_binary = Path("/tools/claude")
    memory.codex_prompt = "retrieve evidence"
    memory.codex_model = "claude-sonnet-test"
    memory.claude_effort = "high"
    memory.claude_max_turns = 12
    memory.claude_bare = True
    memory.claude_no_session_persistence = True
    memory.claude_extra_args = ["--debug"]
    sandbox_dir = Path("/tmp/query")

    command = memory._build_codex_command(
        sandbox_dir=sandbox_dir,
        last_message_path=Path("/tmp/last-message.txt"),
    )

    assert command == [
        str(Path("/tools/claude")),
        "-p",
        "retrieve evidence",
        "--output-format",
        "json",
        "--model",
        "claude-sonnet-test",
        "--max-turns",
        "12",
        "--dangerously-skip-permissions",
        "--effort",
        "high",
        "--bare",
        "--no-session-persistence",
        "--debug",
    ]
    assert memory._process_cwd(sandbox_dir=sandbox_dir) == sandbox_dir


def test_claude_result_usage_is_normalized() -> None:
    memory = object.__new__(ClaudeCodeMemory)
    payload = {
        "type": "result",
        "duration_api_ms": 1200,
        "duration_ms": 1400,
        "num_turns": 7,
        "total_cost_usd": 0.25,
        "usage": {
            "input_tokens": 100,
            "cache_creation_input_tokens": 20,
            "cache_read_input_tokens": 300,
            "output_tokens": 40,
        },
        "modelUsage": {
            "test-model": {
                "inputTokens": 100,
                "outputTokens": 40,
                "costUSD": 0.25,
            }
        },
    }

    events, usage = memory._parse_process_output(json.dumps(payload))

    assert events == [payload]
    assert usage is not None
    assert usage["input_tokens"] == 100
    assert usage["cache_read_input_tokens"] == 300
    assert usage["output_tokens"] == 40
    assert usage["total_tokens"] == 460
    assert usage["num_turns"] == 7
    assert usage["total_cost_usd"] == 0.25
    assert usage["model_usage"] == payload["modelUsage"]
