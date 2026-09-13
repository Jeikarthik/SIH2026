# CNAS — Criminal Network Analysis System

**Problem statement SIH 26189 · working prototype**

> Police data is record-centric. Criminal organisations are networks. No officer
> working a single case has any mechanical way to see that their case is one node
> in a larger graph. CNAS builds that graph, runs detection over it, and shows
> every finding as an inspectable chain of evidence — never as a bare score.

All data in this build is synthetic. Nothing here is a real person, case, account
or phone number (PRD principle P7).

---

## Run it

```bash
pip install -r requirements.txt
python run_pipeline.py     # build the graph, resolve entities, run detection
python serve.py            # opens http://127.0.0.1:8077
```

No database server, no Docker, no build step, no network access required —
Cytoscape.js is vendored locally so the demo works on venue wifi or none at all.
`python-docx` is the only optional dependency: without it, report export falls
back to a Word-compatible HTML document instead of a real `.docx`.

`run_pipeline.py` ends by self-checking all six demonstration criteria from
PRD §7.3 and prints PASS/FAIL for each. If the demo has a hole in it, that
output says so before you find out on stage.

---

## What is real, and what is stood in for

This is the honest version of the table, because the difference matters if a
judge asks.

| Layer | Full architecture (v8) | This build |
|---|---|---|
| Detection mechanisms | 6 families | **Real.** All six implemented and running |
| Explainability Contract | FR-EXP-1 | **Real.** Enforced structurally — a `Finding` cannot be constructed without every field |
| Entity resolution | Splink | **Real logic**, different engine: rapidfuzz + jellyfish + Devanagari transliteration, same three-band decision, same reversibility |
| Access tiers | Keycloak | **Real enforcement**, fake auth: tiers are applied in the query layer; the login is a dropdown |
| Audit log | hash-chained | **Real.** SHA-256 chained, with a working verifier that detects any edited row |
| Bi-temporal edges | FR-GRA-3 | **Real.** Event time and ingestion time on every edge |
| Model registry | MLflow | `model_versions` table — which is what Architecture v8 §6 specifies anyway |
| Graph store | Neo4j + GDS | **NetworkX.** Same algorithms (Louvain, Brandes betweenness); what is lost is distribution, not method. Confined to `cnas/graph.py` |
| Streaming / orchestration | Kafka, Flink, Airflow | A single ordered pipeline. Same stages, same sequence, different transport |
| NER | multilingual extraction | Pre-extracted at data-generation time |
| PII tokenisation | Vault | SQLite token vault with logged detokenisation |

The graph store is the one substitution worth stating plainly rather than
glossing: at ~90 nodes the algorithms and their results are identical, and the
swap to a Cypher-backed store means rewriting one file.

---

## Scope

Five crime packs, chosen so the cross-domain chain and the emergency lookup both
have somewhere to land: **Theft & Robbery (7)**, **Money Laundering (2)**,
**Smuggling & Customs (6)**, **Cybercrime & Fraud (3)**, **Kidnapping &
Extortion (10)**.

### The six mechanisms

| Family | Mechanism | Notes |
|---|---|---|
| Rule-based | Structuring beneath the PMLA ₹10,00,000 CTR threshold | Detection band is ₹9.0–9.99 L within 48 h |
| Graph-structural | Louvain communities + Brandes betweenness | Runs on resolved identities, bounded at 300 nodes (FR-GRA-7) |
| Statistical | Benford's Law first-digit conformity | **Population-level.** Refuses to run below n=150 or under 2 orders of magnitude |
| Time-series | CUSUM change-point detection | Catches a sustained shift no single day would trip |
| Vector-similarity | Modus operandi matching | Structured MO vector (0.70) + TF-IDF narrative (0.30), cosine |
| Emergency lookup | Direct indexed retrieval | No queue, no model, no score |

---

## Reports

Three things can be exported as a Word document, each from the button on the
view it belongs to:

| Report | Where | Contains |
|---|---|---|
| Case analysis | Case workspace | Case particulars, the extracted network record by record, and every finding on that network in full |
| Review queue | Review queue | Summary table, then each finding in full; honours the mechanism and status filters in force |
| Single finding | Details panel, or an expanded queue card | One finding's complete explainability record |

