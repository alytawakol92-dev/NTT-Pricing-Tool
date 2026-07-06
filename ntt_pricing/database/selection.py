"""Least-cost, spec-compliant catalog selection.

The governing rule: **meet the electrical specification at the lowest cost.**
For each device we find every catalog part that satisfies the requirement —
same device type and pole count, a rating that meets the design rating, and a
breaking capacity at or above the fault level — then pick the **cheapest**,
regardless of product series.  Because the chosen ratings (and, downstream,
the enclosure size) drive the copper/busbar and wiring, selecting the
cheapest compliant breaker is what actually minimises the total offer.

Guards:
* non-breaker rows (mounting plates, blanking strips, cut-outs, bus-bar
  supports, connectors…) that share a rating in their description are
  excluded, so a €3 blanking strip is never chosen as a "160A MCCB";
* a ``preferred_series`` allow-list can pin a family when a client mandates
  it; empty means pure least cost.
"""
from __future__ import annotations

from typing import List, Optional

from ..config import SelectionPolicy
from ..models import CatalogItem, Component, DeviceType, MatchResult
from .excel_db import ComponentDatabase

# words that mark a row as an accessory / part, not a switching device
_ACCESSORY = (
    "PLATE", "STRIP", "CUT-OUT", "CUTOUT", "MOUNTING", "SUPPORT", "CONNECTOR",
    "BLANKING", "COVER", "SHROUD", "GLAND", "DOOR", "FRAME", "ROOF", "HANDLE",
    "LOCK", "KIT", "ACCESSORY", "SPREADER", "BARRIER", "ROTARY", "LUG", "AUX",
    "MECHANISM", "BUSBAR", "BUS BAR", "EXTENSION", "ROD", "SEAL", "ADD-ON",
    "TERMINAL BLOCK", "SPACER", "LABEL", "CAP ", "FIXING", "ESCUTCHEON",
    "PADLOCK", "INTERLOCK", "MOTOR MECH", "TOGGLE", "DIN RAIL", "COMB",
)
_BREAKERS = {DeviceType.MCCB, DeviceType.ACB, DeviceType.MCB}


def round_up_ka(value: float) -> float:
    for k in (10, 15, 16, 25, 36, 50, 65, 70, 100, 150):
        if k >= value - 0.01:
            return float(k)
    return 150.0


def _required_ka(spec, policy: SelectionPolicy) -> float:
    if spec.breaking_capacity_ka:
        return float(spec.breaking_capacity_ka)
    if spec.device_type == DeviceType.MCB:
        return policy.mcb_default_ka
    return policy.default_min_ka


def _is_real_breaker(item: CatalogItem) -> bool:
    blob = f"{item.description}".upper()
    if any(a in blob for a in _ACCESSORY):
        return False
    # a genuine breaker states a breaking capacity
    return item.spec.breaking_capacity_ka is not None


def _series_ok(item: CatalogItem, policy: SelectionPolicy) -> bool:
    if policy.objective != "series" or not policy.preferred_series:
        return True
    blob = f"{item.description} {item.part_number}".upper()
    return any(s.upper() in blob for s in policy.preferred_series)


def _manuf_ok(item: CatalogItem, policy: SelectionPolicy) -> bool:
    if not policy.allowed_manufacturers:
        return True
    m = (item.manufacturer or "").upper()
    return any(a.upper() in m for a in policy.allowed_manufacturers)


def select_item(component: Component, db: ComponentDatabase,
                policy: SelectionPolicy) -> Optional[MatchResult]:
    spec = component.spec
    if not policy.enabled or spec.rating_amps is None or \
            spec.device_type == DeviceType.UNKNOWN:
        return None

    required_a = spec.rating_amps
    required_ka = _required_ka(spec, policy)
    is_breaker = spec.device_type in _BREAKERS

    def compliant(exact_rating: bool) -> List[CatalogItem]:
        out = []
        for it in db.items:
            s = it.spec
            if s.device_type != spec.device_type:
                continue
            if s.rating_amps is None:
                continue
            if exact_rating:
                if abs(s.rating_amps - required_a) > 0.5:
                    continue
            elif s.rating_amps < required_a - 0.5:
                continue
            if spec.poles and s.poles and s.poles != spec.poles:
                continue
            if is_breaker:
                if not _is_real_breaker(it):
                    continue
                if (s.breaking_capacity_ka or 0) + 0.01 < required_ka:
                    continue
            if not _series_ok(it, policy) or not _manuf_ok(it, policy):
                continue
            out.append(it)
        return out

    # design specifies a rating: try that exactly, else the next size up
    cands = compliant(exact_rating=True) or compliant(exact_rating=False)
    if not cands:
        return None

    def cost_rank(it: CatalogItem):
        # cheapest compliant part; tie-break to the preferred order code and
        # then the smallest rating so we do not over-frame.
        prefer = 0 if (policy.mcb_ref_prefix and spec.device_type == DeviceType.MCB
                       and it.part_number.upper().startswith(policy.mcb_ref_prefix.upper())) else 1
        return (round(it.unit_price, 2), prefer, it.spec.rating_amps or 0)

    cands.sort(key=cost_rank)
    best = cands[0]
    alts = [MatchResult(item=i, score=90.0, method="least-cost") for i in cands[1:3]]
    return MatchResult(item=best, score=96.0, method="least-cost", alternatives=alts)


def apply_selection(components: List[Component], db: ComponentDatabase,
                    policy: SelectionPolicy) -> List[Component]:
    """Override each component's match with the least-cost compliant part when
    one exists; leave the fuzzy match otherwise."""
    for c in components:
        chosen = select_item(c, db, policy)
        if chosen is not None:
            c.match = chosen
    return components
