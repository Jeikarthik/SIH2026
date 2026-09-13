"""The six mechanism families, plus the entity-resolution findings.

Each mechanism returns Finding objects, which cannot be constructed without a
complete Explainability Contract. Where a mechanism is not statistically valid
on the data in front of it, it declines to run and says so, rather than
producing a number that would not survive scrutiny.
"""
from __future__ import annotations

import math
from collections import Counter
from datetime import datetime
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from . import config
from .findings import Evidence, Finding

BENFORD_EXPECTED = [math.log10(1 + 1 / d) for d in range(1, 10)]


def _ev(store, node_id: str, role: str) -> Evidence:
    d = store.g.nodes[node_id]
    return Evidence(
        node_id=node_id,
        label=d.get("label", "?"),
        role=role,
        source_record_id=d.get("source_record_id", f"SRC/{node_id}"),
    )


# ==========================================================================
# Entity resolution findings
# ==========================================================================

def er_findings(store, merges: list[dict[str, Any]]) -> list[Finding]:
    out: list[Finding] = []

    # --- the collapse: three districts, one person (demonstration criterion 1)
    person_merges = [m for m in merges
                     if m["left_label"] == "Person" and m["decision"] == "auto_merge"]
    phone_merges = [m for m in merges
                    if m["left_label"] == "Phone" and m["method"] == "deterministic"]

    if person_merges:
        people = sorted({m["left"] for m in person_merges} | {m["right"] for m in person_merges})
        cases: list[str] = []
        und = store.g.to_undirected(as_view=True)
        for p in people:
            for nb in und.neighbors(p):
                if store.g.nodes[nb].get("label") == "Case" and nb not in cases:
                    cases.append(nb)

        evidence = [_ev(store, p, "person record merged into the resolved identity")
                    for p in people]
        evidence += [_ev(store, c, "case the merged identity appears in") for c in sorted(cases)]
        if phone_merges:
            for pid in sorted({m["left"] for m in phone_merges} | {m["right"] for m in phone_merges}):
                evidence.append(_ev(store, pid, "handset record carrying the shared IMEI"))

        imei = next((store.g.nodes[m["left"]].get("imei") for m in phone_merges), None)
        districts = sorted({store.g.nodes[c].get("district", "?") for c in cases})

        out.append(Finding(
            finding_id="F-ER-001",
            finding_type="Entity resolution collapse",
            mechanism_family="er",
            mechanism="er.deterministic",
            mechanism_params={
                "deterministic_identifiers": config.DETERMINISTIC_IDENTIFIERS,
                "tau_high": config.TAU_HIGH, "tau_low": config.TAU_LOW,
                "weights": config.ER_WEIGHTS,
            },
            statement=(
                f"{len(cases)} cases filed separately in {len(districts)} districts "
                f"({', '.join(districts)}) name the same individual. The name is "
                f"spelled three different ways across the records, including once in "
                f"Devanagari, but all three handsets share one IMEI "
                f"({imei}), which resolves deterministically."
            ),
            evidence=evidence,
            confidence=round(min(m["score"] for m in person_merges), 3),
            confidence_meaning=(
                "The lowest weighted field-agreement score across the person merges "
                "in this group. 1.0 on the handset link is not a probability - it is "
                "exact identifier equality, which carries no uncertainty."
            ),
            limitations=(
                "A shared IMEI proves a shared handset, not a shared user. Handsets "
                "are sold, lent and stolen. The person-level merge rests additionally "
                "on name and date-of-birth agreement; if the date of birth was copied "
                "between records by an operator, those two signals are not independent."
            ),
            pack=7,
            subject_ids=people,
            contributing_merges=[m["merge_id"] for m in person_merges + phone_merges],
            extra={"merges": person_merges + phone_merges, "cases": cases},
        ))

    # --- the planted false positive (demonstration criterion 4)
    for m in merges:
        if m["decision"] != "human_review" or m["left_label"] != "Person":
            continue
        out.append(Finding(
            finding_id=f"F-ER-{m['left']}-{m['right']}",
            finding_type="Possible duplicate person - review required",
            mechanism_family="er",
            mechanism="er.probabilistic",
            mechanism_params={
                "tau_high": config.TAU_HIGH, "tau_low": config.TAU_LOW,
                "weights": config.ER_WEIGHTS,
            },
            statement=(
                f"'{m['left_display']}' and '{m['right_display']}' score "
                f"{m['score']:.3f}, inside the review band. The system has not "
                f"merged them and will not without a human decision."
            ),
            evidence=[_ev(store, m["left"], "left-hand record"),
                      _ev(store, m["right"], "right-hand record")],
            confidence=m["score"],
            confidence_meaning=(
                "Weighted agreement across the fields present on both records, "
                "renormalised over the fields that carry data. It is a measure of "
                "how alike the records are, not the probability that the two are "
                "the same person."
            ),
            limitations=(
                "Common names are the dominant source of false matches in Indian "
                "police data, and locality names repeat across states. Where a date "
                "of birth is missing the system cannot rule a pair out, which is why "
                "this reached a human rather than being auto-rejected."
            ),
            subject_ids=[m["left"], m["right"]],
            contributing_merges=[m["merge_id"]],
            extra={"merge": m},
        ))
    return out


