"""One-shot pipeline: seed -> load -> entity resolution -> detection -> findings.

The production architecture moves these stages with Kafka, Airflow and Flink.
Here they run in order in a single process. The stages, their sequence and
their outputs are the same; only the transport is different, and the transport
is not what is being demonstrated.

    python run_pipeline.py
"""
from __future__ import annotations

import json
import sys
import time

from cnas import config, findings as findings_mod, mechanisms, seed, store as store_mod
from cnas.er import Resolver
from cnas.graph import GraphStore

ACTOR = "pipeline"
ROLE = "system"


def banner(step: str, detail: str = "") -> None:
    print(f"  [{time.strftime('%H:%M:%S')}] {step:<34} {detail}")


def main() -> int:
    t0 = time.time()
    print("\n  CNAS ingestion pipeline")
    print("  " + "-" * 58)

    # ---------------------------------------------------------------- stage 1
    store_mod.init(reset=True)
    banner("audit + vault + registry", "initialised")

    data = seed.write()
    banner("synthetic records generated",
           f"{len(data['nodes'])} nodes, {len(data['edges'])} edges, "
           f"{len(data['transactions'])} transactions")
    store_mod.audit(ACTOR, ROLE, "INGEST", "seed",
                    {"nodes": len(data["nodes"]), "edges": len(data["edges"]),
                     "synthetic": True})

    # ---------------------------------------------------------------- stage 2
    gs = GraphStore(data)
    banner("graph assembled", f"{gs.g.number_of_nodes()} nodes in memory")

    # ---------------------------------------------------------------- stage 3
    resolver = Resolver(gs)
    merges = resolver.run()
    auto = [m for m in merges if m["decision"] == "auto_merge"]
    review = [m for m in merges if m["decision"] == "human_review"]
    det = [m for m in auto if m["method"] == "deterministic"]
    banner("entity resolution",
           f"{len(auto)} auto-merged ({len(det)} deterministic), "
           f"{len(review)} held for review")
    for m in merges:
        store_mod.audit(ACTOR, ROLE, "MERGE_DECISION", m["merge_id"],
                        {"decision": m["decision"], "score": m["score"],
                         "method": m["method"], "left": m["left"], "right": m["right"]})

    # ---------------------------------------------------------------- stage 4
    for mech, version in config.MODEL_VERSIONS.items():
        store_mod.record_model(mech, version, {"source": "config.MODEL_VERSIONS"})

    results = mechanisms.run_all(gs, merges)
    by_family: dict[str, int] = {}
    for f in results:
        by_family[f.family_label] = by_family.get(f.family_label, 0) + 1
    banner("detection mechanisms", f"{len(results)} findings")
    for family, n in sorted(by_family.items()):
        print(f"{'':<48}{family}: {n}")
    for f in results:
        store_mod.audit(ACTOR, ROLE, "FINDING_CREATED", f.finding_id,
                        {"mechanism": f.mechanism, "confidence": f.confidence,
                         "tier": f.tier})

    # ---------------------------------------------------------------- stage 5
    # Direct identifiers are tokenised (FR-GOV-2). The vault keeps the mapping;
    # detokenisation is a separately authorised, separately logged action.
    tokenised = 0
    for n in data["nodes"]:
        for field in ("number", "account_no", "imei"):
            val = n["props"].get(field)
            if val:
                store_mod.tokenize(str(val), field)
                tokenised += 1
    banner("direct identifiers tokenised", f"{tokenised} values in vault")

    findings_mod.save(results)
    gs.save()
    banner("written", f"{config.GRAPH_PATH.name}, {config.FINDINGS_PATH.name}")

    chain = store_mod.verify_chain()
    banner("audit chain", f"{chain['entries']} entries, intact={chain['intact']}")

    print("  " + "-" * 58)
    print(f"  done in {time.time() - t0:.2f}s\n")

    # A quick self-check that the six demonstration criteria all have something
    # behind them. If one of these is missing the demo has a hole in it.
    ids = {f.finding_id for f in results}
    checks = [
        ("1  entity-resolution collapse", "F-ER-001" in ids),
        ("2  cross-domain chain", "F-STRUCT-CHAIN" in ids),
        ("3  all six mechanism families",
         len({f.mechanism_family for f in results}) >= 6),
        ("4  rejectable false positive",
         any(f.finding_id.startswith("F-ER-P-") for f in results)),
        ("5  restricted-tier item", any(f.tier == "restricted" for f in results)),
        ("6  emergency prior-case hit",
         any(f.finding_id.startswith("F-EMG-") for f in results)),
    ]
    print("  demonstration criteria (PRD 7.3)")
    for label, ok in checks:
        print(f"    {'PASS' if ok else 'FAIL'}  {label}")
    print()
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
