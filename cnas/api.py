"""FastAPI surface.

Every endpoint resolves the caller's tiers server-side and passes them into the
graph query layer. Nothing is filtered client-side, and there is no endpoint
that returns the unfiltered graph.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

from fastapi import (Body, Depends, FastAPI, File, HTTPException, Query,
                     UploadFile)
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import (casefile, config, extract as extract_mod, intake as intake_mod,
               mechanisms, report as report_mod, store as store_mod)
from .auth import Principal, current
from .er import Resolver
from .graph import GraphStore

app = FastAPI(title="CNAS", version="0.1.0",
              description="Criminal Network Analysis System - prototype (SIH 26189)")

_graph: GraphStore | None = None
_findings: list[dict[str, Any]] = []

# The case-file tables were added after the first databases were built. Every
# CREATE is IF NOT EXISTS, so this is a no-op on a current database and brings
# an older one up to date without a pipeline rebuild wiping it.
store_mod.init()

# The graph and the findings are held in memory between requests, and
# run_pipeline.py rebuilds both files from seed underneath a running server.
# Without this, a server started before the rebuild would keep serving the old
# graph and then write it back over the new one on the next ingestion - a reset
# that silently undoes itself, which is the worst way to find out mid-demo.
_mtimes: dict[str, float] = {}


def _stale(key: str, path) -> bool:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return False
    if _mtimes.get(key) == mtime:
        return False
    _mtimes[key] = mtime
    return True


def _mark_written(key: str, path) -> None:
    try:
        _mtimes[key] = path.stat().st_mtime
    except OSError:
        _mtimes.pop(key, None)


def graph() -> GraphStore:
    global _graph
    if _stale("graph", config.GRAPH_PATH) or _graph is None:
        _graph = GraphStore.load()
    return _graph


def findings() -> list[dict[str, Any]]:
    global _findings
    if _stale("findings", config.FINDINGS_PATH) or not _findings:
        _findings = json.loads(config.FINDINGS_PATH.read_text(encoding="utf-8"))
    return _findings


def _persist_findings() -> None:
    config.FINDINGS_PATH.write_text(
        json.dumps(_findings, indent=2, ensure_ascii=False), encoding="utf-8")
    _mark_written("findings", config.FINDINGS_PATH)


def _visible_findings(p: Principal) -> list[dict[str, Any]]:
    return [f for f in findings() if p.can_see(f.get("tier", "standard"))]


# --------------------------------------------------------------------- session

@app.get("/api/session")
def session(p: Principal = Depends(current)) -> dict[str, Any]:
    g = graph()
    return {
        "principal": p.to_dict(),
        "roles": [{"id": k, **{kk: vv for kk, vv in v.items() if kk != "tiers"},
                   "tiers": v["tiers"]} for k, v in config.ROLES.items()],
        "stats": g.stats(p.tiers),
        "hidden_from_you": g.hidden_count(p.tiers),
        "findings_visible": len(_visible_findings(p)),
        "findings_total_all_tiers": len(findings()),
        "case_vocab": {
            "statuses": config.CASE_STATUSES,
            "milestone_kinds": {k: v for k, v in config.MILESTONE_KINDS.items()
                                if k not in config.SYSTEM_MILESTONE_KINDS},
            "note_colors": config.NOTE_COLORS,
            "note_max_chars": config.NOTE_MAX_CHARS,
            "categories": casefile.CATEGORIES,
        },
    }


@app.get("/api/overview")
def overview(p: Principal = Depends(current)) -> dict[str, Any]:
    g = graph()
    store_mod.audit(p.actor, p.role, "VIEW", "overview", {})
    vis = _visible_findings(p)
    by_family: dict[str, int] = {}
    for f in vis:
        by_family[f["family_label"]] = by_family.get(f["family_label"], 0) + 1
    return {
        "stats": g.stats(p.tiers),
        "cases": sorted(g.all_cases(p.tiers), key=lambda c: c["id"]),
        "by_family": by_family,
        "pending": sum(1 for f in vis if f["status"] == "pending"),
        "confirmed": sum(1 for f in vis if f["status"] == "confirmed"),
        "rejected": sum(1 for f in vis if f["status"] == "rejected"),
        "hidden_from_you": g.hidden_count(p.tiers),
    }


# ----------------------------------------------------------------------- graph

@app.get("/api/ego-network/{node_id}")
def ego_network(node_id: str, hops: int = Query(2, ge=1, le=4),
                p: Principal = Depends(current)) -> dict[str, Any]:
    g = graph()
    t0 = time.perf_counter()
    result = g.ego_network(node_id, hops, p.tiers)
    result["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    result["hops"] = hops
    store_mod.audit(p.actor, p.role, "QUERY_EGO_NETWORK", node_id,
                    {"hops": hops, "returned": len(result["nodes"])})
    return result


@app.get("/api/node/{node_id}")
def node(node_id: str, p: Principal = Depends(current)) -> dict[str, Any]:
    g = graph()
    n = g.node(node_id, p.tiers)
    if n is None:
        # A node outside the caller's tier is reported as absent, never as
        # forbidden: "403" would itself disclose that the record exists (R7).
        raise HTTPException(status_code=404, detail="no such record")
    store_mod.audit(p.actor, p.role, "READ_NODE", node_id, {"label": n["label"]})
    n["cases"] = g.cases_for(node_id, p.tiers)
    n["resolved_from"] = g.resolved_group(node_id, p.tiers)
    return n


@app.get("/api/chain")
def chain(src: str = "C-001", dst: str = "C-005",
          p: Principal = Depends(current)) -> dict[str, Any]:
    g = graph()
    result = g.path_between(src, dst, p.tiers)
    store_mod.audit(p.actor, p.role, "TRACE_PATH", f"{src}->{dst}",
                    {"found": result["found"]})
    return result


# -------------------------------------------------------------------- findings

@app.get("/api/findings")
def list_findings(status: str | None = None, family: str | None = None,
                  p: Principal = Depends(current)) -> dict[str, Any]:
    vis = _visible_findings(p)
    if status:
        vis = [f for f in vis if f["status"] == status]
    if family:
        vis = [f for f in vis if f["mechanism_family"] == family]
    order = {"pending": 0, "confirmed": 1, "rejected": 2}
    vis.sort(key=lambda f: (order.get(f["status"], 9), -f["confidence"]))
    store_mod.audit(p.actor, p.role, "VIEW", "review_queue",
                    {"returned": len(vis), "filters": {"status": status, "family": family}})
    return {"findings": vis, "families": config.MECHANISM_FAMILIES}


@app.get("/api/findings/{finding_id}")
def get_finding(finding_id: str, p: Principal = Depends(current)) -> dict[str, Any]:
    for f in _visible_findings(p):
        if f["finding_id"] == finding_id:
            store_mod.audit(p.actor, p.role, "READ_FINDING", finding_id, {})
            return f
    raise HTTPException(status_code=404, detail="no such finding")


def _decide(finding_id: str, p: Principal, status: str, reason: str) -> dict[str, Any]:
    for f in _findings:
        if f["finding_id"] != finding_id:
            continue
        if not p.can_see(f.get("tier", "standard")):
            raise HTTPException(status_code=404, detail="no such finding")
        f["status"] = status
        f["decision_reason"] = reason
        f["decided_by"] = p.display
        f["decided_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        _persist_findings()
        store_mod.audit(p.actor, p.role, f"FINDING_{status.upper()}", finding_id,
                        {"reason": reason, "mechanism": f["mechanism"],
                         "confidence": f["confidence"]})
        return f
    raise HTTPException(status_code=404, detail="no such finding")


@app.post("/api/findings/{finding_id}/confirm")
def confirm(finding_id: str, payload: dict = Body(default={}),
            p: Principal = Depends(current)) -> dict[str, Any]:
    findings()
    return _decide(finding_id, p, "confirmed",
                   payload.get("reason") or "Confirmed by reviewing officer.")


@app.post("/api/findings/{finding_id}/reject")
def reject(finding_id: str, payload: dict = Body(default={}),
           p: Principal = Depends(current)) -> dict[str, Any]:
    findings()
    reason = (payload.get("reason") or "").strip()
    if not reason:
        # A rejection without a reason teaches the system nothing (P4).
        raise HTTPException(status_code=400,
                            detail="a rejection must carry a reason")
    return _decide(finding_id, p, "rejected", reason)


# --------------------------------------------------------------------- reports

def _doc(blocks: list, basename: str, fmt: str,
         p: Principal, report_id: str, target: str,
         detail: dict[str, Any]) -> Response:
    """Render, log the export against the audit chain, and return the file."""
    payload, filename, media_type, digest = report_mod.render(blocks, basename, fmt)
    store_mod.audit(p.actor, p.role, "REPORT_EXPORT", target,
                    {"report_id": report_id, "format": filename.rsplit(".", 1)[-1],
                     "sha256": digest, **detail})
    return Response(
        content=payload,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"',
                 "X-CNAS-Filename": filename},
    )


def _findings_on_network(node_ids: set[str], p: Principal) -> list[dict[str, Any]]:
    """Findings any part of which touches the given set of records."""
    return casefile.findings_on_network(_visible_findings(p), node_ids)


@app.get("/api/report/case/{case_id}")
def report_case(case_id: str, hops: int = Query(2, ge=1, le=4),
                format: str = Query("docx", pattern="^(docx|doc)$"),
                p: Principal = Depends(current)) -> Response:
    g = graph()
    case = g.node(case_id, p.tiers)
    if case is None or case["label"] != "Case":
        raise HTTPException(status_code=404, detail="no such case")

    ego = g.ego_network(case_id, hops, p.tiers)
    ego["hops"] = hops
    rel = _findings_on_network({n["id"] for n in ego["nodes"]}, p)

    blocks, report_id = report_mod.case_report(
        case, ego, rel, p, hidden_count=g.hidden_count(p.tiers))
    return _doc(blocks, f"CNAS-Case-Report-{case_id}", format, p, report_id,
                case_id, {"kind": "case", "findings": len(rel), "hops": hops})


@app.get("/api/report/finding/{finding_id}")
def report_finding(finding_id: str,
                   format: str = Query("docx", pattern="^(docx|doc)$"),
                   p: Principal = Depends(current)) -> Response:
    for f in _visible_findings(p):
        if f["finding_id"] == finding_id:
            blocks, report_id = report_mod.finding_report(f, p)
            return _doc(blocks, f"CNAS-Finding-Report-{finding_id}", format, p,
                        report_id, finding_id, {"kind": "finding"})
    raise HTTPException(status_code=404, detail="no such finding")


@app.get("/api/report/queue")
def report_queue(status: str | None = None, family: str | None = None,
                 format: str = Query("docx", pattern="^(docx|doc)$"),
                 p: Principal = Depends(current)) -> Response:
    vis = _visible_findings(p)
    scope = []
    if status:
        vis = [f for f in vis if f["status"] == status]
        scope.append(f"status: {status}")
    if family:
        vis = [f for f in vis if f["mechanism_family"] == family]
        scope.append(f"mechanism: {config.MECHANISM_FAMILIES.get(family, family)}")
    order = {"pending": 0, "confirmed": 1, "rejected": 2}
    vis.sort(key=lambda f: (order.get(f["status"], 9), -f["confidence"]))

    blocks, report_id = report_mod.queue_report(
        vis, p, scope=" · ".join(scope) if scope else "All findings visible at this tier")
    return _doc(blocks, "CNAS-Review-Queue-Report", format, p, report_id,
                "review_queue", {"kind": "queue", "findings": len(vis),
                                 "filters": {"status": status, "family": family}})


# ---------------------------------------------------------------------- merges

@app.get("/api/merges/{merge_id}")
def get_merge(merge_id: str, p: Principal = Depends(current)) -> dict[str, Any]:
    m = graph().merge_record(merge_id)
    if not m:
        raise HTTPException(status_code=404, detail="no such merge")
    store_mod.audit(p.actor, p.role, "READ_MERGE", merge_id, {})
    return m


@app.post("/api/merges/{merge_id}/unmerge")
def unmerge(merge_id: str, payload: dict = Body(default={}),
            p: Principal = Depends(current)) -> dict[str, Any]:
    g = graph()
    m = g.merge_record(merge_id)
    if not m:
        raise HTTPException(status_code=404, detail="no such merge")
    ok = g.unmerge(merge_id)
    g.save()
    _mark_written("graph", config.GRAPH_PATH)
    store_mod.audit(p.actor, p.role, "MERGE_REVERSED", merge_id,
                    {"reason": payload.get("reason", ""), "applied": ok})
    return {"merge_id": merge_id, "reversed": ok, "pre_state": m["pre_state"]}


# ---------------------------------------------------------------------- intake

@app.get("/api/intake/schema")
def intake_schema(p: Principal = Depends(current)) -> dict[str, Any]:
    """The vocabulary the form may offer, read off the data it will join."""
    return {
        "mo_features": intake_mod.mo_vocabulary(graph()),
        "packs": [{"id": k, "label": v} for k, v in sorted(config.PACK_LABELS.items())],
    }


MAX_UPLOAD_BYTES = 8 * 1024 * 1024


@app.post("/api/intake/parse")
async def intake_parse(file: UploadFile = File(...),
                       p: Principal = Depends(current)) -> dict[str, Any]:
    """Read an FIR document and propose an intake submission from it.

    Nothing is written to the graph. The result is a proposal an officer
    reviews, so the parse is deliberately a separate call from the ingestion:
    a document that ingested itself the moment it was dropped would put a
    machine's reading of an FIR into the record with nobody having seen it.
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="the file is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"the file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")

    try:
        text, how = extract_mod.read_document(file.filename or "", data)
    except extract_mod.ExtractionError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    result = extract_mod.parse_fir(text)

    # A parsed modus operandi value the graph has never recorded would produce
    # a vector the mechanism has nothing to compare against, so it is flagged
    # here rather than silently offered to the officer as though it were usable.
    vocab = intake_mod.mo_vocabulary(graph())
    for key, entry in list(result["mo_features"].items()):
        if entry["value"] not in vocab.get(key, []):
            entry["unusable"] = True

    result["source"] = {
        "filename": file.filename, "how": how,
        "characters": len(text), "bytes": len(data),
    }
    result["text"] = text[:40000]
    store_mod.audit(p.actor, p.role, "DOCUMENT_PARSED", file.filename or "upload",
                    {"how": how, "characters": len(text), **result["counts"]})
    return result


