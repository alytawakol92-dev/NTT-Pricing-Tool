"""Configuration and custom pricing inputs for the NTT Pricing Tool.

Everything a user might want to override without touching code lives here:
enclosure price tables, copper price, wiring rules, markup/tax and the
matching thresholds.  A :class:`PricingConfig` can be loaded from a JSON
file so estimators can keep their own rate cards under version control.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional


@dataclass
class EnclosureTier:
    """One standard enclosure size and its price.

    The layout engine computes a required internal volume; the pricing engine
    then selects the smallest tier that fits and charges its price.
    """

    name: str
    width_mm: float
    height_mm: float
    depth_mm: float
    price: float
    ip_rating: str = "IP54"
    material: str = "Powder-coated steel"

    def fits(self, w: float, h: float, d: float) -> bool:
        return self.width_mm >= w and self.height_mm >= h and self.depth_mm >= d

    def volume_mm3(self) -> float:
        return self.width_mm * self.height_mm * self.depth_mm


# Sensible default enclosure catalog (Schneider Spacial-style sizes).
DEFAULT_ENCLOSURES: List[EnclosureTier] = [
    EnclosureTier("Wall box 300x400x200", 300, 400, 200, 145.0, "IP66"),
    EnclosureTier("Wall box 500x500x250", 500, 500, 250, 240.0, "IP66"),
    EnclosureTier("Wall box 600x800x300", 600, 800, 300, 430.0, "IP66"),
    EnclosureTier("Floor 600x1200x400", 600, 1200, 400, 780.0, "IP55"),
    EnclosureTier("Floor 800x1800x400", 800, 1800, 400, 1180.0, "IP55"),
    EnclosureTier("Floor 800x2000x600", 800, 2000, 600, 1620.0, "IP55"),
    EnclosureTier("Floor 1000x2000x600", 1000, 2000, 600, 1980.0, "IP55"),
    EnclosureTier("Floor 1200x2000x600", 1200, 2000, 600, 2350.0, "IP55"),
]


@dataclass
class SelectionPolicy:
    """Component-selection standards — how the estimator picks a specific
    catalog part for a device, beyond raw fuzzy text matching.

    Encodes the engineering conventions an NTT estimator applies: the breaker
    *series* per rating tier, a minimum breaking capacity (drawings often
    under-state it), the standard rating a sub-feeder gets, and the frame the
    main incomer uses.
    """

    # MCCB series by rating tier: (max_amps, series_token, min_kA)
    mccb_series_rules: List = field(default_factory=lambda: [
        [630.0, "CVS", 25.0],       # feeders / distribution → Easypact CVS 25kA
        [1000000.0, "NS", 50.0],    # large mains → NS-frame MCCB 50kA
    ])
    mcb_series: str = "iC60N"       # modular MCBs
    mcb_ref_prefix: str = "A9F"     # prefer Acti9 order codes over duplicates
    rccb_ref_prefix: str = "A9"

    # sub-feeder rule: a feed to a downstream board is rated to that board's
    # main, not to its diversified demand.
    flat_feeder_amps: float = 50.0
    flat_feeder_poles: int = 3

    # main incomer: derive Icu from the system fault level, not the busbar note
    main_mccb_min_amps: float = 800.0    # at/above this a main uses an NS MCCB
    prefer_cheapest: bool = True
    enabled: bool = True

    # metering distribution boards reserve space for kWh meters and use
    # standard NTT enclosure sizes by incomer rating (H×W×D cm).
    reserve_kwhm_space: bool = True
    metering_enclosures: List = field(default_factory=lambda: [
        # [max_incomer_amps, height_cm, width_cm, depth_cm]
        [160.0, 140.0, 80.0, 25.0],
        [250.0, 140.0, 100.0, 30.0],
        [400.0, 180.0, 100.0, 30.0],
    ])
    # main switchboards (incomer >= main_mccb_min_amps) are floor-standing
    main_enclosure_cm: List = field(default_factory=lambda: [200.0, 140.0, 60.0])


@dataclass
class PricingConfig:
    """Full set of tunable inputs for a quotation run."""

    currency: str = "USD"
    selection: SelectionPolicy = field(default_factory=SelectionPolicy)

    # commercial
    markup_pct: float = 15.0            # applied to material subtotal
    discount_pct: float = 0.0
    tax_pct: float = 14.0               # VAT / sales tax
    labour_rate_per_component: float = 12.0   # assembly labour per device

    # copper / wiring
    copper_price_per_kg: float = 11.5
    busbar_price_per_kg: float = 14.0
    wire_price_per_meter: Dict[str, float] = field(default_factory=lambda: {
        # csa(mm^2) -> price per metre of insulated copper wire
        "1.5": 0.35, "2.5": 0.5, "4": 0.75, "6": 1.05, "10": 1.7,
        "16": 2.6, "25": 3.9, "35": 5.4, "50": 7.6, "70": 10.5,
        "95": 14.0, "120": 17.5, "150": 22.0, "185": 27.5, "240": 35.0,
    })
    # per-ampere copper cross section rule of thumb (A -> mm^2)
    current_density_a_per_mm2: float = 4.0

    # enclosure
    enclosures: List[EnclosureTier] = field(default_factory=lambda: list(DEFAULT_ENCLOSURES))
    enclosure_fill_factor: float = 0.55   # usable fraction of plate area
    enclosure_markup_pct: float = 10.0

    # component pricing overrides: part_number -> unit price
    component_price_overrides: Dict[str, float] = field(default_factory=dict)
    # fallback unit price when a component cannot be matched to the catalog
    default_component_price: float = 25.0

    # matching
    match_threshold: float = 60.0        # minimum score to accept a match
    confident_threshold: float = 75.0

    # NTT offer format
    currency_symbol: str = ""            # "" → derived from currency code
    include_standard_accessories: bool = True   # fit indication lamps + fuse per panel
    panel_defaults: Dict[str, str] = field(default_factory=dict)   # PanelDefaults overrides
    company: Dict[str, str] = field(default_factory=dict)          # CompanyProfile overrides
    signatories: List[Dict[str, str]] = field(default_factory=list)  # [{title,name}]
    contacts: List[str] = field(default_factory=list)

    # layout
    component_clearance_mm: float = 20.0   # gap between adjacent devices
    din_rail_pitch_mm: float = 150.0       # vertical spacing between rails
    wiring_duct_width_mm: float = 40.0

    @classmethod
    def load(cls, path: Optional[str]) -> "PricingConfig":
        cfg = cls()
        if not path:
            return cfg
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: Dict) -> "PricingConfig":
        cfg = cls()
        for key, value in data.items():
            if key == "enclosures" and isinstance(value, list):
                cfg.enclosures = [EnclosureTier(**e) for e in value]
            elif key == "selection" and isinstance(value, dict):
                pol = SelectionPolicy()
                for k, v in value.items():
                    if hasattr(pol, k):
                        setattr(pol, k, v)
                cfg.selection = pol
            elif hasattr(cfg, key):
                setattr(cfg, key, value)
        return cfg

    def to_dict(self) -> Dict:
        return asdict(self)

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)

    # ---- helpers -------------------------------------------------------
    def wire_price(self, csa_mm2: float) -> float:
        """Nearest wire price per metre for a given cross section."""
        key = _nearest_csa_key(csa_mm2, self.wire_price_per_meter.keys())
        return self.wire_price_per_meter[key]

    def symbol(self) -> str:
        """Currency symbol for display; falls back to a small lookup then the code."""
        if self.currency_symbol:
            return self.currency_symbol
        return {"EUR": "€", "USD": "$", "GBP": "£", "EGP": "E£",
                "AED": "د.إ", "SAR": "﷼"}.get(self.currency.upper(), self.currency)

    def csa_for_current(self, current_a: float) -> float:
        """Standard copper cross section (mm^2) sized for a current."""
        required = current_a / max(self.current_density_a_per_mm2, 0.1)
        for csa in STANDARD_CSA:
            if csa >= required:
                return csa
        return STANDARD_CSA[-1]


STANDARD_CSA: List[float] = [1.5, 2.5, 4, 6, 10, 16, 25, 35, 50, 70, 95, 120, 150, 185, 240, 300]


def _nearest_csa_key(value: float, keys) -> str:
    best = None
    best_diff = None
    for k in keys:
        diff = abs(float(k) - value)
        if best_diff is None or diff < best_diff:
            best, best_diff = k, diff
    return best if best is not None else "2.5"
