"""Standards-based catalog selection.

Fuzzy text matching finds *a* plausible catalog item; this layer enforces the
estimator's **selection standards** on top of it — the right breaker series
for the rating tier, a minimum breaking capacity (drawings under-state it),
and a canonical order code.  It turns "a 200A MCCB somewhere in the catalog"
into "LV525302 — CVS250B 25kA", which is what an NTT engineer actually picks.

Applied after fuzzy matching: where a policy-conformant part exists it
replaces the fuzzy result; otherwise the fuzzy match stands.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from ..config import SelectionPolicy
from ..models import CatalogItem, Component, DeviceType, MatchResult
from .excel_db import ComponentDatabase

# standard breaking-capacity tiers (kA)
_STD_KA = [10, 15, 16, 25, 36, 50, 65, 70, 100, 150]


def round_up_ka(value: float) -> float:
    for k in _STD_KA:
        if k >= value - 0.01:
            return float(k)
    return _STD_KA[-1]


def _series_for(spec, policy: SelectionPolicy) -> Tuple[Optional[str], float, Optional[str]]:
    """Return (series_token, min_kA, preferred_ref_prefix) for a device."""
    dt = spec.device_type
    if dt in (DeviceType.MCCB, DeviceType.ACB):
        amps = spec.rating_amps or 0.0
        for max_a, series, min_ka in policy.mccb_series_rules:
            if amps <= max_a:
                return series, float(min_ka), None
        max_a, series, min_ka = policy.mccb_series_rules[-1]
        return series, float(min_ka), None
    if dt == DeviceType.MCB:
        return policy.mcb_series, 10.0, policy.mcb_ref_prefix
    if dt in (DeviceType.RCCB, DeviceType.RCD):
        return None, 0.0, policy.rccb_ref_prefix
    if dt == DeviceType.CONTACTOR:
        return None, 0.0, "LC1D"
    return None, 0.0, None


def select_item(component: Component, db: ComponentDatabase,
                policy: SelectionPolicy) -> Optional[MatchResult]:
    spec = component.spec
    if not policy.enabled or spec.rating_amps is None or \
            spec.device_type == DeviceType.UNKNOWN:
        return None

    series, min_ka, ref_prefix = _series_for(spec, policy)
    target_ka = round_up_ka(max(spec.breaking_capacity_ka or 0.0, min_ka))

    def candidates(require_series: bool) -> List[CatalogItem]:
        out = []
        for it in db.items:
            s = it.spec
            if s.device_type != spec.device_type:
                continue
            if s.rating_amps is None or abs(s.rating_amps - spec.rating_amps) > 0.5:
                continue
            if spec.poles and s.poles and s.poles != spec.poles:
                continue
            if require_series and series:
                blob = f"{it.description} {it.part_number}".upper()
                if series.upper() not in blob:
                    continue
            if min_ka and s.breaking_capacity_ka and \
                    s.breaking_capacity_ka + 0.5 < min_ka:
                continue
            out.append(it)
        return out

    cands = candidates(require_series=True) or candidates(require_series=False)
    if not cands:
        return None

    def rank(it: CatalogItem):
        pref = 0 if (ref_prefix and it.part_number.upper().startswith(ref_prefix.upper())) else 1
        ka = it.spec.breaking_capacity_ka or 9999
        # closest kA at/above target, then cheapest conforming part
        ka_gap = ka - target_ka if ka >= target_ka else 9999
        price = it.unit_price if policy.prefer_cheapest else -it.unit_price
        return (pref, ka_gap, price)

    cands.sort(key=rank)
    best = cands[0]
    alts = [MatchResult(item=i, score=90.0, method="policy") for i in cands[1:3]]
    return MatchResult(item=best, score=96.0, method="policy", alternatives=alts)


def apply_selection(components: List[Component], db: ComponentDatabase,
                    policy: SelectionPolicy) -> List[Component]:
    """Override each component's match with a policy-conformant part when one
    exists; leave the fuzzy match otherwise."""
    for c in components:
        chosen = select_item(c, db, policy)
        if chosen is not None:
            c.match = chosen
    return components
