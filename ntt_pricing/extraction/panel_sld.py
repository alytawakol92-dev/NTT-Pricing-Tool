"""Extract components from a *panel-schedule* single line diagram.

Consultant SLDs for a whole building often draw several distribution boards
side by side on one sheet, and — unlike the graphical drawings handled by
:mod:`graphical` — they **atomise every label into separate text entities**.
A single breaker is drawn as three independent pieces of text stacked in a
column::

        3P            <- poles      (above the symbol)
        MCB           <- device     (the symbol label)
        32A           <- rating     (below the symbol)

The other readers expect a device and its rating to live in one string, so
they see ``"MCB"`` and ``"32A"`` as unrelated tokens and recover nothing.

This reader instead works geometrically:

1. classify every text token (device word / rating / poles / panel name /
   cable / load / noise);
2. rebuild each device by pairing a ``MCB``/``MCCB`` word with the rating
   token directly **below** it and the pole token directly **above** it
   (small, well-tested x/y tolerances);
3. detect the panels from their name headers (``LPP-B37-GR``, ``MCC-B37`` …)
   and assign each device to the panel whose header column it sits under;
4. mark the top-most device in each panel (the one fed by a ``FROM …`` cable)
   as the incomer.

The output is a flat list of :class:`Component` with ``board`` populated, so
the offer builder groups them into INCOMING / OUTGOING exactly as for the
other formats and adds the standard NTT indication + enclosure set.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from ..models import Component, DeviceType, Specification

# ---- token recognisers ----------------------------------------------------
_DEVICE_RE = re.compile(r"^(M\.?C\.?C\.?B|MCB|ELCB|RCCB|RCBO|ACB)\.?$", re.I)
_RATING_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*A$", re.I)
_POLE_RE = re.compile(r"^([1234])\s*P$", re.I)
_KA_RE = re.compile(r"(\d+(?:\.\d+)?)\s*K\.?\s*A", re.I)
# a panel-name header: LPP-B37-GR, ELPP-B36-FR, MCC-B44, UDP-B37, UDB-36,
# DB-B34-SC, SMDB-B37, EDB-B35-SER …
_PANEL_RE = re.compile(
    r"^(E?SM?DB|E?LPP|MCC|U?DB|UDP|EDB|DB|SDB|MDB)[-\s]?[A-Z]?\d{0,3}[-\s]?[A-Z0-9]{0,4}$",
    re.I)
_FROM_RE = re.compile(r"\b(FROM|FEEDING\s+FROM)\b", re.I)
_SPARE_RE = re.compile(r"\bSPARE\b", re.I)


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip()


class _Tok:
    __slots__ = ("x", "y", "t")

    def __init__(self, x, y, t):
        self.x, self.y, self.t = x, y, _norm(t)


def looks_like_panel_sld(entries: List[Tuple[Tuple[float, float], str]]) -> bool:
    """True when the drawing has many *standalone* device words and *standalone*
    rating tokens — the atomised layout this reader targets (as opposed to the
    combined ``"50A MCB"`` labels the graphical reader handles)."""
    dev = rat = 0
    for _p, t in entries:
        s = _norm(t)
        if _DEVICE_RE.match(s):
            dev += 1
        elif _RATING_RE.match(s):
            rat += 1
    return dev >= 4 and rat >= 4


# ---- geometry tolerances (drawing units) ---------------------------------
# ratings sit ~180-260 below the device word, sharing its x within ~130;
# poles sit ~520-620 above the device word, within ~650 in x.
_X_RATING = 150.0
_Y_RATING = (60.0, 340.0)      # (min, max) drop below the device
_X_POLE = 700.0
_Y_POLE = (300.0, 900.0)       # rise above the device


def _device_type(word: str) -> DeviceType:
    w = word.upper().replace(".", "")
    if w == "MCCB":
        return DeviceType.MCCB
    if w == "ACB":
        return DeviceType.ACB
    if w in ("ELCB", "RCCB", "RCBO"):
        return DeviceType.RCCB if hasattr(DeviceType, "RCCB") else DeviceType.MCB
    return DeviceType.MCB


def _pair_rating(dev: _Tok, ratings: List[_Tok]) -> Optional[float]:
    best = None
    best_dy = None
    for r in ratings:
        dy = dev.y - r.y                      # positive => below the device
        if _Y_RATING[0] <= dy <= _Y_RATING[1] and abs(r.x - dev.x) <= _X_RATING:
            if best_dy is None or dy < best_dy:
                best_dy, best = dy, r
    if best is None:
        return None
    return float(_RATING_RE.match(best.t).group(1))


def _pair_poles(dev: _Tok, poles: List[_Tok]) -> Optional[int]:
    best = None
    best_dy = None
    for p in poles:
        dy = p.y - dev.y                      # positive => above the device
        if _Y_POLE[0] <= dy <= _Y_POLE[1] and abs(p.x - dev.x) <= _X_POLE:
            if best_dy is None or dy < best_dy:
                best_dy, best = dy, p
    if best is None:
        return None
    return int(_POLE_RE.match(best.t).group(1))


def _detect_panels(toks: List[_Tok]) -> List[Tuple[float, float, str]]:
    """Return (x, y, name) for every panel-name header, keeping the highest
    (top-most) occurrence of each distinct name."""
    seen: Dict[str, Tuple[float, float, str]] = {}
    for t in toks:
        s = t.t
        if _PANEL_RE.match(s) and any(ch.isdigit() for ch in s):
            key = s.upper()
            if key not in seen or t.y > seen[key][1]:
                seen[key] = (t.x, t.y, s)
    return list(seen.values())


# a panel schedule hangs at most this far below its name header; anything
# deeper is a *different* band on the sheet (a main-feeder / riser diagram)
# and must not be filed under the distribution panel sitting above it.
_SCHED_DEPTH = 11000.0


def _assign_panel(dev_x: float, dev_y: float,
                  panels: List[Tuple[float, float, str]]) -> Optional[str]:
    """Assign the device to the panel whose name header sits above it and is
    horizontally nearest.  Returns ``None`` when the device is not within any
    panel's schedule band (e.g. a lower main-feeder diagram)."""
    if not panels:
        return None
    best = None
    best_dx = None
    for px, py, name in panels:
        # header must be above the device and within the schedule depth
        if not (0.0 <= (py - dev_y) <= _SCHED_DEPTH):
            continue
        dx = abs(px - dev_x)
        if best_dx is None or dx < best_dx:
            best_dx, best = dx, name
    return best


