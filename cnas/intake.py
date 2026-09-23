"""Evidence intake: a new FIR arriving at a graph that already exists.

The form is structured rather than a document drop. NER is pre-extracted at
data-generation time in this build, so asking an officer to type the narrative
and then pretending to read identifiers out of it would be a claim the system
cannot support. The identifiers are asked for.

Everything downstream of the form is the production path: the same
deterministic resolver, the same modus operandi mechanism, the same
Explainability Contract, the same hash-chained ledger. Nothing here is a
special case for demonstration.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from . import config
from .graph import GraphStore

# Free text goes into the narrative only. Every structured field is either
# chosen from the existing vocabulary or matched against one of these, so a
# malformed identifier cannot reach the resolver as though it were clean.
PATTERNS = {
    "number": re.compile(r"^[0-9 +\-()]{6,20}$"),
    "imei": re.compile(r"^[0-9]{14,17}$"),
    "account_no": re.compile(r"^[0-9]{6,20}$"),
    "registration": re.compile(r"^[A-Za-z0-9 \-]{4,16}$"),
    "dob": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    "opened": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
}


class IntakeError(ValueError):
    """A submission the graph should not be asked to hold."""


def mo_vocabulary(store: GraphStore) -> dict[str, list[str]]:
    """The modus operandi attributes and the values already in use.

    Derived from the data rather than declared here, so the form can only offer
    values the mechanism is able to compare against something.
    """
    vocab: dict[str, set[str]] = {}
    for profile in store.mo_profiles.values():
        for k, v in profile.get("features", {}).items():
            vocab.setdefault(k, set()).add(str(v))
    return {k: sorted(v) for k, v in sorted(vocab.items())}


def _next_id(store: GraphStore, prefix: str) -> str:
    """The next free id in a series, at the width the series already uses."""
    used = [n for n in store.g.nodes if n.startswith(prefix + "-")]
    width = max((len(n.split("-", 1)[1]) for n in used), default=3)
    nums = []
    for n in used:
        tail = n.split("-", 1)[1]
        if tail.isdigit():
            nums.append(int(tail))
    return f"{prefix}-{max(nums, default=0) + 1:0{width}d}"


def _clean(value: Any, field: str, *, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    pattern = PATTERNS.get(field)
    if pattern and not pattern.match(text):
        raise IntakeError(f"{label} is not in a form this system can index")
    return text


def _required(payload: dict, key: str, label: str, limit: int = 400) -> str:
    text = str(payload.get(key) or "").strip()
    if not text:
        raise IntakeError(f"{label} is required")
    return text[:limit]


def ingest(store: GraphStore, payload: dict[str, Any],
           actor: str) -> dict[str, Any]:
    """Add one FIR and its records to the graph. Returns what was created.

    The graph is mutated in place and saved by the caller, so a failure here
    leaves nothing half-written: everything is validated before the first node
    is added.
    """
    title = _required(payload, "title", "Case title", 120)
    district = _required(payload, "district", "District", 60)
    narrative = _required(payload, "narrative", "FIR narrative", 4000)
    officer = str(payload.get("officer") or "").strip()[:60] or actor

    try:
        pack = int(payload.get("pack"))
    except (TypeError, ValueError):
        raise IntakeError("Crime pack is required") from None
    if pack not in config.PACK_LABELS:
        raise IntakeError("Unknown crime pack")

    opened = _clean(payload.get("opened"), "opened", label="Date opened")
    if not opened:
        raise IntakeError("Date opened is required")

    ident = payload.get("identifiers") or {}
    number = _clean(ident.get("number"), "number", label="Phone number")
    imei = _clean(ident.get("imei"), "imei", label="IMEI")
    account_no = _clean(ident.get("account_no"), "account_no", label="Account number")
    registration = _clean(ident.get("registration"), "registration",
                          label="Vehicle registration")

    person = payload.get("person") or {}
    person_name = str(person.get("name") or "").strip()[:80]
    person_dob = _clean(person.get("dob"), "dob", label="Date of birth")

    vocab = mo_vocabulary(store)
    features = {}
    for k, v in (payload.get("mo_features") or {}).items():
        v = str(v or "").strip()
        if not v:
            continue
        if k not in vocab:
            raise IntakeError(f"Unknown modus operandi attribute {k!r}")
        if v not in vocab[k]:
            raise IntakeError(f"{k}: {v!r} is not a recorded value for this attribute")
        features[k] = v

    # ---------------------------------------------------------------- build
    case_id = _next_id(store, "C")
    # The MO mechanism reaches a case's narrative by deriving the document id
    # from the case id, so the pairing is not optional.
    doc_id = "D-" + case_id.split("-", 1)[1]
    if doc_id in store.g:
        raise IntakeError("The document id for this case is already taken")

    src = f"INTAKE/{case_id}"
    now = datetime.now().replace(microsecond=0).isoformat()
    when = f"{opened}T00:00:00"

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    def node(node_id, label, props, suffix=""):
        nodes.append({"id": node_id, "label": label, "tier": "standard",
                      "source_record_id": src + suffix, "props": props})
        return node_id

    def edge(a, b, etype):
        edges.append({"id": f"E-{case_id}-{len(edges) + 1:02d}", "src": a, "dst": b,
                      "type": etype, "tier": "standard",
                      "event_time": when, "ingested_time": now, "props": {}})

    node(case_id, "Case", {
        "district": district, "pack": pack, "title": title,
        "crime": config.PACK_LABELS[pack], "opened": opened,
        "officer": officer, "status": "under_investigation",
    })
    node(doc_id, "Document", {"doc_type": "FIR", "case": case_id,
                              "language": "en", "narrative": narrative}, "/FIR")
    edge(doc_id, case_id, "APPEARS_IN")

    person_id = None
    if person_name:
        person_id = node(_next_id(store, "P"), "Person", {
            "name": person_name, "name_script": "latin",
            "dob": person_dob or None, "role_in_case": "accused",
        }, "/ACC1")
        edge(person_id, case_id, "APPEARS_IN")

    if number or imei:
        phone_id = node(_next_id(store, "PH"), "Phone", {
            "number": number or None, "imei": imei or None,
        }, "/CDR1")
        edge(phone_id, case_id, "APPEARS_IN")
        if person_id:
            edge(person_id, phone_id, "OWNS")

    if account_no:
        acc_id = node(_next_id(store, "ACC"), "BankAccount", {
            "account_no": account_no,
            "bank": str(ident.get("bank") or "").strip()[:60] or None,
            "holder": person_name or None,
        }, "/ACC1")
        edge(acc_id, case_id, "APPEARS_IN")
        if person_id:
            edge(person_id, acc_id, "OWNS")

    if registration:
        veh_id = node(_next_id(store, "VEH"), "Vehicle", {
            "registration": registration.upper(),
            "vtype": str(ident.get("vtype") or "").strip()[:40] or None,
        }, "/VEH1")
        edge(veh_id, case_id, "APPEARS_IN")

    # ------------------------------------------------------------- commit
    for n in nodes:
        props = {k: v for k, v in n["props"].items() if v is not None}
        store.raw["nodes"].append({**n, "props": props})
        store.g.add_node(n["id"], label=n["label"], tier=n["tier"],
                         source_record_id=n["source_record_id"], **props)
    for e in edges:
        store.raw["edges"].append(e)
        store.g.add_edge(e["src"], e["dst"], key=e["id"], type=e["type"],
                         tier=e["tier"], event_time=e["event_time"],
                         ingested_time=e["ingested_time"])

    if features:
        store.mo_profiles[case_id] = {"features": features, "narrative": narrative}
        store.raw.setdefault("mo_profiles", {})[case_id] = \
            store.mo_profiles[case_id]

    # Betweenness and communities have changed shape.
    store.invalidate_centrality()

    return {
        "case_id": case_id,
        "node_ids": [n["id"] for n in nodes],
        "edge_ids": [e["id"] for e in edges],
        "nodes": nodes,
        "edges": edges,
        "has_mo_profile": bool(features),
    }
