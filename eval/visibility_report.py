"""Diagnose observable vs masked beneficiary identifiers without changing the primary metric.

Synthetic generator rules: IN IMPS SMS masks destination accounts; it renders no bank
receipt, and the chat uses the mule VPA, not the full account. UPI receipts or SMS expose
VPAs; IN NEFT SMS and MY receipts expose full account numbers. No production prompt is
changed based on this held-out inspection.
"""
from pathlib import Path
import argparse,hashlib,json
ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--result",type=Path,default=ROOT/"eval/extraction_test.json")
    parser.add_argument("--data-root",type=Path,default=ROOT/"data-gen/out")
    parser.add_argument("--output",type=Path,default=ROOT/"eval/beneficiary_visibility_test.json")
    parser.add_argument("--report",type=Path,default=ROOT/"eval/report_extraction_test.md")
    args=parser.parse_args()
    result=json.loads(args.result.read_text())
    seeds={entry["case"]["id"]:entry["case"] for entry in json.loads((args.data_root/"cases.json").read_text())["cases"]}
    predictions={x["case"]:x for x in result["diagnostics"]}
    groups={};masked=[]
    for cid in result["manifest"]["case_ids"]:
        truth=json.loads((args.data_root/"artifacts"/cid/"truth.json").read_text())
        original={t["utr"]["value"]:t for t in seeds[cid]["transactions"]}
        predicted={t["reference"]:t for t in predictions.get(cid,{}).get("transactions",[])}
        for index,t in enumerate(truth["transactions"],1):
            rail=original[t["utr"]]["rail"]
            visible=not (truth["country"]=="IN" and rail=="IMPS" and f"receipt_{index}.png" not in truth["files"])
            key="observable" if visible else "masked_full_account"
            group=groups.setdefault(key,{"total":0,"raw_hit":0,"checked_hit":0})
            group["total"]+=1
            got=predicted.get(t["utr"])
            if got:
                field=got["fields"]["beneficiary.vpa" if t.get("beneficiary_vpa") else "beneficiary.account"]
                value=(field["value"] or "").casefold()
                want=(t.get("beneficiary_vpa") or t.get("beneficiary_account") or "").casefold()
                matched=value==want
                group["raw_hit"]+=int(matched)
                group["checked_hit"]+=int(matched and field["valid"] and field["status"]=="checked")
            if not visible:masked.append({"case":cid,"utr":t["utr"],"reason":"IN IMPS exposes only masked destination digits; no receipt with the full account was rendered"})
    for group in groups.values():
        group["raw_accuracy"]=group["raw_hit"]/group["total"] if group["total"] else 0
        group["checked_accuracy"]=group["checked_hit"]/group["total"] if group["total"] else 0
    out={"split":"test","cases":result["cases"],"primary_denominator_unchanged":result["total"]["beneficiary"],"groups":groups,"masked_transfers":masked,"method":"Deterministic generator-rule diagnostic, not model-output-based exclusion. The primary full-identifier metric retains these misses.","generator_sha256":hashlib.sha256((ROOT/"data-gen/generate.py").read_bytes()).hexdigest(),"sms_formats_sha256":hashlib.sha256((ROOT/"data-gen/sms_formats.py").read_bytes()).hexdigest()}
    args.output.write_text(json.dumps(out,indent=2)+"\n")
    path=args.report;text=path.read_text();text+="\n## Beneficiary visibility diagnostic\n\nPrimary full-identifier results above are unchanged. The generator masks some IMPS destination accounts and supplies no bank receipt with the full number. Secondary visibility groups:\n\n| Group | Transfers | Raw exact | Independently checked |\n|---|---|---|---|\n"
    for name,group in groups.items():text+=f"| {name} | {group['total']} | {group['raw_hit']} ({group['raw_accuracy']:.1%}) | {group['checked_hit']} ({group['checked_accuracy']:.1%}) |\n"
    text+="\nVisibility is derived from the original renderer/SMS rules, independently of predictions. Masked transfers remain in the primary denominator; asking the bank for the full destination identifier is the correct next action. See the matching visibility JSON for retained case/reference diagnostics. This generator covers India and Malaysia; Singapore is covered by separate functional cloud probes.\n";path.write_text(text)
    print(json.dumps({"groups":groups,"primary_denominator_unchanged":out["primary_denominator_unchanged"]}))

if __name__=="__main__":main()
