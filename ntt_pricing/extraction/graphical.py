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

# riser / feeder notations
_AT_RE = re.compile(r"(\d+)\s*AT\b", re.IGNORECASE)        # trip rating
_AF_RE = re.compile(r"(\d+)\s*AF\b", re.IGNORECASE)        # frame rating
_TP_MCCB_RE = re.compile(r"(\d+)\s*A\s*TP\s*MCCB", re.IGNORECASE)
_A_KA_RE = re.compile(r"(\d+)\s*A\s*-\s*(\d+)\s*KA", re.IGNORECASE)
_IC60_RE = re.compile(r"IC\s*60[HNCL]?\s*C?\s*(\d+)", re.IGNORECASE)
_CONTACTOR_RE = re.compile(r"CONTA?CT?OR", re.IGNORECASE)  # 'contactor' / 'contator'
_POLE3_RE = re.compile(r"\b3\s*P\b|\b3\s*PH\b|\bTP\b|3\s*PH", re.IGNORECASE)
_ONLY_AMPS_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*A\s*$", re.IGNORECASE)
_CABLE_RE = re.compile(r"XLPE|AL/|EARTH|mm[²2]|CU\.", re.IGNORECASE)
_LOAD_RE = re.compile(r"KVA|KW|K\.V\.A", re.IGNORECASE)

# board-name keywords (a text like "DB-KWHM", "FLAT - 1", "MDB-TYPE 2")
_BOARD_KW = re.compile(r"\b(MDB|SMDB|EMDB|SDB|DB|MCC|FLAT|PANEL)\b", re.IGNORECASE)
_HEADER_RE = re.compile(r"REF\.?:|LOAD\b|QTY|TYPE OF|D\.F|IP\b|K\.V\.A|\bF\.F\.L", re.IGNORECASE)


def is_graphical(texts: List[str]) -> bool:
    """Heuristic: the drawing is a graphical SLD if several free-text labels
    look like breaker specs (MCB/MCCB ratings, AT/AF frames, IC60 MCBs)."""
    hits = 0
    for t in texts:
        u = t.upper()
        if (("MCB" in u or "MCCB" in u) and _BREAKER_RE.search(t)) or \
                _AT_RE.search(t) or _AF_RE.search(t) or _IC60_RE.search(t) or \
                _TP_MCCB_RE.search(t):
            hits += 1
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

        spec, has_elcb = _parse_device(line, t, texts, pole_threshold_a)
        if spec is None:
            continue

        qty = _nearest_xmult(t, xmults)
        raw_devices.append((board, spec, qty))
        if has_elcb:
            raw_devices.append((board, _rccb_for(spec), qty))

    # incomers are chosen per board by the offer builder; none pre-assigned here
    components = _aggregate(incomers, raw_devices, panels)
    return components


def _parse_device(line: str, t: "_Text", texts: List["_Text"],
                  pole_threshold_a: float):
    """Return (Specification | None, has_elcb).  Recognises MCCB/MCB/contactor
    labels in the many notations real drawings use."""
    up = line.upper()

    # reject non-device labels: cables, load figures, schedule headers, boards
    if _CABLE_RE.search(line):
        return None, False
    if _LOAD_RE.search(line) and not any(k in up for k in ("MCB", "MCCB", "ACB")):
        return None, False
    if _HEADER_RE.search(line) and not _BREAKER_RE.search(line) and not _AF_RE.search(line):
        return None, False
    if _is_board_name(line):
        return None, False

    has_elcb = "ELCB" in up or "RCCB" in up or "30MA" in up.replace(" ", "")

    # ---- MCCB (frame/trip, TP MCCB, A-kA, or MCCB keyword) ----
    is_mccb = ("MCCB" in up or "M.C.C.B" in up or _AF_RE.search(line)
               or _TP_MCCB_RE.search(line) or _A_KA_RE.search(line))
    # an "AT"-only trip label with no frame is a setting for a nearby breaker
    if not is_mccb and _AT_RE.search(line) and not _AF_RE.search(line):
        return None, False
    if is_mccb:
        return _mccb_spec(line, t, texts), False

    # ---- MCB (iC60 / MCB keyword) ----
    if "MCB" in up or _IC60_RE.search(line):
        spec = Specification(device_type=DeviceType.MCB)
        ic = _IC60_RE.search(line)
        m = _BREAKER_RE.search(line)
        if ic:
            spec.rating_amps = float(ic.group(1))
        elif m:
            spec.rating_amps = float(m.group(1))
        k = _KA_RE.search(line)
        if k:
            spec.breaking_capacity_ka = float(k.group(1))
        if spec.rating_amps is None:
            return None, False
        spec.poles = 3 if _POLE3_RE.search(line) or spec.rating_amps >= pole_threshold_a else 1
        spec.raw_attributes["text"] = line
        return spec, has_elcb

    # ---- contactor ----
    if _CONTACTOR_RE.search(line):
        m = _BREAKER_RE.search(line)
        spec = Specification(device_type=DeviceType.CONTACTOR,
                             rating_amps=float(m.group(1)) if m else None,
                             poles=3 if _POLE3_RE.search(line) else 3)
        spec.raw_attributes["text"] = line
        return (spec, False) if spec.rating_amps else (None, False)

    # ---- bare rating in a schedule (e.g. "16 A") → a modular MCB ----
    m = _ONLY_AMPS_RE.match(line)
    if m:
        amps = float(m.group(1))
        if amps > 125:            # a bare large rating is usually a feeder note
            return None, False
        spec = Specification(device_type=DeviceType.MCB, rating_amps=amps,
                             poles=3 if amps >= pole_threshold_a else 1)
        spec.raw_attributes["text"] = line
        return spec, False

    return None, False