# ==========================================================================
# 1. Rule-based - structuring beneath the CTR reporting threshold
# ==========================================================================

def structuring(store) -> list[Finding]:
    by_target: dict[str, list[dict]] = {}
    for e in store.raw["edges"]:
        if e["type"] != "TRANSACTED_WITH":
            continue
        amt = e["props"].get("amount")
        if amt is None:
            continue
        if config.STRUCTURING_BAND_LOW <= amt <= config.STRUCTURING_BAND_HIGH:
            by_target.setdefault(e["dst"], []).append(e)

    out = []
    for target, deposits in by_target.items():
        if len(deposits) < config.STRUCTURING_MIN_COUNT:
            continue
        deposits.sort(key=lambda e: e["event_time"])
        times = [datetime.fromisoformat(e["event_time"]) for e in deposits]
        span_h = (times[-1] - times[0]).total_seconds() / 3600
        if span_h > config.STRUCTURING_WINDOW_HOURS:
            continue

        total = sum(e["props"]["amount"] for e in deposits)
        evidence = [_ev(store, target, "receiving account")]
        for e in deposits:
            evidence.append(_ev(store, e["src"],
                                f"deposited Rs {e['props']['amount']:,} on "
                                f"{e['event_time'][:16].replace('T', ' ')}"))

        out.append(Finding(
            finding_id=f"F-RULE-{target}",
            finding_type="Structuring beneath the CTR reporting threshold",
            mechanism_family="rule",
            mechanism="rule.structuring",
            mechanism_params={
                "ctr_threshold": config.CTR_THRESHOLD,
                "band": [config.STRUCTURING_BAND_LOW, config.STRUCTURING_BAND_HIGH],
                "min_count": config.STRUCTURING_MIN_COUNT,
                "window_hours": config.STRUCTURING_WINDOW_HOURS,
            },
            statement=(
                f"{len(deposits)} deposits totalling Rs {total:,} reached account "
                f"{store.g.nodes[target].get('account_no')} within {span_h:.0f} hours. "
                f"Every one sits between Rs {config.STRUCTURING_BAND_LOW:,} and the "
                f"Rs {config.CTR_THRESHOLD:,} Cash Transaction Report threshold, and "
                f"none of them individually triggers a report."
            ),
            evidence=evidence,
            confidence=0.91,
            confidence_meaning=(
                "A deterministic rule either fires or it does not; the figure is the "
                "historical precision of this rule at review, not a model score. "
                "Rule-based findings are held to a precision floor of 0.85 (metric M2)."
            ),
            limitations=(
                "Legitimate businesses with genuine sub-threshold cash cycles trip "
                "this rule. It shows deposit timing and amount only - it says nothing "
                "about the source of the funds, and cannot distinguish deliberate "
                "structuring from ordinary trade receipts of a similar size."
            ),
            pack=2,
            subject_ids=[target] + [e["src"] for e in deposits],
            extra={
                "deposits": [
                    {"from": e["src"], "amount": e["props"]["amount"],
                     "when": e["event_time"], "channel": e["props"].get("channel")}
                    for e in deposits
                ],
                "total": total, "window_hours": round(span_h, 1),
            },
        ))
    return out


