from app.models import Medicine
from app.services.extraction import extract_medicine_lines, parse_line
from app.services.matching import active_tokens, level_for, match_item


def names(text):
    return [i.name for i in extract_medicine_lines(text).items]


def test_only_form_prefixed_lines_count():
    text = "Paracetamol 500 mg\nTab Dolo 500 mg OD\nCap Amoxil 250mg TID\nSyp Ascoril 5 ml BD\nInj Vitamin B12 1 ml\n" \
           "Drops Otrivin 0.1% PRN\nOintment Betnovate 15 g BD\n1) Tab Pan 40 morning"
    assert names(text) == ["Dolo 500 mg", "Amoxil 250mg", "Ascoril 5 ml", "Vitamin B12 1 ml",
                           "Otrivin 0.1%", "Betnovate 15 g", "Pan 40"]


def test_blocklist_skips_non_medicine_lines_even_with_a_form_word():
    text = ("Tab Dr Rao MBBS\nTab Plot 4 Sector 9 Colony\nTab Hospital Road 110001\nTab Telephone 98765\n"
            "Tab Age 45 Yrs\nTab BP 140/90\nTab Diagnosis DM\nTab Review after 2 weeks\nTab Dolo 500 mg")
    res = extract_medicine_lines(text)
    assert [i.name for i in res.items] == ["Dolo 500 mg"] and len(res.skipped) == 8


def test_strength_frequency_duration_and_quantity_suggestion():
    p = parse_line("Tab Metformin 500 mg 1-0-1 x 10 days")
    assert (p.strength, p.frequency, p.duration, p.quantity) == ("500 mg", "1-0-1", "10 days", 20)
    assert parse_line("Cap Foo 250 mcg BD for 2 weeks").quantity == 28
    assert parse_line("Tab Foo 5 mg HS").frequency == "HS"
    assert parse_line("Tab Foo 5 mg morning night").frequency == "Morning, Night"
    assert parse_line("Syp Cough 5 ml TID x 5 days").quantity == 1           # only tablets/capsules are estimated
    assert parse_line("Tab Foo 5 mg PRN").frequency == "PRN"


def test_known_ocr_misreads_are_corrected():
    p = parse_line("Tab Si zoDon PLua5 OD")
    assert p.name == "Sizodon Plus" and p.corrected is True
    assert parse_line("Tab D0lo 5OO").name == "Dolo 500"


def test_levels():
    assert (level_for(95), level_for(90), level_for(89.9), level_for(70), level_for(69.9)) == \
           ("HIGH", "HIGH", "MEDIUM", "MEDIUM", "LOW")


def _med(i, name, generic=None, comp=None, brand=None, strength=None):
    return Medicine(id=i, medicine_name=name, generic_name=generic, composition=comp, brand_name=brand,
                    strength=strength, reorder_level=15)


def test_matching_ranks_candidates_and_penalises_different_strength():
    meds = [_med(1, "Crocin 500", "Paracetamol", "Paracetamol 500 mg", "Crocin", "500 mg"),
            _med(2, "Crocin 650", "Paracetamol", "Paracetamol 650 mg", "Crocin", "650 mg"),
            _med(3, "Metformin 500", "Metformin Hydrochloride", "Metformin Hydrochloride 500 mg", "Glycomet", "500 mg")]
    res = match_item("Crocin 650 mg", "650 mg", meds, {1: 0, 2: 10, 3: 5})
    assert res["candidates"][0]["medicine_id"] == 2 and res["candidates"][0]["level"] == "HIGH"
    wrong = next(c for c in res["candidates"] if c["medicine_id"] == 1)
    assert wrong["strength_mismatch"] is True and wrong["score"] < 90      # different strength is never HIGH
    assert len(res["candidates"]) <= 5


def test_substitutes_share_an_ingredient_and_sort_in_stock_first():
    meds = [_med(1, "Crocin 500", "Paracetamol", "Paracetamol 500 mg"),
            _med(2, "Dolo 500", "Paracetamol", "Paracetamol 500 mg"),
            _med(3, "Calpol 500", "Paracetamol", "Paracetamol 500 mg"),
            _med(4, "Zerodol P", "Aceclofenac", "Aceclofenac 100 mg + Paracetamol 325 mg"),
            _med(5, "Metformin 500", "Metformin Hydrochloride", "Metformin Hydrochloride 500 mg"),
            _med(6, "Cetirizine 10", "Cetirizine Hydrochloride", "Cetirizine Hydrochloride 10 mg")]
    stock = {2: 20, 3: 150, 4: 0, 5: 10, 6: 10}
    subs = match_item("Crocin 500", None, meds, stock)["substitutes"]
    assert [s["medicine_id"] for s in subs] == [3, 2, 4]          # in-stock by stock desc, then out-of-stock
    assert all(s["medicine_id"] not in (1, 5, 6) for s in subs)    # "hydrochloride" alone is not an active ingredient
    assert subs[0]["same_ingredients"] is True and subs[2]["same_ingredients"] is False


def test_active_token_extraction_ignores_form_words():
    m = _med(1, "X", "Amoxicillin Tablet", "Amoxicillin 500 mg + Clavulanic Acid 125 mg Plus Capsule")
    assert active_tokens(m) == {"amoxicillin", "clavulanic"}
