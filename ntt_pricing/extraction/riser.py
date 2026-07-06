"""Extract a board/feeder-level component list from a power *riser* diagram.

Riser (system-overview) drawings are laid out very differently from panel
schedules: the per-floor distribution-board schedules are small stamped
tables, often drawn as repeated blocks.  When a drawing is converted from
DWG the table cell positions can collapse onto a point, which destroys any
chance of a position-based reconstruction — but the **entity reading order**
still preserves each table as a contiguous run.

This parser works from that reading order.  It segments the text stream into
the recurring floor-DB tables, and from each one reads the board name, the
incomer feeder (MCCB) and the outgoing flat feeders (sized from the declared
flat load).  It also captures the MDB main + feeders and the services board.

The result is a **feeder-level** bill of materials: MDB, floor DBs and their
incomers/feeders.  Flat *final* circuits are not detailed on a riser, so
those are represented as one feeder per flat rather than the flat's internal
ways — quote the flat panels from their own schedules when available.
"""
from __future__ import annotations

import math
import re
from typing import List, Optional, Tuple

from ..models import Component, DeviceType, Specification

_FLOOR_HEADER_RE = re.compile(r"50\s*HZ.*KA", re.IGNORECASE)
_AF_RE = re.compile(r"(\d+)\s*AF\b", re.IGNORECASE)
_AT_RE = re.compile(r"(\d+)\s*AT\b", re.IGNORECASE)
_A_KA_RE = re.compile(r"(\d+)\s*A\s*-\s*(\d+)\s*KA", re.IGNORECASE)
_KA_RE = re.compile(r"(\d+(?:\.\d+)?)\s*KA", re.IGNORECASE)
_TP_MCCB_RE = re.compile(r"(\d+)\s*A\s*(?:TP|3\s*PH)?\s*MCCB", re.IGNORECASE)
_KVA_RE = re.compile(r"(\d+(?:\.\d+)?)\s*KVA", re.IGNORECASE)
_FLAT_RE = re.compile(r"\bFLAT\s*-?\s*(\d+)\b", re.IGNORECASE)
_MAIN_RE = re.compile(r"(\d+)\s*AT\s*/\s*(\d+)\s*AF", re.IGNORECASE)
_CONTACTOR_RE = re.compile(r"CONTA?CT?OR", re.IGNORECASE)
_FLOOR_NAME_RE = re.compile(r"DB[-\s]*([A-Z]+(?:\s+FLOOR)?)", re.IGNORECASE)

_FLOOR_ORDER = ["GROUND", "FIRST", "SECOND", "THIRD", "FOURTH", "FIFTH",
                "SIXTH", "SEVENTH", "EIGHTH", "NINTH", "TENTH"]


def looks_like_stacked_riser(entries: List[Tuple[Tuple[float, float], str]]) -> bool:
    """True if the drawing is a riser whose table text has collapsed onto a
    few points (so only reading-order parsing is viable)."""
    if not entries:
        return False
    texts = [t for _p, t in entries]
    has_panelref = sum(1 for t in texts if "PANEL REF" in t.upper()) >= 2
    has_floor_tables = sum(1 for t in texts if _FLOOR_HEADER_RE.search(t)) >= 2
    distinct = len({(round(p[0], 1), round(p[1], 1)) for p, _t in entries})
    collapsed = distinct < max(4, len(entries) * 0.15)
    return (has_panelref or has_floor_tables) and collapsed


def extract_riser(entries: List[Tuple[Tuple[float, float], str]],
                  *, flat_feeder_amps: float = 50.0,
                  flat_feeder_poles: int = 3) -> List[Component]:
    seq = [t for _p, t in entries if t and t.strip()]
    starts = [i for i, t in enumerate(seq) if _FLOOR_HEADER_RE.search(t)]
    if not starts:
        return []

    components: List[Component] = []
    tag = _Counter()

    # ---- floor distribution boards ----
    floor_feeders: List[Specification] = []   # incomers become MDB outgoing feeders
    for n, s in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(seq)
        seg = seq[s:end]
        board = _floor_board_name(seg, n)
        incomer = _segment_feeder(seg)
        if incomer:
            floor_feeders.append(incomer)
            components.append(_mk(tag, board, incomer, 1,
                                  _describe(incomer, "incomer")))
        # outgoing flat feeders — a feed to a flat sub-DB is rated to that
        # board's main (standard flat feeder), not to its diversified demand.
        for _amps, qty in _flat_feeders(seg):
            spec = Specification(device_type=DeviceType.MCB,
                                 rating_amps=flat_feeder_amps, poles=flat_feeder_poles)
            components.append(_mk(tag, board, spec, qty, _describe(spec, "flat")))

    # ---- MDB: main + floor feeders + services feeder ----
    mdb_main = _mdb_main(seq)
    if mdb_main:
        components.insert(0, _mk(tag, "MDB-TYPE 2", mdb_main, 1,
                                 _describe(mdb_main, "main")))
    for fspec in floor_feeders:
        # each floor DB's incomer is an outgoing feeder in the MDB
        components.append(_mk(tag, "MDB-TYPE 2", _copy(fspec), 1,
                              _describe(fspec, "feeder")))

    # ---- services board (contactors, meters, service feeders) ----
    components.extend(_services(seq, tag))

    return components


# --------------------------------------------------------------------------
def _segment_feeder(seg: List[str]) -> Optional[Specification]:
    """The MCCB feeding this floor DB (rating from 'NNNA-15KA' or AF/AT)."""
    for t in seg:
        m = _A_KA_RE.search(t)
        if m:
            return Specification(device_type=DeviceType.MCCB,
                                 rating_amps=float(m.group(1)),
                                 breaking_capacity_ka=float(m.group(2)), poles=3)
    for t in seg:
        af = _AF_RE.search(t)
        if af:
            return Specification(device_type=DeviceType.MCCB,
                                 rating_amps=float(af.group(1)), poles=3)
    return None


