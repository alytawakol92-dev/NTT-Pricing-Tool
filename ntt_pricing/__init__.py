"""NTT Pricing Tool — automated quotation & panel design generation.

Extracts components from an AutoCAD single line diagram, fuzzy-matches them
against a supplier pricing database, validates against a client load
schedule, retrieves component dimensions (EPLAN Data Portal), lays out a 3D
panel, routes copper, and produces a professional itemised quotation.
"""
from .config import PricingConfig, EnclosureTier
from .models import (Component, CatalogItem, Quotation, PanelLayout,
                     LineItem, Specification, DeviceType, Dimensions)
from .quotation import (generate_quotation, PipelineResult, render_html,
                        write_html, write_json, write_csv)

__version__ = "1.0.0"

__all__ = [
    "PricingConfig", "EnclosureTier",
    "Component", "CatalogItem", "Quotation", "PanelLayout", "LineItem",
    "Specification", "DeviceType", "Dimensions",
    "generate_quotation", "PipelineResult",
    "render_html", "write_html", "write_json", "write_csv",
    "__version__",
]