@app.post("/api/intake/fir")
def intake_fir(payload: dict = Body(...),
               p: Principal = Depends(current)) -> dict[str, Any]:
    """Ingest one FIR and run it against the records already held.

    Only the deterministic resolver runs here. A probabilistic merge belongs in
    the review queue with a human in front of it, which is what the existing
    pipeline already does; a record arriving through this door does not get a
    shortcut past that.
    """
    g = graph()
    findings()
    try:
        created = intake_mod.ingest(g, payload, p.display)
    except intake_mod.IntakeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    new_ids = set(created["node_ids"])
    store_mod.audit(p.actor, p.role, "INGEST", created["case_id"],
                    {"nodes": len(created["nodes"]), "edges": len(created["edges"]),
                     "source": "evidence_intake", "synthetic": True})

    # --- entity resolution, scoped to what has just arrived
    resolver = Resolver(g)
    known = {m["merge_id"] for m in g.merges}
    merges = [m for m in resolver.deterministic_pass()
              if (m["left"] in new_ids or m["right"] in new_ids)
              and m["merge_id"] not in known]
    for m in merges:
        g.apply_merge(m)
        store_mod.audit(p.actor, p.role, "MERGE_DECISION", m["merge_id"],
                        {"decision": m["decision"], "score": m["score"],
                         "method": m["method"], "left": m["left"], "right": m["right"]})

    # --- modus operandi, against every case already on file
    new_findings: list[dict[str, Any]] = []
    if created["has_mo_profile"]:
        existing = {f["finding_id"] for f in _findings}
        # The vectoriser refits over the enlarged corpus, so scores on existing
        # pairs shift slightly. Findings are added by id and never replaced by
        # it: overwriting one would silently revert a decision an officer has
        # already taken on it.
        for f in mechanisms.mo_similarity(g):
            if f.finding_id in existing:
                continue
            if created["case_id"] not in f.subject_ids:
                continue
            f.created_at = store_mod.now()
            new_findings.append(f.to_dict())
            store_mod.audit(p.actor, p.role, "FINDING_CREATED", f.finding_id,
                            {"mechanism": f.mechanism, "confidence": f.confidence,
                             "tier": f.tier})

    _findings.extend(new_findings)
    _persist_findings()
    g.save()
    _mark_written("graph", config.GRAPH_PATH)

    # Which records the new case attached itself to is the whole point, so it
    # is returned rather than left to be inferred from the redrawn graph.
    attached = sorted({m["left"] for m in merges} | {m["right"] for m in merges})
    return {
        "case_id": created["case_id"],
        "created_nodes": created["node_ids"],
        "created_edges": created["edge_ids"],
        "merges": merges,
        "attached_to": [n for n in attached if n not in new_ids],
        "findings": new_findings,
    }