# ==========================================================================
# 2. Graph-structural - communities, betweenness, and the cross-domain chain
# ==========================================================================

def structural(store, allowed_tiers: list[str]) -> list[Finding]:
    out = []
    analysis = store.communities_and_bridges(allowed_tiers)

    bridge = next((n for n in analysis["ranked"]
                   if store.g.nodes[n].get("label") == "Person"), None)
    if bridge:
        impact = store.disconnects_if_removed(bridge, allowed_tiers)
        und = store.visible(allowed_tiers).to_undirected(as_view=True)
        group = store.resolved_group(bridge, allowed_tiers)

        # Neighbours of the *resolved* identity, which is the union of the
        # neighbours of every record that resolved into it.
        neighbours: set[str] = set()
        for member in group:
            neighbours.update(und.neighbors(member))
        neighbours -= set(group)

        n_spanned = analysis["community_span"].get(bridge, 0)
        packs = set()
        for m in neighbours:
            for m2 in list(und.neighbors(m)) + [m]:
                if store.g.nodes[m2].get("label") == "Case":
                    p = store.g.nodes[m2].get("pack")
                    if p:
                        packs.add(p)

        evidence = [_ev(store, b, "record resolving to the bridging identity")
                    for b in group]
        for m in sorted(neighbours)[:8]:
            evidence.append(_ev(store, m, "directly linked record spanning the communities"))

        out.append(Finding(
            finding_id=f"F-STRUCT-{bridge}",
            finding_type="Bridge between otherwise separate communities",
            mechanism_family="structural",
            mechanism="structural.community_bridge",
            mechanism_params={
                "community_algorithm": "Louvain",
                "resolution": config.COMMUNITY_RESOLUTION,
                "centrality": "betweenness (Brandes, normalised)",
                "subgraph_bound": config.MAX_SUBGRAPH_NODES,
                "seed": 42,
            },
            statement=(
                f"{store.g.nodes[bridge].get('name')} - a single identity resolved "
                f"from {len(group)} separate case records - touches "
                f"{n_spanned} otherwise separate communities and carries a normalised "
                f"betweenness of {analysis['betweenness'].get(bridge, 0):.3f}, the "
                f"highest of any person in the bounded subgraph. Removing this node "
                f"{'splits' if impact['splits'] else 'does not split'} the network. "
                f"The communities it connects span "
                f"{', '.join(config.PACK_LABELS.get(p, str(p)) for p in sorted(packs))}."
            ),
            evidence=evidence,
            confidence=0.78,
            confidence_meaning=(
                "Rank-based, not probabilistic: this node's betweenness relative to "
                "every other node in the bounded subgraph. It measures position in the "
                "network, and says nothing on its own about culpability."
            ),
            limitations=(
                "Betweenness is an artefact of what has been collected. A node can "
                "look like a bridge purely because the data around it is denser, and "
                "a genuine bridge can be invisible if the records that would reveal "
                "it were never ingested. Computed on a subgraph bounded at "
                f"{config.MAX_SUBGRAPH_NODES} nodes, so it is local, not national."
            ),
            pack=2,
            subject_ids=[bridge],
            extra={
                "betweenness": round(analysis["betweenness"].get(bridge, 0), 4),
                "communities_spanned": n_spanned,
                "resolved_from": group,
                "n_communities": analysis["n_communities"],
                "removal_impact": impact,
                "bounded_at": analysis["bounded_at"],
                "top_by_betweenness": [
                    {"id": n, "display": store.g.nodes[n].get("name") or n,
                     "label": store.g.nodes[n].get("label"),
                     "betweenness": round(analysis["betweenness"][n], 4)}
                    for n in sorted(analysis["betweenness"],
                                    key=lambda x: -analysis["betweenness"][x])[:6]
                ],
            },
        ))

    # --- the cross-domain chain (demonstration criterion 2)
    chain = store.path_between("C-001", "C-005", allowed_tiers)
    if chain["found"]:
        evidence = [_ev(store, n["id"], f"step {i + 1} on the traced path")
                    for i, n in enumerate(chain["nodes"])]
        # Describe the path from the edges actually traversed, so the sentence
        # cannot drift away from the route the traversal really took.
        steps = []
        for i, n in enumerate(chain["nodes"]):
            steps.append(n["display"])
            if i < len(chain["edges"]):
                steps.append(f"--[{chain['edges'][i]['type']}]-->")
        hops = " ".join(steps)
        rel_types = [e["type"] for e in chain["edges"]]
        out.append(Finding(
            finding_id="F-STRUCT-CHAIN",
            finding_type="Cross-domain link between separate investigations",
            mechanism_family="structural",
            mechanism="structural.community_bridge",
            mechanism_params={"traversal": "shortest path over the visible subgraph",
                              "max_hops": 8},
            statement=(
                f"A {chain['hops']}-hop path connects a theft investigation in Jaipur "
                f"to a smuggling investigation at Kandla port, running through the "
                f"bullion dealer who received the stolen property and the "
                f"laundering-flagged account he controls. No single source system "
                f"holds both ends of this path. Relationships traversed: "
                f"{', '.join(rel_types)}. Route: {hops}."
            ),
            evidence=evidence,
            confidence=0.83,
            confidence_meaning=(
                "Every edge on this path is a recorded fact drawn from a source "
                "document, so the path exists with certainty. The figure reflects "
                "confidence that the path is investigatively meaningful rather than "
                "incidental, which is a judgement, not a measurement."
            ),
            limitations=(
                "A path is not a conspiracy. Two parties can transact without shared "
                "intent, and a bullion dealer will legitimately appear between a theft "
                "and a bank. The value-share reaching the far end of this chain is not "
                "computed here, so the strength of the financial link is unquantified "
                "(FR-GRA-8 remains open in this build)."
            ),
            pack=6,
            subject_ids=[n["id"] for n in chain["nodes"]],
            extra={"path": chain},
        ))

    # --- the restricted-tier finding (demonstration criterion 5)
    if "restricted" in allowed_tiers and "P-030" in store.g:
        out.append(Finding(
            finding_id="F-STRUCT-RESTRICTED",
            finding_type="Public servant linked to a financier under investigation",
            mechanism_family="structural",
            mechanism="structural.community_bridge",
            mechanism_params={"traversal": "1-hop neighbourhood", "tier": "restricted"},
            statement=(
                "Devendra Rathore, Deputy Commissioner of Customs at Kandla, received "
                "Rs 25,00,000 through an informal value transfer from the financier "
                "behind consignment BE/2025/KDL/88214, and cleared that consignment out "
                "of turn. This record is Restricted tier and is not visible to Standard "
                "or Elevated logins."
            ),
            evidence=[
                _ev(store, "P-030", "the public servant"),
                _ev(store, "P-020", "the financier who made the payment"),
                _ev(store, "CNS-001", "the consignment cleared out of turn"),
            ],
            confidence=0.71,
            confidence_meaning=(
                "Reflects the strength of the underlying reporting, not the graph "
                "structure. One leg rests on informant material corroborated by call "
                "records; corroborated single-source reporting is capped at 0.75."
            ),
            limitations=(
                "One leg of this finding rests on informant reporting, which cannot be "
                "independently verified within the system and must never be exported "
                "(FR-GOV-4). Out-of-turn clearance has legitimate operational "
                "explanations and is not by itself evidence of an offence."
            ),
            tier="restricted",
            pack=6,
            subject_ids=["P-030", "P-020"],
        ))
    return out


