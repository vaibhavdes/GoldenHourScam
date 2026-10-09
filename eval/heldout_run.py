"""Run the frozen extraction benchmark with bounded parallelism and token accounting.

Calls the unmodified runtime extraction pipeline. Only synthetic local artifacts are read;
no Firestore/GCS cases are created. Checkpoints survive interruptions without silently
rerunning successful cases or substituting development data for test cases.
"""
from __future__ import annotations
import argparse, contextvars, hashlib, json, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"api"))
sys.path.insert(0,str(ROOT/"eval"))
from app import llm
from extraction_eval import run
from app.config import get_settings

PRICING_URL="https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing"
# Published non-global standard rates on 8 October 2026, USD / 1M tokens.
# The 3.8 Flash table rate assumes the published through-Dec promotional credits.
RATES={"gemini-3.8-flash":{"input":.825,"cached_input":.0825,"output":4.125},
       "gemini-3.1-flash-lite":{"input":.275,"cached_input":.0275,"output":1.65}}
CASE=contextvars.ContextVar("eval_case",default=None)
LOCK=threading.Lock()
CALLS=[]


def percentile(values, fraction):
    if not values:return None
    values=sorted(values);pos=(len(values)-1)*fraction;lo=int(pos);hi=min(lo+1,len(values)-1)
    return round(values[lo]+(values[hi]-values[lo])*(pos-lo),3)