# ------------------------------------------------------------------- case file
#
# Notes, milestones and status belong to a case, so every route here starts by
# resolving the case under the caller's tiers: a case the caller cannot see has
# no notes and no timeline, and is reported as absent rather than forbidden.
#
# The audit ledger is not tier-filtered - every role can read it - so the
# entries written here record what was done and to which case, with the tier,
# length and a digest of any text, and never the text itself. A Restricted
# analyst's note about a Restricted record must not reach a Standard officer
# by way of the audit tab.

def _case_or_404(case_id: str, p: Principal) -> dict[str, Any]:
    case = graph().node(case_id, p.tiers)
    if case is None or case["label"] != "Case":
        raise HTTPException(status_code=404, detail="no such case")
    return case


def _tier_for(payload: dict, p: Principal) -> str:
    """The tier a new note or milestone is filed at.

    Defaults to the author's most sensitive tier, which fails closed: an
    analyst writing about a Restricted record who forgets to choose has not
    published it to every officer. Lowering it is a choice they make.
    """
    tier = str(payload.get("tier") or p.tiers[-1])
    if tier not in p.tiers:
        raise HTTPException(status_code=400,
                            detail="you cannot file material at that tier")
    return tier


def _note_text(payload: dict) -> str:
    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="a note cannot be empty")
    if len(text) > config.NOTE_MAX_CHARS:
        raise HTTPException(status_code=400,
                            detail=f"a note is limited to {config.NOTE_MAX_CHARS} characters")
    return text


