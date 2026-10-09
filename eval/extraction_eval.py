"""Field-level extraction accuracy on rendered synthetic artifacts.

  python eval/extraction_eval.py --split test        # held-out set (report numbers from this)
  python eval/extraction_eval.py --split dev --limit 20

Pass bars (PLAN.md §7): UTR exact >=95%, amount >=98%, beneficiary >=90%, hallucinated UTR = 0.
Writes eval/report_extraction.md
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from app.models import Case  # noqa: E402
from app.services.extract import extract, transaction_fields  # noqa: E402

ART = ROOT / "data-gen" / "out" / "artifacts"


def run(split: str, limit: int | None, *, case_ids: list[str] | None = None, data_root: Path | None = None) -> dict:
    data_root = data_root or ROOT / "data-gen" / "out"
    ids = case_ids if case_ids is not None else json.loads((data_root / "split.json").read_text())[split]
    if limit:
        ids = ids[:limit]
    tot = {"utr": 0, "amount": 0, "beneficiary": 0}
    hit = {"utr": 0, "amount": 0, "beneficiary": 0}
    accepted = {"utr": 0, "amount": 0, "beneficiary": 0}
    errors = []
    durations = []
    hallucinated_utr = 0
    extra_txns = 0
    accepted_hallucinated_utr = 0
    failures = []
    diagnostics = []
    for cid in ids:
        d = data_root / "artifacts" / cid
        truth = json.loads((d / "truth.json").read_text(encoding="utf-8"))
        files = [(f"#{i} {name}", "image/png", (d / name).read_bytes())
                 for i, name in enumerate(truth["files"], 1)]
        started = time.monotonic()
        try:
            case, _ = extract(Case(country=truth.get("country", "IN")), files)
        except Exception as error:
            errors.append({"case": cid, "error": type(error).__name__})
            for key in tot:
                tot[key] += len(truth["transactions"])
            continue
        durations.append(round(time.monotonic() - started, 3))
        diagnostics.append({"case": cid, "files": truth["files"], "transactions": [
            {"reference": t.utr.value, "fields": {path: getattr(obj, name).model_dump()
              for path, obj, name in transaction_fields(t)}} for t in case.transactions]})
        got_utrs = {t.utr.value for t in case.transactions if t.utr.value}
        true_utrs = {t["utr"] for t in truth["transactions"]}
        hallucinated_utr += len([u for u in got_utrs if u not in true_utrs])
        accepted_hallucinated_utr += sum(1 for t in case.transactions if t.utr.value and t.utr.value not in true_utrs and t.utr.valid)
        extra_txns += max(0, len(case.transactions) - len(truth["transactions"]))
        by_utr = {t.utr.value: t for t in case.transactions}
        for tt in truth["transactions"]:
            for k in tot:
                tot[k] += 1
            g = by_utr.get(tt["utr"])
            if g is None:
                failures.append({"case": cid, "missing_utr": tt["utr"]})
                continue
            hit["utr"] += 1
            accepted["utr"] += int(g.utr.valid and g.utr.status == "checked")
            if g.amount.value and abs(float(g.amount.value) - float(tt["amount"])) < 0.01:
                hit["amount"] += 1
                accepted["amount"] += int(g.amount.valid and g.amount.status == "checked")
            else:
                failures.append({"case": cid, "utr": tt["utr"], "amount": g.amount.value, "want": tt["amount"]})
            want_vpa = (tt.get("beneficiary_vpa") or "").lower()
            want_acct = tt.get("beneficiary_account") or ""
            got_vpa = (g.beneficiary.vpa.value or "").lower()
            got_acct = "".join(ch for ch in (g.beneficiary.account.value or "") if ch.isdigit())
            if (want_vpa and got_vpa == want_vpa) or (not want_vpa and want_acct and got_acct == want_acct):
                hit["beneficiary"] += 1
                field = g.beneficiary.vpa if want_vpa else g.beneficiary.account
                accepted["beneficiary"] += int(field.valid and field.status == "checked")
                if not field.valid or field.status != "checked":
                    failures.append({"case": cid, "utr": tt["utr"], "raw_beneficiary_matched": True,
                                     "checked": False, "issue": field.issue, "source_file": field.source_file})
            else:
                failures.append({"case": cid, "utr": tt["utr"], "got": g.beneficiary.vpa.value or g.beneficiary.account.value,
                                 "want": want_vpa or want_acct})
    acc = {k: (hit[k] / tot[k] if tot[k] else 0) for k in tot}
    return {"split": split, "cases": len(ids), "accuracy": acc, "hallucinated_utr": hallucinated_utr,
            "extra_transactions": extra_txns, "failures": failures[:50], "hit": hit, "total": tot, "accepted_checked_hit": accepted, "accepted_checked_accuracy": {k: accepted[k] / tot[k] if tot[k] else 0 for k in tot}, "accepted_hallucinated_utr": accepted_hallucinated_utr, "model_errors": errors, "seconds_per_case": durations, "diagnostics": diagnostics}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["train", "dev", "test"], default="dev")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    r = run(a.split, a.limit)
    bars = {"utr": 0.95, "amount": 0.98, "beneficiary": 0.90}
    lines = [f"# Extraction eval ({r['split']}, {r['cases']} cases)", "",
             "| Field | Raw hit/total | Raw accuracy | Checked accuracy | Target |", "|---|---|---|---|---|"]
    for k, v in r["accuracy"].items():
        lines.append(f"| {k} | {r['hit'][k]}/{r['total'][k]} | {v:.1%} | {r['accepted_checked_accuracy'][k]:.1%} | {bars[k]:.0%} |")
    lines += ["", f"Hallucinated UTRs: **{r['hallucinated_utr']}** (bar 0)",
              f"Extra transactions: {r['extra_transactions']}", "", "## Failures (first 50)",
              "```json", json.dumps(r["failures"], indent=1), "```"]
    out = ROOT / "eval" / f"report_extraction_{a.split}.md"
    (ROOT / "eval" / f"extraction_{a.split}.json").write_text(json.dumps(r, indent=2), encoding="utf-8")
    lines += ["", f"Accepted unsupported UTRs: {r['accepted_hallucinated_utr']}", f"Model errors: {len(r['model_errors'])}; counted as missed fields.", "This is a synthetic evaluation; raw accuracy is separate from accepted, independently checked values."]
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:8]))
    print(f"-> {out}")


if __name__ == "__main__":
    main()
