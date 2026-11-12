from __future__ import annotations

import json
import re
import zipfile
from io import BytesIO
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parent
METHODS = ["Direct", "CoT", "ToT-inspired"]
LABELS = {"Direct": "Direct", "CoT": "Chain of Thought (CoT)", "ToT-inspired": "ToT-inspired"}

st.set_page_config(page_title="Structured Reasoning Dashboard", page_icon="🧠", layout="wide")
st.markdown("""
<style>
.block-container {padding-top:1.5rem;padding-bottom:3rem}
[data-testid="stMetricValue"] {font-size:1.8rem}
[data-testid="stMetricLabel"] {font-size:.95rem}
</style>
""", unsafe_allow_html=True)


def discover_runs():
    folders = [ROOT / "results"]
    runs_dir = ROOT / "runs"
    if runs_dir.exists():
        folders += [path for path in runs_dir.iterdir() if path.is_dir()]
    found = {}
    for folder in folders:
        if (folder / "summary.csv").exists() and (folder / "experiment_results.jsonl").exists():
            label = "پایلوت اولیه (results)" if folder.name == "results" else folder.name
            found[label] = folder
    return found


def load_run(folder):
    summary = pd.read_csv(folder / "summary.csv")
    records = [
        json.loads(line)
        for line in (folder / "experiment_results.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    details = pd.DataFrame(records)
    config_path = folder / "run_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    report_path = folder / "question_report.md"
    report = report_path.read_text(encoding="utf-8") if report_path.exists() else None

    # Legacy pilot JSONL did not store question text. Recover it from its
    # accompanying Markdown report so the old run remains fully inspectable.
    if report and not details.empty:
        report_questions = {}
        blocks = re.split(r"(?=^### Question \\d+ \\(dataset index: \\d+\\)\\s*$)", report, flags=re.MULTILINE)
        for block in blocks:
            index_match = re.search(r"^### Question \\d+ \\(dataset index: (\\d+)\\)", block, flags=re.MULTILINE)
            problem_match = re.search(r"\\*\\*Problem:\\*\\*\\s*(.*?)\\s*\\*\\*Correct answer:\\*\\*", block, flags=re.DOTALL)
            answer_match = re.search(r"\\*\\*Correct answer:\\*\\*\\s*(.*?)\\s*(?=^#### Direct)", block, flags=re.DOTALL | re.MULTILINE)
            if index_match and problem_match:
                idx = int(index_match.group(1))
                report_questions[idx] = {
                    "question": problem_match.group(1).strip(),
                    "report_gold_answer": answer_match.group(1).strip() if answer_match else None,
                }
        if report_questions:
            details["question"] = details["dataset_index"].astype(int).map(
                lambda idx: report_questions.get(idx, {}).get("question", "متن سؤال در گزارش پیدا نشد.")
            )
            if "gold_answer" not in details.columns:
                details["gold_answer"] = details["dataset_index"].astype(int).map(
                    lambda idx: report_questions.get(idx, {}).get("report_gold_answer")
                )

    if not details.empty:
        details["method"] = pd.Categorical(details["method"], METHODS, ordered=True)
        details = details.sort_values(["dataset_index", "method"])
    return summary, details, config, report


def make_zip(folder, details):
    memory = BytesIO()
    with zipfile.ZipFile(memory, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ["summary.csv", "experiment_results.jsonl", "run_config.json", "question_report.md"]:
            path = folder / name
            if path.exists():
                archive.write(path, arcname=name)
        if not details.empty:
            archive.writestr("question_details.csv", details.to_csv(index=False))
    return memory.getvalue()


def pct(value):
    return f"{float(value) * 100:.1f}%"


st.title("🧠 Structured Reasoning Dashboard")
st.caption("تحلیل کامل مقایسه Direct، Chain of Thought و ToT-inspired روی GSM8K")
runs = discover_runs()
if not runs:
    st.error("هنوز اجرای کاملی پیدا نشده است. ابتدا آزمایش را اجرا کنید.")
    st.stop()

with st.sidebar:
    st.header("کنترل پنل")
    selected = st.selectbox("اجرای مورد بررسی", list(runs))
    comparisons = st.multiselect("مقایسه با اجراهای دیگر", [name for name in runs if name != selected])
    st.divider()
    st.caption("داشبورد فقط داده‌های ذخیره‌شده را می‌خواند و مدل را اجرا نمی‌کند.")
    st.code(str(runs[selected].relative_to(ROOT)))

folder = runs[selected]
summary, details, config, report = load_run(folder)
st.subheader("مشخصات اجرا")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("سؤال‌های این اجرا", int(config.get("sample_size", details["dataset_index"].nunique() if not details.empty else 0)))
c2.metric("کل سؤال‌های GSM8K test", config.get("dataset_size", "—"))
c3.metric("سؤال‌های استفاده‌شده پیش از اجرا", config.get("previously_used_questions", "—"))
c4.metric("Seed", config.get("sample_seed", "—"))
elapsed = config.get("elapsed_seconds")
c5.metric("زمان کل اجرا", f"{float(elapsed)/60:.1f} دقیقه" if elapsed is not None else "—")
st.caption(f"Run ID: {config.get('run_id', folder.name)} · وضعیت: {config.get('status', 'legacy')}")
with st.expander("تنظیمات و شناسه سؤال‌های این اجرا"):
    st.json(config)

st.divider()
st.subheader("مقایسه عملکرد روش‌ها")
summary = summary.copy()
summary["accuracy_percent"] = summary["accuracy"].astype(float) * 100
summary["method_label"] = summary["method"].map(LABELS).fillna(summary["method"])

kpis = st.columns(4)
for col, title, field, is_pct in zip(
    kpis,
    ["دقت CoT", "میانگین توکن خروجی CoT", "فراخوانی CoT", "زمان متوسط CoT"],
    ["accuracy", "avg_generated_tokens", "avg_generation_calls", "avg_elapsed_seconds"],
    [True, False, False, False],
):
    row = summary[summary["method"] == "CoT"]
    value = row.iloc[0][field] if not row.empty and field in row else None
    col.metric(title, pct(value) if is_pct and value is not None else (f"{float(value):.2f}" if value is not None else "—"))

overview, questions, tot_tab, downloads = st.tabs([
    "📊 مقایسه کلی", "🔎 بررسی کامل سؤال‌ها", "🌳 تحلیل ToT-inspired", "📦 دریافت خروجی‌ها"
])

with overview:
    chart_specs = [
        ("accuracy_percent", "دقت پاسخ نهایی (%)", 100, "%"),
        ("avg_input_tokens", "میانگین توکن ورودی", None, ""),
        ("avg_generated_tokens", "میانگین توکن خروجی", None, ""),
        ("avg_generation_calls", "میانگین فراخوانی مدل", None, ""),
        ("avg_elapsed_seconds", "میانگین زمان تولید برای هر سؤال (ثانیه)", None, ""),
        ("judge_failures", "خطاهای قالب داوری", None, ""),
    ]
    for start in range(0, len(chart_specs), 2):
        left, right = st.columns(2)
        for col, spec in zip([left, right], chart_specs[start:start + 2]):
            field, title, ymax, suffix = spec
            if field not in summary.columns:
                continue
            with col:
                fig = px.bar(
                    summary, x="method_label", y=field, color="method_label",
                    text_auto=".1f", title=title,
                    labels={"method_label": "روش", field: title},
                )
                if ymax:
                    fig.update_yaxes(range=[0, ymax], ticksuffix=suffix)
                fig.update_layout(showlegend=False, xaxis_title="", yaxis_title=title)
                st.plotly_chart(fig, width="stretch")

    st.markdown("#### جدول عددی مقایسه")
    columns = [
        "method", "questions", "correct", "accuracy", "parseable_answers",
        "avg_input_tokens", "avg_generated_tokens", "avg_total_tokens",
        "avg_generation_calls", "avg_elapsed_seconds", "judge_failures",
    ]
    table = summary[[name for name in columns if name in summary.columns]].copy()
    if "accuracy" in table:
        table["accuracy"] = table["accuracy"].map(pct)
    table = table.rename(columns={
        "method": "روش", "questions": "تعداد سؤال", "correct": "پاسخ صحیح",
        "accuracy": "دقت", "parseable_answers": "پاسخ قابل استخراج",
        "avg_input_tokens": "توکن ورودی", "avg_generated_tokens": "توکن خروجی",
        "avg_total_tokens": "مجموع توکن", "avg_generation_calls": "فراخوانی",
        "avg_elapsed_seconds": "زمان متوسط (ثانیه)", "judge_failures": "خطای داوری",
    })
    st.dataframe(table, width="stretch", hide_index=True)

    if comparisons:
        st.markdown("#### مقایسه اجراهای مستقل")
        rows = []
        for label in [selected] + comparisons:
            run_summary, _, run_config, _ = load_run(runs[label])
            for _, row in run_summary.iterrows():
                rows.append({
                    "اجرا": label, "روش": row["method"],
                    "دقت (%)": float(row["accuracy"]) * 100,
                    "توکن خروجی": float(row["avg_generated_tokens"]),
                    "فراخوانی": float(row["avg_generation_calls"]),
                    "زمان متوسط": float(row.get("avg_elapsed_seconds", 0)),
                    "تعداد سؤال": int(row["questions"]),
                    "Seed": run_config.get("sample_seed", "—"),
                })
        comparison = pd.DataFrame(rows)
        metric = st.selectbox("معیار مقایسه اجراها", ["دقت (%)", "توکن خروجی", "فراخوانی", "زمان متوسط"])
        fig = px.line(comparison, x="اجرا", y=metric, color="روش", markers=True, hover_data=["تعداد سؤال", "Seed"])
        st.plotly_chart(fig, width="stretch")
        st.dataframe(comparison, width="stretch", hide_index=True)

with questions:
    if details.empty:
        st.warning("جزئیات سؤال‌ها موجود نیست.")
    else:
        question_ids = sorted(details["dataset_index"].astype(int).unique().tolist())
        selected_id = st.selectbox("انتخاب سؤال", question_ids, format_func=lambda value: f"سؤال {value} از GSM8K test")
        rows = details[details["dataset_index"].astype(int) == int(selected_id)]
        first = rows.iloc[0]
        st.markdown("### صورت کامل مسئله")
        st.markdown(first.get("question", "متن سؤال در فایل ذخیره نشده است."))
        st.markdown(f"**پاسخ مرجع GSM8K:** {first.get('gold_answer', '—')}")

        for _, row in rows.iterrows():
            method = str(row["method"])
            with st.expander(f"{LABELS.get(method, method)} · {'درست' if bool(row['correct']) else 'نادرست'}", expanded=True):
                a, b, c, d, e = st.columns(5)
                a.metric("نتیجه", "درست" if bool(row["correct"]) else "نادرست")
                b.metric("پاسخ مدل", str(row.get("predicted_answer") or "استخراج نشد"))
                c.metric("توکن ورودی", int(row.get("input_tokens", 0)))
                d.metric("توکن خروجی", int(row.get("generated_tokens", 0)))
                e.metric("زمان (ثانیه)", f"{float(row.get('elapsed_seconds', 0)):.2f}")
                st.markdown("**پرامپت ارسال‌شده به مدل**")
                st.code(str(row.get("prompt", "")), language="text")
                if method == "ToT-inspired":
                    try:
                        raw = json.loads(str(row.get("raw_output", "{}")))
                    except json.JSONDecodeError:
                        raw = {}
                    candidates = raw.get("candidates", [])
                    candidate_answers = raw.get("candidate_answers", row.get("candidate_answers", []))
                    candidate_tokens = raw.get("candidate_token_counts", row.get("candidate_token_counts", []))
                    candidate_times = raw.get("candidate_generation_seconds", row.get("candidate_generation_seconds", []))
                    st.markdown("**مسیرهای پیشنهادی**")
                    for i, candidate in enumerate(candidates):
                        answer = candidate_answers[i] if i < len(candidate_answers) else "—"
                        tokens = candidate_tokens[i] if i < len(candidate_tokens) else "—"
                        seconds = candidate_times[i] if i < len(candidate_times) else "—"
                        st.markdown(f"**Candidate {i + 1}** · پاسخ استخراج‌شده: {answer} · توکن: {tokens} · زمان: {seconds} ثانیه")
                        st.code(candidate, language="text")
                    st.markdown(f"**انتخاب داور:** {raw.get('selected_candidate', row.get('selected_candidate', '—'))}")
                    st.markdown("**خروجی خام داور**")
                    st.code(raw.get("judge_output", row.get("judge_output", "")), language="text")
                    st.markdown("**خروجی مسیر انتخاب‌شده**")
                    st.code(raw.get("selected_candidate_output", ""), language="text")
                st.markdown("**خروجی خام کامل مدل**")
                st.code(str(row.get("raw_output", "")), language="text")

        st.markdown("#### مقایسه سه روش روی همین مسئله")
        view_cols = [
            "method", "gold_answer", "predicted_answer", "correct", "input_tokens",
            "generated_tokens", "generation_calls", "elapsed_seconds",
        ]
        view = rows[[name for name in view_cols if name in rows.columns]].copy()
        st.dataframe(view, width="stretch", hide_index=True)

with tot_tab:
    tot = details[details["method"].astype(str) == "ToT-inspired"] if not details.empty else pd.DataFrame()
    if tot.empty:
        st.info("رکورد ToT-inspired وجود ندارد.")
    else:
        valid = int(tot.get("judge_selection_valid", pd.Series([False] * len(tot))).fillna(False).astype(bool).sum())
        a, b, c = st.columns(3)
        a.metric("مسائل ToT-inspired", len(tot))
        b.metric("قالب داوری معتبر", valid)
        c.metric("خطای قالب داوری", len(tot) - valid)
        st.caption("اعتبار قالب فقط به معنی قابل‌خواندن بودن پاسخ داور است؛ نه صحت محتوایی انتخاب او.")
        for _, row in tot.iterrows():
            with st.expander(f"سؤال GSM8K {int(row['dataset_index'])}"):
                st.markdown(row.get("question", ""))
                st.write("پاسخ مرجع:", row.get("gold_answer"))
                st.write("پاسخ نهایی:", row.get("predicted_answer") or "استخراج نشد")
                try:
                    raw = json.loads(str(row.get("raw_output", "{}")))
                except json.JSONDecodeError:
                    raw = {}
                candidates = raw.get("candidates", [])
                candidate_answers = raw.get("candidate_answers", row.get("candidate_answers", []))
                for i, candidate in enumerate(candidates, 1):
                    answer = candidate_answers[i - 1] if i - 1 < len(candidate_answers) else "استخراج نشده"
                    st.markdown(f"**Candidate {i} · پاسخ استخراج‌شده: {answer}**")
                    st.code(candidate, language="text")
                st.markdown("**انتخاب داور**")
                st.write(raw.get("selected_candidate", row.get("selected_candidate", "در خروجی ثبت نشده")))
                st.markdown("**Judge output**")
                st.code(raw.get("judge_output", row.get("judge_output", "")), language="text")
                st.markdown("**خروجی مسیر انتخاب‌شده**")
                st.code(raw.get("selected_candidate_output", ""), language="text")

with downloads:
    st.caption("دانلود خروجی‌ها آزمایش را دوباره اجرا نمی‌کند.")
    st.download_button("دانلود خلاصه CSV", (folder / "summary.csv").read_bytes(), file_name=f"{folder.name}_summary.csv", mime="text/csv")
    st.download_button("دانلود داده خام JSONL", (folder / "experiment_results.jsonl").read_bytes(), file_name=f"{folder.name}_results.jsonl", mime="application/json")
    if (folder / "run_config.json").exists():
        st.download_button("دانلود تنظیمات اجرا", (folder / "run_config.json").read_bytes(), file_name=f"{folder.name}_config.json", mime="application/json")
    if report:
        st.download_button("دانلود گزارش Markdown", report, file_name=f"{folder.name}_report.md", mime="text/markdown")
    st.download_button("دانلود جزئیات سؤال‌ها CSV", details.to_csv(index=False), file_name=f"{folder.name}_question_details.csv", mime="text/csv")
    st.download_button("دانلود بسته کامل ZIP", make_zip(folder, details), file_name=f"{folder.name}_results.zip", mime="application/zip", type="primary")

st.divider()
st.markdown("### ملاحظات علمی")
st.warning(
    "هر اجرا فقط نمونه‌ای از GSM8K test را گزارش می‌کند، نه کل مجموعه را. "
    "شناسه سؤال‌های قبلاً استفاده‌شده در حالت پیش‌فرض دوباره انتخاب نمی‌شوند. "
    "ToT-inspired پیاده‌سازی کامل Tree of Thoughts نیست و تولیدکننده و داور یک مدل‌اند. "
    "تعداد توکن‌ها شاخص حجم ورودی/خروجی است، نه اندازه‌گیری مستقیم هزینه مالی یا انرژی."
)
st.caption("Structured Reasoning in Language Models · GSM8K · Qwen2.5-0.5B-Instruct")
