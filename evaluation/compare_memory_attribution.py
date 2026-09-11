#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
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
            "question_text": row.get("question_text"),
            "answer_gold": row.get("answer_gold"),
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


def render_html(summary: dict[str, Any], diffs: list[dict[str, Any]]) -> str:
    def escaped(value: object) -> str:
        return html.escape("" if value is None else str(value))

    def percent(value: float, *, signed: bool = False) -> str:
        return f"{value:+.2%}" if signed else f"{value:.2%}"

    accuracy = summary["accuracy"]
    cells = {
        "AA": ("写入 A + 召回 A", accuracy["aa"]),
        "AB": ("写入 A + 召回 B", accuracy["ab"]),
        "BA": ("写入 B + 召回 A", accuracy["ba"]),
        "BB": ("写入 B + 召回 B", accuracy["bb"]),
    }
    cell_cards = "".join(
        f'<article class="cell"><span>{name}</span><strong>{percent(value)}</strong><small>{label}</small></article>'
        for name, (label, value) in cells.items()
    )
    effects = (
        ("写入效果 · 召回 A", summary["write_effect_recall_a"]),
        ("写入效果 · 召回 B", summary["write_effect_recall_b"]),
        ("召回效果 · 记忆 A", summary["recall_effect_memory_a"]),
        ("召回效果 · 记忆 B", summary["recall_effect_memory_b"]),
        ("交互效应", summary["interaction"]),
    )
    effect_rows = "".join(
        f'<tr><td>{label}</td><td class="delta {"positive" if value > 0 else "negative" if value < 0 else "neutral"}">{percent(value, signed=True)}</td></tr>'
        for label, value in effects
    )
    question_cards = []
    for row in diffs:
        response_cells = "".join(
            f'<div><b>{name.upper()}</b><span class="badge {"pass" if row[f"{name}_correct"] else "fail"}">{"正确" if row[f"{name}_correct"] else "错误"}</span><pre>{escaped(row.get(f"{name}_response"))}</pre></div>'
            for name in ("aa", "ab", "ba", "bb")
        )
        question_cards.append(
            f'<details><summary><code>{escaped(row["question_id"])}</code><span>{escaped(row.get("category"))}</span></summary>'
            f'<section class="question"><p><b>题目：</b>{escaped(row.get("question_text"))}</p>'
            f'<p><b>标准答案：</b>{escaped(row.get("answer_gold"))}</p><div class="responses">{response_cells}</div></section></details>'
        )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CodeAgent 记忆归因报告</title><style>
:root{{--bg:#f4f6fb;--panel:#fff;--ink:#182033;--muted:#697386;--line:#e2e7f0;--blue:#315bea;--green:#07865c;--red:#c33b4a}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,"Microsoft YaHei",sans-serif}}
main{{max-width:1080px;margin:auto;padding:42px 22px 70px}}header{{display:flex;justify-content:space-between;gap:24px;align-items:end;margin-bottom:28px}}
h1{{font-size:30px;margin:0 0 6px}}h2{{font-size:18px;margin:30px 0 12px}}p{{margin:6px 0}}.muted{{color:var(--muted)}}
.count{{background:#e8edff;color:var(--blue);padding:8px 13px;border-radius:20px;font-weight:700;white-space:nowrap}}
.matrix{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}.cell{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px;box-shadow:0 5px 18px #24365b0d}}
.cell span{{font-weight:800;color:var(--blue)}}.cell strong{{display:block;font-size:27px;margin:9px 0 2px}}.cell small{{color:var(--muted)}}
.panel{{background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden}}table{{width:100%;border-collapse:collapse}}td{{padding:13px 17px;border-bottom:1px solid var(--line)}}tr:last-child td{{border:0}}td:last-child{{text-align:right;font-weight:800}}
.positive{{color:var(--green)}}.negative{{color:var(--red)}}.neutral{{color:var(--muted)}}.note{{padding:14px 17px;border-left:4px solid var(--blue);background:#eef2ff;border-radius:8px}}
details{{background:var(--panel);border:1px solid var(--line);border-radius:12px;margin:10px 0;overflow:hidden}}summary{{cursor:pointer;padding:14px 17px;display:flex;gap:12px;align-items:center;font-weight:700}}summary span{{color:var(--muted);font-weight:500}}
.question{{padding:0 17px 17px;border-top:1px solid var(--line)}}.responses{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-top:14px}}.responses>div{{border:1px solid var(--line);border-radius:9px;padding:11px}}
.badge{{float:right;padding:2px 8px;border-radius:12px;font-size:12px}}.pass{{background:#dff6ed;color:var(--green)}}.fail{{background:#fde8eb;color:var(--red)}}pre{{white-space:pre-wrap;word-break:break-word;margin:10px 0 0;color:#374151}}
@media(max-width:760px){{.matrix{{grid-template-columns:repeat(2,1fr)}}.responses{{grid-template-columns:1fr}}header{{align-items:start;flex-direction:column}}}}
</style></head><body><main><header><div><h1>CodeAgent 记忆归因报告</h1><p class="muted">写入策略 × 召回算法 · 2×2 配对实验</p></div><div class="count">{summary['question_count']} 道题</div></header>
<div class="matrix">{cell_cards}</div><h2>归因结果</h2><div class="panel"><table>{effect_rows}</table></div>
<p class="note"><b>解读：</b>正值表示 B 优于 A，负值表示退化。交互效应不为零时，说明写入与召回的组合存在耦合。该诊断不替代端到端 baseline/candidate 回归结论。</p>
<h2>逐题结果</h2>{''.join(question_cards)}</main></body></html>"""


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
    (output_dir / "report.html").write_text(render_html(summary, diffs), encoding="utf-8")


if __name__ == "__main__":
    main()
