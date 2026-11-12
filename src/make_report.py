#!/usr/bin/env python3
"""Generate a detailed Markdown report for one saved experiment run."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def read_jsonl(path: Path):
    records = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
    return records


def code_block(value):
    return "~~~text\n" + str(value or "").replace("~~~", "'''") + "\n~~~"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", default="results", help="Folder containing one run's result files.")
    args = parser.parse_args()
    folder = Path(args.input_dir).expanduser().resolve()

    records = read_jsonl(folder / "experiment_results.jsonl")
    with (folder / "summary.csv").open(encoding="utf-8") as handle:
        summary = list(csv.DictReader(handle))
    config_path = folder / "run_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}

    grouped = {}
    for record in records:
        grouped.setdefault(int(record["dataset_index"]), {})[record["method"]] = record

    report = [
        "# Structured Reasoning Experiment Report",
        "",
        f"**Run ID:** {config.get('run_id', folder.name)}  ",
        f"**Questions in this run:** {len(grouped)}  ",
        f"**Dataset:** {config.get('dataset', 'openai/gsm8k')} · {config.get('split', 'test')}  ",
        f"**Dataset size:** {config.get('dataset_size', 'not recorded')}  ",
        f"**Model:** {config.get('model', 'not recorded')}",
        "",
        "## 1. Run configuration",
        "",
    ]
    for key, value in config.items():
        if key not in {"notes", "error"}:
            report.append(f"- **{key}:** {value}")
    for note in config.get("notes", []):
        report.append(f"- Note: {note}")
    if config.get("error"):
        report += ["", f"**Run error:** {config['error']}"]

    report += [
        "",
        "## 2. Aggregate results",
        "",
        "| Method | Questions | Correct | Accuracy | Avg input tokens | Avg output tokens | Avg calls | Avg seconds | Judge failures |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary:
        report.append(
            f"| {row['method']} | {row['questions']} | {row['correct']} "
            f"| {float(row['accuracy']) * 100:.1f}% "
            f"| {float(row.get('avg_input_tokens', 0)):.1f} "
            f"| {float(row['avg_generated_tokens']):.1f} "
            f"| {float(row['avg_generation_calls']):.1f} "
            f"| {float(row.get('avg_elapsed_seconds', 0)):.2f} "
            f"| {row.get('judge_failures', 0)} |"
        )

    report += ["", "## 3. Question-by-question inspection", ""]
    for number, (index, methods) in enumerate(sorted(grouped.items()), 1):
        first = next(iter(methods.values()))
        report += [
            f"### Question {number} · GSM8K index {index}",
            "",
            "**Problem statement**",
            "",
            first.get("question", "Question text not stored."),
            "",
            f"**Gold answer:** {first.get('gold_answer')}",
            "",
        ]
        for method in ["Direct", "CoT", "ToT-inspired"]:
            row = methods.get(method)
            if not row:
                continue
            report += [
                f"#### {method}",
                "",
                f"- Predicted answer: {row.get('predicted_answer')}",
                f"- Correct: {row.get('correct')}",
                f"- Input tokens: {row.get('input_tokens', 0)}",
                f"- Output tokens: {row.get('generated_tokens', 0)}",
                f"- Generation calls: {row.get('generation_calls', 0)}",
                f"- Generation time (seconds): {row.get('elapsed_seconds', 0)}",
                "",
                "**Prompt**",
                "",
                code_block(row.get("prompt", "")),
                "",
            ]
            if method == "ToT-inspired":
                try:
                    raw = json.loads(row.get("raw_output", "{}"))
                except (TypeError, json.JSONDecodeError):
                    raw = {}
                for i, candidate in enumerate(raw.get("candidates", []), 1):
                    report += [f"**Candidate {i}**", "", code_block(candidate), ""]
                report += [
                    f"**Judge selection:** {raw.get('selected_candidate')}",
                    "",
                    "**Judge output**",
                    "",
                    code_block(raw.get("judge_output", "")),
                    "",
                    "**Selected candidate output**",
                    "",
                    code_block(raw.get("selected_candidate_output", "")),
                    "",
                ]
            else:
                report += ["**Raw model output**", "", code_block(row.get("raw_output", "")), ""]

    report += [
        "",
        "## 4. Interpretation notes",
        "",
        "- This report describes this run only; it is not the entire GSM8K test set.",
        "- The question history prevents previously attempted dataset indices from being sampled again in default mode.",
        "- ToT-inspired is not a full Tree of Thoughts search implementation.",
        "- The candidate generator and judge use the same model.",
        "- Token counts are workload proxies, not direct monetary-cost or energy measurements.",
        "- Visible model outputs should not be treated as proof of the model's internal reasoning process.",
    ]

    report_path = folder / "question_report.md"
    report_path.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"Report saved: {report_path}")


if __name__ == "__main__":
    main()
