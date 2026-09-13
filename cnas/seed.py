"""Hand-crafted synthetic dataset (PRD P7 - nothing here is real).

Every record exists to make one of the six demonstration criteria in PRD s7.3
reproducible on stage. Nothing is randomly generated except the transaction
populations the statistical mechanisms need, and those use a fixed seed.

Planted scenarios
-----------------
1. ER collapse      C-001 / C-002 / C-003 share one handset IMEI across three
                    districts, with the same person spelled three ways
                    (Latin, misspelled Latin, Devanagari).
2. Cross-domain     C-001 theft -> fenced goods -> mule account -> smuggling
                    financier -> C-005.
3. MO similarity    C-001 and C-004 describe the same modus operandi in
                    deliberately different vocabulary, with no shared identifier.
4. False positive   Two unrelated "Suresh Kumar" records, one missing a date of
                    birth, scoring into the review band rather than auto-merging.
5. Restricted tier  A bribed customs officer, invisible below Restricted.
6. Emergency        A kidnapping ransom handset that already appears in an
                    older cyber-fraud case.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from typing import Any

from . import config

RNG = random.Random(20260912)
INGEST_BASE = datetime(2026, 9, 10, 6, 0, 0)

_nodes: list[dict[str, Any]] = []
_edges: list[dict[str, Any]] = []
_edge_seq = 0


def _n(node_id: str, label: str, tier: str = "standard",
       source: str | None = None, **props: Any) -> str:
    _nodes.append({
        "id": node_id,
        "label": label,
        "tier": tier,
        "source_record_id": source or f"SRC/{node_id}",
        "props": props,
    })
    return node_id


def _e(src: str, dst: str, etype: str, event_time: str,
       tier: str = "standard", **props: Any) -> None:
    """Bi-temporal edge (FR-GRA-3): when it happened, and when we learned it."""
    global _edge_seq
    _edge_seq += 1
    ingest_lag = timedelta(hours=RNG.randint(6, 400))
    _edges.append({
        "id": f"E{_edge_seq:04d}",
        "src": src,
        "dst": dst,
        "type": etype,
        "tier": tier,
        "event_time": event_time,
        "ingested_time": (INGEST_BASE - ingest_lag).isoformat(timespec="seconds"),
        "props": props,
    })


# ==========================================================================
# Modus operandi narratives
#
# C-001 and C-004 describe the same MO with almost no shared vocabulary.
# That is the point: bag-of-words alone cannot connect "gas cutter" to
# "oxy-acetylene torch", which is why the mechanism weights a structured MO
# feature vector at 0.70 and the narrative text at only 0.30.
# ==========================================================================

NARRATIVE_C001 = (
    "Complainant states that between 0215 and 0350 hours unknown persons gained "
    "entry to a ground-floor jewellery showroom on the main bazaar road by "
    "cutting the shutter lock with a gas cutter. The CCTV digital video recorder "
    "was disconnected before entry. Gold ornaments weighing approximately 2.4 kg "
    "were removed from the display counters. The strong room was not touched. "
    "Three persons are seen on a neighbouring shop camera. A motorcycle without "
    "a number plate was used to leave the spot."
)

NARRATIVE_C004 = (
    "In the early hours of the morning suspects breached a street-level gold "
    "retail outlet situated on a market thoroughfare. The rolling gate padlock "
    "had been severed using an oxy-acetylene torch. Surveillance equipment was "
    "rendered inoperative prior to the intrusion. Roughly 2.1 kilograms of gold "
    "articles were lifted from the showcases. The vault itself remained secure "
    "and unopened. A witness describes a group of three men departing on a "
    "two-wheeler carrying no registration mark."
)

NARRATIVE_C007 = (
    "Complainant reports that his motorcycle parked outside his residence was "
    "stolen during the night. The steering lock was broken. No other property "
    "was disturbed and there is no camera coverage at the location."
)

# Pre-extracted MO features. Per the build plan, entity and attribute
# extraction is done at data-generation time rather than by running NER on
# stage - the pre-baked values are indistinguishable in the demo.
MO_FEATURES = {
    "C-001": {
        "target_type": "jewellery_retail", "premises_level": "ground_floor",
        "entry_method": "shutter_lock_defeated", "tool_class": "thermal_cutting",
        "time_band": "0200_0400", "cctv_defeated": "yes",
        "vault_breached": "no", "goods_class": "gold_ornament",
        "crew_size": "3", "escape_vehicle": "two_wheeler_no_plate",
    },
    "C-004": {
        "target_type": "jewellery_retail", "premises_level": "ground_floor",
        "entry_method": "shutter_lock_defeated", "tool_class": "thermal_cutting",
        "time_band": "0200_0400", "cctv_defeated": "yes",
        "vault_breached": "no", "goods_class": "gold_ornament",
        "crew_size": "3", "escape_vehicle": "two_wheeler_no_plate",
    },
    "C-007": {
        "target_type": "residential_street", "premises_level": "open_air",
        "entry_method": "steering_lock_broken", "tool_class": "mechanical_force",
        "time_band": "0000_0500", "cctv_defeated": "no",
        "vault_breached": "no", "goods_class": "vehicle",
        "crew_size": "1", "escape_vehicle": "stolen_vehicle_itself",
    },
}


def _build_entities() -> None:
    # ---------------------------------------------------------------- cases
    _n("C-001", "Case", district="Jaipur", pack=7, title="Jewellery showroom burglary",
       crime="Theft & Robbery", opened="2025-03-12", officer="SI A. Meena",
       status="under_investigation", source="CCTNS/RJ/JPR/2025/00417")
    _n("C-002", "Case", district="Indore", pack=3, title="UPI fraud - 41 victims",
       crime="Cybercrime & Fraud", opened="2025-04-02", officer="SI P. Sharma",
       status="under_investigation", source="NCRP/MP/IND/2025/10233")
    _n("C-003", "Case", district="Surat", pack=2, title="Suspicious layering - trade accounts",
       crime="Money Laundering", opened="2025-05-18", officer="Insp. K. Desai",
       status="under_investigation", source="FIU/GJ/SRT/2025/00088")
    _n("C-004", "Case", district="Nagpur", pack=7, title="Gold retail outlet burglary",
       crime="Theft & Robbery", opened="2025-06-24", officer="SI R. Kale",
       status="under_investigation", source="CCTNS/MH/NGP/2025/03119")
    _n("C-005", "Case", district="Kandla", pack=6, title="Undeclared consignment - Kandla port",
       crime="Smuggling & Customs", opened="2025-07-09", officer="DRI Off. S. Nair",
       status="under_investigation", source="ICEGATE/DRI/2025/00291")
    _n("C-006", "Case", district="Bhopal", pack=10, title="Abduction for ransom - minor",
       crime="Kidnapping & Extortion", opened="2026-09-08", officer="DSP M. Qureshi",
       status="active_emergency", source="CCTNS/MP/BPL/2026/07740")
    _n("C-007", "Case", district="Pune", pack=7, title="Two-wheeler theft",
       crime="Theft & Robbery", opened="2025-08-30", officer="SI V. Jadhav",
       status="under_investigation", source="CCTNS/MH/PUN/2025/09982")

    # ------------------------------------------------------------ documents
    for cid, narrative in (("C-001", NARRATIVE_C001), ("C-004", NARRATIVE_C004),
                           ("C-007", NARRATIVE_C007)):
        _n(f"D-{cid[2:]}", "Document", doc_type="FIR", case=cid, language="en",
           narrative=narrative, source=f"FIR/{cid}")
        _e(f"D-{cid[2:]}", cid, "APPEARS_IN", "2025-03-12T09:00:00")

    _n("D-002", "Document", doc_type="Complaint bundle", case="C-002", language="hi",
       narrative="41 individual complaints of UPI debit following an OTP-sharing "
                 "call. Beneficiary handles resolve to four accounts.",
       source="FIR/C-002")
    _e("D-002", "C-002", "APPEARS_IN", "2025-04-02T11:20:00")

    # --------------------------------------------- the entity-resolution trio
    # Same individual, three districts, three spellings, one handset.
    _n("P-001", "Person", name="Ramesh Yadav", name_script="latin",
       dob="1986-07-14", father_name="Bhanwar Lal Yadav",
       address_ref="ADR-001", role_in_case="accused",
       source="CCTNS/RJ/JPR/2025/00417/ACC1")
    _n("P-002", "Person", name="Ramesh Yadev", name_script="latin",
       dob="1986-07-14", father_name="B. L. Yadav",
       address_ref="ADR-002", role_in_case="suspect",
       source="NCRP/MP/IND/2025/10233/SUS3")
    _n("P-003", "Person", name="रमेश यादव",
       name_script="devanagari", dob="1986-07-14", father_name="भँवर लाल",
       address_ref="ADR-003", role_in_case="account_holder",
       source="FIU/GJ/SRT/2025/00088/AH1")

    _n("ADR-001", "Address", line="14 Kishanpole Bazar", city="Jaipur", state="Rajasthan")
    _n("ADR-002", "Address", line="88 Sanyogitaganj", city="Indore", state="Madhya Pradesh")
    _n("ADR-003", "Address", line="12 Ring Road", city="Surat", state="Gujarat")

    # Three numbers, one handset. This is the deterministic bridge (FR-ER-5).
    SHARED_IMEI = "358240051111110"
    _n("PH-001", "Phone", number="+91 98290 41188", imei=SHARED_IMEI,
       operator="Airtel", circle="Rajasthan", source="CDR/RJ/2025/Q1/0417")
    _n("PH-002", "Phone", number="+91 73140 90221", imei=SHARED_IMEI,
       operator="Jio", circle="Madhya Pradesh", source="CDR/MP/2025/Q2/1023")
    _n("PH-003", "Phone", number="+91 90990 77341", imei=SHARED_IMEI,
       operator="VI", circle="Gujarat", source="CDR/GJ/2025/Q2/0088")

    for p, ph, adr, case, when in (
        ("P-001", "PH-001", "ADR-001", "C-001", "2025-03-12T02:40:00"),
        ("P-002", "PH-002", "ADR-002", "C-002", "2025-04-02T10:05:00"),
        ("P-003", "PH-003", "ADR-003", "C-003", "2025-05-18T14:30:00"),
    ):
        _e(p, ph, "OWNS", when)
        _e(p, adr, "LOCATED_AT", when)
        _e(p, case, "APPEARS_IN", when)

    # ------------------------------------------------- the cross-domain chain
    _n("SP-001", "StolenProperty", description="Gold ornaments, assorted",
       weight_kg=2.4, est_value=14_800_000, recovered="no",
       source="CCTNS/RJ/JPR/2025/00417/PROP1")
    _e("SP-001", "C-001", "APPEARS_IN", "2025-03-12T09:00:00")
    _e("P-001", "SP-001", "OWNS", "2025-03-12T03:50:00", relation="removed_from_scene")

    _n("P-010", "Person", name="Imran Shaikh", name_script="latin", dob="1979-01-23",
       address_ref="ADR-004", role_in_case="receiver_of_stolen_property",
       occupation="Bullion dealer", source="CCTNS/RJ/JPR/2025/00417/ACC4")
    _n("ADR-004", "Address", line="Johari Bazar, Shop 221", city="Jaipur", state="Rajasthan")
    _e("P-010", "ADR-004", "LOCATED_AT", "2025-03-15T00:00:00")
    _e("SP-001", "P-010", "FENCED_TO", "2025-03-14T19:20:00",
       basis="melting receipt seized during search")
    _e("P-010", "C-001", "APPEARS_IN", "2025-03-20T00:00:00")

    _n("ACC-7781", "BankAccount", account_no="0077815520143",
       bank="Union Bank", branch="Jaipur MI Road", holder="Imran Shaikh",
       flag="laundering_suspect", opened="2024-11-02",
       source="FIU/STR/2025/44120")
    _e("P-010", "ACC-7781", "OWNS", "2024-11-02T00:00:00")
    _e("ACC-7781", "C-003", "APPEARS_IN", "2025-05-18T14:30:00")

    _n("ACC-9902", "BankAccount", account_no="9902144007766",
       bank="Kotak Mahindra", branch="Gandhidham", holder="Noor Trading Co",
       flag="under_scrutiny", opened="2023-06-14",
       source="FIU/STR/2025/44980")
    _e("ACC-7781", "ACC-9902", "TRANSACTED_WITH", "2025-06-02T11:41:00",
       amount=4_260_000, channel="RTGS", legs=3)

    _n("P-020", "Person", name="Haji Noor Mohammed", name_script="latin",
       dob="1968-04-02", address_ref="ADR-005", role_in_case="financier",
       occupation="Import-export", source="ICEGATE/DRI/2025/00291/SUS1")
    _n("ADR-005", "Address", line="Plot 6, Sector 8", city="Gandhidham", state="Gujarat")
    _e("P-020", "ACC-9902", "OWNS", "2023-06-14T00:00:00")
    _e("P-020", "ADR-005", "LOCATED_AT", "2023-06-14T00:00:00")
    _e("P-020", "C-005", "APPEARS_IN", "2025-07-09T08:15:00")

    _n("CNS-001", "SmugglingConsignment", bill_of_entry="BE/2025/KDL/88214",
       declared="Ceramic tableware", actual="Undeclared gold dore bars, 18.2 kg",
       port="Kandla", duty_evaded=41_000_000,
       source="ICEGATE/DRI/2025/00291/CNS1")
    _e("CNS-001", "C-005", "APPEARS_IN", "2025-07-09T08:15:00")
    _e("CNS-001", "P-020", "FINANCED_BY", "2025-07-02T00:00:00",
       basis="letter of credit traced to ACC-9902")

    # ----------------------------------------------- restricted tier (crit. 5)
    # A bribed customs officer. Invisible to Standard and Elevated logins:
    # the filtering happens in the graph query layer, not in the UI.
    _n("P-030", "Person", tier="restricted", name="Devendra Rathore",
       name_script="latin", dob="1972-09-19", role_in_case="public_servant",
       occupation="Dy. Commissioner, Customs (Kandla)",
       handling_caveat="Source-protected. Not for export.",
       source="ACB/GJ/2026/RESTR/0031")
    _e("P-020", "P-030", "TRANSACTED_WITH", "2025-06-28T16:00:00",
       tier="restricted", amount=2_500_000, channel="hawala",
       basis="informant reporting, corroborated by call records")
    _e("P-030", "CNS-001", "APPEARS_IN", "2025-07-09T08:15:00", tier="restricted",
       basis="cleared the consignment out of turn")

    # ------------------------------------------------- MO twin case (crit. 3)
    _n("P-011", "Person", name="Sandeep Bhoyar", name_script="latin", dob="1990-11-05",
       address_ref="ADR-006", role_in_case="accused",
       source="CCTNS/MH/NGP/2025/03119/ACC1")
    _n("ADR-006", "Address", line="Itwari Main Road", city="Nagpur", state="Maharashtra")
    _n("SP-002", "StolenProperty", description="Gold articles, showcase stock",
       weight_kg=2.1, est_value=12_900_000, recovered="no",
       source="CCTNS/MH/NGP/2025/03119/PROP1")
    _e("P-011", "ADR-006", "LOCATED_AT", "2025-06-24T00:00:00")
    _e("P-011", "C-004", "APPEARS_IN", "2025-06-24T07:30:00")
    _e("SP-002", "C-004", "APPEARS_IN", "2025-06-24T07:30:00")
    _n("VEH-001", "Vehicle", registration="UNREGISTERED", vtype="Motorcycle",
       note="No number plate on CCTV", source="CCTNS/MH/NGP/2025/03119/VEH1")
    _e("VEH-001", "C-004", "APPEARS_IN", "2025-06-24T07:30:00")

    # --------------------------------------------- emergency lookup (crit. 6)
    _n("KID-001", "KidnappingCase", victim_age=11, ransom_demand=5_000_000,
       demand_channel="voice call", status="active",
       source="CCTNS/MP/BPL/2026/07740/KID1")
    _e("KID-001", "C-006", "APPEARS_IN", "2026-09-08T19:40:00")

    # The ransom handset already exists in the older cyber-fraud case.
    _n("PH-020", "Phone", number="+91 90391 44517", imei="359871044920018",
       operator="Jio", circle="Madhya Pradesh", source="CDR/MP/2025/Q2/1023")
    _e("PH-020", "C-002", "APPEARS_IN", "2025-04-02T10:05:00",
       role="beneficiary contact number")
    _e("PH-020", "KID-001", "CALLED", "2026-09-08T21:12:00",
       role="ransom demand call", duration_s=94)

    _n("P-021", "Person", name="Faizan Qureshi", name_script="latin", dob="1994-03-17",
       role_in_case="suspect", source="NCRP/MP/IND/2025/10233/SUS7")
    _e("P-021", "PH-020", "OWNS", "2025-01-11T00:00:00")
    _e("P-021", "C-002", "APPEARS_IN", "2025-04-02T10:05:00")

    _n("CYB-001", "CyberComplaint", victims=41, total_loss=3_180_000,
       vector="OTP social engineering", source="NCRP/MP/IND/2025/10233/CMP")
    _e("CYB-001", "C-002", "APPEARS_IN", "2025-04-02T10:05:00")

    # ------------------------------------------------ false positive (crit. 4)
    # Identical common name; one record has no date of birth, so the system
    # cannot rule the match out and must not auto-merge it (P3, FR-ER-6).
    _n("P-040", "Person", name="Suresh Kumar", name_script="latin",
       dob="1991-02-11", address_ref="ADR-007", role_in_case="complainant",
       source="CCTNS/MH/PUN/2025/09982/CMP1")
    _n("P-041", "Person", name="Suresh Kumar", name_script="latin",
       dob=None, address_ref="ADR-008", role_in_case="witness",
       source="ICEGATE/DRI/2025/00291/WIT2")
    _n("ADR-007", "Address", line="Shivaji Nagar", city="Pune", state="Maharashtra")
    _n("ADR-008", "Address", line="Shivaji Nagar", city="Gandhidham", state="Gujarat")
    _e("P-040", "ADR-007", "LOCATED_AT", "2025-08-30T00:00:00")
    _e("P-041", "ADR-008", "LOCATED_AT", "2025-07-09T00:00:00")
    _e("P-040", "C-007", "APPEARS_IN", "2025-08-30T09:15:00")
    _e("P-041", "C-005", "APPEARS_IN", "2025-07-09T08:15:00")
    _n("VEH-002", "Vehicle", registration="MH 12 QR 4471", vtype="Motorcycle",
       source="VAHAN/MH/4471")
    _e("VEH-002", "C-007", "APPEARS_IN", "2025-08-30T09:15:00")
    _e("P-040", "VEH-002", "OWNS", "2023-02-01T00:00:00")

    # ------------------------------------------- structuring mules (rule fam.)
    mule_names = [
        ("P-050", "Ajay Pawar", "ACC-5001", "3410077120014"),
        ("P-051", "Nitin Gaikwad", "ACC-5002", "3410077120022"),
        ("P-052", "Salim Ansari", "ACC-5003", "3410077120039"),
        ("P-053", "Deepak Rathi", "ACC-5004", "3410077120047"),
        ("P-054", "Mohit Verma", "ACC-5005", "3410077120055"),
    ]
    for pid, name, acc, accno in mule_names:
        _n(pid, "Person", name=name, name_script="latin", role_in_case="account_holder",
           occupation="Student", source=f"FIU/STR/2025/MULE/{pid}")
        _n(acc, "BankAccount", account_no=accno, bank="Union Bank",
           branch="Jaipur MI Road", holder=name, flag="mule_suspect",
           opened="2025-01-08", source=f"FIU/STR/2025/MULE/{acc}")
        _e(pid, acc, "OWNS", "2025-01-08T00:00:00")

    # The five structured deposits: all inside the top decile below the
    # Rs 10,00,000 CTR reporting trigger, all inside 40 hours.
    deposits = [
        ("ACC-5001", 920_000, "2025-05-14T10:22:00"),
        ("ACC-5002", 965_000, "2025-05-14T15:47:00"),
        ("ACC-5003", 945_000, "2025-05-15T09:05:00"),
        ("ACC-5004", 980_000, "2025-05-15T17:31:00"),
        ("ACC-5005", 915_000, "2025-05-16T01:58:00"),
    ]
    for acc, amt, when in deposits:
        _e(acc, "ACC-7781", "TRANSACTED_WITH", when,
           amount=amt, channel="IMPS", structured="yes")

    # ---------------------------------------------- unrelated control cluster
    # A second, clean district cluster. Benford must NOT flag this one.
    for i, (pid, name, acc) in enumerate([
        ("P-060", "Anil Kulkarni", "ACC-6001"),
        ("P-061", "Ravi Shetty", "ACC-6002"),
        ("P-062", "Girish Patil", "ACC-6003"),
    ]):
        _n(pid, "Person", name=name, name_script="latin", role_in_case="account_holder",
           occupation="Trader", source=f"CTRL/{pid}")
        _n(acc, "BankAccount", account_no=f"660011{i:05d}", bank="Bank of Baroda",
           branch="Pune Camp", holder=name, flag="none", opened="2022-03-01",
           source=f"CTRL/{acc}")
        _e(pid, acc, "OWNS", "2022-03-01T00:00:00")


# ==========================================================================
# Transaction populations
#
# Benford's Law needs a population, not one account. These two ledgers give
# the mechanism something statistically legitimate to run on, and give the
# demo a control group that correctly comes back clean.
# ==========================================================================

LAUNDERING_ACCOUNTS = ["ACC-7781", "ACC-9902", "ACC-5001", "ACC-5002",
                       "ACC-5003", "ACC-5004", "ACC-5005"]
CONTROL_ACCOUNTS = ["ACC-6001", "ACC-6002", "ACC-6003"]

# First-digit distribution for the laundering cluster. Deliberately distorted:
# threshold-hugging amounts pile up on 9 and starve 1, which is the opposite of
# what Benford predicts (1 = 30.1%, 9 = 4.6%).
SUSPECT_DIGIT_WEIGHTS = [0.11, 0.08, 0.06, 0.07, 0.13, 0.06, 0.08, 0.11, 0.30]
BENFORD_WEIGHTS = [0.301, 0.176, 0.125, 0.097, 0.079, 0.067, 0.058, 0.051, 0.046]


def _amount_with_first_digit(digit: int, magnitude: int) -> int:
    rest = RNG.random()
    return int((digit + rest) * (10 ** magnitude))


def _make_transactions() -> list[dict[str, Any]]:
    txns: list[dict[str, Any]] = []
    start = datetime(2025, 3, 20, 9, 0, 0)
    tid = 0

    def emit(accounts: list[str], weights: list[float], n: int,
             magnitudes: list[int], cluster: str) -> None:
        nonlocal tid
        for _ in range(n):
            tid += 1
            digit = RNG.choices(range(1, 10), weights=weights)[0]
            magnitude = RNG.choice(magnitudes)
            src, dst = RNG.sample(accounts, 2)
            when = start + timedelta(minutes=RNG.randint(0, 60 * 24 * 120))
            txns.append({
                "id": f"TXN-{tid:05d}",
                "src_account": src,
                "dst_account": dst,
                "amount": _amount_with_first_digit(digit, magnitude),
                "ts": when.isoformat(timespec="seconds"),
                "channel": RNG.choice(["IMPS", "NEFT", "UPI", "RTGS"]),
                "cluster": cluster,
            })

    # Spread across 10^3 to 10^5 so the population genuinely spans several
    # orders of magnitude - without that, Benford is not applicable at all.
    emit(LAUNDERING_ACCOUNTS, SUSPECT_DIGIT_WEIGHTS, 240, [3, 4, 5], "laundering")
    emit(CONTROL_ACCOUNTS, BENFORD_WEIGHTS, 210, [3, 4, 5], "control")

    # The five hand-placed structured deposits also belong in the ledger.
    for acc, amt, when in [
        ("ACC-5001", 920_000, "2025-05-14T10:22:00"),
        ("ACC-5002", 965_000, "2025-05-14T15:47:00"),
        ("ACC-5003", 945_000, "2025-05-15T09:05:00"),
        ("ACC-5004", 980_000, "2025-05-15T17:31:00"),
        ("ACC-5005", 915_000, "2025-05-16T01:58:00"),
    ]:
        tid += 1
        txns.append({
            "id": f"TXN-{tid:05d}", "src_account": acc, "dst_account": "ACC-7781",
            "amount": amt, "ts": when, "channel": "IMPS", "cluster": "laundering",
            "structured": True,
        })
    return txns


def _make_daily_volume() -> dict[str, list[dict[str, Any]]]:
    """Daily credit volume for the mule account, with a real step change.

    Baseline for 37 days, then a sustained shift upward - which is exactly the
    signal CUSUM exists to catch, and which a simple threshold would miss
    because no single day is extraordinary.
    """
    series = []
    day0 = datetime(2025, 4, 8)
    for d in range(60):
        if d < 38:
            credit = max(0, RNG.gauss(180_000, 52_000))
        else:
            credit = max(0, RNG.gauss(860_000, 130_000))
        series.append({
            "date": (day0 + timedelta(days=d)).date().isoformat(),
            "credit": int(credit),
        })
    return {"ACC-7781": series}


def build() -> dict[str, Any]:
    _nodes.clear()
    _edges.clear()
    global _edge_seq
    _edge_seq = 0
    _build_entities()
    return {
        "nodes": list(_nodes),
        "edges": list(_edges),
        "transactions": _make_transactions(),
        "daily_volume": _make_daily_volume(),
        "mo_profiles": {
            "C-001": {"features": MO_FEATURES["C-001"], "narrative": NARRATIVE_C001},
            "C-004": {"features": MO_FEATURES["C-004"], "narrative": NARRATIVE_C004},
            "C-007": {"features": MO_FEATURES["C-007"], "narrative": NARRATIVE_C007},
        },
        "generated_at": INGEST_BASE.isoformat(timespec="seconds"),
        "synthetic": True,
    }


def write() -> dict[str, Any]:
    data = build()
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    (config.DATA_DIR / "seed.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return data
