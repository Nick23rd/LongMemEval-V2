from pathlib import Path

from memory_modules.memory import MEMORY_TYPES
from memory_modules.codeagent import DEFAULT_CODEAGENT_BINARY


CodeAgentMemory = MEMORY_TYPES["codeagent"]


def test_codeagent_is_registered() -> None:
    assert MEMORY_TYPES["codeagent"] is CodeAgentMemory
    assert DEFAULT_CODEAGENT_BINARY == "codeagentcli"


def test_codeagent_uses_builtin_model_by_default() -> None:
    memory = object.__new__(CodeAgentMemory)
    memory.codex_binary = Path("/tools/codeagent")
    memory.codex_prompt = "retrieve evidence"
    memory.codeagent_model = None
    memory.claude_effort = None
    memory.claude_max_turns = 12
    memory.claude_bare = False
    memory.claude_no_session_persistence = True
    memory.claude_extra_args = []

    command = memory._build_codex_command(
        sandbox_dir=Path("/tmp/query"),
        last_message_path=Path("/tmp/last-message.txt"),
    )

    assert command == [
        str(Path("/tools/codeagent")),
        "-p",
        "retrieve evidence",
        "--output-format",
        "json",
        "--max-turns",
        "12",
        "--dangerously-skip-permissions",
        "--no-session-persistence",
    ]


def test_codeagent_allows_reserved_model_override() -> None:
    memory = object.__new__(CodeAgentMemory)
    memory.codex_binary = Path("/tools/codeagent")
    memory.codex_prompt = "retrieve evidence"
    memory.codeagent_model = "future-model"
    memory.claude_effort = None
    memory.claude_max_turns = 1
    memory.claude_bare = False
    memory.claude_no_session_persistence = False
    memory.claude_extra_args = []

    command = memory._build_codex_command(
        sandbox_dir=Path("/tmp/query"),
        last_message_path=Path("/tmp/last-message.txt"),
    )

    assert command[5:7] == ["--model", "future-model"]


def test_codeagent_parses_single_json_result() -> None:
    memory = object.__new__(CodeAgentMemory)
    events, usage = memory._parse_process_output(
        '{"type":"result","subtype":"success","result":"done",'
        '"num_turns":2,"duration_ms":125,"usage":'
        '{"input_tokens":10,"cache_creation_input_tokens":3,'
        '"cache_read_input_tokens":4,"output_tokens":5}}\n'
    )

    assert events[0]["result"] == "done"
    assert usage == {
        "input_tokens": 10,
        "cache_creation_input_tokens": 3,
        "cache_read_input_tokens": 4,
        "output_tokens": 5,
        "num_turns": 2,
        "duration_ms": 125,
        "total_tokens": 22,
    }