def _flat_feeders(seg: List[str]) -> List[Tuple[float, int]]:
    """Return (breaker_amps, qty) feeders for the flats in this floor DB."""
    flats = sorted({int(m.group(1)) for t in seg for m in [_FLAT_RE.search(t)] if m})
    if not flats:
        return []
    # flat design loads (KVA), excluding the board C/D-load totals (large)
    loads = [float(m.group(1)) for t in seg for m in [_KVA_RE.search(t)]
             if m and 3.0 <= float(m.group(1)) <= 40.0]
    typical_kva = (sum(loads) / len(loads)) if loads else 15.0
    amps = _breaker_for_kva(typical_kva)
    return [(amps, len(flats))]


def _breaker_for_kva(kva: float, voltage: float = 400.0) -> float:
    current = kva * 1000.0 / (math.sqrt(3) * voltage)
    for s in (16, 20, 25, 32, 40, 50, 63, 80, 100):
        if current <= s * 0.9:      # keep margin
            return float(s)
    return 100.0


def _mdb_main(seq: List[str]) -> Optional[Specification]:
    for t in seq:
        m = _MAIN_RE.search(t)
        if m:
            amps = float(m.group(2))
            # a large main is a moulded/air-frame MCCB (e.g. NS1000N); the
            # selection policy chooses the series and Icu from the fault level.
            spec = Specification(device_type=DeviceType.MCCB, rating_amps=amps, poles=3)
            for u in seq:
                k = re.search(r"(\d+(?:\.\d+)?)\s*kA", u)
                if k and 20 <= float(k.group(1)) <= 100:
                    spec.breaking_capacity_ka = float(k.group(1))
                    break
            return spec
    return None


def _services(seq: List[str], tag: "_Counter") -> List[Component]:
    """Best-effort DB-SERV: the incomer/feeder MCCBs, contactors (stair /
    elevator), CT and meter.  Riser services detail is dense and repeated, so
    devices are de-duplicated by (type, rating)."""
    out: List[Component] = []
    seen = set()
    board = "DB-SRV"

    def add(spec, desc, key):
        if key in seen:
            return
        seen.add(key)
        out.append(_mk(tag, board, spec, 1, desc))

    for t in seq:
        up = t.upper()
        if _CONTACTOR_RE.search(up):
            a = re.search(r"(\d+)\s*A", t)
            amps = float(a.group(1)) if a else None
            role = " (stair lighting)" if "STAIR" in up else \
                   " (elevator)" if "ELEV" in up else ""
            add(Specification(device_type=DeviceType.CONTACTOR, rating_amps=amps, poles=3),
                f"Contactor 3P {amps:g}A{role}" if amps else "Contactor 3P",
                ("CT", amps, role))
        elif "TP MCCB" in up or ("MCCB" in up and "TP" in up):
            a = re.search(r"(\d+)\s*A", t)
            if not a:
                continue
            amps = float(a.group(1))
            k = _KA_RE.search(t)
            spec = Specification(device_type=DeviceType.MCCB, rating_amps=amps, poles=3,
                                 breaking_capacity_ka=float(k.group(1)) if k else None)
            add(spec, f"MCCB 3P {amps:g}A", ("MCCB", amps))
        elif "C.T" in up or ("CT " in up and "/5" in t):
            m = re.search(r"(\d+)\s*/\s*5", t)
            ratio = f"{m.group(1)}/5 A" if m else "CT"
            add(Specification(device_type=DeviceType.CT), f"Current Transformer {ratio}",
                ("CTr", ratio))
        elif "WATTE METER" in up or ("SMART" in up and "METER" in up):
            add(Specification(device_type=DeviceType.METER), "3PH Smart Watt-hour Meter",
                ("METER",))
    return out


# --------------------------------------------------------------------------
def _floor_board_name(seg: List[str], index: int) -> str:
    # The floor label is repeated verbatim in every table ("DB- GROUND FLOOR"),
    # so it cannot distinguish floors — name them by their order in the riser.
    floor = _FLOOR_ORDER[index] if index < len(_FLOOR_ORDER) else f"LEVEL-{index + 1}"
    return f"DB-{floor} FLOOR"


def _describe(spec: Specification, role: str) -> str:
    dt = spec.device_type
    a = f"{spec.rating_amps:g}A" if spec.rating_amps else ""
    ka = f" {spec.breaking_capacity_ka:g}kA" if spec.breaking_capacity_ka else ""
    if dt == DeviceType.ACB:
        return f"ACB 3P {a}{ka} main incomer"
    if dt == DeviceType.MCCB:
        tag = {"incomer": "incoming", "feeder": "feeder"}.get(role, "")
        return f"MCCB 3P {a}{ka} {tag}".strip()
    if dt == DeviceType.MCB:
        return f"MCB 3P {a} flat feeder"
    if dt == DeviceType.CONTACTOR:
        return f"Contactor 3P {a}"
    if dt == DeviceType.METER:
        return "Meter"
    return spec.signature()


class _Counter:
    def __init__(self):
        self.n = 0

    def next(self) -> str:
        self.n += 1
        return f"Q{self.n}"


def _mk(tag: "_Counter", board: str, spec: Specification, qty: int,
        desc: str) -> Component:
    return Component(tag=tag.next(), raw_description=desc, spec=spec,
                     quantity=qty, board=board)


def _copy(spec: Specification) -> Specification:
    import copy
    return copy.deepcopy(spec)