def _note_color(payload: dict) -> str:
    color = str(payload.get("color") or config.NOTE_COLORS[0])
    if color not in config.NOTE_COLORS:
        raise HTTPException(status_code=400, detail="unknown note colour")
    return color


def _own_note(case_id: str, note_id: str, p: Principal) -> dict[str, Any]:
    note = store_mod.get_note(case_id, note_id)
    if note is None or not p.can_see(note["tier"]):
        raise HTTPException(status_code=404, detail="no such note")
    # The login is a role, so authorship is by role: a note can be changed by
    # whoever holds the role that wrote it, and seen by anyone cleared for it.
    if note["role"] != p.role:
        raise HTTPException(status_code=403,
                            detail="only the author of a note can change it")
    return note


def _note_audit(note: dict[str, Any]) -> dict[str, Any]:
    return {"note_id": note["note_id"], "tier": note["tier"],
            "chars": len(note["text"]),
            "sha256": store_mod.content_digest(note["text"])}


@app.get("/api/cases/{case_id}/notes")
def list_notes(case_id: str, p: Principal = Depends(current)) -> dict[str, Any]:
    _case_or_404(case_id, p)
    notes = store_mod.list_notes(case_id, p.tiers)
    for n in notes:
        n["mine"] = n["role"] == p.role
    return {"case_id": case_id, "notes": notes}


