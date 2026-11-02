"""Orchestration: ingest -> extract (rules + LLM) -> normalise -> reconcile -> validate -> score."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from difflib import SequenceMatcher
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from . import confidence, ingest
from .extractors import gemini as gemini_extractor
from .extractors import llm as llm_extractor
from .extractors import rules as rules_extractor
from .extractors.base import Candidate, ExtractorOutput
from .grounding import ground, value_in_evidence
from .normalize import normalize
from .schema import (LINE_ITEM_FIELDS, REQUIRED_FIELDS, SCALAR_FIELDS, ChangeOrder, ExtractionResult,
                     FieldResult, LineItemResult, ValidationIssue)
from .validate import Check, arithmetic_score, run_checks

REVIEW_THRESHOLD = 0.80
# Any extracted value scoring below this blocks auto-accept, even on optional fields:
# a low-confidence value that is present is more likely wrong than merely uncertain.
LOW_CONFIDENCE_BLOCK = 0.60
MONEY_FIELDS = [f for f, k in SCALAR_FIELDS.items() if k == "money"]


@dataclass
class Choice:
    value: Any
    raw: str | None
    evidence: str | None
    certainty: float
    sources: list[str]
    flags: list[str] = field(default_factory=list)
    agreement: str | None = None
    alt: Choice | None = None


@dataclass
class Item:
    values: dict[str, Any]
    raw: dict[str, str | None]
    flags: dict[str, list[str]]
    evidence: str | None
    certainty: float
    source: str


# ---------------------------------------------------------------- reconcile

def _choice(name: str, kind: str, c: Candidate | None) -> Choice | None:
    """Normalize one extractor's candidate into a Choice, or None if it can't be parsed."""
    if c is None:
        return None
    value, flags = normalize(name, kind, c.raw)
    if value is None:
        return None
    return Choice(value, c.raw, c.evidence, c.certainty, [c.source], list(flags))


def _same(kind: str, a: Any, b: Any) -> bool:
    """Return True if two normalized values agree (fuzzy match for text)."""
    if kind == "text":
        return SequenceMatcher(None, str(a).lower(), str(b).lower()).ratio() >= 0.85
    return a == b


def _grounding_score(ch: Choice, doc: ingest.Document) -> float:
    """Score how well a choice's evidence quote is found in the document text."""
    return 0.0 if doc.kind == "pdf_scanned" else ground(ch.evidence, doc.text)


def reconcile_field(name: str, kind: str, r: Candidate | None, l: Candidate | None, both_ran: bool,
                    doc: ingest.Document) -> Choice | None:
    """Merge the rules and LLM candidates for one field into a single choice."""
    rc, lc = _choice(name, kind, r), _choice(name, kind, l)
    if rc and lc:
        if _same(kind, rc.value, lc.value):
            # LLM is better at text boundaries; rules quotes are exact lines. Keep the LLM value.
            best = replace(lc, sources=["rules", "llm"], certainty=max(lc.certainty, rc.certainty),
                           flags=sorted(set(lc.flags) | set(rc.flags)), agreement="agree")
            return best
        # Disagreement: prefer the grounded, more certain candidate; keep the other for arithmetic arbitration.
        rs = rc.certainty + 0.3 * _grounding_score(rc, doc)
        ls = lc.certainty + 0.3 * _grounding_score(lc, doc) + 0.05  # small LLM prior on ties
        best, other = (lc, rc) if ls >= rs else (rc, lc)
        return replace(best, agreement="disagree", alt=replace(other, agreement="disagree"),
                       flags=best.flags + ["extractors_disagree"])
    one = rc or lc
    if one is None:
        return None
    one.agreement = "single" if both_ran else None
    return one


def _items(out: ExtractorOutput | None) -> list[Item]:
    """Normalize an extractor's raw line items into Items."""
    if out is None:
        return []
    items = []
    for row in out.line_items:
        values, flags = {}, {}
        for f, kind in LINE_ITEM_FIELDS.items():
            values[f], flags[f] = normalize(f, kind, row.fields.get(f))
        if values["amount"] is None:
            continue
        items.append(Item(values, dict(row.fields), flags, row.evidence, row.certainty, row.source))
    return items


def _item_sum_target(v: dict) -> Decimal | None:
    """Return the amount the line items should add up to (subtotal, or total if no markup/tax)."""
    if v.get("subtotal") is not None:
        return v["subtotal"]
    if v.get("markup") is None and v.get("tax") is None:
        return v.get("total_change_amount")
    return None


