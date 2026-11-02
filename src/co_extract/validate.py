"""Accounting and sanity checks over the reconciled values.

Change orders are self-checking documents: line items roll up to a subtotal,
markups roll up to a total, and the total moves the contract sum. Each check
that passes is independent evidence the participating fields were read
correctly; each that fails points at exactly which fields to distrust.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass
class Check:
    rule: str
    passed: bool
    fields: list[str]
    message: str
    severity: str = "error"  # failing arithmetic is an error; sanity checks are warnings
    arithmetic: bool = True
    items: list[int] = field(default_factory=list)  # line-item indices involved


def close(a: Decimal, b: Decimal) -> bool:
    """Return True if two amounts are equal within rounding tolerance."""
    tol = max(Decimal("0.02"), abs(b) * Decimal("0.001"))
    return abs(a - b) <= tol


def run_checks(v: dict, items: list[dict], today: date | None = None) -> list[Check]:
    """``v`` maps field -> normalised value (or None). ``items`` are dicts with Decimal amounts."""
    today = today or date.today()
    checks: list[Check] = []
    g = v.get

    for i, it in enumerate(items):
        if it.get("quantity") is not None and it.get("unit_price") is not None and it.get("amount") is not None:
            ext = (it["quantity"] * it["unit_price"]).quantize(Decimal("0.01"))
            ok = close(abs(ext), abs(it["amount"]))  # credits: positive qty x price, negative amount
            checks.append(Check("item_extension", ok, [], f"item {i + 1}: {it['quantity']} x {it['unit_price']} = {ext} vs amount {it['amount']}",
                                items=[i]))

    item_sum = sum((it["amount"] for it in items if it.get("amount") is not None), Decimal("0")) if items else None
    if item_sum is not None:
        if g("subtotal") is not None:
            checks.append(Check("items_sum_to_subtotal", close(item_sum, g("subtotal")), ["subtotal"],
                                f"line items sum {item_sum} vs subtotal {g('subtotal')}", items=list(range(len(items)))))
        elif g("total_change_amount") is not None:
            calc = item_sum + (g("markup") or 0) + (g("tax") or 0)
            parts = ["total_change_amount"] + [f for f in ("markup", "tax") if g(f) is not None]
            checks.append(Check("items_plus_markup_tax_equal_total", close(calc, g("total_change_amount")), parts,
                                f"line items + markup + tax = {calc} vs total {g('total_change_amount')}", items=list(range(len(items)))))

    if g("subtotal") is not None and g("total_change_amount") is not None and (g("markup") is not None or g("tax") is not None):
        calc = g("subtotal") + (g("markup") or 0) + (g("tax") or 0)
        parts = ["subtotal", "total_change_amount"] + [f for f in ("markup", "tax") if g(f) is not None]
        checks.append(Check("subtotal_plus_markup_tax_equals_total", close(calc, g("total_change_amount")), parts,
                            f"subtotal + markup + tax = {calc} vs total {g('total_change_amount')}"))

    if None not in (g("original_contract_sum"), g("prior_change_orders_total"), g("contract_sum_before")):
        calc = g("original_contract_sum") + g("prior_change_orders_total")
        checks.append(Check("original_plus_prior_equals_before", close(calc, g("contract_sum_before")),
                            ["original_contract_sum", "prior_change_orders_total", "contract_sum_before"],
                            f"original + prior = {calc} vs contract sum before {g('contract_sum_before')}"))

    if None not in (g("contract_sum_before"), g("total_change_amount"), g("new_contract_sum")):
        calc = g("contract_sum_before") + g("total_change_amount")
        checks.append(Check("before_plus_change_equals_new", close(calc, g("new_contract_sum")),
                            ["contract_sum_before", "total_change_amount", "new_contract_sum"],
                            f"before + change = {calc} vs new contract sum {g('new_contract_sum')}"))
    elif None not in (g("original_contract_sum"), g("prior_change_orders_total"), g("total_change_amount"), g("new_contract_sum")):
        calc = g("original_contract_sum") + g("prior_change_orders_total") + g("total_change_amount")
        checks.append(Check("original_plus_prior_plus_change_equals_new", close(calc, g("new_contract_sum")),
                            ["original_contract_sum", "prior_change_orders_total", "total_change_amount", "new_contract_sum"],
                            f"original + prior + change = {calc} vs new contract sum {g('new_contract_sum')}"))

    # --- sanity checks (warnings, not arithmetic) ---
    d = g("date_issued")
    if d is not None:
        ok = date(1990, 1, 1) <= d <= date(today.year + 1, today.month, min(today.day, 28))
        checks.append(Check("date_issued_plausible", ok, ["date_issued"], f"date issued {d}", "warning", False))
    if d is not None and g("new_completion_date") is not None:
        checks.append(Check("completion_after_issue", g("new_completion_date") >= d, ["new_completion_date", "date_issued"],
                            f"completion {g('new_completion_date')} vs issued {d}", "warning", False))
    if g("schedule_impact_days") is not None:
        checks.append(Check("schedule_days_plausible", abs(g("schedule_impact_days")) <= 730, ["schedule_impact_days"],
                            f"schedule impact {g('schedule_impact_days')} days", "warning", False))
    t = g("total_change_amount")
    if t is not None and g("contract_sum_before") not in (None, 0):
        ratio = abs(t) / abs(g("contract_sum_before"))
        checks.append(Check("change_size_plausible", ratio <= Decimal("0.5"), ["total_change_amount"],
                            f"change is {ratio:.0%} of contract sum", "warning", False))
    return checks


def arithmetic_score(checks: list[Check]) -> int:
    """Score a set of checks: +1 per passing arithmetic check, -1 per failure."""
    return sum(1 if c.passed else -1 for c in checks if c.arithmetic)
