from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Candidate:
    """One extractor's raw guess for one field. Values stay strings until normalisation."""

    raw: str | None
    evidence: str | None  # verbatim snippet the value was read from
    certainty: float  # the extractor's own belief, 0..1 (not yet calibrated)
    source: str  # "rules" | "llm"


@dataclass
class RawLineItem:
    fields: dict[str, str | None]
    evidence: str | None
    certainty: float
    source: str


@dataclass
class ExtractorOutput:
    source: str
    fields: dict[str, Candidate] = field(default_factory=dict)
    line_items: list[RawLineItem] = field(default_factory=list)
    error: str | None = None
    usage: dict | None = None
