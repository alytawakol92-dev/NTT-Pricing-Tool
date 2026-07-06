"""Reconstruct components from scattered SLD text tokens (PDF exports).

In a PDF-exported single line diagram the label of one circuit is split into
separate tokens placed at different points: the rating (``16A,1∅``), the
device keyword (``MCB``), and the quantity (``X9``) rarely share a position.
This module re-associates them spatially:

* every *rating* token becomes a candidate device (its pole count read from
  the ``∅`` / ``PH`` phase notation);
* its device *type* is taken from the nearest type keyword (MCB, contactor,
  earth-leakage…), defaulting to MCB — the norm on a distribution board;
* its *quantity* is the nearest ``X<n>`` multiplier (associated by row, since
  quantities sit in a column beside the ratings);
* identical devices are aggregated into ``N × …`` lines.

The board name is taken from a ``FROM <SOURCE>`` / board-title token when
present.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import List, Optional, Tuple

from ..models import Component, DeviceType, Specification

# rating with optional phase, e.g. "16A,1∅", "32A,3∅", "63A"
_RATING_RE = re.compile(r"(\d+(?:\.\d+)?)\s*A\b", re.IGNORECASE)
_PHASE_RE = re.compile(r"(\d)\s*(?:∅|Ø|ø|Φ|φ|PH\b|PHASE)", re.IGNORECASE)
_XMULT_RE = re.compile(r"^X\s*(\d+)$", re.IGNORECASE)
_KA_RE = re.compile(r"(\d+(?:\.\d+)?)\s*K\.?\s*A\b", re.IGNORECASE)

# type keywords → device type
_TYPE_KEYWORDS = [
    ("EARTH LEAKAGE", DeviceType.RCD), ("ELCB", DeviceType.RCD),
    ("RCCB", DeviceType.RCCB), ("RCBO", DeviceType.RCD),
    ("CONTACTOR", DeviceType.CONTACTOR),
    ("MCCB", DeviceType.MCCB), ("ACB", DeviceType.ACB),
    ("ISOLATOR", DeviceType.ISOLATOR), ("SWITCH DISCONNECTOR", DeviceType.ISOLATOR),
    ("MCB", DeviceType.MCB),
]
# tokens that are never a device (cables, conduits, system data, notes)
_NOISE_RE = re.compile(
    r"MM2|MM²|XLPE|PVC|CABLE|CONDUIT|KVA|KV\b|HZ|VAC|VOLT|SPARE|SPACE|LAMP|"
    r"INDICATOR|SELECTOR|TIMER|PHOTO|LANDSCAPE|LIGHTING|INSIDE|T\.L|AC1|AC3",
    re.IGNORECASE)
_SOURCE_RE = re.compile(r"\bFROM\b", re.IGNORECASE)
_BOARD_TOKEN_RE = re.compile(r"\b([EFS]?M?DB[-\w]*|PANEL[-\w]*)\b", re.IGNORECASE)


class _Tok:
    __slots__ = ("x", "y", "t")

    def __init__(self, x, y, t):
        self.x, self.y, self.t = x, y, t


def extract_scattered(entries: List[Tuple[Tuple[float, float], str]]
                      ) -> List[Component]:
    toks = [_Tok(p[0], p[1], t.strip()) for p, t in entries if t and t.strip()]
    if not toks:
        return []

    # MCCB feeder schedules write ratings as separate "63" "AT" / "100" "AF"
    # (trip / frame) tokens — reconstruct those first.
    atf = _extract_atf(toks)
    if atf:
        return atf

    rating_toks = [tk for tk in toks if _RATING_RE.search(tk.t)
                   and not _KA_RE.search(tk.t) and not _NOISE_RE.search(tk.t)]
    if len(rating_toks) < 2:
        return []

    type_toks = _type_tokens(toks)
    xmults = [(tk.x, tk.y, int(m.group(1)))
              for tk in toks for m in [_XMULT_RE.match(tk.t)] if m]
    board = _board_name(toks)

    # the incomer is the highest-rated breaker; it carries no X-multiplier
    incomer_tk = max(rating_toks, key=lambda t: float(_RATING_RE.search(t.t).group(1)))

    # assign each X-multiplier to the nearest *outgoing* rating (by row), so the
    # incomer never absorbs an outgoing quantity
    qty_of = _assign_quantities(rating_toks, incomer_tk, xmults)

    raw: List[Tuple[Specification, int]] = []
    for tk in rating_toks:
        m = _RATING_RE.search(tk.t)
        amps = float(m.group(1))
        has_phase = bool(_PHASE_RE.search(tk.t))
        poles = _poles(tk, toks)
        dtype = _nearest_type(tk, type_toks, has_phase)
        spec = Specification(device_type=dtype, rating_amps=amps, poles=poles)
        if dtype in (DeviceType.RCD, DeviceType.RCCB):
            spec.raw_attributes["residual_ma"] = 30
        qty = 1 if tk is incomer_tk else qty_of.get(id(tk), 1)
        raw.append((spec, qty))

    return _aggregate(raw, board)


def _assign_quantities(rating_toks, incomer_tk, xmults):
    """Give each X<n> multiplier to the nearest outgoing rating token (row
    based).  Ratings with no multiplier default to quantity 1."""
    out = {}
    outgoing = [t for t in rating_toks if t is not incomer_tk]
    for x, y, n in xmults:
        best, best_score = None, None
        for t in outgoing:
            dy = abs(y - t.y)
            if dy > 220:
                continue
            score = dy + 0.1 * abs(x - t.x)
            if best_score is None or score < best_score:
                best, best_score = t, score
        if best is not None:
            out[id(best)] = out.get(id(best), 0) + n
    return out


_NUM_RE = re.compile(r"^\d+$")
_ATF_BOARD_RE = re.compile(r"\b(MDB|SMDB|EMDB|MSB|MCC|MDBP?)\b", re.IGNORECASE)


def _extract_atf(toks: List[_Tok]) -> List[Component]:
    """Reconstruct MCCB feeders from split trip/frame tokens: "63" "AT",
    "100" "AF" placed next to an "MCCB" symbol (common in PDF MDB SLDs)."""
    at_toks = [t for t in toks if t.t.upper() == "AT"]
    af_toks = [t for t in toks if t.t.upper() == "AF"]
    mccb_toks = [t for t in toks if "MCCB" in t.t.upper()]
    if len(af_toks) < 2 or not mccb_toks:
        return []

    numbers = [t for t in toks if _NUM_RE.match(t.t)]

    def value_at(marker: _Tok) -> Optional[int]:
        # the trip number sits directly above its "AT" and the frame number
        # above its "AF" — weight column (x) alignment so the two don't cross.
        best, best_s = None, None
        for n in numbers:
            dx, dy = abs(n.x - marker.x), abs(n.y - marker.y)
            if math.hypot(dx, dy) > 70:
                continue
            score = dx * 3 + dy
            if best_s is None or score < best_s:
                best, best_s = int(n.t), score
        return best

    def nearest(marker: _Tok, group) -> Optional[_Tok]:
        best, best_d = None, None
        for g in group:
            d = math.hypot(g.x - marker.x, g.y - marker.y)
            if d < 140 and (best_d is None or d < best_d):
                best, best_d = g, d
        return best

    system_ka = _system_ka(toks)
    board = _atf_board(toks)

    raw: List[Tuple[Specification, int]] = []
    for m in mccb_toks:
        af = nearest(m, af_toks)
        at = nearest(m, at_toks)
        frame = value_at(af) if af else None
        trip = value_at(at) if at else None
        rating = trip or frame           # trip = actual rated current
        if not rating:
            continue
        spec = Specification(device_type=DeviceType.MCCB, rating_amps=float(rating),
                             poles=3, breaking_capacity_ka=system_ka)
        if frame:
            spec.raw_attributes["frame_af"] = frame
        raw.append((spec, 1))

    return _aggregate(raw, board) if raw else []


def _system_ka(toks: List[_Tok]) -> Optional[float]:
    for t in toks:
        m = _KA_RE.search(t.t)
        if m:
            return float(m.group(1))
    # "Isc=25" style split token
    for i, t in enumerate(toks):
        if "ISC" in t.t.upper():
            mm = re.search(r"(\d+(?:\.\d+)?)", t.t)
            if mm:
                return float(mm.group(1))
    return None


def _atf_board(toks: List[_Tok]) -> str:
    for t in toks:
        if _ATF_BOARD_RE.search(t.t):
            return t.t.strip().upper()
    return "MDB"


# --------------------------------------------------------------------------
def _type_tokens(toks: List[_Tok]):
    out = []
    for tk in toks:
        up = tk.t.upper()
        for kw, dt in _TYPE_KEYWORDS:
            if kw in up:
                out.append((tk, dt))
                break
    return out


def _nearest_type(tk: _Tok, type_toks, has_phase: bool) -> DeviceType:
    best, best_d = DeviceType.MCB, None
    for ttk, dt in type_toks:
        # a phase-marked circuit (e.g. "32A,3∅") is a feeder breaker, not the
        # separately-drawn contactor — don't let the contactor keyword claim it
        if has_phase and dt == DeviceType.CONTACTOR:
            continue
        d = math.hypot(ttk.x - tk.x, ttk.y - tk.y)
        if best_d is None or d < best_d:
            best, best_d = dt, d
    if best_d is not None and best_d < 300:
        return best
    return DeviceType.MCB


def _poles(tk: _Tok, toks: List[_Tok]) -> int:
    m = _PHASE_RE.search(tk.t)
    if m:
        return int(m.group(1))
    # look for a phase note very close by
    for o in toks:
        if o is tk:
            continue
        pm = _PHASE_RE.search(o.t)
        if pm and math.hypot(o.x - tk.x, o.y - tk.y) < 120:
            return int(pm.group(1))
    return 1


def _nearest_qty(tk: _Tok, xmults) -> int:
    # quantities sit in a column beside the ratings → weight the row (Y) gap
    best, best_score = 1, None
    for x, y, n in xmults:
        dy = abs(y - tk.y)
        if dy > 200:
            continue
        score = dy + 0.15 * abs(x - tk.x)
        if best_score is None or score < best_score:
            best, best_score = n, score
    return best


def _board_name(toks: List[_Tok]) -> str:
    # "FROM <SOURCE>" → the upstream board; label this panel by its feed
    for i, tk in enumerate(toks):
        if _SOURCE_RE.search(tk.t):
            # nearest board-like token to the "FROM"
            cand = None
            cand_d = None
            for o in toks:
                if _BOARD_TOKEN_RE.search(o.t) and not _SOURCE_RE.search(o.t):
                    d = math.hypot(o.x - tk.x, o.y - tk.y)
                    if cand_d is None or d < cand_d:
                        cand, cand_d = o.t, d
            if cand:
                return f"DB (from {cand.strip()})"
    for tk in toks:
        if _BOARD_TOKEN_RE.search(tk.t):
            return tk.t.strip()
    return "DB"


def _aggregate(raw: List[Tuple[Specification, int]], board: str) -> List[Component]:
    buckets = defaultdict(int)
    order = []
    for spec, qty in raw:
        key = (spec.device_type, spec.rating_amps, spec.poles)
        if key not in buckets:
            order.append((key, spec))
        buckets[key] += qty

    comps: List[Component] = []
    for i, (key, spec) in enumerate(order, start=1):
        comps.append(Component(tag=f"Q{i}", raw_description=_describe(spec),
                               spec=spec, quantity=buckets[key], board=board))
    return comps


def _describe(spec: Specification) -> str:
    a = f"{spec.rating_amps:g}A" if spec.rating_amps else ""
    p = f"{spec.poles}P" if spec.poles else ""
    dt = spec.device_type
    if dt in (DeviceType.RCD, DeviceType.RCCB):
        return f"Earth leakage, ID/RCCB {p} 30mA {a}".strip()
    if dt == DeviceType.CONTACTOR:
        return f"Contactor {p} {a}".strip()
    if dt == DeviceType.MCCB:
        return f"MCCB {p} {a}".strip()
    return f"MCB {p} {a}".strip()
