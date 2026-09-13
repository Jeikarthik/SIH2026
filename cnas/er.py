"""Entity resolution.

PRD principle P3: merging two people is the most dangerous thing the system
does. A false merge puts an innocent person inside a criminal network. So this
module is deliberately conservative and deliberately verbose about its reasoning:

  * exact identifiers resolve deterministically, with no probabilistic score
    involved at all (FR-ER-5);
  * everything else goes through a weighted, per-field, explainable score with
    a three-band decision (FR-ER-2);
  * a field with no data contributes nothing rather than counting against the
    pair - people move house and FIRs omit dates of birth, and treating silence
    as disagreement manufactures false negatives;
  * absent a date of birth, a pair cannot be ruled out, so it cannot be
    auto-merged either. It goes to a human (FR-ER-6);
  * every merge keeps its pre-merge state and is reversible (FR-ER-3).

Phonetic matching handles Devanagari by transliterating to Latin first, because
Soundex and Metaphone are Latin-alphabet algorithms and FR-ER-4 explicitly
requires more than Soundex alone.
"""
from __future__ import annotations

import itertools
from datetime import datetime, timezone
from typing import Any

import jellyfish
from rapidfuzz import fuzz

from . import config

# --------------------------------------------------------------------------
# Devanagari -> Latin transliteration (FR-ER-4)
#
# Enough of an ITRANS-style mapping to handle Indian personal names. Not a
# general-purpose transliterator: it exists so that "रमेश यादव" and
# "Ramesh Yadav" reach the same phonetic key.
# --------------------------------------------------------------------------
_CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v", "ळ": "l",
    "श": "sh", "ष": "sh", "स": "s", "ह": "h",
    "ड़": "r", "ढ़": "rh", "फ़": "f", "ज़": "z", "क़": "q", "ख़": "kh", "ग़": "g",
}
_INDEPENDENT_VOWELS = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo",
    "ऋ": "ri", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au",
}
_MATRAS = {
    "ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "ृ": "ri",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au",
}
_VIRAMA = "्"
_NASALS = {"ं": "n", "ँ": "n", "ः": "h"}


def transliterate(text: str) -> str:
    """Devanagari to Latin. Latin input passes through untouched."""
    if not any("ऀ" <= ch <= "ॿ" for ch in text):
        return text
    units: list[list[str]] = []   # [consonant, vowel]
    for ch in text:
        if ch in _CONSONANTS:
            units.append([_CONSONANTS[ch], "a"])   # inherent schwa
        elif ch in _MATRAS:
            if units:
                units[-1][1] = _MATRAS[ch]
            else:
                units.append(["", _MATRAS[ch]])
        elif ch == _VIRAMA:
            if units:
                units[-1][1] = ""                  # schwa suppressed
        elif ch in _INDEPENDENT_VOWELS:
            units.append(["", _INDEPENDENT_VOWELS[ch]])
        elif ch in _NASALS:
            units.append([_NASALS[ch], ""])
        elif ch.isspace():
            units.append([" ", ""])
        else:
            units.append([ch, ""])
    # Hindi drops the word-final inherent vowel: रमेश is "ramesh", not "ramesha".
    for i, u in enumerate(units):
        at_word_end = (i == len(units) - 1) or (units[i + 1][0] == " ")
        if at_word_end and u[1] == "a" and u[0] not in ("", " "):
            u[1] = ""
    return "".join(c + v for c, v in units)


def normalise_name(name: str | None) -> str:
    """Fold to a comparable form: transliterate, lowercase, flatten long vowels."""
    if not name:
        return ""
    s = transliterate(name).lower().strip()
    s = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in s)
    for long_v, short_v in (("aa", "a"), ("ee", "i"), ("oo", "u")):
        s = s.replace(long_v, short_v)
    return " ".join(s.split())


def _expand_initials(a: str, b: str) -> tuple[str, str]:
    """Let "R. Yadav" compare fairly against "Ramesh Yadav"."""
    ta, tb = a.split(), b.split()
    if len(ta) == len(tb):
        out_a, out_b = [], []
        for wa, wb in zip(ta, tb):
            if len(wa) == 1 and wb.startswith(wa):
                out_a.append(wb)
                out_b.append(wb)
            elif len(wb) == 1 and wa.startswith(wb):
                out_a.append(wa)
                out_b.append(wa)
            else:
                out_a.append(wa)
                out_b.append(wb)
        return " ".join(out_a), " ".join(out_b)
    return a, b


