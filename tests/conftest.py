import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


class FakeClient:
    """Stands in for anthropic.Anthropic(); returns a canned structured-output response."""

    def __init__(self, payload=None, stop_reason="end_turn", raises=None):
        """Set up the fake client with a canned payload or an error to raise."""
        self.payload, self.stop_reason, self.raises = payload, stop_reason, raises
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        """Record the request and return a fake Claude response."""
        self.calls.append(kwargs)
        if self.raises:
            raise self.raises
        text = json.dumps(self.payload) if self.payload is not None else ""
        return SimpleNamespace(
            stop_reason=self.stop_reason, model=kwargs["model"],
            content=[SimpleNamespace(type="text", text=text)] if self.stop_reason != "refusal" else [],
            usage=SimpleNamespace(input_tokens=1000, output_tokens=500))


def llm_payload(fields: dict, line_items=()):
    """Build an LLM response. ``fields`` maps name -> (value, evidence[, certainty])."""
    from co_extract.schema import SCALAR_FIELDS
    out = {}
    for f in SCALAR_FIELDS:
        v = fields.get(f)
        out[f] = ({"value": v[0], "evidence": v[1], "certainty": v[2] if len(v) > 2 else "high"}
                  if v else {"value": None, "evidence": None, "certainty": "high"})
    return {"fields": out, "line_items": list(line_items)}


@pytest.fixture
def samples():
    """Path to the sample documents directory."""
    return SAMPLES


@pytest.fixture(autouse=True)
def _no_real_keys(monkeypatch):
    """Tests never hit a real API, whatever keys the developer has exported."""
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)


class FakeGeminiClient:
    """Stands in for google.genai.Client(); returns a canned JSON response."""

    def __init__(self, payload=None, finish_reason="STOP", raises=None, block_reason=None):
        """Set up the fake client with a canned payload or an error to raise."""
        self.payload, self.finish_reason, self.raises, self.block_reason = payload, finish_reason, raises, block_reason
        self.calls = []
        self.models = SimpleNamespace(generate_content=self._generate)

    def _generate(self, **kwargs):
        """Record the request and return a fake Gemini response."""
        self.calls.append(kwargs)
        if self.raises:
            raise self.raises
        return SimpleNamespace(
            text=json.dumps(self.payload) if self.payload is not None else None,
            candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name=self.finish_reason))],
            prompt_feedback=SimpleNamespace(block_reason=self.block_reason) if self.block_reason else None,
            usage_metadata=SimpleNamespace(prompt_token_count=900, candidates_token_count=400),
            model_version=kwargs["model"])
