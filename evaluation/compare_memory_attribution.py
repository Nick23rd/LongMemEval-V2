#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


COMPARABILITY_FIELDS = (
    "question_text", "question_type", "category", "eval_function", "answer_gold", "haystack_ids"
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_results(value: str | Path) -> dict[str, dict[str, Any]]:
    path = Path(value).expanduser().resolve()
    if path.is_dir():
        path /= "per_question.jsonl"
    require(path.is_file(), f"Missing per-question results: {path}")
    rows: dict[str, dict[str, Any]] = {}
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        question_id = row.get("question_id")
        require(isinstance(question_id, str) and question_id, f"Invalid question_id at {path}:{line_no}")
        require(question_id not in rows, f"Duplicate question_id {question_id!r} in {path}")
        require(isinstance(row.get("score_bool"), bool), f"Missing boolean score_bool for {question_id} in {path}")
        rows[question_id] = row
    require(bool(rows), f"No result rows in {path}")
    return rows


def build_attribution(groups: dict[str, dict[str, dict[str, Any]]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    require(set(groups) == {"aa", "ab", "ba", "bb"}, "Attribution requires aa, ab, ba, and bb")
    id_sets = {name: set(rows) for name, rows in groups.items()}
    require(len({frozenset(ids) for ids in id_sets.values()}) == 1, "Attribution question IDs do not match")
    question_ids = list(groups["aa"])
    for question_id in question_ids:
        reference = groups["aa"][question_id]
        for name in ("ab", "ba", "bb"):
            for field in COMPARABILITY_FIELDS:
                require(groups[name][question_id].get(field) == reference.get(field), f"Non-comparable {field} for {question_id}: aa vs {name}")

    diffs = []
    for question_id in question_ids:
        scores = {name: int(bool(rows[question_id]["score_bool"])) for name, rows in groups.items()}
        row = groups["aa"][question_id]
        diffs.append({
            "question_id": question_id,
            "question_type": row.get("question_type"),
            "category": row.get("category"),
            **{f"{name}_correct": bool(value) for name, value in scores.items()},
            "write_effect_recall_a": scores["ba"] - scores["aa"],
            "write_effect_recall_b": scores["bb"] - scores["ab"],
            "recall_effect_memory_a": scores["ab"] - scores["aa"],
            "recall_effect_memory_b": scores["bb"] - scores["ba"],
            "interaction": scores["bb"] - scores["ba"] - scores["ab"] + scores["aa"],
            **{f"{name}_response": groups[name][question_id].get("response_raw") for name in groups},
        })

    count = len(diffs)
    accuracy = {name: sum(bool(row["score_bool"]) for row in rows.values()) / count for name, rows in groups.items()}
    summary = {
        "design": {"aa": "writer A + recall A", "ab": "writer A + recall B", "ba": "writer B + recall A", "bb": "writer B + recall B"},
        "question_count": count,
        "accuracy": accuracy,
        "write_effect_recall_a": accuracy["ba"] - accuracy["aa"],
        "write_effect_recall_b": accuracy["bb"] - accuracy["ab"],
        "recall_effect_memory_a": accuracy["ab"] - accuracy["aa"],
        "recall_effect_memory_b": accuracy["bb"] - accuracy["ba"],
        "interaction": accuracy["bb"] - accuracy["ba"] - accuracy["ab"] + accuracy["aa"],
    }
    return summary, diffs


def render_markdown(summary: dict[str, Any]) -> str:
    accuracy = summary["accuracy"]
    return "\n".join([
        "# CodeAgent Memory Attribution Report", "",
        "This diagnostic 2×2 report is separate from the end-to-end baseline/candidate regression conclusion.", "",
        "| Cell | Configuration | Accuracy |", "|---|---|---:|",
        f"| AA | writer A + recall A | {accuracy['aa']:.2%} |",
        f"| AB | writer A + recall B | {accuracy['ab']:.2%} |",
        f"| BA | writer B + recall A | {accuracy['ba']:.2%} |",
        f"| BB | writer B + recall B | {accuracy['bb']:.2%} |", "",
        "| Attribution contrast | Delta |", "|---|---:|",
        f"| Write B−A under recall A | {summary['write_effect_recall_a']:+.2%} |",
        f"| Write B−A under recall B | {summary['write_effect_recall_b']:+.2%} |",
        f"| Recall B−A on memory A | {summary['recall_effect_memory_a']:+.2%} |",
        f"| Recall B−A on memory B | {summary['recall_effect_memory_b']:+.2%} |",
        f"| Interaction | {summary['interaction']:+.2%} |", "",
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare a 2x2 CodeAgent memory write/recall attribution run.")
    for name in ("aa", "ab", "ba", "bb"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    groups = {name: load_results(getattr(args, name)) for name in ("aa", "ab", "ba", "bb")}
    summary, diffs = build_attribution(groups)
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "attribution.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with (output_dir / "per_question_attribution.jsonl").open("w", encoding="utf-8") as handle:
        for row in diffs:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    (output_dir / "report.md").write_text(render_markdown(summary), encoding="utf-8")


if __name__ == "__main__":
    main()
