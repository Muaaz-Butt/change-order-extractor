"""Deterministic, label-driven extractor.

It is deliberately conservative: it only fires on recognisable labels and table
rows, and it reports the exact line it read. Its job is to be an *independent*
second opinion to the LLM (agreement between two unrelated methods is the
strongest confidence signal we have) and a working offline fallback.
"""

from __future__ import annotations

import re

from ..ingest import Document
from .base import Candidate, ExtractorOutput, RawLineItem

SOURCE = "rules"

MONEY = r"\(?-?\s*\$?\s*[\dOolIS][\dOolIS,]*\.[\dOolIS]{2}\)?|\(?-?\s*\$\s*[\d,]+\)?"
COL_GAP = r"(?=\s{3,}|\s*\n|\s*$)"

# field -> list of (label regex, certainty). First matching label wins, so order
# specific labels before generic ones.
LABELS: dict[str, list[tuple[str, float]]] = {
    "change_order_number": [
        (r"change\s*order\s*(?:no\.?|number|#)", 0.9),
        (r"\b(?:P?CO|COR)\s*(?:no\.?|#|number)", 0.8),
        (r"change\s*order", 0.6),
        (r"\bCO(?=\s*[-#]?\s*\d)", 0.55),
    ],
    "project_number": [(r"(?:project|job|contract)\s*(?:no\.?|number|#)", 0.85)],
    "project_name": [(r"project\s*name", 0.9), (r"project(?!\s*(?:no\.?|number|#|manager))", 0.75), (r"\bre", 0.4)],
    "owner": [(r"\bowner(?!'s)(?:\s*name)?", 0.85), (r"\bclient", 0.7)],
    "contractor": [(r"(?:general\s+)?contractor(?:\s*name)?", 0.85), (r"\bfrom", 0.4)],
    "date_issued": [(r"date\s*(?:issued|of\s*issuance)", 0.9), (r"\bissued(?:\s*on)?", 0.75), (r"\bdate", 0.7)],
    "description": [(r"description\s*of\s*(?:the\s*)?(?:change|work)", 0.85), (r"scope\s*of\s*change", 0.8), (r"\bdescription", 0.65)],
    "reason": [(r"reason\s*for\s*change", 0.85), (r"\breason", 0.75), (r"justification|cause\s*of\s*change", 0.7)],
    "status": [(r"\bstatus", 0.85)],
    "subtotal": [(r"sub-?\s*total|total\s*direct\s*costs?", 0.85)],
    "markup": [(r"overhead\s*(?:and|&)\s*profit|\bO\s*&\s*P\b|mark-?up|contractor'?s?\s*fee", 0.8)],
    "tax": [(r"(?:sales\s*)?tax", 0.8)],
    "total_change_amount": [
        (r"total\s*(?:amount\s*)?(?:of\s*)?(?:this\s*)?change\s*order(?:\s*amount)?|change\s*order\s*total|total\s*change\s*(?:amount)?|amount\s*of\s*this\s*change\s*order", 0.9),
        (r"(?<!sub)(?<!sub-)\btotal(?:\s*cost)?(?!\s*direct)", 0.55),
    ],
    "original_contract_sum": [(r"original\s*contract\s*(?:sum|amount|value|price)", 0.9)],
    "prior_change_orders_total": [(r"(?:net\s*change\s*by\s*)?previous(?:ly)?\s*(?:authorized|approved)?\s*change\s*orders|prior\s*change\s*orders", 0.85)],
    "contract_sum_before": [(r"contract\s*(?:sum|amount)\s*prior\s*to\s*this\s*change\s*order|current\s*contract\s*(?:sum|amount)", 0.85)],
    "new_contract_sum": [(r"(?:new|revised)\s*contract\s*(?:sum|amount|value)(?:\s*including\s*this\s*change\s*order)?|contract\s*sum\s*including\s*this\s*change\s*order", 0.9)],
    "schedule_impact_days": [(r"schedule\s*impact|time\s*extension|contract\s*time(?:\s*adjustment)?|days\s*added", 0.75)],
    "new_completion_date": [(r"(?:new|revised)\s*(?:substantial\s*)?completion\s*date|date\s*of\s*substantial\s*completion\s*(?:as\s*of\s*the\s*date\s*of\s*this\s*change\s*order)?", 0.85)],
}

