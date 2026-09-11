import json
from pathlib import Path

import pytest

from evaluation.compare_memory_attribution import build_attribution, load_results, load_writer_metrics, render_html


def row(question_id: str, score: bool, *, text: str = "question") -> dict[str, object]:
    return {
        "question_id": question_id, "score_bool": score, "question_text": text,
        "question_type": "single", "category": "fact", "eval_function": "exact",
        "answer_gold": "yes", "haystack_ids": ["t1"], "response_raw": str(score),
    }


def test_build_attribution_computes_four_contrasts() -> None:
    groups = {
        "aa": {"q": row("q", False)}, "ab": {"q": row("q", True)},
        "ba": {"q": row("q", False)}, "bb": {"q": row("q", True)},
    }
    summary, diffs = build_attribution(groups)
    assert summary["recall_effect_memory_a"] == 1.0
    assert summary["recall_effect_memory_b"] == 1.0
    assert summary["write_effect_recall_a"] == 0.0
    assert summary["interaction"] == 0.0
    assert diffs[0]["recall_effect_memory_a"] == 1


def test_build_attribution_rejects_non_comparable_input() -> None:
    groups = {name: {"q": row("q", False)} for name in ("aa", "ab", "ba", "bb")}
    groups["bb"]["q"] = row("q", False, text="changed")
    with pytest.raises(RuntimeError, match="Non-comparable question_text"):
        build_attribution(groups)


def test_load_results_rejects_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "per_question.jsonl"
    encoded = json.dumps(row("q", True))
    path.write_text(encoded + "\n" + encoded + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Duplicate question_id"):
        load_results(path)


def test_render_html_contains_summary_and_escaped_question() -> None:
    groups = {name: {"q": row("q", name == "bb", text="<unsafe>")} for name in ("aa", "ab", "ba", "bb")}
    summary, diffs = build_attribution(groups)
    output = render_html(summary, diffs)
    assert "<!doctype html>" in output
    assert "&lt;unsafe&gt;" in output
    assert "写入策略 × 召回算法" in output


def test_load_writer_metrics_reads_provenance_and_cost(tmp_path: Path) -> None:
    (tmp_path / "ingestion_manifest.json").write_text(json.dumps({
        "version_label": "candidate", "detected_ingest_version": "2.0",
        "ingest_launcher_command": ["candidate.exe"], "prompt_hashes": {"ingest": "abc"},
        "memory_snapshot_digest": "digest",
    }), encoding="utf-8")
    (tmp_path / "ingestion_metrics.json").write_text(json.dumps({
        "trajectory_count": 10, "failed_attempt_count": 1,
        "usage_totals": {"total_cost_usd": 1.25},
    }), encoding="utf-8")
    metrics = load_writer_metrics(tmp_path)
    assert metrics["detected_version"] == "2.0"
    assert metrics["trajectory_count"] == 10
    assert metrics["usage"]["total_cost_usd"] == 1.25