def _mccb_spec(line: str, t: "_Text", texts: List["_Text"]) -> Specification:
    spec = Specification(device_type=DeviceType.MCCB, poles=3)
    # frame (AF) preferred as the rated current; look at neighbours too because
    # riser drawings split "150AT" and "160AF" into separate labels.
    scope = [line] + [n.clean for n in _neighbours(t, texts, 2500)]
    for s in scope:
        af = _AF_RE.search(s)
        if af:
            spec.rating_amps = float(af.group(1))
            break
    for s in scope:
        at = _AT_RE.search(s)
        if at:
            spec.trip_amps = float(at.group(1))
            break
    if spec.rating_amps is None:
        ak = _A_KA_RE.search(line)
        if ak:
            spec.rating_amps = float(ak.group(1))
    if spec.rating_amps is None:
        tp = _TP_MCCB_RE.search(line)
        if tp:
            spec.rating_amps = float(tp.group(1))
    if spec.rating_amps is None:
        for s in scope:
            fr = _FRAME_RE.search(s)
            if fr:
                spec.trip_amps, spec.rating_amps = float(fr.group(1)), float(fr.group(2))
                break
    if spec.rating_amps is None:
        m = _BREAKER_RE.search(line)
        if m:
            spec.rating_amps = float(m.group(1))
    for s in scope:
        k = _KA_RE.search(s)
        if k:
            spec.breaking_capacity_ka = float(k.group(1))
            break
    spec.raw_attributes["text"] = "MCCB " + line
    return spec


# ---- panel detection ------------------------------------------------------
class _Panel:
    __slots__ = ("name", "x", "y")

    def __init__(self, name, x, y):
        self.name, self.x, self.y = name, x, y


def _detect_panels(texts: List[_Text]) -> List[_Panel]:
    """Detect panels two ways and keep whichever yields more boards:

    1. explicit board-name labels (``DB-KWHM``, ``FLAT - 1``, ``MDB-TYPE 2``);
    2. names sitting next to the D.LOAD / C.LOAD schedule totals.
    """
    by_name = _panels_by_name(texts)
    by_anchor = _panels_by_anchor(texts)
    panels = by_name if len(by_name) >= len(by_anchor) else by_anchor
    if not panels:
        panels.append(_Panel("MDB", 0.0, 0.0))
    return panels


def _panels_by_name(texts: List[_Text]) -> List[_Panel]:
    panels: List[_Panel] = []
    used = set()
    for t in texts:
        s = _norm_board(t.clean)
        if _is_board_name(t.clean) and s not in used:
            panels.append(_Panel(s, t.x, t.y))
            used.add(s)
    return panels


def _panels_by_anchor(texts: List[_Text]) -> List[_Panel]:
    anchors = [t for t in texts if _LOAD_TOTAL_RE.search(t.clean)]
    panels: List[_Panel] = []
    used = set()
    for a in anchors:
        best, best_d = None, None
        for t in texts:
            if t is a or _LOAD_TOTAL_RE.search(t.clean):
                continue
            if not _looks_like_name(t.clean):
                continue
            d = math.hypot(t.x - a.x, t.y - a.y)
            if best_d is None or d < best_d:
                best, best_d = t, d
        if best is not None and best.clean not in used:
            panels.append(_Panel(best.clean, best.x, best.y))
            used.add(best.clean)
    return panels


def _is_board_name(s: str) -> bool:
    s = s.strip()
    if not (3 <= len(s) <= 26):
        return False
    if _HEADER_RE.search(s) or _BREAKER_RE.search(s) or _AF_RE.search(s):
        return False
    if any(k in s.upper() for k in ("MCB", "MCCB", "CONTACTOR", "CABLE", "BUSBAR",
                                    "METER", "EARTH", "CONDUIT", "TRAY", "RISER",
                                    "FROM", "TO ", "TYPICAL", "SPACE", "SPARE",
                                    "LOCATION", "VERTICAL")):
        return False
    return bool(_BOARD_KW.search(s))


def _norm_board(s: str) -> str:
    # tidy "DB- GROUND FLOOR" / "FLAT - 1" spacing
    return re.sub(r"\s*-\s*", "-", s.strip()).replace("  ", " ")


def _looks_like_name(s: str) -> bool:
    s = s.strip()
    if not (3 <= len(s) <= 24):
        return False
    if _BREAKER_RE.search(s) or _XMULT_RE.match(s):
        return False
    letters = sum(c.isalpha() for c in s)
    return letters >= 3 and "MCB" not in s.upper()


def _nearest_panel(t: _Text, panels: List[_Panel]) -> str:
    if len(panels) == 1:
        return panels[0].name
    best, best_d = panels[0], None
    for p in panels:
        d = math.hypot(t.x - p.x, t.y - p.y)
        if best_d is None or d < best_d:
            best, best_d = p, d
    return best.name


# ---- parsing helpers ------------------------------------------------------
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