MONEY_FIELDS = {"subtotal", "markup", "tax", "total_change_amount", "original_contract_sum",
                "prior_change_orders_total", "contract_sum_before", "new_contract_sum"}
MULTILINE_FIELDS = {"description", "reason"}

SUMMARY_WORDS = re.compile(
    r"sub-?\s*total|\btotal\b|tax|overhead|profit|mark-?up|\bfee\b|contract\s*(?:sum|amount)|original|previous|prior|bond|insurance\s*\(|amount\s*of\s*this",
    re.I)


def _line_of(text: str, pos: int) -> str:
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    return text[start: end if end != -1 else len(text)].strip()


def _line_bounds(text: str, pos: int) -> tuple[int, int]:
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    return start, (len(text) if end == -1 else end)


def _cells(line: str) -> list[str]:
    return [c for c in re.split(r"\s{3,}", line.strip()) if c]


EXTRA_LABELS = r"architect|engineer|phone|tel|fax|email|e-mail|address|attn|to|from|cc|subject|signed|by|item|qty|unit|amount|rate"
ANY_LABEL = "|".join([l for labels in LABELS.values() for l, _ in labels] + [EXTRA_LABELS])
# "... Phase 2 Project #: MSL-02" -- a second known "Label:" on the same line ends the value.
INLINE_LABEL = re.compile(rf"(?i)\s+(?:{ANY_LABEL})(?![A-Za-z])[ \t]*[#.]*[ \t]*:")
HEADER_CELL = re.compile(rf"(?i)(?:{ANY_LABEL})(?![A-Za-z])[\s:#.]*")


def _value_after_label(search: str, text: str, label: str, field: str) -> tuple[str, str] | None:
    """Find ``label`` in ``search`` and return (value, evidence) sliced from ``text``.

    ``search`` is ``text`` with OCR letter/digit swaps undone (same length), so
    labels like "0wner" still match while values and evidence stay verbatim.
    """
    pat = re.compile(rf"(?im)(?<![A-Za-z])(?:{label})(?![A-Za-z])[ \t]*[:#.\-–]*[ \t]*")
    for m in pat.finditer(search):
        ls, le = _line_bounds(search, m.start())
        evidence = text[ls:le].strip()
        next_line = ""
        if le < len(text):
            ns, ne = _line_bounds(text, le + 1)
            next_line = text[ns:ne]

        # Layout 1: a row of column headers with the values on the next line.
        cells = _cells(search[ls:le])
        k = next((i for i, c in enumerate(cells) if re.fullmatch(rf"(?i)(?:{label})[\s:#.]*", c)), None)
        if k is not None and len(cells) >= 2 and all(HEADER_CELL.fullmatch(c) for c in cells):
            ncells = _cells(next_line)
            if len(ncells) == len(cells) and (field not in MONEY_FIELDS or re.search(MONEY, ncells[k])):
                return ncells[k], f"{evidence}\n{next_line.strip()}"
            continue

        base = m.end()
        rest = search[base:]
        if field in MONEY_FIELDS:
            vm = re.match(rf"[^\n$]{{0,40}}?({MONEY})(?![\d%])", rest) or re.match(rf"\s*\n\s*({MONEY})(?![\d%])", rest)
            if not vm:
                continue
            val = text[base + vm.start(1): base + vm.end(1)].strip()
            if val.startswith("(") and re.match(r"[ \t]*[A-Za-z]", text[base + vm.end(1):le]):
                # "markup ($165.50) so the total..." is a parenthetical aside, not an accounting credit.
                val = val.strip("()")
            return val, evidence

        # Layout 2: "Label: value" on one line, value ends at a column gap or another label.
        vm = re.match(rf"([^\n]*?){COL_GAP}", rest)
        val = text[base: base + vm.end(1)].strip() if vm else ""
        cut = INLINE_LABEL.search(val)
        if cut:
            val = val[:cut.start()].strip()
        if field in MULTILINE_FIELDS:
            # Wrapped continuation lines, until a blank line or another "Label:".
            for line in text[le + 1:].split("\n")[:5]:
                if not line.strip() or re.match(r"\s*[A-Z][A-Za-z ]{2,30}:", line):
                    break
                val = (val + " " + line.strip()).strip()
                evidence = (evidence + "\n" + line.strip())
        # Layout 3: label alone on its line, value on the next.
        if not val:
            ncells = _cells(next_line)
            if not ncells:
                continue
            val = ncells[0]
            evidence = f"{evidence}\n{next_line.strip()}"
        if len(val) < 2 and not (field == "change_order_number" and val.isdigit()):
            continue
        return val, evidence
    return None


