from pathlib import Path

from .claude_code import ClaudeCodeMemory
from .codex import DEFAULT_PROMPT
from .memory import MemoryConfig, register_memory, require


DEFAULT_CODEAGENT_BINARY = "codeagentcli"
DEFAULT_CODEAGENT_TIMEOUT_SECONDS = 1800.0
DEFAULT_CODEAGENT_MAX_ATTEMPTS = 3
DEFAULT_CODEAGENT_MAX_TURNS = 30


@register_memory
class CodeAgentMemory(ClaudeCodeMemory):
    """CodeAgent-backed retrieval using its non-interactive JSON CLI."""

    memory_type = "codeagent"

    def __init__(self, memory_params: dict[str, object]) -> None:
        params_obj = memory_params.get("codeagent_params", {})
        require(isinstance(params_obj, dict), "codeagent codeagent_params must be an object")
        params = dict(params_obj)

        model = params.get("model")
        require(
            model is None or (isinstance(model, str) and model.strip()),
            "codeagent model must be null or a non-empty string",
        )

        translated_params = dict(memory_params)
        translated_params.pop("codeagent_params", None)
        translated_params["claude_params"] = {
            "binary": params.get("binary", DEFAULT_CODEAGENT_BINARY),
            # ClaudeCodeMemory requires a model; CodeAgent omits --model when this
            # sentinel is retained so the CLI can select its built-in default.
            "model": model or "__codeagent_builtin__",
            "effort": params.get("effort"),
            "timeout_seconds": params.get("timeout_seconds", DEFAULT_CODEAGENT_TIMEOUT_SECONDS),
            "max_retries": params.get(
                "max_attempts",
                params.get("max_retries", DEFAULT_CODEAGENT_MAX_ATTEMPTS),
            ),
            "max_turns": params.get("max_turns", DEFAULT_CODEAGENT_MAX_TURNS),
            "bare": params.get("bare", False),
            "no_session_persistence": params.get("no_session_persistence", True),
            "version_label": params.get("version_label"),
            "extra_args": params.get("extra_args", []),
            "prompt": params.get("prompt", DEFAULT_PROMPT),
            "require_evidence_gate": params.get("require_evidence_gate", False),
        }
        super().__init__(translated_params)
        self.codeagent_model = model.strip() if isinstance(model, str) else None

    @property
    def memory_config(self) -> MemoryConfig:
        params: dict[str, object] = {
            "binary": str(self.codex_binary),
            "model": self.codeagent_model,
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
            params["effort"] = self.claude_effort
        if self.claude_version_label is not None:
            params["version_label"] = self.claude_version_label
        memory_params: dict[str, object] = {
            "evidence_mode": self.evidence_mode,
            "codeagent_params": params,
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
        ]
        if self.codeagent_model is not None:
            command.extend(["--model", self.codeagent_model])
        command.extend(
            [
                "--max-turns",
                str(self.claude_max_turns),
                "--dangerously-skip-permissions",
            ]
        )
        if self.claude_effort is not None:
            command.extend(["--effort", self.claude_effort])
        if self.claude_bare:
            command.append("--bare")
        if self.claude_no_session_persistence:
            command.append("--no-session-persistence")
        command.extend(self.claude_extra_args)
        return command
