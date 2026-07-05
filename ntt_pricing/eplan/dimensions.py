"""Physics-based fallback estimator for component dimensions.

When authoritative EPLAN data is unavailable, we still need a realistic
mechanical envelope to lay out the panel.  These estimates are grounded in
real Schneider modular / moulded-case device families: modular Acti9 devices
are one 18mm pole wide per pole; NSX-class MCCBs grow with frame size; ACBs
are large fixed footprints, and so on.  The numbers are conservative
(slightly generous) so the resulting panel is never undersized.
"""
from __future__ import annotations

from ..models import Dimensions, DeviceType, Specification


# One modular pole is ~18mm wide, 85mm tall, 70mm deep on a DIN rail.
_MODULE_W = 18.0
_MODULE_H = 85.0
_MODULE_D = 70.0


def estimate_dimensions(spec: Specification) -> Dimensions:
    dt = spec.device_type
    amps = spec.rating_amps or 0.0
    poles = spec.poles or _default_poles(dt)

    if dt in (DeviceType.MCB, DeviceType.RCD, DeviceType.RCCB, DeviceType.SPD):
        w = _MODULE_W * poles
        d = Dimensions(width_mm=round(w, 1), height_mm=_MODULE_H, depth_mm=_MODULE_D,
                       weight_kg=round(0.11 * poles + 0.05, 2),
                       din_modules=round(poles, 1), source="estimated")
        return d

    if dt == DeviceType.MCCB:
        # frame size grows with current
        if amps <= 160:
            w, h, dep, wt = 90 * (poles / 3), 130, 86, 1.5
        elif amps <= 250:
            w, h, dep, wt = 105 * (poles / 3), 165, 86, 2.5
        elif amps <= 400:
            w, h, dep, wt = 140 * (poles / 3), 255, 110, 5.0
        elif amps <= 630:
            w, h, dep, wt = 185 * (poles / 3), 280, 110, 9.0
        else:
            w, h, dep, wt = 210 * (poles / 3), 320, 140, 14.0
        return Dimensions(round(w, 1), round(h, 1), round(dep, 1), round(wt, 2),
                          source="estimated")

    if dt == DeviceType.ACB:
        # air circuit breakers — large fixed envelopes
        if amps <= 1600:
            w, h, dep, wt = 352, 302, 290, 40.0
        elif amps <= 2500:
            w, h, dep, wt = 422, 302, 290, 55.0
        else:
            w, h, dep, wt = 536, 439, 320, 90.0
        return Dimensions(w, h, dep, wt, source="estimated")

    if dt == DeviceType.CONTACTOR:
        if amps <= 40:
            w, h, dep, wt = 45, 85, 90, 0.5
        elif amps <= 95:
            w, h, dep, wt = 72, 120, 105, 1.2
        elif amps <= 150:
            w, h, dep, wt = 90, 150, 130, 2.5
        else:
            w, h, dep, wt = 120, 190, 150, 4.5
        return Dimensions(w, h, dep, wt, source="estimated")

    if dt == DeviceType.OVERLOAD:
        return Dimensions(45, 90, 80, 0.4, source="estimated")

    if dt == DeviceType.ISOLATOR:
        w = max(_MODULE_W * poles, 36.0)
        return Dimensions(round(w, 1), 90, 75, 0.6, source="estimated")

    if dt == DeviceType.FUSE:
        w = _MODULE_W * poles
        return Dimensions(round(w, 1), 90, 75, 0.3, source="estimated")

    if dt == DeviceType.METER:
        return Dimensions(96, 96, 60, 0.4, source="estimated")

    if dt == DeviceType.CT:
        return Dimensions(60, 60, 45, 0.3, source="estimated")

    if dt == DeviceType.CAPACITOR:
        return Dimensions(120, 240, 130, 3.0, source="estimated")

    if dt == DeviceType.TRANSFORMER:
        return Dimensions(100, 120, 110, 4.0, source="estimated")

    if dt == DeviceType.PLC:
        return Dimensions(110, 90, 75, 0.5, source="estimated")

    if dt == DeviceType.PILOT:
        return Dimensions(22, 22, 45, 0.05, source="estimated")

    if dt == DeviceType.TERMINAL:
        return Dimensions(6, 50, 55, 0.02, din_modules=0.33, source="estimated")

    if dt == DeviceType.BUSBAR:
        return Dimensions(30, 10, 10, 0.5, source="estimated")

    # generic default: a small modular device
    return Dimensions(_MODULE_W * max(poles, 1), _MODULE_H, _MODULE_D,
                      0.2, source="estimated")


def _default_poles(dt: DeviceType) -> int:
    if dt in (DeviceType.ACB, DeviceType.MCCB):
        return 3
    if dt in (DeviceType.CONTACTOR, DeviceType.OVERLOAD):
        return 3
    return 1
