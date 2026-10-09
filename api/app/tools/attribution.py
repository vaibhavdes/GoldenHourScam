"""Multi-victim attribution: split held funds pro-rata, reconciling to the smallest unit."""
from decimal import ROUND_DOWN, Decimal


def pro_rata(held_amount: float, losses: dict[str, float]) -> list[dict]:
    """Return per-victim share. Remainder (paise/sen) goes to the largest losses first."""
    held = Decimal(str(held_amount)).quantize(Decimal("0.01"))
    total = sum(Decimal(str(v)) for v in losses.values())
    if total <= 0 or held <= 0:
        return [{"case_id": k, "loss": v, "share": 0.0, "pct": 0.0} for k, v in losses.items()]
    held = min(held, total)
    rows = []
    allocated = Decimal("0")
    for cid, loss in losses.items():
        loss_d = Decimal(str(loss))
        share = (held * loss_d / total).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        allocated += share
        rows.append({"case_id": cid, "loss": float(loss_d), "share": share})
    remainder = held - allocated
    cent = Decimal("0.01")
    for row in sorted(rows, key=lambda r: -r["loss"]):
        if remainder <= 0:
            break
        row["share"] += cent
        remainder -= cent
    for row in rows:
        row["pct"] = round(float(row["share"] / held * 100), 2)
        row["share"] = float(row["share"])
    return rows
