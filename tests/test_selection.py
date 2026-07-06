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
