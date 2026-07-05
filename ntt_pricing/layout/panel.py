"""Assemble the full 3D panel layout and choose an enclosure.

Ties together placement + routing and computes the optimal panel dimensions:
the smallest standard enclosure (from the pricing config) whose internal
mounting area and depth accommodate every placed component plus wiring
clearance.  If nothing in the catalog fits, a custom enclosure size is
returned so the quotation still reflects the true requirement.
"""
from __future__ import annotations

from typing import List, Optional

from ..config import EnclosureTier, PricingConfig
from ..models import Component, PanelLayout
from .placement import place_components, din_rail_length
from .routing import route_wiring


# Margins added to the used mounting area to reach the enclosure internal size.
_SIDE_MARGIN = 80.0     # mm each side for gland plates / wiring gutters
_TOP_BOTTOM_MARGIN = 120.0
_DEPTH_ALLOWANCE = 90.0  # wiring / door-mounted devices behind the plate front


def build_panel(components: List[Component], config: PricingConfig
                ) -> PanelLayout:
    # try a range of candidate plate widths (portrait through landscape) and
    # keep the tightest result — a wide plate yields a shorter, shallower
    # wall-box shape, a narrow one a tall floor-standing shape.
    best: Optional[PanelLayout] = None
    for plate_w in (500.0, 600.0, 700.0, 800.0, 900.0, 1000.0, 1100.0):
        placements, used_w, used_h, max_d = place_components(
            components, config, plate_width_mm=plate_w)
        if not placements:
            continue
        req_w = used_w + _SIDE_MARGIN
        req_h = used_h + _TOP_BOTTOM_MARGIN
        req_d = max_d + _DEPTH_ALLOWANCE

        enclosure = _select_enclosure(config.enclosures, req_w, req_h, req_d)
        if enclosure is not None:
            w, h, d = enclosure.width_mm, enclosure.height_mm, enclosure.depth_mm
        else:
            w, h, d = _round_up(req_w), _round_up(req_h), _round_up(req_d)

        wires = route_wiring(components, placements, config)
        plate_area = max(used_w, 1) * max(used_h, 1)
        encl_area = w * h * config.enclosure_fill_factor
        utilisation = min(1.0, plate_area / encl_area) if encl_area else 0.0

        layout = PanelLayout(
            width_mm=w, height_mm=h, depth_mm=d,
            placements=placements, wire_runs=wires,
            din_rail_length_mm=din_rail_length(placements),
            utilisation=round(utilisation, 3),
        )
        layout.notes.append(
            f"Mounting area used {used_w:.0f}x{used_h:.0f} mm on a {plate_w:.0f} mm plate; "
            f"deepest component {max_d:.0f} mm.")
        if enclosure is not None:
            layout.notes.append(
                f"Selected standard enclosure '{enclosure.name}' "
                f"({enclosure.ip_rating}, {enclosure.material}).")
        else:
            layout.notes.append(
                "No standard enclosure fits — custom size quoted.")

        # prefer the layout with the smallest enclosure volume
        if best is None or (w * h * d) < (best.width_mm * best.height_mm * best.depth_mm):
            best = layout

    if best is None:
        # nothing placeable (no dimensions) — return an empty small panel
        best = PanelLayout(width_mm=600, height_mm=800, depth_mm=300)
        best.notes.append("No components with dimensions to place.")
    return best


def _select_enclosure(tiers: List[EnclosureTier], w: float, h: float, d: float
                      ) -> Optional[EnclosureTier]:
    fitting = [t for t in tiers if t.fits(w, h, d)]
    if not fitting:
        return None
    return min(fitting, key=lambda t: t.volume_mm3())


def _round_up(v: float, step: float = 50.0) -> float:
    import math
    return math.ceil(v / step) * step
