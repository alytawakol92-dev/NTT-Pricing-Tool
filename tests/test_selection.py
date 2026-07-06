"""Tests for standards-based catalog selection (SelectionPolicy)."""
from ntt_pricing.config import SelectionPolicy
from ntt_pricing.database import ComponentDatabase, select_item
from ntt_pricing.database.selection import round_up_ka
from ntt_pricing.models import CatalogItem, Component, Specification, DeviceType
from ntt_pricing.extraction import parse_specification


def _db():
    rows = [
        # 200A MCCB in three families: CVS (25kA), NSX (36kA), NS (50kA)
        ("LV525302", "MCCB , 3P , 200A , 25KA , CVS250B , TMD", 186.32),
        ("LV432893", "MCCB , 3P3T , 200A , 36KA , NSX250F , TMD", 320.00),
        ("NS20N", "MCCB , 3P , 200A , 50KA , NS", 500.00),
        # 1000A NS main
        ("C100N320FM", "MCCB, 3P 1000A , 50K.A , NS1000N , MICR-2.0", 1589.0),
        # 50A 3P MCB in two order codes (A9F preferred, plus a duplicate)
        ("A9F77350", "MCB , 3P , 50A , 10KA , iC60N .", 29.42),
        ("18638", "MCB , 3P , 50A , 10KA , iC60N .", 30.10),
    ]
    items = []
    for ref, desc, price in rows:
        it = CatalogItem(part_number=ref, description=desc, unit_price=price,
                         currency="EUR")
        it.spec = parse_specification(desc)
        items.append(it)
    return ComponentDatabase(items)


def _comp(desc):
    return Component(tag="Q", raw_description=desc, spec=parse_specification(desc))


def test_round_up_ka():
    assert round_up_ka(15) == 15
    assert round_up_ka(34.5) == 36
    assert round_up_ka(45) == 50


def test_mccb_feeder_prefers_cvs_25ka():
    db = _db()
    c = _comp("MCCB 3P 200A 15KA")     # drawing says 15kA
    m = select_item(c, db, SelectionPolicy())
    assert m is not None
    assert m.item.part_number == "LV525302"   # CVS 25kA, not NSX/NS
    assert m.method == "policy"


def test_main_prefers_ns_frame():
    db = _db()
    c = _comp("MCCB 3P 1000A 34.5KA")
    m = select_item(c, db, SelectionPolicy())
    assert m.item.part_number == "C100N320FM"   # NS1000N 50kA


def test_mcb_prefers_a9f_order_code():
    db = _db()
    c = _comp("MCB 3P 50A")
    c.spec.poles = 3
    m = select_item(c, db, SelectionPolicy())
    assert m.item.part_number == "A9F77350"


def test_disabled_policy_returns_none():
    db = _db()
    pol = SelectionPolicy(enabled=False)
    assert select_item(_comp("MCCB 3P 200A"), db, pol) is None