def extract_panel_sld(entries: List[Tuple[Tuple[float, float], str]]
                      ) -> List[Component]:
    toks = [_Tok(p[0], p[1], t) for p, t in entries if t and t.strip()]

    devices = [t for t in toks if _DEVICE_RE.match(t.t)]
    ratings = [t for t in toks if _RATING_RE.match(t.t)]
    poles = [t for t in toks if _POLE_RE.match(t.t)]
    froms = [t for t in toks if _FROM_RE.search(t.t)]
    panels = _detect_panels(toks)

    # sheet-wide fault level, if a "… KA" note is present anywhere
    sheet_ka = None
    for t in toks:
        m = _KA_RE.search(t.t)
        if m:
            sheet_ka = float(m.group(1))
            break

    built: List[Tuple[str, Specification, float, float]] = []  # board, spec, x, y
    for d in devices:
        rating = _pair_rating(d, ratings)
        if rating is None:
            continue                          # a device word with no rating: skip
        dtype = _device_type(d.t)
        p = _pair_poles(d, poles)
        if p is None:
            # no pole token drawn: MCCBs are 3-phase; small MCBs single-phase
            p = 3 if dtype in (DeviceType.MCCB, DeviceType.ACB) or rating >= 32 else 1
        spec = Specification(device_type=dtype, rating_amps=rating, poles=p)
        # a sheet-wide Ic.w note is the busbar/MCCB withstand; apply it only to
        # the moulded-case devices.  Small final MCBs keep their own (lower)
        # breaking capacity, which the selection policy defaults sensibly — this
        # avoids over-specifying every 16A way to the main fault level.
        if sheet_ka and dtype in (DeviceType.MCCB, DeviceType.ACB):
            spec.breaking_capacity_ka = sheet_ka
        board = _assign_panel(d.x, d.y, panels)
        if board is None:
            # a device outside every panel's schedule band — usually a lower
            # main-feeder / riser diagram on the same sheet.  Keep it, but in a
            # clearly-flagged bucket so the engineer reviews it rather than it
            # being silently misfiled under a distribution panel.
            board = "MAIN-FEEDERS (review)"
        built.append((board, spec, d.x, d.y))

    # mark the top-most device of each board as its incomer (it is the one fed
    # by the "FROM …" cable); everything else is an outgoing way.
    top_of_board: Dict[str, float] = {}
    for board, spec, x, y in built:
        if board not in top_of_board or y > top_of_board[board]:
            top_of_board[board] = y

    components: List[Component] = []
    counters: Dict[str, int] = defaultdict(int)
    for board, spec, x, y in built:
        is_incomer = abs(y - top_of_board[board]) < 1.0
        role = "incomer" if is_incomer else "outgoing"
        counters[board] += 1
        dt = spec.device_type.name if hasattr(spec.device_type, "name") else "MCB"
        desc = f"{dt} , {spec.poles}P , {int(spec.rating_amps)}A"
        if spec.breaking_capacity_ka:
            desc += f" , {int(spec.breaking_capacity_ka)}KA"
        spec.raw_attributes["role"] = role
        components.append(Component(
            tag=f"{board}-Q{counters[board]}",
            raw_description=desc,
            spec=spec,
            board=board,
        ))
    return components
