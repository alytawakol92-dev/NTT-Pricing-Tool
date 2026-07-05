"""Algorithmic 3D placement of components on the panel mounting plate.

Strategy (mirrors how a real panel builder lays out a board):

* Large switchgear (ACB / large MCCB incomers) is placed first, at the top,
  each on its own horizontal band.
* Moulded-case feeders are packed left-to-right into bands sized to the
  tallest device in the band.
* Modular (DIN-rail) devices — MCBs, RCDs, contactors — are grouped and
  packed onto DIN rails at the bottom.
* A configurable clearance is kept around every device, and a wiring-duct
  allowance is added between bands for horizontal trunking.

Placement is bin-packing in 2D on the plate (X = width, Y = height); the Z
axis (depth) is tracked per device so the enclosure depth can be sized to
the deepest component plus a wiring/gland allowance.
"""
from __future__ import annotations

from typing import List, Tuple

from ..config import PricingConfig
from ..models import Component, DeviceType, Placement


# device classes, in vertical order top→bottom of the plate
_TOP = {DeviceType.ACB}
_UPPER = {DeviceType.MCCB, DeviceType.ISOLATOR}
_MID = {DeviceType.CONTACTOR, DeviceType.OVERLOAD, DeviceType.CAPACITOR,
        DeviceType.TRANSFORMER}
_MODULAR = {DeviceType.MCB, DeviceType.RCD, DeviceType.RCCB, DeviceType.FUSE,
            DeviceType.SPD, DeviceType.TERMINAL, DeviceType.PILOT}


def place_components(components: List[Component], config: PricingConfig,
                     plate_width_mm: float = 700.0
                     ) -> Tuple[List[Placement], float, float, float]:
    """Return (placements, used_width, used_height, max_depth).

    ``plate_width_mm`` is the target usable width; bands wrap to a new row
    when they exceed it, growing the plate height instead.
    """
    clr = config.component_clearance_mm
    duct = config.wiring_duct_width_mm

    # expand quantities into individual mountable units
    units: List[Tuple[Component, float, float, float]] = []
    for c in components:
        dims = c.dimensions
        if dims is None:
            continue
        for _ in range(max(1, c.quantity)):
            units.append((c, dims.width_mm, dims.height_mm, dims.depth_mm))

    # order by vertical band priority, then by descending height for tidy rows
    def band_rank(c: Component) -> int:
        dt = c.spec.device_type
        if dt in _TOP:
            return 0
        if dt in _UPPER:
            return 1
        if dt in _MID:
            return 2
        if dt in _MODULAR:
            return 3
        return 4

    units.sort(key=lambda u: (band_rank(u[0]), -u[2]))

    placements: List[Placement] = []
    cursor_x = clr
    cursor_y = clr
    row_height = 0.0
    used_width = 0.0
    max_depth = 0.0
    current_band = None
    rail_index = 0

    for comp, w, h, d in units:
        rank = band_rank(comp)
        # force a new row when the band class changes
        if current_band is not None and rank != current_band:
            cursor_y += row_height + duct
            cursor_x = clr
            row_height = 0.0
            rail_index += 1
        current_band = rank

        # wrap within a band if the row would overflow the plate width
        if cursor_x + w + clr > plate_width_mm and cursor_x > clr:
            cursor_y += row_height + duct
            cursor_x = clr
            row_height = 0.0
            rail_index += 1

        placements.append(Placement(
            component_tag=comp.tag,
            x_mm=round(cursor_x, 1),
            y_mm=round(cursor_y, 1),
            z_mm=0.0,
            width_mm=w, height_mm=h, depth_mm=d,
            rail=f"R{rail_index+1}" if rank == 3 else None,
        ))
        cursor_x += w + clr
        row_height = max(row_height, h)
        used_width = max(used_width, cursor_x)
        max_depth = max(max_depth, d)

    used_height = cursor_y + row_height + clr

    # Bands are built bottom-up (incomer band first at low Y).  Flip Y so the
    # incomer/main switchgear ends up at the top of the plate — the standard
    # top-down reading order for a distribution board.
    for p in placements:
        p.y_mm = round(used_height - p.y_mm - p.height_mm, 1)

    return placements, round(used_width, 1), round(used_height, 1), round(max_depth, 1)


def din_rail_length(placements: List[Placement]) -> float:
    """Total DIN rail length (mm) needed for modular devices."""
    rails = {}
    for p in placements:
        if p.rail:
            rails.setdefault(p.rail, 0.0)
            rails[p.rail] = max(rails[p.rail], p.x_mm + p.width_mm)
    return round(sum(rails.values()), 1)
