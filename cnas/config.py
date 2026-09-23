"""Central configuration: thresholds, tiers, model versions, presentation metadata.

Every tunable number a judge might ask about lives here, once, so the value shown
in a finding's `mechanism_params` is provably the value the mechanism used.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
GRAPH_PATH = DATA_DIR / "graph.json"
FINDINGS_PATH = DATA_DIR / "findings.json"
DB_PATH = DATA_DIR / "cnas.sqlite"
WEB_DIR = ROOT / "web"
SAMPLES_DIR = ROOT / "samples"

# --------------------------------------------------------------------------
# Access tiers (FR-GOV-1). Ordered least to most sensitive.
# Enforcement happens in the graph query layer, never in the UI.
# --------------------------------------------------------------------------
TIERS = ["standard", "elevated", "restricted"]

ROLES = {
    "standard_officer": {
        "display": "Standard Officer",
        "unit": "District Crime Branch, Jaipur",
        "tiers": ["standard"],
    },
    "elevated_analyst": {
        "display": "Elevated Analyst",
        "unit": "State Crime Records Bureau",
        "tiers": ["standard", "elevated"],
    },
    "restricted_analyst": {
        "display": "Restricted Analyst",
        "unit": "Special Branch / ATS",
        "tiers": ["standard", "elevated", "restricted"],
    },
}
DEFAULT_ROLE = "standard_officer"

# --------------------------------------------------------------------------
# Entity resolution (FR-ER-2). Three-band decision.
# --------------------------------------------------------------------------
TAU_HIGH = 0.97   # at or above -> auto-merge
TAU_LOW = 0.80    # at or above -> human review queue; below -> auto-reject

ER_WEIGHTS = {
    "name_fuzzy": 0.40,
    "name_phonetic": 0.20,
    "dob": 0.15,
    "address": 0.10,
    "co_occurrence": 0.15,
}

# Identifiers that resolve deterministically, with no probabilistic scoring
# at all (FR-ER-5).
DETERMINISTIC_IDENTIFIERS = ["imei", "account_no", "vehicle_reg", "upi_handle"]

# --------------------------------------------------------------------------
# Mechanism parameters
# --------------------------------------------------------------------------

# Rule-based: structuring against the PMLA Cash Transaction Report threshold.
# The Indian CTR reporting trigger is Rs 10,00,000. Structuring means sitting
# deliberately below it, so the detection band is the top decile beneath it.
CTR_THRESHOLD = 1_000_000
STRUCTURING_BAND_LOW = 900_000
STRUCTURING_BAND_HIGH = 999_999
STRUCTURING_MIN_COUNT = 3
STRUCTURING_WINDOW_HOURS = 48

# Graph-structural: super-linear algorithms run on bounded subgraphs only
# (FR-GRA-7).
MAX_SUBGRAPH_NODES = 300
COMMUNITY_RESOLUTION = 1.0

# Statistical: Benford's Law is only valid on a population, not one account.
# Below this n, or below this spread of magnitudes, the mechanism refuses to run.
BENFORD_MIN_N = 150
BENFORD_MIN_ORDERS_OF_MAGNITUDE = 2
BENFORD_MAD_SUSPECT = 0.012   # Nigrini: > 0.012 = nonconformity
BENFORD_MAD_MARGINAL = 0.006

# Time-series: CUSUM change-point detection on daily credit volume.
CUSUM_K_SIGMA = 0.5      # slack, in baseline standard deviations
CUSUM_H_SIGMA = 5.0      # decision interval, in baseline standard deviations
CUSUM_BASELINE_DAYS = 21

# Vector-similarity: modus operandi matching.
# The narrative is deliberately not the only signal. Two FIRs describing the
# same MO in different words must still match, which bag-of-words alone cannot
# do, so a structured MO feature vector carries most of the weight.
MO_FEATURE_WEIGHT = 0.70
MO_TEXT_WEIGHT = 0.30
# Two cases agreeing on every structured attribute score 0.70 from features
# alone, so the threshold has to sit below that for the mechanism to fire at all
# on lexically dissimilar narratives - which is precisely the case it exists for.
MO_SIMILARITY_THRESHOLD = 0.65

# Emergency lookup (FR-UX-7, NFR-2): p95 < 1s. Everything is pre-indexed.
EMERGENCY_MAX_RESULTS = 25

# Edges that record an event, as against a standing relationship. Every edge
# carries an event time, but an account's opening date and an address
# association are dated facts rather than things that happened on a case
# timeline: plotting them puts a 2023 account opening before a 2025 theft.
EVENT_EDGE_TYPES = ["TRANSACTED_WITH", "CALLED", "FENCED_TO",
                    "FINANCED_BY", "APPEARS_IN"]

# --------------------------------------------------------------------------
# Model / mechanism versions (FR-MLO-1, FR-MLO-2).
# Replaces MLflow per Architecture v8 section 6.
# --------------------------------------------------------------------------
MODEL_VERSIONS = {
    "er.deterministic": "1.0.0",
    "er.probabilistic": "1.2.0",
    "rule.structuring": "1.1.0",
    "structural.community_bridge": "1.0.0",
    "statistical.benford": "2.0.0",
    "timeseries.cusum": "1.0.0",
    "vector.mo_similarity": "1.3.0",
    "emergency.direct_lookup": "1.0.0",
}

# --------------------------------------------------------------------------
# Presentation metadata.
# --------------------------------------------------------------------------
# Colours are chosen for a light canvas: each one holds a 4.5:1 contrast ratio
# against white, so a node label sitting beside it stays legible on a projector.
# `icon` names a pictogram drawn by the console; `glyph` is the text fallback,
# used as the accessible label and anywhere an image cannot be drawn.
NODE_STYLE = {
    "Person":               {"color": "#9a4b00", "glyph": "PER", "icon": "person"},
    "Phone":                {"color": "#1a5fa8", "glyph": "TEL", "icon": "phone"},
    "BankAccount":          {"color": "#15683c", "glyph": "ACC", "icon": "bank"},
    "Vehicle":              {"color": "#6b3fa0", "glyph": "VEH", "icon": "vehicle"},
    "Address":              {"color": "#5a6472", "glyph": "ADR", "icon": "pin"},
    "Case":                 {"color": "#a32020", "glyph": "CAS", "icon": "case"},
    "Document":             {"color": "#6b7480", "glyph": "DOC", "icon": "document"},
    "StolenProperty":       {"color": "#8a5a00", "glyph": "PRP", "icon": "valuables"},
    "SmugglingConsignment": {"color": "#a0522d", "glyph": "CNS", "icon": "crate"},
    "CyberComplaint":       {"color": "#0f6b72", "glyph": "CYB", "icon": "screen"},
    "KidnappingCase":       {"color": "#9c2a66", "glyph": "KID", "icon": "person_alert"},
}

PACK_LABELS = {
    2: "Money Laundering",
    3: "Cybercrime & Fraud",
    6: "Smuggling & Customs",
    7: "Theft, Robbery & Dacoity",
    10: "Kidnapping & Extortion",
}

MECHANISM_FAMILIES = {
    # Entity resolution is not one of the five detection families; it is the
    # subsystem that feeds all of them. It carries the same Explainability
    # Contract because a merge is the most consequential thing the system does.
    "er": "Entity resolution",
    "rule": "Rule-based",
    "structural": "Graph-structural",
    "statistical": "Statistical",
    "timeseries": "Time-series",
    "vector": "Vector-similarity",
    "emergency": "Emergency lookup",
}