@app.post("/api/cases/{case_id}/notes")
def add_note(case_id: str, payload: dict = Body(...),
             p: Principal = Depends(current)) -> dict[str, Any]:
    _case_or_404(case_id, p)
    note = store_mod.add_note(case_id, _note_text(payload), _note_color(payload),
                              _tier_for(payload, p), p.display, p.role)
    store_mod.audit(p.actor, p.role, "NOTE_ADDED", case_id, _note_audit(note))
    return {**note, "mine": True}


@app.patch("/api/cases/{case_id}/notes/{note_id}")
def edit_note(case_id: str, note_id: str, payload: dict = Body(...),
              p: Principal = Depends(current)) -> dict[str, Any]:
    _case_or_404(case_id, p)
    note = _own_note(case_id, note_id, p)
    changes: dict[str, Any] = {}
    if "text" in payload:
        changes["text"] = _note_text(payload)
    if "color" in payload:
        changes["color"] = _note_color(payload)
    if "tier" in payload:
        changes["tier"] = _tier_for(payload, p)
    if not changes:
        raise HTTPException(status_code=400, detail="nothing to change")
    store_mod.update_note(note_id, changes)
    updated = store_mod.get_note(case_id, note_id)
    store_mod.audit(p.actor, p.role, "NOTE_EDITED", case_id,
                    {**_note_audit(updated), "fields": sorted(changes),
                     "previous_sha256": store_mod.content_digest(note["text"])})
    return {**updated, "mine": True}


