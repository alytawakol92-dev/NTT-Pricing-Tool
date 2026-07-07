"""Tests for the atomised panel-schedule SLD reader.

These consultant drawings split each device into separate "poles / device /
rating" text tokens stacked in a column, with several panels side by side.
"""
from ntt_pricing.extraction.panel_sld import (
    extract_panel_sld, looks_like_panel_sld,
)


def _stack(x, y_top, poles, device, rating):
    """Emit the three tokens of one device as a consultant sheet draws them:
    poles above, device word, rating below (shared x)."""
    return [
        ((x, y_top), poles),
        ((x, y_top - 560), device),
        ((x, y_top - 780), rating),
    ]


def _sheet():
    """Two panels side by side: LPP-B37-GR (MCB 32A in, 2×16A out) and
    MCC-B37 (MCCB 80A in, 63A + 16A out).  A lower main-feeder band (MCCB
    250A) sits far below and must not be filed under either panel."""
    e = []
    # panel name headers (near the top of each block)
    e += [((-800, -2900), "LPP-B37-GR"), ((-460, -2900), "MCC-B37")]
    e += [((-800, -3400), "@ GROUND FLOOR"), ((-460, -3400), "@ ROOF FLOOR")]
    # LPP incomer at top of its band, two 16A outgoings below it
    e += _stack(-780, -3800, "3P", "MCB", "32A")
    e += _stack(-760, -6000, "1P", "MCB", "16A")
    e += _stack(-730, -6000, "1P", "MCB", "16A")
    # MCC incomer + a 63A and a 16A outgoing
    e += _stack(-470, -3800, "3P", "MCCB", "80A")
    e += _stack(-450, -6000, "3P", "MCCB", "63A")
    e += _stack(-430, -6000, "1P", "MCB", "16A")
    # a lower riser/main-feeder band, ~15000 below the headers
    e += _stack(-600, -18000, "3P", "MCCB", "250A")
    # a fault-level note somewhere on the sheet
    e += [((-600, -20000), "Ic.w = 25KA")]
    return e


def _by_board(comps):
    out = {}
    for c in comps:
        out.setdefault(c.board, []).append(c)
    return out


def test_detects_atomised_sheet():
    assert looks_like_panel_sld(_sheet()) is True


def test_recovers_panels_and_incomers():
    comps = extract_panel_sld(_sheet())
    boards = _by_board(comps)
    assert "LPP-B37-GR" in boards and "MCC-B37" in boards

    def incomer(board):
        return next(c for c in boards[board]
                    if c.spec.raw_attributes.get("role") == "incomer")

    lpp = incomer("LPP-B37-GR")
    assert lpp.spec.device_type.name == "MCB"
    assert lpp.spec.rating_amps == 32 and lpp.spec.poles == 3

    mcc = incomer("MCC-B37")
    assert mcc.spec.device_type.name == "MCCB"
    assert mcc.spec.rating_amps == 80


def test_sheet_fault_level_applied_to_mccb_only():
    # the sheet Ic.w note is the busbar/MCCB withstand: MCCBs pick it up, small
    # final MCBs keep their own (policy-defaulted) breaking capacity.
    comps = extract_panel_sld(_sheet())
    mccbs = [c for c in comps if c.spec.device_type.name == "MCCB"]
    assert mccbs and all(c.spec.breaking_capacity_ka == 25 for c in mccbs)
    mcbs = [c for c in comps if c.spec.device_type.name == "MCB"]
    assert all(c.spec.breaking_capacity_ka is None for c in mcbs)


def test_lower_feeder_band_not_misfiled():
    # the 250A MCCB sits ~15000 below the panel headers: it must land in the
    # review bucket, never under LPP-B37-GR or MCC-B37.
    comps = extract_panel_sld(_sheet())
    boards = _by_board(comps)
    for panel in ("LPP-B37-GR", "MCC-B37"):
        assert all(c.spec.rating_amps != 250 for c in boards[panel])
    assert any("review" in b.lower() for b in boards)


def test_outgoing_ways_captured():
    comps = extract_panel_sld(_sheet())
    boards = _by_board(comps)
    lpp_out = [c for c in boards["LPP-B37-GR"]
               if c.spec.raw_attributes.get("role") == "outgoing"]
    assert len(lpp_out) == 2
    assert all(c.spec.rating_amps == 16 for c in lpp_out)
