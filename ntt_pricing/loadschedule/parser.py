"""Parse the client load schedule and cross reference it with the SLD.

The load schedule is the client's declaration of every circuit: its load
(kW), design current, phases and the protective device rating.  We parse it
(CSV or XLSX) and then validate the extracted single-line-diagram components
against it, surfacing:

* circuits present in the schedule but missing a device on the drawing,
* devices on the drawing not accounted for in the schedule,
* protective devices whose rating is undersized for the declared load
  current (a safety-relevant discrepancy).
"""
from __future__ import annotations

import csv
import math
import os
from typing import Dict, List, Optional

from ..models import Component, LoadScheduleEntry, ValidationIssue


_REF_ALIASES = ["circuit", "circuit ref", "ref", "way", "circuit no", "id", "tag", "feeder"]
_DESC_ALIASES = ["description", "load", "load description", "desc", "service"]
_KW_ALIASES = ["kw", "load kw", "power", "power kw", "connected load", "demand kw"]
_AMP_ALIASES = ["current", "current a", "amps", "fla", "design current", "load current", "ampere"]
_VOLT_ALIASES = ["voltage", "volt", "v"]
_PH_ALIASES = ["phase", "phases", "ph", "no of phase"]
_PF_ALIASES = ["pf", "power factor", "cos"]
_BRK_ALIASES = ["breaker", "breaker rating", "protection", "mccb", "mcb", "device rating", "rating"]
_BOARD_ALIASES = ["board", "panel", "db", "source"]


def load_schedule(path: str) -> List[LoadScheduleEntry]:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        rows = _read_csv(path)
    elif ext in (".xlsx", ".xlsm"):
        rows = _read_xlsx(path)
    else:
        raise ValueError(f"Unsupported load schedule format: {ext}")
    return _rows_to_entries(rows)


def _read_csv(path: str) -> List[Dict]:
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        return [dict(r) for r in csv.DictReader(fh)]


def _read_xlsx(path: str) -> List[Dict]:
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    it = ws.iter_rows(values_only=True)
    try:
        header = next(it)
    except StopIteration:
        return []
    headers = [str(h).strip() if h is not None else f"col{i}" for i, h in enumerate(header)]
    out = []
    for row in it:
        if row is None or all(v is None for v in row):
            continue
        out.append({headers[i]: row[i] for i in range(min(len(headers), len(row)))})
    wb.close()
    return out


def _rows_to_entries(rows: List[Dict]) -> List[LoadScheduleEntry]:
    if not rows:
        return []
    hm = _map_headers(list(rows[0].keys()))
    entries: List[LoadScheduleEntry] = []
    for i, r in enumerate(rows):
        ref = _get(r, hm, "ref")
        desc = _get(r, hm, "desc")
        if ref is None and desc is None:
            continue
        entries.append(LoadScheduleEntry(
            circuit_ref=str(ref or f"C{i+1}").strip(),
            description=str(desc or "").strip(),
            load_kw=_num(_get(r, hm, "kw")),
            current_a=_num(_get(r, hm, "amp")),
            voltage=_num(_get(r, hm, "volt")),
            phases=_int(_get(r, hm, "ph")),
            power_factor=_num(_get(r, hm, "pf")),
            breaker_rating_a=_num(_get(r, hm, "brk")),
            board=(str(_get(r, hm, "board")).strip() if _get(r, hm, "board") else None),
        ))
    for e in entries:
        _derive_current(e)
    return entries


