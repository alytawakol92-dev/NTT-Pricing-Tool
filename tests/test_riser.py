"""Tests for the order-based riser (stacked-table) extractor.

Riser drawings converted from DWG can collapse all table text onto a couple
of points, so these entries deliberately reuse the same position — the parser
must rely on reading order, not geometry.
"""
from ntt_pricing.extraction.riser import extract_riser, looks_like_stacked_riser
from ntt_pricing.models import DeviceType

P = (322.3, 837.2)   # every text shares (nearly) one point, as in the real file


def _floor_table(feeder, flats, kva):
    seq = ["380V,50HZ,15KA", "Type of load", "QTY. OF C.B", "PANEL REF.:",
           "C.LOAD K.V.A", f"{feeder}A-15KA", "MCCB"]
    for i in range(flats):
        seq += [f"FLAT - {i+1}", f"{kva} KVA"]
    seq.append("(3CX95+50)mm2 AL/XLPE EARTH")
    return seq


def _entries(seq):
    return [(P, t) for t in seq]


def test_detects_stacked_riser():
    seq = ["PANEL REF.:", "380V,50HZ,15KA"] + _floor_table(160, 6, 15) + \
          _floor_table(200, 6, 18)
    assert looks_like_stacked_riser(_entries(seq))


def test_not_riser_when_positions_spread():
    seq = ["380V,50HZ,15KA", "PANEL REF.:"]
    entries = [((i * 100.0, i * 50.0), t) for i, t in enumerate(seq)]
    assert not looks_like_stacked_riser(entries)


def test_floor_boards_and_feeders():
    seq = ["1000AT/1000AF", "MCCB 3P", "34.5 kA"]
    seq += _floor_table(160, 6, 15)
    seq += _floor_table(200, 7, 18)
    comps = extract_riser(_entries(seq))
    boards = [c.board for c in comps]
    assert "MDB-TYPE 2" in boards
    assert "DB-GROUND FLOOR" in boards and "DB-FIRST FLOOR" in boards

    # MDB carries the 1000A main (NS-frame MCCB) + one feeder per floor DB
    mdb = [c for c in comps if c.board == "MDB-TYPE 2"]
    assert any(c.spec.device_type == DeviceType.MCCB and c.spec.rating_amps == 1000
               for c in mdb)
    # 1000A main + 2 floor feeders = 3 MCCBs
    assert sum(1 for c in mdb if c.spec.device_type == DeviceType.MCCB) == 3

    # each floor DB has an MCCB incomer + flat feeders summing to the flat count
    ground = [c for c in comps if c.board == "DB-GROUND FLOOR"]
    assert any(c.spec.device_type == DeviceType.MCCB and c.spec.rating_amps == 160
               for c in ground)
    flats = [c for c in ground if c.spec.device_type == DeviceType.MCB]
    assert sum(c.quantity for c in flats) == 6
    # Rule 2: a flat feed is rated to the flat sub-DB's main (standard 50A 3P),
    # not to its diversified demand.
    assert all(c.spec.rating_amps == 50 and c.spec.poles == 3 for c in flats)


def test_flat_feeder_standard_rating():
    # Rule 2: each flat feed = the flat sub-DB main (standard 50A 3P), one per flat
    seq = _floor_table(160, 6, 15)
    comps = extract_riser(_entries(seq))
    feeders = [c for c in comps if c.spec.device_type == DeviceType.MCB]
    assert feeders and feeders[0].quantity == 6
    assert feeders[0].spec.rating_amps == 50 and feeders[0].spec.poles == 3


def test_flat_feeder_rating_configurable():
    seq = _floor_table(160, 6, 15)
    comps = extract_riser(_entries(seq), flat_feeder_amps=63)
    feeders = [c for c in comps if c.spec.device_type == DeviceType.MCB]
    assert feeders[0].spec.rating_amps == 63
