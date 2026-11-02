"""Turn raw strings (from either extractor) into typed values.

Both extractors return *strings*; all parsing happens here so the rules path
and the LLM path are normalised identically and can be compared fairly.
Every parser returns ``(value, flags)``; flags record lossy repairs (e.g. an
OCR'd ``O`` read as ``0``) so the confidence scorer can discount them.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from .schema import Reason, Status

# Characters OCR commonly confuses with digits, only applied inside tokens
# that are already mostly numeric.
_OCR_DIGIT_MAP = str.maketrans({"O": "0", "o": "0", "D": "0", "l": "1", "I": "1", "|": "1",
                                "S": "5", "s": "5", "B": "8", "Z": "2"})


def _fix_ocr_digits(token: str) -> tuple[str, bool]:
    """Repair OCR look-alike characters (O->0, l->1, S->5, ...) in a numeric token."""
    stripped = re.sub(r"[\s$,.()\-+/]", "", token)
    if not stripped:
        return token, False
    digits = sum(c.isdigit() for c in stripped)
    # Only touch tokens made purely of digits and digit look-alikes, with at least one real digit.
    if digits == len(stripped) or digits == 0 or not all(c.isdigit() or c in "OoDlI|SsBZ" for c in stripped):
        return token, False
    return token.translate(_OCR_DIGIT_MAP), True


def parse_money(raw: str | None) -> tuple[Decimal | None, list[str]]:
    """Parse a money string (credits, OCR damage, EU formats) into a Decimal with flags."""
    if raw is None:
        return None, []
    s = str(raw).strip()
    if not s:
        return None, []
    flags: list[str] = []
    negative = False
    if re.search(r"\(\s*\$?\s*[\dOolIS,.\s]+\)", s) or re.search(r"\bCR\b|credit|deduct", s, re.I):
        negative = True
    if re.search(r"(^|[\s$])-\s*\$?\s*\d|^\$?\s*-", s) or "−" in s:
        negative = True
    m = re.search(r"\d[\dOolIS,.]*[\dOolIS]|[OolIS][\dOolIS,.]*\d[\dOolIS,.]*[\dOolIS]|\d", s)
    if not m:
        return None, ["unparseable"]
    token, fixed = _fix_ocr_digits(m.group(0))
    if fixed:
        flags.append("ocr_corrected")
    token = re.sub(r"[^\d.,]", "", token)
    # "1.234,56" (EU) vs "1,234.56" (US): last separator with 2 trailing digits is decimal.
    if re.search(r",\d{2}$", token) and "." in token:
        token = token.replace(".", "").replace(",", ".")
    elif re.search(r",\d{2}$", token) and token.count(",") == 1 and len(token) <= 6:
        token = token.replace(",", ".")
    else:
        token = token.replace(",", "")
    if token.count(".") > 1:  # "1.234.567" thousands dots
        head, _, tail = token.rpartition(".")
        token = head.replace(".", "") + "." + tail if len(tail) == 2 else token.replace(".", "")
    try:
        val = Decimal(token)
    except InvalidOperation:
        return None, ["unparseable"]
    if negative:
        val = -val
    return val.quantize(Decimal("0.01")), flags


def parse_number(raw: str | None) -> tuple[Decimal | None, list[str]]:
    """Parse a plain number such as a quantity into a Decimal with flags."""
    if raw is None or not str(raw).strip():
        return None, []
    m = re.search(r"-?[\dOolI][\dOolI,]*(?:\.\d+)?", str(raw))
    if not m:
        return None, ["unparseable"]
    token, fixed = _fix_ocr_digits(m.group(0))
    try:
        return Decimal(token.replace(",", "")), (["ocr_corrected"] if fixed else [])
    except InvalidOperation:
        return None, ["unparseable"]


_WORD_NUMBERS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty".split())}
_WORD_NUMBERS.update({"thirty": 30, "forty": 40, "forty-five": 45, "sixty": 60, "ninety": 90})


def parse_days(raw: str | None) -> tuple[int | None, list[str]]:
    """Schedule impact in calendar days. Negative means time removed."""
    if raw is None or not str(raw).strip():
        return None, []
    s = str(raw).strip().lower()
    if re.search(r"\b(none|no(?:\s+\w+)?\s+(?:change|impact)|n/?a|zero)\b", s) or re.fullmatch(r"[+\-]?0\s*(days?)?", s):
        return 0, []
    negative = bool(re.search(r"\b(decrease|reduc|less|shorten|credit)\w*|^-|^\(\s*\d+\s*\)$", s))
    m = re.search(r"\d+", s)
    if m:
        n = int(m.group(0))
    else:
        word = next((w for w in sorted(_WORD_NUMBERS, key=len, reverse=True) if re.search(rf"\b{w}\b", s)), None)
        if word is None:
            return None, ["unparseable"]
        n = _WORD_NUMBERS[word]
    flags = []
    if re.search(r"\bweeks?\b", s):
        n *= 7
        flags.append("converted_from_weeks")
    elif re.search(r"\bworking|business\b", s):
        flags.append("working_days_not_calendar")
    return (-n if negative else n), flags


_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%B %d, %Y", "%b %d, %Y",
                 "%B %d %Y", "%b %d %Y", "%d %B %Y", "%d %b %Y", "%b. %d, %Y", "%Y/%m/%d")


def parse_date(raw: str | None) -> tuple[date | None, list[str]]:
    """Parse a date in many formats, flagging OCR repairs and ambiguous day/month order."""
    if raw is None or not str(raw).strip():
        return None, []
    s = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", str(raw).strip())
    flags_pre: list[str] = []
    m = re.search(r"[\dOolI]{1,4}[/\-][\dOolI]{1,2}[/\-][\dOolI]{2,4}", s)
    if m and re.search(r"[OolI]", m.group(0)):
        fixed, _ = _fix_ocr_digits(m.group(0))
        s = s.replace(m.group(0), fixed)
        flags_pre.append("ocr_corrected")
    s = re.sub(r"\s+", " ", s).strip(" .,")
    candidates = [s]
    m = re.search(r"\d{1,4}[/\-]\d{1,2}[/\-]\d{2,4}|[A-Za-z]{3,9}\.? \d{1,2},? \d{4}|\d{1,2} [A-Za-z]{3,9} \d{4}", s)
    if m:
        candidates.insert(0, m.group(0))
    for cand in candidates:
        for fmt in _DATE_FORMATS:
            try:
                d = datetime.strptime(cand, fmt).date()
            except ValueError:
                continue
            flags = list(flags_pre)
            # dd/mm vs mm/dd ambiguity: both parts <= 12 and differ.
            nm = re.match(r"(\d{1,2})[/\-](\d{1,2})[/\-]", cand)
            if nm and int(nm.group(1)) <= 12 and int(nm.group(2)) <= 12 and nm.group(1) != nm.group(2):
                flags.append("ambiguous_day_month")
            return d, flags
    return None, ["unparseable"]


def clean_text(raw: str | None) -> tuple[str | None, list[str]]:
    """Collapse whitespace and trim stray punctuation from a text value."""
    if raw is None:
        return None, []
    s = re.sub(r"\s+", " ", str(raw)).strip(" :;-\t")
    return (s or None), []


def clean_id(raw: str | None) -> tuple[str | None, list[str]]:
    """Clean a change-order or project number (drops 'No.', '#' and uppercases it)."""
    s, _ = clean_text(raw)
    if s is None:
        return None, []
    s = re.sub(r"^(no\.?|number|#)\s*", "", s, flags=re.I).strip()
    return (s.upper() or None), []


_REASON_KEYWORDS: list[tuple[Reason, tuple[str, ...]]] = [
    (Reason.VALUE_ENGINEERING, ("value engineering", "value-engineering", " ve ", "cost reduction", "cost savings")),
    (Reason.REGULATORY, ("code", "inspector", "fire marshal", "permit", "ada ", "regulat", "authority having jurisdiction", "ahj")),
    (Reason.UNFORESEEN_CONDITION, ("unforeseen", "concealed", "differing site", "unknown", "discovered", "uncovered", "rock", "contaminat", "asbestos")),
    (Reason.DESIGN_ERROR, ("design error", "omission", "drawing error", "conflict in drawings", "rfi", "discrepan", "not shown on")),
    (Reason.OWNER_REQUEST, ("owner request", "owner-requested", "requested by owner", "owner directive", "client request", "per owner", "owner has requested", "upgrade", "added scope", "tenant request")),
]


def parse_reason(raw: str | None) -> tuple[Reason | None, list[str]]:
    """Map reason wording to a Reason category using keywords."""
    if raw is None or not str(raw).strip():
        return None, []
    s = " " + str(raw).lower().replace("_", " ") + " "
    for r in Reason:
        if s.strip() == r.value.replace("_", " "):
            return r, []
    for reason, kws in _REASON_KEYWORDS:
        if any(k in s for k in kws):
            return reason, ["inferred_from_keywords"]
    return Reason.OTHER, ["inferred_from_keywords"]


def parse_status(raw: str | None) -> tuple[Status | None, list[str]]:
    """Map approval wording or a stamp to a Status (approved, pending, rejected)."""
    if raw is None or not str(raw).strip():
        return None, []
    s = str(raw).lower().replace("0", "o")
    if re.search(r"reject|denied|declin|void", s):
        return Status.REJECTED, []
    if re.search(r"approv|accepted|executed|signed|authori[sz]ed", s) and not re.search(r"pending|not yet|awaiting|un", s):
        return Status.APPROVED, []
    if re.search(r"pending|proposed|submitted|awaiting|draft|for review|request", s):
        return Status.PENDING, []
    return None, ["unparseable"]


PARSERS = {
    "money": parse_money,
    "number": parse_number,
    "int": parse_days,
    "date": parse_date,
    "text": clean_text,
    "id": clean_id,
}
ENUM_PARSERS = {"reason": parse_reason, "status": parse_status}


def normalize(field: str, kind: str, raw: str | None):
    """Normalize a raw field value with the parser for its kind; returns (value, flags)."""
    if kind == "enum":
        return ENUM_PARSERS[field](raw)
    return PARSERS[kind](raw)