@app.delete("/api/cases/{case_id}/notes/{note_id}")
def delete_note(case_id: str, note_id: str,
                p: Principal = Depends(current)) -> dict[str, Any]:
    _case_or_404(case_id, p)
    note = _own_note(case_id, note_id, p)
    store_mod.soft_delete_note(note_id)
    store_mod.audit(p.actor, p.role, "NOTE_DELETED", case_id, _note_audit(note))
    return {"note_id": note_id, "deleted": True}


@app.get("/api/cases/{case_id}/timeline")
def case_timeline(case_id: str, hops: int = Query(2, ge=1, le=4),
                  p: Principal = Depends(current)) -> dict[str, Any]:
    case = _case_or_404(case_id, p)
    vis = _visible_findings(p)
    decisions = [d for d in store_mod.audit_for_targets(f["finding_id"] for f in vis)
                 if d["action"] in ("FINDING_CONFIRMED", "FINDING_REJECTED")]
    result = casefile.build_timeline(
        graph(), case, vis,
        notes=store_mod.list_notes(case_id, p.tiers),
        milestones=store_mod.list_milestones(case_id, p.tiers),
        decisions=decisions, tiers=p.tiers, hops=hops)
    store_mod.audit(p.actor, p.role, "VIEW_TIMELINE", case_id,
                    {"entries": len(result["entries"]), "hops": hops})
    return result


def _occurred_at(value: Any) -> str:
    text = str(value or "").strip()
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        raise HTTPException(status_code=400,
                            detail="the date must be given as YYYY-MM-DD or "
                                   "YYYY-MM-DDTHH:MM") from None
    if when.tzinfo is not None:
        when = when.astimezone().replace(tzinfo=None)
    # A milestone is something that has happened. A diary entry for next week
    # is a plan, and a timeline that mixes the two stops being a record.
    if when > datetime.now():
        raise HTTPException(status_code=400,
                            detail="a milestone cannot be dated in the future")
    return text if len(text) == 10 else when.isoformat(timespec="minutes")


@app.post("/api/cases/{case_id}/milestones")
def add_milestone(case_id: str, payload: dict = Body(...),
                  p: Principal = Depends(current)) -> dict[str, Any]:
    _case_or_404(case_id, p)
    kind = str(payload.get("kind") or "")
    if kind not in config.MILESTONE_KINDS or kind in config.SYSTEM_MILESTONE_KINDS:
        raise HTTPException(status_code=400, detail="unknown milestone kind")
    title = str(payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="a milestone needs a title")
    if len(title) > config.MILESTONE_TITLE_MAX:
        raise HTTPException(status_code=400, detail="the title is too long")
    detail = str(payload.get("detail") or "").strip()
    if len(detail) > config.MILESTONE_DETAIL_MAX:
        raise HTTPException(status_code=400, detail="the detail is too long")
    m = store_mod.add_milestone(case_id, kind, title, detail,
                                _occurred_at(payload.get("occurred_at")),
                                _tier_for(payload, p), p.display, p.role)
    store_mod.audit(p.actor, p.role, "MILESTONE_ADDED", case_id,
                    {"milestone_id": m["milestone_id"], "kind": kind,
                     "tier": m["tier"]})
    return m


def _status_label(s: str) -> str:
    return config.CASE_STATUSES.get(s, s.replace("_", " ") or "none")


