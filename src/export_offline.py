from __future__ import annotations
import argparse, csv, json, re, zipfile
from pathlib import Path

def parse_report(text):
    out={}
    blocks=re.split(r"(?=^### Question \d+ \(dataset index: \d+\)\s*$)",text,flags=re.M)
    for b in blocks:
        i=re.search(r"^### Question \d+ \(dataset index: (\d+)\)",b,flags=re.M)
        q=re.search(r"\*\*Problem:\*\*\s*(.*?)\s*\*\*Correct answer:\*\*",b,flags=re.S)
        a=re.search(r"\*\*Correct answer:\*\*\s*(.*?)\s*(?=^#### Direct)",b,flags=re.S|re.M)
        if i and q: out[int(i.group(1))]={"question":q.group(1).strip(),"gold_answer":a.group(1).strip() if a else ""}
    return out

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input-dir",default="results")
    p.add_argument("--output-dir",default="offline_package")
    a=p.parse_args(); src=Path(a.input_dir); out=Path(a.output_dir)
    for n in ("summary.csv","experiment_results.jsonl"):
        if not (src/n).is_file(): raise SystemExit("Missing "+str(src/n))
    summary=list(csv.DictReader((src/"summary.csv").open(encoding="utf-8-sig")))
    records=[json.loads(x) for x in (src/"experiment_results.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    rp=src/"question_report.md"; report=rp.read_text(encoding="utf-8") if rp.exists() else ""
    qmap=parse_report(report)
    for r in records:
        q=qmap.get(int(r.get("dataset_index",-1)),{})
        r.setdefault("question",q.get("question","Question text unavailable"))
        r.setdefault("gold_answer",q.get("gold_answer",""))
    cp=src/"run_config.json"; config=json.loads(cp.read_text(encoding="utf-8")) if cp.exists() else {}
    data=json.dumps({"summary":summary,"records":records,"config":config},ensure_ascii=False).replace("</","<\\/")
    out.mkdir(parents=True,exist_ok=True)
    page=r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Structured Reasoning Offline Dashboard</title><style>
:root{color-scheme:dark;--bg:#111827;--panel:#1f2937;--line:#374151;--text:#f3f4f6;--muted:#aab4c3;--accent:#60a5fa}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.6 system-ui,Segoe UI,sans-serif}main{max-width:1150px;margin:auto;padding:28px 18px}h1{font-size:30px}.muted{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}.card{background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:15px;margin:12px 0}.metric{font-size:24px;font-weight:700}.tabs{display:flex;gap:8px;flex-wrap:wrap;border-bottom:1px solid var(--line);padding:20px 0 10px}button,select{background:#273449;color:white;border:1px solid #526176;border-radius:8px;padding:10px;cursor:pointer}.active{background:#1d4ed8!important}.panel{display:none}.panel.active{display:block}.output,.question{white-space:pre-wrap;overflow-wrap:anywhere;background:#0b1220;padding:13px;border-radius:8px;max-height:500px;overflow:auto}.good{color:#34d399}.bad{color:#f87171}table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:9px;border-bottom:1px solid var(--line)}summary{cursor:pointer;font-weight:bold;padding:8px}label{display:block;margin:12px 0 5px}.bar{height:12px;background:#60a5fa;border-radius:12px}.track{background:#374151;border-radius:12px;margin:5px 0 12px}.small{font-size:13px}@media(max-width:600px){main{padding:14px}}</style></head><body><main><h1>Structured Reasoning in Language Models</h1><p class="muted">Offline dashboard · Direct vs CoT vs ToT-inspired · GSM8K</p><div id="meta" class="grid"></div><div class="tabs"><button class="active" data-tab="overview">Overview</button><button data-tab="questions">Question details</button><button data-tab="tot">ToT analysis</button><button data-tab="method">Methodology</button></div>
<section id="overview" class="panel active"><h2>Method comparison</h2><div id="charts" class="card"></div><h2>Numerical summary</h2><div class="card" style="overflow:auto"><table id="summary"></table></div></section><section id="questions" class="panel"><h2>Inspect a question</h2><label>GSM8K dataset index</label><select id="qselect"></select><div id="qdetail"></div></section><section id="tot" class="panel"><h2>ToT-inspired candidates and judge</h2><div id="totdetail"></div></section><section id="method" class="panel"><h2>Experimental configuration</h2><div id="config" class="card"></div><div class="card"><h3>Scientific limitations</h3><ul><li>ToT-inspired is simplified candidate generation and same-model judging, not full Tree of Thoughts.</li><li>Generator and judge use the same model; self-evaluation bias is possible.</li><li>Unparseable final answers are counted as incorrect.</li><li>Generated tokens measure output volume, not monetary cost or energy.</li><li>Results apply only to the evaluated GSM8K sample.</li><li>Generated reasoning text is not proof of the model's internal reasoning process.</li></ul></div></section><p class="muted small">Runs locally in a modern browser and makes no network requests.</p></main>
<script>
var D=__DATA__, $=function(x){return document.getElementById(x);};
function esc(x){return String(x==null?"":x).replace(/[&<>"']/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];});}
function raw(r){try{return JSON.parse(r.raw_output||"{}");}catch(e){return {};}}
function block(t,b){return "<h4>"+esc(t)+"</h4><pre class='output'>"+esc(b||"Not available")+"</pre>";}
function totHtml(r){var x=raw(r),cs=x.candidates||[],ans=x.candidate_answers||r.candidate_answers||[],s="<h4>Candidate paths</h4>";cs.forEach(function(c,i){s+=block("Candidate "+(i+1)+" · answer: "+(ans[i]||"—"),c);});s+="<p><b>Judge selection:</b> "+esc(x.selected_candidate||r.selected_candidate||"Not recorded")+"</p>"+block("Judge output",x.judge_output||r.judge_output)+block("Selected candidate output",x.selected_candidate_output);return s;}
function question(){var id=$("qselect").value,rows=D.records.filter(function(r){return String(r.dataset_index)===String(id);});if(!rows.length)return;var r=rows[0],s="<h3>Problem · GSM8K index "+esc(id)+"</h3><div class='question'>"+esc(r.question)+"</div><p><b>Gold answer:</b> "+esc(r.gold_answer)+"</p>";rows.forEach(function(x){s+="<details class='card' open><summary>"+esc(x.method)+" · <span class='"+(x.correct?"good":"bad")+"'>"+(x.correct?"Correct":"Incorrect")+"</span></summary><p>Prediction: "+esc(x.predicted_answer||"Not extracted")+" · Output tokens: "+esc(x.generated_tokens)+" · Calls: "+esc(x.generation_calls)+"</p>";if(x.prompt)s+=block("Prompt",x.prompt);if(x.method==="ToT-inspired")s+=totHtml(x);s+=block("Raw model output",x.raw_output)+"</details>";});$("qdetail").innerHTML=s;}
function render(){var c=D.config||{},ids=[...new Set(D.records.map(function(r){return r.dataset_index;}))],meta=[["Questions",c.sample_size||ids.length],["Model",c.model||"—"],["Dataset",c.dataset||"GSM8K"],["Seed",c.sample_seed||"—"],["Elapsed",c.elapsed_seconds?(Number(c.elapsed_seconds)/60).toFixed(1)+" min":"—"]];$("meta").innerHTML=meta.map(function(x){return "<div class='card'><div class='muted'>"+esc(x[0])+"</div><div class='metric'>"+esc(x[1])+"</div></div>";}).join("");
var names={"Direct":"Direct","CoT":"Chain of Thought (CoT)","ToT-inspired":"ToT-inspired"},rows=D.summary,h="<thead><tr><th>Method</th><th>Questions</th><th>Correct</th><th>Accuracy</th><th>Parseable</th><th>Avg output tokens</th><th>Calls</th><th>Judge failures</th></tr></thead><tbody>";
rows.forEach(function(r){h+="<tr><td>"+esc(names[r.method]||r.method)+"</td><td>"+esc(r.questions)+"</td><td>"+esc(r.correct)+"</td><td>"+(Number(r.accuracy)*100).toFixed(1)+"%</td><td>"+esc(r.parseable_answers||"—")+"</td><td>"+Number(r.avg_generated_tokens).toFixed(1)+"</td><td>"+esc(r.avg_generation_calls)+"</td><td>"+esc(r.judge_failures||"—")+"</td></tr>";});$("summary").innerHTML=h+"</tbody>";
var max=Math.max(1,...rows.map(function(r){return Number(r.avg_generated_tokens||0);}));$("charts").innerHTML=rows.map(function(r){return "<div><b>"+esc(names[r.method]||r.method)+"</b><div class='muted small'>Accuracy: "+(Number(r.accuracy)*100).toFixed(1)+"%</div><div class='track'><div class='bar' style='width:"+Math.max(0,Math.min(100,Number(r.accuracy)*100))+"%'></div></div><div class='muted small'>Average output tokens: "+Number(r.avg_generated_tokens).toFixed(1)+"</div><div class='track'><div class='bar' style='width:"+(Number(r.avg_generated_tokens||0)/max*100)+"%'></div></div></div>";}).join("");
ids.sort(function(a,b){return Number(a)-Number(b);});$("qselect").innerHTML=ids.map(function(i){return "<option value='"+esc(i)+"'>Question "+esc(i)+"</option>";}).join("");$("qselect").onchange=question;question();
var tr=D.records.filter(function(r){return r.method==="ToT-inspired";});$("totdetail").innerHTML=tr.map(function(r){return "<details class='card'><summary>Question "+esc(r.dataset_index)+" · "+(r.correct?"Correct":"Incorrect")+"</summary><div class='question'>"+esc(r.question)+"</div><p>Gold: "+esc(r.gold_answer)+" · Prediction: "+esc(r.predicted_answer||"Not extracted")+"</p>"+totHtml(r)+"</details>";}).join("")||"No ToT records.";
$("config").innerHTML="<table>"+Object.keys(c).map(function(k){return "<tr><th>"+esc(k)+"</th><td>"+esc(typeof c[k]==="object"?JSON.stringify(c[k]):c[k])+"</td></tr>";}).join("")+"</table>";}
document.querySelectorAll("[data-tab]").forEach(function(b){b.onclick=function(){document.querySelectorAll("[data-tab],.panel").forEach(function(x){x.classList.remove("active");});b.classList.add("active");$(b.dataset.tab).classList.add("active");};});render();
</script></body></html>'''.replace("__DATA__",data)
    out.mkdir(exist_ok=True,parents=True)
    (out/"offline_dashboard.html").write_text(page,encoding="utf-8")
    for n in ("summary.csv","experiment_results.jsonl","run_config.json","question_report.md"):
        f=src/n
        if f.is_file(): (out/n).write_bytes(f.read_bytes())
    (out/"README_FA.md").write_text("بسته آفلاین پژوهش\n\nبرای اجرای داشبورد، offline_dashboard.html را با Chrome، Edge یا Firefox باز کنید. اینترنت، Python، Streamlit و حساب GitHub لازم نیست.\n\nمحتویات: داشبورد تعاملی، خلاصه CSV، داده خام JSONL، تنظیمات اجرا و گزارش Markdown.\n\nمحدودیت علمی: ToT-inspired نسخه ساده‌شده تولید چند candidate و داوری با همان مدل است، نه پیاده‌سازی کامل Tree of Thoughts. نتایج فقط مربوط به نمونه ارزیابی‌شده GSM8K هستند.\n",encoding="utf-8")
    zp=out.with_suffix(".zip")
    with zipfile.ZipFile(zp,"w",zipfile.ZIP_DEFLATED) as z:
        for f in sorted(out.iterdir()):
            if f.is_file(): z.write(f,arcname=out.name+"/"+f.name)
    print("Dashboard:",out/"offline_dashboard.html")
    print("ZIP:",zp)
    print("Questions:",len({r.get("dataset_index") for r in records}),"Records:",len(records))
    print("Question texts recovered:",sum(1 for r in records if r.get("question")!="Question text unavailable"))

if __name__=="__main__": main()
