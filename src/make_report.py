import csv
import json
import re
from pathlib import Path
from collections import defaultdict

import matplotlib.pyplot as plt
from datasets import load_dataset

RESULTS = Path("results")
JSONL_FILE = RESULTS / "experiment_results.jsonl"
CSV_FILE = RESULTS / "summary.csv"

# Read experiment records
records = []
with open(JSONL_FILE, encoding="utf-8") as f:
    for line in f:
        if line.strip():
            records.append(json.loads(line))

# Read summary
with open(CSV_FILE, encoding="utf-8") as f:
    summary = list(csv.DictReader(f))

# Retrieve the original GSM8K questions
dataset = load_dataset("openai/gsm8k", "main", split="test")

questions = {}
for row in records:
    index = int(row["dataset_index"])
    questions[index] = dataset[index]["question"]

# Group results by question
grouped = defaultdict(dict)
for row in records:
    grouped[int(row["dataset_index"])][row["method"]] = row

# Create accuracy chart
methods = [row["method"] for row in summary]
accuracies = [float(row["accuracy"]) * 100 for row in summary]

plt.figure(figsize=(8, 5))
bars = plt.bar(methods, accuracies)

plt.title("Accuracy Comparison")
plt.ylabel("Accuracy (%)")
plt.xlabel("Reasoning Method")
plt.ylim(0, 100)

for bar, value in zip(bars, accuracies):
    plt.text(
        bar.get_x() + bar.get_width() / 2,
        bar.get_height() + 2,
        f"{value:.1f}%",
        ha="center"
    )

plt.tight_layout()
plt.savefig(RESULTS / "accuracy_comparison.png", dpi=200)
plt.close()

# Helpers
def show_answer(value):
    return "Not extracted" if value is None else str(value)

def show_correct(value):
    return "Correct" if value else "Incorrect"

def code_block(text):
    text = str(text or "").replace("```", "'''")
    return f"```text\n{text}\n```"

# Build detailed report
report = [
    "# Structured Reasoning Experiment — Final 10-Question Report",
    "",
    "> Final report for the 10-question experiment.",
    "",
    "## 1. Experiment configuration",
    "",
]

config_path = RESULTS / "run_config.json"
if config_path.exists():
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    for key, value in config.items():
        if key != "notes":
            report.append(f"- **{key}:** {value}")

    for note in config.get("notes", []):
        report.append(f"- Note: {note}")

report += [
    "",
    "## 2. Accuracy comparison",
    "",
    "![Accuracy comparison](accuracy_comparison.png)",
    "",
    "| Method | Questions | Correct | Accuracy | Avg. generated tokens | Avg. generation calls |",
    "|---|---:|---:|---:|---:|---:|",
]

for row in summary:
    report.append(
        f"| {row['method']} "
        f"| {row['questions']} "
        f"| {row['correct']} "
        f"| {float(row['accuracy']) * 100:.1f}% "
        f"| {float(row['avg_generated_tokens']):.1f} "
        f"| {float(row['avg_generation_calls']):.1f} |"
    )

report += ["", "## 3. Question-by-question results", ""]

for number, (index, methods_data) in enumerate(sorted(grouped.items()), 1):
    report += [
        f"### Question {number} (dataset index: {index})",
        "",
        "**Problem:**",
        "",
        questions[index],
        "",
    ]

    # Gold answer
    first_record = next(iter(methods_data.values()))
    report += [
        f"**Correct answer:** {first_record['gold_answer']}",
        "",
    ]

    # Direct and CoT
    for method in ["Direct", "CoT"]:
        if method not in methods_data:
            continue

        row = methods_data[method]
        report += [
            f"#### {method}",
            "",
            f"- Predicted answer: {show_answer(row['predicted_answer'])}",
            f"- Result: {show_correct(row['correct'])}",
            f"- Generated tokens: {row['generated_tokens']}",
            f"- Generation calls: {row['generation_calls']}",
            "",
            "**Model output:**",
            "",
            code_block(row["raw_output"]),
            "",
        ]

    # ToT-inspired
    if "ToT-inspired" in methods_data:
        row = methods_data["ToT-inspired"]

        report += [
            "#### ToT-inspired",
            "",
            f"- Predicted answer: {show_answer(row['predicted_answer'])}",
            f"- Result: {show_correct(row['correct'])}",
            f"- Generated tokens: {row['generated_tokens']}",
            f"- Generation calls: {row['generation_calls']}",
            "",
        ]

        try:
            raw = json.loads(row["raw_output"])
        except (TypeError, json.JSONDecodeError):
            raw = {}

        candidates = raw.get("candidates", [])
        judge_output = raw.get("judge_output", "")
        selected_output = raw.get("selected_candidate_output", "")

        # Strictly validate the judge's response format
        match = re.fullmatch(
            r"\s*Best\s+candidate\s*:\s*(\d+)\s*",
            str(judge_output),
            re.IGNORECASE
        )

        selected_number = int(match.group(1)) if match else None
        judge_valid = (
            selected_number is not None
            and 1 <= selected_number <= len(candidates)
        )

        report += [
            f"- Judge selection format valid: {'Yes' if judge_valid else 'No'}",
            "",
            "**Generated candidates:**",
            "",
        ]

        for i, candidate in enumerate(candidates, 1):
            report += [
                f"Candidate {i}:",
                "",
                code_block(candidate),
                "",
            ]

        report += [
            "**Judge output:**",
            "",
            code_block(judge_output),
            "",
            "**Selected candidate output:**",
            "",
            code_block(selected_output),
            "",
        ]

# Overall conclusion
total_questions = len(grouped)
best = max(summary, key=lambda x: float(x["accuracy"])) if summary else None

report += [
    "## 4. Conclusion and limitations",
    "",
    f"This experiment evaluated {total_questions} questions using three reasoning methods.",
    "",
]

if best:
    report.append(
        f"The highest observed accuracy in this experiment was achieved by "
        f"**{best['method']}**, at "
        f"**{float(best['accuracy']) * 100:.1f}%**."
    )

report += [
    "",
    "The sample contains only 10 questions, so the results are limited and do not support broad general conclusions.",
    "",
    "The ToT-inspired method uses multiple candidate generations followed by a selection step. This increases generation calls and output-token usage compared with Direct and CoT.",
    "",
    "Generated-token counts are used as an output-volume proxy, not as a direct measurement of monetary cost or total computational cost.",
    "",
    "This implementation is ToT-inspired rather than a full Tree of Thoughts search. Candidate generation and selection are performed using the same language model.",
    "",
    "Unextracted final answers are treated as incorrect for the accuracy calculation.",
    "",
    "This 10-question run provides a small-scale comparison; further evaluation on a larger sample would be needed for stronger conclusions.",
]

# Save report
with open(RESULTS / "question_report.md", "w", encoding="utf-8") as f:
    f.write("\n".join(report))

print("Report generated successfully.")
print(f"- {RESULTS / 'accuracy_comparison.png'}")
print(f"- {RESULTS / 'question_report.md'}")
