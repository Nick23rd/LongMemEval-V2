"""Build one browser-friendly JSON document from a retained single evaluation."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RESULT_FILENAME = "evaluation_result.json"
REPORT_FILENAME = "report.html"


def read_json(path: Path) -> Any:
    if not path.is_file():
        raise RuntimeError(f"Missing required result artifact: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[Any]:
    if not path.is_file():
        raise RuntimeError(f"Missing required result artifact: {path}")
    rows: list[Any] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid JSONL at {path}:{line_number}: {exc.msg}") from exc
    return rows


def read_optional_json(path: Path) -> Any | None:
    return read_json(path) if path.is_file() else None


def build_result(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    runner = read_json(run_dir / "runner_config.json")
    metrics = read_json(run_dir / "evaluate" / "aggregated_metrics.json")
    questions = read_jsonl(run_dir / "evaluate" / "per_question.jsonl")
    identity = runner.get("run_identity", {})
    mode = identity.get("experiment_mode")
    if mode not in {"single", "memory_off"}:
        raise RuntimeError(f"Unsupported single-run experiment mode: {mode!r}")

    return {
        "schema_version": 1,
        "document_type": "longmemeval_v2_codeagent_single_run",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run": {
            "experiment_mode": mode,
            "memory_enabled": mode == "single",
            "identity": identity,
            "config": runner.get("config", {}),
        },
        "selection": read_optional_json(run_dir / "build" / "runtime_inputs" / "data_selection.json"),
        "metrics": metrics,
        "questions": questions,
        "build": {
            "ingestion_metrics": read_optional_json(run_dir / "build" / "memory_state" / "ingestion_metrics.json"),
            "ingestion_manifest": read_optional_json(run_dir / "build" / "memory_state" / "ingestion_manifest.json"),
        },
        "artifacts": {
            "runner_config": "runner_config.json",
            "build_directory": "build",
            "evaluation_directory": "evaluate",
            "per_question_jsonl": "evaluate/per_question.jsonl",
            "aggregated_metrics": "evaluate/aggregated_metrics.json",
            "html_report": REPORT_FILENAME,
        },
    }


def write_result(run_dir: Path) -> Path:
    output_path = run_dir.resolve() / RESULT_FILENAME
    payload = build_result(run_dir)
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    report_template = Path(__file__).with_name("codeagent_memory_results.html")
    if not report_template.is_file():
        raise RuntimeError(f"Missing HTML report template: {report_template}")
    (run_dir.resolve() / REPORT_FILENAME).write_text(
        report_template.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Combine a retained CodeAgent single run into browser-friendly JSON."
    )
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    output_path = write_result(Path(args.run_dir))
    print(output_path)


if __name__ == "__main__":
    main()
