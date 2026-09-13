# Demo script — six steps, mapped 1:1 to PRD §7.3

Rehearse this. Do not improvise it. Roughly 6–7 minutes.

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

**Do:** Click **Trace cross-domain link** in the canvas bar. The five-hop path
replaces the case view and reads left to right, end to end.

**Say:**
> "Theft case in Jaipur. The stolen gold goes to a bullion dealer. That dealer
> controls an account already flagged for laundering. That account transacts with
> an account belonging to the financier behind an undeclared consignment seized at
> Kandla port — a customs case, different agency, different state, different
> crime.
> Five hops. No single source system holds both ends of this path. Today nobody
> connects those two cases, because there is no place where both of them exist
> at once."

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

## 7 - Taking it off the screen

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
