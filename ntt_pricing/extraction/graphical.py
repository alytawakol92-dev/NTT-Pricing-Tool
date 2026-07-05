"""Extract components from a *graphical* single line diagram.

Many real SLDs (especially consultant drawings) carry no block attributes:
the devices are drawn as geometry with free-text labels next to them.  This
extractor recovers the component list from those labels:

* **Panels** are detected from board-name texts (e.g. "DP-REST BECH") and
  each device is assigned to the nearest panel by position.
* **Outgoing ways** are read from the multi-line breaker labels
  ``"50A / 10KA / MCB / ELCB / 30mA"`` — each becomes an MCB plus, when an
  ELCB/RCCB is noted, a matching residual-current device (as NTT quote them).
* **Incomers** are read from an ``MCCB`` label with a nearby frame/setting
  (``150/160``) and breaking capacity (``Isc = 18KA``).
* Identical ways are **aggregated** into a single line with a quantity, so
  the bill of materials reads ``4 × MCB 50A`` rather than four rows.

Pole count is not present in these text labels (it is shown graphically), so
it is inferred with a documented heuristic and flagged; supply a load
schedule with a phases column to override it.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from ..models import Component, DeviceType, Specification
from .specs import parse_specification


# ---- text cleaning --------------------------------------------------------
_FONT_RE = re.compile(r"\\[A-Za-z][^;\\]*;")   # inline MTEXT font codes  \fArial|..;
_FMT_RE = re.compile(r"[{}]|\\P|\\~")
_UNDERSCORES = re.compile(r"[_]{2,}")


def _clean(text: str) -> str:
    text = _FONT_RE.sub(" ", text)
    text = _FMT_RE.sub(" ", text)
    text = _UNDERSCORES.sub(" ", text)
    return text.strip()


# ---- recognisers ----------------------------------------------------------
_BREAKER_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*A\b", re.IGNORECASE)
_KA_RE = re.compile(r"(\d+(?:\.\d+)?)\s*KA", re.IGNORECASE)
_FRAME_RE = re.compile(r"\b(\d+)\s*/\s*(\d+)\b")          # 150/160 = trip/frame
_XMULT_RE = re.compile(r"^X\s*(\d+)$", re.IGNORECASE)
_LOAD_TOTAL_RE = re.compile(r"[DC]\.?LOAD", re.IGNORECASE)


def is_graphical(texts: List[str]) -> bool:
    """Heuristic: the drawing is a graphical SLD if several free-text labels
    look like breaker specs."""
    hits = sum(1 for t in texts
               if ("MCB" in t.upper() or "MCCB" in t.upper()) and _BREAKER_RE.search(t))
    return hits >= 3


# ---- main -----------------------------------------------------------------
class _Text:
    __slots__ = ("x", "y", "raw", "clean")

    def __init__(self, x, y, raw):
        self.x, self.y = x, y
        self.raw = raw
        self.clean = _clean(raw)


def extract_graphical(entries: List[Tuple[Tuple[float, float], str]],
                      *, pole_threshold_a: float = 25.0) -> List[Component]:
    """entries: list of ((x, y), raw_text).  Returns aggregated components."""
    texts = [_Text(p[0], p[1], t) for p, t in entries if t and t.strip()]

    panels = _detect_panels(texts)
    xmults = [(t.x, t.y, int(m.group(1)))
              for t in texts for m in [_XMULT_RE.match(t.clean)] if m]

    raw_devices: List[Tuple[str, Specification, int]] = []  # (board, spec, qty)
    incomers: Dict[str, Specification] = {}

    for t in texts:
        line = t.clean
        upper = line.upper()
        board = _nearest_panel(t, panels)

        # incomer: an MCCB label
        if "MCCB" in upper and "MCB" not in upper.replace("MCCB", ""):
            spec = _parse_incomer(t, texts)
            # keep the highest-rated incomer per board
            cur = incomers.get(board)
            if cur is None or (spec.rating_amps or 0) > (cur.rating_amps or 0):
                incomers[board] = spec
            continue

        # outgoing way: an MCB label (possibly with ELCB)
        if "MCB" in upper and _BREAKER_RE.search(line):
            spec = _parse_way(line)
            if spec.rating_amps is None:
                continue
            spec.poles = 3 if spec.rating_amps >= pole_threshold_a else 1
            qty = _nearest_xmult(t, xmults)
            raw_devices.append((board, spec, qty))
            # matching ELCB / RCCB when noted
            if "ELCB" in upper or "RCCB" in upper or "30MA" in upper.replace(" ", ""):
                raw_devices.append((board, _rccb_for(spec), qty))

    components = _aggregate(incomers, raw_devices, panels)
    return components


# ---- panel detection ------------------------------------------------------
class _Panel:
    __slots__ = ("name", "x", "y")

    def __init__(self, name, x, y):
        self.name, self.x, self.y = name, x, y


def _detect_panels(texts: List[_Text]) -> List[_Panel]:
    # board names sit near the D.LOAD / C.LOAD totals; use those as anchors.
    anchors = [t for t in texts if _LOAD_TOTAL_RE.search(t.clean)]
    panels: List[_Panel] = []
    used = set()
    for a in anchors:
        # nearest short name-like text that is not itself a load total / number
        best = None
        best_d = None
        for t in texts:
            if t is a or _LOAD_TOTAL_RE.search(t.clean):
                continue
            if not _looks_like_panel_name(t.clean):
                continue
            d = math.hypot(t.x - a.x, t.y - a.y)
            if best_d is None or d < best_d:
                best, best_d = t, d
        if best is not None and best.clean not in used:
            panels.append(_Panel(best.clean, best.x, best.y))
            used.add(best.clean)
    if not panels:
        panels.append(_Panel("MDB", 0.0, 0.0))
    return panels


def _looks_like_panel_name(s: str) -> bool:
    s = s.strip()
    if not (3 <= len(s) <= 24):
        return False
    if _BREAKER_RE.search(s) or _XMULT_RE.match(s):
        return False
    letters = sum(c.isalpha() for c in s)
    # a board name is mostly letters, often with a hyphen (DP-REST BECH)
    return letters >= 3 and any(c.isalpha() for c in s) and "MCB" not in s.upper()


def _nearest_panel(t: _Text, panels: List[_Panel]) -> str:
    if len(panels) == 1:
        return panels[0].name
    best, best_d = panels[0], None
    for p in panels:
        # panels are stacked vertically → weight Y distance more
        d = abs(t.y - p.y) + 0.15 * abs(t.x - p.x)
        if best_d is None or d < best_d:
            best, best_d = p, d
    return best.name


# ---- parsing helpers ------------------------------------------------------
def _parse_way(line: str) -> Specification:
    spec = Specification(device_type=DeviceType.MCB)
    m = _BREAKER_RE.search(line)
    if m:
        spec.rating_amps = float(m.group(1))
    k = _KA_RE.search(line)
    if k:
        spec.breaking_capacity_ka = float(k.group(1))
    spec.raw_attributes["text"] = line
    return spec


def _parse_incomer(t: _Text, texts: List[_Text]) -> Specification:
    spec = Specification(device_type=DeviceType.MCCB)
    # look at the label itself and nearby texts for frame / setting / kA
    nearby = [t] + _neighbours(t, texts, radius=8000)
    for n in nearby:
        fm = _FRAME_RE.search(n.clean)
        if fm and spec.rating_amps is None:
            spec.trip_amps = float(fm.group(1))     # setting, e.g. 150
            spec.rating_amps = float(fm.group(2))   # frame, e.g. 160
        km = _KA_RE.search(n.clean)
        if km and spec.breaking_capacity_ka is None:
            spec.breaking_capacity_ka = float(km.group(1))
    if spec.rating_amps is None:
        bm = _BREAKER_RE.search(t.clean)
        if bm:
            spec.rating_amps = float(bm.group(1))
    spec.poles = 3
    spec.raw_attributes["text"] = "MCCB " + (t.clean or "")
    return spec


def _rccb_for(mcb: Specification) -> Specification:
    """The residual-current device NTT pair with an outgoing MCB."""
    amps = mcb.rating_amps or 25.0
    # RCCB sized at the next standard rating >= the MCB
    for r in (25, 40, 63, 80, 100, 125):
        if amps <= r:
            amps = r
            break
    spec = Specification(device_type=DeviceType.RCCB, rating_amps=amps,
                         poles=(4 if (mcb.poles or 1) >= 3 else 2))
    spec.raw_attributes["residual_ma"] = 30
    return spec


def _neighbours(t: _Text, texts: List[_Text], radius: float) -> List[_Text]:
    return [o for o in texts if o is not t and
            math.hypot(o.x - t.x, o.y - t.y) <= radius]


def _nearest_xmult(t: _Text, xmults) -> int:
    best, best_d = 1, None
    for x, y, n in xmults:
        d = math.hypot(x - t.x, y - t.y)
        if best_d is None or d < best_d:
            best, best_d = n, d
    # only trust a multiplier that is genuinely adjacent
    return best if best_d is not None and best_d < 4000 else 1


# ---- aggregation ----------------------------------------------------------
def _aggregate(incomers: Dict[str, Specification],
               raw_devices: List[Tuple[str, Specification, int]],
               panels: List[_Panel]) -> List[Component]:
    components: List[Component] = []
    tag_seq = 0

    # incomers first, one per board
    for board, spec in incomers.items():
        tag_seq += 1
        components.append(Component(
            tag=f"Q{tag_seq}", raw_description=spec.raw_attributes.get("text", "MCCB"),
            spec=spec, quantity=1, board=board))

    # aggregate identical outgoing devices per board
    buckets: Dict[Tuple, int] = defaultdict(int)
    order: List[Tuple] = []
    for board, spec, qty in raw_devices:
        key = (board, spec.device_type, spec.rating_amps, spec.poles,
               spec.breaking_capacity_ka)
        if key not in buckets:
            order.append((key, spec))
        buckets[key] += qty

    for key, spec in order:
        board = key[0]
        tag_seq += 1
        desc = _way_description(spec)
        components.append(Component(
            tag=f"Q{tag_seq}", raw_description=desc, spec=spec,
            quantity=buckets[key], board=board))
    return components


def _way_description(spec: Specification) -> str:
    if spec.device_type == DeviceType.RCCB:
        return (f"ELCB / RCCB {spec.poles}P {spec.rating_amps:g}A 30mA")
    ka = f" {spec.breaking_capacity_ka:g}KA" if spec.breaking_capacity_ka else ""
    return f"MCB {spec.poles}P {spec.rating_amps:g}A{ka}"
