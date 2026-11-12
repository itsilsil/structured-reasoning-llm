from __future__ import annotations
import json
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
</style>
""", unsafe_allow_html=True)

def discover_runs():
    folders = [ROOT / "results"]
    runs = ROOT / "runs"
    if runs.exists():
        folders += [p for p in runs.iterdir() if p.is_dir()]
    found = {}
    for p in folders:
        if (p / "summary.csv").exists() and (p / "experiment_results.jsonl").exists():
            found["نتایج اصلی (results)" if p.name == "results" else p.name] = p
    return found

def load_run(folder):
    summary = pd.read_csv(folder / "summary.csv")
    records = [json.loads(line) for line in (folder / "experiment_results.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    details = pd.DataFrame(records)
    config_file = folder / "run_config.json"
    config = json.loads(config_file.read_text(encoding="utf-8")) if config_file.exists() else {}
    report_file = folder / "question_report.md"
    report = report_file.read_text(encoding="utf-8") if report_file.exists() else None
    if not details.empty:
        details["method"] = pd.Categorical(details["method"], METHODS, ordered=True)
        details = details.sort_values(["dataset_index", "method"])
    return summary, details, config, report

def make_zip(folder):
    memory = BytesIO()
    with zipfile.ZipFile(memory, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ["summary.csv", "experiment_results.jsonl", "run_config.json", "question_report.md"]:
            path = folder / name
            if path.exists():
                archive.write(path, arcname=name)
    return memory.getvalue()

def percent(value):
    return f"{float(value) * 100:.1f}%"

st.title("🧠 Structured Reasoning Dashboard")
st.caption("داشبورد تحلیل و مقایسه Direct، Chain of Thought و ToT-inspired روی GSM8K")
runs = discover_runs()
if not runs:
    st.error("نتیجه‌ای پیدا نشد. فایل‌های summary.csv و experiment_results.jsonl باید در results/ یا runs/ باشند.")
    st.stop()

with st.sidebar:
    st.header("کنترل پنل")
    selected = st.selectbox("اجرای مورد بررسی", list(runs))
    comparisons = st.multiselect("مقایسه با اجراهای دیگر", [x for x in runs if x != selected])
    st.divider()
    st.caption("این داشبورد فقط نتایج ذخیره‌شده را می‌خواند و مدل را اجرا نمی‌کند.")
    st.code(str(runs[selected].relative_to(ROOT)))

folder = runs[selected]
summary, details, config, report = load_run(folder)
st.subheader("نمای کلی اجرا")
a, b, c, d = st.columns(4)
a.metric("تعداد سؤال‌ها", int(config.get("sample_size", len(details) // 3 if not details.empty else 0)))
b.metric("مدل", str(config.get("model", "نامشخص")).split("/")[-1])
c.metric("Seed", config.get("sample_seed", "—"))
elapsed = config.get("elapsed_seconds")
d.metric("زمان اجرا", f"{float(elapsed)/60:.1f} دقیقه" if elapsed is not None else "ثبت نشده")
with st.expander("تنظیمات کامل آزمایش"):
    st.json(config)

st.divider()
st.subheader("مقایسه عملکرد روش‌ها")
summary = summary.copy()
summary["accuracy_percent"] = summary["accuracy"].astype(float) * 100
summary["method_label"] = summary["method"].map(LABELS).fillna(summary["method"])
kpis = st.columns(4)
for col, title, field, is_pct in zip(
    kpis,
    ["دقت CoT", "میانگین توکن CoT", "فراخوانی CoT", "پاسخ قابل استخراج CoT"],
    ["accuracy", "avg_generated_tokens", "avg_generation_calls", "parseable_answers"],
    [True, False, False, False],
):
    row = summary[summary.method == "CoT"]
    value = row.iloc[0][field] if not row.empty and field in row else None
    col.metric(title, percent(value) if is_pct and value is not None else (f"{float(value):.1f}" if value is not None else "—"))

overview, questions, tot_tab, downloads = st.tabs(["📊 مقایسه کلی", "🔎 بررسی سؤال‌ها", "🌳 تحلیل ToT-inspired", "📦 دریافت خروجی‌ها"])
with overview:
    left, right = st.columns(2)
    with left:
        fig = px.bar(summary, x="method_label", y="accuracy_percent", color="method_label", text=summary["accuracy_percent"].map(lambda x: f"{x:.0f}%"), title="دقت پاسخ نهایی", labels={"method_label":"روش","accuracy_percent":"دقت (%)"})
        fig.update_yaxes(range=[0,100], ticksuffix="%")
        fig.update_layout(showlegend=False, xaxis_title="", yaxis_title="دقت (%)")
        st.plotly_chart(fig, use_container_width=True)
    with right:
        fig = px.bar(summary, x="method_label", y="avg_generated_tokens", color="method_label", text_auto=".1f", title="میانگین توکن‌های تولیدشده", labels={"method_label":"روش","avg_generated_tokens":"تعداد توکن"})
        fig.update_layout(showlegend=False, xaxis_title="", yaxis_title="میانگین توکن")
        st.plotly_chart(fig, use_container_width=True)
    left, right = st.columns(2)
    with left:
        fig = px.bar(summary, x="method_label", y="avg_generation_calls", color="method_label", text_auto=".1f", title="میانگین تعداد فراخوانی مدل", labels={"method_label":"روش","avg_generation_calls":"فراخوانی"})
        fig.update_layout(showlegend=False, xaxis_title="", yaxis_title="فراخوانی")
        st.plotly_chart(fig, use_container_width=True)
    with right:
        if "judge_failures" in summary.columns:
            fig = px.bar(summary, x="method_label", y="judge_failures", color="method_label", text_auto=True, title="خطاهای قالب داوری", labels={"method_label":"روش","judge_failures":"تعداد خطا"})
            fig.update_layout(showlegend=False, xaxis_title="", yaxis_title="خطا")
            st.plotly_chart(fig, use_container_width=True)
    cols = [x for x in ["method","questions","correct","accuracy","parseable_answers","avg_generated_tokens","avg_generation_calls","judge_failures"] if x in summary.columns]
    table = summary[cols].copy()
    if "accuracy" in table:
        table["accuracy"] = table["accuracy"].map(percent)
    table = table.rename(columns={"method":"روش","questions":"تعداد سؤال","correct":"پاسخ صحیح","accuracy":"دقت","parseable_answers":"قابل استخراج","avg_generated_tokens":"میانگین توکن","avg_generation_calls":"میانگین فراخوانی","judge_failures":"خطای داوری"})
    st.markdown("#### جدول خلاصه")
    st.dataframe(table, use_container_width=True, hide_index=True)

    if comparisons:
        st.markdown("#### مقایسه اجراهای ذخیره‌شده")
        rows = []
        for label in [selected] + comparisons:
            s, _, cfg, _ = load_run(runs[label])
            for _, r in s.iterrows():
                rows.append({"اجرا":label,"روش":r["method"],"دقت (%)":float(r["accuracy"])*100,"میانگین توکن":float(r["avg_generated_tokens"]),"میانگین فراخوانی":float(r["avg_generation_calls"]),"تعداد سؤال":int(r["questions"]),"Seed":cfg.get("sample_seed","—")})
        comp = pd.DataFrame(rows)
        metric = st.selectbox("معیار مقایسه", ["دقت (%)","میانگین توکن","میانگین فراخوانی"])
        fig = px.line(comp, x="اجرا", y=metric, color="روش", markers=True, hover_data=["تعداد سؤال","Seed"])
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(comp, use_container_width=True, hide_index=True)

with questions:
    if details.empty:
        st.warning("جزئیات سؤال‌ها موجود نیست.")
    else:
        ids = sorted(details["dataset_index"].astype(int).unique().tolist())
        qid = st.selectbox("انتخاب سؤال", ids, format_func=lambda x: f"شناسه دیتاست: {x}")
        rows = details[details["dataset_index"].astype(int) == int(qid)]
        first = rows.iloc[0]
        st.markdown("**متن مسئله**")
        st.info(first.get("question", "متن سؤال ذخیره نشده است."))
        st.markdown(f"**پاسخ صحیح:** {first.get('gold_answer','—')}")
        cols = st.columns(len(rows))
        for col, (_, row) in zip(cols, rows.iterrows()):
            with col:
                method = str(row["method"])
                st.markdown(f"#### {LABELS.get(method,method)}")
                st.metric("نتیجه", "درست" if bool(row["correct"]) else "نادرست")
                st.write("پاسخ مدل:", row.get("predicted_answer") or "استخراج نشد")
                st.write("توکن خروجی:", row.get("generated_tokens","—"))
                st.write("فراخوانی:", row.get("generation_calls","—"))
                with st.expander("مشاهده خروجی خام و استدلال"):
                    raw = str(row.get("raw_output",""))
                    try:
                        parsed = json.loads(raw) if method == "ToT-inspired" else None
                    except json.JSONDecodeError:
                        parsed = None
                    if parsed:
                        st.markdown("**خروجی داور**")
                        st.code(parsed.get("judge_output",""), language="text")
                        for i, candidate in enumerate(parsed.get("candidates",[]),1):
                            with st.expander(f"مسیر پیشنهادی {i}"):
                                st.code(candidate, language="text")
                        st.markdown("**مسیر انتخاب‌شده**")
                        st.code(parsed.get("selected_candidate_output",""), language="text")
                    else:
                        st.code(raw, language="text")
        st.markdown("#### جدول مقایسه این سؤال")
        cols = ["method","gold_answer","predicted_answer","correct","generated_tokens","generation_calls"]
        st.dataframe(rows[cols], use_container_width=True, hide_index=True)

with tot_tab:
    tot = details[details["method"].astype(str) == "ToT-inspired"] if not details.empty else pd.DataFrame()
    if tot.empty:
        st.info("رکورد ToT-inspired پیدا نشد.")
    else:
        total = len(tot)
        valid = int(tot.get("judge_selection_valid", pd.Series([False]*total)).fillna(False).astype(bool).sum())
        x, y, z = st.columns(3)
        x.metric("تعداد نمونه‌ها", total)
        y.metric("داوری با قالب معتبر", valid)
        z.metric("خطای قالب داوری", total-valid)
        st.caption("قالب معتبر فقط یعنی خروجی داور قابل‌خواندن بوده است؛ نه اینکه انتخاب او از نظر محتوایی درست بوده باشد.")
        for _, row in tot.iterrows():
            with st.expander(f"سؤال {int(row['dataset_index'])} · {'داوری معتبر' if row.get('judge_selection_valid') else 'خطای داوری'}"):
                st.write("پاسخ صحیح:", row.get("gold_answer"))
                st.write("پاسخ مدل:", row.get("predicted_answer") or "استخراج نشد")
                st.write("پاسخ‌های کاندید:", row.get("candidate_answers", []))
                try:
                    parsed = json.loads(str(row.get("raw_output","")))
                except json.JSONDecodeError:
                    parsed = {}
                for i, candidate in enumerate(parsed.get("candidates",[]),1):
                    st.markdown(f"**Candidate {i}**")
                    st.code(candidate, language="text")
                st.markdown("**Judge output**")
                st.code(parsed.get("judge_output", row.get("judge_output","")), language="text")

with downloads:
    st.caption("دانلود فایل‌ها آزمایش را دوباره اجرا نمی‌کند.")
    st.download_button("دانلود خلاصه CSV", (folder/"summary.csv").read_bytes(), file_name=f"{folder.name}_summary.csv", mime="text/csv")
    st.download_button("دانلود داده خام JSONL", (folder/"experiment_results.jsonl").read_bytes(), file_name=f"{folder.name}_results.jsonl", mime="application/json")
    if (folder/"run_config.json").exists():
        st.download_button("دانلود تنظیمات JSON", (folder/"run_config.json").read_bytes(), file_name=f"{folder.name}_config.json", mime="application/json")
    if report:
        st.download_button("دانلود گزارش Markdown", report, file_name=f"{folder.name}_report.md", mime="text/markdown")
    st.download_button("دانلود بسته کامل ZIP", make_zip(folder), file_name=f"{folder.name}_results.zip", mime="application/zip", type="primary")

st.divider()
st.markdown("### ملاحظات علمی")
st.warning("این نتایج مربوط به نمونه آزمایشی ۱۰ سؤالی هستند. ToT-inspired پیاده‌سازی کامل Tree of Thoughts نیست و تولیدکننده و داور یک مدل‌اند. تعداد توکن‌ها شاخص حجم خروجی است، نه اندازه‌گیری مستقیم زمان، انرژی یا هزینه مالی.")
st.caption("Structured Reasoning in Language Models · GSM8K · Qwen2.5-0.5B-Instruct")