def _sentence_patterns(text: str, out: dict[str, Candidate]) -> None:
    """AIA-style prose: 'The Contract Sum will be increased by ... $12,450.00'."""
    m = re.search(rf"contract\s+(?:sum|amount|price)\s+(?:will\s+be|is|shall\s+be)\s+(increased|decreased)\b[^$\d]{{0,80}}({MONEY})",
                  text, re.I | re.S)
    if m and "total_change_amount" not in out:
        raw = m.group(2) if m.group(1).lower() == "increased" else "-" + m.group(2).replace("-", "")
        out["total_change_amount"] = Candidate(raw, re.sub(r"\s+", " ", m.group(0)), 0.85, SOURCE)
    m = re.search(r"contract\s+time\s+(?:will\s+be|is|shall\s+be)\s+(increased|decreased|unchanged)(?:[^.\d]{0,60}?(\(?\d+\)?\s*(?:calendar\s+|working\s+)?(?:days?|weeks?)))?",
                  text, re.I | re.S)
    if m and "schedule_impact_days" not in out:
        if m.group(1).lower() == "unchanged":
            raw = "0"
        elif m.group(2):
            raw = ("-" if m.group(1).lower() == "decreased" else "") + m.group(2).strip("() ")
        else:
            raw = None
        if raw is not None:
            out["schedule_impact_days"] = Candidate(raw, re.sub(r"\s+", " ", m.group(0)), 0.85, SOURCE)
    m = re.search(r"(?:add(?:s|ing)?|extend(?:s|ed|ing)?(?:\s+the\s+schedule)?(?:\s+by)?)\s+(\d+|[a-z]+)\s+(calendar\s+|working\s+)?(days?|weeks?)", text, re.I)
    if m and "schedule_impact_days" not in out:
        out["schedule_impact_days"] = Candidate(m.group(0), m.group(0), 0.6, SOURCE)


def _status(search: str, text: str, out: dict[str, Candidate]) -> None:
    if "status" in out:
        return
    m = (re.search(r"(?i)\b(?:awaiting|pending)\b[^.\n]{0,40}\b(?:approval|sign-?off|signature)", search)
         or re.search(r"\b(APPROVED|REJECTED|PENDING(?:\s+APPROVAL)?|FOR\s+REVIEW|DRAFT)\b", search))
    if m:  # slice from the original text so the quote stays verbatim
        out["status"] = Candidate(text[m.start():m.end()], _line_of(text, m.start()), 0.6, SOURCE)


ROW_FULL = re.compile(
    rf"^\s*(?:(?:\d+|[A-Z])[.)]\s+|\d+\s{{2,}})?(?P<desc>[A-Za-z0-9][^\n]*?)\s+(?P<qty>[\d,]*\.?\d+)\s+(?P<unit>[A-Za-z/.]{{1,8}})\s+(?P<price>{MONEY})\s+(?P<amount>{MONEY})\s*$")
ROW_LUMP = re.compile(
    rf"^\s*(?:(?:item\s*)?(?:\d+|[A-Z])[.):]?\s+|[-*•]\s+)?(?P<desc>[A-Za-z][^\n]*?)(?:\s{{2,}}|\s*\.{{3,}}\s*|\s+-+\s+|:\s+)(?P<amount>{MONEY})\s*$")
