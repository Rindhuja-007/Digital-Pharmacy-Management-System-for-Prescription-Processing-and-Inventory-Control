"""Catalogue matching (rapidfuzz WRatio) and same-ingredient substitutes. Suggestions only."""
import re

from rapidfuzz import fuzz, utils

from ..models import Medicine

HIGH, MEDIUM = 90, 70

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
STOPWORDS = {
    "tablet", "tablets", "capsule", "capsules", "syrup", "plus", "injection", "drops", "drop", "ointment",
    "cream", "gel", "suspension", "solution", "forte", "extended", "release", "sustained", "retard", "film",
    "coated", "dispersible", "chewable", "oral", "dose", "each", "contains", "with", "and", "anhydrous",
    "hydrochloride", "hcl", "sodium", "potassium", "calcium", "magnesium", "sulfate", "sulphate", "phosphate",
    "maleate", "besylate", "tartrate", "succinate", "acetate", "citrate", "mesylate", "bromide", "chloride",
    "dihydrate", "monohydrate", "acid", "equivalent", "base",
}


def level_for(score: float) -> str:
    return "HIGH" if score >= HIGH else "MEDIUM" if score >= MEDIUM else "LOW"


def active_tokens(m: Medicine) -> set[str]:
    text = f"{m.generic_name or ''} {m.composition or ''}".lower()
    return {t for t in re.findall(r"[a-z]+", text) if len(t) >= 4 and t not in STOPWORDS}


def _numbers(*texts: str | None) -> set[str]:
    return {str(float(n)).rstrip("0").rstrip(".") for t in texts if t for n in _NUM_RE.findall(t)}


def _med_summary(m: Medicine, stock: int) -> dict:
    return {"medicine_id": m.id, "medicine_name": m.medicine_name, "brand_name": m.brand_name,
            "generic_name": m.generic_name, "strength": m.strength, "dosage_form": m.dosage_form,
            "usable_stock": stock}


def score_medicine(query: str, query_numbers: set[str], m: Medicine) -> tuple[float, bool]:
    fields = [f for f in (m.medicine_name, m.brand_name, m.generic_name, m.composition) if f]
    score = max((fuzz.WRatio(query, f, processor=utils.default_process) for f in fields), default=0.0)
    mismatch = False
    med_numbers = _numbers(m.medicine_name, m.strength)
    if query_numbers and med_numbers and query_numbers.isdisjoint(med_numbers):
        mismatch = True               # e.g. prescription says 650 but catalogue entry is 500
        score = max(0.0, score - 20)  # never let a different strength look like a HIGH match
    return float(score), mismatch


def match_item(name: str, dosage: str | None, medicines: list[Medicine], usable: dict[int, int],
               top_n: int = 5) -> dict:
    query = (name or "").strip()
    qnums = _numbers(query, dosage)
    scored = []
    for m in medicines:
        s, mismatch = score_medicine(query, qnums, m)
        if s > 0:
            scored.append((s, mismatch, m))
    scored.sort(key=lambda t: (-t[0], -usable.get(t[2].id, 0), t[2].medicine_name))
    candidates = []
    for s, mismatch, m in scored[:top_n]:
        c = _med_summary(m, usable.get(m.id, 0))
        c.update(score=round(s, 1), level=level_for(s), strength_mismatch=mismatch)
        candidates.append(c)
    return {"candidates": candidates, "substitutes": substitutes_for(scored[0][2], medicines, usable)
            if scored else []}


def substitutes_for(base: Medicine, medicines: list[Medicine], usable: dict[int, int]) -> list[dict]:
    base_tokens = active_tokens(base)
    if not base_tokens:
        return []
    out = []
    for m in medicines:
        if m.id == base.id:
            continue
        toks = active_tokens(m)
        shared = base_tokens & toks
        if shared:
            row = _med_summary(m, usable.get(m.id, 0))
            row.update(shared_ingredients=sorted(shared), same_ingredients=(toks == base_tokens),
                       strength_differs=bool(base.strength and m.strength
                                             and base.strength.lower() != m.strength.lower()))
            out.append(row)
    out.sort(key=lambda r: (r["usable_stock"] <= 0, -r["usable_stock"], r["medicine_name"]))
    return out
