#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def resolve_results_path(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()
    if path.is_dir():
        path = path / "per_question.jsonl"
    require(path.is_file(), f"Missing per-question results: {path}")
    return path


def load_results(value: str | Path, expected_mode: str) -> dict[str, dict[str, Any]]:
    path = resolve_results_path(value)
    rows: dict[str, dict[str, Any]] = {}
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        require(isinstance(row, dict), f"Line {line_no} in {path} is not an object")
        question_id = row.get("question_id")
        require(isinstance(question_id, str) and question_id, f"Invalid question_id at {path}:{line_no}")
        require(question_id not in rows, f"Duplicate question_id {question_id!r} in {path}")
        require(isinstance(row.get("score_bool"), bool), f"Missing boolean score_bool for {question_id} in {path}")
        mode = row.get("experiment_mode")
        require(mode == expected_mode, f"Expected experiment_mode={expected_mode!r} for {question_id}, got {mode!r}")
        rows[question_id] = row
    require(rows, f"No result rows in {path}")
    return rows


COMPARABILITY_FIELDS = (
    "question_text",
    "question_type",
    "category",
    "eval_function",
    "answer_gold",
    "haystack_ids",
)


def validate_comparable(
    memory_off: dict[str, dict[str, Any]],
    baseline: dict[str, dict[str, Any]],
    candidate: dict[str, dict[str, Any]],
) -> list[str]:
    id_sets = {"memory_off": set(memory_off), "baseline": set(baseline), "candidate": set(candidate)}
    require(
        id_sets["memory_off"] == id_sets["baseline"] == id_sets["candidate"],
        "Experiment question IDs do not match: "
        + ", ".join(f"{name}={len(ids)}" for name, ids in id_sets.items()),
    )
    ordered_ids = list(baseline)
    for question_id in ordered_ids:
        reference = baseline[question_id]
        for group_name, group in (("memory_off", memory_off), ("candidate", candidate)):
            for field in COMPARABILITY_FIELDS:
                require(
                    group[question_id].get(field) == reference.get(field),
                    f"Non-comparable {field} for question {question_id}: baseline vs {group_name}",
                )
    return ordered_ids


def accuracy(rows: list[dict[str, Any]]) -> float:
    return sum(bool(row["score_bool"]) for row in rows) / len(rows)


def pair_status(baseline_correct: bool, candidate_correct: bool) -> str:
    if not baseline_correct and candidate_correct:
        return "improved"
    if baseline_correct and not candidate_correct:
        return "regressed"
    if baseline_correct:
        return "both_correct"
    return "both_wrong"