def choose_items(rules_items: list[Item], llm_items: list[Item], v: dict) -> tuple[list[Item], list[Item]]:
    """Pick one line-item set; return (chosen, alternative)."""
    if not rules_items or not llm_items:
        return (llm_items or rules_items), []
    target = _item_sum_target(v)

    def fits(items: list[Item]) -> bool:
        """Return True if these line items add up to the target amount."""
        return target is not None and abs(sum(i.values["amount"] for i in items) - target) <= Decimal("0.02")

    if fits(rules_items) and not fits(llm_items):
        return rules_items, llm_items
    return llm_items, rules_items


# ---------------------------------------------------------------- derive

def derive(v: dict[str, Any], items: list[Item]) -> dict[str, tuple[Any, list[str]]]:
    """Fill gaps that are arithmetically implied. Returns field -> (value, input fields)."""
    out: dict[str, tuple[Any, list[str]]] = {}
    g = v.get
    if g("total_change_amount") is None:
        if g("new_contract_sum") is not None and g("contract_sum_before") is not None:
            out["total_change_amount"] = (g("new_contract_sum") - g("contract_sum_before"), ["new_contract_sum", "contract_sum_before"])
        elif g("subtotal") is not None and (g("markup") is not None or g("tax") is not None):
            out["total_change_amount"] = (g("subtotal") + (g("markup") or 0) + (g("tax") or 0), ["subtotal", "markup", "tax"])
        elif items and g("subtotal") is None:
            out["total_change_amount"] = (sum(i.values["amount"] for i in items) + (g("markup") or 0) + (g("tax") or 0),
                                          ["line_items", "markup", "tax"])
    if g("contract_sum_before") is None and g("original_contract_sum") is not None and g("prior_change_orders_total") is not None:
        out["contract_sum_before"] = (g("original_contract_sum") + g("prior_change_orders_total"),
                                      ["original_contract_sum", "prior_change_orders_total"])
    before = g("contract_sum_before") if g("contract_sum_before") is not None else out.get("contract_sum_before", (None,))[0]
    total = g("total_change_amount") if g("total_change_amount") is not None else out.get("total_change_amount", (None,))[0]
    if g("new_contract_sum") is None and before is not None and total is not None:
        out["new_contract_sum"] = (before + total, ["contract_sum_before", "total_change_amount"])
    return out


# ---------------------------------------------------------------- helpers

def _jsonable(x: Any) -> Any:
    """Convert Decimal, date and Enum values into JSON-friendly types."""
    if isinstance(x, Decimal):
        return float(x)
    if isinstance(x, date):
        return x.isoformat()
    if isinstance(x, Enum):
        return x.value
    return x


def _checks_for(checks: list[Check], name: str) -> tuple[int, int, int]:
    """Count passed, failed and warning checks that involve the given field."""
    passed = sum(1 for c in checks if c.arithmetic and c.passed and name in c.fields)
    failed = sum(1 for c in checks if c.arithmetic and not c.passed and name in c.fields)
    warned = sum(1 for c in checks if not c.arithmetic and not c.passed and name in c.fields)
    return passed, failed, warned


def pick_provider(provider: str, use_llm: bool | None, client: Any) -> str | None:
    """Which LLM to use: "claude", "gemini", or None (rules only).

    ``auto`` prefers Claude when an Anthropic credential is present, then Gemini.
    """
    if use_llm is False:
        return None
    if provider in ("claude", "gemini"):
        return provider
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return "claude"
    if gemini_extractor.api_key():
        return "gemini"
    if use_llm or client is not None:
        return "claude"
    return None


# ---------------------------------------------------------------- main entry