def phonetic_key(name: str) -> str:
    return " ".join(jellyfish.metaphone(tok) for tok in normalise_name(name).split())


# --------------------------------------------------------------------------
# Field comparators. Each returns a score in [0,1], or None meaning
# "no evidence either way" - which is excluded from the weighted average
# rather than counted as disagreement.
# --------------------------------------------------------------------------

def _cmp_name_fuzzy(a: dict, b: dict) -> tuple[float | None, str]:
    na, nb = normalise_name(a.get("name")), normalise_name(b.get("name"))
    if not na or not nb:
        return None, "one record has no name"
    ea, eb = _expand_initials(na, nb)
    score = fuzz.token_set_ratio(ea, eb) / 100.0
    return score, f"'{na}' vs '{nb}' -> token_set_ratio {score:.2f}"


def _cmp_name_phonetic(a: dict, b: dict) -> tuple[float | None, str]:
    ka, kb = phonetic_key(a.get("name") or ""), phonetic_key(b.get("name") or "")
    if not ka or not kb:
        return None, "one record has no name"
    ta, tb = set(ka.split()), set(kb.split())
    if not ta or not tb:
        return None, "no phonetic tokens"
    overlap = len(ta & tb) / max(len(ta), len(tb))
    note = f"metaphone '{ka}' vs '{kb}'"
    if a.get("name_script") == "devanagari" or b.get("name_script") == "devanagari":
        note += " (after Devanagari transliteration)"
    return overlap, note


def _cmp_dob(a: dict, b: dict) -> tuple[float | None, str]:
    da, db = a.get("dob"), b.get("dob")
    if not da or not db:
        missing = "left" if not da else "right"
        return None, f"no date of birth on the {missing} record - cannot rule out"
    if da == db:
        return 1.0, f"both {da}"
    return 0.0, f"{da} vs {db} - incompatible"


def _cmp_address(a: dict, b: dict, addr_lookup: dict[str, dict]) -> tuple[float | None, str]:
    aa = addr_lookup.get(a.get("address_ref") or "")
    ab = addr_lookup.get(b.get("address_ref") or "")
    if not aa or not ab:
        return None, "address not on file for one record"
    same_line = aa.get("line", "").strip().lower() == ab.get("line", "").strip().lower()
    same_city = aa.get("city", "").strip().lower() == ab.get("city", "").strip().lower()
    if same_line and same_city:
        return 1.0, f"same address: {aa.get('line')}, {aa.get('city')}"
    if same_line:
        # Locality names repeat across the country. This is weak evidence and
        # is exactly the kind of coincidence that produces false positives.
        return 1.0, (f"locality name matches ('{aa.get('line')}') but cities differ "
                     f"({aa.get('city')} vs {ab.get('city')})")
    if same_city:
        return 0.5, f"same city ({aa.get('city')}), different address"
    # People move. Different addresses are not evidence against a match.
    return None, "different addresses - no inference drawn (people relocate)"


def _cmp_co_occurrence(a_id: str, b_id: str, neighbours: dict[str, set]) -> tuple[float, str]:
    shared = neighbours.get(a_id, set()) & neighbours.get(b_id, set())
    if shared:
        return 1.0, f"share {len(shared)} linked record(s): {', '.join(sorted(shared)[:4])}"
    return 0.0, "no shared phone, account, vehicle or address"


# --------------------------------------------------------------------------
# The resolver
# --------------------------------------------------------------------------

