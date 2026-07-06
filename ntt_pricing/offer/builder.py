"""Assemble an :class:`NTTOffer` from the extracted / matched components.

Each board (MDB, DB-1, …) becomes a separate physical panel: its components
are classified into INCOMING / INDICATION & INSTRUMENTS / OUTGOING, the
standard indication set is added, the enclosure is sized by laying out just
that board's components, and the panel is priced (components + copper +
enclosure + labour, with markup) to give a per-panel unit price.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..config import PricingConfig
from ..database import ComponentDatabase, apply_selection, match_all
from ..eplan import EplanClient
from ..extraction import extract_components
from ..layout import build_panel
from ..layout.routing import route_wiring
from ..models import Component, DeviceType
from .models import (ComponentLine, GROUP_INCOMING, GROUP_INDICATION,
                     GROUP_OUTGOING, NTTOffer, OfferPanel)
from .profile import (CompanyProfile, DEFAULT_ACCESSORIES, DEFAULT_CONTACTS,
                      DEFAULT_SIGNATORIES, OfferTerms, PanelDefaults, Signatory)

# device types shown under INDICATION & INSTRUMENTS
_INSTRUMENT_TYPES = {DeviceType.METER, DeviceType.PILOT, DeviceType.CT,
                     DeviceType.SPD, DeviceType.FUSE, DeviceType.CAPACITOR}


def build_offer(sld_path: str, catalog_path: str,
                schedule_path: Optional[str] = None,
                config: Optional[PricingConfig] = None, *,
                offer_no: str = "Q-0001", client: str = "Client",
                project_name: str = "Untitled Project", date: str = "",
                code: str = "", attention: str = "",
                eplan_client: Optional[EplanClient] = None) -> NTTOffer:
    config = config or PricingConfig()
    components = extract_components(sld_path)
    db = ComponentDatabase.load(catalog_path)
    match_all(components, db, threshold=config.match_threshold)
    apply_selection(components, db, config.selection)

    client_obj = eplan_client or EplanClient()
    for c in components:
        c.dimensions = client_obj.get_dimensions(c)
    client_obj.flush()

    return assemble_offer(components, config, offer_no=offer_no, client=client,
                          project_name=project_name, date=date, code=code,
                          attention=attention)


def offer_from_result(result, config: PricingConfig, *, offer_no: str,
                      client: str, project_name: str, date: str,
                      code: str = "", attention: str = "") -> NTTOffer:
    """Build an offer from an existing pipeline result (reuses extraction /
    matching / dimensions instead of re-running them)."""
    return assemble_offer(result.components, config, offer_no=offer_no,
                          client=client, project_name=project_name, date=date,
                          code=code, attention=attention)


def assemble_offer(components: List[Component], config: PricingConfig, *,
                   offer_no: str, client: str, project_name: str, date: str,
                   code: str = "", attention: str = "") -> NTTOffer:
    panel_defaults = _panel_defaults(config)
    boards = _group_by_board(components)

    offer_panels: List[OfferPanel] = []
    for item_no, (board_name, board_comps) in enumerate(boards.items(), start=1):
        offer_panels.append(
            _build_panel(item_no, board_name, board_comps, config, panel_defaults))

    offer = NTTOffer(
        offer_no=offer_no, client=client, project_name=project_name, date=date,
        currency=config.currency, currency_symbol=config.symbol(),
        tax_pct=config.tax_pct, code=code, attention=attention,
        panels=offer_panels,
        company=_company(config), terms=OfferTerms(),
        signatories=_signatories(config), contacts=config.contacts or list(DEFAULT_CONTACTS),
    )
    for p in offer_panels:
        for n in p.notes:
            offer.notes.append(f"Item {p.item_no} ({p.name}): {n}")
    return offer


# --------------------------------------------------------------------------
# per-board panel construction
# --------------------------------------------------------------------------
def _build_panel(item_no: int, name: str, comps: List[Component],
                 config: PricingConfig, defaults: PanelDefaults) -> OfferPanel:
    incomer = _pick_incomer(comps)

    lines: List[ComponentLine] = []
    components_cost = 0.0
    for c in comps:
        group = _classify(c, incomer)
        price, ref, brand, desc = _price_and_describe(c, config)
        lines.append(ComponentLine(qty=c.quantity, ref=ref, brand=brand,
                                   description=desc, group=group, unit_price=price))
        components_cost += price * c.quantity

    # standard indication set (lamps + fuse)
    if config.include_standard_accessories:
        for acc in DEFAULT_ACCESSORIES:
            lines.append(ComponentLine(qty=acc.qty, ref=acc.ref, brand=acc.brand,
                                       description=acc.description, group=acc.group,
                                       unit_price=acc.unit_price))
            components_cost += acc.unit_price * acc.qty

    # Rule 5: metering distribution boards reserve space for the kWh meters and
    # use standard NTT enclosure sizes rather than a tight computed envelope.
    metering = _is_metering_board(name)
    if metering and config.selection.reserve_kwhm_space:
        lines.append(ComponentLine(qty=1, ref="—", brand="NTT Panel",
                                   description="SPACE FOR KWHM", group=GROUP_OUTGOING,
                                   unit_price=0.0))

    # lay out just this board to size the enclosure + copper
    layout = build_panel(comps, config)
    copper_cost = _copper_cost(comps, layout, config)
    labour_cost = sum(max(1, c.quantity) for c in comps) * config.labour_rate_per_component

    # enclosure: choose the cheapest available LOCAL NTT enclosure that fits.
    # Metering boards reserve meter space (larger standard box); everything else
    # is sized to the computed component envelope. If a board genuinely exceeds
    # the local range, the largest local box is quoted with a flag for review.
    ip_dims = "IP42"
    if metering:
        req_h, req_w, req_d = [v * 10 for v in _metering_size(incomer, config)]
        thermal_note = None
    else:
        req_w, req_h, req_d, thermal_note = _design_required_size(layout, incomer, comps)
    tier, note = _select_local_enclosure(req_w, req_h, req_d, config)
    enclosure_cost = round(tier.price * (1 + config.enclosure_markup_pct / 100.0), 2)
    h_cm, w_cm, d_cm = round(tier.height_mm / 10), round(tier.width_mm / 10), round(tier.depth_mm / 10)
    panel_notes = [n for n in (note, thermal_note) if n]

    lines.append(ComponentLine(
        qty=1, ref=f"NTT-{int(h_cm)}{int(w_cm)}{int(d_cm)}",
        brand=defaults.enclosure_type,
        description=(f"{defaults.enclosure_type} {tier.ip_rating} , Dim "
                     f"{h_cm:g}H * {w_cm:g}W * {d_cm:g}D Cm"),
        group=GROUP_OUTGOING, unit_price=enclosure_cost))

    pre = components_cost + copper_cost + enclosure_cost + labour_cost
    unit_price = pre * (1 + config.markup_pct / 100.0) * (1 - config.discount_pct / 100.0)

    inst = _install_for(defaults, incomer)
    return OfferPanel(
        item_no=item_no, name=name, quantity=1,
        main_bb_rating=_rating_text(incomer), install=inst, lines=lines,
        width_cm=w_cm, height_cm=h_cm, depth_cm=d_cm, enclosure_ip=ip_dims,
        components_cost=round(components_cost, 2), copper_cost=round(copper_cost, 2),
        enclosure_cost=round(enclosure_cost, 2), labour_cost=round(labour_cost, 2),
        unit_price=round(unit_price, 2), notes=panel_notes,
    )


def _design_required_size(layout, incomer, comps):
    """Manufacturability-aware internal size (mm) for a switchboard.

    A board's size is not just the sum of component footprints — it is driven
    by the busbar chamber, cable-entry/gland zone, side wireways and working
    clearances (all scaled to the incomer rating), plus a heat check.  Sizing
    to these standards keeps the panel buildable and lets the cheapest
    enclosure that still fits be chosen.
    """
    placements = layout.placements
    if placements:
        used_w = max(p.x_mm + p.width_mm for p in placements)
        used_h = max(p.y_mm + p.height_mm for p in placements)
        used_d = max(p.depth_mm for p in placements)
    else:
        used_w = used_h = 300.0
        used_d = 150.0

    amps = incomer.spec.rating_amps if (incomer and incomer.spec.rating_amps) else 100.0

    def by_rating(low, mid, high):
        return low if amps <= 250 else mid if amps <= 630 else high

    busbar_chamber = by_rating(150, 200, 300)   # top busbar zone (mm)
    cable_zone = by_rating(150, 200, 300)        # bottom gland / cable zone
    side_wireway = 2 * by_rating(60, 80, 100)    # vertical trunking both sides
    depth_allow = by_rating(90, 150, 250)        # busbar + wiring behind plate

    req_w = used_w + side_wireway + 60
    req_h = used_h + busbar_chamber + cable_zone + 80
    req_d = used_d + depth_allow

    # heat check: rough device dissipation vs enclosure surface capacity
    p_loss = _heat_dissipation(comps)
    surface_m2 = 2 * (req_w * req_h + req_w * req_d + req_h * req_d) / 1e6
    capacity_w = surface_m2 * 55.0               # ~55 W/m2 for a sealed steel box
    thermal_note = None
    if p_loss > capacity_w * 1.05:
        thermal_note = (f"Estimated heat {p_loss:.0f} W exceeds sealed-enclosure "
                        f"dissipation (~{capacity_w:.0f} W) — add ventilation/fan "
                        f"or a larger enclosure.")
    return round(req_w, 1), round(req_h, 1), round(req_d, 1), thermal_note


def _heat_dissipation(comps) -> float:
    """Rough total power loss (W): breakers dissipate roughly with rating."""
    total = 0.0
    for c in comps:
        a = c.spec.rating_amps or 0.0
        dt = c.spec.device_type
        if dt in (DeviceType.MCCB, DeviceType.ACB):
            per = 0.12 * a           # W per device (~15W at 125A ... scales up)
        elif dt == DeviceType.MCB:
            per = 0.05 * a
        elif dt == DeviceType.CONTACTOR:
            per = 0.08 * a
        else:
            per = 1.0
        total += per * max(1, c.quantity)
    return total


def _select_local_enclosure(req_w_mm, req_h_mm, req_d_mm, config):
    """Cheapest available local enclosure that fits (W×H×D in mm).

    If nothing in the local range fits, quote the largest available box and
    return a note so the estimator knows a bigger (floor) enclosure is needed.
    """
    if not config.enclosures:
        raise ValueError("no enclosures configured")
    fitting = [t for t in config.enclosures
               if t.fits(req_w_mm, req_h_mm, req_d_mm)]
    if fitting:
        return min(fitting, key=lambda t: t.price), None
    largest = max(config.enclosures, key=lambda t: t.volume_mm3())
    note = (f"Required {req_h_mm/10:.0f}H×{req_w_mm/10:.0f}W×{req_d_mm/10:.0f}D cm "
            f"exceeds the largest local enclosure ({largest.name}); "
            f"a floor-standing enclosure is required — price to be confirmed.")
    return largest, note


# --------------------------------------------------------------------------
# classification & pricing helpers
# --------------------------------------------------------------------------
def _group_by_board(components: List[Component]) -> Dict[str, List[Component]]:
    boards: Dict[str, List[Component]] = {}
    for c in components:
        boards.setdefault(c.board or "MDB", []).append(c)
    return boards


_SWITCHGEAR = {DeviceType.ACB, DeviceType.MCCB, DeviceType.ISOLATOR}


def _pick_incomer(comps: List[Component]) -> Optional[Component]:
    """The board incomer: dedicated switchgear if present, else the highest-rated
    protective device (tie-broken by pole count)."""
    switchgear = [c for c in comps if c.spec.device_type in _SWITCHGEAR]
    pool = switchgear or [c for c in comps if c.spec.device_type not in _INSTRUMENT_TYPES]
    if not pool:
        return None
    return max(pool, key=lambda c: (c.spec.rating_amps or 0, c.spec.poles or 0))


def _classify(c: Component, incomer: Optional[Component]) -> str:
    if incomer is not None and c is incomer:
        return GROUP_INCOMING
    if c.spec.device_type in _INSTRUMENT_TYPES:
        return GROUP_INDICATION
    return GROUP_OUTGOING


def _price_and_describe(c: Component, config: PricingConfig):
    """Return (unit_price, ref, brand, description) for a component."""
    ref = c.tag
    brand = "Schneider"
    desc = ntt_description(c)
    price = config.default_component_price

    if c.match and c.match.item:
        item = c.match.item
        if item.part_number in config.component_price_overrides:
            price = config.component_price_overrides[item.part_number]
            ref, brand = item.part_number, item.manufacturer
        elif c.match.score >= config.match_threshold:
            price = item.unit_price
            ref, brand = item.part_number, item.manufacturer
            # a standards-based (policy) or confident match carries the exact
            # catalog wording the engineer quotes — prefer it.
            if item.description and (c.match.method == "policy" or c.match.confident):
                desc = item.description
            elif not desc:
                desc = item.description
    return round(price, 2), ref, brand, desc


def ntt_description(c: Component) -> str:
    """Format an NTT-style device description from the parsed spec."""
    s = c.spec
    dt = s.device_type
    poles = f"{s.poles}P" if s.poles else None
    amps = f"{s.rating_amps:g}A" if s.rating_amps else None
    ka = f"{s.breaking_capacity_ka:g}KA" if s.breaking_capacity_ka else None

    def join(*parts):
        return " , ".join(p for p in parts if p) + " ."

    if dt == DeviceType.MCB:
        return join("MCB", poles, amps, ka, "iC60N")
    if dt in (DeviceType.RCCB, DeviceType.RCD):
        ma = "30mA"
        return join(f"Earth leakage, ID/RCCB {poles or ''}".strip(), ma, amps)
    if dt == DeviceType.MCCB:
        return join("MCCB", (f"{poles}3T" if s.poles else "3P3T"), amps, ka, "TMD")
    if dt == DeviceType.ACB:
        return join("ACB", poles, amps, ka, "Drawout")
    if dt == DeviceType.CONTACTOR:
        return join("Contactor", poles, amps)
    if dt == DeviceType.OVERLOAD:
        return join("Thermal Overload Relay", amps)
    if dt == DeviceType.ISOLATOR:
        return join("Switch Disconnector", poles, amps)
    if dt == DeviceType.SPD:
        return join("Surge Protection Device", poles, ka)
    if dt == DeviceType.METER:
        return c.raw_description or "Power Meter"
    # fall back to the drawing / catalog text
    return c.raw_description or (c.match.item.description if c.match and c.match.item else s.signature())


def _rating_text(incomer: Optional[Component]) -> str:
    if incomer and incomer.spec.rating_amps:
        return f"{incomer.spec.rating_amps:g}A"
    return ""


def _install_for(defaults: PanelDefaults, incomer: Optional[Component]) -> PanelDefaults:
    import copy
    inst = copy.copy(defaults)
    if incomer and incomer.spec.rating_amps:
        amps = incomer.spec.rating_amps
        inst.main_bb_sizing = f"Comb Bus Bar {_bb_size(amps)}"
    return inst


def _bb_size(amps: float) -> str:
    for s in (63, 100, 160, 250, 400, 630, 800, 1250, 1600, 2000, 2500):
        if amps <= s:
            return f"{s}A"
    return f"{int(amps)}A"


def _is_metering_board(name: str) -> bool:
    up = (name or "").upper()
    return "KWHM" in up or "FLOOR" in up


def _metering_size(incomer: Optional[Component], config: PricingConfig):
    """Standard NTT metering-DB size (H, W, D cm) for the incomer rating."""
    amps = (incomer.spec.rating_amps if incomer and incomer.spec.rating_amps else 160.0)
    for row in config.selection.metering_enclosures:
        if amps <= row[0]:
            return float(row[1]), float(row[2]), float(row[3])
    last = config.selection.metering_enclosures[-1]
    return float(last[1]), float(last[2]), float(last[3])


def _copper_cost(comps, layout, config: PricingConfig) -> float:
    from ..pricing.engine import build_copper_line_items
    wires = layout.wire_runs or route_wiring(comps, layout.placements, config)
    return round(sum(li.total for li in build_copper_line_items(wires, config)), 2)


# --------------------------------------------------------------------------
# profile / defaults from config
# --------------------------------------------------------------------------
def _panel_defaults(config: PricingConfig) -> PanelDefaults:
    d = PanelDefaults()
    for k, v in (config.panel_defaults or {}).items():
        if hasattr(d, k):
            setattr(d, k, v)
    return d


def _company(config: PricingConfig) -> CompanyProfile:
    c = CompanyProfile()
    for k, v in (config.company or {}).items():
        if hasattr(c, k):
            setattr(c, k, v)
    return c


def _signatories(config: PricingConfig) -> List[Signatory]:
    if config.signatories:
        return [Signatory(title=s.get("title", ""), name=s.get("name", ""))
                for s in config.signatories]
    return list(DEFAULT_SIGNATORIES)
