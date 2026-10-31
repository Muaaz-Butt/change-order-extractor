from decimal import Decimal as D

from co_extract.grounding import ground, value_in_evidence
from co_extract.validate import run_checks


def _by_rule(checks):
    return {c.rule: c.passed for c in checks}


def test_consistent_change_order_passes_all_arithmetic():
    v = {"subtotal": D("100"), "markup": D("10"), "total_change_amount": D("110"),
         "original_contract_sum": D("1000"), "prior_change_orders_total": D("50"),
         "contract_sum_before": D("1050"), "new_contract_sum": D("1160")}
    items = [{"quantity": D("2"), "unit_price": D("25"), "amount": D("50")}, {"amount": D("50")}]
    r = _by_rule(run_checks(v, items))
    assert r.items() >= {"item_extension": True, "items_sum_to_subtotal": True, "subtotal_plus_markup_tax_equals_total": True,
                 "original_plus_prior_equals_before": True, "before_plus_change_equals_new": True}.items()


def test_transposed_subtotal_is_caught():
    r = _by_rule(run_checks({"subtotal": D("8540"), "markup": D("854"), "total_change_amount": D("9394")},
                            [{"amount": D("3920")}, {"amount": D("3680")}, {"amount": D("850")}]))
    assert r["items_sum_to_subtotal"] is False
    assert r["subtotal_plus_markup_tax_equals_total"] is True


def test_credit_line_extension_uses_magnitudes():
    r = _by_rule(run_checks({}, [{"quantity": D("1200"), "unit_price": D("9.50"), "amount": D("-11400")}]))
    assert r["item_extension"] is True


def test_grounding():
    text = "Total Change Order Amount     $5,922.50\nOther line"
    assert ground("Total Change Order Amount $5,922.50", text) == 1.0
    assert ground("Grand total due: $9,999.00", text) < 0.7
    assert value_in_evidence("$5,922.50", "Total Change Order Amount $5,922.50", "money")
    assert not value_in_evidence("$9,999.00", "Total Change Order Amount $5,922.50", "money")
