import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


class FakeClient:
    """Stands in for anthropic.Anthropic(); returns a canned structured-output response."""

    def __init__(self, payload=None, stop_reason="end_turn", raises=None):
        self.payload, self.stop_reason, self.raises = payload, stop_reason, raises
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
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
    return SAMPLES