class Resolver:
    def __init__(self, store):
        self.store = store
        self.g = store.g
        self._addr = {
            n: d for n, d in self.g.nodes(data=True) if d.get("label") == "Address"
        }
        self._neighbours = self._build_neighbours()
        self.merges: list[dict[str, Any]] = []

    def _build_neighbours(self) -> dict[str, set]:
        """Identifier-bearing neighbours of each person, with deterministic
        identifier groups folded in, so two people holding what turns out to be
        the same handset count as sharing it."""
        und = self.g.to_undirected(as_view=True)
        out: dict[str, set] = {}
        for n, d in self.g.nodes(data=True):
            if d.get("label") != "Person":
                continue
            nb = set()
            for m in und.neighbors(n):
                md = self.g.nodes[m]
                if md.get("label") in ("Phone", "BankAccount", "Vehicle", "Address"):
                    nb.add(self._identity_group(m, md))
            out[n] = nb
        return out

    def _identity_group(self, node_id: str, d: dict) -> str:
        """Collapse a node to its strongest identifier, so three SIM records on
        one handset resolve to a single shared thing."""
        for ident in config.DETERMINISTIC_IDENTIFIERS:
            if d.get(ident):
                return f"{ident}:{d[ident]}"
        return node_id

    # ------------------------------------------------------------ pass one
    def deterministic_pass(self) -> list[dict[str, Any]]:
        """Exact identifier equality. No probabilistic scoring is applied here
        at all - this is a lookup, not an inference (FR-ER-5, principle P1)."""
        buckets: dict[str, list[str]] = {}
        for n, d in self.g.nodes(data=True):
            for ident in config.DETERMINISTIC_IDENTIFIERS:
                val = d.get(ident)
                if val:
                    buckets.setdefault(f"{ident}={val}", []).append(n)

        results = []
        for key, members in buckets.items():
            if len(members) < 2:
                continue
            ident_name = key.split("=", 1)[0]
            for left, right in itertools.combinations(sorted(members), 2):
                results.append(self._record(
                    left, right,
                    decision="auto_merge",
                    score=1.0,
                    method="deterministic",
                    basis=f"exact {ident_name} match ({key.split('=', 1)[1]})",
                    fields=[{
                        "field": ident_name, "score": 1.0, "weight": None,
                        "note": f"identical on both records: {key.split('=', 1)[1]}",
                    }],
                    rationale=(
                        f"Both records carry the same {ident_name}. Exact identifier "
                        f"equality is resolved deterministically and is not put "
                        f"through probabilistic scoring."
                    ),
                ))
        return results

    # ------------------------------------------------------------ pass two
    def probabilistic_pass(self) -> list[dict[str, Any]]:
        """Blocked pairwise comparison.

        Only pairs sharing at least one phonetic key token are compared. This is
        standard record-linkage blocking: comparing every pair against every
        other is quadratic and, more importantly, floods the review queue with
        pairs no human would ever have looked at. Two people whose names share
        no phonetic token are not candidates for the same person.
        """
        people = [(n, d) for n, d in self.g.nodes(data=True)
                  if d.get("label") == "Person"]
        blocks: dict[str, list[str]] = {}
        for n, d in people:
            for tok in set(phonetic_key(d.get("name") or "").split()):
                if tok:
                    blocks.setdefault(tok, []).append(n)

        candidates: set[tuple[str, str]] = set()
        for members in blocks.values():
            for a, b in itertools.combinations(sorted(set(members)), 2):
                candidates.add((a, b))

        results = []
        for ia, ib in sorted(candidates):
            rec = self._score_pair(ia, self.g.nodes[ia], ib, self.g.nodes[ib])
            if rec["decision"] != "auto_reject":
                results.append(rec)
        return results

    def _shares_strong_identifier(self, ia: str, ib: str) -> str | None:
        shared = self._neighbours.get(ia, set()) & self._neighbours.get(ib, set())
        for s in sorted(shared):
            if ":" in s and s.split(":", 1)[0] in config.DETERMINISTIC_IDENTIFIERS:
                return s
        return None

    def _score_pair(self, ia: str, da: dict, ib: str, db: dict) -> dict[str, Any]:
        comparators = [
            ("name_fuzzy", *_cmp_name_fuzzy(da, db)),
            ("name_phonetic", *_cmp_name_phonetic(da, db)),
            ("dob", *_cmp_dob(da, db)),
            ("address", *_cmp_address(da, db, self._addr)),
            ("co_occurrence", *_cmp_co_occurrence(ia, ib, self._neighbours)),
        ]

        fields, total, denom = [], 0.0, 0.0
        for name, score, note in comparators:
            weight = config.ER_WEIGHTS[name]
            fields.append({
                "field": name,
                "score": score,
                "weight": weight,
                "note": note,
                "counted": score is not None,
            })
            if score is not None:
                total += weight * score
                denom += weight

        final = (total / denom) if denom else 0.0
        dob_known = any(f["field"] == "dob" and f["counted"] for f in fields)
        dob_contradicts = any(
            f["field"] == "dob" and f["counted"] and f["score"] == 0.0 for f in fields)

        phonetic_ok = any(f["field"] == "name_phonetic" and f["counted"]
                          and (f["score"] or 0) >= 0.99 for f in fields)
        strong_id = self._shares_strong_identifier(ia, ib)

        # Bands (FR-ER-2), with three overrides on top.
        if dob_contradicts:
            decision, reason = "human_review", (
                "Dates of birth are incompatible. Even a strong identifier match "
                "cannot override that on its own (FR-ER-6), so this pair is held "
                "for a human.")
        elif strong_id and dob_known and phonetic_ok:
            # FR-ER-6 says a strong identifier match is insufficient *if
            # contradicting evidence exists*. Here there is none: the date of
            # birth is present and agrees, and the phonetic name key is
            # identical. That is the case the requirement carves out.
            decision, reason = "auto_merge", (
                f"Both records are linked to the same {strong_id.split(':', 1)[0]} "
                f"({strong_id.split(':', 1)[1]}), the dates of birth agree, and the "
                f"phonetic name keys are identical. With no contradicting evidence, "
                f"FR-ER-6 is satisfied and the pair merges without needing the "
                f"weighted score to clear tau_high (it reached {final:.3f}).")
        elif final >= config.TAU_HIGH and not dob_known:
            decision, reason = "human_review", (
                "Score is above the auto-merge threshold, but neither record "
                "carries a date of birth, so the match cannot be ruled out rather "
                "than positively confirmed. Held for a human.")
        elif final >= config.TAU_HIGH:
            decision, reason = "auto_merge", (
                f"Score {final:.3f} is at or above tau_high {config.TAU_HIGH}.")
        elif final >= config.TAU_LOW:
            decision, reason = "human_review", (
                f"Score {final:.3f} falls between tau_low {config.TAU_LOW} and "
                f"tau_high {config.TAU_HIGH}.")
        else:
            decision, reason = "auto_reject", (
                f"Score {final:.3f} is below tau_low {config.TAU_LOW}.")

        basis = "; ".join(f["note"] for f in fields
                          if f["counted"] and (f["score"] or 0) > 0)
        return self._record(ia, ib, decision=decision, score=round(final, 4),
                            method="probabilistic", basis=basis or "weak agreement",
                            fields=fields, rationale=reason)

    # ------------------------------------------------------------- plumbing
    def _record(self, left: str, right: str, *, decision: str, score: float,
                method: str, basis: str, fields: list[dict], rationale: str
                ) -> dict[str, Any]:
        merge_id = f"M-{method[:3].upper()}-{left}-{right}"
        return {
            "merge_id": merge_id,
            "left": left,
            "right": right,
            "left_label": self.g.nodes[left].get("label"),
            "right_label": self.g.nodes[right].get("label"),
            "left_display": self.g.nodes[left].get("name")
                            or self.g.nodes[left].get("number") or left,
            "right_display": self.g.nodes[right].get("name")
                             or self.g.nodes[right].get("number") or right,
            "decision": decision,
            "score": score,
            "method": method,
            "model_version": config.MODEL_VERSIONS[
                "er.deterministic" if method == "deterministic" else "er.probabilistic"],
            "basis": basis,
            "fields": fields,
            "rationale": rationale,
            "thresholds": {"tau_high": config.TAU_HIGH, "tau_low": config.TAU_LOW},
            # Pre-merge state, kept so the merge is reversible (FR-ER-3).
            "pre_state": {
                "left": dict(self.g.nodes[left]),
                "right": dict(self.g.nodes[right]),
            },
            "decided_by": "automatic" if decision != "human_review" else None,
            "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "reversed": False,
        }

    def run(self) -> list[dict[str, Any]]:
        merges = self.deterministic_pass()
        seen = {(m["left"], m["right"]) for m in merges}
        for m in self.probabilistic_pass():
            if (m["left"], m["right"]) not in seen:
                merges.append(m)
        self.merges = merges
        for m in merges:
            self.store.apply_merge(m)
        return merges