def aggregate(results, ids, manifest, started):
    fields=("utr","amount","beneficiary")
    total={k:sum(r["total"][k] for r in results.values()) for k in fields}
    hit={k:sum(r["hit"][k] for r in results.values()) for k in fields}
    checked={k:sum(r["accepted_checked_hit"][k] for r in results.values()) for k in fields}
    calls=list(CALLS);cost=0;missing_usage=0
    for call in calls:
        usage=call.get("usage")
        rates=RATES.get(call["model"])
        if not usage or not rates:missing_usage+=1;continue
        prompt=usage.get("prompt_token_count") or 0;cached=usage.get("cached_content_token_count") or 0
        output=(usage.get("candidates_token_count") or 0)+(usage.get("thoughts_token_count") or 0)
        call["reference_cost_usd"]=(max(0,prompt-cached)*rates["input"]+cached*rates["cached_input"]+output*rates["output"])/1e6
        cost+=call["reference_cost_usd"]
    durations=[r["attempt_seconds"] for r in results.values()]
    return {"split":"test","status":"complete" if len(results)==len(ids) else "running", "completed_cases":len(results),"cases":len(ids),
        "checked_at":datetime.now(timezone.utc).isoformat(),"manifest":manifest,"wall_seconds":round(time.monotonic()-started,3),
        "total":total,"hit":hit,"accepted_checked_hit":checked,
        "accuracy":{k:hit[k]/total[k] if total[k] else 0 for k in fields},
        "accepted_checked_accuracy":{k:checked[k]/total[k] if total[k] else 0 for k in fields},
        "hallucinated_utr":sum(r["hallucinated_utr"] for r in results.values()),
        "accepted_hallucinated_utr":sum(r["accepted_hallucinated_utr"] for r in results.values()),
        "extra_transactions":sum(r["extra_transactions"] for r in results.values()),
        "model_errors":[x for r in results.values() for x in r["model_errors"]],
        "failures":[x for r in results.values() for x in r["failures"]],
        "diagnostics":[x for r in results.values() for x in r.get("diagnostics",[])],
        "per_case_seconds":{cid:r["attempt_seconds"] for cid,r in results.items()},
        "latency":{"p50_seconds":percentile(durations,.5),"p90_seconds":percentile(durations,.9),"scope":"Local API-service extraction with real Vertex calls, four concurrent cases; includes model-error attempts, excludes cloud upload/classify/draft and physical-device latency"},
        "model_calls":calls,"token_usage":{"calls":len(calls),"missing_usage_calls":missing_usage},
        "reference_cost":{"total_usd":round(cost,6),"mean_per_completed_case_usd":round(cost/max(1,len(results)),6),"rates_usd_per_million":RATES,"source":PRICING_URL,"as_of":"2026-10-08","note":"Reference estimate using published non-global rates, assuming eligibility for Flash promotional credits. Not an invoice; failed calls without usage, taxes, hosting, storage, classify/draft and voice excluded."}}


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--workers",type=int,default=4)
    parser.add_argument("--data-root",type=Path,default=ROOT/"data-gen/out")
    parser.add_argument("--name",default="test")
    args=parser.parse_args()
    import re
    if not re.fullmatch(r"[a-z0-9_]+",args.name):parser.error("Use a lowercase report name")
    data_root=args.data_root.resolve()
    if not 1<=args.workers<=4:parser.error("Use 1–4 workers")
    ids=json.loads((data_root/"split.json").read_text())["test"]
    s=get_settings();assert s.use_vertex and s.gcp_project=="goldenhour-aicup-2026-vk1007"
    manifest={"git_commit":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),"project":s.gcp_project,"location":s.gcp_location,"main":s.model_main,"lite":s.model_lite,"workers":args.workers,"case_ids":ids,"file_sha256":{}}
    paths=[data_root/"split.json",ROOT/"api/app/services/extract.py",ROOT/"api/app/tools/validators.py",ROOT/"api/app/llm.py",Path(__file__),ROOT/"eval/extraction_eval.py"]
    for cid in ids:
        directory=data_root/"artifacts"/cid;truth=json.loads((directory/"truth.json").read_text());paths.extend([directory/"truth.json"]+[directory/f for f in truth["files"]])
    for path in paths:manifest["file_sha256"][str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
    checkpoint=ROOT/f".runtime/heldout-{args.name}-checkpoint.json";assert not checkpoint.exists(),"Existing held-out checkpoint must be reviewed before rerunning"
    if (ROOT/f"eval/extraction_{args.name}.json").exists():raise RuntimeError("Refusing to overwrite an existing benchmark report")
    manifest["dataset_root"]=str(data_root.relative_to(ROOT)); manifest["synthetic"]=True
    original=llm.client().models.generate_content
    def measured(*a,**kw):
        start=time.monotonic();call={"case":CASE.get(),"model":kw.get("model")}
        try:
            response=original(*a,**kw);call["usage"]=response.usage_metadata.model_dump(mode="json") if response.usage_metadata else None;return response
        except Exception as error:
            call["error_type"]=type(error).__name__;raise
        finally:
            call["seconds"]=round(time.monotonic()-start,3)
            with LOCK:CALLS.append(call)
    llm.client().models.generate_content=measured
    def one(cid):
        CASE.set(cid);start=time.monotonic();result=run("test",None,case_ids=[cid],data_root=data_root);result["attempt_seconds"]=round(time.monotonic()-start,3);return result
    results={};started=time.monotonic()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures={pool.submit(one,cid):cid for cid in ids}
        for future in as_completed(futures):
            cid=futures[future];results[cid]=future.result()
            with LOCK:report=aggregate(results,ids,manifest,started)
            checkpoint.write_text(json.dumps(report,indent=2)+"\n")
            print(json.dumps({"completed":len(results),"total":len(ids),"case":cid,"seconds":results[cid]["attempt_seconds"],"raw_hit":report["hit"],"checked_hit":report["accepted_checked_hit"],"denominators":report["total"],"model_errors":len(report["model_errors"]),"reference_usd":report["reference_cost"]["total_usd"]}),flush=True)
    out=ROOT/f"eval/extraction_{args.name}.json";out.write_text(json.dumps(report,indent=2)+"\n")
    lines=[f"# Held-out extraction — {len(ids)} synthetic cases", "", f"Frozen pipeline; all selected test cases retained. See extraction_{args.name}.json for hashes, predictions, source-check issues, exact denominators and token usage.", "", "| Field | Raw hit/total | Raw accuracy | Independently checked | Target |", "|---|---|---|---|---|"]
    bars={"utr":.95,"amount":.98,"beneficiary":.90}
    for field in bars:lines.append(f"| {field} | {report['hit'][field]}/{report['total'][field]} | {report['accuracy'][field]:.1%} | {report['accepted_checked_hit'][field]}/{report['total'][field]} ({report['accepted_checked_accuracy'][field]:.1%}) | {bars[field]:.0%} |")
    lines += ["",f"Unsupported raw UTRs: {report['hallucinated_utr']}; unsupported independently accepted UTRs: {report['accepted_hallucinated_utr']}; extra transactions: {report['extra_transactions']}; model-error cases: {len(report['model_errors'])}.","",f"Extraction p50 {report['latency']['p50_seconds']} s; p90 {report['latency']['p90_seconds']} s. Four concurrent local service requests using real Vertex calls; excludes cloud upload, classification, drafts and voice.","",f"Token-based reference cost: USD {report['reference_cost']['total_usd']:.4f} total, USD {report['reference_cost']['mean_per_completed_case_usd']:.4f} per case. [Official pricing]({PRICING_URL}), 8 October 2026, non-global rates with eligible Flash promotional credits assumed; not an invoice. Unknown failed-call charges and other services excluded.","", "Masked destination accounts are retained as full-identifier misses in the primary denominator. No hidden characters are invented to reach the target. This measures synthetic extraction, not money recovery or human reporting-time improvements."]
    (ROOT/f"eval/report_extraction_{args.name}.md").write_text("\n".join(lines)+"\n")
    print(f"Finished: {out}",flush=True)

if __name__=="__main__":main()