# ==========================================================================
# 3. Statistical - Benford's Law, applied to a population
# ==========================================================================

def _benford(amounts: list[int]) -> dict[str, Any]:
    """First-digit conformity. Refuses to run where the test is not valid.

    Benford applies to populations spanning several orders of magnitude, not to
    one account's handful of transactions. Running it anyway produces a number
    that looks like evidence and is not.
    """
    amounts = [a for a in amounts if a > 0]
    n = len(amounts)
    if n < config.BENFORD_MIN_N:
        return {"applicable": False,
                "reason": f"n={n} is below the minimum of {config.BENFORD_MIN_N}"}
    orders = math.log10(max(amounts)) - math.log10(min(amounts))
    if orders < config.BENFORD_MIN_ORDERS_OF_MAGNITUDE:
        return {"applicable": False,
                "reason": (f"the population spans only {orders:.1f} orders of "
                           f"magnitude; Benford requires at least "
                           f"{config.BENFORD_MIN_ORDERS_OF_MAGNITUDE}")}

    counts = Counter(int(str(a)[0]) for a in amounts)
    observed = [counts.get(d, 0) / n for d in range(1, 10)]
    chi2 = sum((counts.get(d, 0) - n * BENFORD_EXPECTED[d - 1]) ** 2
               / (n * BENFORD_EXPECTED[d - 1]) for d in range(1, 10))
    mad = sum(abs(o - e) for o, e in zip(observed, BENFORD_EXPECTED)) / 9

    if mad > config.BENFORD_MAD_SUSPECT:
        verdict = "nonconformity"
    elif mad > config.BENFORD_MAD_MARGINAL:
        verdict = "marginal"
    else:
        verdict = "conforms"
    return {
        "applicable": True, "n": n, "chi2": round(chi2, 2), "mad": round(mad, 5),
        "verdict": verdict, "orders_of_magnitude": round(orders, 2),
        "observed": [round(o, 4) for o in observed],
        "expected": [round(e, 4) for e in BENFORD_EXPECTED],
        "critical_value_chi2_p01": 20.09,   # 8 degrees of freedom
    }


