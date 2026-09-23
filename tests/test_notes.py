"""Case notes: the sticky-note panel on every case page."""
from __future__ import annotations

import json

from conftest import ELV, RES, STD, rebuild

from cnas import store


def notes(client, case, who):
    r = client.get(f"/api/cases/{case}/notes", headers=who)
    assert r.status_code == 200, r.text
    return r.json()["notes"]


def add(client, case, who, **body):
    return client.post(f"/api/cases/{case}/notes", headers=who,
                       json={"text": "Check the CCTV at the petrol pump", **body})


def test_add_list_edit_delete_round_trip(client):
    r = add(client, "C-001", STD, color="blue")
    assert r.status_code == 200, r.text
    note = r.json()
    assert note["note_id"].startswith("N-")
    assert note["color"] == "blue" and note["tier"] == "standard"
    assert note["author"] == "Standard Officer" and note["mine"] is True

    listed = notes(client, "C-001", STD)
    assert [n["note_id"] for n in listed] == [note["note_id"]]
    assert notes(client, "C-002", STD) == []          # notes belong to one case

    r = client.patch(f"/api/cases/C-001/notes/{note['note_id']}", headers=STD,
                     json={"text": "Pump CCTV requested", "color": "green"})
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "Pump CCTV requested"
    assert r.json()["color"] == "green" and r.json()["updated_at"]

    r = client.delete(f"/api/cases/C-001/notes/{note['note_id']}", headers=STD)
    assert r.status_code == 200
    assert notes(client, "C-001", STD) == []
    # Deleting twice is deleting something that is no longer there.
    r = client.delete(f"/api/cases/C-001/notes/{note['note_id']}", headers=STD)
    assert r.status_code == 404


def test_tier_defaults_to_authors_highest(client):
    assert add(client, "C-005", STD).json()["tier"] == "standard"
    assert add(client, "C-005", ELV).json()["tier"] == "elevated"
    assert add(client, "C-005", RES).json()["tier"] == "restricted"
    assert add(client, "C-005", RES, tier="standard").json()["tier"] == "standard"


def test_notes_are_filtered_by_tier(client):
    add(client, "C-005", RES, text="Informant says the officer was paid")
    add(client, "C-005", ELV, text="STR received on the financier")
    add(client, "C-005", RES, text="Shared with the district", tier="standard")

    seen = {role: {n["text"] for n in notes(client, "C-005", h)}
            for role, h in (("std", STD), ("elv", ELV), ("res", RES))}
    assert seen["std"] == {"Shared with the district"}
    assert seen["elv"] == {"Shared with the district", "STR received on the financier"}
    assert len(seen["res"]) == 3


def test_cannot_file_above_own_tier(client):
    r = add(client, "C-001", STD, tier="restricted")
    assert r.status_code == 400
    r = add(client, "C-001", ELV, tier="restricted")
    assert r.status_code == 400


def test_only_the_author_role_can_change_a_note(client):
    note = add(client, "C-001", STD).json()
    url = f"/api/cases/C-001/notes/{note['note_id']}"
    # Visible to the restricted analyst, but not theirs to change.
    assert client.patch(url, headers=RES, json={"text": "x"}).status_code == 403
    assert client.delete(url, headers=RES).status_code == 403

    hidden = add(client, "C-001", RES).json()
    url = f"/api/cases/C-001/notes/{hidden['note_id']}"
    # Not visible at all: absent, never forbidden.
    assert client.patch(url, headers=STD, json={"text": "x"}).status_code == 404
    assert client.delete(url, headers=STD).status_code == 404


def test_unknown_case_and_non_case_records_are_404(client):
    assert client.get("/api/cases/C-999/notes", headers=STD).status_code == 404
    assert client.get("/api/cases/P-001/notes", headers=STD).status_code == 404
    assert add(client, "P-001", STD).status_code == 404
    # A note id from one case cannot be used through another.
    note = add(client, "C-001", STD).json()
    r = client.delete(f"/api/cases/C-002/notes/{note['note_id']}", headers=STD)
    assert r.status_code == 404


def test_validation(client):
    assert add(client, "C-001", STD, text="   ").status_code == 400
    assert add(client, "C-001", STD, text="x" * 4001).status_code == 400
    assert add(client, "C-001", STD, color="purple").status_code == 400
    note = add(client, "C-001", STD).json()
    r = client.patch(f"/api/cases/C-001/notes/{note['note_id']}", headers=STD, json={})
    assert r.status_code == 400


def test_audit_log_records_the_act_not_the_text(client):
    secret = "Source KESTREL met the accused at the dhaba"
    note = add(client, "C-005", RES, text=secret).json()
    client.patch(f"/api/cases/C-005/notes/{note['note_id']}", headers=RES,
                 json={"text": secret + " twice"})
    client.delete(f"/api/cases/C-005/notes/{note['note_id']}", headers=RES)

    # The ledger is readable at every tier, so the text must not be in it.
    log = client.get("/api/audit-log?limit=1000", headers=STD).json()
    assert "KESTREL" not in json.dumps(log, ensure_ascii=False)
    actions = [e["action"] for e in log["entries"] if e["target"] == "C-005"]
    assert {"NOTE_ADDED", "NOTE_EDITED", "NOTE_DELETED"} <= set(actions)
    added = next(e for e in log["entries"] if e["action"] == "NOTE_ADDED")
    assert added["detail"]["sha256"] == store.content_digest(secret)
    assert log["verification"]["intact"] is True
    assert store.verify_chain()["intact"] is True


def test_pipeline_rebuild_clears_notes(client):
    add(client, "C-001", STD)
    assert len(notes(client, "C-001", STD)) == 1
    rebuild()
    assert notes(client, "C-001", STD) == []
