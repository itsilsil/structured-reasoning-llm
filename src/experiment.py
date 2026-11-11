#!/usr/bin/env python3
"""Pilot comparison of Direct, CoT, and a lightweight ToT-inspired strategy."""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import torch
from datasets import load_dataset
from transformers import AutoModelForCausalLM, AutoTokenizer
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
PROMPT_DIR = ROOT / "prompts"
RESULTS_DIR = ROOT / "results"

NUMBER_RE = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?")
FINAL_RE = re.compile(r"Final\s+answer\s*:\s*([^\n\r]+)", re.IGNORECASE)
JUDGE_RE = re.compile(r"Best\s+candidate\s*:\s*(\d+)", re.IGNORECASE)


def read_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def normalize_number(value: str) -> str | None:
    """Normalize a numeric answer without guessing from unrelated reasoning text."""
    match = NUMBER_RE.search(value.replace("$", "").strip())
    if not match:
        return None
    number = match.group(0).replace(",", "")
    try:
        numeric = float(number)
    except ValueError:
        return None
    if numeric.is_integer():
        return str(int(numeric))
    return format(numeric, ".10g")


def gold_answer(answer_text: str) -> str | None:
    # GSM8K marks its target answer after ####. Do not fall back to arbitrary numbers.
    if "####" not in answer_text:
        return None
    return normalize_number(answer_text.rsplit("####", 1)[1].strip())


def model_answer(output: str) -> str | None:
    # Only parse an explicitly marked final-answer line.
    matches = FINAL_RE.findall(output)
    if not matches:
        return None
    return normalize_number(matches[-1])


def load_model(model_id: str):
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        torch_dtype="auto",
        device_map="auto",
    )
    model.eval()
    return tokenizer, model


def generate(tokenizer, model, prompt: str, max_new_tokens: int, sample: bool = False):
    messages = [
        {"role": "system", "content": "You are a careful assistant that solves arithmetic word problems."},
        {"role": "user", "content": prompt},
    ]
    rendered = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    inputs = tokenizer(rendered, return_tensors="pt")
    model_device = next(model.parameters()).device
    inputs = {key: value.to(model_device) for key, value in inputs.items()}
    generation_args: dict[str, Any] = {
        "max_new_tokens": max_new_tokens,
        "do_sample": sample,
        "pad_token_id": tokenizer.pad_token_id,
        "eos_token_id": tokenizer.eos_token_id,
    }
    if sample:
        generation_args["temperature"] = 0.7
        generation_args["top_p"] = 0.9
    with torch.inference_mode():
        output_ids = model.generate(**inputs, **generation_args)
    new_ids = output_ids[0, inputs["input_ids"].shape[1]:]
    text = tokenizer.decode(new_ids, skip_special_tokens=True).strip()
    return text, int(new_ids.shape[0])


