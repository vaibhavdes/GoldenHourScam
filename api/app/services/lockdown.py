"""Lockdown checklist tailored to scam type, plus the standard SOS steps."""
from app.models import Case, Step
from app.packs import load_pack


def sos_steps(case: Case) -> list[Step]:
    pack = load_pack(case.country)
    primary = next(h for h in pack["helplines"] if h.get("primary"))
    steps = [
        Step(id="call_helpline", label=f"Call {primary['label']} {primary['number']}"),
        Step(id="bank_block", label="Call your bank's 24/7 anti-scam hotline / use the kill switch"),
        Step(id="evidence", label="Upload screenshots so we can fill in the details"),
        Step(id="file_report", label=f"Complete the report on {pack['portal']['name']}"),
    ]
    order = pack.get("step_order", [s.id for s in steps])
    for step in steps:
        step.label = pack.get("sos_labels", {}).get(step.id, step.label)
        step.label = pack.get(f"sos_labels_{case.language}", {}).get(step.id, step.label)
    return sorted(steps, key=lambda s: order.index(s.id) if s.id in order else len(order))


def lockdown(case: Case) -> list[Step]:
    rules = load_pack(case.country)
    pack = rules.get("lockdown_hi", rules["lockdown"]) if case.language == "hi" else rules["lockdown"]
    items = pack.get(case.scam_type.value, []) + pack["common"]
    return [Step(id=f"lock_{i}", label=txt) for i, txt in enumerate(items)]


def ensure_steps(case: Case) -> Case:
    existing = {s.id for s in case.steps}
    for s in sos_steps(case) + lockdown(case):
        if s.id not in existing:
            case.steps.append(s)
    return case


def refresh_lockdown(case: Case) -> Case:
    """Re-generate lockdown items after classification (scam type may have changed)."""
    keep = [s for s in case.steps if not s.id.startswith("lock_")]
    case.steps = keep + lockdown(case)
    return case
