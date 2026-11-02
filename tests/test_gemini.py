from google.genai import errors

from co_extract import run
from co_extract.extractors.llm import OUTPUT_SCHEMA, SYSTEM_PROMPT
from co_extract.pipeline import pick_provider

from .conftest import FakeGeminiClient, llm_payload

TOTAL = {"total_change_amount": ("$34,670.00", "Total   $34,670.00"),
         "project_name": ("Westfield Retail Pad Site", "Westfield Retail Pad Site   IW-7740")}


def test_auto_provider_prefers_claude_then_gemini(monkeypatch):
    """Auto mode picks Claude if its key is set, else Gemini, else rules only."""
    assert pick_provider("auto", None, None) is None
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    assert pick_provider("auto", None, None) == "gemini"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "y")
    assert pick_provider("auto", None, None) == "claude"
    assert pick_provider("gemini", None, None) == "gemini"
    assert pick_provider("auto", False, None) is None


def test_gemini_request_uses_shared_prompt_and_schema(samples):
    """Gemini gets the same prompt and JSON schema as Claude."""
    client = FakeGeminiClient(llm_payload({}))
    run(samples / "co_002_email.txt", client=client, provider="gemini", model="gemini-test")
    call = client.calls[0]
    assert call["model"] == "gemini-test"
    assert call["config"].response_json_schema == OUTPUT_SCHEMA
    assert call["config"].system_instruction == SYSTEM_PROMPT
    assert call["config"].response_mime_type == "application/json"
    assert "<document" in call["contents"][0]


def test_gemini_agreement_raises_confidence(samples):
    """Gemini agreeing with the rules extractor raises confidence."""
    path = samples / "co_006_twocolumn.pdf"
    offline = run(path, use_llm=False)
    online = run(path, client=FakeGeminiClient(llm_payload(TOTAL)), provider="gemini")
    assert online.meta["llm_provider"] == "gemini"
    assert online.meta["llm_usage"]["provider"] == "gemini"
    assert online.fields["total_change_amount"].sources == ["rules", "llm"]
    assert online.fields["total_change_amount"].confidence > offline.fields["total_change_amount"].confidence


def test_gemini_reads_scanned_pdf_as_bytes(samples):
    """Scanned PDFs are sent to Gemini as raw PDF bytes and still need review."""
    client = FakeGeminiClient(llm_payload({"change_order_number": ("3", "Change Order No.: 3"),
                                           "total_change_amount": ("$1,310.00", "Total Change Order Amount $1,310.00")}))
    res = run(samples / "co_008_scanned.pdf", client=client, provider="gemini")
    part = client.calls[0]["contents"][0]
    assert part.inline_data.mime_type == "application/pdf"
    assert res.fields["total_change_amount"].value == 1310.0
    assert res.status == "needs_review"


def test_gemini_api_error_falls_back_to_rules(samples):
    """A non-retryable Gemini error is not retried and falls back to rules."""
    err = errors.ClientError(400, {"error": {"code": 400, "message": "bad request", "status": "INVALID_ARGUMENT"}})
    client = FakeGeminiClient(raises=err)
    res = run(samples / "co_001_formal.pdf", client=client, provider="gemini")
    assert len(client.calls) == 1  # non-transient errors are not retried
    assert res.meta["extractors"] == ["rules"]
    assert "400" in res.meta["llm_error"]
    assert res.fields["total_change_amount"].value == 5922.50


def test_gemini_safety_block_is_handled(samples):
    """Safety declines and blocked prompts are reported as errors, not crashes."""
    res = run(samples / "co_001_formal.pdf", client=FakeGeminiClient(llm_payload({}), finish_reason="SAFETY"),
              provider="gemini")
    assert "declined" in res.meta["llm_error"]
    res = run(samples / "co_001_formal.pdf", client=FakeGeminiClient(llm_payload({}), block_reason="OTHER"),
              provider="gemini")
    assert "blocked" in res.meta["llm_error"]


def test_overloaded_model_retries_then_falls_back(samples, monkeypatch):
    """An overloaded model is retried, then the next fallback model is used."""
    import co_extract.extractors.gemini as g
    monkeypatch.setattr(g.time, "sleep", lambda s: None)
    overloaded = errors.ServerError(503, {"error": {"code": 503, "message": "high demand", "status": "UNAVAILABLE"}})

    class Flaky(FakeGeminiClient):
        def _generate(self, **kwargs):
            """Fail with 503 on the primary model and answer normally on the others."""
            if kwargs["model"] == "gemini-3.8-flash":
                self.calls.append(kwargs)
                raise overloaded
            return super()._generate(**kwargs)

    client = Flaky(llm_payload(TOTAL))
    res = run(samples / "co_006_twocolumn.pdf", client=client, provider="gemini", model="gemini-3.8-flash")
    assert [c["model"] for c in client.calls] == ["gemini-3.8-flash"] * 3 + ["gemini-3.7-flash"]
    assert res.meta["llm_usage"]["model"] == "gemini-3.7-flash"
    assert res.meta["llm_usage"]["retries"] == 3
    assert "llm_error" not in res.meta
