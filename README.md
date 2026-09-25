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

pip install -r requirements-dev.txt
python -m pytest           # 25 API tests; each builds its own dataset in a temp dir
```

No database server, no Docker, no build step, no network access required —
Cytoscape.js is vendored locally so the demo works on venue wifi or none at all.

Two dependencies degrade rather than break. Without `python-docx`, report export
falls back to a Word-compatible HTML document instead of a real `.docx`, and
evidence intake refuses `.docx` uploads with a message saying why. Without
`pymupdf`, PDF intake falls back to `pypdf` and then refuses. Every other
document format still works in both cases.

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
| Bi-temporal edges | FR-GRA-3 | **Real.** Event time and ingestion time on every edge, both shown on the events strip |
| Model registry | MLflow | `model_versions` table — which is what Architecture v8 §6 specifies anyway |
| Graph store | Neo4j + GDS | **NetworkX.** Same algorithms (Louvain, Brandes betweenness); what is lost is distribution, not method. Confined to `cnas/graph.py` |
| Streaming / orchestration | Kafka, Flink, Airflow | A single ordered pipeline. Same stages, same sequence, different transport |
| NER | multilingual transformer extraction | **Rule-based, and says so.** Evidence intake reads a real FIR document: labelled form fields, identifier patterns, and a modus operandi lexicon. Every value carries the span it came from. No model; no Devanagari narrative parsing |
| PII tokenisation | Vault | SQLite token vault with logged detokenisation |

The graph store is the one substitution worth stating plainly rather than
glossing: at ~60 nodes the algorithms and their results are identical, and the
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

## Reading the graph

A node carries three things at once, and none of them is a score about a person:

| Channel | Means |
|---|---|
| Colour and pictogram | What kind of record it is |
| Size | Betweenness centrality, across the whole visible network |
| Red ring | How many findings cite this record as evidence |

There is deliberately no risk colour. Nothing in CNAS scores a person for
propensity to offend, so nothing on the canvas may imply that it does. A node
is large because of where it sits in the recorded relationships and ringed
because evidence points at it, and both of those are traceable to records.

Beneath the canvas, the **events strip** plots the dated events in the network
on an event-time axis. Standing relationships are excluded from it: an account
opening date and an address association are dated facts rather than things that
happened, and plotting them puts a 2023 account opening in front of a 2025
theft. Which edge types count as events is declared in
`config.EVENT_EDGE_TYPES`. Hovering an event shows both its event time and its
ingestion time, which is where the bi-temporal claim becomes checkable rather
than asserted.

---

## Evidence intake

Drop an FIR into the **Evidence intake** tab — Word, PDF or plain text — and it
is read, parsed, reviewed and filed against the running graph. This is the one
place the demonstration shows the system doing what it exists to do: a record
arrives and attaches itself to what is already held.

### Reading the document

Extraction is rule-based in three layers, in decreasing reliability, and the
interface labels every value with which layer produced it:

| Layer | What it reads | Example |
|---|---|---|
| Labelled fields | An FIR is a form | `District : Kota` is not a guess |
| Identifier patterns | Shapes that can be matched exactly | fifteen digits is an IMEI; `RJ 14 AB 1234` is a registration |
| Modus operandi lexicon | Phrases that mean the same method | "gas cutter" and "oxy-acetylene torch" both give `tool_class = thermal_cutting` |

An IMEI is taken before phone numbers are looked for, and its digits masked
out, because ten digits of a fifteen-digit IMEI otherwise become a phone number
that was never in the document.

Only the third layer infers anything, and it is the one the review step exists
for. Every extracted value carries the span of text it came from; the parse
panel shows the document with each one marked in place, so "where did that IMEI
come from" is answered by looking rather than by trusting. A parsed modus
operandi value the graph has never recorded is flagged rather than offered,
because it would produce a vector the mechanism has nothing to compare against.

**The parse is a separate call from the ingestion.** A document that filed
itself the moment it was dropped would put a machine's reading of an FIR into
the record with nobody having seen it, which is the opposite of what the rest of
this system argues for. Nothing reaches the graph until an officer confirms it.

What this does *not* do: resolve names against a gazetteer, disambiguate people,
or read a scanned FIR — a PDF with no text layer is refused rather than guessed
at, and OCR is not in this build. Name disambiguation is entity resolution, and
it happens afterwards in `er.py` where it is explainable.

### After the confirmation

Everything downstream of the review is the production path:

- the **deterministic resolver**, unchanged, scoped to the records that just
  arrived — a shared IMEI links the new handset to the ones already on file
- the **modus operandi mechanism**, unchanged, against every case on record
- an `INGEST` entry in the hash-chained ledger, plus one per merge and one per
  finding, with `Verify chain` still passing afterwards

Probabilistic merges are not applied here. A merge that needs a human belongs in
the review queue with a human in front of it, and a record arriving through this
door gets no shortcut past that.

New findings are added by id and never replace an existing one. The narrative
vectoriser refits over the enlarged corpus, so scores on existing pairs shift
slightly; overwriting a finding on that basis would silently revert a decision
an officer had already recorded against it.

Intake writes to `data/graph.json`. `python run_pipeline.py` rebuilds it from
seed, which is the reset between rehearsals, **and the running server picks that
up without being restarted.** That is not incidental: the API holds the graph
and the findings in memory between requests, so a server started before a
rebuild would go on serving the old graph and then write it back over the new
one at the next ingestion — a reset that silently undoes itself, which is the
worst possible way to discover it. Both files are checked for modification on
read.

---

## Case notes and the case timeline

Every case page has a **sticky-note icon** at the bottom right, with a count of
the notes on that case. It opens the case's notes. Officers can write, colour,
edit and delete them, and each note shows who wrote it and when.

**Case timeline** in the canvas toolbar opens the whole history of the case
in one place, oldest first:

| Entry | Where it comes from |
|---|---|
| Case registered | The case's own opening date |
| Evidence entered the case | Every record attached to the case, with both the date it happened and the date the system learnt of it |
| Network activity | Dated events in the surrounding network: fencing, transfers, calls |
| Resolution and findings | Entity-resolution merges and detection findings touching the network |
| Decisions | Every confirm or reject taken on those findings, kept even when later reversed, plus every change of case status |
| Investigation | Milestones an officer logs: arrest, raid, seizure, chargesheet, hearing (confirming or closing a case is a status change, not a milestone) |
| Notes | That a note was written, and by whom (the text stays in the notes panel) |

The case status can be changed from the same screen, but only with a reason.
The change becomes a timeline entry. Each seeded case carries a few synthetic
milestones, so every timeline runs from complaint to its present state.

Both features follow the rules the rest of the system keeps:
- **Tiers apply.** Notes and milestones carry an access tier and are filtered
  on the server. A note defaults to its author's most sensitive tier, so a
  Restricted analyst's note never reaches a Standard officer by accident.
- **The audit log records the act, not the text.** The audit log is readable
  at every tier. Each note, milestone or status change is written there as an
  id, a tier and a SHA-256 of the text.
- **A rebuild clears them.** `run_pipeline.py` resets notes and milestones
  along with everything else, because intake reuses case ids after a rebuild.

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
  store.py        hash-chained audit, token vault, model registry, case notes/milestones
  casefile.py     a case's full timeline, assembled on read
  auth.py         role -> tiers
  extract.py      reading an FIR document: form fields, patterns, MO lexicon
  intake.py       a new FIR arriving at a graph that already exists
  report.py       one content model, rendered to .docx or Word HTML
  api.py          FastAPI
web/              single-page console (vendored Cytoscape.js)
samples/          synthetic FIR documents to drop into evidence intake
tests/            pytest suite for the case-file API (notes, timeline, status)
data/             generated — graph.json, findings.json, cnas.sqlite
```

See `DEMO_SCRIPT.md` for the 3-minute demo video script: a plain-language
walkthrough that touches all six PRD §7.3 criteria, then evidence intake and the
case timeline.
