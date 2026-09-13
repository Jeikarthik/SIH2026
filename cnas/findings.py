"""The Explainability Contract (FR-EXP-1), enforced structurally.

A Finding cannot be constructed without every field of the contract populated.
That is deliberate: PRD principle P2 says a finding with no retrievable source
evidence is a bug, not a low-confidence result, and safety metric S2 sets
unexplained findings to a ceiling of zero. Making the dataclass refuse to build
is cheaper and more reliable than remembering to fill the fields in six
different mechanisms.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any

from . import config


@dataclass(frozen=True)
class Evidence:
    """One retrievable record underpinning a finding."""
    node_id: str
    label: str
    role: str               # what this record contributes, in plain language
    source_record_id: str   # FR-ING-8: immutable pointer back to the source


@dataclass
class Finding:
    finding_id: str
    finding_type: str
    mechanism_family: str          # key into config.MECHANISM_FAMILIES
    mechanism: str                 # key into config.MODEL_VERSIONS
    mechanism_params: dict[str, Any]
    statement: str                 # plain language, readable in under 30s (U1)
    evidence: list[Evidence]
    confidence: float
    confidence_meaning: str        # FR-EXP-1: what this number means, not just its value
    limitations: str               # FR-EXP-6: failure modes, stated on every finding
    tier: str = "standard"
    pack: int | None = None
    subject_ids: list[str] = field(default_factory=list)
    contributing_merges: list[str] = field(default_factory=list)  # FR-ER-7
    status: str = "pending"        # pending | confirmed | rejected
    decision_reason: str | None = None
    decided_by: str | None = None
    decided_at: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)  # mechanism-specific panel data

    def __post_init__(self) -> None:
        missing = [
            name for name in (
                "finding_id", "finding_type", "mechanism_family", "mechanism",
                "statement", "confidence_meaning", "limitations",
            ) if not getattr(self, name)
        ]
        if missing:
            raise ValueError(
                f"Explainability Contract violation in {self.finding_id!r}: "
                f"missing {', '.join(missing)}"
            )
        if not self.evidence:
            raise ValueError(
                f"Explainability Contract violation in {self.finding_id!r}: "
                "a finding must carry at least one retrievable evidence record "
                "(PRD P2 / safety metric S2)"
            )
        if self.mechanism_family not in config.MECHANISM_FAMILIES:
            raise ValueError(f"unknown mechanism family {self.mechanism_family!r}")
        if self.tier not in config.TIERS:
            raise ValueError(f"unknown tier {self.tier!r}")

    @property
    def model_version(self) -> str:
        return config.MODEL_VERSIONS.get(self.mechanism, "unversioned")

    @property
    def family_label(self) -> str:
        return config.MECHANISM_FAMILIES[self.mechanism_family]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["model_version"] = self.model_version
        d["family_label"] = self.family_label
        d["pack_label"] = config.PACK_LABELS.get(self.pack) if self.pack else None
        return d


def save(findings: list[Finding]) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = [f.to_dict() for f in findings]
    config.FINDINGS_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load() -> list[dict[str, Any]]:
    if not config.FINDINGS_PATH.exists():
        return []
    return json.loads(config.FINDINGS_PATH.read_text(encoding="utf-8"))
