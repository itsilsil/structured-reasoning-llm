#!/usr/bin/env python3
"""Run Direct, CoT, and ToT-inspired experiments on fresh GSM8K questions."""

from __future__ import annotations

import argparse
import csv
import fcntl
import json
import random
import re
import secrets
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import torch
from datasets import load_dataset
from transformers import AutoModelForCausalLM, AutoTokenizer
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
PROMPT_DIR = ROOT / "prompts"
RESULTS_DIR = ROOT / "results"
RUNS_DIR = ROOT / "runs"
HISTORY_FILE = RUNS_DIR / "question_history.json"
LOCK_FILE = RUNS_DIR / ".question_history.lock"

NUMBER_RE = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?")
FINAL_RE = re.compile(r"Final\s+answer\s*:\s*([^\n\r]+)", re.IGNORECASE)
JUDGE_RE = re.compile(r"Best\s+candidate\s*:\s*(\d+)", re.IGNORECASE)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return fallback or {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback or {}


def normalize_number(value: str) -> str | None:
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
    if "####" not in answer_text:
        return None
    return normalize_number(answer_text.rsplit("####", 1)[1].strip())


def model_answer(output: str) -> str | None:
    matches = FINAL_RE.findall(output)
    return normalize_number(matches[-1]) if matches else None


def load_model(model_id: str):
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        model_id, torch_dtype="auto", device_map="auto"
    )
    model.eval()
    return tokenizer, model


def generate(tokenizer, model, prompt: str, max_new_tokens: int, sample: bool = False):
    messages = [
        {"role": "system", "content": "You are a careful assistant that solves arithmetic word problems."},
        {"role": "user", "content": prompt},
    ]
    rendered = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(rendered, return_tensors="pt")
    input_token_count = int(inputs["input_ids"].shape[1])
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
    started = time.perf_counter()
    with torch.inference_mode():
        output_ids = model.generate(**inputs, **generation_args)
    elapsed = time.perf_counter() - started
    new_ids = output_ids[0, inputs["input_ids"].shape[1]:]
    text = tokenizer.decode(new_ids, skip_special_tokens=True).strip()
    return text, int(new_ids.shape[0]), input_token_count, elapsed


def choose_candidate(judge_output: str, n_candidates: int) -> int | None:
    match = JUDGE_RE.fullmatch(judge_output.strip())
    if not match:
        return None
    selected = int(match.group(1))
    return selected if 1 <= selected <= n_candidates else None


def read_history() -> dict[str, Any]:
    history = read_json(HISTORY_FILE, {"version": 1, "used_indices": [], "runs": []})
    history.setdefault("version", 1)
    history.setdefault("used_indices", [])
    history.setdefault("runs", [])
    return history


def scan_existing_indices(dataset_size: int) -> set[int]:
    """Recover used IDs from the legacy pilot and saved run folders."""
    used: set[int] = set()
    folders = [RESULTS_DIR]
    if RUNS_DIR.exists():
        folders.extend(path for path in RUNS_DIR.iterdir() if path.is_dir())
    for folder in folders:
        jsonl_path = folder / "experiment_results.jsonl"
        if jsonl_path.exists():
            try:
                for line in jsonl_path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        index = int(json.loads(line)["dataset_index"])
                        if 0 <= index < dataset_size:
                            used.add(index)
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                pass
        config = read_json(folder / "run_config.json")
        for key in ("attempted_indices", "completed_indices"):
            for value in config.get(key, []):
                try:
                    index = int(value)
                    if 0 <= index < dataset_size:
                        used.add(index)
                except (TypeError, ValueError):
                    continue
    return used


def reserve_questions(dataset_size: int, sample_size: int, seed: int, run_id: str, allow_repeats: bool):
    """Atomically reserve IDs so concurrent runs cannot choose the same fresh questions."""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        history = read_history()
        recorded = {
            int(value) for value in history.get("used_indices", [])
            if str(value).lstrip("-").isdigit()
        }
        for entry in history.get("runs", []):
            if entry.get("status") == "running":
                recorded.update(int(x) for x in entry.get("reserved_indices", []))
        used = recorded | scan_existing_indices(dataset_size)
        available = list(range(dataset_size)) if allow_repeats else [
            index for index in range(dataset_size) if index not in used
        ]
        random.Random(seed).shuffle(available)
        selected = available[:sample_size]
        if len(selected) < sample_size:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            raise RuntimeError(
                f"Only {len(available)} unused questions remain, but {sample_size} were requested. "
                "Reduce --sample-size or use --allow-repeats intentionally."
            )
        history["runs"].append({
            "run_id": run_id,
            "created_at": utc_now(),
            "status": "running",
            "reserved_indices": selected,
            "attempted_indices": [],
            "allow_repeats": allow_repeats,
        })
        write_json_atomic(HISTORY_FILE, history)
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
    return selected, len(used)


