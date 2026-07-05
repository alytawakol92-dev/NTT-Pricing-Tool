"""Core data models shared across the NTT Pricing Tool pipeline.

These dataclasses form the common vocabulary that flows between the
extraction, matching, load-schedule, EPLAN, layout, pricing and quotation
stages.  Keeping them free of behaviour (other than light convenience
helpers) means every stage can be developed and tested independently.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


class DeviceType(str, Enum):
    """Coarse classification of an electrical device on a single line diagram."""

    MCCB = "MCCB"            # Moulded case circuit breaker
    MCB = "MCB"             # Miniature circuit breaker
    ACB = "ACB"             # Air circuit breaker
    CONTACTOR = "Contactor"
    OVERLOAD = "Overload Relay"
    RCD = "RCD"             # Residual current device
    RCCB = "RCCB"
    FUSE = "Fuse"
    ISOLATOR = "Isolator / Switch Disconnector"
    BUSBAR = "Busbar"
    METER = "Meter"
    SPD = "Surge Protection Device"
    CT = "Current Transformer"
    PILOT = "Pilot Device"          # lamps, push buttons
    TRANSFORMER = "Control Transformer"
    CAPACITOR = "Capacitor"
    PLC = "PLC / Controller"
    TERMINAL = "Terminal Block"
    UNKNOWN = "Unknown"


@dataclass
class Specification:
    """Structured electrical specification parsed from free-text description."""

    device_type: DeviceType = DeviceType.UNKNOWN
    rating_amps: Optional[float] = None          # nominal / frame current
    trip_amps: Optional[float] = None            # trip setting for adjustable breakers
    poles: Optional[int] = None                  # 1P, 2P, 3P, 4P
    breaking_capacity_ka: Optional[float] = None  # Icu / Ics
    voltage: Optional[float] = None              # rated voltage (V)
    curve: Optional[str] = None                  # B/C/D tripping curve for MCBs
    mounting: Optional[str] = None               # DIN / Panel / Plug-in
    manufacturer: Optional[str] = None
    raw_attributes: Dict[str, Any] = field(default_factory=dict)

    def signature(self) -> str:
        """A compact human-readable signature used for matching / logging."""
        parts: List[str] = [self.device_type.value]
        if self.poles:
            parts.append(f"{self.poles}P")
        if self.rating_amps:
            parts.append(f"{self.rating_amps:g}A")
        if self.breaking_capacity_ka:
            parts.append(f"{self.breaking_capacity_ka:g}kA")
        if self.curve:
            parts.append(f"curve-{self.curve}")
        return " ".join(parts)


@dataclass
class Dimensions:
    """Physical envelope of a component, in millimetres, plus mass in kg."""

    width_mm: float
    height_mm: float
    depth_mm: float
    weight_kg: float = 0.0
    din_modules: Optional[float] = None   # width in 17.5mm DIN modules if known
    source: str = "unknown"               # eplan-api | eplan-cache | estimated

    def footprint_area_mm2(self) -> float:
        return self.width_mm * self.height_mm

    def volume_mm3(self) -> float:
        return self.width_mm * self.height_mm * self.depth_mm


@dataclass
class Component:
    """A single device extracted from the single line diagram."""

    tag: str                              # e.g. "Q1", "-F3"
    raw_description: str                  # text as found on the drawing
    spec: Specification = field(default_factory=Specification)
    quantity: int = 1
    parent_tag: Optional[str] = None      # hierarchy: which board/section it sits under
    board: Optional[str] = None           # "MDB", "DB-1", ...
    source_handle: Optional[str] = None   # DXF entity handle for traceability

    # populated downstream
    match: Optional["MatchResult"] = None
    dimensions: Optional[Dimensions] = None

    def display_name(self) -> str:
        return f"{self.tag}: {self.spec.signature()}"


@dataclass
class CatalogItem:
    """A row from the Schneider (or any supplier) pricing Excel database."""

    part_number: str
    description: str
    unit_price: float
    currency: str = "USD"
    manufacturer: str = "Schneider Electric"
    category: Optional[str] = None
    spec: Specification = field(default_factory=Specification)
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MatchResult:
    """Outcome of fuzzy-matching an extracted component to a catalog item."""

    item: CatalogItem
    score: float                          # 0..100
    method: str = "fuzzy"                 # fuzzy | exact | spec | manual
    alternatives: List["MatchResult"] = field(default_factory=list)

    @property
    def confident(self) -> bool:
        return self.score >= 75.0


@dataclass
class LoadScheduleEntry:
    """A single circuit as declared by the client's load schedule."""

    circuit_ref: str
    description: str
    load_kw: Optional[float] = None
    current_a: Optional[float] = None
    voltage: Optional[float] = None
    phases: Optional[int] = None
    power_factor: Optional[float] = None
    breaker_rating_a: Optional[float] = None
    board: Optional[str] = None


