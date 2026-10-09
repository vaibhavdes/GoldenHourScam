"""Link cases by validated beneficiary identifiers using an in-process networkx graph."""
import re
from collections import defaultdict

import networkx as nx

from app.models import Case


def norm_identifier(kind: str, value: str) -> str:
    v = (value or "").strip().lower()
    if kind == "phone":
        v = re.sub(r"\D", "", v)[-10:]
    if kind == "account":
        v = re.sub(r"\D", "", v)
    return f"{kind}:{v}"


def identifiers(case: Case) -> set[str]:
    ids: set[str] = set()
    for t in case.transactions:
        if t.direction != "debit":
            continue
        b = t.beneficiary
        if b.vpa.value and b.vpa.valid:
            ids.add(norm_identifier("vpa", b.vpa.value))
        if b.account.value and b.account.valid:
            ids.add(norm_identifier("account", b.account.value))
    return ids


def build_graph(cases: list[Case]) -> nx.Graph:
    g = nx.Graph()
    for c in cases:
        g.add_node(c.id, kind="case")
        for ident in identifiers(c):
            # Bank account numbers live in a country namespace; do not mix currencies
            # or connect unrelated accounts just because their digits are identical.
            node = (c.country, ident)
            g.add_node(node, kind="identifier", label=ident)
            g.add_edge(c.id, node)
    return g


def clusters(cases: list[Case]) -> list[dict]:
    g = build_graph(cases)
    by_id = {c.id: c for c in cases}
    out = []
    for comp in nx.connected_components(g):
        case_ids = sorted(n for n in comp if g.nodes[n]["kind"] == "case")
        if len(case_ids) < 2:
            continue
        idents = [n for n in comp if g.nodes[n]["kind"] == "identifier"]
        shared = sorted(g.nodes[i]["label"] for i in idents if g.degree(i) >= 2)
        total = sum(by_id[cid].total_lost() for cid in case_ids)
        out.append({
            "case_ids": case_ids,
            "shared_identifiers": shared,
            "victims": len(case_ids),
            "total_lost": round(total, 2),
            "currency": next((t.currency for cid in case_ids for t in by_id[cid].transactions), "INR"),
        })
    out.sort(key=lambda c: (-c["victims"], -c["total_lost"]))
    return out


def linked_count(case: Case, cases: list[Case]) -> int:
    """How many *other* cases share at least one identifier with this case."""
    mine = identifiers(case)
    if not mine:
        return 0
    index: dict[str, set[str]] = defaultdict(set)
    for c in cases:
        if c.country != case.country:
            continue
        for i in identifiers(c):
            index[i].add(c.id)
    others: set[str] = set()
    for i in mine:
        others |= index[i]
    others.discard(case.id)
    return len(others)