def update_history_run(run_id: str, attempted_indices: list[int], status: str, error: str | None = None):
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        history = read_history()
        for entry in history.get("runs", []):
            if entry.get("run_id") == run_id:
                entry["attempted_indices"] = list(attempted_indices)
                entry["status"] = status
                entry["finished_at"] = utc_now() if status != "running" else None
                entry["reserved_indices"] = entry.get("reserved_indices", []) if status == "running" else []
                if error:
                    entry["error"] = error
                break
        if status in {"completed", "failed"}:
            history["used_indices"] = sorted(
                set(int(x) for x in history.get("used_indices", [])) | set(int(x) for x in attempted_indices)
            )
        write_json_atomic(HISTORY_FILE, history)
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def create_run_directory(requested: str | None):
    if requested:
        folder = Path(requested).expanduser()
        if not folder.is_absolute():
            folder = ROOT / folder
        if folder.exists() and any(folder.iterdir()):
            raise FileExistsError(f"Output directory is not empty: {folder}. Choose a new --output-dir.")
        folder.mkdir(parents=True, exist_ok=True)
        return folder.name, folder
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_id = f"run_{stamp}_{secrets.token_hex(3)}"
    folder = RUNS_DIR / run_id
    folder.mkdir(parents=True, exist_ok=False)
    return run_id, folder


