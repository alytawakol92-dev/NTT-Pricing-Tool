"""Tests for least-cost, spec-compliant catalog selection."""
from ntt_pricing.config import SelectionPolicy
from ntt_pricing.database import ComponentDatabase, select_item
from ntt_pricing.database.selection import round_up_ka
from ntt_pricing.models import CatalogItem, Component
from ntt_pricing.extraction import parse_specification


def _db():
    rows = [
        # 200A 3P MCCB in several families/prices, all >= 25kA
        ("G20B3A200", "Circuit breaker, GoPact MCCB 200, 3 poles, 25kA, 200A rating, TMD", 116.22),
        ("LV525302", "MCCB , 3P , 200A , 25KA , CVS250B , TMD", 186.32),
        ("LV525332", "MCCB , 3P , 200A , 36KA , CVS250F , TMD", 251.13),
        # a 200A accessory that must NOT be chosen as a breaker
        ("LVS03220", "Blanking Strip For MCCB , NSXm 100A,160A,200A", 3.38),
        # a 200A breaker with too-low Icu (10kA) — must be rejected for 25kA
        ("EZC200", "MCCB , 3P , 200A , 10KA , EasypactEZC", 90.00),
        # 1000A main options
        ("C100N320FM", "MCCB, 3P 1000A , 50K.A , NS1000N , MICR-2.0", 1589.0),
        ("NS10N20D3PMFF", "MCCB, 3P 1000A , 50K.A , NS1000N , MICR-2.0", 2515.63),
        # 50A 3P MCB
        ("A9F77350", "MCB , 3P , 50A , 10KA , iC60N .", 29.42),
        ("18638", "MCB , 3P , 50A , 10KA , iC60N .", 30.10),
    ]
    items = []
    for ref, desc, price in rows:
        it = CatalogItem(part_number=ref, description=desc, unit_price=price, currency="EUR")
        it.spec = parse_specification(desc)
        items.append(it)
    return ComponentDatabase(items)


def _comp(desc):
    return Component(tag="Q", raw_description=desc, spec=parse_specification(desc))


def test_round_up_ka():
    assert round_up_ka(34.5) == 36
    assert round_up_ka(15) == 15


def test_ka_regex_parses_dotted_form():
    # "50K.A" must parse to 50 kA (real NTT price-book notation)
    assert parse_specification("MCCB, 3P 1000A , 50K.A , NS1000N").breaking_capacity_ka == 50


def test_picks_cheapest_compliant_breaker():
    db = _db()
    c = _comp("MCCB 3P 200A 15KA")           # 15kA required
    m = select_item(c, db, SelectionPolicy())
    assert m is not None
    assert m.item.part_number == "G20B3A200"  # cheapest 200A >= 15kA, not CVS
    assert m.method == "least-cost"


def test_rejects_accessory_and_underrated():
    db = _db()
    c = _comp("MCCB 3P 200A 25KA")
    m = select_item(c, db, SelectionPolicy())
    # never the €3 blanking strip, never the 10kA EZC when 25kA is required
    assert m.item.part_number not in ("LVS03220", "EZC200")
    assert m.item.part_number == "G20B3A200"


def test_breaking_capacity_is_respected():
    db = _db()
    c = _comp("MCCB 3P 200A 36KA")           # needs 36kA
    m = select_item(c, db, SelectionPolicy())
    assert m.item.spec.breaking_capacity_ka >= 36   # the CVS250F, not the 25kA parts


def test_main_least_cost_ns():
    db = _db()
    c = _comp("MCCB 3P 1000A 34.5KA")
    m = select_item(c, db, SelectionPolicy())
    assert m.item.part_number == "C100N320FM"       # cheapest 1000A >= 34.5kA


def test_series_mode_pins_family():
    db = _db()
    c = _comp("MCCB 3P 200A 15KA")
    pol = SelectionPolicy(objective="series", preferred_series=["CVS"])
    m = select_item(c, db, pol)
    assert "CVS" in m.item.description        # pinned to CVS despite GoPact being cheaper


def test_mcb_prefers_a9f_on_price_tie():
    db = _db()
    c = _comp("MCB 3P 50A")
    c.spec.poles = 3
    m = select_item(c, db, SelectionPolicy())
    assert m.item.part_number == "A9F77350"   # cheapest; A9F breaks the tie


def test_disabled_returns_none():
    assert select_item(_comp("MCCB 3P 200A"), _db(), SelectionPolicy(enabled=False)) is None


def _frame_db():
    rows = [
        # exact 320A exists only as an expensive high-kA part (adjustable)
        ("NSX400H320", "MCCB, 3P 320A , 70KA , NSX400H , Micrologic 2.3 Adj", 690.32),
        # a cheaper 400A adjustable frame that can be set down to 320A
        ("G40F3A400", "Circuit breaker, GoPact MCCB 400, 3 poles, 36kA, 400A rating, adjustable", 244.10),
        # a cheap 400A FIXED — must NOT be used for a 320A trip (over-protection)
        ("G40F3F400", "Circuit breaker, GoPact MCCB 400, 3 poles, 36kA, 400A rating, fixed", 200.00),
        # a plain 63A fixed feeder + a big adjustable that must not be picked for 63A
        ("G12F3F63", "Circuit breaker, GoPact MCCB 125, 3 poles, 30kA, 63A rating, fixed", 63.67),
    ]
    items = []
    for ref, desc, price in rows:
        it = CatalogItem(part_number=ref, description=desc, unit_price=price, currency="EUR")
        it.spec = parse_specification(desc)
        items.append(it)
    return ComponentDatabase(items)


def test_adjustable_larger_frame_chosen_when_cheaper():
    db = _frame_db()
    c = _comp("MCCB 3P 320A 25KA")
    m = select_item(c, db, SelectionPolicy())
    # 400A adjustable set to 320A (EUR244) beats the exact 320A part (EUR690)
    assert m.item.part_number == "G40F3A400"


def test_fixed_breaker_not_oversized():
    db = _frame_db()
    c = _comp("MCCB 3P 320A 25KA")
    m = select_item(c, db, SelectionPolicy())
    # a FIXED 400A must never protect a 320A circuit, even though it is cheapest
    assert m.item.part_number != "G40F3F400"


def test_small_feeder_not_jumped_to_big_frame():
    db = _frame_db()
    c = _comp("MCCB 3P 63A 25KA")
    m = select_item(c, db, SelectionPolicy())
    # 63A is below 0.7 x 400, so the big adjustable frame is not eligible
    assert m.item.part_number == "G12F3F63"
