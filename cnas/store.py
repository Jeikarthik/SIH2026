"""SQLite-backed side stores: hash-chained audit log, token vault, model
registry, and the officer-written parts of a case file.

  audit_log       FR-GOV-3, NFR-8  - tamper-evident, hash-chained
  token_vault     FR-GOV-2         - direct identifiers stored as tokens
  model_versions  FR-MLO-1/2       - replaces MLflow per Architecture v8 s6
  case_notes      officer notes on a case, tier-filtered on read
  case_milestones investigative steps and status changes on a case
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from . import config

_lock = threading.Lock()
GENESIS_HASH = "0" * 64


def _connect() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def now() -> str:
    """System time, as every store here records it: UTC, to the millisecond."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


_now = now


def init(reset: bool = False) -> None:
    with _lock, _connect() as conn:
        if reset:
            conn.executescript(
                "DROP TABLE IF EXISTS audit_log;"
                "DROP TABLE IF EXISTS token_vault;"
                "DROP TABLE IF EXISTS model_versions;"
                # Notes and milestones are keyed on case ids, and intake reuses
                # ids after a rebuild: kept across a reset, a note on C-008
                # would attach itself to whatever C-008 is next.
                "DROP TABLE IF EXISTS case_notes;"
                "DROP TABLE IF EXISTS case_milestones;"
            )
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                seq        INTEGER PRIMARY KEY AUTOINCREMENT,
                ts         TEXT NOT NULL,
                actor      TEXT NOT NULL,
                role       TEXT NOT NULL,
                action     TEXT NOT NULL,
                target     TEXT NOT NULL,
                detail     TEXT NOT NULL,
                prev_hash  TEXT NOT NULL,
                hash       TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS token_vault (
                token      TEXT PRIMARY KEY,
                kind       TEXT NOT NULL,
                plaintext  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS model_versions (
                mechanism  TEXT PRIMARY KEY,
                version    TEXT NOT NULL,
                params     TEXT NOT NULL,
                recorded   TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS case_notes (
                note_id    TEXT PRIMARY KEY,
                case_id    TEXT NOT NULL,
                text       TEXT NOT NULL,
                color      TEXT NOT NULL,
                tier       TEXT NOT NULL,
                author     TEXT NOT NULL,
                role       TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                deleted_at TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_case_notes_case ON case_notes (case_id);
            CREATE TABLE IF NOT EXISTS case_milestones (
                milestone_id TEXT PRIMARY KEY,
                case_id      TEXT NOT NULL,
                kind         TEXT NOT NULL,
                title        TEXT NOT NULL,
                detail       TEXT NOT NULL,
                occurred_at  TEXT NOT NULL,
                tier         TEXT NOT NULL,
                author       TEXT NOT NULL,
                role         TEXT NOT NULL,
                recorded_at  TEXT NOT NULL,
                source       TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_case_milestones_case
                ON case_milestones (case_id);
            """
        )


# --------------------------------------------------------------------------
# Audit log (append-only, hash-chained)
# --------------------------------------------------------------------------

def _row_hash(seq: int, ts: str, actor: str, role: str, action: str,
              target: str, detail: str, prev_hash: str) -> str:
    payload = "|".join([str(seq), ts, actor, role, action, target, detail, prev_hash])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def audit(actor: str, role: str, action: str, target: str,
          detail: dict[str, Any] | None = None) -> dict[str, Any]:
    """Append one tamper-evident entry. Each row commits to the one before it."""
    detail_json = json.dumps(detail or {}, sort_keys=True, ensure_ascii=False)
    ts = _now()
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT seq, hash FROM audit_log ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        prev_hash = row["hash"] if row else GENESIS_HASH
        seq = (row["seq"] + 1) if row else 1
        h = _row_hash(seq, ts, actor, role, action, target, detail_json, prev_hash)
        conn.execute(
            "INSERT INTO audit_log (seq, ts, actor, role, action, target, detail,"
            " prev_hash, hash) VALUES (?,?,?,?,?,?,?,?,?)",
            (seq, ts, actor, role, action, target, detail_json, prev_hash, h),
        )
    return {"seq": seq, "ts": ts, "hash": h}


def read_audit(limit: int = 250) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY seq DESC LIMIT ?", (limit,)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["detail"] = json.loads(d["detail"])
        out.append(d)
    return out


def verify_chain() -> dict[str, Any]:
    """Recompute the whole chain. Returns the first break, or intact=True.

    This is what makes the log tamper-evident rather than merely append-only:
    editing any historical row invalidates every hash after it.
    """
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM audit_log ORDER BY seq ASC").fetchall()
    prev_hash = GENESIS_HASH
    for r in rows:
        expected = _row_hash(r["seq"], r["ts"], r["actor"], r["role"],
                             r["action"], r["target"], r["detail"], prev_hash)
        if r["prev_hash"] != prev_hash:
            return {"intact": False, "entries": len(rows), "broken_at": r["seq"],
                    "reason": "prev_hash does not match preceding entry"}
        if expected != r["hash"]:
            return {"intact": False, "entries": len(rows), "broken_at": r["seq"],
                    "reason": "row hash does not match its contents"}
        prev_hash = r["hash"]
    return {"intact": True, "entries": len(rows), "head": prev_hash}


# --------------------------------------------------------------------------
# Token vault (FR-GOV-2)
# --------------------------------------------------------------------------

def tokenize(plaintext: str, kind: str) -> str:
    token = f"tok_{kind}_{hashlib.sha256(plaintext.encode()).hexdigest()[:12]}"
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO token_vault (token, kind, plaintext) VALUES (?,?,?)",
            (token, kind, plaintext),
        )
    return token


def detokenize(token: str, actor: str, role: str, reason: str) -> str | None:
    """Detokenisation is separately authorised and separately logged."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT plaintext FROM token_vault WHERE token = ?", (token,)
        ).fetchone()
    audit(actor, role, "DETOKENIZE", token,
          {"reason": reason, "granted": row is not None})
    return row["plaintext"] if row else None


# --------------------------------------------------------------------------
# Model registry (FR-MLO-1/2)
# --------------------------------------------------------------------------

def record_model(mechanism: str, version: str, params: dict[str, Any]) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO model_versions (mechanism, version, params,"
            " recorded) VALUES (?,?,?,?)",
            (mechanism, version, json.dumps(params, sort_keys=True), _now()),
        )


def read_models() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM model_versions ORDER BY mechanism"
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["params"] = json.loads(d["params"])
        out.append(d)
    return out


def audit_for_targets(targets: Iterable[str]) -> list[dict[str, Any]]:
    """Ledger rows about the given targets, oldest first, projected safely.

    Only the action, actor, time and target are returned, plus the stated
    reason on a finding decision - which is shown on the finding itself to
    anyone who can see it. Other detail fields are not passed through, so a
    caller can only learn from this what the targets it named already allow.
    """
    ids = sorted(set(targets))
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT seq, ts, actor, role, action, target, detail FROM audit_log"
            f" WHERE target IN ({marks}) ORDER BY seq ASC", ids,
        ).fetchall()
    out = []
    for r in rows:
        d = {"seq": r["seq"], "ts": r["ts"], "actor": r["actor"],
             "role": r["role"], "action": r["action"], "target": r["target"]}
        if r["action"] in ("FINDING_CONFIRMED", "FINDING_REJECTED"):
            d["reason"] = json.loads(r["detail"]).get("reason", "")
        out.append(d)
    return out


# --------------------------------------------------------------------------
# Case notes and milestones
#
# Both carry a tier and are filtered by it here, on read, exactly as graph
# records are: a note an analyst writes about a Restricted record is itself
# Restricted material. Their text never goes into the audit ledger, which is
# not tier-filtered - the ledger records that a note was written, not what.
# --------------------------------------------------------------------------

def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def content_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def add_note(case_id: str, text: str, color: str, tier: str,
             author: str, role: str) -> dict[str, Any]:
    note = {"note_id": _new_id("N"), "case_id": case_id, "text": text,
            "color": color, "tier": tier, "author": author, "role": role,
            "created_at": _now(), "updated_at": None, "deleted_at": None}
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO case_notes (note_id, case_id, text, color, tier, author,"
            " role, created_at, updated_at, deleted_at)"
            " VALUES (:note_id,:case_id,:text,:color,:tier,:author,:role,"
            ":created_at,:updated_at,:deleted_at)", note)
    return note


def get_note(case_id: str, note_id: str) -> dict[str, Any] | None:
    """A live note, regardless of tier. Callers apply the tier check."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM case_notes WHERE note_id = ? AND case_id = ?"
            " AND deleted_at IS NULL", (note_id, case_id)).fetchone()
    return dict(row) if row else None


def list_notes(case_id: str, tiers: Iterable[str]) -> list[dict[str, Any]]:
    allowed = list(tiers)
    marks = ",".join("?" * len(allowed))
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM case_notes WHERE case_id = ? AND deleted_at IS NULL"
            f" AND tier IN ({marks}) ORDER BY created_at DESC",
            (case_id, *allowed)).fetchall()
    return [dict(r) for r in rows]


def update_note(note_id: str, changes: dict[str, Any]) -> None:
    fields = {k: v for k, v in changes.items() if k in ("text", "color", "tier")}
    fields["updated_at"] = _now()
    sets = ", ".join(f"{k} = :{k}" for k in fields)
    with _lock, _connect() as conn:
        conn.execute(f"UPDATE case_notes SET {sets} WHERE note_id = :note_id",
                     {**fields, "note_id": note_id})


def soft_delete_note(note_id: str) -> None:
    """The row is kept: the ledger entry for it still has something to point at."""
    with _lock, _connect() as conn:
        conn.execute("UPDATE case_notes SET deleted_at = ? WHERE note_id = ?",
                     (_now(), note_id))


def add_milestone(case_id: str, kind: str, title: str, detail: str,
                  occurred_at: str, tier: str, author: str, role: str,
                  source: str = "officer") -> dict[str, Any]:
    m = {"milestone_id": _new_id("MS"), "case_id": case_id, "kind": kind,
         "title": title, "detail": detail, "occurred_at": occurred_at,
         "tier": tier, "author": author, "role": role,
         "recorded_at": _now(), "source": source}
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO case_milestones (milestone_id, case_id, kind, title,"
            " detail, occurred_at, tier, author, role, recorded_at, source)"
            " VALUES (:milestone_id,:case_id,:kind,:title,:detail,:occurred_at,"
            ":tier,:author,:role,:recorded_at,:source)", m)
    return m


def list_milestones(case_id: str, tiers: Iterable[str]) -> list[dict[str, Any]]:
    allowed = list(tiers)
    marks = ",".join("?" * len(allowed))
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM case_milestones WHERE case_id = ?"
            f" AND tier IN ({marks}) ORDER BY occurred_at ASC",
            (case_id, *allowed)).fetchall()
    return [dict(r) for r in rows]