def summarize(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[record["method"]].append(record)
    rows = []
    for method in ["Direct", "CoT", "ToT-inspired"]:
        items = grouped[method]
        count = len(items)
        rows.append({
            "method": method,
            "questions": count,
            "correct": sum(bool(row["correct"]) for row in items),
            "accuracy": sum(bool(row["correct"]) for row in items) / count if count else 0.0,
            "parseable_answers": sum(row.get("predicted_answer") is not None for row in items),
            "avg_input_tokens": sum(row.get("input_tokens", 0) for row in items) / count if count else 0.0,
            "avg_generated_tokens": sum(row.get("generated_tokens", 0) for row in items) / count if count else 0.0,
            "avg_total_tokens": sum(row.get("input_tokens", 0) + row.get("generated_tokens", 0) for row in items) / count if count else 0.0,
            "avg_generation_calls": sum(row.get("generation_calls", 0) for row in items) / count if count else 0.0,
            "avg_elapsed_seconds": sum(row.get("elapsed_seconds", 0) for row in items) / count if count else 0.0,
            "judge_failures": sum(row.get("judge_selection_valid") is False for row in items),
        })
    return rows


def main():
    parser = argparse.ArgumentParser(description="Compare reasoning methods on unused GSM8K test questions.")
    parser.add_argument("--model", default="Qwen/Qwen2.5-0.5B-Instruct")
    parser.add_argument("--sample-size", type=int, default=20)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--num-candidates", type=int, default=2)
    parser.add_argument("--output-dir", type=str, default=None)
    parser.add_argument("--allow-repeats", action="store_true",
                        help="Intentionally allow questions from previous runs to be sampled again.")
    args = parser.parse_args()
    if args.sample_size < 1 or args.num_candidates < 2:
        parser.error("--sample-size must be positive and --num-candidates must be at least 2")

    sample_seed = args.seed if args.seed is not None else secrets.randbelow(2**31 - 1)
    random.seed(sample_seed)
    torch.manual_seed(sample_seed)
    run_id, output_dir = create_run_directory(args.output_dir)
    jsonl_path = output_dir / "experiment_results.jsonl"
    summary_path = output_dir / "summary.csv"
    config_path = output_dir / "run_config.json"

    config: dict[str, Any] = {
        "run_id": run_id,
        "status": "loading",
        "created_at": utc_now(),
        "model": args.model,
        "dataset": "openai/gsm8k",
        "configuration": "main",
        "split": "test",
        "sample_size_requested": args.sample_size,
        "sample_seed": sample_seed,
        "sample_strategy": "random sample from unused dataset indices",
        "allow_repeats": args.allow_repeats,
        "max_new_tokens": args.max_new_tokens,
        "num_candidates": args.num_candidates,
        "output_directory": str(output_dir.relative_to(ROOT) if output_dir.is_relative_to(ROOT) else output_dir),
        "notes": [
            "New runs sample unused GSM8K test indices by default.",
            "The legacy results/ pilot is included when recovering previously used indices.",
            "ToT-inspired candidate generation and same-model judging; not full ToT.",
            "Generated tokens are an output-volume proxy, not monetary cost.",
            "Unparseable final answers are counted as incorrect.",
        ],
    }
    write_json_atomic(config_path, config)
    attempted_indices: list[int] = []
    started = time.perf_counter()
    run_reserved = False

    try:
        print("Loading GSM8K test split...")
        dataset = load_dataset("openai/gsm8k", "main", split="test")
        config["dataset_size"] = len(dataset)
        print(f"GSM8K test questions available: {len(dataset)}")

        print(f"Loading model: {args.model}")
        tokenizer, model = load_model(args.model)

        selected_indices, previously_used = reserve_questions(
            len(dataset), args.sample_size, sample_seed, run_id, args.allow_repeats
        )
        run_reserved = True
        config.update({
            "status": "running",
            "sample_size": len(selected_indices),
            "selected_indices": selected_indices,
            "attempted_indices": [],
            "completed_indices": [],
            "previously_used_questions": previously_used,
            "available_questions_before_run": len(dataset) - previously_used,
            "started_at": utc_now(),
        })
        write_json_atomic(config_path, config)
        print(f"Selected {len(selected_indices)} fresh questions ({previously_used} had been used before this run).")

        direct_template = read_prompt("direct_prompt.txt")
        cot_template = read_prompt("cot_prompt.txt")
        candidates_template = read_prompt("tot_candidates_prompt.txt")
        judge_template = read_prompt("tot_judge_prompt.txt")
        records: list[dict[str, Any]] = []

        for dataset_index in tqdm(selected_indices, desc="Questions"):
            attempted_indices.append(dataset_index)
            config["attempted_indices"] = list(attempted_indices)
            write_json_atomic(config_path, config)

            item = dataset[dataset_index]
            question = item["question"]
            target = gold_answer(item["answer"])

            direct_prompt = direct_template.format(question=question)
            direct_text, direct_tokens, direct_input, direct_time = generate(
                tokenizer, model, direct_prompt, args.max_new_tokens, sample=False
            )
            direct_prediction = model_answer(direct_text)
            records.append({
                "dataset_index": dataset_index, "question": question, "method": "Direct",
                "prompt": direct_prompt, "gold_answer": target, "predicted_answer": direct_prediction,
                "correct": direct_prediction == target and target is not None,
                "input_tokens": direct_input, "generated_tokens": direct_tokens,
                "generation_calls": 1, "elapsed_seconds": round(direct_time, 4), "raw_output": direct_text,
            })

            cot_prompt = cot_template.format(question=question)
            cot_text, cot_tokens, cot_input, cot_time = generate(
                tokenizer, model, cot_prompt, args.max_new_tokens, sample=False
            )
            cot_prediction = model_answer(cot_text)
            records.append({
                "dataset_index": dataset_index, "question": question, "method": "CoT",
                "prompt": cot_prompt, "gold_answer": target, "predicted_answer": cot_prediction,
                "correct": cot_prediction == target and target is not None,
                "input_tokens": cot_input, "generated_tokens": cot_tokens,
                "generation_calls": 1, "elapsed_seconds": round(cot_time, 4), "raw_output": cot_text,
            })

            candidate_texts, candidate_tokens, candidate_inputs, candidate_seconds = [], [], [], []
            candidate_prompt = candidates_template.format(question=question)
            for _ in range(args.num_candidates):
                candidate, token_count, input_count, elapsed = generate(
                    tokenizer, model, candidate_prompt, args.max_new_tokens, sample=True
                )
                candidate_texts.append(candidate)
                candidate_tokens.append(token_count)
                candidate_inputs.append(input_count)
                candidate_seconds.append(round(elapsed, 4))

            candidate_answers = [model_answer(text) for text in candidate_texts]
            candidate_block = "\n\n".join(
                f"Candidate {i + 1}:\nExtracted final answer: {answer if answer is not None else 'NOT PROVIDED'}\nCandidate solution:\n{text}"
                for i, (text, answer) in enumerate(zip(candidate_texts, candidate_answers))
            )
            judge_prompt = judge_template.format(question=question, candidates=candidate_block)
            judge_text, judge_tokens, judge_input, judge_time = generate(
                tokenizer, model, judge_prompt, min(args.max_new_tokens, 128), sample=False
            )
            selected = choose_candidate(judge_text, len(candidate_texts))
            selected_text = candidate_texts[selected - 1] if selected else ""
            prediction = model_answer(selected_text) if selected_text else None
            tot_input = sum(candidate_inputs) + judge_input
            tot_output = sum(candidate_tokens) + judge_tokens
            tot_time = sum(candidate_seconds) + judge_time
            tot_raw = {
                "candidates": candidate_texts,
                "candidate_answers": candidate_answers,
                "candidate_token_counts": candidate_tokens,
                "candidate_generation_seconds": candidate_seconds,
                "judge_output": judge_text,
                "judge_input_tokens": judge_input,
                "judge_generated_tokens": judge_tokens,
                "judge_seconds": round(judge_time, 4),
                "selected_candidate": selected,
                "selected_candidate_output": selected_text,
            }
            records.append({
                "dataset_index": dataset_index, "question": question, "method": "ToT-inspired",
                "prompt": candidate_prompt + "\n\n[JUDGE PROMPT]\n" + judge_prompt,
                "gold_answer": target, "predicted_answer": prediction,
                "correct": prediction == target and target is not None,
                "input_tokens": tot_input, "generated_tokens": tot_output,
                "generation_calls": args.num_candidates + 1, "elapsed_seconds": round(tot_time, 4),
                "candidate_answers": candidate_answers, "candidate_token_counts": candidate_tokens,
                "candidate_generation_seconds": candidate_seconds,
                "judge_selection_valid": selected is not None, "selected_candidate": selected,
                "judge_output": judge_text, "raw_output": json.dumps(tot_raw, ensure_ascii=False),
            })

            with jsonl_path.open("a", encoding="utf-8") as handle:
                for record in records[-3:]:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                handle.flush()
            config["completed_indices"] = list(attempted_indices)
            config["elapsed_seconds_so_far"] = round(time.perf_counter() - started, 2)
            write_json_atomic(config_path, config)

        summary_rows = summarize(records)
        with summary_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(summary_rows[0].keys()))
            writer.writeheader()
            writer.writerows(summary_rows)

        config.update({
            "status": "completed",
            "finished_at": utc_now(),
            "attempted_indices": list(attempted_indices),
            "completed_indices": list(attempted_indices),
            "elapsed_seconds": round(time.perf_counter() - started, 2),
            "notes": config["notes"] + [
                "Per-method elapsed_seconds measures model generation wall time for that question.",
                "Input and output token counts are recorded separately.",
            ],
        })
        write_json_atomic(config_path, config)
        update_history_run(run_id, attempted_indices, "completed")

        print("\nSummary")
        for row in summary_rows:
            print(
                f'{row["method"]:14s} accuracy={row["accuracy"]:.3f} '
                f'avg_input_tokens={row["avg_input_tokens"]:.1f} '
                f'avg_output_tokens={row["avg_generated_tokens"]:.1f} '
                f'avg_calls={row["avg_generation_calls"]:.1f} '
                f'avg_seconds={row["avg_elapsed_seconds"]:.2f}'
            )
        print(f"\nRun folder: {output_dir}")
        print(f"Saved: {jsonl_path}, {summary_path}, and {config_path}")

    except Exception as exc:
        config.update({
            "status": "failed",
            "finished_at": utc_now(),
            "attempted_indices": list(attempted_indices),
            "elapsed_seconds": round(time.perf_counter() - started, 2),
            "error": f"{type(exc).__name__}: {exc}",
        })
        write_json_atomic(config_path, config)
        if run_reserved:
            update_history_run(run_id, attempted_indices, "failed", str(exc))
        raise


if __name__ == "__main__":
    main()
