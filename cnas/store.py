"""SQLite-backed side stores: hash-chained audit log, token vault, model registry.

Three things live here rather than in the graph, because all three are
append-only ledgers rather than network structure:

  audit_log       FR-GOV-3, NFR-8  - tamper-evident, hash-chained
  token_vault     FR-GOV-2         - direct identifiers stored as tokens
  model_versions  FR-MLO-1/2       - replaces MLflow per Architecture v8 s6
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

from . import config

_lock = threading.Lock()
GENESIS_HASH = "0" * 64


def _connect() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def init(reset: bool = False) -> None:
    with _lock, _connect() as conn:
        if reset:
            conn.executescript(
                "DROP TABLE IF EXISTS audit_log;"
                "DROP TABLE IF EXISTS token_vault;"
                "DROP TABLE IF EXISTS model_versions;"
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
