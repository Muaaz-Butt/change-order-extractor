import anthropic
import httpx2

from co_extract import run
from co_extract.extractors.llm import OUTPUT_SCHEMA

from .conftest import FakeClient, llm_payload


def test_formal_pdf_offline_is_auto_accepted(samples):
    """A clean formal PDF is auto-accepted using rules only."""
    res = run(samples / "co_001_formal.pdf", use_llm=False)
    assert res.status == "auto_accept"
    assert res.fields["total_change_amount"].value == 5922.50
    assert res.fields["new_contract_sum"].value == 4982322.50
    assert len(res.line_items) == 4
    assert res.change_order["change_order_number"] == "007"


def test_internally_inconsistent_document_needs_review(samples):
    """A document whose numbers don't add up is sent to review."""
    res = run(samples / "co_005_inconsistent.txt", use_llm=False)
    assert res.status == "needs_review"
    assert any(i.rule == "items_sum_to_subtotal" for i in res.validation)
    assert "subtotal" in res.needs_review
    assert "failed_validation" in res.fields["subtotal"].flags


def test_scanned_pdf_without_llm_fails_cleanly(samples):
    """A scan with no LLM available fails cleanly instead of guessing."""
    res = run(samples / "co_008_scanned.pdf", use_llm=False)
    assert res.status == "failed"
    assert res.meta["input_kind"] == "pdf_scanned"
    assert res.change_order is None


def test_llm_agreement_raises_confidence(samples):
    """Claude agreeing with the rules extractor raises confidence."""
    path = samples / "co_006_twocolumn.pdf"
    offline = run(path, use_llm=False)
    client = FakeClient(llm_payload({
        "change_order_number": ("CO 9", "CO 9   10/02/2025"),
        "total_change_amount": ("$34,670.00", "Total   $34,670.00"),
        "project_name": ("Westfield Retail Pad Site", "Westfield Retail Pad Site   IW-7740"),
    }))
    online = run(path, client=client)
    assert online.meta["extractors"] == ["rules", "llm"]
    for f in ("total_change_amount", "project_name"):
        assert online.fields[f].sources == ["rules", "llm"]
        assert online.fields[f].confidence > offline.fields[f].confidence


def test_request_uses_structured_output_and_fallback(samples):
    """The Claude request uses structured output and server-side fallback."""
    client = FakeClient(llm_payload({}))
    run(samples / "co_002_email.txt", client=client)
    call = client.calls[0]
    assert call["output_config"]["format"] == {"type": "json_schema", "schema": OUTPUT_SCHEMA}
    assert call["fallbacks"] == "default"
    assert "<document" in call["messages"][0]["content"][0]["text"]


def test_scanned_pdf_is_sent_as_document_block(samples):
    """Scanned PDFs are sent to Claude as a document block."""
    client = FakeClient(llm_payload({"change_order_number": ("3", "Change Order No.: 3"),
                                     "total_change_amount": ("$1,310.00", "Total Change Order Amount $1,310.00")}))
    res = run(samples / "co_008_scanned.pdf", client=client)
    assert client.calls[0]["messages"][0]["content"][0]["type"] == "document"
    assert res.fields["total_change_amount"].value == 1310.0
    # Quotes from a scan cannot be verified against a text layer, so confidence stays moderate.
    assert res.fields["total_change_amount"].confidence < 0.8
    assert res.status == "needs_review"


def test_hallucinated_evidence_is_penalised(samples):
    """A value whose quote isn't in the document gets low confidence."""
    client = FakeClient(llm_payload({"owner": ("Harbor View Development LLC", "Owner: Harbor View Development LLC")}))
    res = run(samples / "co_002_email.txt", client=client)
    owner = res.fields["owner"]
    assert owner.value == "Harbor View Development LLC"
    assert "evidence_not_found" in owner.flags
    assert owner.confidence < 0.3
    assert "owner" in res.needs_review


def test_disagreement_resolved_by_arithmetic(samples):
    # LLM misreads the subtotal; the rules value is the one that makes subtotal + O&P = total.
    """When extractors disagree, the value that makes the math work wins."""
    client = FakeClient(llm_payload({"subtotal": ("$5,510.00", "Subtotal   5,150.00")}))
    res = run(samples / "co_001_formal.pdf", client=client)
    sub = res.fields["subtotal"]
    assert sub.value == 5150.0
    assert "resolved_by_arithmetic" in sub.flags


def test_llm_failure_falls_back_to_rules(samples):
    """A Claude connection error falls back to rules only."""
    err = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    res = run(samples / "co_001_formal.pdf", client=FakeClient(raises=err))
    assert res.meta["extractors"] == ["rules"]
    assert "connection error" in res.meta["llm_error"]
    assert res.fields["total_change_amount"].value == 5922.50


def test_refusal_is_handled(samples):
    """A Claude refusal is reported as an error, not a crash."""
    res = run(samples / "co_001_formal.pdf", client=FakeClient(stop_reason="refusal"))
    assert res.meta["llm_error"] == "model declined the request"