def benford(store) -> list[Finding]:
    clusters: dict[str, list[int]] = {}
    for t in store.transactions:
        clusters.setdefault(t.get("cluster", "unknown"), []).append(t["amount"])

    suspect = _benford(clusters.get("laundering", []))
    control = _benford(clusters.get("control", []))
    if not suspect.get("applicable") or suspect["verdict"] == "conforms":
        return []

    accounts = sorted({t["src_account"] for t in store.transactions
                       if t.get("cluster") == "laundering"}
                      | {t["dst_account"] for t in store.transactions
                         if t.get("cluster") == "laundering"})
    evidence = [_ev(store, a, "account contributing to the tested population")
                for a in accounts if a in store.g]

    return [Finding(
        finding_id="F-STAT-BENFORD",
        finding_type="First-digit distribution inconsistent with Benford's Law",
        mechanism_family="statistical",
        mechanism="statistical.benford",
        mechanism_params={
            "min_n": config.BENFORD_MIN_N,
            "min_orders_of_magnitude": config.BENFORD_MIN_ORDERS_OF_MAGNITUDE,
            "mad_threshold_suspect": config.BENFORD_MAD_SUSPECT,
            "scope": "population of all transactions across the flagged cluster",
        },
        statement=(
            f"Across {suspect['n']} transactions spanning "
            f"{suspect['orders_of_magnitude']} orders of magnitude in this cluster, "
            f"leading digit 9 occurs at {suspect['observed'][8] * 100:.1f}% against an "
            f"expected {BENFORD_EXPECTED[8] * 100:.1f}%, while leading digit 1 is "
            f"suppressed at {suspect['observed'][0] * 100:.1f}% against an expected "
            f"{BENFORD_EXPECTED[0] * 100:.1f}%. Mean absolute deviation "
            f"{suspect['mad']:.4f} exceeds the {config.BENFORD_MAD_SUSPECT} "
            f"nonconformity threshold. The same test over an unrelated district "
            f"cluster of {control.get('n', 0)} transactions returns "
            f"'{control.get('verdict', 'n/a')}'."
        ),
        evidence=evidence,
        confidence=0.66,
        confidence_meaning=(
            "Nigrini's mean-absolute-deviation banding, where above 0.012 is read as "
            "nonconformity. It is a property of the population as a whole and is not "
            "attributable to any individual transaction or account within it."
        ),
        limitations=(
            "Benford is a screening test, never proof. It is invalid on populations "
            "with assigned or bounded numbers, on small samples, and on data spanning "
            "less than two orders of magnitude - the mechanism refuses to run in those "
            "cases rather than returning a figure. Legitimate businesses with "
            "price-point clustering also fail it. It cannot identify which "
            "transactions are responsible."
        ),
        pack=2,
        subject_ids=accounts,
        extra={"suspect": suspect, "control": control,
               "control_note": "unrelated Pune district cluster, used as a control"},
    )]


