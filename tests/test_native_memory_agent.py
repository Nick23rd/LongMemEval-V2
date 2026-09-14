from pathlib import Path
import subprocess
from unittest.mock import patch

from memory_modules.memory import MEMORY_TYPES
from memory_modules.native_memory_agent import (
    NativeMemoryAgent,
    inject_native_memory_runtime_config,
    is_native_memory_config,
    native_memory_class,
)


def _config(*, resume_build: bool = False) -> dict[str, object]:
    return {
        "memory_type": "codeagent_auto_memory",
        "memory_params": {
            "codeagent_auto_memory_params": {
                "launcher_command": ["agent"],
                "resume_build": resume_build,
            }
        },
    }


def test_codeagent_uses_generic_native_memory_contract() -> None:
    memory_cls = MEMORY_TYPES["codeagent_auto_memory"]
    assert issubclass(memory_cls, NativeMemoryAgent)
    assert native_memory_class(_config()) is memory_cls
    assert is_native_memory_config(_config())
    assert memory_cls.adapter_manifest() == {
        "name": "codeagent_cli",
        "memory_type": "codeagent_auto_memory",
        "black_box": True,
        "capabilities": {
            "trajectory_file_ingestion": True,
            "fresh_query_session": True,
            "frozen_memory_snapshot": True,
            "historical_session_import": True,
            "local_memory_state": True,
        },
    }


def test_native_memory_runtime_paths_are_injected_generically(tmp_path: Path) -> None:
    config = _config()
    trajectories_path = tmp_path / "data" / "trajectories.jsonl"
    query_trace_dir = tmp_path / "traces"
    workspace_dir = tmp_path / "workspace"
    runtime = inject_native_memory_runtime_config(
        config,
        workspace_dir=workspace_dir,
        trajectories_path=str(trajectories_path),
        query_trace_dir=query_trace_dir,
    )
    assert runtime["memory_params"]["workspace_dir"] == str(workspace_dir.resolve())
    assert runtime["memory_params"]["trajectories_root_dir"] == str(
        trajectories_path.resolve().parent
    )
    assert runtime["memory_params"]["query_trace_dir"] == str(query_trace_dir.resolve())
    assert "workspace_dir" not in config["memory_params"]


def test_native_memory_resume_is_adapter_namespace_driven() -> None:
    memory_cls = native_memory_class(_config())
    assert memory_cls is not None
    assert not memory_cls.config_resumes_build(_config())
    assert memory_cls.config_resumes_build(_config(resume_build=True))


def test_native_memory_manifest_is_written_for_codeagent(tmp_path: Path) -> None:
    config = _config()["memory_params"]
    config["workspace_dir"] = str(tmp_path / "workspace")
    config["trajectories_root_dir"] = str(tmp_path)
    version_result = subprocess.CompletedProcess(["agent", "--version"], 0, "1.0\n", "")
    with patch(
        "memory_modules.codeagent_auto_memory.subprocess.run",
        return_value=version_result,
    ):
        memory = MEMORY_TYPES["codeagent_auto_memory"](config)
    memory._write_manifests()
    manifest = (tmp_path / "workspace" / "ingestion_manifest.json").read_text(
        encoding="utf-8"
    )
    assert '"native_memory_adapter"' in manifest
    assert '"black_box": true' in manifest
