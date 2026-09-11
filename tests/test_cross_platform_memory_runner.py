import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_cross_platform_runner_builds_calibration_commands_without_shell() -> None:
    repo = Path(__file__).resolve().parents[1]
    script = repo / "evaluation/scripts/run_codeagent_memory_eval.mjs"
    result = subprocess.run(
        [
            "node", str(script), "attribution", "--preset", "calibration",
            "--data-root", str(repo / "data/longmemeval-v2"),
            "--output-root", str(repo / "runs/dry-run-not-created"),
            "--confirm-full-haystack", "--dry-run",
            "--writer-a-launcher", '["before"]', "--writer-b-launcher", '["bun","candidate.ts"]',
            "--recall-a-launcher", '["before"]', "--recall-b-launcher", '["bun","candidate.ts"]',
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "writer_a:build" in result.stdout
    assert "writer_b:build" in result.stdout
    assert "aa:evaluate" in result.stdout and "bb:evaluate" in result.stdout
    assert "attribution:report" in result.stdout
    assert not (repo / "runs/dry-run-not-created").exists()
