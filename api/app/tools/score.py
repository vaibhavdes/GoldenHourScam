"""Response-priority score: deterministic heuristic. Gemini only narrates these factors.

Weights are an illustrative policy that a bank/centre would tune.
"""
from datetime import datetime, timezone

from app.models import Case, Rail, ScoreCard, ScoreFactor

RAIL_FACTOR = {
    Rail.UPI: 1.0, Rail.IMPS: 1.0, Rail.DUITNOW: 1.0, Rail.PAYNOW: 1.0,
    Rail.NEFT: 0.9, Rail.RTGS: 0.9, Rail.BANK_TRANSFER: 0.9,
    Rail.CARD: 0.8, Rail.WALLET: 0.7, Rail.CRYPTO: 0.3, Rail.GIFT_CARD: 0.1,
    Rail.UNKNOWN: 0.6,
}


def time_decay(minutes: float | None) -> float:
    if minutes is None:
        return 0.5
    if minutes <= 30:
        return 1.0
    if minutes <= 60:
        return 0.8
    if minutes <= 360:
        return 0.5
    if minutes <= 1440:
        return 0.2
    return 0.05


def completeness(case: Case) -> float:
    if not case.transactions:
        return 0.0
    per = []
    for t in case.transactions:
        have = [bool(t.utr.value and t.utr.valid), bool(t.amount.value and t.amount.valid),
                bool(t.timestamp.value and t.timestamp.valid),
                bool((t.beneficiary.vpa.value and t.beneficiary.vpa.valid) or
                     (t.beneficiary.account.value and t.beneficiary.account.valid))]
        per.append(sum(have) / 4)
    return sum(per) / len(per)


def score_case(case: Case, linked_cases: int = 0, now: datetime | None = None) -> ScoreCard:
    now = now or datetime.now(timezone.utc)
    first = case.first_txn_time()
    minutes = (now - first).total_seconds() / 60 if first else None
    td = time_decay(minutes)
    rails = [t.rail for t in case.transactions] or [Rail.UNKNOWN]
    rf = max(RAIL_FACTOR.get(r, 0.6) for r in rails)
    comp = completeness(case)
    link_bonus = min(linked_cases, 5) * 2.0          # up to +10
    base = 100 * td * rf * (0.4 + 0.6 * comp)       # incomplete cases still get attention
    score = round(min(100.0, base + link_bonus), 1)

    factors = [
        ScoreFactor(name="time_since_transfer",
                    value="unknown" if minutes is None else f"{int(minutes)} min",
                    weight=td, contribution=round(100 * td, 1)),
        ScoreFactor(name="payment_rail", value=",".join(sorted({r.value for r in rails})),
                    weight=rf, contribution=round(100 * rf, 1)),
        ScoreFactor(name="report_completeness", value=f"{int(comp * 100)}%",
                    weight=round(0.4 + 0.6 * comp, 2), contribution=round(100 * comp, 1)),
        ScoreFactor(name="beneficiary_linked_cases", value=str(linked_cases),
                    weight=1.0, contribution=link_bonus),
    ]
    return ScoreCard(case_id=case.id, score=score, minutes_since_txn=minutes, factors=factors)
