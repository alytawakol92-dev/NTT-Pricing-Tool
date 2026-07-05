"""Render an :class:`NTTOffer` to the technical and commercial offer documents.

Two print-ready HTML documents matching the NTT / Al-Tawakol house format:

* **Technical offer** — cover page + one spec sheet per panel (installation
  parameters block, BOM grouped INCOMING / INDICATION & INSTRUMENTS /
  OUTGOING, suggested dimensions). No prices.
* **Commercial offer** — cover page + per-panel price table with the grand
  total (+ tax), the bilingual terms & conditions and the signatures.
"""
from __future__ import annotations

import os

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import NTTOffer

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.filters["money"] = lambda v: f"{v:,.2f}"
    return env


def render_technical(offer: NTTOffer) -> str:
    return _env().get_template("technical_offer.html.j2").render(o=offer)


def render_commercial(offer: NTTOffer) -> str:
    return _env().get_template("commercial_offer.html.j2").render(o=offer)


def write_technical(offer: NTTOffer, path: str) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render_technical(offer))
    return path


def write_commercial(offer: NTTOffer, path: str) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render_commercial(offer))
    return path
