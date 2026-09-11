import json
import subprocess
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

from memory_modules.memory import EndToEndMemoryAgent, MEMORY_TYPES, load_memory, save_memory
from evaluation.memory_lifecycle import build_stateful_memory


CodeAgentAutoMemory = MEMORY_TYPES["codeagent_auto_memory"]


def _trajectory(screenshot: Path, trajectory_id: str = "traj/one") -> dict[str, object]:
    return {
        "id": trajectory_id,
        "goal": "remember the account setting",
        "outcome": "success",
        "start_url": "https://example.test/settings",
        "states": [
            {
                "url": "https://example.test/settings",
                "action": "set locale",
                "thought": "The locale is zh-CN",
                "accessibility_tree": "Locale: Chinese (Simplified)",
                "screenshot": str(screenshot),
            }
        ],
    }


def _config(
    workspace: Path,
    trajectories_root: Path,
    *,
    resume_build: bool = False,
    experiment_mode: str = "baseline",
) -> dict[str, object]:
    return {
        "workspace_dir": str(workspace),
        "trajectories_root_dir": str(trajectories_root),
        "codeagent_auto_memory_params": {
            "binary": "fake-codeagent",
            "model": None,
            "timeout_seconds": 5,
            "ingest_max_turns": 3,
            "query_max_turns": 2,
            "ingest_max_attempts": 2,
            "query_max_attempts": 2,
            "experiment_mode": experiment_mode,
            "require_memory_write": experiment_mode != "memory_off",
            "resume_build": resume_build,
            "extra_args": [],
        },
    }


def test_codeagent_auto_memory_is_registered() -> None:
    assert MEMORY_TYPES["codeagent_auto_memory"] is CodeAgentAutoMemory


def test_codeagent_auto_memory_supports_direct_answers() -> None:
    memory = object.__new__(CodeAgentAutoMemory)
    assert isinstance(memory, EndToEndMemoryAgent)


def test_source_launcher_command_is_used_for_version_and_sessions(tmp_path: Path) -> None:
    config = _config(tmp_path / "workspace", tmp_path)
    params = config["codeagent_auto_memory_params"]
    assert isinstance(params, dict)
    params["launcher_command"] = ["bun", "D:/CodeAgent/src/cli.ts"]
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "source-version\n", "")

    with patch("memory_modules.codeagent_auto_memory.subprocess.run", side_effect=fake_run):
        memory = CodeAgentAutoMemory(config)
        command = memory._command("prompt", 2, ingestion=False)

    assert calls[0] == ["bun", "D:/CodeAgent/src/cli.ts", "--version"]
    assert command[:2] == ["bun", "D:/CodeAgent/src/cli.ts"]
    assert memory.memory_config["memory_params"]["codeagent_auto_memory_params"]["launcher_command"] == [
        "bun",
        "D:/CodeAgent/src/cli.ts",
    ]


