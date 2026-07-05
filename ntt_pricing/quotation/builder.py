"""End-to-end orchestration of the quotation pipeline.

``generate_quotation`` runs the full two-phase flow:

Phase 1 (costing)
  extract → parse specs → load catalog → fuzzy match → load schedule →
  cross-validate → price components.

Phase 2 (panel design)
  fetch EPLAN dimensions → place components in 3D → route copper →
  size enclosure → price copper + enclosure + labour.

The result is a fully populated :class:`Quotation` plus a
:class:`PipelineResult` carrying the intermediate artefacts for inspection
or reporting.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from ..config import PricingConfig
from ..database import ComponentDatabase, match_all
from ..eplan import EplanClient
from ..extraction import extract_components
from ..layout import build_panel
from ..loadschedule import cross_validate, load_schedule
from ..models import (Component, LoadScheduleEntry, PanelLayout, Quotation,
                      ValidationIssue)
from ..pricing import (build_component_line_items, build_copper_line_items,
                       build_enclosure_line_item, build_labour_line_item)


@dataclass
class PipelineResult:
    quotation: Quotation
    components: List[Component]
    schedule: List[LoadScheduleEntry] = field(default_factory=list)
    panel: Optional[PanelLayout] = None
    issues: List[ValidationIssue] = field(default_factory=list)


def generate_quotation(
    sld_path: str,
    catalog_path: str,
    schedule_path: Optional[str] = None,
    config: Optional[PricingConfig] = None,
    *,
    project_name: str = "Untitled Project",
    client_name: str = "Client",
    quote_number: str = "Q-0001",
    date: str = "",
    eplan_client: Optional[EplanClient] = None,
    include_panel: bool = True,
) -> PipelineResult:
    config = config or PricingConfig()

    # ---- Phase 1: extraction, matching, validation, component pricing --
    components = extract_components(sld_path)
    db = ComponentDatabase.load(catalog_path)
    match_all(components, db, threshold=config.match_threshold)

    schedule: List[LoadScheduleEntry] = []
    issues: List[ValidationIssue] = []
    if schedule_path:
        schedule = load_schedule(schedule_path)
        issues = cross_validate(components, schedule)

    quote = Quotation(
        project_name=project_name, client_name=client_name,
        quote_number=quote_number, date=date, currency=config.currency,
        markup_pct=config.markup_pct, discount_pct=config.discount_pct,
        tax_pct=config.tax_pct, validation_issues=issues,
    )
    quote.line_items.extend(build_component_line_items(components, config))

    panel: Optional[PanelLayout] = None
    # ---- Phase 2: dimensions, layout, copper + enclosure pricing --------
    if include_panel:
        client = eplan_client or EplanClient()
        for c in components:
            c.dimensions = client.get_dimensions(c)
        client.flush()

        panel = build_panel(components, config)
        quote.panel = panel

        quote.line_items.extend(build_copper_line_items(panel.wire_runs, config))
        quote.line_items.append(build_enclosure_line_item(panel, config))

    labour = build_labour_line_item(components, config)
    if labour:
        quote.line_items.append(labour)

    _add_summary_notes(quote, components, panel)

    return PipelineResult(quotation=quote, components=components,
                          schedule=schedule, panel=panel, issues=issues)


def _add_summary_notes(quote: Quotation, components: List[Component],
                       panel: Optional[PanelLayout]) -> None:
    matched = sum(1 for c in components if c.match and c.match.confident)
    quote.notes.append(
        f"{len(components)} device(s) extracted; {matched} confidently matched "
        f"to the catalog.")
    if panel:
        quote.notes.append(
            f"Panel envelope {panel.width_mm:.0f}x{panel.height_mm:.0f}x"
            f"{panel.depth_mm:.0f} mm, mounting-plate utilisation "
            f"{panel.utilisation*100:.0f}%, copper {panel.total_copper_kg():.1f} kg.")
    errs = sum(1 for i in quote.validation_issues if i.severity == "error")
    if errs:
        quote.notes.append(
            f"⚠ {errs} validation error(s) against the load schedule — review before issue.")
