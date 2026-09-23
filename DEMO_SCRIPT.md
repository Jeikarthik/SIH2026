# Demo script — the six PRD §7.3 criteria, then two closing steps

Rehearse this. Do not improvise it. Roughly 8–9 minutes.

**Before you start:** run `python run_pipeline.py` (resets every finding to
pending), then `python serve.py`. Role selector at top right should read
**Standard Officer**. Open on the **Case workspace** tab.

---

## Opening line

> "An FIR is a document about an incident. A CDR is a list of calls. Each sits in
> its own system, indexed by its own key. Criminal organisations aren't
> record-centric — they're networks. Nothing in the current toolchain represents
> the network at all, so serial offenders get found by luck or not at all.
> This is what finding them mechanically looks like."

---

## 1 — Entity resolution collapse · criterion 1

**Do:** Click case **C-001, Jewellery showroom burglary (Jaipur)**. Let the graph
settle. In the left rail under *Findings on this network*, click
**Entity resolution collapse**.

**Before you say anything, let them read the canvas.** Every node carries its
record type as a three-letter code, its betweenness as its size, and a red ring
if a finding cites it. The three `PER` nodes that are all Ramesh Yadav are the
same size as each other, because centrality is computed on resolved identities
rather than on raw records — which is the point this step is about, visible
before anyone says it.

**Say:**
> "Three cases. Jaipur, Indore, Surat. Three districts, three filing officers,
> three different investigations. The name is spelled three different ways —
> Ramesh Yadav, Ramesh Yadev, and once in Devanagari, which Soundex cannot touch
> at all. What ties them is that all three handsets carry the same IMEI."

**Point at the panel:** evidence list, then the field-agreement table.

> "Exact identifier equality is resolved deterministically — no probability is
> involved, because there's no uncertainty to model. The person-level merge is
> scored separately, field by field, and you can see each field's contribution."

**Read the limitation aloud.** It is the strongest thing on the screen:
> "A shared IMEI proves a shared handset, not a shared user. Handsets are sold,
> lent and stolen. The system says that itself, on the finding, unprompted."

---

## 2 — Cross-domain chain · criterion 2

**Do:** Click **Trace cross-domain link** in the canvas bar. The graph stands
down and the path takes the whole view: six numbered cards, each with what that
record is, and between them the relationship traversed and the date it happened.

**Read the captions in order, left to right.** They are not narration — every
one is a field off the record itself:

> "Theft & Robbery, Jaipur. Receiver of stolen property, bullion dealer.
> Laundering suspect, Union Bank. Under scrutiny, Kotak Mahindra. Financier,
> import-export. Smuggling & Customs, Kandla.
> That progression is the system's, not mine. I have not written a word of it —
> the dealer's role is on his record, the account flag is on the account, the
> crime type is on the case.
> Five hops. No single source system holds both ends of this path. Today nobody
> connects those two cases, because there is no place where both of them exist
> at once."

**If asked why it is not drawn as a graph:** a six-node line laid out by a force
algorithm is a worse drawing of itself. The cards show every node, every
relationship and every date, and they fit on a projector.

---

## 3 — All six mechanism families · criterion 3

**Do:** Go to **Review queue**. Click through the mechanism filter on the left,
opening one card per family. The panels that land best:

- **Statistical (Benford)** — point at the bar chart.
  > "Leading digit 9 at 28% against an expected 4.6%. But notice what it says
  > about itself: this only runs on a population spanning at least two orders of
  > magnitude, n of at least 150. Run Benford on one account's handful of
  > transactions and you get a number that looks like evidence and isn't. We also
  > run it on an unrelated clean district as a control — that one comes back
  > conforming."
- **Vector-similarity (MO)** — show the two narratives side by side.
  > "Two burglaries, no shared person, phone, account or vehicle. Read the two
  > FIRs — they share almost no vocabulary. One says 'gas cutter', the other says
  > 'oxy-acetylene torch'. Keyword matching finds nothing here. The match comes
  > from the structured MO attributes, which is why they carry 70% of the weight."
- **Time-series (CUSUM)** — show the sparkline.
  > "No single day here is extraordinary. A threshold alert would never fire. The
  > signal is in the accumulation."

