"""Route copper wiring between placed components and size the conductors.

Wiring follows the electrical hierarchy: every branch device is fed from its
parent (the board incomer / upstream breaker).  For each feed we:

* compute a Manhattan (right-angle) route length between the two placements,
  including a vertical drop into the horizontal wiring duct and back out —
  which is how wiring is actually dressed in a panel,
* size the copper cross section from the downstream device's rating using the
  configured current density,
* add a slack allowance for terminations and dressing.

The incomer itself is fed by a main busbar sized to the incomer rating; its
length spans the plate width.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..config import PricingConfig
from ..models import Component, DeviceType, Placement, WireRun


_SLACK = 1.15          # 15% slack for dressing / terminations
_DROP_TO_DUCT = 60.0   # mm drop each end into the wiring duct


def route_wiring(components: List[Component], placements: List[Placement],
                 config: PricingConfig) -> List[WireRun]:
    pmap: Dict[str, Placement] = {}
    for p in placements:
        pmap.setdefault(p.component_tag, p)  # first unit of each tag

    cmap = {c.tag: c for c in components}
    runs: List[WireRun] = []

    # identify the main incomer (largest breaker with no parent)
    incomer = _find_incomer(components)

    for comp in components:
        parent_tag = comp.parent_tag or (incomer.tag if incomer and comp is not incomer else None)
        if not parent_tag or parent_tag == comp.tag:
            continue
        if comp.tag not in pmap or parent_tag not in pmap:
            continue
        a, b = pmap[parent_tag], pmap[comp.tag]
        length = _manhattan(a, b)
        current = comp.spec.trip_amps or comp.spec.rating_amps or 16.0
        csa = config.csa_for_current(current)
        # 3 phases + neutral for polyphase feeders
        conductors = (comp.spec.poles or 2)
        runs.append(WireRun(
            from_tag=parent_tag, to_tag=comp.tag,
            length_mm=round(length * conductors, 1),
            csa_mm2=csa, current_a=current, kind="wire"))

    # main busbar feeding the incomer, spanning the board width
    if incomer and incomer.tag in pmap:
        width = max((p.x_mm + p.width_mm) for p in placements) if placements else 600.0
        cur = incomer.spec.rating_amps or 250.0
        csa = config.csa_for_current(cur)
        runs.append(WireRun(
            from_tag="INCOMING SUPPLY", to_tag=incomer.tag,
            length_mm=round(width * 1.2 * 4, 1),  # 3ph + N across the board
            csa_mm2=max(csa, 25.0), current_a=cur, kind="busbar"))

    return runs


def _manhattan(a: Placement, b: Placement) -> float:
    ax = a.x_mm + a.width_mm / 2
    ay = a.y_mm + a.height_mm / 2
    bx = b.x_mm + b.width_mm / 2
    by = b.y_mm + b.height_mm / 2
    base = abs(ax - bx) + abs(ay - by) + 2 * _DROP_TO_DUCT
    return base * _SLACK


def _find_incomer(components: List[Component]) -> Optional[Component]:
    best = None
    for c in components:
        if c.spec.device_type in (DeviceType.ACB, DeviceType.MCCB, DeviceType.ISOLATOR):
            if best is None or (c.spec.rating_amps or 0) > (best.spec.rating_amps or 0):
                best = c
    return best