def test_query_launcher_override_requires_explicit_attribution_mode(tmp_path: Path) -> None:
    with patch("memory_modules.codeagent_auto_memory.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], 0, "version-a\n", "")
        memory = CodeAgentAutoMemory(_config(tmp_path / "workspace", tmp_path))
    saved = memory.memory_config
    requested = deepcopy(saved)
    params = requested["memory_params"]["codeagent_auto_memory_params"]
    assert isinstance(params, dict)
    params["query_launcher_command"] = ["candidate-codeagent"]
    params["allow_query_override_on_load"] = False

    with pytest.raises(RuntimeError, match="does not match saved ingestion config"):
        CodeAgentAutoMemory.reconcile_loaded_memory_config(saved, requested)

    params["allow_query_override_on_load"] = True
    effective = CodeAgentAutoMemory.reconcile_loaded_memory_config(saved, requested)
    effective_params = effective["memory_params"]["codeagent_auto_memory_params"]
    assert isinstance(effective_params, dict)
    assert effective_params["ingest_launcher_command"] == ["fake-codeagent"]
    assert effective_params["query_launcher_command"] == ["candidate-codeagent"]


def test_resumed_failed_trajectory_uses_next_attempt_number(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    screenshot = tmp_path / "state.png"
    screenshot.write_bytes(b"png")
    with patch("memory_modules.codeagent_auto_memory.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], 0, "version\n", "")
        initial = CodeAgentAutoMemory(_config(workspace, tmp_path))
        initial.ingestion_records = [{"trajectory_id": "trajectory-1", "attempt": 1, "status": "failed"}]
        initial._write_manifests(status="partial_failed")

    with patch("memory_modules.codeagent_auto_memory.subprocess.run") as run:
        run.side_effect = [
            subprocess.CompletedProcess([], 0, "version\n", ""),
            subprocess.CompletedProcess([], 1, "", "failed"),
        ]
        resumed_config = _config(workspace, tmp_path, resume_build=True)
        resumed_config["codeagent_auto_memory_params"]["ingest_max_attempts"] = 1
        resumed = CodeAgentAutoMemory(resumed_config)
        with pytest.raises(RuntimeError, match="after 1 attempts"):
            resumed.insert(_trajectory(screenshot, "trajectory-1"))

    summary_path = next(workspace.glob("ingestion_sessions/*/attempt_002/summary.json"))
    assert json.loads(summary_path.read_text(encoding="utf-8"))["attempt"] == 2


def test_invalid_experiment_mode_is_rejected(tmp_path: Path) -> None:
    config = _config(tmp_path / "workspace", tmp_path)
    params = config["codeagent_auto_memory_params"]
    assert isinstance(params, dict)
    params["experiment_mode"] = "unknown"
    with patch("memory_modules.codeagent_auto_memory.subprocess.run"):
        with pytest.raises(RuntimeError, match="experiment_mode"):
            CodeAgentAutoMemory(config)


def test_ingestion_query_isolation_and_save_load(tmp_path: Path) -> None:
    screenshot = tmp_path / "state.png"
    screenshot.write_bytes(b"png")
    workspace = tmp_path / "workspace"
    calls: list[dict[str, object]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, "1.2.3 (codeAgentCLI)\n", "")
        cwd = Path(str(kwargs["cwd"]))
        env = kwargs["env"]
        assert isinstance(env, dict)
        memory_dir = Path(env["CODEAGENT3_COWORK_MEMORY_PATH_OVERRIDE"])
        assert env["CODEAGENT3_DISABLE_AUTO_MEMORY"] == "0"
        assert "--resume" not in command and "--continue" not in command and "--bare" not in command
        assert "--dangerously-skip-permissions" not in command
        calls.append({"cwd": cwd, "memory_dir": memory_dir, "command": command})
        if "--tools=Read,Write,Edit,Glob,Grep" in command:
            assert (cwd / "trajectory" / "trajectory.json").exists()
            memory_dir.mkdir(parents=True, exist_ok=True)
            (memory_dir / "MEMORY.md").write_text("Locale is zh-CN.\n", encoding="utf-8")
            result_text = "Memory saved"
        else:
            assert "--tools=Read" in command
            assert "dontAsk" in command
            assert not (cwd / "trajectory").exists()
            assert (cwd / "question.json").exists()
            result_text = "The remembered locale is zh-CN."
            (memory_dir / "query-only.md").write_text("must stay isolated\n", encoding="utf-8")
        payload = {"type": "result", "subtype": "success", "result": result_text, "usage": {"input_tokens": 2, "output_tokens": 1}}
        return subprocess.CompletedProcess(command, 0, json.dumps(payload) + "\n", "")

    with patch("memory_modules.codeagent_auto_memory.subprocess.run", side_effect=fake_run):
        memory = CodeAgentAutoMemory(_config(workspace, tmp_path))
        memory.insert(_trajectory(screenshot))
        main_before = (workspace / "auto_memory" / "MEMORY.md").read_bytes()
        memory.set_query_context(query_invocation_id="question/one")
        context = memory.query("What locale was configured?")
        assert context == [{"type": "text", "value": "The remembered locale is zh-CN.\n"}]
        memory.set_query_context(query_invocation_id="question/direct")
        answer = memory.answer("What locale was configured? Wrap the answer in \\boxed{}.")
        assert answer["response_raw"] == "The remembered locale is zh-CN."
        assert answer["usage"] == {"input_tokens": 2, "output_tokens": 1}
        assert answer["metadata"]["query_invocation_id"] == "question/direct"
        assert answer["metadata"]["main_memory_unchanged"] is True
        assert "directly" in calls[-1]["command"][-1]
        assert (workspace / "auto_memory" / "MEMORY.md").read_bytes() == main_before
        assert not (workspace / "auto_memory" / "query-only.md").exists()

        saved = tmp_path / "saved"
        save_memory(memory, saved)
        prompt_manifest = json.loads((saved / "prompt_manifest.json").read_text(encoding="utf-8"))
        assert set(prompt_manifest) == {"ingest", "query", "direct_answer"}
        assert len(prompt_manifest["direct_answer"]["sha256"]) == 64
        requested = {
            "memory_type": "codeagent_auto_memory",
            "memory_params": _config(tmp_path / "loaded-workspace", tmp_path),
        }
        loaded = load_memory(saved, requested_config=requested)
        assert isinstance(loaded, CodeAgentAutoMemory)
        assert loaded.inserted_trajectory_ids == ["traj/one"]
        assert (loaded.workspace_dir / "auto_memory" / "MEMORY.md").read_text(encoding="utf-8") == "Locale is zh-CN.\n"

    assert len(calls) == 3
    assert calls[0]["memory_dir"] != (workspace / "auto_memory").resolve()
    assert calls[1]["memory_dir"] != (workspace / "auto_memory").resolve()
    assert calls[2]["memory_dir"] != (workspace / "auto_memory").resolve()
    assert calls[0]["memory_dir"] != calls[1]["memory_dir"]
    assert calls[1]["memory_dir"] != calls[2]["memory_dir"]


def test_failed_attempt_rolls_back_then_resume_skips_completed_trajectory(tmp_path: Path) -> None:
    screenshot = tmp_path / "state.png"
    screenshot.write_bytes(b"png")
    workspace = tmp_path / "workspace"
    attempts = 0

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal attempts
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, "1.2.3\n", "")
        attempts += 1
        memory_dir = Path(kwargs["env"]["CODEAGENT3_COWORK_MEMORY_PATH_OVERRIDE"])
        memory_dir.mkdir(parents=True, exist_ok=True)
        (memory_dir / "MEMORY.md").write_text(f"attempt {attempts}\n", encoding="utf-8")
        if attempts == 1:
            return subprocess.CompletedProcess(command, 1, "", "failed")
        payload = {"type": "result", "subtype": "success", "result": "saved"}
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    with patch("memory_modules.codeagent_auto_memory.subprocess.run", side_effect=fake_run):
        memory = CodeAgentAutoMemory(_config(workspace, tmp_path))
        build_stateful_memory(memory, ["traj/one"], {"traj/one": _trajectory(screenshot)})
        assert (workspace / "auto_memory" / "MEMORY.md").read_text(encoding="utf-8") == "attempt 2\n"
        manifest = json.loads((workspace / "ingestion_manifest.json").read_text(encoding="utf-8"))
        assert manifest["build_status"] == "complete"
        assert manifest["ingestion_plan"]["ordering_source"] == "haystack_order"

        resumed = CodeAgentAutoMemory(_config(workspace, tmp_path, resume_build=True))
        resumed.insert(_trajectory(screenshot))
        assert attempts == 2


def test_memory_off_still_ingests_but_keeps_memory_empty(tmp_path: Path) -> None:
    screenshot = tmp_path / "state.png"
    screenshot.write_bytes(b"png")
    workspace = tmp_path / "workspace"
    calls: list[dict[str, object]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, "1.2.3\n", "")
        env = kwargs["env"]
        assert isinstance(env, dict)
        assert env["CODEAGENT3_DISABLE_AUTO_MEMORY"] == "1"
        cwd = Path(str(kwargs["cwd"]))
        calls.append({"command": command, "cwd": cwd})
        result_text = "trajectory processed" if (cwd / "trajectory").exists() else "\\boxed{UNKNOWN}"
        payload = {"type": "result", "result": result_text}
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    with patch("memory_modules.codeagent_auto_memory.subprocess.run", side_effect=fake_run):
        memory = CodeAgentAutoMemory(
            _config(workspace, tmp_path, experiment_mode="memory_off")
        )
        build_stateful_memory(memory, ["traj/one"], {"traj/one": _trajectory(screenshot)})
        assert memory.inserted_trajectory_ids == ["traj/one"]
        assert not list((workspace / "auto_memory").iterdir())
        manifest = json.loads((workspace / "ingestion_manifest.json").read_text(encoding="utf-8"))
        assert manifest["experiment_mode"] == "memory_off"
        assert manifest["build_status"] == "complete_memory_off"

        memory.set_query_context(query_invocation_id="memory-off/question")
        answer = memory.answer("What was retained? Wrap it in \\boxed{}.")
        assert answer["response_raw"] == "\\boxed{UNKNOWN}"

    assert len(calls) == 2
    assert (calls[0]["cwd"] / "trajectory").exists() is False
    assert "historical work session" in calls[0]["command"][-1]
    assert "directly" in calls[1]["command"][-1]


def test_memory_off_rejects_unexpected_memory_write(tmp_path: Path) -> None:
    screenshot = tmp_path / "state.png"
    screenshot.write_bytes(b"png")

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, "1.2.3\n", "")
        memory_dir = Path(kwargs["env"]["CODEAGENT3_COWORK_MEMORY_PATH_OVERRIDE"])
        memory_dir.mkdir(parents=True, exist_ok=True)
        (memory_dir / "unexpected.md").write_text("leak", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, json.dumps({"type": "result", "result": "done"}), "")

    with patch("memory_modules.codeagent_auto_memory.subprocess.run", side_effect=fake_run):
        memory = CodeAgentAutoMemory(
            _config(tmp_path / "workspace", tmp_path, experiment_mode="memory_off")
        )
        with pytest.raises(RuntimeError, match="wrote auto-memory"):
            memory.insert(_trajectory(screenshot))
        manifest = json.loads(
            (tmp_path / "workspace" / "ingestion_manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["build_status"] == "isolation_failed"


def test_incomplete_saved_memory_is_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    saved = tmp_path / "saved"
    saved.mkdir()
    (saved / "auto_memory").mkdir()
    config = {
        "memory_type": "codeagent_auto_memory",
        "memory_params": _config(workspace, tmp_path),
    }
    (saved / "memory_config.json").write_text(json.dumps(config), encoding="utf-8")
    (saved / "ingestion_manifest.json").write_text(
        json.dumps({"memory_type": "codeagent_auto_memory", "build_status": "partial_failed"}),
        encoding="utf-8",
    )
    with patch("memory_modules.codeagent_auto_memory.subprocess.run"):
        try:
            load_memory(saved, requested_config=config)
        except RuntimeError as exc:
            assert "not complete" in str(exc)
        else:
            raise AssertionError("incomplete memory should not load")
