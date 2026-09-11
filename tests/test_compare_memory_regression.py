import json
from pathlib import Path

import pytest

from evaluation.compare_memory_regression import build_comparison, load_results, write_outputs


def row(question_id: str, mode: str, correct: bool, category: str = "static") -> dict[str, object]:
    return {
        "question_id": question_id,
        "experiment_mode": mode,
        "question_text": f"Question {question_id}",
        "question_type": "static-environment",
        "category": category,
        "eval_function": "exact",
        "answer_gold": "gold",
        "haystack_ids": ["trajectory-one"],
        "score_bool": correct,
        "response_raw": "answer",
    }


def write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(item) + "\n" for item in rows), encoding="utf-8")


def test_build_comparison_and_reports(tmp_path: Path) -> None:
    off_path = tmp_path / "off.jsonl"
    baseline_path = tmp_path / "baseline.jsonl"
    candidate_path = tmp_path / "candidate.jsonl"
    write_rows(off_path, [row("q1", "memory_off", False), row("q2", "memory_off", True)])
    write_rows(baseline_path, [row("q1", "baseline", False), row("q2", "baseline", True)])
    write_rows(candidate_path, [row("q1", "candidate", True), row("q2", "candidate", False)])

    summary, diffs = build_comparison(
        load_results(off_path, "memory_off"),
        load_results(baseline_path, "baseline"),
        load_results(candidate_path, "candidate"),
    )

    assert summary["accuracy_delta"] == 0.0
    assert summary["improved"] == 1
    assert summary["regressed"] == 1
    assert summary["net_improved_count"] == 0
    assert [item["status"] for item in diffs] == ["improved", "regressed"]

    output_dir = tmp_path / "report"
    write_outputs(output_dir, summary, diffs)
    assert (output_dir / "comparison.json").is_file()
    assert len((output_dir / "per_question_diff.jsonl").read_text().splitlines()) == 2
    report = (output_dir / "report.md").read_text(encoding="utf-8")
    assert "Improved questions" in report
    assert "`q2`" in report


def test_comparison_rejects_different_questions(tmp_path: Path) -> None:
    off_path = tmp_path / "off.jsonl"
    baseline_path = tmp_path / "baseline.jsonl"
    candidate_path = tmp_path / "candidate.jsonl"
    write_rows(off_path, [row("q1", "memory_off", False)])
    write_rows(baseline_path, [row("q1", "baseline", False)])
    write_rows(candidate_path, [row("q2", "candidate", True)])

    with pytest.raises(RuntimeError, match="question IDs do not match"):
        build_comparison(
            load_results(off_path, "memory_off"),
            load_results(baseline_path, "baseline"),
            load_results(candidate_path, "candidate"),
        )


def test_load_results_rejects_wrong_mode(tmp_path: Path) -> None:
    path = tmp_path / "rows.jsonl"
    write_rows(path, [row("q1", "baseline", True)])
    with pytest.raises(RuntimeError, match="Expected experiment_mode"):
        load_results(path, "candidate")

