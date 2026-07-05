import os

from ntt_pricing.database import ComponentDatabase, match_component
from ntt_pricing.extraction import parse_specification
from ntt_pricing.models import Component

DATA = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


def _db():
    return ComponentDatabase.load(os.path.join(DATA, "sample_pricing.csv"))


def test_catalog_loads():
    db = _db()
    assert len(db) > 20
    assert db.by_part_number("A9F74116") is not None


def test_match_mccb():
    db = _db()
    c = Component(tag="Q1", raw_description="Compact NSX250F MCCB 3P 250A 36kA feeder",
                  spec=parse_specification("Compact NSX250F MCCB 3P 250A 36kA feeder"))
    m = match_component(c, db, threshold=60)
    assert m is not None
    assert m.item.part_number == "LV432893"
    assert m.confident


def test_match_mcb_by_rating():
    db = _db()
    c = Component(tag="Q1-3", raw_description="iC60N MCB 1P 16A C curve lighting",
                  spec=parse_specification("iC60N MCB 1P 16A C curve lighting"))
    m = match_component(c, db, threshold=60)
    assert m is not None
    assert m.item.part_number == "A9F74116"


def test_spec_prevents_wrong_type():
    """A 100A MCCB query should not match a 100A contactor better than the MCCB."""
    db = _db()
    c = Component(tag="Q3", raw_description="MCCB 3P 100A 36kA",
                  spec=parse_specification("MCCB 3P 100A 36kA"))
    m = match_component(c, db, threshold=60)
    assert m.item.spec.device_type.name == "MCCB"
