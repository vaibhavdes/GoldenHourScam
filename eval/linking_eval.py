"""Cluster precision/recall of identifier linking vs generator ground truth (pairwise).

  python eval/linking_eval.py      ->  eval/report_linking.md   (bars: precision >=0.95, recall >=0.90)
"""
import itertools
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from app.models import Case  # noqa: E402
from app.tools.linking import clusters  # noqa: E402
from app.services.extract import transaction_fields
from app.tools.validators import validate_case  # noqa: E402


def pairs(groups):
    out = set()
    for g in groups:
        out |= {tuple(sorted(p)) for p in itertools.combinations(g, 2)}
    return out


def main():
    data = json.loads((ROOT / "data-gen" / "out" / "cases.json").read_text(encoding="utf-8"))
    cases = []
    for item in data["cases"]:
        case = Case.model_validate(item["case"])
        for transaction in case.transactions:
            for _, obj, name in transaction_fields(transaction):
                field = getattr(obj, name)
                field.status = "user" if field.value else "missing"
                field.source_file = "user"
        cases.append(validate_case(case))
    pred = pairs([c["case_ids"] for c in clusters(cases)])
    truth = pairs(data["ground_truth_clusters"])
    tp = len(pred & truth)
    precision = tp / len(pred) if pred else 1.0
    recall = tp / len(truth) if truth else 1.0
    report = (f"# Linking eval\n\nMethod: manually prepared synthetic identifiers, validated as user-entered facts. This measures deterministic linking, not screenshot extraction.\n\nCases: {len(cases)}  |  true pairs: {len(truth)}  |  predicted pairs: {len(pred)}\n\n"
              f"- Precision: **{precision:.3f}** (bar 0.95) {'✅' if precision >= .95 else '❌'}\n"
              f"- Recall: **{recall:.3f}** (bar 0.90) {'✅' if recall >= .90 else '❌'}\n")
    (ROOT / "eval" / "report_linking.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
