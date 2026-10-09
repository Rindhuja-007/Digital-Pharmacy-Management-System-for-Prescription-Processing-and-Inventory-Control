"""Regex parser: OCR text -> medicine lines. Only lines starting with a dosage-form word count."""
import math
import re
from dataclasses import dataclass, field

FORM_RE = re.compile(
    r"^(?P<form>tablets?|tabs?|capsules?|caps?|injection|inj|syrup|syp|drops?|ointment|oint)\b\.?\s*[:\-]?\s*",
    re.I)
NUMBERING_RE = re.compile(r"^\s*(?:\(?\d{1,2}[\).:]|[-•*·])\s+")

CITIES = ("mumbai|delhi|chennai|kolkata|bengaluru|bangalore|hyderabad|pune|ahmedabad|jaipur|lucknow|"
          "noida|gurgaon|gurugram|kochi|coimbatore|surat|nagpur|indore|bhopal|chandigarh")
BLOCK_RE = re.compile(
    r"\b(?:dr|md|mbbs|dnb|frcs|consultant|reg\.?\s*no"                      # doctor titles / credentials
    r"|plot|colony|road|street|sector|floor|" + CITIES + r")\b|\b\d{6}\b"      # address words, pincodes
    r"|\b(?:hospital|clinic|telephone|mobile|e-?mail|website)\b"              # hospital / contact
    r"|\b(?:age|yrs?|gender|weight|bp|pulse|temp)\b"                          # vitals
    r"|\b(?:dm|htn|hypertension|diabetes|diagnosis)\b|\bc/o\b|\bo/e\b|\breview\s+after\b",  # diagnoses
    re.I)

STRENGTH_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|%)(?![A-Za-z])", re.I)
FREQ_PATTERN_RE = re.compile(r"(?<![\d.])\d(?:\.\d)?\s*-\s*\d(?:\.\d)?\s*-\s*\d(?:\.\d)?(?:\s*-\s*\d(?:\.\d)?)?(?![\d.])")
FREQ_ABBR_RE = re.compile(r"\b(?:OD|BD|BID|TID|TDS|QID|QDS|HS|PRN|SOS)\b", re.I)
FREQ_WORD_RE = re.compile(r"\b(?:morning|night|evening|afternoon)\b", re.I)
DURATION_RE = re.compile(r"(\d+)\s*(days?|weeks?|months?)\b", re.I)
SEPARATOR_RE = re.compile(r"\s+(?:x|for|[-–—:])\s+|\s+x\s*(?=\d)|[,;(\[]", re.I)

PER_DAY = {"OD": 1, "BD": 2, "BID": 2, "TID": 3, "TDS": 3, "QID": 4, "QDS": 4, "HS": 1}
UNIT_DAYS = {"day": 1, "week": 7, "month": 30}

# Known OCR misreads: key = lowercase letters/digits only. Extend as you see new mistakes.
OCR_FIXES = {
    "sizodonplua5": "Sizodon Plus", "sizodonplus": "Sizodon Plus",
    "dolo5oo": "Dolo 500", "d0lo500": "Dolo 500", "d0lo5oo": "Dolo 500",
    "crocln500": "Crocin 500", "croc1n500": "Crocin 500", "crocin5oo": "Crocin 500",
    "metformln500": "Metformin 500", "metformin5oo": "Metformin 500", "metforminsoo": "Metformin 500",
    "pan4o": "Pan 40", "pantoprazole4o": "Pantoprazole 40",
    "azithral5oo": "Azithral 500", "amoxlcillin": "Amoxicillin", "amoxicilin": "Amoxicillin",
}


@dataclass
class ExtractedLine:
    raw: str
    form: str
    name: str
    strength: str | None = None
    frequency: str | None = None
    duration: str | None = None
    quantity: int = 1
    corrected: bool = False


@dataclass
class ExtractionResult:
    items: list[ExtractedLine] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)  # medicine-looking lines dropped by the blocklist


