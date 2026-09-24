"""The case file: one case's history, start to finish, as a single timeline.

Nothing here stores anything. The timeline is assembled on read from records
that already exist, each kept where it belongs:

  case_opened       the Case node's own `opened` date
  evidence          every record attached to the case by an APPEARS_IN edge
  network_event     dated events in the surrounding network (config.EVENT_EDGE_TYPES)
  merge             entity-resolution decisions touching that network
  finding_raised    detection findings on that network
  finding_decision  every confirm / reject an officer took on one, from the ledger
  milestone         investigative steps an officer logged (arrest, raid, ...)
  status_change     changes to the case's status, logged as milestones
  note              that a note was written, and by whom

Every input arrives already filtered to the caller's tiers, and the graph reads
here take the same tiers, so the timeline cannot show a caller more than the
rest of the console would. Standing relationships - OWNS, LOCATED_AT - are not
events and are left off, for the reason config.EVENT_EDGE_TYPES gives.

Two clocks appear side by side and are labelled rather than blended: event
time is when something happened, system time is when this system recorded or
decided it. A finding raised in 2026 about a theft in 2025 is both.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from . import config
from .graph import GraphStore

CATEGORIES = {
    "investigation": "Investigation",
    "evidence": "Evidence",
    "network": "Network activity",
    "analysis": "Analysis",
    "decision": "Decisions",
    "notes": "Notes",
}


def findings_on_network(findings: Iterable[dict[str, Any]],
                        node_ids: set[str]) -> list[dict[str, Any]]:
    """Findings any part of which touches the given set of records.

    Takes findings the caller may already see; it does no tier filtering.
    """
    out = []
    for f in findings:
        touched = set(f.get("subject_ids") or [])
        touched |= {e.get("node_id") for e in (f.get("evidence") or [])}
        if touched & node_ids:
            out.append(f)
    order = {"pending": 0, "confirmed": 1, "rejected": 2}
    out.sort(key=lambda f: (order.get(f["status"], 9), -f["confidence"]))
    return out


def sort_key(ts: str | None) -> str:
    """One comparable form for every timestamp format in the system.

    Seeded events are naive, intake writes naive local time, the stores write
    UTC with an offset and milliseconds, and a case's opened date has no time
    at all. Aware times are brought to local time so that "today" means the
    same thing on both clocks.
    """
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return ts
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt.isoformat(timespec="seconds")


def _humanise(s: str) -> str:
    t = str(s).replace("_", " ")
    return t[:1].upper() + t[1:]


def _entry(kind: str, category: str, at: str | None, title: str, *,
           time_basis: str = "event", detail: str = "", actor: str = "",
           tier: str = "standard", refs: dict[str, str] | None = None,
           ingested_time: str | None = None, uid: str = "") -> dict[str, Any]:
    return {
        "id": f"{kind}:{uid}",
        "kind": kind,
        "category": category,
        "at": at,
        "sort_key": sort_key(at),
        "time_basis": time_basis,
        "title": title,
        "detail": detail,
        "actor": actor,
        "tier": tier,
        "refs": refs or {},
        "ingested_time": ingested_time,
    }


def _edge_detail(props: dict[str, Any]) -> str:
    parts = []
    for key in ("role", "basis", "relation", "channel"):
        if props.get(key):
            parts.append(_humanise(props[key]) if key == "relation" else str(props[key]))
    if props.get("amount"):
        parts.append(f"Rs {int(props['amount']):,}")
    return " · ".join(parts)


def build_timeline(g: GraphStore, case: dict[str, Any],
                   findings: list[dict[str, Any]],
                   notes: list[dict[str, Any]],
                   milestones: list[dict[str, Any]],
                   decisions: list[dict[str, Any]],
                   tiers: Iterable[str], hops: int = 2) -> dict[str, Any]:
    """Every dated thing known about one case, oldest first.

    `findings`, `notes`, `milestones` and `decisions` must already be limited
    to what the caller may see; the graph is read here under `tiers`.
    """
    tiers = list(tiers)
    case_id = case["id"]
    props = case.get("props", {})
    entries: list[dict[str, Any]] = []

    # ------------------------------------------------------------ opened
    if props.get("opened"):
        entries.append(_entry(
            "case_opened", "investigation", props["opened"], "Case registered",
            detail=" · ".join(str(x) for x in (
                props.get("crime"), props.get("district"),
                props.get("officer") and f"IO {props['officer']}") if x),
            actor=str(props.get("officer") or ""),
            refs={"node_id": case_id}, uid=case_id))

    # ---------------------------------------------------------- evidence
    vis = g.visible(tiers)
    evidence_edges: set[str] = set()
    if case_id in vis:
        for u, _, k, d in vis.in_edges(case_id, keys=True, data=True):
            if d.get("type") != "APPEARS_IN":
                continue
            evidence_edges.add(k)
            n = g._node_payload(u, vis.nodes[u])
            extra = {kk: vv for kk, vv in d.items()
                     if kk not in ("type", "tier", "event_time", "ingested_time")}
            entries.append(_entry(
                "evidence", "evidence", d.get("event_time"),
                f"{_humanise(n['label'])} entered the case: {n['display']}",
                detail=" · ".join(x for x in (_edge_detail(extra),
                                              f"source {n['source_record_id']}") if x),
                tier=n["tier"], refs={"node_id": u},
                ingested_time=d.get("ingested_time"), uid=k))

    # ---------------------------------------------------- network events
    ego = g.ego_network(case_id, hops, tiers)
    ego_ids = {n["id"] for n in ego["nodes"]}
    for ev in ego["timeline"]:
        if ev["edge_id"] in evidence_edges:
            continue
        entries.append(_entry(
            "network_event", "network", ev["event_time"],
            f"{_humanise(ev['type'].lower())}: {ev['src_display']} → {ev['dst_display']}",
            refs={"node_id": ev["src"], "other_node_id": ev["dst"]},
            ingested_time=ev.get("ingested_time"), uid=ev["edge_id"]))

    # ------------------------------------------------------------ merges
    # A merge is shown only when both of its records are visible: naming one
    # side of a merge with a hidden record would disclose that it exists.
    labels = {"auto_merge": "Records resolved as one identity",
              "human_review": "Possible match held for human review"}
    for m in g.merges:
        if m.get("decision") not in labels:
            continue
        if not ({m["left"], m["right"]} & ego_ids):
            continue
        if g.node(m["left"], tiers) is None or g.node(m["right"], tiers) is None:
            continue
        detail = (f"{m.get('left_display')} ≡ {m.get('right_display')} · "
                  f"{m.get('method')} · score {m.get('score')}")
        if m.get("reversed"):
            detail += " · since reversed"
        entries.append(_entry(
            "merge", "analysis", m.get("decided_at"), labels[m["decision"]],
            time_basis="system", detail=detail,
            actor=m.get("decided_by") or "entity resolution",
            refs={"merge_id": m["merge_id"], "node_id": m["left"]},
            uid=m["merge_id"]))

    # ---------------------------------------------------------- findings
    on_network = findings_on_network(findings, ego_ids)
    by_id = {f["finding_id"]: f for f in on_network}
    for f in on_network:
        if not f.get("created_at"):
            continue
        entries.append(_entry(
            "finding_raised", "analysis", f["created_at"],
            f"Finding raised: {f['finding_type']}", time_basis="system",
            detail=f.get("statement", ""), actor=f.get("family_label", ""),
            tier=f.get("tier", "standard"),
            refs={"finding_id": f["finding_id"]}, uid=f["finding_id"]))

    for i, d in enumerate(decisions):
        f = by_id.get(d["target"])
        if f is None:
            continue
        verb = "confirmed" if d["action"] == "FINDING_CONFIRMED" else "rejected"
        entries.append(_entry(
            "finding_decision", "decision", d["ts"],
            f"Finding {verb}: {f['finding_type']}", time_basis="system",
            detail=d.get("reason", ""), actor=d.get("actor", ""),
            tier=f.get("tier", "standard"),
            refs={"finding_id": f["finding_id"]}, uid=f"{d['seq']}-{i}"))

    # -------------------------------------------------------- milestones
    for m in milestones:
        is_status = m["kind"] == "status_change"
        entries.append(_entry(
            "status_change" if is_status else "milestone",
            "decision" if is_status else "investigation",
            m["occurred_at"],
            m["title"] if is_status else
            f"{config.MILESTONE_KINDS.get(m['kind'], _humanise(m['kind']))}: {m['title']}",
            detail=m.get("detail", ""), actor=m.get("author", ""),
            tier=m.get("tier", "standard"),
            refs={"milestone_id": m["milestone_id"]},
            ingested_time=m.get("recorded_at"), uid=m["milestone_id"]))

    # ------------------------------------------------------------- notes
    # The note's text stays in the notes panel; the timeline says only that
    # one was written, by whom and when.
    for n in notes:
        entries.append(_entry(
            "note", "notes", n["created_at"], "Note added", time_basis="system",
            actor=n.get("author", ""), tier=n.get("tier", "standard"),
            refs={"note_id": n["note_id"]}, uid=n["note_id"]))

    # Stable: entries sharing a time keep the order they were gathered in,
    # which is the order of the case's own logic (opened, then evidence...).
    entries.sort(key=lambda e: e["sort_key"])

    counts = {k: 0 for k in CATEGORIES}
    for e in entries:
        counts[e["category"]] = counts.get(e["category"], 0) + 1

    status = str(props.get("status") or "")
    return {
        "case": case,
        "status": status,
        "status_label": config.CASE_STATUSES.get(status, _humanise(status)),
        "hops": hops,
        "entries": entries,
        "counts": counts,
        "categories": CATEGORIES,
        "span": {"first": entries[0]["at"] if entries else None,
                 "last": entries[-1]["at"] if entries else None},
    }