@dataclass
class ValidationIssue:
    """A discrepancy found while cross referencing the SLD and load schedule."""

    severity: str                         # info | warning | error
    circuit_ref: Optional[str]
    message: str


@dataclass
class Placement:
    """Where a component is mounted inside the panel (mm, origin bottom-left-front)."""

    component_tag: str
    x_mm: float
    y_mm: float
    z_mm: float
    width_mm: float
    height_mm: float
    depth_mm: float
    rail: Optional[str] = None            # DIN rail identifier
    rotated: bool = False


@dataclass
class WireRun:
    """A single copper conductor routed between two placements."""

    from_tag: str
    to_tag: str
    length_mm: float
    csa_mm2: float                        # cross sectional area
    current_a: float
    kind: str = "wire"                    # wire | busbar

    def copper_mass_kg(self) -> float:
        # copper density 8.96 g/cm^3 = 8.96e-3 kg / (mm^2 * m) ... compute properly:
        # volume = csa(mm^2) * length(mm) -> mm^3 ; density 8.96e-6 kg/mm^3
        return self.csa_mm2 * self.length_mm * 8.96e-6


@dataclass
class PanelLayout:
    """Result of the 3D placement + routing stage."""

    width_mm: float
    height_mm: float
    depth_mm: float
    placements: List[Placement] = field(default_factory=list)
    wire_runs: List[WireRun] = field(default_factory=list)
    din_rail_length_mm: float = 0.0
    utilisation: float = 0.0              # mounting-plate area utilisation 0..1
    notes: List[str] = field(default_factory=list)

    def total_copper_kg(self) -> float:
        return sum(w.copper_mass_kg() for w in self.wire_runs)


@dataclass
class LineItem:
    """One priced row in the final quotation."""

    ref: str
    description: str
    quantity: float
    unit: str
    unit_price: float
    currency: str = "USD"
    category: str = "Component"

    @property
    def total(self) -> float:
        return round(self.quantity * self.unit_price, 2)


@dataclass
class Quotation:
    """The complete, priced quotation."""

    project_name: str
    client_name: str
    quote_number: str
    date: str
    currency: str = "USD"
    line_items: List[LineItem] = field(default_factory=list)
    panel: Optional[PanelLayout] = None
    validation_issues: List[ValidationIssue] = field(default_factory=list)
    markup_pct: float = 0.0
    discount_pct: float = 0.0
    tax_pct: float = 0.0
    notes: List[str] = field(default_factory=list)

    # ---- money helpers -------------------------------------------------
    def subtotal(self) -> float:
        return round(sum(li.total for li in self.line_items), 2)

    def category_subtotal(self, category: str) -> float:
        return round(sum(li.total for li in self.line_items if li.category == category), 2)

    def markup_amount(self) -> float:
        return round(self.subtotal() * self.markup_pct / 100.0, 2)

    def discount_amount(self) -> float:
        base = self.subtotal() + self.markup_amount()
        return round(base * self.discount_pct / 100.0, 2)

    def net_total(self) -> float:
        return round(self.subtotal() + self.markup_amount() - self.discount_amount(), 2)

    def tax_amount(self) -> float:
        return round(self.net_total() * self.tax_pct / 100.0, 2)

    def grand_total(self) -> float:
        return round(self.net_total() + self.tax_amount(), 2)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["subtotal"] = self.subtotal()
        d["markup_amount"] = self.markup_amount()
        d["discount_amount"] = self.discount_amount()
        d["net_total"] = self.net_total()
        d["tax_amount"] = self.tax_amount()
        d["grand_total"] = self.grand_total()
        return d