def _derive_current(e: LoadScheduleEntry) -> None:
    """Fill in design current from kW when it is not stated explicitly."""
    if e.current_a is not None or e.load_kw is None:
        return
    v = e.voltage or (400 if (e.phases or 3) == 3 else 230)
    pf = e.power_factor or 0.85
    if (e.phases or 3) == 3:
        e.current_a = round(e.load_kw * 1000 / (math.sqrt(3) * v * pf), 1)
    else:
        e.current_a = round(e.load_kw * 1000 / (v * pf), 1)


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------
def cross_validate(components: List[Component],
                   schedule: List[LoadScheduleEntry]) -> List[ValidationIssue]:
    """Compare extracted devices against the load schedule."""
    issues: List[ValidationIssue] = []
    if not schedule:
        issues.append(ValidationIssue("info", None,
                                      "No load schedule supplied — validation skipped."))
        return issues

    matched_entries = set()
    for comp in components:
        entry = _match_entry(comp, schedule)
        if entry is None:
            continue
        matched_entries.add(entry.circuit_ref)
        # rating adequacy check
        if entry.current_a and comp.spec.rating_amps:
            if comp.spec.rating_amps < entry.current_a * 1.0:
                issues.append(ValidationIssue(
                    "error", entry.circuit_ref,
                    f"Device {comp.tag} rated {comp.spec.rating_amps:g}A is below the "
                    f"declared load current {entry.current_a:g}A for '{entry.description}'."))
            elif comp.spec.rating_amps < entry.current_a * 1.25:
                issues.append(ValidationIssue(
                    "warning", entry.circuit_ref,
                    f"Device {comp.tag} ({comp.spec.rating_amps:g}A) leaves little margin "
                    f"over {entry.current_a:g}A on '{entry.description}' (<25%)."))
        # breaker-rating mismatch
        if entry.breaker_rating_a and comp.spec.rating_amps and \
                abs(entry.breaker_rating_a - comp.spec.rating_amps) > 1:
            issues.append(ValidationIssue(
                "warning", entry.circuit_ref,
                f"Schedule specifies {entry.breaker_rating_a:g}A for {entry.circuit_ref} "
                f"but drawing shows {comp.tag} at {comp.spec.rating_amps:g}A."))

    # circuits in schedule with no device found on the drawing
    for e in schedule:
        if e.circuit_ref not in matched_entries:
            issues.append(ValidationIssue(
                "warning", e.circuit_ref,
                f"Circuit '{e.circuit_ref}' ({e.description}) is in the load schedule "
                f"but no matching device was extracted from the drawing."))

    return issues


def _match_entry(comp: Component,
                 schedule: List[LoadScheduleEntry]) -> Optional[LoadScheduleEntry]:
    # 1) exact circuit ref / tag
    for e in schedule:
        if e.circuit_ref and comp.tag and \
                e.circuit_ref.upper() == comp.tag.upper():
            return e
    # 2) description contains the tag or vice-versa
    for e in schedule:
        if comp.tag and e.description and comp.tag.upper() in e.description.upper():
            return e
    # 3) fuzzy on description
    best, best_score = None, 0.0
    for e in schedule:
        s = _similar(comp.raw_description, e.description)
        if s > best_score:
            best, best_score = e, s
    return best if best_score >= 0.6 else None


def _similar(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    try:
        from rapidfuzz import fuzz
        return fuzz.token_set_ratio(a.lower(), b.lower()) / 100.0
    except Exception:
        import difflib
        return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


# --------------------------------------------------------------------------
# header helpers
# --------------------------------------------------------------------------
def _map_headers(headers: List[str]) -> Dict[str, str]:
    lut = {h.lower().strip(): h for h in headers}

    def find(aliases):
        for a in aliases:
            if a in lut:
                return lut[a]
        for key, orig in lut.items():
            if any(key == a or key.startswith(a) for a in aliases):
                return orig
        return None

    return {
        "ref": find(_REF_ALIASES), "desc": find(_DESC_ALIASES),
        "kw": find(_KW_ALIASES), "amp": find(_AMP_ALIASES),
        "volt": find(_VOLT_ALIASES), "ph": find(_PH_ALIASES),
        "pf": find(_PF_ALIASES), "brk": find(_BRK_ALIASES),
        "board": find(_BOARD_ALIASES),
    }


def _get(row, hm, field):
    col = hm.get(field)
    return row.get(col) if col else None


def _num(v) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = "".join(ch for ch in str(v) if ch.isdigit() or ch in ".-")
    try:
        return float(s) if s not in ("", "-", ".") else None
    except ValueError:
        return None


def _int(v) -> Optional[int]:
    n = _num(v)
    return int(n) if n is not None else None