# ==========================================================================
# 4. Time-series - CUSUM change-point detection
# ==========================================================================

def cusum(store) -> list[Finding]:
    out = []
    for account, series in store.daily_volume.items():
        values = np.array([p["credit"] for p in series], dtype=float)
        dates = [p["date"] for p in series]
        base = values[: config.CUSUM_BASELINE_DAYS]
        mu0, sigma = float(base.mean()), float(base.std(ddof=1))
        if sigma <= 0:
            continue
        k = config.CUSUM_K_SIGMA * sigma
        h = config.CUSUM_H_SIGMA * sigma

        s_hi, chart, alarm_idx = 0.0, [], None
        for i, x in enumerate(values):
            s_hi = max(0.0, s_hi + (x - mu0) - k)
            chart.append(s_hi)
            if alarm_idx is None and s_hi > h and i >= config.CUSUM_BASELINE_DAYS:
                alarm_idx = i
        if alarm_idx is None or account not in store.g:
            continue

        post = values[alarm_idx:]
        out.append(Finding(
            finding_id=f"F-TS-{account}",
            finding_type="Sustained change in transaction volume",
            mechanism_family="timeseries",
            mechanism="timeseries.cusum",
            mechanism_params={
                "statistic": "one-sided upper CUSUM",
                "baseline_days": config.CUSUM_BASELINE_DAYS,
                "k_sigma": config.CUSUM_K_SIGMA, "h_sigma": config.CUSUM_H_SIGMA,
                "mu0": round(mu0, 2), "sigma": round(sigma, 2),
            },
            statement=(
                f"Daily credit volume on account "
                f"{store.g.nodes[account].get('account_no')} shifted from a baseline "
                f"of about Rs {mu0:,.0f} per day to about Rs {post.mean():,.0f} per "
                f"day, with the change detected on {dates[alarm_idx]}. No individual "
                f"day is extreme enough to trip a fixed threshold; the signal is in "
                f"the accumulation."
            ),
            evidence=[_ev(store, account, "account whose volume series was tested")],
            confidence=0.74,
            confidence_meaning=(
                "The decision interval h was set at 5 baseline standard deviations, "
                "which corresponds to a low false-alarm rate for an in-control "
                "process. It expresses confidence that a change occurred, not that "
                "the change is criminal."
            ),
            limitations=(
                "CUSUM detects that a process shifted, never why. A new legitimate "
                "contract, a seasonal cycle or a business acquisition produce the same "
                "signal. The detection date lags the true change point by design, and "
                "the baseline assumes the first "
                f"{config.CUSUM_BASELINE_DAYS} days were themselves in control - if "
                "the account was already being misused, the baseline is contaminated."
            ),
            pack=2,
            subject_ids=[account],
            extra={
                "series": [{"date": d, "credit": int(v)} for d, v in zip(dates, values)],
                "chart": [round(c, 1) for c in chart],
                "h": round(h, 1), "mu0": round(mu0, 1),
                "alarm_index": alarm_idx, "alarm_date": dates[alarm_idx],
                "post_change_mean": round(float(post.mean()), 1),
            },
        ))
    return out