@app.post("/api/cases/{case_id}/status")
def set_status(case_id: str, payload: dict = Body(...),
               p: Principal = Depends(current)) -> dict[str, Any]:
    case = _case_or_404(case_id, p)
    status = str(payload.get("status") or "")
    if status not in config.CASE_STATUSES:
        raise HTTPException(status_code=400, detail="unknown case status")
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        # As with a rejected finding, a change nobody can account for later
        # is not a decision on the record.
        raise HTTPException(status_code=400,
                            detail="a status change must carry a reason")
    if len(reason) > config.MILESTONE_DETAIL_MAX:
        raise HTTPException(status_code=400, detail="the reason is too long")
    previous = str(case["props"].get("status") or "")
    if status == previous:
        raise HTTPException(status_code=400, detail="the case already has that status")
    _tier_for(payload, p)   # refuse before anything is written, not after

    # The graph holds the case twice - the NetworkX node and the raw record it
    # is saved from - and both must change, or the next save reverts it.
    g = graph()
    g.g.nodes[case_id]["status"] = status
    for n in g.raw["nodes"]:
        if n["id"] == case_id:
            n.setdefault("props", {})["status"] = status
    g.save()
    _mark_written("graph", config.GRAPH_PATH)

    # The status itself is a property of the case and everyone who can see
    # the case sees it. The reason for the change is authored text, and can
    # name what only the author is cleared for, so the timeline entry that
    # carries it is filed like a note: at the author's tier unless lowered.
    m = store_mod.add_milestone(
        case_id, "status_change",
        f"{_status_label(previous)} → {_status_label(status)}", reason,
        datetime.now().isoformat(timespec="minutes"),
        _tier_for(payload, p), p.display, p.role)
    store_mod.audit(p.actor, p.role, "CASE_STATUS_CHANGED", case_id,
                    {"from": previous, "to": status,
                     "milestone_id": m["milestone_id"],
                     "reason_sha256": store_mod.content_digest(reason)})
    return {"case_id": case_id, "status": status, "previous": previous,
            "milestone": m}


# ------------------------------------------------------------------- emergency

@app.get("/api/emergency-lookup")
def emergency_lookup(q: str = Query(..., min_length=3),
                     p: Principal = Depends(current)) -> dict[str, Any]:
    """Direct indexed retrieval. No queue, no scoring, no model (FR-UX-7)."""
    g = graph()
    t0 = time.perf_counter()
    hits = g.search(q, p.tiers)
    for h in hits:
        h["cases"] = g.cases_for(h["node"]["id"], p.tiers)
    elapsed = round((time.perf_counter() - t0) * 1000, 2)
    store_mod.audit(p.actor, p.role, "EMERGENCY_LOOKUP", q,
                    {"hits": len(hits), "elapsed_ms": elapsed})
    return {"query": q, "hits": hits, "elapsed_ms": elapsed,
            "target_ms": 1000, "within_target": elapsed < 1000}


# ----------------------------------------------------------------------- audit

@app.get("/api/audit-log")
def audit_log(limit: int = Query(200, ge=1, le=1000),
              p: Principal = Depends(current)) -> dict[str, Any]:
    return {"entries": store_mod.read_audit(limit),
            "verification": store_mod.verify_chain()}


@app.get("/api/audit-log/verify")
def audit_verify(p: Principal = Depends(current)) -> dict[str, Any]:
    result = store_mod.verify_chain()
    store_mod.audit(p.actor, p.role, "AUDIT_VERIFY", "chain",
                    {"intact": result["intact"]})
    return result


@app.get("/api/models")
def models(p: Principal = Depends(current)) -> dict[str, Any]:
    return {"models": store_mod.read_models()}


# -------------------------------------------------------------------------- ui

@app.get("/")
def index() -> FileResponse:
    return FileResponse(config.WEB_DIR / "index.html")


@app.exception_handler(404)
async def not_found(request, exc):
    return JSONResponse(status_code=404, content={"detail": getattr(exc, "detail", "not found")})


app.mount("/static", StaticFiles(directory=str(config.WEB_DIR)), name="static")

# The sample FIRs are served so the intake demonstration is one click rather
# than a file dialogue on someone else's laptop. They are synthetic documents
# in the repository, not data.
if config.SAMPLES_DIR.is_dir():
    app.mount("/samples", StaticFiles(directory=str(config.SAMPLES_DIR)),
              name="samples")
