"""Check that an extractor's evidence really is in the document, and that the value is in the evidence."""

from __future__ import annotations

import re
from difflib import SequenceMatcher


def _norm(s: str) -> str:
    """Lowercase and collapse whitespace so quotes can be compared to the document text."""
    return re.sub(r"\s+", " ", s).strip().lower()


def ground(evidence: str | None, text: str) -> float:
    """Fraction of the evidence found verbatim (modulo whitespace/case) in the text. 1.0 = exact."""
    if not evidence or not evidence.strip():
        return 0.0
    ev, doc = _norm(evidence), _norm(text)
    if ev in doc:
        return 1.0
    # Longest contiguous overlap; tolerant of a few chars the model "cleaned up".
    m = SequenceMatcher(None, doc, ev, autojunk=False).find_longest_match(0, len(doc), 0, len(ev))
    return round(m.size / len(ev), 3)


def _digits(s: str) -> str:
    """Keep only the digits of a string."""
    return re.sub(r"[^\d]", "", s)


def value_in_evidence(raw: str | None, evidence: str | None, kind: str) -> bool:
    """Return True if the extracted value actually appears inside its own evidence quote."""
    if raw is None or evidence is None:
        return False
    if kind in ("money", "number"):
        d = _digits(raw).lstrip("0")
        if not d:
            return True
        # "12,450.00" vs evidence "$12,450" -- allow missing trailing cents.
        return d in _digits(evidence) or d.rstrip("0") in _digits(evidence)
    if kind in ("enum", "int"):
        return True  # these are interpretations of wording, not copies
    r, e = _norm(raw), _norm(evidence)
    return r in e or SequenceMatcher(None, r, e).find_longest_match(0, len(r), 0, len(e)).size >= 0.8 * len(r)
