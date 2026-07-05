"""Render a :class:`Quotation` to professional output formats.

* **HTML** — a print-ready quotation (Jinja2 template) with an inline SVG of
  the panel layout.
* **JSON** — the full structured quotation for downstream systems.
* **CSV** — the bill of materials for spreadsheet import.

HTML is the primary deliverable; it prints cleanly to PDF from any browser
and needs no binary dependencies.
"""
from __future__ import annotations

import csv
import json
import os
from typing import Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..models import PanelLayout, Quotation

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "xml"]),
    )


def render_html(quote: Quotation, company: str = "",
                include_layout: bool = True) -> str:
    env = _env()
    tpl = env.get_template("quotation.html.j2")
    cat_totals = _category_totals(quote)
    svg = layout_svg(quote.panel) if (include_layout and quote.panel) else ""
    return tpl.render(q=quote, company=company, category_totals=cat_totals,
                      layout_svg=svg)


def write_html(quote: Quotation, path: str, company: str = "") -> str:
    html = render_html(quote, company=company)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return path


def write_json(quote: Quotation, path: str) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(quote.to_dict(), fh, indent=2, default=str)
    return path


def write_csv(quote: Quotation, path: str) -> str:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Ref", "Description", "Category", "Qty", "Unit",
                    f"Unit Price ({quote.currency})", f"Total ({quote.currency})"])
        for li in quote.line_items:
            w.writerow([li.ref, li.description, li.category, li.quantity,
                        li.unit, f"{li.unit_price:.2f}", f"{li.total:.2f}"])
        w.writerow([])
        w.writerow(["", "", "", "", "", "Subtotal", f"{quote.subtotal():.2f}"])
        w.writerow(["", "", "", "", "", "Markup", f"{quote.markup_amount():.2f}"])
        w.writerow(["", "", "", "", "", "Discount", f"-{quote.discount_amount():.2f}"])
        w.writerow(["", "", "", "", "", "Tax", f"{quote.tax_amount():.2f}"])
        w.writerow(["", "", "", "", "", "GRAND TOTAL", f"{quote.grand_total():.2f}"])
    return path


def _category_totals(quote: Quotation) -> Dict[str, float]:
    cats: Dict[str, float] = {}
    for li in quote.line_items:
        cats[li.category] = round(cats.get(li.category, 0.0) + li.total, 2)
    return cats


# --------------------------------------------------------------------------
# SVG panel layout diagram
# --------------------------------------------------------------------------
def layout_svg(panel: Optional[PanelLayout], max_w: int = 820) -> str:
    if panel is None or not panel.placements:
        return ""
    scale = max_w / max(panel.width_mm, 1)
    pad = 24
    W = int(panel.width_mm * scale) + pad * 2
    H = int(panel.height_mm * scale) + pad * 2 + 26

    parts: List[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'width="{W}" height="{H}" font-family="Segoe UI,Arial,sans-serif">')
    # enclosure outline
    parts.append(
        f'<rect x="{pad}" y="{pad}" width="{panel.width_mm*scale:.0f}" '
        f'height="{panel.height_mm*scale:.0f}" fill="#ffffff" stroke="#1a2332" '
        f'stroke-width="2" rx="4"/>')
    # devices (Y flipped so origin is bottom-left)
    plate_h = panel.height_mm * scale
    for p in panel.placements:
        x = pad + p.x_mm * scale
        y = pad + plate_h - (p.y_mm + p.height_mm) * scale
        w = max(p.width_mm * scale, 3)
        h = max(p.height_mm * scale, 6)
        colour = _hash_colour(p.component_tag)
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'fill="{colour}" fill-opacity="0.82" stroke="#26303d" stroke-width="0.7" rx="2"/>')
        if w > 22 and h > 12:
            parts.append(
                f'<text x="{x + w/2:.1f}" y="{y + h/2 + 3:.1f}" font-size="9" '
                f'fill="#fff" text-anchor="middle">{_esc(p.component_tag)}</text>')
    # dimension caption
    parts.append(
        f'<text x="{pad}" y="{H-8}" font-size="12" fill="#5b6472">'
        f'Enclosure {panel.width_mm:.0f} × {panel.height_mm:.0f} × {panel.depth_mm:.0f} mm '
        f'· scale 1:{1/scale:.0f} · {len(panel.placements)} devices</text>')
    parts.append("</svg>")
    return "".join(parts)


def _hash_colour(s: str) -> str:
    """Deterministic device colour derived from the tag (stable across runs)."""
    h = 0
    for ch in s:
        h = (h * 31 + ord(ch)) & 0xFFFFFF
    hue = h % 360
    return f"hsl({hue},45%,45%)"


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