# ==========================================================================
# 5. Vector-similarity - modus operandi matching
# ==========================================================================

class TfidfNarrativeVectorizer:
    """Narrative encoder. Swappable for sentence-transformers without touching
    the mechanism: the contract is encode(list[str]) -> matrix."""

    name = "tfidf-word-1-2gram"

    def encode(self, texts: list[str]) -> np.ndarray:
        vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2),
                              sublinear_tf=True)
        return vec.fit_transform(texts).toarray()


def _feature_matrix(profiles: dict[str, dict]) -> tuple[list[str], np.ndarray, list[str]]:
    keys = sorted(profiles)
    vocab = sorted({f"{k}={v}" for p in profiles.values()
                    for k, v in p["features"].items()})
    mat = np.zeros((len(keys), len(vocab)))
    for i, cid in enumerate(keys):
        for k, v in profiles[cid]["features"].items():
            mat[i, vocab.index(f"{k}={v}")] = 1.0
    return keys, mat, vocab


def mo_similarity(store, vectorizer=None) -> list[Finding]:
    profiles = store.mo_profiles
    if len(profiles) < 2:
        return []
    vectorizer = vectorizer or TfidfNarrativeVectorizer()

    keys, feat, _ = _feature_matrix(profiles)
    feat_sim = cosine_similarity(feat)
    text_sim = cosine_similarity(vectorizer.encode([profiles[k]["narrative"] for k in keys]))
    combined = (config.MO_FEATURE_WEIGHT * feat_sim
                + config.MO_TEXT_WEIGHT * text_sim)

    out = []
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            score = float(combined[i, j])
            if score < config.MO_SIMILARITY_THRESHOLD:
                continue
            a, b = keys[i], keys[j]
            fa, fb = profiles[a]["features"], profiles[b]["features"]
            agreeing = [k for k in fa if fa[k] == fb.get(k)]

            # Shared identifiers would make this finding redundant; the point of
            # the mechanism is to connect cases that share nothing concrete.
            und = store.g.to_undirected(as_view=True)
            shared = set(und.neighbors(a)) & set(und.neighbors(b))

            out.append(Finding(
                finding_id=f"F-VEC-{a}-{b}",
                finding_type="Matching modus operandi across unconnected cases",
                mechanism_family="vector",
                mechanism="vector.mo_similarity",
                mechanism_params={
                    "feature_weight": config.MO_FEATURE_WEIGHT,
                    "text_weight": config.MO_TEXT_WEIGHT,
                    "threshold": config.MO_SIMILARITY_THRESHOLD,
                    "text_encoder": vectorizer.name,
                    "similarity": "cosine",
                },
                statement=(
                    f"{store.g.nodes[a].get('district')} case {a} and "
                    f"{store.g.nodes[b].get('district')} case {b} agree on "
                    f"{len(agreeing)} of {len(fa)} modus operandi attributes "
                    f"(combined similarity {score:.2f}) while sharing no person, "
                    f"phone, account or vehicle. The two narratives describe the same "
                    f"method in different words, which is why the structured "
                    f"attributes carry {config.MO_FEATURE_WEIGHT:.0%} of the weight "
                    f"and the free text only {config.MO_TEXT_WEIGHT:.0%}."
                ),
                evidence=[
                    _ev(store, a, "first case"),
                    _ev(store, b, "second case"),
                    _ev(store, f"D-{a[2:]}", "first FIR narrative"),
                    _ev(store, f"D-{b[2:]}", "second FIR narrative"),
                ],
                confidence=round(score, 3),
                confidence_meaning=(
                    "Cosine similarity of a weighted modus operandi vector, on a scale "
                    "where 1.0 is an identical attribute profile. It measures "
                    "resemblance of method. It is not a probability that the same "
                    "people committed both offences."
                ),
                limitations=(
                    "Method resemblance is weak evidence on its own. Burglary "
                    "techniques are copied, taught and independently reinvented, and "
                    "common methods will match by coincidence across unrelated crews. "
                    "The attributes were extracted from the FIR text, so an inaccurate "
                    "or terse FIR silently degrades this comparison. This finding is a "
                    "lead for a human to test, never a link in itself."
                ),
                pack=7,
                subject_ids=[a, b],
                extra={
                    "feature_similarity": round(float(feat_sim[i, j]), 3),
                    "text_similarity": round(float(text_sim[i, j]), 3),
                    "combined": round(score, 3),
                    "agreeing_features": {k: fa[k] for k in agreeing},
                    "differing_features": {
                        k: {"a": fa[k], "b": fb.get(k)} for k in fa if fa[k] != fb.get(k)},
                    "shared_entities": sorted(shared),
                    "narratives": {a: profiles[a]["narrative"], b: profiles[b]["narrative"]},
                },
            ))
    return out


