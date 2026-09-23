"""The case timeline: one case's history from registration to its present state."""
from __future__ import annotations

from datetime import datetime, timedelta

from conftest import RES, STD

from cnas import casefile, config
from cnas.graph import GraphStore


def timeline(client, case, who=STD, hops=2):
    r = client.get(f"/api/cases/{case}/timeline?hops={hops}", headers=who)
    assert r.status_code == 200, r.text
    return r.json()


def kinds(t):
    return [e["kind"] for e in t["entries"]]


def test_c001_tells_the_whole_story_in_order(client):
    t = timeline(client, "C-001")
    assert t["status"] == "confirmed"
    ks = set(kinds(t))
    assert {"case_opened", "evidence", "network_event", "merge",
            "finding_raised", "milestone", "status_change"} <= ks

    keys = [e["sort_key"] for e in t["entries"]]
    assert keys == sorted(keys)
    assert t["entries"][0]["kind"] == "case_opened"

    titles = " | ".join(e["title"] for e in t["entries"])
    assert "Fenced to" in titles                        # how the network built
    assert "Receiver of stolen property arrested" in titles
    assert sum(t["counts"].values()) == len(t["entries"])

    # Evidence is dated when it happened and when the system learnt of it.
    ev = next(e for e in t["entries"] if e["kind"] == "evidence")
    assert ev["time_basis"] == "event" and ev["ingested_time"]
    # Findings are system-time events, raised by the pipeline.
    fr = next(e for e in t["entries"] if e["kind"] == "finding_raised")
    assert fr["time_basis"] == "system" and fr["refs"]["finding_id"]


def test_standing_relationships_are_not_events(client):
    g = GraphStore.load()
    standing = {k for _, _, k, d in g.g.edges(keys=True, data=True)
                if d["type"] in ("OWNS", "LOCATED_AT")}
    for case in ("C-001", "C-002", "C-003", "C-005"):
        for e in timeline(client, case, RES, hops=3)["entries"]:
            assert e["id"].split(":", 1)[1] not in standing, e


def test_restricted_material_is_withheld_below_restricted(client):
    def touches_p030(t):
        return any("P-030" in e["refs"].values() for e in t["entries"])

    std = timeline(client, "C-005", STD)
    assert not touches_p030(std)
    assert all(e["tier"] == "standard" for e in std["entries"])
    assert "ACB informant report" not in str(std)

    res = timeline(client, "C-005", RES)
    assert touches_p030(res)
    assert any(e["tier"] == "restricted" and e["kind"] == "milestone"
               for e in res["entries"])
    assert len(res["entries"]) > len(std["entries"])


def test_every_finding_decision_is_on_the_timeline(client):
    base = "/api/findings/F-ER-001"
    assert client.post(f"{base}/confirm", headers=STD,
                       json={"reason": "Same IMEI and DOB"}).status_code == 200
    assert client.post(f"{base}/reject", headers=STD,
                       json={"reason": "DOB came from a copied form"}).status_code == 200

    decided = [e for e in timeline(client, "C-001")["entries"]
               if e["kind"] == "finding_decision"
               and e["refs"]["finding_id"] == "F-ER-001"]
    # The finding keeps only its last decision; the timeline keeps both.
    assert [e["title"].split(":")[0] for e in decided] == \
        ["Finding confirmed", "Finding rejected"]
    assert decided[1]["detail"] == "DOB came from a copied form"
    assert decided[0]["actor"] == "Standard Officer"


def test_add_milestone(client):
    body = {"kind": "arrest", "occurred_at": "2025-04-10T14:30",
            "title": "Accused arrested at Indore bus stand",
            "detail": "Produced before magistrate next day"}
    r = client.post("/api/cases/C-002/milestones", headers=STD, json=body)
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["milestone_id"].startswith("MS-") and m["tier"] == "standard"

    entry = next(e for e in timeline(client, "C-002")["entries"]
                 if e["refs"].get("milestone_id") == m["milestone_id"])
    assert entry["kind"] == "milestone" and entry["category"] == "investigation"
    assert entry["title"] == "Arrest: Accused arrested at Indore bus stand"
    assert entry["actor"] == "Standard Officer"