def run(path: str | Path, use_llm: bool | None = None, client: Any = None,
        model: str | None = None, today: date | None = None, provider: str = "auto") -> ExtractionResult:
    """Run the full pipeline on one document and return the scored, validated result."""
    t0 = time.time()
    doc = ingest.load(path)
    meta: dict[str, Any] = {"input_kind": doc.kind, "pages": doc.pages, "text_quality": doc.quality,
                            "ingest_notes": doc.notes, "extractors": ["rules"]}

    r_out = rules_extractor.extract(doc)
    l_out: ExtractorOutput | None = None
    chosen = pick_provider(provider, use_llm, client)
    if chosen is not None:
        meta["llm_provider"] = chosen
        if chosen == "gemini":
            l_out = gemini_extractor.extract(doc, client=client, model=model or gemini_extractor.DEFAULT_MODEL)
        else:
            l_out = llm_extractor.extract(doc, client=client, model=model or llm_extractor.DEFAULT_MODEL)
        if l_out.error:
            meta["llm_error"] = l_out.error
            l_out = None
        else:
            meta["extractors"].append("llm")
            meta["llm_usage"] = l_out.usage
    both = l_out is not None

    # 1. reconcile scalar fields
    choices: dict[str, Choice | None] = {
        f: reconcile_field(f, kind, r_out.fields.get(f), l_out.fields.get(f) if l_out else None, both, doc)
        for f, kind in SCALAR_FIELDS.items()
    }
    values = {f: (c.value if c else None) for f, c in choices.items()}

    # 2. choose line items, run checks
    r_items, l_items = _items(r_out), _items(l_out)
    items, alt_items = choose_items(r_items, l_items, values)

    def checks_for(vals: dict, its: list[Item]) -> list[Check]:
        """Run the validation checks for a given set of field values and line items."""
        return run_checks(vals, [i.values for i in its], today)

    checks = checks_for(values, items)

    # 3. arithmetic arbitration: when extractors disagree, let the accounting decide.
    for name, ch in choices.items():
        if ch is None or ch.alt is None or SCALAR_FIELDS[name] != "money":
            continue
        trial = {**values, name: ch.alt.value}
        trial_checks = checks_for(trial, items)
        if arithmetic_score(trial_checks) > arithmetic_score(checks):
            choices[name] = replace(ch.alt, alt=ch, flags=ch.alt.flags + ["extractors_disagree", "resolved_by_arithmetic"])
            values, checks = trial, trial_checks
    if alt_items:
        trial_checks = checks_for(values, alt_items)
        if arithmetic_score(trial_checks) > arithmetic_score(checks):
            items, alt_items, checks = alt_items, items, trial_checks
            meta["line_items_resolved_by_arithmetic"] = True

    # 4. derive missing values from arithmetic (they do not feed back into checks)
    derived = derive(values, items)

    # 5. score fields
    fields: dict[str, FieldResult] = {}
    for name, kind in SCALAR_FIELDS.items():
        ch = choices[name]
        if ch is None and name in derived:
            continue  # scored below, once its inputs are scored
        if ch is None:
            fields[name] = FieldResult(value=None, confidence=0.0, flags=["missing"],
                                       reasons=["not found by any extractor"])
            continue
        g = None if doc.kind == "pdf_scanned" else ground(ch.evidence, doc.text)
        p, f_, w = _checks_for(checks, name)
        sig = confidence.Signals(
            certainty=ch.certainty, grounding=g, has_evidence=bool(ch.evidence),
            value_in_evidence=value_in_evidence(ch.raw, ch.evidence, kind),
            agreement=ch.agreement, checks_passed=p, checks_failed=f_, warnings_failed=w, flags=ch.flags)
        conf, reasons = confidence.score(sig, doc.quality if doc.kind != "pdf_scanned" else 0.75)
        flags = list(ch.flags)
        if g is not None and g < 0.7 and ch.evidence:
            flags.append("evidence_not_found")
        if f_:
            flags.append("failed_validation")
        alt = {"alternative_value": _jsonable(ch.alt.value), "alternative_source": ch.alt.sources[0]} if ch.alt else {}
        if alt:
            reasons.append(f"alternative {alt['alternative_source']} value: {alt['alternative_value']}")
        fields[name] = FieldResult(value=_jsonable(ch.value), confidence=conf, sources=ch.sources,
                                   evidence=ch.evidence, flags=flags, reasons=reasons)

    for name in ("contract_sum_before", "total_change_amount", "new_contract_sum"):
        if name not in derived:
            continue
        dval, inputs = derived[name]
        in_conf = [fields[i].confidence if i in fields else 0.8 for i in inputs if i == "line_items" or values.get(i) is not None]
        conf = round(0.85 * min(in_conf), 3) if in_conf else 0.5
        fields[name] = FieldResult(value=_jsonable(dval), confidence=conf, sources=["derived"], flags=["derived"],
                                   reasons=[f"computed from {', '.join(inputs)}; 0.85 x weakest input"])
        values[name] = dval
    fields = {n: fields[n] for n in SCALAR_FIELDS}

    # 6. score line items
    other_amounts = [i.values["amount"] for i in alt_items]
    line_results: list[LineItemResult] = []
    for idx, it in enumerate(items):
        g = None if doc.kind == "pdf_scanned" else ground(it.evidence, doc.text)
        agreement = None
        if both:
            agreement = "agree" if it.values["amount"] in other_amounts else ("single" if not other_amounts else "disagree")
        ifields: dict[str, FieldResult] = {}
        for f, kind in LINE_ITEM_FIELDS.items():
            if it.values[f] is None:
                ifields[f] = FieldResult(value=None, confidence=0.0, flags=["missing"])
                continue
            rel = [c for c in checks if idx in c.items and
                   (c.rule != "item_extension" or f in ("quantity", "unit_price", "amount")) and
                   (c.rule == "item_extension" or f == "amount")]
            sig = confidence.Signals(
                certainty=it.certainty, grounding=g, has_evidence=bool(it.evidence),
                value_in_evidence=value_in_evidence(it.raw.get(f), it.evidence, kind),
                agreement=agreement if f == "amount" else None,
                checks_passed=sum(c.passed for c in rel), checks_failed=sum(not c.passed for c in rel),
                flags=it.flags[f])
            conf, reasons = confidence.score(sig, doc.quality if doc.kind != "pdf_scanned" else 0.75)
            ifields[f] = FieldResult(value=_jsonable(it.values[f]), confidence=conf, sources=[it.source],
                                     evidence=it.evidence, flags=it.flags[f], reasons=reasons)
        item_conf = min(ifields["amount"].confidence, ifields["description"].confidence or ifields["amount"].confidence)
        line_results.append(LineItemResult(fields=ifields, confidence=item_conf, evidence=it.evidence))

    # 7. validation issues, review routing
    issues = [ValidationIssue(rule=c.rule, severity=c.severity, message=c.message, fields=c.fields)
              for c in checks if not c.passed]
    for req in REQUIRED_FIELDS:
        if fields[req].value is None:
            issues.append(ValidationIssue(rule="required_field_missing", severity="error",
                                          message=f"{req} not found", fields=[req]))

    change_order = None
    try:
        co_values = {f: values[f] for f in SCALAR_FIELDS if values.get(f) is not None}
        co_values["line_items"] = [
            {"description": it.values["description"] or "(no description)", **{k: it.values[k] for k in ("quantity", "unit", "unit_price", "amount")}}
            for it in items]
        change_order = ChangeOrder(**co_values).model_dump(mode="json")
    except ValidationError as e:
        if not any(i.rule == "required_field_missing" for i in issues):
            issues.append(ValidationIssue(rule="schema", severity="error", message=str(e).splitlines()[0]))

    needs_review = sorted({n for n, fr in fields.items() if fr.value is not None and fr.confidence < REVIEW_THRESHOLD}
                          | {f for i in issues if i.severity == "error" for f in i.fields}
                          | {f"line_items[{k}]" for k, li in enumerate(line_results) if li.confidence < REVIEW_THRESHOLD})

    present = [(n, fr) for n, fr in fields.items() if fr.value is not None]
    if present:
        weights = [2.0 if SCALAR_FIELDS[n] == "money" else 1.0 for n, _ in present]
        overall = sum(w * fr.confidence for w, (_, fr) in zip(weights, present)) / sum(weights)
        overall = min(overall, min(fields[r].confidence for r in REQUIRED_FIELDS) + 0.1)
    else:
        overall = 0.0

    errors = [i for i in issues if i.severity == "error"]
    if change_order is None:
        status = "failed"
    elif errors or doc.kind == "pdf_scanned" or \
            any(fields[r].confidence < REVIEW_THRESHOLD for r in REQUIRED_FIELDS) or \
            any(fr.confidence < REVIEW_THRESHOLD for n, fr in present if SCALAR_FIELDS[n] == "money") or \
            any(fr.confidence < LOW_CONFIDENCE_BLOCK for _, fr in present) or \
            any(li.confidence < REVIEW_THRESHOLD for li in line_results):
        status = "needs_review"
    else:
        status = "auto_accept"

    meta["elapsed_s"] = round(time.time() - t0, 3)
    meta["checks_passed"] = [c.rule for c in checks if c.passed]
    return ExtractionResult(document=doc.path.name, status=status, overall_confidence=round(overall, 3),
                            fields=fields, line_items=line_results, validation=issues,
                            needs_review=needs_review, change_order=change_order, meta=meta)
