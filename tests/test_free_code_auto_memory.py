import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from memory_modules.memory import MEMORY_TYPES, load_memory, save_memory


FreeCodeAutoMemory = MEMORY_TYPES["free_code_auto_memory"]


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


def _config(workspace: Path, trajectories_root: Path) -> dict[str, object]:
    return {
        "workspace_dir": str(workspace),
        "trajectories_root_dir": str(trajectories_root),
        "free_code_params": {
            "binary": "fake-codeagent",
            "model": None,
            "timeout_seconds": 5,
            "ingest_max_turns": 3,
            "query_max_turns": 2,
            "max_retries": 2,
            "require_memory_write": True,
            "extra_args": [],
        },
    }


def test_free_code_auto_memory_is_registered() -> None:
    assert MEMORY_TYPES["free_code_auto_memory"] is FreeCodeAutoMemory


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
        calls.append({"cwd": cwd, "memory_dir": memory_dir, "command": command})
        if "ingestion_sessions" in cwd.parts:
            assert (cwd / "trajectory" / "trajectory.json").exists()
            memory_dir.mkdir(parents=True, exist_ok=True)
            (memory_dir / "MEMORY.md").write_text("Locale is zh-CN.\n", encoding="utf-8")
            result_text = "Memory saved"
        else:
            assert not (cwd / "trajectory").exists()
            assert (cwd / "question.json").exists()
            result_text = "The remembered locale is zh-CN."
            (memory_dir / "query-only.md").write_text("must stay isolated\n", encoding="utf-8")
        payload = {"type": "result", "subtype": "success", "result": result_text, "usage": {"input_tokens": 2, "output_tokens": 1}}
        return subprocess.CompletedProcess(command, 0, json.dumps(payload) + "\n", "")

    with patch("memory_modules.free_code_auto_memory.subprocess.run", side_effect=fake_run):
        memory = FreeCodeAutoMemory(_config(workspace, tmp_path))
        memory.insert(_trajectory(screenshot))
        main_before = (workspace / "auto_memory" / "MEMORY.md").read_bytes()
        memory.set_query_context(query_invocation_id="question/one")
        context = memory.query("What locale was configured?")
        assert context == [{"type": "text", "value": "The remembered locale is zh-CN.\n"}]
        assert (workspace / "auto_memory" / "MEMORY.md").read_bytes() == main_before
        assert not (workspace / "auto_memory" / "query-only.md").exists()

        saved = tmp_path / "saved"
        save_memory(memory, saved)
        requested = {
            "memory_type": "free_code_auto_memory",
            "memory_params": _config(tmp_path / "loaded-workspace", tmp_path),
        }
        loaded = load_memory(saved, requested_config=requested)
        assert isinstance(loaded, FreeCodeAutoMemory)
        assert loaded.inserted_trajectory_ids == ["traj/one"]
        assert (loaded.workspace_dir / "auto_memory" / "MEMORY.md").read_text(encoding="utf-8") == "Locale is zh-CN.\n"

    assert len(calls) == 2
    assert calls[0]["memory_dir"] == (workspace / "auto_memory").resolve()
    assert calls[1]["memory_dir"] != (workspace / "auto_memory").resolve()
