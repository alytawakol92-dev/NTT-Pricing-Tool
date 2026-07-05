"""Tests for the graphical single-line-diagram extractor.

Uses synthetic ``((x, y), text)`` entries that mimic a consultant drawing —
two panels stacked in Y, each with an MCCB incomer and a row of
``"50A / 10KA / MCB / ELCB / 30mA"`` outgoing-way labels — so no CAD file is
needed.
"""
from ntt_pricing.extraction.graphical import extract_graphical, is_graphical
from ntt_pricing.models import DeviceType


def _way(a):
    return f"{a}A\n10KA\nMCB\nELCB\n30mA"


def _panel_entries(y, name, ratings):
    entries = [((0, y + 20), name), ((0, y + 5), "D.LOAD = 80 KVA"),
               ((-300, y), "MCCB ADJ"), ((-295, y + 5), "150/160"),
               ((-350, y), "Isc = 18KA")]
    for i, a in enumerate(ratings):
        entries.append(((i * 100, y), _way(a)))
        entries.append(((i * 100, y - 8), "X1"))
    return entries


def test_is_graphical():
    assert is_graphical([_way(50), _way(32), "MCCB", _way(16)])
    assert not is_graphical(["hello", "DP-REST", "X1"])


def test_two_panels_detected():
    entries = _panel_entries(1000, "DP-REST BECH", [50, 50, 32]) + \
              _panel_entries(0, "EDP-REST BECH", [16, 10])
    comps = extract_graphical(entries)
    boards = {c.board for c in comps}
    assert boards == {"DP-REST BECH", "EDP-REST BECH"}


def test_incomer_and_aggregation():
    entries = _panel_entries(0, "DP-REST BECH", [50, 50, 50, 32])
    comps = extract_graphical(entries)
    mccb = [c for c in comps if c.spec.device_type == DeviceType.MCCB]
    assert len(mccb) == 1
    assert mccb[0].spec.rating_amps == 160      # frame from 150/160
    assert mccb[0].spec.trip_amps == 150
    # three identical 50A ways aggregate into one line of qty 3
    mcb50 = [c for c in comps if c.spec.device_type == DeviceType.MCB
             and c.spec.rating_amps == 50]
    assert len(mcb50) == 1 and mcb50[0].quantity == 3


def test_elcb_paired_with_each_mcb():
    entries = _panel_entries(0, "DP", [50])
    comps = extract_graphical(entries)
    mcb = [c for c in comps if c.spec.device_type == DeviceType.MCB]
    rccb = [c for c in comps if c.spec.device_type == DeviceType.RCCB]
    assert mcb and rccb
    # a 3P 50A MCB pairs with a 4P RCCB sized >= 50A
    assert mcb[0].spec.poles == 3
    assert rccb[0].spec.poles == 4
    assert rccb[0].spec.rating_amps >= 50


def test_pole_heuristic():
    entries = _panel_entries(0, "DP", [50, 16])
    comps = extract_graphical(entries)
    by_a = {c.spec.rating_amps: c for c in comps
            if c.spec.device_type == DeviceType.MCB}
    assert by_a[50].spec.poles == 3    # >= 25A → 3P
    assert by_a[16].spec.poles == 1    # < 25A  → 1P
