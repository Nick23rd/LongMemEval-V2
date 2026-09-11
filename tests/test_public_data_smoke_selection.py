import json
from pathlib import Path

import pytest

from data.public_data import materialize_runtime_haystack


def test_materialize_runtime_haystack_can_limit_structural_smoke_data(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    (data_root / "haystacks").mkdir(parents=True)
    (data_root / "haystacks" / "lme_v2_small.json").write_text(
        json.dumps({"q1": ["t1", "t2", "t3"]}), encoding="utf-8"
    )
    output = tmp_path / "runtime" / "haystack.json"
    output.parent.mkdir()

    result = materialize_runtime_haystack(
        data_root=data_root,
        tier="small",
        selected_questions=[{"id": "q1"}],
        output_path=output,
        trajectory_limit=2,
    )

    assert result == {"q1": ["t1", "t2"]}
    assert json.loads(output.read_text(encoding="utf-8")) == result


def test_materialize_runtime_haystack_rejects_nonpositive_limit(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    (data_root / "haystacks").mkdir(parents=True)
    (data_root / "haystacks" / "lme_v2_small.json").write_text(
        json.dumps({"q1": ["t1"]}), encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="positive"):
        materialize_runtime_haystack(
            data_root=data_root,
            tier="small",
            selected_questions=[{"id": "q1"}],
            output_path=tmp_path / "out.json",
            trajectory_limit=0,
        )

