import json
from pathlib import Path

import pytest

from evaluation.build_single_run_result import build_result, write_result


def make_run(tmp_path: Path, mode: str = "single") -> Path:
    run_dir = tmp_path / "run"
    (run_dir / "build" / "memory_state").mkdir(parents=True)
    (run_dir / "build" / "runtime_inputs").mkdir(parents=True)
    (run_dir / "evaluate").mkdir()
    (run_dir / "runner_config.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "config": {"preset": "smoke"},
                "run_identity": {
                    "commit_hash": "0123456789abcdef",
                    "experiment_mode": mode,
                },
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "build" / "runtime_inputs" / "data_selection.json").write_text(
        json.dumps({"domain": "web", "structural_smoke_only": True}), encoding="utf-8"
    )
    (run_dir / "build" / "memory_state" / "ingestion_metrics.json").write_text(
        json.dumps({"duration_seconds": 12.5}), encoding="utf-8"
    )
    (run_dir / "build" / "memory_state" / "ingestion_manifest.json").write_text(
        json.dumps({"experiment_mode": mode}), encoding="utf-8"
    )
    (run_dir / "evaluate" / "aggregated_metrics.json").write_text(
        json.dumps({"overall": {"accuracy": 0.5}}), encoding="utf-8"
    )
    (run_dir / "evaluate" / "per_question.jsonl").write_text(
        json.dumps({"question_id": "q1", "score": 1.0}) + "\n"
        + json.dumps({"question_id": "q2", "score": 0.0}) + "\n",
        encoding="utf-8",
    )
    return run_dir


def test_build_result_is_one_html_consumable_json_document(tmp_path: Path) -> None:
    run_dir = make_run(tmp_path)
    output_path = write_result(run_dir)
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["document_type"] == "longmemeval_v2_codeagent_single_run"
    assert payload["run"]["memory_enabled"] is True
    assert payload["metrics"]["overall"]["accuracy"] == 0.5
    assert [row["question_id"] for row in payload["questions"]] == ["q1", "q2"]
    assert payload["artifacts"]["aggregated_metrics"] == "evaluate/aggregated_metrics.json"
    report = (run_dir / "report.html").read_text(encoding="utf-8")
    assert 'id="files"' in report
    assert "multiple" in report
    assert "longmemeval_v2_codeagent_single_run" in report


def test_memory_off_result_is_explicit(tmp_path: Path) -> None:
    payload = build_result(make_run(tmp_path, mode="memory_off"))
    assert payload["run"]["experiment_mode"] == "memory_off"
    assert payload["run"]["memory_enabled"] is False


def test_result_rejects_removed_three_arm_modes(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="Unsupported single-run experiment mode"):
        build_result(make_run(tmp_path, mode="baseline"))