def test_milestone_validation(client):
    ok = {"kind": "arrest", "occurred_at": "2025-04-10", "title": "t"}
    post = lambda **kw: client.post("/api/cases/C-002/milestones",
                                    headers=STD, json={**ok, **kw})
    assert post().status_code == 200
    assert post(kind="teleported").status_code == 400
    # A status change is recorded by the status endpoint, never typed in.
    assert post(kind="status_change").status_code == 400
    # Confirming or closing a case is a status change, not a free milestone.
    assert post(kind="case_closed").status_code == 400
    assert post(kind="case_confirmed").status_code == 400
    assert post(occurred_at="10/04/2025").status_code == 400
    tomorrow = (datetime.now() + timedelta(days=2)).date().isoformat()
    assert post(occurred_at=tomorrow).status_code == 400
    assert post(title="  ").status_code == 400
    assert post(title="x" * 121).status_code == 400
    assert post(tier="restricted").status_code == 400
    r = client.post("/api/cases/P-001/milestones", headers=STD, json=ok)
    assert r.status_code == 404


def test_status_change(client):
    url = "/api/cases/C-002/status"
    assert client.post(url, headers=STD, json={"status": "confirmed"}).status_code == 400
    assert client.post(url, headers=STD,
                       json={"status": "solved", "reason": "x"}).status_code == 400
    r = client.post(url, headers=STD,
                    json={"status": "confirmed", "reason": "Beneficiary accounts traced"})
    assert r.status_code == 200, r.text
    assert r.json()["previous"] == "under_investigation"
    # Setting it again is not a change.
    r = client.post(url, headers=STD, json={"status": "confirmed", "reason": "again"})
    assert r.status_code == 400

    cases = client.get("/api/overview", headers=STD).json()["cases"]
    assert next(c for c in cases if c["id"] == "C-002")["props"]["status"] == "confirmed"
    # Written through to the saved graph, not only held in memory.
    assert GraphStore.load().g.nodes["C-002"]["status"] == "confirmed"

    t = timeline(client, "C-002")
    assert t["status"] == "confirmed"
    change = [e for e in t["entries"] if e["kind"] == "status_change"][-1]
    assert change["title"] == "Under investigation → Confirmed"
    assert change["detail"] == "Beneficiary accounts traced"
    assert change["category"] == "decision"

    log = client.get("/api/audit-log", headers=STD).json()
    entry = next(e for e in log["entries"] if e["action"] == "CASE_STATUS_CHANGED")
    assert entry["detail"]["from"] == "under_investigation"
    assert "Beneficiary" not in str(entry["detail"])
    assert log["verification"]["intact"] is True


def test_status_reason_follows_its_authors_tier(client):
    reason = "ACB confirms P-030 was paid through hawala"
    r = client.post("/api/cases/C-005/status", headers=RES,
                    json={"status": "under_trial", "reason": reason})
    assert r.status_code == 200, r.text
    assert r.json()["milestone"]["tier"] == "restricted"

    # The status is the case's, and everyone who can see the case sees it...
    cases = client.get("/api/overview", headers=STD).json()["cases"]
    assert next(c for c in cases if c["id"] == "C-005")["props"]["status"] == "under_trial"
    std = timeline(client, "C-005", STD)
    assert std["status"] == "under_trial"
    # ...but the reason is the author's, and stays at the author's tier.
    assert "hawala" not in str(std)
    assert "hawala" in str(timeline(client, "C-005", RES))

    # Filed lower on purpose, it is visible lower.
    r = client.post("/api/cases/C-005/status", headers=RES,
                    json={"status": "closed", "reason": "Trial concluded", "tier": "standard"})
    assert r.status_code == 200
    assert "Trial concluded" in str(timeline(client, "C-005", STD))
    # And nobody can file above their own tier.
    r = client.post("/api/cases/C-002/status", headers=STD,
                    json={"status": "closed", "reason": "x", "tier": "restricted"})
    assert r.status_code == 400
    assert timeline(client, "C-002", STD)["status"] == "under_investigation"


