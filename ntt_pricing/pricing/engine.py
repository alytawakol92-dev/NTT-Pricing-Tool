"""Turn matched components + panel layout into priced line items.

Pricing precedence for each component:
1. explicit ``component_price_overrides[part_number]`` from the config,
2. the matched catalog unit price,
3. the configured ``default_component_price`` (with a note flagging it).

Copper is priced from the routed wire runs — per-metre insulated-wire rates
by cross section for feeders, and per-kg for busbar — so the cost tracks the
actual conductor sizing.  The enclosure is priced from the selected standard
tier (or an area-based estimate for custom sizes).  Assembly labour is a
per-device rate.
"""
from __future__ import annotations

from typing import List, Optional

from ..config import PricingConfig
from ..models import (Component, LineItem, PanelLayout, WireRun)


def build_component_line_items(components: List[Component],
                               config: PricingConfig) -> List[LineItem]:
    items: List[LineItem] = []
    for c in components:
        unit_price, ref, desc, note = _price_component(c, config)
        li = LineItem(
            ref=ref,
            description=desc + (f"  [{note}]" if note else ""),
            quantity=c.quantity,
            unit="pc",
            unit_price=round(unit_price, 2),
            currency=config.currency,
            category="Component",
        )
        items.append(li)
    return items


def _price_component(c: Component, config: PricingConfig):
    part = None
    desc = c.raw_description or c.spec.signature()
    if c.match and c.match.item:
        part = c.match.item.part_number
        desc = c.match.item.description or desc

    # 1) override by part number
    if part and part in config.component_price_overrides:
        return config.component_price_overrides[part], part, f"{c.tag} — {desc}", "price override"

    # 2) matched catalog price (only trust confident-enough matches)
    if c.match and c.match.item and c.match.score >= config.match_threshold:
        note = "" if c.match.confident else f"low-confidence match {c.match.score:.0f}%"
        return c.match.item.unit_price, part or c.tag, f"{c.tag} — {desc}", note

    # 3) default fallback
    return (config.default_component_price, c.tag, f"{c.tag} — {desc}",
            "no catalog match — default price")


def build_copper_line_items(wires: List[WireRun],
                            config: PricingConfig) -> List[LineItem]:
    """Aggregate wire runs into priced copper line items by cross section."""
    items: List[LineItem] = []

    # feeders grouped by CSA, priced per metre
    by_csa = {}
    busbar_mass = 0.0
    for w in wires:
        if w.kind == "busbar":
            busbar_mass += w.copper_mass_kg()
        else:
            by_csa.setdefault(w.csa_mm2, 0.0)
            by_csa[w.csa_mm2] += w.length_mm

    for csa in sorted(by_csa):
        metres = by_csa[csa] / 1000.0
        if metres <= 0:
            continue
        items.append(LineItem(
            ref=f"CU-{csa:g}",
            description=f"Copper power wiring {csa:g} mm² (insulated)",
            quantity=round(metres, 1),
            unit="m",
            unit_price=round(config.wire_price(csa), 2),
            currency=config.currency,
            category="Copper",
        ))

    if busbar_mass > 0:
        items.append(LineItem(
            ref="CU-BUS",
            description="Copper busbar / main distribution bars",
            quantity=round(busbar_mass, 2),
            unit="kg",
            unit_price=round(config.busbar_price_per_kg, 2),
            currency=config.currency,
            category="Copper",
        ))
    return items


def build_enclosure_line_item(panel: PanelLayout,
                              config: PricingConfig) -> LineItem:
    tier = _matching_tier(panel, config)
    if tier is not None:
        price = tier.price * (1 + config.enclosure_markup_pct / 100.0)
        desc = (f"Enclosure {tier.name} "
                f"({panel.width_mm:.0f}x{panel.height_mm:.0f}x{panel.depth_mm:.0f} mm, "
                f"{tier.ip_rating}, {tier.material})")
    else:
        # area-based estimate for custom sizes: steel + fabrication
        area_m2 = 2 * (panel.width_mm * panel.height_mm +
                       panel.width_mm * panel.depth_mm +
                       panel.height_mm * panel.depth_mm) / 1e6
        price = area_m2 * 260.0 * (1 + config.enclosure_markup_pct / 100.0)
        desc = (f"Custom enclosure "
                f"{panel.width_mm:.0f}x{panel.height_mm:.0f}x{panel.depth_mm:.0f} mm "
                f"(fabricated, ~{area_m2:.2f} m² sheet)")
    return LineItem(
        ref="ENC", description=desc, quantity=1, unit="pc",
        unit_price=round(price, 2), currency=config.currency,
        category="Enclosure",
    )


def build_labour_line_item(components: List[Component],
                           config: PricingConfig) -> Optional[LineItem]:
    total_units = sum(max(1, c.quantity) for c in components)
    if total_units == 0 or config.labour_rate_per_component <= 0:
        return None
    return LineItem(
        ref="LAB",
        description=f"Assembly, wiring & testing labour ({total_units} devices)",
        quantity=total_units, unit="device",
        unit_price=round(config.labour_rate_per_component, 2),
        currency=config.currency, category="Labour",
    )


def _matching_tier(panel: PanelLayout, config: PricingConfig):
    for t in config.enclosures:
        if (abs(t.width_mm - panel.width_mm) < 1 and
                abs(t.height_mm - panel.height_mm) < 1 and
                abs(t.depth_mm - panel.depth_mm) < 1):
            return t
    # otherwise pick the smallest tier that fits (may have been custom-rounded)
    fitting = [t for t in config.enclosures if t.fits(panel.width_mm, panel.height_mm, panel.depth_mm)]
    return min(fitting, key=lambda t: t.volume_mm3()) if fitting else None
