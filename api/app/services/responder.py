"""Responder side: explainable scoring, proportionate hold requests, attribution."""
from __future__ import annotations

from fastapi import HTTPException

from app.config import get_settings
from app.llm import generate_text
from app.models import Case, HoldRequest, Rail, ScoreCard
from app.packs import load_pack
from app.tools.attribution import pro_rata
from app.tools.linking import clusters, linked_count
from app.tools.score import score_case


def queue(cases: list[Case], *, include_empty: bool = False) -> list[dict]:
    rows = []
    for c in cases:
        if not c.transactions and not include_empty:
            continue
        card = score_case(c, linked_cases=linked_count(c, cases))
        rows.append({
            "case_id": c.id, "country": c.country, "scam_type": c.scam_type.value,
            "total_lost": c.total_lost(), "currency": load_pack(c.country)["currency"],
            "score": card.score, "minutes_since_txn": card.minutes_since_txn,
            "linked": linked_count(c, cases), "stage": c.stage.value,
            "transactions": len(c.transactions), "synthetic": c.synthetic,
        })
    rows.sort(key=lambda r: -r["score"])
    return rows


def explain(card: ScoreCard) -> str:
    """Gemini narrates ONLY the deterministic factors (rubric-evaluated)."""
    s = get_settings()
    facts = [{"name": f.name, "value": f.value, "factor": f.weight} for f in card.factors]
    try:
        return generate_text(
            model=s.model_lite,
            system=("You explain a fraud-recovery priority score to a bank scam-desk analyst in "
                    "2 sentences. Mention only the factors provided, with their values. Do not add "
                    "any other reason, guess or recommendation beyond acting on high scores first."),
            prompt=f"Score {card.score}/100. Factors: {facts}",
        )
    except Exception:  # noqa: BLE001
        return f"Response priority {card.score}/100 uses " + ", ".join(
            f"{f.name.replace('_', ' ')} ({f.value})" for f in card.factors) + ". This is a heuristic, not a recovery probability."


def hold_request(case: Case, cases: list[Case], txn_id: str | None = None) -> HoldRequest:
    pack = load_pack(case.country)
    txns = [t for t in case.transactions if (t.direction == "debit" if txn_id is None else t.id == txn_id)]
    bank_rails = {Rail.UPI, Rail.IMPS, Rail.NEFT, Rail.RTGS, Rail.DUITNOW, Rail.PAYNOW, Rail.BANK_TRANSFER}
    if not txns or any(t.direction != "debit" or t.rail not in bank_rails or
                       not t.confirmed or not t.utr.valid or not t.amount.valid or
                       not (t.beneficiary.vpa.valid or t.beneficiary.account.valid) for t in txns):
        raise HTTPException(409, "Confirm valid reference, amount and beneficiary for each outgoing bank transfer first; credits and unsupported payment methods cannot be included")
    action = "HOLD_DISPUTED_AMOUNT"
    rows = []
    for t in txns:
        b = t.beneficiary
        rows.append({
            "transaction_ref": t.utr.value, "rail": t.rail.value,
            "datetime": t.timestamp.value if t.timestamp.valid else "[please check: date/time]", "disputed_amount": t.amount.value,
            "beneficiary_vpa": b.vpa.value if b.vpa.valid else None, "beneficiary_account": b.account.value if b.account.valid else None,
            "beneficiary_ifsc": b.ifsc.value if b.ifsc.valid else None, "beneficiary_bank": b.bank.value if b.bank.valid else None,
        })
    fields = {
        "investigating_officer": "[Name, rank, contact - to be filled by officer]",
        "complaint_reference": case.ncrp_complaint_id or case.ack_number or f"GoldenHour {case.id}",
        "legal_provision": "[Provision under which the restraint is requested - officer to fill]",
        "action": action,
        "transactions": rows,
        "currency": pack["currency"],
        "total_disputed": sum(float(r["disputed_amount"] or 0) for r in rows),
        "review_note": "Restraint to be reviewed periodically and withdrawn when no longer necessary.",
    }
    lines = [
        "REQUEST TO HOLD DISPUTED FUNDS",
        f"Complaint reference: {fields['complaint_reference']}",
        f"Investigating officer: {fields['investigating_officer']}",
        f"Legal provision: {fields['legal_provision']}",
        "",
    ]
    for r in rows:
        lines.append(f"- Ref {r['transaction_ref']} ({r['rail']}, {r['datetime']}): "
                     f"{pack['currency']} {r['disputed_amount']} -> "
                     f"{r['beneficiary_vpa'] or r['beneficiary_account']} "
                     f"{('/ ' + r['beneficiary_ifsc']) if r['beneficiary_ifsc'] else ''}")
    lines.append("\nAction requested: place a lien/hold ONLY on the disputed amount(s) above, "
                 "not on the entire account.")
    lines.append(fields["review_note"])
    return HoldRequest(case_id=case.id, action=action, text="\n".join(lines), fields=fields)


def cluster_attribution(cases: list[Case], cluster_case_ids: list[str], held_amount: float) -> list[dict]:
    by_id = {c.id: c for c in cases}
    if any(cid not in by_id for cid in cluster_case_ids):
        raise HTTPException(404, "Case not found")
    if len({by_id[cid].country for cid in cluster_case_ids}) > 1:
        raise HTTPException(422, "Allocate held funds within one country and currency")
    losses = {cid: by_id[cid].total_lost() for cid in cluster_case_ids if cid in by_id}
    return pro_rata(held_amount, losses)


__all__ = ["queue", "explain", "hold_request", "cluster_attribution", "clusters", "score_case"]
