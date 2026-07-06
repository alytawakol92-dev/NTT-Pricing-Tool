"""Data models for the NTT two-document offer (technical + commercial)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .profile import (CompanyProfile, OfferTerms, PanelDefaults, Signatory)


# Component groups on a technical spec sheet, in display order.
GROUP_INCOMING = "INCOMING"
GROUP_INDICATION = "INDICATION & INSTRUMENTS"
GROUP_OUTGOING = "OUTGOING"
GROUP_ORDER = [GROUP_INCOMING, GROUP_INDICATION, GROUP_OUTGOING]


@dataclass
class ComponentLine:
    """One row of a panel's technical bill of materials."""

    qty: int
    ref: str
    brand: str
    description: str
    group: str = GROUP_OUTGOING
    unit_price: float = 0.0            # used for the commercial roll-up only

    @property
    def line_total(self) -> float:
        return round(self.qty * self.unit_price, 2)


@dataclass
class OfferPanel:
    """A single switchboard: its construction spec, BOM and price."""

    item_no: int
    name: str
    quantity: int = 1
    main_bb_rating: str = ""
    install: PanelDefaults = field(default_factory=PanelDefaults)
    lines: List[ComponentLine] = field(default_factory=list)

    # suggested enclosure size (cm) from the layout engine
    width_cm: float = 0.0
    height_cm: float = 0.0
    depth_cm: float = 0.0
    enclosure_ip: str = "IP42"

    # commercial
    components_cost: float = 0.0
    copper_cost: float = 0.0
    enclosure_cost: float = 0.0
    labour_cost: float = 0.0
    unit_price: float = 0.0           # per single panel, incl. markup

    @property
    def total_price(self) -> float:
        return round(self.unit_price * self.quantity, 2)

    def grouped_lines(self) -> Dict[str, List[ComponentLine]]:
        out: Dict[str, List[ComponentLine]] = {g: [] for g in GROUP_ORDER}
        for ln in self.lines:
            out.setdefault(ln.group, []).append(ln)
        return {g: v for g, v in out.items() if v}

    def dimensions_text(self) -> str:
        return (f"{self.enclosure_ip} , Dim {self.height_cm:g}H * {self.width_cm:g}W "
                f"* {self.depth_cm:g}D Cm")


@dataclass
class NTTOffer:
    """The complete offer: cover info, panels, commercials and terms."""

    offer_no: str
    client: str
    project_name: str
    date: str
    currency: str = "EUR"
    currency_symbol: str = "€"
    tax_pct: float = 14.0
    code: str = ""
    attention: str = ""
    subject: str = "Commercial Offer"

    panels: List[OfferPanel] = field(default_factory=list)

    company: CompanyProfile = field(default_factory=CompanyProfile)
    terms: OfferTerms = field(default_factory=OfferTerms)
    signatories: List[Signatory] = field(default_factory=list)
    contacts: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    # ---- money -------------------------------------------------------
    def net_total(self) -> float:
        return round(sum(p.total_price for p in self.panels), 2)

    def tax_amount(self) -> float:
        return round(self.net_total() * self.tax_pct / 100.0, 2)

    def grand_total(self) -> float:
        return round(self.net_total() + self.tax_amount(), 2)