ROW_AT = re.compile(
    rf"(?P<qty>\d+(?:\.\d+)?)\s*(?P<unit>[A-Za-z]{{0,6}}\.?)\s+(?P<desc>[^@\n]+?)\s*@\s*(?P<price>\$?\s*[\d,]+(?:\.\d{{2}})?)\s*(?:ea\.?|each|/\s*\w+)?\s*=\s*(?P<amount>\$?\s*[\d,]+(?:\.\d{{2}})?)", re.I)


def _line_items(text: str) -> list[RawLineItem]:
    lines = text.split("\n")
    header = next((i for i, l in enumerate(lines)
                   if re.search(r"description|item", l, re.I) and re.search(r"amount|cost|total|price", l, re.I)), None)
    items: list[RawLineItem] = []
    in_table = header is not None
    for i, line in enumerate(lines):
        if header is not None and i <= header:
            continue
        m = ROW_AT.search(line)
        if m:
            items.append(RawLineItem({"description": m["desc"], "quantity": m["qty"], "unit": m["unit"] or None,
                                      "unit_price": m["price"], "amount": m["amount"]}, line.strip(), 0.7, SOURCE))
            continue
        if not in_table:
            continue
        if re.search(r"sub-?\s*total|^\s*total\b", line, re.I):
            break  # end of the item table
        m = ROW_FULL.match(line)
        if m and not SUMMARY_WORDS.search(m["desc"]):
            items.append(RawLineItem({"description": m["desc"], "quantity": m["qty"], "unit": m["unit"],
                                      "unit_price": m["price"], "amount": m["amount"]}, line.strip(), 0.8, SOURCE))
            continue
        m = ROW_LUMP.match(line)
        if m and not SUMMARY_WORDS.search(m["desc"]):
            items.append(RawLineItem({"description": m["desc"].rstrip(" .:-"), "quantity": None, "unit": None,
                                      "unit_price": None, "amount": m["amount"]}, line.strip(), 0.65, SOURCE))
    return items


def _ocr_label_text(text: str) -> str:
    """Undo digit-for-letter OCR swaps inside words ("0wner", "C0NTRACT") for label matching only."""
    return re.sub(r"(?<=[A-Za-z])0|0(?=[A-Za-z]{2})", "o", text)


def extract(doc: Document) -> ExtractorOutput:
    text = doc.text
    search = _ocr_label_text(text)
    out: dict[str, Candidate] = {}
    m = re.search(r"(?i)\bno\s+(?:schedule|time)\s+impact|no\s+change\s+(?:in|to)\s+(?:the\s+)?contract\s+time", search)
    if m:
        out["schedule_impact_days"] = Candidate("no change", _line_of(text, m.start()), 0.75, SOURCE)
    for fname, labels in LABELS.items():
        if fname in out:
            continue
        for label, certainty in labels:
            hit = _value_after_label(search, text, label, fname)
            if hit:
                val, ev = hit
                if fname == "change_order_number":
                    idm = re.search(r"[A-Z]*[-\s]?\d[\w\-./]*", val, re.I)
                    if not idm:
                        continue
                    val = idm.group(0)
                out[fname] = Candidate(val, ev, certainty, SOURCE)
                break
    _sentence_patterns(text, out)
    _status(search, text, out)
    if "reason" not in out and "description" in out:
        # No explicit reason; let the keyword classifier read the description's paragraph.
        ev = out["description"].evidence or ""
        pos = text.find(ev.split("\n")[0])
        para = re.split(r"\n\s*\n", text[pos:], maxsplit=1)[0] if pos >= 0 else out["description"].raw
        out["reason"] = Candidate(para, para.strip(), 0.45, SOURCE)
    elif "reason" not in out and len(text) < 600:
        out["reason"] = Candidate(text, None, 0.35, SOURCE)
    return ExtractorOutput(source=SOURCE, fields=out, line_items=_line_items(text))