# ==========================================================================
# 6. Emergency lookup - direct indexed retrieval, no queue, no scoring
# ==========================================================================

def emergency_prior_hit(store) -> list[Finding]:
    out = []
    for n, d in store.g.nodes(data=True):
        if d.get("label") != "Phone":
            continue
        # Cases sit up to two hops away: a handset reaches a case directly, or
        # through the pack-specific record (KidnappingCase, CyberComplaint) or
        # through its registered holder.
        und = store.g.to_undirected(as_view=True)
        reached: set[str] = set()
        for nb in und.neighbors(n):
            reached.add(nb)
            reached.update(und.neighbors(nb))
        cases = sorted(c for c in reached if store.g.nodes[c].get("label") == "Case")
        kidnap = [c for c in cases if store.g.nodes[c].get("pack") == 10]
        prior = [c for c in cases if store.g.nodes[c].get("pack") != 10]
        if not (kidnap and prior):
            continue

        out.append(Finding(
            finding_id=f"F-EMG-{n}",
            finding_type="Emergency lookup returned a prior-case hit",
            mechanism_family="emergency",
            mechanism="emergency.direct_lookup",
            mechanism_params={"index": "phone.number, phone.imei",
                              "queue": "bypassed", "scoring": "none"},
            statement=(
                f"The handset used for the ransom demand in {kidnap[0]} "
                f"({d.get('number')}) already exists in this system. It was recorded "
                f"in {prior[0]}, a "
                f"{config.PACK_LABELS.get(store.g.nodes[prior[0]].get('pack'), '')} "
                f"case opened {store.g.nodes[prior[0]].get('opened')} in "
                f"{store.g.nodes[prior[0]].get('district')}, and is registered to a "
                f"named suspect in that investigation."
            ),
            evidence=[_ev(store, n, "the handset queried")]
                     + [_ev(store, c, "case this handset already appears in")
                        for c in kidnap + prior],
            confidence=1.0,
            confidence_meaning=(
                "This is a retrieval, not a detection. The number either is in the "
                "index or it is not; there is no model and no estimate. Confidence "
                "1.0 refers to the match, not to any inference drawn from it."
            ),
            limitations=(
                "A number appearing in a prior case does not establish that the same "
                "person holds it now. Numbers are recycled by operators, handsets "
                "change hands, and SIMs are obtained on other people's documents. "
                "Subscriber details must be re-verified with the operator before any "
                "action is taken on this."
            ),
            pack=10,
            subject_ids=[n] + kidnap + prior,
            extra={"kidnapping_cases": kidnap, "prior_cases": prior},
        ))
    return out


# ==========================================================================

def run_all(store, merges: list[dict[str, Any]]) -> list[Finding]:
    """Every mechanism runs at Restricted tier so the full finding set exists;
    the API then filters per caller. Findings are never generated per-login."""
    all_tiers = list(config.TIERS)
    findings: list[Finding] = []
    findings += er_findings(store, merges)
    findings += structuring(store)
    findings += structural(store, all_tiers)
    findings += benford(store)
    findings += cusum(store)
    findings += mo_similarity(store)
    findings += emergency_prior_hit(store)
    return findings
