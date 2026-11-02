"""Per-field confidence as an additive log-odds model over observable signals.

Starting from the extractor's own certainty, each signal adds or subtracts
log-odds, then the result is squashed back to 0..1 and capped by document
quality. Additive log-odds keeps every contribution explainable (each one is
emitted as a human-readable reason) and the weights can be refit with logistic
regression once there is labelled data (see ``eval/evaluate.py``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# Signal weights in log-odds. Hand-set; see README "Calibration".
W = {
    "grounded_exact": 0.8,
    "grounded_partial": 0.0,
    "not_grounded": -2.5,  # a quote that is not in the document is the main hallucination signal
    "no_evidence": -0.8,
    "value_not_in_evidence": -1.0,
    "extractors_agree": 1.6,
    "extractors_disagree": -1.2,
    "only_one_extractor_found_it": -0.3,
    "check_passed": 0.8,  # per check, capped at 2
    "check_failed": -1.8,
    "warning_failed": -0.8,
    "resolved_by_arithmetic": 0.0,  # already credited through check_passed
    "ocr_corrected": -0.7,
    "ambiguous_day_month": -0.9,
    "inferred_from_keywords": -0.6,
    "converted_from_weeks": -0.3,
    "working_days_not_calendar": -0.5,
}
MAX_CHECK_BONUS = 2
CEILING = 0.99


def logit(p: float) -> float:
    """Convert a probability to log-odds, clamped away from 0 and 1."""
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def sigmoid(x: float) -> float:
    """Convert log-odds back to a probability."""
    return 1 / (1 + math.exp(-x))


@dataclass
class Signals:
    certainty: float
    grounding: float | None = None  # None = could not be checked (e.g. scanned PDF)
    has_evidence: bool = True
    value_in_evidence: bool = True
    agreement: str | None = None  # "agree" | "disagree" | "single" | None (only one extractor ran)
    checks_passed: int = 0
    checks_failed: int = 0
    warnings_failed: int = 0
    flags: list[str] = field(default_factory=list)


def score(s: Signals, doc_quality: float) -> tuple[float, list[str]]:
    """Combine a field's signals into a confidence score plus the human-readable reasons behind it."""
    x = logit(s.certainty)
    reasons = [f"extractor certainty {s.certainty:.2f}"]

    def add(key: str, label: str, times: int = 1) -> None:
        """Apply one weighted signal to the running log-odds and record why."""
        nonlocal x
        if times and W[key]:
            x += W[key] * times
            reasons.append(f"{'+' if W[key] > 0 else '-'} {label}")

    if not s.has_evidence:
        add("no_evidence", "no supporting quote")
    elif s.grounding is not None:
        if s.grounding >= 0.95:
            add("grounded_exact", "quote found verbatim in document")
        elif s.grounding < 0.7:
            add("not_grounded", f"quote not found in document (overlap {s.grounding:.0%})")
        if not s.value_in_evidence:
            add("value_not_in_evidence", "value does not appear in its own quote")
    if s.agreement == "agree":
        add("extractors_agree", "rules and LLM extractors agree")
    elif s.agreement == "disagree":
        add("extractors_disagree", "rules and LLM extractors disagree")
    elif s.agreement == "single":
        add("only_one_extractor_found_it", "only one extractor found this field")
    add("check_passed", f"{min(s.checks_passed, MAX_CHECK_BONUS)} arithmetic check(s) pass", min(s.checks_passed, MAX_CHECK_BONUS))
    add("check_failed", f"{s.checks_failed} arithmetic check(s) fail", s.checks_failed)
    add("warning_failed", f"{s.warnings_failed} sanity check(s) fail", s.warnings_failed)
    for f in s.flags:
        if f in W:
            add(f, f.replace("_", " "))

    p = sigmoid(x)
    cap = 0.6 + 0.4 * doc_quality
    if cap < 1:
        reasons.append(f"capped by document text quality {doc_quality:.2f}")
    return round(min(p * cap, CEILING), 3), reasons
