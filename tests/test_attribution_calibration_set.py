import json
from pathlib import Path

from data.public_data import load_questions


def test_web_small_calibration_set_is_fixed_stratified_subset() -> None:
    repo = Path(__file__).resolve().parents[1]
    config = json.loads((repo / "evaluation/calibration_sets/codeagent_memory_web_small_10.json").read_text(encoding="utf-8"))
    ids = config["question_ids"]
    assert len(ids) == 10
    assert len(set(ids)) == 10
    rows = {row["id"]: row for row in load_questions(repo / "data/longmemeval-v2", domain="web")}
    selected_types = {rows[question_id]["question_type"] for question_id in ids}
    assert selected_types == {
        "static-environment", "dynamic-environment", "procedure", "errors-gotchas",
        "static-environment-abs", "dynamic-environment-abs", "procedure-abs",
    }
