from __future__ import annotations
import argparse, csv, json, re, zipfile
from pathlib import Path

def choose_source(value):
    if value:
        return Path(value)
    runs = Path("runs")
    candidates = [p for p in runs.glob("run_*") if (p/"summary.csv").exists() and (p/"experiment_results.jsonl").exists()] if runs.exists() else []
    if candidates:
        return max(candidates, key=lambda p: p.stat().st_mtime)
    return Path("results")

def parse_report(text):
    found = {}
    blocks = re.split(r"(?=^### Question \\d+ \\(dataset index: \\d+\\)\\s*$)", text, flags=re.M)
    for block in blocks:
        idx = re.search(r"^### Question \\d+ \\(dataset index: (\\d+)\\)", block, flags=re.M)
        problem = re.search(r"\\*\\*Problem:\\*\\*\\s*(.*?)\\s*\\*\\*Correct answer:\\*\\*", block, flags=re.S)
        answer = re.search(r"\\*\\*Correct answer:\\*\\*\\s*(.*?)\\s*(?=^#### Direct)", block, flags=re.S|re.M)
        if idx and problem:
            found[int(idx.group(1))] = {"question": problem.group(1).strip(), "gold_answer": answer.group(1).strip() if answer else ""}
    return found

def main():
    ap=argparse.ArgumentParser(description="ساخت داشبورد فارسی و آفلاین پژوهش")
    ap.add_argument("--input-dir",default=None,help="مسیر پوشه نتایج؛ در حالت پیش‌فرض آخرین اجرای کامل از runs انتخاب می‌شود")
    ap.add_argument("--output-dir",default="offline_package")
    args=ap.parse_args()
    src=choose_source(args.input_dir); out=Path(args.output_dir)
    for name in ("summary.csv","experiment_results.jsonl"):
        if not (src/name).is_file(): raise SystemExit(f"فایل {name} در {src} پیدا نشد.")
    summary=list(csv.DictReader((src/"summary.csv").open(encoding="utf-8-sig")))
    records=[json.loads(x) for x in (src/"experiment_results.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    report_path=src/"question_report.md"
    qmap=parse_report(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    for r in records:
        q=qmap.get(int(r.get("dataset_index",-1)),{})
        r.setdefault("question",q.get("question","متن سؤال در فایل‌های این اجرا موجود نیست."))
        r.setdefault("gold_answer",q.get("gold_answer",""))
    cfgpath=src/"run_config.json"
    config=json.loads(cfgpath.read_text(encoding="utf-8")) if cfgpath.exists() else {}
    payload=json.dumps({"summary":summary,"records":records,"config":config},ensure_ascii=False).replace("</","<\\/")
    page=r'''<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>داشبورد آفلاین پژوهش استدلال ساختارمند</title><style>
:root{color-scheme:dark;--bg:#101827;--panel:#1d293b;--line:#37465b;--text:#f2f5fa;--muted:#b2bdcc;--accent:#60a5fa}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.9 Tahoma,"Segoe UI",sans-serif}main{max-width:1200px;margin:auto;padding:28px 18px}h1{font-size:29px}h2{font-size:21px}.muted{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:15px;margin:12px 0}.metric{font-size:20px;font-weight:700;direction:ltr;text-align:right;overflow-wrap:anywhere}.tabs{display:flex;gap:8px;flex-wrap:wrap;border-bottom:1px solid var(--line);padding:20px 0 10px}button,select{background:#27364d;color:white;border:1px solid #526176;border-radius:8px;padding:10px 13px;font:inherit;cursor:pointer}.active{background:#1d4ed8!important}.panel{display:none}.panel.active{display:block}.output,.question{white-space:pre-wrap;overflow-wrap:anywhere;background:#0b1220;padding:13px;border-radius:8px;max-height:520px;overflow:auto;direction:auto;text-align:start}.good{color:#34d399}.bad{color:#f87171}table{border-collapse:collapse;width:100%;min-width:650px}td,th{text-align:right;padding:9px;border-bottom:1px solid var(--line)}summary{cursor:pointer;font-weight:bold;padding:8px}label{display:block;margin:12px 0 5px}.bar{height:12px;background:#60a5fa;border-radius:12px}.track{background:#374151;border-radius:12px;margin:5px 0 12px}.small{font-size:13px}.ltr{direction:ltr;text-align:left;unicode-bidi:plaintext}.tag{display:inline-block;background:#263b56;border-radius:18px;padding:2px 9px;margin:2px;font-size:12px}@media(max-width:600px){main{padding:14px}}
</style></head><body><main>
<h1>استدلال ساختارمند در مدل‌های زبانی</h1><p class="muted">داشبورد تعاملی آفلاین · مقایسه Direct، زنجیره افکار (CoT) و درخت افکار الهام‌گرفته (ToT-inspired) · مجموعه GSM8K</p>
<div id="meta" class="grid"></div><div class="tabs"><button class="active" data-tab="overview">خلاصه نتایج</button><button data-tab="questions">بررسی سؤال‌ها</button><button data-tab="tot">تحلیل ToT</button><button data-tab="method">روش آزمایش و محدودیت‌ها</button></div>
<section id="overview" class="panel active"><h2>مقایسه روش‌ها</h2><div id="charts" class="card"></div><h2>جدول نتایج عددی</h2><div class="card" style="overflow:auto"><table id="summary"></table></div></section>
<section id="questions" class="panel"><h2>بررسی جزئیات هر سؤال</h2><label for="qselect">انتخاب سؤال بر اساس شناسه مجموعه GSM8K</label><select id="qselect"></select><div id="qdetail"></div></section>
<section id="tot" class="panel"><h2>مسیرهای پیشنهادی و ارزیابی داور در روش ToT-inspired</h2><div id="totdetail"></div></section>
<section id="method" class="panel"><h2>تنظیمات آزمایش</h2><div id="config" class="card"></div><h2>محدودیت‌ها و ملاحظات علمی</h2><div class="card"><ul>
<li>روش ToT-inspired در این پژوهش، نسخه ساده‌شده تولید چند مسیر پیشنهادی و انتخاب با داوری همان مدل است؛ پیاده‌سازی کامل الگوریتم Tree of Thoughts نیست.</li>
<li>تولیدکننده و داور از یک مدل استفاده می‌کنند؛ بنابراین احتمال سوگیری در خودارزیابی وجود دارد.</li>
<li>پاسخ‌هایی که پاسخ نهایی آن‌ها قابل استخراج نبوده، نادرست محاسبه شده‌اند.</li>
<li>تعداد توکن‌های تولیدشده فقط شاخصی از حجم خروجی است و معادل هزینه مالی یا مصرف انرژی نیست.</li>
<li>نتایج به نمونه ارزیابی‌شده از مجموعه GSM8K محدود است و نباید بدون آزمایش بیشتر به همه مسائل تعمیم داده شود.</li>
<li>متن استدلال تولیدشده، لزوماً بازتاب قطعی فرایند استدلال داخلی مدل نیست.</li>
</ul></div></section>
<p class="muted small">این داشبورد به‌صورت محلی در مرورگر اجرا می‌شود و برای نمایش اطلاعات به اینترنت یا سرویس خارجی متصل نمی‌شود.</p></main>
<script>
const D=__DATA__, $=id=>document.getElementById(id);
const esc=x=>String(x==null?"":x).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const names={"Direct":"Direct (پاسخ مستقیم)","CoT":"CoT (زنجیره افکار)","ToT-inspired":"ToT-inspired (روش الهام‌گرفته از درخت افکار)"};
function raw(r){try{return JSON.parse(r.raw_output||"{}")}catch(e){return {}}}
function block(t,b){return "<h4>"+esc(t)+"</h4><pre class='output'>"+esc(b||"در داده‌های ذخیره‌شده موجود نیست.")+"</pre>"}
function totHtml(r){const x=raw(r),cs=x.candidates||[],ans=x.candidate_answers||r.candidate_answers||[];let s="<h4>مسیرهای تولیدشده (Candidateها)</h4>";cs.forEach((c,i)=>s+=block("مسیر "+(i+1)+" ـ پاسخ استخراج‌شده: "+(ans[i]||"قابل استخراج نیست"),c));s+="<p><b>انتخاب داور:</b> "+esc(x.selected_candidate||r.selected_candidate||"ثبت نشده")+"</p>"+block("متن ارزیابی داور (Judge)",x.judge_output||r.judge_output)+block("خروجی مسیر انتخاب‌شده",x.selected_candidate_output);return s}
function renderQuestion(){const id=$("qselect").value,rows=D.records.filter(r=>String(r.dataset_index)===String(id));if(!rows.length)return;const first=rows[0];let s="<h3>صورت مسئله ـ شناسه "+esc(id)+"</h3><div class='question'>"+esc(first.question)+"</div><p><b>پاسخ مرجع:</b> "+esc(first.gold_answer||"ثبت نشده")+"</p>";rows.forEach(r=>{s+="<details class='card' open><summary>"+esc(names[r.method]||r.method)+" ـ <span class='"+(r.correct?"good":"bad")+"'>"+(r.correct?"درست":"نادرست")+"</span></summary><p><span class='tag'>پاسخ مدل: "+esc(r.predicted_answer||"قابل استخراج نیست")+"</span><span class='tag'>توکن خروجی: "+esc(r.generated_tokens??"—")+"</span><span class='tag'>تعداد فراخوانی: "+esc(r.generation_calls??"—")+"</span></p>";if(r.prompt)s+=block("متن ورودی مدل (Prompt)",r.prompt);if(r.method==="ToT-inspired")s+=totHtml(r);s+=block("خروجی خام مدل",r.raw_output)+"</details>"});$("qdetail").innerHTML=s}
function render(){const c=D.config||{},ids=[...new Set(D.records.map(r=>r.dataset_index))];const meta=[["تعداد سؤال‌ها",c.sample_size||ids.length],["مدل زبانی",c.model||"—"],["مجموعه داده",c.dataset||"GSM8K"],["بذر نمونه‌گیری",c.sample_seed??"—"],["زمان اجرا",c.elapsed_seconds?(Number(c.elapsed_seconds)/60).toFixed(1)+" دقیقه":"—"]];$("meta").innerHTML=meta.map(x=>"<div class='card'><div class='muted'>"+esc(x[0])+"</div><div class='metric'>"+esc(x[1])+"</div></div>").join("");
let h="<thead><tr><th>روش</th><th>تعداد سؤال</th><th>پاسخ درست</th><th>دقت</th><th>پاسخ قابل استخراج</th><th>میانگین توکن خروجی</th><th>میانگین فراخوانی مدل</th><th>خطای قالب داور</th></tr></thead><tbody>";
D.summary.forEach(r=>{h+="<tr><td>"+esc(names[r.method]||r.method)+"</td><td>"+esc(r.questions)+"</td><td>"+esc(r.correct)+"</td><td>"+(Number(r.accuracy)*100).toFixed(1)+"٪</td><td>"+esc(r.parseable_answers??"—")+"</td><td>"+Number(r.avg_generated_tokens||0).toFixed(1)+"</td><td>"+Number(r.avg_generation_calls||0).toFixed(1)+"</td><td>"+esc(r.judge_failures??"—")+"</td></tr>"});$("summary").innerHTML=h+"</tbody>";
const max=Math.max(1,...D.summary.map(r=>Number(r.avg_generated_tokens||0)));$("charts").innerHTML=D.summary.map(r=>"<div><b>"+esc(names[r.method]||r.method)+"</b><div class='muted small'>دقت: "+(Number(r.accuracy)*100).toFixed(1)+"٪</div><div class='track'><div class='bar' style='width:"+Math.max(0,Math.min(100,Number(r.accuracy)*100))+"%'></div></div><div class='muted small'>میانگین توکن خروجی: "+Number(r.avg_generated_tokens||0).toFixed(1)+"</div><div class='track'><div class='bar' style='width:"+(Number(r.avg_generated_tokens||0)/max*100)+"%'></div></div></div>").join("");
ids.sort((a,b)=>Number(a)-Number(b));$("qselect").innerHTML=ids.map(i=>"<option value='"+esc(i)+"'>سؤال با شناسه "+esc(i)+"</option>").join("");$("qselect").onchange=renderQuestion;renderQuestion();
$("totdetail").innerHTML=D.records.filter(r=>r.method==="ToT-inspired").map(r=>"<details class='card'><summary>سؤال "+esc(r.dataset_index)+" ـ "+(r.correct?"پاسخ نهایی درست":"پاسخ نهایی نادرست")+"</summary><div class='question'>"+esc(r.question)+"</div><p><b>پاسخ مرجع:</b> "+esc(r.gold_answer)+" ـ <b>پاسخ مدل:</b> "+esc(r.predicted_answer||"قابل استخراج نیست")+"</p>"+totHtml(r)+"</details>").join("")||"داده‌ای برای روش ToT ثبت نشده است.";
$("config").innerHTML="<table>"+Object.keys(c).map(k=>"<tr><th>"+esc(k)+"</th><td class='ltr'>"+esc(typeof c[k]==="object"?JSON.stringify(c[k]):c[k])+"</td></tr>").join("")+"</table>"}
document.querySelectorAll("[data-tab]").forEach(b=>b.onclick=()=>{document.querySelectorAll("[data-tab],.panel").forEach(x=>x.classList.remove("active"));b.classList.add("active");$(b.dataset.tab).classList.add("active")});render();
</script></body></html>'''.replace("__DATA__",payload)
    out.mkdir(parents=True,exist_ok=True)
    (out/"داشبورد_آفلاین.html").write_text(page,encoding="utf-8")
    for name in ("summary.csv","experiment_results.jsonl","run_config.json","question_report.md"):
        f=src/name
        if f.is_file():(out/name).write_bytes(f.read_bytes())
    (out/"راهنمای_فارسی.txt").write_text(
        "راهنمای بسته آفلاین پژوهش\n\nفایل «داشبورد_آفلاین.html» را با Chrome یا Edge باز کنید. برای مشاهده داشبورد به اینترنت، Python، Streamlit یا حساب GitHub نیازی نیست.\n\nفایل‌های CSV و JSONL داده‌های عددی و خام آزمایش هستند؛ فایل Markdown گزارش تفصیلی اجراست.\n\nمحدودیت علمی: ToT-inspired نسخه ساده‌شده تولید چند مسیر پیشنهادی و داوری با همان مدل است، نه پیاده‌سازی کامل Tree of Thoughts.\n",
        encoding="utf-8")
    zip_path=out.with_suffix(".zip")
    with zipfile.ZipFile(zip_path,"w",zipfile.ZIP_DEFLATED) as z:
        for f in sorted(out.iterdir()):
            if f.is_file():z.write(f,arcname=out.name+"/"+f.name)
    unique=len({r.get("dataset_index") for r in records})
    print("پوشه نتایج:",src)
    print("تعداد سؤال:",unique,"| تعداد رکورد:",len(records))
    print("داشبورد:",out/"داشبورد_آفلاین.html")
    print("بسته قابل ارسال:",zip_path)

if __name__=="__main__":main()