def test_seeded_status_agrees_with_its_last_status_change(client):
    for c in client.get("/api/overview", headers=RES).json()["cases"]:
        t = timeline(client, c["id"], RES)
        changes = [e for e in t["entries"] if e["kind"] == "status_change"]
        if changes:
            assert changes[-1]["title"].endswith(t["status_label"]), c["id"]
        else:
            assert t["status"] in ("under_investigation", "active_emergency"), c["id"]


def test_notes_appear_without_their_text(client):
    client.post("/api/cases/C-001/notes", headers=STD, json={"text": "Visit the dhaba"})
    t = timeline(client, "C-001")
    note = next(e for e in t["entries"] if e["kind"] == "note")
    assert note["title"] == "Note added" and note["actor"] == "Standard Officer"
    assert "dhaba" not in str(t)
    assert t["counts"]["notes"] == 1


def test_evidence_is_dated_to_its_own_case(client):
    for case, opened in (("C-004", "2025-06-24"), ("C-007", "2025-08-30")):
        fir = next(e for e in timeline(client, case)["entries"]
                   if e["kind"] == "evidence" and e["refs"]["node_id"].startswith("D-"))
        assert fir["at"].startswith(opened), (case, fir)


def test_every_seeded_case_has_a_timeline(client):
    cases = client.get("/api/overview", headers=STD).json()["cases"]
    assert len(cases) == 7
    for c in cases:
        t = timeline(client, c["id"])
        opened = next(e for e in t["entries"] if e["kind"] == "case_opened")
        assert t["counts"]["investigation"] >= 2, c["id"]  # opened + a milestone
        # Activity in the surrounding network can predate the case - the
        # deposits behind C-003's STR happened before anyone opened a file -
        # but no investigative step on the case itself can.
        early = [e for e in t["entries"] if e["sort_key"] < opened["sort_key"]]
        assert all(e["kind"] == "network_event" for e in early), (c["id"], early)


def test_intake_case_gets_a_timeline(client):
    payload = {
        "title": "Mobile shop burglary", "district": "Ajmer", "pack": "7",
        "opened": "2025-10-01", "officer": "SI K. Rao",
        "narrative": "Shutter cut at night; handsets removed.",
        "identifiers": {"imei": "358240051111110"},
    }
    r = client.post("/api/intake/fir", headers=STD, json=payload)
    assert r.status_code == 200, r.text
    case_id = r.json()["case_id"]

    t = timeline(client, case_id)
    assert t["entries"][0]["kind"] == "case_opened"
    assert t["entries"][0]["at"] == "2025-10-01"
    assert sum(1 for e in t["entries"] if e["kind"] == "evidence") >= 2
    # The shared IMEI resolves the new handset against the ones on file.
    assert any(e["kind"] == "merge" for e in t["entries"])


def test_unknown_case_is_404(client):
    assert client.get("/api/cases/C-999/timeline", headers=STD).status_code == 404
    assert client.get("/api/cases/P-001/timeline", headers=STD).status_code == 404
    r = client.post("/api/cases/C-999/status", headers=STD,
                    json={"status": "closed", "reason": "x"})
    assert r.status_code == 404


def test_session_carries_the_case_vocabulary(client):
    v = client.get("/api/session", headers=STD).json()["case_vocab"]
    assert v["statuses"] == config.CASE_STATUSES
    assert "arrest" in v["milestone_kinds"]
    assert "status_change" not in v["milestone_kinds"]
    assert v["note_colors"] == config.NOTE_COLORS


def test_sort_key_normalises_every_format():
    assert casefile.sort_key("2025-03-12") == "2025-03-12T00:00:00"
    assert casefile.sort_key("2025-03-12T02:40:00") == "2025-03-12T02:40:00"
    aware = "2026-09-10T06:00:00.123+00:00"
    local = datetime.fromisoformat(aware).astimezone().replace(tzinfo=None)
    assert casefile.sort_key(aware) == local.isoformat(timespec="seconds")
    assert casefile.sort_key(None) == ""
    # Date-only and full timestamps compare correctly once normalised.
    assert casefile.sort_key("2025-03-12") < casefile.sort_key("2025-03-12T00:00:01")
