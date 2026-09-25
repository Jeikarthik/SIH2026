# Demo script — 3 minutes

One idea per scene. Say what the viewer is looking at and why it matters; leave
the mechanics to the README. Spoken text is about 500 words, which fills
3:00–3:10 at a brisk pace with the clicks in between. Keep the clicks moving
while you talk.

**Before recording:** run `python run_pipeline.py`, then `python serve.py`.
Role selector reads **Standard Officer**. Start on the **Case workspace** tab.

---

## 0:00 — The problem

**Screen:** Case workspace, no case selected.

> "Police records are kept one case at a time — an FIR in one system, phone
> records in another, bank statements somewhere else. But criminals don't work
> one case at a time. They work as networks. The same man turns up in three
> districts under three spellings, and nobody connects them — because no one
> can see all the records at once. CNAS puts every record into one connected
> picture, and points out what an officer needs to look at."

## 0:25 — One person, three cases

**Do:** Click case **C-001, Jewellery showroom burglary (Jaipur)**. In the left
rail, click **Entity resolution collapse**.

> "A jewellery showroom burglary in Jaipur. Every dot here is a record — a
> person, a phone, a bank account, a vehicle — and the lines are how they're
> connected. The system has found that the accused here is the same man named
> in cases in Indore and Surat — spelled differently each time, once in Hindi,
> but all three share the same phone handset. And it says, in plain words,
> what that link proves and what it doesn't."

## 0:55 — From a theft to smuggling

**Do:** Click **Trace cross-domain link**.

> "Now follow the stolen gold. To a bullion dealer. Through two bank accounts.
> To a financier. And into a smuggling case at Kandla port. Five steps, across
> police, banking and customs records that never talk to each other. Two cases
> nobody would have linked — here, it's one trail."

## 1:20 — Leads, not verdicts

**Do:** Go to **Review queue**. Click through two or three cards. Open
**Possible duplicate person — review required**. Type
`Common name and locality, no shared phone or account.` and click **Reject**.

> "Everything the system finds lands here as a lead — money moved in amounts
> just under the reporting limit, burglaries with the same method in different
> cities, a sudden change in account activity. Each lead comes with its
> evidence and its limits. And the system never decides. These two 'Suresh
> Kumars' look alike, but an officer says no — and must write down why. CNAS
> never rates a person as dangerous; it connects what's on record, and the
> officer makes the call."

## 1:55 — Who sees what

**Do:** Switch the role selector to **Restricted Analyst**, open case **C-005**.

> "Some records are sensitive — here, a customs officer taking a bribe to clear
> a shipment. Only cleared officers can see it; for everyone else, it simply
> isn't there. And every search, every view, every decision is written to a
> tamper-proof log."

**Do:** Switch back to **Standard Officer**.

## 2:15 — When minutes matter

**Do:** Go to **Emergency search**, type `9039144517`, press Enter.

> "A kidnapping. The ransom call came from this number twenty minutes ago. One
> search, instant answer: the number is already in a fraud case in Indore,
> with a name and an address."

## 2:30 — A new FIR arrives

**Do:** Go to **Evidence intake**, click the **Kota burglary (.docx)** shortcut,
then **Ingest record**.

> "A new FIR comes in as a Word file. The system reads it and fills in the
> form — names, phone, handset, how the crime was done — and the officer checks
> it before anything is saved. The moment it's saved, it links itself to the
> network: same handset as the Jaipur case, same method as a burglary in
> Nagpur. Nobody searched for that."

## 2:50 — The whole case, start to end

**Do:** Case workspace, C-001, click **Case timeline**. Then close it and click
**Export report**.

> "And every case keeps its full story — complaint, raid, arrest, and what the
> system found — in one timeline, with officers' notes alongside. One click
> turns it into a report, evidence included."

## 3:00 — Close

> "CNAS covers 14 crime types where the records connect across systems —
> theft, money laundering, smuggling, cyber fraud and kidnapping. One connected
> picture of crime. Every lead backed by evidence. And an officer makes every
> decision. That's CNAS."

---

**After recording:** run `python run_pipeline.py` to reset the data. The server
picks up the reset without a restart.