def _clean(line: str) -> str:
    line = line.replace("\u00a0", " ").replace("\t", " ")
    line = NUMBERING_RE.sub("", line)
    return re.sub(r"\s+", " ", line).strip()


def _fix_ocr_name(name: str) -> tuple[str, bool]:
    key = re.sub(r"[^a-z0-9]", "", name.lower())
    if key in OCR_FIXES:
        return OCR_FIXES[key], True
    stripped = re.sub(r"[^a-z0-9]", "", STRENGTH_RE.sub("", name).lower())
    if stripped in OCR_FIXES:
        return OCR_FIXES[stripped], True
    return name, False


def _frequency(rest: str) -> tuple[str | None, list[int]]:
    found: list[tuple[int, str]] = []
    doses = 0.0
    counted = False
    for m in FREQ_PATTERN_RE.finditer(rest):
        val = re.sub(r"\s+", "", m.group(0))
        found.append((m.start(), val))
        doses += sum(float(x) for x in val.split("-"))
        counted = True
    for m in FREQ_ABBR_RE.finditer(rest):
        val = m.group(0).upper()
        found.append((m.start(), val))
        if val in PER_DAY:
            doses += PER_DAY[val]
            counted = True
    for m in FREQ_WORD_RE.finditer(rest):
        found.append((m.start(), m.group(0).capitalize()))
        doses += 1
        counted = True
    if not found:
        return None, []
    found.sort()
    seen, ordered = set(), []
    for _, v in found:
        if v not in seen:
            seen.add(v)
            ordered.append(v)
    return ", ".join(ordered), ([math.ceil(doses)] if counted else [])


def parse_line(raw: str) -> ExtractedLine | None:
    line = _clean(raw)
    m = FORM_RE.match(line)
    if not m:
        return None
    form = m.group("form").lower()
    rest = line[m.end():]

    cut = len(rest)
    for rx in (FREQ_PATTERN_RE, FREQ_ABBR_RE, FREQ_WORD_RE, DURATION_RE, SEPARATOR_RE):
        hit = rx.search(rest)
        if hit:
            cut = min(cut, hit.start())
    name = rest[:cut]
    name = re.sub(r"\s+(?:x|for)$", "", name, flags=re.I).strip(" .,:;-–—_|")
    name = re.sub(r"\s+", " ", name)
    if len(re.sub(r"[^A-Za-z]", "", name)) < 2:
        return None
    name, corrected = _fix_ocr_name(name)

    strength_m = STRENGTH_RE.search(rest)
    strength = re.sub(r"\s+", " ", strength_m.group(0)).lower() if strength_m else None
    frequency, doses = _frequency(rest[cut:] if cut < len(rest) else rest)
    dur_m = DURATION_RE.search(rest)
    duration = f"{dur_m.group(1)} {dur_m.group(2).lower()}" if dur_m else None

    quantity = 1  # a SUGGESTION only; the pharmacist confirms the real quantity
    if dur_m and doses and form.startswith(("tab", "cap")):
        days = int(dur_m.group(1)) * UNIT_DAYS[dur_m.group(2).lower().rstrip("s")]
        quantity = max(1, doses[0] * days)
    return ExtractedLine(raw=raw.strip(), form=form, name=name, strength=strength, frequency=frequency,
                         duration=duration, quantity=quantity, corrected=corrected)


def extract_medicine_lines(text: str) -> ExtractionResult:
    out = ExtractionResult()
    for raw in (text or "").splitlines():
        line = _clean(raw)
        if not line or not FORM_RE.match(line):
            continue                      # rule: only lines that begin with a form prefix count
        if BLOCK_RE.search(line):
            out.skipped.append({"line": raw.strip(), "reason": "matched the non-medicine blocklist"})
            continue
        parsed = parse_line(raw)
        if parsed:
            out.items.append(parsed)
    return out
