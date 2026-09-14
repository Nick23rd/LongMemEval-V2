import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_cross_platform_runner_defaults_to_retained_single_arm() -> None:
    repo = Path(__file__).resolve().parents[1]
    script = repo / "evaluation/scripts/run_codeagent_memory_eval.mjs"
    output_root = repo / "runs/dry-run-single-not-created"
    result = subprocess.run(
        [
            "node", str(script), "--preset", "smoke",
            "--data-root", str(repo / "data/longmemeval-v2"),
            "--output-root", str(output_root), "--dry-run",
            "--launcher", '["fake-codeagent"]',
            "--commit-hash", "0123456789abcdef0123456789abcdef01234567",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "single:build" in result.stdout
    assert "single:evaluate" in result.stdout
    assert "single:result" in result.stdout
    assert "build_single_run_result.py" in result.stdout
    assert '"single"' in result.stdout
    assert "0123456789ab" in result.stdout
    assert "regression:report" not in result.stdout
    assert not output_root.exists()


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_cross_platform_runner_rejects_historical_importer_for_codeagent_runtime() -> None:
    repo = Path(__file__).resolve().parents[1]
    script = repo / "evaluation/scripts/run_codeagent_memory_eval.mjs"
    result = subprocess.run(
        [
            "node",
            str(script),
            "--preset",
            "smoke",
            "--data-root",
            str(repo / "data/longmemeval-v2"),
            "--output-root",
            str(repo / "runs/dry-run-invalid-historical-not-created"),
            "--dry-run",
            "--launcher",
            '["fake-codeagent"]',
            "--commit-hash",
            "0123456789abcdef0123456789abcdef01234567",
            "--ingestion-strategy",
            "historical_session",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "requires --runtime free_code" in result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_cross_platform_runner_supports_one_memory_off_run() -> None:
    repo = Path(__file__).resolve().parents[1]
    script = repo / "evaluation/scripts/run_codeagent_memory_eval.mjs"
    result = subprocess.run(
        [
            "node", str(script), "--preset", "smoke",
            "--data-root", str(repo / "data/longmemeval-v2"),
            "--output-root", str(repo / "runs/dry-run-memory-off-not-created"),
            "--dry-run", "--memory-off",
            "--runtime", "free_code",
            "--launcher", '["before"]',
            "--commit-hash", "0123456789abcdef0123456789abcdef01234567",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "memory_off:build" in result.stdout
    assert "memory_off:evaluate" in result.stdout
    assert "memory_off:result" in result.stdout
    assert '"memory_off"' in result.stdout
    assert '\"free_code\"' in result.stdout
    assert not (repo / "runs/dry-run-memory-off-not-created").exists()


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
@pytest.mark.parametrize("removed_command", ["regression", "attribution"])
def test_cross_platform_runner_rejects_removed_multi_arm_commands(removed_command: str) -> None:
    repo = Path(__file__).resolve().parents[1]
    script = repo / "evaluation/scripts/run_codeagent_memory_eval.mjs"
    result = subprocess.run(
        [
            "node", str(script), removed_command,
            "--data-root", str(repo / "data/longmemeval-v2"),
            "--output-root", str(repo / "runs/dry-run-removed-command-not-created"),
            "--dry-run",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert f"unknown command: {removed_command}" in result.stderr