def build_comparison(
    memory_off: dict[str, dict[str, Any]],
    baseline: dict[str, dict[str, Any]],
    candidate: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    question_ids = validate_comparable(memory_off, baseline, candidate)
    diffs: list[dict[str, Any]] = []
    for question_id in question_ids:
        off_row = memory_off[question_id]
        baseline_row = baseline[question_id]
        candidate_row = candidate[question_id]
        baseline_correct = bool(baseline_row["score_bool"])
        candidate_correct = bool(candidate_row["score_bool"])
        diffs.append(
            {
                "question_id": question_id,
                "question_type": baseline_row.get("question_type"),
                "category": baseline_row.get("category"),
                "question_text": baseline_row.get("question_text"),
                "answer_gold": baseline_row.get("answer_gold"),
                "memory_off_correct": bool(off_row["score_bool"]),
                "baseline_correct": baseline_correct,
                "candidate_correct": candidate_correct,
                "status": pair_status(baseline_correct, candidate_correct),
                "memory_off_response": off_row.get("response_raw"),
                "baseline_response": baseline_row.get("response_raw"),
                "candidate_response": candidate_row.get("response_raw"),
            }
        )

    off_accuracy = accuracy(list(memory_off.values()))
    baseline_accuracy = accuracy(list(baseline.values()))
    candidate_accuracy = accuracy(list(candidate.values()))
    status_counts = Counter(row["status"] for row in diffs)

    categories: dict[str, Any] = {}
    for category in sorted({str(row["category"]) for row in diffs}):
        category_rows = [row for row in diffs if row["category"] == category]
        count = len(category_rows)
        category_status = Counter(row["status"] for row in category_rows)
        categories[category] = {
            "count": count,
            "memory_off_accuracy": sum(row["memory_off_correct"] for row in category_rows) / count,
            "baseline_accuracy": sum(row["baseline_correct"] for row in category_rows) / count,
            "candidate_accuracy": sum(row["candidate_correct"] for row in category_rows) / count,
            "accuracy_delta": (
                sum(row["candidate_correct"] for row in category_rows)
                - sum(row["baseline_correct"] for row in category_rows)
            ) / count,
            "improved": category_status["improved"],
            "regressed": category_status["regressed"],
        }

    question_count = len(diffs)
    summary = {
        "question_count": question_count,
        "memory_off_accuracy": off_accuracy,
        "baseline_accuracy": baseline_accuracy,
        "candidate_accuracy": candidate_accuracy,
        "accuracy_delta": candidate_accuracy - baseline_accuracy,
        "baseline_memory_gain": baseline_accuracy - off_accuracy,
        "candidate_memory_gain": candidate_accuracy - off_accuracy,
        "improved": status_counts["improved"],
        "regressed": status_counts["regressed"],
        "both_correct": status_counts["both_correct"],
        "both_wrong": status_counts["both_wrong"],
        "net_improved_count": status_counts["improved"] - status_counts["regressed"],
        "net_improved_rate": (status_counts["improved"] - status_counts["regressed"]) / question_count,
        "categories": categories,
    }
    return summary, diffs


def render_markdown(summary: dict[str, Any], diffs: list[dict[str, Any]]) -> str:
    lines = [
        "# CodeAgent Memory Regression Report",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Questions | {summary['question_count']} |",
        f"| Memory off accuracy | {summary['memory_off_accuracy']:.2%} |",
        f"| Baseline accuracy | {summary['baseline_accuracy']:.2%} |",
        f"| Candidate accuracy | {summary['candidate_accuracy']:.2%} |",
        f"| Accuracy delta | {summary['accuracy_delta']:+.2%} |",
        f"| Improved | {summary['improved']} |",
        f"| Regressed | {summary['regressed']} |",
        f"| Net improved | {summary['net_improved_count']} |",
        "",
        "## Categories",
        "",
        "| Category | Count | Memory off | Baseline | Candidate | Delta | Improved | Regressed |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for category, values in summary["categories"].items():
        lines.append(
            f"| {category} | {values['count']} | {values['memory_off_accuracy']:.2%} | "
            f"{values['baseline_accuracy']:.2%} | {values['candidate_accuracy']:.2%} | "
            f"{values['accuracy_delta']:+.2%} | {values['improved']} | {values['regressed']} |"
        )
    for title, status in (("Improved questions", "improved"), ("Regressed questions", "regressed")):
        lines.extend(["", f"## {title}", ""])
        selected = [row for row in diffs if row["status"] == status]
        if not selected:
            lines.append("None.")
        else:
            for row in selected:
                lines.append(f"- `{row['question_id']}` ({row['category']}): {row['question_text']}")
    return "\n".join(lines) + "\n"


def write_outputs(output_dir: Path, summary: dict[str, Any], diffs: list[dict[str, Any]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "comparison.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    with (output_dir / "per_question_diff.jsonl").open("w", encoding="utf-8") as handle:
        for row in diffs:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    (output_dir / "report.md").write_text(render_markdown(summary, diffs), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare memory_off, baseline, and candidate CodeAgent runs.")
    parser.add_argument("--memory-off", required=True, help="Run directory or per_question.jsonl")
    parser.add_argument("--baseline", required=True, help="Run directory or per_question.jsonl")
    parser.add_argument("--candidate", required=True, help="Run directory or per_question.jsonl")
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary, diffs = build_comparison(
        load_results(args.memory_off, "memory_off"),
        load_results(args.baseline, "baseline"),
        load_results(args.candidate, "candidate"),
    )
    write_outputs(Path(args.output_dir).expanduser().resolve(), summary, diffs)


if __name__ == "__main__":
    main()

