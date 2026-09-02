import json
import subprocess
from pathlib import Path
from typing import Any

from .codex import DEFAULT_PROMPT, CodexMemory, ensure_string_list
from .memory import MemoryConfig, register_memory, require


DEFAULT_CLAUDE_BINARY = "claude"
DEFAULT_CLAUDE_MODEL = "sonnet"
DEFAULT_CLAUDE_TIMEOUT_SECONDS = 1800.0
DEFAULT_CLAUDE_MAX_ATTEMPTS = 3
DEFAULT_CLAUDE_MAX_TURNS = 30


@register_memory
class ClaudeCodeMemory(CodexMemory):
    """Claude Code-backed trajectory retrieval using the Codex workspace protocol."""

    memory_type = "claude_code"

    def __init__(self, memory_params: dict[str, object]) -> None:
        claude_params_obj = memory_params.get("claude_params", {})
        require(
            isinstance(claude_params_obj, dict),
            "claude_code claude_params must be an object",
        )
        claude_params = dict(claude_params_obj)

        model = claude_params.get("model", DEFAULT_CLAUDE_MODEL)
        effort = claude_params.get("effort")
        max_turns = claude_params.get("max_turns", DEFAULT_CLAUDE_MAX_TURNS)
        bare = claude_params.get("bare", False)
        no_session_persistence = claude_params.get("no_session_persistence", True)
        version_label = claude_params.get("version_label")
        extra_args_obj = claude_params.get("extra_args", [])

        require(isinstance(model, str) and model.strip(), "claude_code model must be a non-empty string")
        require(
            effort is None or (isinstance(effort, str) and effort.strip()),
            "claude_code effort must be null or a non-empty string",
        )
        require(
            isinstance(max_turns, int) and not isinstance(max_turns, bool) and max_turns > 0,
            "claude_code max_turns must be a positive integer",
        )
        require(isinstance(bare, bool), "claude_code bare must be a boolean")
        require(
            isinstance(no_session_persistence, bool),
            "claude_code no_session_persistence must be a boolean",
        )
        require(
            version_label is None or (isinstance(version_label, str) and version_label.strip()),
            "claude_code version_label must be null or a non-empty string",
        )

        translated_params = dict(memory_params)
        translated_params.pop("claude_params", None)
        translated_params["codex_params"] = {
            "binary": claude_params.get("binary", DEFAULT_CLAUDE_BINARY),
            "model": model,
            # Required by the shared initializer but not passed as a Codex option.
            "reasoning_effort": effort or "unused",
            "timeout_seconds": claude_params.get(
                "timeout_seconds", DEFAULT_CLAUDE_TIMEOUT_SECONDS
            ),
            "max_retries": claude_params.get(
                "max_attempts",
                claude_params.get("max_retries", DEFAULT_CLAUDE_MAX_ATTEMPTS),
            ),
            "prompt": claude_params.get("prompt", DEFAULT_PROMPT),
            "require_evidence_gate": claude_params.get("require_evidence_gate", False),
            "extra_config": [],
            "extra_args": [],
        }
        super().__init__(translated_params)

        self.claude_effort = effort.strip() if isinstance(effort, str) else None
        self.claude_max_turns = max_turns
        self.claude_bare = bare
        self.claude_no_session_persistence = no_session_persistence
        self.claude_version_label = version_label.strip() if isinstance(version_label, str) else None
        self.claude_extra_args = ensure_string_list(
            extra_args_obj,
            field_name="claude_params.extra_args",
        )
        self.claude_detected_version = self._detect_claude_version()

    def _detect_claude_version(self) -> str | None:
        try:
            result = subprocess.run(
                [str(self.codex_binary), "--version"],
                capture_output=True,
                text=True,
                timeout=10.0,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        version = (result.stdout or result.stderr).strip()
        return version or None

    @property
    def memory_config(self) -> MemoryConfig:
        claude_params: dict[str, object] = {
            "binary": str(self.codex_binary),
            "model": self.codex_model,
            "timeout_seconds": self.codex_timeout_seconds,
            "max_retries": self.codex_max_attempts,
            "max_turns": self.claude_max_turns,
            "prompt": self.codex_prompt,
            "require_evidence_gate": self.require_evidence_gate,
            "bare": self.claude_bare,
            "no_session_persistence": self.claude_no_session_persistence,
            "extra_args": list(self.claude_extra_args),
            "detected_version": self.claude_detected_version,
        }
        if self.claude_effort is not None:
            claude_params["effort"] = self.claude_effort
        if self.claude_version_label is not None:
            claude_params["version_label"] = self.claude_version_label
        memory_params: dict[str, object] = {
            "evidence_mode": self.evidence_mode,
            "claude_params": claude_params,
        }
        if self.trajectory_pool_root is not None:
            memory_params["trajectory_pool_root"] = str(self.trajectory_pool_root)
        return {"memory_type": self.memory_type, "memory_params": memory_params}

    def _build_codex_command(self, *, sandbox_dir: Path, last_message_path: Path) -> list[str]:
        del sandbox_dir, last_message_path
        command = [
            str(self.codex_binary),
            "-p",
            self.codex_prompt,
            "--output-format",
            "json",
            "--model",
            self.codex_model,
            "--max-turns",
            str(self.claude_max_turns),
            "--dangerously-skip-permissions",
        ]
        if self.claude_effort is not None:
            command.extend(["--effort", self.claude_effort])
        if self.claude_bare:
            command.append("--bare")
        if self.claude_no_session_persistence:
            command.append("--no-session-persistence")
        command.extend(self.claude_extra_args)
        return command

    def _process_cwd(self, *, sandbox_dir: Path) -> Path | None:
        return sandbox_dir

    def _parse_process_output(
        self,
        raw_stdout: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        events: list[dict[str, Any]] = []
        result_payload: dict[str, Any] | None = None
        for line in raw_stdout.splitlines():
            stripped = line.strip()
            if not stripped.startswith("{"):
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            events.append(payload)
            if payload.get("type") == "result":
                result_payload = payload
        if result_payload is None:
            return events, None

        raw_usage = result_payload.get("usage")
        usage: dict[str, Any] = dict(raw_usage) if isinstance(raw_usage, dict) else {}
        for key in ("num_turns", "total_cost_usd", "duration_api_ms", "duration_ms"):
            value = result_payload.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                usage[key] = value
        model_usage = result_payload.get("modelUsage")
        if isinstance(model_usage, dict):
            usage["model_usage"] = model_usage

        token_keys = (
            "input_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
            "output_tokens",
        )
        token_values = [usage.get(key) for key in token_keys]
        if all(isinstance(value, int) and not isinstance(value, bool) for value in token_values):
            usage["total_tokens"] = sum(token_values)
        return events, usage or None