A report is built once as a content model and rendered to `.docx`, so the same
report cannot say different things in different formats. Three properties hold
for all three:

- **A report can only contain what the officer can see.** It is generated from
  the same tier-filtered query layer as the screen, so the same export run under
  a lower tier is a shorter document, and a case report states how many records
  were withheld from it.
- **Nothing is exported without evidence.** Every finding carries its evidence
  table, mechanism version, parameters, confidence meaning and limitations into
  the document, because a finding that arrives on someone's desk stripped of its
  contract is exactly the failure the Explainability Contract exists to prevent.
- **Each report digests itself.** A SHA-256 of the content is printed in the
  document and written to the audit ledger at export time, so a printed report
  can be tied back to the moment it was produced — and one that was never
  produced by this system has no matching ledger entry.

---

## Four corrections made to the source plan

These were wrong in the build plan and are fixed here:

1. **Benford on a single account is a statistical misuse.** It needs a population
   spanning orders of magnitude. It now runs across the cluster's full
   transaction ledger, states its own n-requirement, and **refuses to run** when
   the data cannot support it. A clean control cluster is tested alongside and
   correctly comes back conforming.
2. **₹2,00,000 is not a reporting threshold.** Structuring means sitting under a
   *reporting* trigger; under PMLA that is the ₹10,00,000 CTR.
3. **The audit log had to be hash-chained**, not merely append-only (FR-GOV-3,
   NFR-8). It is, and `/api/audit-log/verify` proves it.
4. **Neo4j Aura Free would not have worked** — AuraDB Free ships no Graph Data
   Science, so the one component the plan said not to fake would have been
   silently removed.

Smaller ones: exact identifiers resolve deterministically and never enter the
probabilistic score (FR-ER-5); phonetic matching transliterates Devanagari
rather than relying on Soundex (FR-ER-4); findings carry the merges that
produced them so a bad merge can be traced and unwound (FR-ER-7); and record
linkage is blocked on phonetic keys, without which the review queue floods with
pairs no human would ever have looked at.

---

## Design decisions worth defending

**A `Finding` cannot be constructed without its full contract.** Evidence,
confidence *meaning*, and limitations are validated in `__post_init__`.
Safety metric S2 sets unexplained findings to a ceiling of zero, and the cheapest
way to hold that line is to make the violation impossible rather than remembered.

**Tier filtering is in the query layer, never the UI.** FR-GOV-1 says so
explicitly. A restricted node is reported as `404`, not `403` — a "forbidden"
would itself disclose that the record exists, which is risk R7.

**Absent evidence is not counter-evidence.** A missing date of birth or a
different address contributes nothing to the ER score rather than counting
against the pair. People move house and FIRs omit fields; treating silence as
disagreement manufactures false negatives.

**Absent a date of birth, a pair cannot be auto-merged** however high it scores,
because it cannot be ruled *out* (FR-ER-6). This is what puts the planted false
positive in front of a human instead of silently merging two unrelated people.

**Structural analytics run on resolved identities, not raw records.** SAME_AS is
contracted before centrality. Three FIR mentions of one person would otherwise
inflate each other's betweenness and manufacture a bridge out of duplicate data
entry.

**A rejection without a reason is refused by the API.** A rejection that teaches
the system nothing is not a review (P4).

---

## Layout

```
cnas/
  config.py       every threshold a judge might ask about, in one place
  seed.py         the hand-crafted dataset and the six planted scenarios
  graph.py        graph store, tier enforcement, ego networks, centrality
  er.py           entity resolution: deterministic pass, then three-band
  findings.py     the Explainability Contract, enforced
  mechanisms.py   all six mechanism families
  store.py        hash-chained audit, token vault, model registry
  auth.py         role -> tiers
  report.py       one content model, rendered to .docx or Word HTML
  api.py          FastAPI
web/              single-page console (vendored Cytoscape.js)
data/             generated — graph.json, findings.json, cnas.sqlite
```

See `DEMO_SCRIPT.md` for the six-step walkthrough mapped 1:1 to PRD §7.3.
