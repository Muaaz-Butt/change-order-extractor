"""Load a PDF or text file into a ``Document`` and estimate how trustworthy its text is.

Text quality matters because every downstream confidence is capped by it: a
perfect regex match against garbled OCR is still a guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

TEXT_SUFFIXES = {".txt", ".md", ".eml", ".text", ""}
MIN_CHARS_PER_PAGE = 40  # below this a PDF page is treated as image-only


@dataclass
class Document:
    path: Path
    text: str
    kind: str  # "text" | "pdf_text" | "pdf_scanned"
    pages: int = 1
    quality: float = 1.0  # 0..1 heuristic text quality
    pdf_bytes: bytes | None = None  # kept so the LLM can read scanned pages itself
    notes: list[str] = field(default_factory=list)


def text_quality(text: str) -> tuple[float, list[str]]:
    """Cheap signal of OCR damage: odd characters, digit/letter soup, broken words."""
    notes: list[str] = []
    stripped = re.sub(r"\s+", "", text)
    if len(stripped) < 20:
        return 0.0, ["almost_no_text"]
    odd = sum(1 for c in stripped if not (c.isalnum() or c in "$.,:;-/()#%&'\"@*+=_[]!?"))
    odd_ratio = odd / len(stripped)
    tokens = re.findall(r"\S+", text)
    # tokens mixing letters and digits like "1O,5OO" or "Arnount" style damage
    mixed = sum(1 for t in tokens if re.search(r"\d", t) and re.search(r"[OolIS]", t) and re.fullmatch(r"[\d$OolIS,.()\-]+", t))
    mixed_ratio = mixed / max(len(tokens), 1)
    score = 1.0 - min(1.0, odd_ratio * 8) * 0.5 - min(1.0, mixed_ratio * 15) * 0.5
    if odd_ratio > 0.02:
        notes.append("unusual_characters")
    if mixed_ratio > 0.01:
        notes.append("ocr_digit_letter_confusion")
    return round(max(0.0, min(1.0, score)), 3), notes


def load(path: str | Path) -> Document:
    """Load a PDF or text file into a Document with its text, kind and quality score."""
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        return _load_pdf(p)
    if p.suffix.lower() in TEXT_SUFFIXES:
        text = p.read_text(encoding="utf-8", errors="replace")
        q, notes = text_quality(text)
        return Document(path=p, text=text, kind="text", quality=q, notes=notes)
    raise ValueError(f"Unsupported file type: {p.suffix}")


def _load_pdf(p: Path) -> Document:
    """Extract the text layer of a PDF and detect scanned (image-only) PDFs."""
    import pdfplumber

    raw = p.read_bytes()
    page_texts: list[str] = []
    with pdfplumber.open(p) as pdf:
        n_pages = len(pdf.pages)
        for page in pdf.pages:
            # layout=True keeps column gaps so table rows stay on one line.
            page_texts.append(page.extract_text(layout=True) or "")
    text = "\n\f\n".join(t.rstrip() for t in page_texts)
    # Collapse the long runs of spaces layout mode produces, but keep >=2 as a column marker.
    text = re.sub(r"[ \t]{3,}", "   ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    sparse = sum(1 for t in page_texts if len(t.strip()) < MIN_CHARS_PER_PAGE)
    if n_pages and sparse == n_pages:
        return Document(path=p, text=text, kind="pdf_scanned", pages=n_pages, quality=0.0,
                        pdf_bytes=raw, notes=["no_text_layer: needs OCR or the LLM vision path"])
    q, notes = text_quality(text)
    if sparse:
        notes.append(f"{sparse}_of_{n_pages}_pages_without_text")
        q *= 1 - sparse / n_pages
    return Document(path=p, text=text, kind="pdf_text", pages=n_pages, quality=round(q, 3),
                    pdf_bytes=raw, notes=notes)
