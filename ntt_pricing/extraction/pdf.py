"""Extract components from a single line diagram supplied as a PDF.

A drawing exported to PDF keeps a text layer, but the labels are broken into
scattered tokens — the rating, the device keyword and the quantity of one
circuit sit at different coordinates on the sheet.  We pull every text token
with its position (PyMuPDF) and hand them to the scattered-token
reconstructor, which re-associates them spatially into components.
"""
from __future__ import annotations

import os
from typing import List, Tuple

from ..models import Component

try:
    import fitz  # PyMuPDF
    _HAVE_FITZ = True
except Exception:  # pragma: no cover
    _HAVE_FITZ = False


def extract_from_pdf(path: str) -> List[Component]:
    if not _HAVE_FITZ:
        raise RuntimeError(
            "Reading a PDF single line diagram needs PyMuPDF. "
            "Install it with 'pip install pymupdf', or export the drawing to "
            "DXF / JSON.")
    entries = pdf_tokens(path)
    if not entries:
        raise RuntimeError(
            "No text layer found in the PDF — it may be a scanned image. "
            "Supply a vector PDF, DXF or JSON export.")

    # a graphical panel-schedule PDF parses with the graphical extractor; the
    # more common scattered-token SLD uses the reconstructor.
    from .graphical import is_graphical
    from .scattered import extract_scattered
    plain = [t for _p, t in entries]
    comps = extract_scattered(entries)
    if comps:
        return comps
    if is_graphical(plain):
        from .graphical import extract_graphical
        return extract_graphical(entries)
    return []


def pdf_tokens(path: str) -> List[Tuple[Tuple[float, float], str]]:
    """Return [((x, y), text)] for every word token, y flipped to a
    bottom-left origin so downstream geometry matches the CAD convention."""
    doc = fitz.open(path)
    entries: List[Tuple[Tuple[float, float], str]] = []
    for page in doc:
        height = page.rect.height
        for w in page.get_text("words"):
            x0, y0, x1, y1, text = w[0], w[1], w[2], w[3], w[4]
            if not text.strip():
                continue
            cx = (x0 + x1) / 2.0
            cy = height - (y0 + y1) / 2.0
            entries.append(((cx, cy), text))
    doc.close()
    return entries
