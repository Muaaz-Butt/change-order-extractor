"""Gemini-based extractor. Same prompt, JSON schema and output contract as the Claude extractor.

Both LLM extractors report as source ``"llm"``, so reconciliation, grounding and
confidence scoring treat them identically.
"""

from __future__ import annotations

import json
import os
import time

from ..ingest import Document
from .base import ExtractorOutput
from .llm import OUTPUT_SCHEMA, SOURCE, SYSTEM_PROMPT, parse_output

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
# Tried in order when the requested model is overloaded (503) or rate-limited (429).
FALLBACK_MODELS = [m.strip() for m in os.environ.get("GEMINI_FALLBACK_MODELS", "gemini-3.7-flash,gemini-3.6-flash").split(",") if m.strip()]
TRANSIENT_CODES = {429, 500, 502, 503, 504}
ATTEMPTS_PER_MODEL = 3
BACKOFF_S = (5, 15)  # sleep before attempt 2 and 3
DECLINED = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION"}


def api_key() -> str | None:
    """Return the Gemini API key from the environment, if one is set."""
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def _contents(doc: Document, types) -> list:
    """Build the Gemini request content: the PDF bytes for scans, otherwise the document text."""
    if doc.kind == "pdf_scanned" and doc.pdf_bytes:
        return [types.Part.from_bytes(data=doc.pdf_bytes, mime_type="application/pdf"),
                "Extract the change order in the attached scanned PDF."]
    return [f"<document name=\"{doc.path.name}\">\n{doc.text}\n</document>\n\nExtract the change order above."]


def extract(doc: Document, client=None, model: str = DEFAULT_MODEL) -> ExtractorOutput:
    """Extract change-order fields with Gemini, retrying overloaded models and falling back to others."""
    from google import genai
    from google.genai import errors, types

    client = client or genai.Client(api_key=api_key())
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
        response_json_schema=OUTPUT_SCHEMA,
        temperature=0,
    )
    response, errors_seen = None, []
    for m in dict.fromkeys([model, *FALLBACK_MODELS]):  # requested model first, no duplicates
        for attempt in range(ATTEMPTS_PER_MODEL):
            if attempt:
                time.sleep(BACKOFF_S[attempt - 1])
            try:
                response = client.models.generate_content(model=m, contents=_contents(doc, types), config=config)
                model = m
                break
            except errors.APIError as e:
                errors_seen.append(f"{m}: {e.code} {(e.message or '')[:80]}")
                if e.code not in TRANSIENT_CODES:
                    return ExtractorOutput(source=SOURCE, error=f"Gemini API error {e.code}: {e.message}")
            except Exception as e:  # dropped connections surface as transport exceptions; retry them too
                errors_seen.append(f"{m}: {type(e).__name__}")
        if response is not None:
            break
    if response is None:
        return ExtractorOutput(source=SOURCE, error="Gemini unavailable after retries: " + "; ".join(errors_seen[-3:]))

    feedback = getattr(response, "prompt_feedback", None)
    if feedback is not None and feedback.block_reason:
        return ExtractorOutput(source=SOURCE, error=f"Gemini blocked the prompt: {feedback.block_reason}")
    candidate = (response.candidates or [None])[0]
    reason = getattr(getattr(candidate, "finish_reason", None), "name", None)
    if reason == "MAX_TOKENS":
        return ExtractorOutput(source=SOURCE, error="output truncated (max_tokens)")
    if reason in DECLINED:
        return ExtractorOutput(source=SOURCE, error=f"model declined the request ({reason})")
    if not response.text:
        return ExtractorOutput(source=SOURCE, error="empty response from Gemini")
    try:
        data = json.loads(response.text)
    except json.JSONDecodeError as e:
        return ExtractorOutput(source=SOURCE, error=f"Gemini returned invalid JSON: {e}")
    meta = response.usage_metadata
    usage = {"provider": "gemini", "model": response.model_version or model, "retries": len(errors_seen),
             "input_tokens": getattr(meta, "prompt_token_count", None),
             "output_tokens": getattr(meta, "candidates_token_count", None)}
    return parse_output(data, usage)