**Say, generally:**
> "Every finding on this screen carries the same six things: a plain-language
> statement, the exact evidence records, the mechanism and its parameters, a
> confidence figure *and what that figure means*, and the known limitations.
> That isn't a template we filled in — the Finding object refuses to be
> constructed without them."

---

## 4 — Rejecting the false positive · criterion 4

**Do:** Filter to **Entity resolution**. Open
**Possible duplicate person — review required**.

**Say:**
> "Two records, both 'Suresh Kumar'. Identical name, identical phonetics, and
> both addresses say Shivaji Nagar — which is one of the most common locality
> names in the country. Score 0.82. That's inside the review band, so the system
> has not merged them and won't without a human.
> Look at why it couldn't rule them out: one record has no date of birth. Missing
> data can't be treated as disagreement, but it also can't be treated as
> confirmation — so it stops here and asks."

**Do:** Type into the reason box:
> `Shivaji Nagar is among the most common locality names in India. Different
> states, no shared phone, account or vehicle, and no DOB on the second record.
> No basis to merge.`

Click **Reject**. Then try clicking **Reject** on another finding with the box
empty — the API refuses it.

**Say:**
> "A rejection without a reason teaches the system nothing. The API rejects the
> rejection. Merging two people is the most dangerous thing this system does —
> a false merge puts an innocent person inside a criminal network."

---

## 5 — Restricted tier · criterion 5

**Do:** Note the left rail: *Withheld at your tier: 1*. Then switch the role
selector to **Restricted Analyst**. Re-open case C-005 or the review queue.

**Say:**
> "As a Standard officer I could see that something was withheld, but not what.
> Now, as Restricted — a Deputy Commissioner of Customs, taking ₹25 lakh from the
> financier, who cleared that consignment out of turn.
> The important part is where that filtering happens. It is not the UI hiding a
> row. It's applied in the query layer, so a Standard login cannot reach that node
> by any path — and a restricted record returns 404, not 403, because 'forbidden'
> would itself confirm the record exists."

**Do:** Go to **Audit log**. Point at both accesses.
> "Both logins are in the ledger. Append-only and hash-chained."

**Do:** Click **Verify chain integrity**.
> "Every entry commits to the one before it. Edit any historical row and every
> hash after it stops matching. We tested that — it's caught at the exact row."

---

## 6 — Emergency lookup · criterion 6

**Do:** Go to **Emergency search**. Type `9039144517`. Press Enter.

**Say:**
> "Kidnapping. The ransom call came from this number twenty minutes ago. This
> path bypasses every queue, every model, every score — it's a direct indexed
> retrieval, because in an active abduction a ranked list of probable matches is
> worse than useless."

**Point at the timing readout, then the result.**
> "Five milliseconds. And the number isn't new — it's already in a cyber-fraud
> case in Indore from April, registered to a named suspect. That officer has a
> name and an address to work with, now, rather than in three weeks."

**Do:** Click the prior case to jump into its workspace.

---

## 7 — A new record arriving · the graph is not a picture

**Do:** Go to **Evidence intake**. Drag `samples/FIR-Kota-2026-00318.docx` onto
the drop zone — or click the **Kota burglary (.docx)** shortcut. Type nothing.

**Say while it parses:**
> "That is a Word document. An FIR, as it would actually arrive."

**Point at the blue panel, then scroll the form:**
> "Twenty values, out of a document nobody has read. Six case fields, the
> accused and his date of birth, his mobile number, the handset IMEI, and all
> ten modus operandi attributes. Under every box is where it came from.
> Some of that is trivial — 'District: Kota' is a labelled field on a form, not
> a discovery. The IMEI is a shape: fifteen consecutive digits. Note the order
> there, because it matters — the IMEI is taken first and masked out, or ten of
> its digits become a phone number that was never in the document.
> The interesting row is the modus operandi. The document says 'gas cutter'. The
> attribute says `thermal_cutting`, because the case in Nagpur says
> 'oxy-acetylene torch' and those are the same method described twice. That is
> the whole reason the mechanism carries a structured vector instead of reading
> the narrative."

**Do:** Expand **Document text, with every extracted value marked**.
> "And here is the document with every one of them highlighted where it sits.
> Nothing here asks to be trusted."

**Say, before clicking:**
> "It has stopped. It has not filed anything. Extraction is rules, rules are
> fallible, and the officer signs the record — so the parse is a proposal and
> this button is the decision."

