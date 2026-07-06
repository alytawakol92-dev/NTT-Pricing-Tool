"""Tests for the scattered-token SLD reconstructor (PDF exports).

Synthetic ``((x, y), text)`` tokens mimic a PDF drawing where the rating,
device keyword and quantity of a circuit sit at different coordinates.
"""
from ntt_pricing.extraction.scattered import extract_scattered
from ntt_pricing.models import DeviceType


def _entries():
    # a small lighting DB fed from EMDB-2: 63A 3∅ incomer, a 32A contactor,
    # and 16A/20A outgoing circuits with X-multipliers in a left column.
    return [
        ((1900, 1100), "FROM"), ((1900, 1050), "EMDB-2"),
        ((1680, 300), "63A,3∅"), ((1640, 300), "MCB"),          # incomer
        ((1250, 1400), "CONTACTOR"), ((1180, 1150), "32A"),      # contactor (no phase)
        ((840, 1300), "16A,1∅"), ((805, 1300), "MCB"), ((340, 1300), "X9"),
        ((1360, 500), "20A,1∅"), ((410, 520), "X6"),
        ((1360, 100), "25A,3∅"), ((340, 120), "X3"),
        ((450, 1450), "(3*4)mm2"), ((450, 1420), "CU,PVC/PVC"),  # cable noise
        ((1550, 1600), "380V,50HZ,10KA"),                        # system noise
    ]


def test_extracts_board_and_devices():
    comps = extract_scattered(_entries())
    assert comps
    assert comps[0].board == "DB (from EMDB-2)"
    kinds = {(c.spec.device_type, c.spec.rating_amps, c.spec.poles): c.quantity
             for c in comps}
    # incomer 63A 3P, quantity 1 (never absorbs an outgoing X-multiplier)
    assert kinds.get((DeviceType.MCB, 63.0, 3)) == 1


def test_phase_notation_to_poles():
    comps = extract_scattered(_entries())
    for c in comps:
        if c.spec.rating_amps == 16:
            assert c.spec.poles == 1        # "16A,1∅"
        if c.spec.rating_amps == 25:
            assert c.spec.poles == 3        # "25A,3∅"


def test_phase_marked_feeder_is_not_contactor():
    # "32A,3∅" would be a feeder; only the plain "32A" near CONTACTOR is one
    comps = extract_scattered(_entries())
    contactors = [c for c in comps if c.spec.device_type == DeviceType.CONTACTOR]
    assert contactors and contactors[0].spec.rating_amps == 32


def test_quantities_from_multipliers():
    comps = extract_scattered(_entries())
    q = {c.spec.rating_amps: c.quantity for c in comps
         if c.spec.device_type == DeviceType.MCB}
    assert q.get(16) == 9      # X9
    assert q.get(20) == 6      # X6


def test_noise_tokens_ignored():
    comps = extract_scattered(_entries())
    # cables / system labels must not become devices
    assert all(c.spec.rating_amps in (63, 32, 16, 20, 25) for c in comps)


def _atf_feeder(x, trip, frame):
    """One MCCB feeder drawn as split trip/frame tokens (63 / AT, 100 / AF)."""
    return [
        ((x, 500), "MCCB"),
        ((x, 520), str(trip)), ((x, 505), "AT"),       # trip above "AT"
        ((x + 12, 520), str(frame)), ((x + 12, 505), "AF"),  # frame above "AF"
    ]


def test_atf_trip_frame_notation():
    # MDB feeder schedule: 320A main + 63A + 100A + 50A feeders, all in the
    # "NN AT / NN AF" split-token style used by PDF MDB drawings.
    entries = [((100, 900), "MDB"), ((100, 880), "Isc=25"), ((100, 860), "kA")]
    entries += _atf_feeder(300, 320, 400)
    entries += _atf_feeder(500, 63, 100)
    entries += _atf_feeder(700, 100, 100)
    entries += _atf_feeder(900, 50, 100)
    comps = extract_scattered(entries)
    assert comps and comps[0].board == "MDB"
    ratings = {c.spec.rating_amps: c.quantity for c in comps}
    assert ratings.get(320) == 1        # main incomer (trip 320, frame 400)
    assert ratings.get(63) == 1
    assert ratings.get(50) == 1
    # breaking capacity read from the system Isc note
    assert all(c.spec.breaking_capacity_ka == 25 for c in comps)
    assert all(c.spec.device_type.value == "MCCB" for c in comps)