def choose_candidate(judge_output: str, n_candidates: int) -> int | None:
    match = JUDGE_RE.search(judge_output)
    if not match:
        return None
    selected = int(match.group(1))
    if 1 <= selected <= n_candidates:
        return selected
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="Qwen/Qwen2.5-1.5B-Instruct")
    parser.add_argument("--sample-size", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--num-candidates", type=int, default=3)
    args = parser.parse_args()

    if args.sample_size < 1 or args.num_candidates < 2:
        parser.error("--sample-size must be positive and --num-candidates must be at least 2")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    random.seed(args.seed)
    torch.manual_seed(args.seed)

    print("Loading GSM8K test split...")
    dataset = load_dataset("openai/gsm8k", "main", split="test")
    indices = list(range(len(dataset)))
    random.Random(args.seed).shuffle(indices)
    selected_indices = indices[: min(args.sample_size, len(indices))]

    print(f"Loading model: {args.model}")
    tokenizer, model = load_model(args.model)

    direct_template = read_prompt("direct_prompt.txt")
    cot_template = read_prompt("cot_prompt.txt")
    candidates_template = read_prompt("tot_candidates_prompt.txt")
    judge_template = read_prompt("tot_judge_prompt.txt")

    records: list[dict[str, Any]] = []
    started = time.time()

    for dataset_index in tqdm(selected_indices, desc="Questions"):
        item = dataset[dataset_index]
        question = item["question"]
        target = gold_answer(item["answer"])

        # Direct prompting: one generation call.
        direct_text, direct_tokens = generate(
            tokenizer, model, direct_template.format(question=question),
            args.max_new_tokens, sample=False
        )
        records.append({
            "dataset_index": dataset_index, "method": "Direct",
            "gold_answer": target, "predicted_answer": model_answer(direct_text),
            "correct": model_answer(direct_text) == target and target is not None,
            "generated_tokens": direct_tokens, "generation_calls": 1,
            "raw_output": direct_text,
        })

        # Chain of Thought: one sequential solution path.
        cot_text, cot_tokens = generate(
            tokenizer, model, cot_template.format(question=question),
            args.max_new_tokens, sample=False
        )
        records.append({
            "dataset_index": dataset_index, "method": "CoT",
            "gold_answer": target, "predicted_answer": model_answer(cot_text),
            "correct": model_answer(cot_text) == target and target is not None,
            "generated_tokens": cot_tokens, "generation_calls": 1,
            "raw_output": cot_text,
        })

        # ToT-inspired: sample candidate paths, then use the same model as a judge.
        candidate_texts: list[str] = []
        candidate_tokens = 0
        for _ in range(args.num_candidates):
            candidate, token_count = generate(
                tokenizer, model,
                candidates_template.format(n=args.num_candidates, question=question),
                args.max_new_tokens, sample=True
            )
            candidate_texts.append(candidate)
            candidate_tokens += token_count

        candidate_block = "\n\n".join(
            f"Candidate {i + 1}:\n{text}" for i, text in enumerate(candidate_texts)
        )
        judge_text, judge_tokens = generate(
            tokenizer, model,
            judge_template.format(question=question, candidates=candidate_block),
            min(args.max_new_tokens, 128), sample=False
        )
        selected = choose_candidate(judge_text, len(candidate_texts))
        selected_text = candidate_texts[selected - 1] if selected else ""
        prediction = model_answer(selected_text) if selected_text else None
        records.append({
            "dataset_index": dataset_index, "method": "ToT-inspired",
            "gold_answer": target, "predicted_answer": prediction,
            "correct": prediction == target and target is not None,
            "generated_tokens": candidate_tokens + judge_tokens,
            "generation_calls": args.num_candidates + 1,
            "selected_candidate": selected,
            "raw_output": json.dumps({
                "candidates": candidate_texts,
                "judge_output": judge_text,
                "selected_candidate_output": selected_text,
            }, ensure_ascii=False),
        })

    # Preserve full outputs for auditability and later error analysis.
    jsonl_path = RESULTS_DIR / "experiment_results.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[record["method"]].append(record)

    summary_rows = []
    for method in ["Direct", "CoT", "ToT-inspired"]:
        rows = grouped[method]
        n = len(rows)
        summary_rows.append({
            "method": method,
            "questions": n,
            "correct": sum(bool(row["correct"]) for row in rows),
            "accuracy": (sum(bool(row["correct"]) for row in rows) / n) if n else 0.0,
            "avg_generated_tokens": (
                sum(row["generated_tokens"] for row in rows) / n if n else 0.0
            ),
            "avg_generation_calls": (
                sum(row["generation_calls"] for row in rows) / n if n else 0.0
            ),
        })

    summary_path = RESULTS_DIR / "summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary_rows[0].keys()))
        writer.writeheader()
        writer.writerows(summary_rows)

    config = {
        "model": args.model,
        "dataset": "openai/gsm8k",
        "configuration": "main",
        "split": "test",
        "sample_size": len(selected_indices),
        "sample_seed": args.seed,
        "max_new_tokens": args.max_new_tokens,
        "num_candidates": args.num_candidates,
        "elapsed_seconds": round(time.time() - started, 2),
        "device_map": "auto",
        "notes": [
            "ToT-inspired candidate generation and same-model judging; not full ToT.",
            "Generated tokens are an output-volume proxy, not monetary cost.",
            "Unparseable final answers are counted as incorrect.",
        ],
    }
    (RESULTS_DIR / "run_config.json").write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print("\nSummary")
    for row in summary_rows:
        print(
            f'{row["method"]:14s} accuracy={row["accuracy"]:.3f} '
            f'avg_tokens={row["avg_generated_tokens"]:.1f} '
            f'avg_calls={row["avg_generation_calls"]:.1f}'
        )
    print(f"\nSaved: {jsonl_path}, {summary_path}, and results/run_config.json")


if __name__ == "__main__":
    main()