**Do:** Click **Ingest record**.

**Point at the result panel, then the graph it drops you into:**
> "Four records created. Three records already on file resolved to the same
> handset — those are the three green-ringed ones, and these three in blue were
> already here. Two findings raised against cases in Jaipur and Nagpur.
> Nobody searched for anything, and nobody typed anything. A document arrived
> and the system found what it belonged to. That is the whole argument: the FIR
> is not a document that goes into a drawer, it is a node that lands in a
> network."

**Do:** Go to **Audit log**, and click **Verify chain integrity**.
> "The ingestion, each merge and each finding are all in the ledger, and the
> chain still verifies."

**After the demo:** run `python run_pipeline.py` to rebuild the graph from seed.
Intake writes to it, so the next rehearsal starts from a clean C-007. You do not
need to stop the server — it notices the rebuilt files and reloads them.

---

## 8 - Taking it off the screen

**Do:** Back in **Case workspace**, with C-001 selected, click **Export report**.
Open the downloaded `.docx`.

**Say:**
> "An officer does not work from a browser tab. This is the case file as a Word
> document: the network record by record, then every finding in full - evidence,
> mechanism version, the parameters it ran with, what its confidence figure
> means, and its limitations. Nothing is summarised out.
> Two things to note. It is generated from the same tier-filtered query the
> screen uses, so this same button under a standard officer's login produces a
> shorter document, and it says so. And the document digests itself: that
> SHA-256 at the foot is written to the audit ledger at the moment of export, so
> a report can be tied back to the moment it was produced."

---

## Closing line

> "Retrieval before prediction. Every finding carries its evidence. The human
> decides, and the interface makes that true rather than nominal. And the system
> states what it cannot see — every finding on that queue carries its own
> limitations, because a lead that oversells itself is how an investigation goes
> wrong."

---

## If a judge asks

**"Why isn't the risk colour-coded, red for dangerous?"**
> "Because there is no risk score, and there must not be one. Size is
> betweenness — where a record sits in the recorded relationships. The red ring
> means a finding cites that record as evidence. Both are traceable back to
> documents. A green-to-red ramp on a person would be a propensity score, which
> is an explicit non-goal in the PRD and is not in the ontology anywhere."

**"Is that a language model reading the FIR?"**
> "No. It is rules, in three layers, and the interface tells you which layer
> produced each value. Labelled form fields, identifier patterns, and a lexicon
> for the modus operandi attributes. A transformer NER model would replace that
> one module and nothing else — the contract it produces is the same."

**"What does it get wrong?"**
> "It will not read a scanned FIR — a PDF with no text layer is refused rather
> than guessed at, because OCR is not in this build. It does not disambiguate
> names; that is entity resolution and it happens afterwards, where it is
> explainable. And the lexicon is the layer that infers, so if a narrative
> describes a method in words we have never seen, that attribute comes back
> empty rather than wrong. Which is why an officer confirms the parse."


**"Is this Neo4j?"**
> "No — NetworkX, in process. Same algorithms, Louvain and Brandes betweenness.
> At this scale the results are identical; what's missing is distribution, not
> method. It's confined to one module, so moving to Neo4j and GDS is rewriting
> one file. The README says exactly this."

**"Isn't this predictive policing?"**
> "No. Nothing here scores a person for propensity to offend. Every detection is
> about evidenced past events and recorded relationships. It's an explicit
> non-goal in the PRD, and there's no propensity attribute anywhere in the
> ontology."

**"How do you know your confidence numbers are right?"**
> "For the rule-based and emergency findings they're not estimates at all — the
> rule fired or it didn't, the number is in the index or it isn't. For the rest,
> each one states what it means on the finding itself. Some of them are
> deliberately rank-based rather than probabilistic, and say so. We'd rather
> state the basis than imply a calibration we haven't measured."

**"What happens when a merge turns out to be wrong?"**
> "Every finding lists the merges behind it. Records are linked, not collapsed,
> so unmerging is removing an edge — the pre-merge state was never destroyed.
> There's an endpoint for it and it writes to the ledger."

**"What's the hardest dependency in production?"**
> "CCTNS/ICJS integration. Roughly 70% of the value depends on it. Without it
> this demonstrates the method rather than delivering the outcome — which is why
> the pilot should be scoped to one state with an MoU, not a national rollout."
