"""Parse free-text device descriptions into structured :class:`Specification`.

The same parser is used for text pulled off the AutoCAD drawing and for the
descriptions in the supplier Excel sheet, so that matching compares
apples to apples.  It is deliberately tolerant of the messy, abbreviated
notation electrical drawings use ("3P 100A 36kA MCCB", "TeSys D 18.5kW",
"iC60N C16", etc.).
"""
from __future__ import annotations

import re
from typing import Optional

from ..models import DeviceType, Specification


# Ordered so the more specific / longer tokens win over generic ones.
_DEVICE_PATTERNS = [
    (DeviceType.ACB, r"\bACB\b|air\s+circuit\s+breaker|masterpact"),
    (DeviceType.MCCB, r"\bMCCB\b|moulded\s+case|compact\s*ns|compact\s*nsx|\bnsx\b"),
    (DeviceType.RCCB, r"\bRCCB\b|residual\s+current\s+circuit"),
    (DeviceType.RCD, r"\bRCD\b|\bRCBO\b|\bELCB\b|residual\s+current|vigi"),
    (DeviceType.MCB, r"\bMCB\b|miniature\s+circuit|\bic60\b|\bic60n\b|acti9|\bc60\b|multi9"),
    (DeviceType.OVERLOAD, r"overload|thermal\s+relay|\bO/?L\b|lrd|lr2"),
    (DeviceType.CONTACTOR, r"contactor|tesys|\blc1\b|\blc2\b"),
    (DeviceType.ISOLATOR, r"isolator|switch\s*disconnector|load\s*break|\bINS\b|\bINV\b|\bswitch-disconnector"),
    (DeviceType.FUSE, r"\bfuse\b|hrc|\bgg\b|\bam\b\s*fuse"),
    (DeviceType.SPD, r"\bSPD\b|surge\s+protect|surge\s+arrest|\bPRD\b|\bPRF\b|iPRD"),
    (DeviceType.CT, r"current\s+transformer|\bC\.?T\.?\b|\bCT\s*\d"),
    (DeviceType.METER, r"\bmeter\b|multimeter|power\s+meter|\bpm\d|\biem\d|energy\s+meter"),
    (DeviceType.CAPACITOR, r"capacitor|\bkvar\b|power\s+factor|varplus"),
    (DeviceType.TRANSFORMER, r"control\s+transformer|\bVA\b\s+transformer|\d+\s*VA\b"),
    (DeviceType.PLC, r"\bPLC\b|modicon|\bM221\b|\bM241\b|controller"),
    (DeviceType.PILOT, r"pilot\s+light|indicator|push\s*button|\bXB\d|selector\s+switch|harmony"),
    (DeviceType.TERMINAL, r"terminal\s+block|\bterminal\b|linergy"),
    (DeviceType.BUSBAR, r"busbar|bus\s*bar|linergy\s*bs"),
]

# Matches "curve C", "C curve", and "C16" style tripping-curve notation.
_CURVE_RE = re.compile(r"\b([BCDKZ])\s*\d", re.IGNORECASE)
_CURVE_ALT_RE = re.compile(r"\bcurve\s*([BCDKZ])\b|\b([BCDKZ])\s*curve\b", re.IGNORECASE)
_POLES_RE = re.compile(r"\b([1-4])\s*[pP]\b|\b([1-4])\s*-?\s*pole", re.IGNORECASE)
_KA_RE = re.compile(r"(\d+(?:\.\d+)?)\s*kA", re.IGNORECASE)
_AMP_RE = re.compile(r"(\d+(?:\.\d+)?)\s*A(?![a-zA-Z])")
_VOLT_RE = re.compile(r"(\d{2,4})\s*V(?![a-zA-Z])")
_MANUF_RE = re.compile(r"schneider|abb|siemens|eaton|legrand|hager|chint", re.IGNORECASE)


def parse_specification(text: str) -> Specification:
    """Parse a free-text description into a :class:`Specification`."""
    spec = Specification()
    if not text:
        return spec
    t = text.strip()

    spec.device_type = _classify_device(t)

    # poles
    m = _POLES_RE.search(t)
    if m:
        spec.poles = int(m.group(1) or m.group(2))

    # breaking capacity (kA) — resolve before generic amps so "36kA" isn't read as amps
    m = _KA_RE.search(t)
    if m:
        spec.breaking_capacity_ka = float(m.group(1))

    # rating in amps — take the first plausible amp figure, ignoring the kA one
    amps = _extract_amps(t)
    if amps is not None:
        spec.rating_amps = amps

    # voltage
    m = _VOLT_RE.search(t)
    if m:
        v = float(m.group(1))
        if 100 <= v <= 1000:
            spec.voltage = v

    # tripping curve (MCB)
    if spec.device_type in (DeviceType.MCB, DeviceType.RCD, DeviceType.UNKNOWN):
        m = _CURVE_ALT_RE.search(t)
        if m:
            spec.curve = (m.group(1) or m.group(2)).upper()
        else:
            m = _CURVE_RE.search(t)
            if m:
                spec.curve = m.group(1).upper()

    # manufacturer
    m = _MANUF_RE.search(t)
    if m:
        spec.manufacturer = m.group(0).title()

    # mounting hint
    if re.search(r"din\s*rail|din-?mount|acti9|modular", t, re.IGNORECASE):
        spec.mounting = "DIN"
    elif re.search(r"panel\s*mount|fixed|withdrawable|plug-?in", t, re.IGNORECASE):
        spec.mounting = "Panel"

    spec.raw_attributes["text"] = t
    return spec


def _classify_device(t: str) -> DeviceType:
    for dtype, pattern in _DEVICE_PATTERNS:
        if re.search(pattern, t, re.IGNORECASE):
            return dtype
    return DeviceType.UNKNOWN


def _extract_amps(t: str) -> Optional[float]:
    """Return the rated current, skipping any number immediately before 'kA'."""
    # Mask out kA figures so they are not mistaken for amps.
    masked = _KA_RE.sub(" ", t)
    candidates = [float(x) for x in _AMP_RE.findall(masked)]
    # Also catch "AF"/"AT" frame/trip notation e.g. 250AF 200AT
    frame = re.search(r"(\d+(?:\.\d+)?)\s*AF\b", t, re.IGNORECASE)
    trip = re.search(r"(\d+(?:\.\d+)?)\s*AT\b", t, re.IGNORECASE)
    if trip:
        return float(trip.group(1))
    if frame:
        return float(frame.group(1))
    if candidates:
        # Prefer the largest reasonable current rating found.
        plausible = [c for c in candidates if 0.5 <= c <= 6300]
        if plausible:
            return max(plausible)
    return None
