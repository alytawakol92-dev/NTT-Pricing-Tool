"""Extract the component hierarchy from an AutoCAD single line diagram.

Real single line diagrams carry device information in one of three ways,
and this module handles all of them:

1. **Block attributes** — the cleanest case.  SLD symbol blocks (INSERT
   entities) carry ATTRIB tags such as ``TAG``, ``DESC``/``RATING``,
   ``BOARD``.  We read them directly.
2. **Free text near symbols** — text (TEXT / MTEXT) placed next to a block
   is associated by proximity when the block has no attributes.
3. **Structured JSON export** — a lossless, tool-friendly representation
   ``{"boards": [{"name": ..., "components": [...]}]}`` for when a DXF is
   unavailable or has already been digitised.

The output is a flat list of :class:`Component` with ``board`` / ``parent_tag``
populated so the MDB → branch-circuit hierarchy is preserved.
"""
from __future__ import annotations

import json
import math
import os
from typing import Dict, List, Optional, Tuple

from ..models import Component
from .specs import parse_specification

try:  # ezdxf is optional at import time so the JSON path always works
    import ezdxf  # type: ignore
    _HAVE_EZDXF = True
except Exception:  # pragma: no cover
    _HAVE_EZDXF = False


# ATTRIB tag names we recognise (upper-cased), mapped to a canonical field.
_ATTR_TAG = {"TAG", "REF", "DESIGNATION", "ID", "NAME"}
_ATTR_DESC = {"DESC", "DESCRIPTION", "RATING", "TYPE", "SPEC", "VALUE"}
_ATTR_BOARD = {"BOARD", "PANEL", "SECTION", "DB", "GROUP", "FEEDER"}
_ATTR_QTY = {"QTY", "QUANTITY", "NO", "COUNT"}


def extract_components(path: str) -> List[Component]:
    """Dispatch to the correct extractor based on file extension."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".json":
        return extract_from_json(path)
    if ext in (".dxf", ".dwg"):
        if not _HAVE_EZDXF:
            raise RuntimeError(
                "ezdxf is required to read DXF/DWG single line diagrams. "
                "Install it with 'pip install ezdxf', or supply a JSON export."
            )
        if ext == ".dwg":
            from .dwg import convert_dwg_to_dxf
            path = convert_dwg_to_dxf(path)
        return extract_from_dxf(path)
    raise ValueError(f"Unsupported single line diagram format: {ext}")


# --------------------------------------------------------------------------
# JSON export path
# --------------------------------------------------------------------------
def extract_from_json(path: str) -> List[Component]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return components_from_dict(data)


def components_from_dict(data: Dict) -> List[Component]:
    components: List[Component] = []
    boards = data.get("boards")
    if boards is None:
        # flat list form
        boards = [{"name": data.get("board", "MDB"),
                   "components": data.get("components", [])}]
    for board in boards:
        board_name = board.get("name", "MDB")
        parent = board.get("parent")
        for c in board.get("components", []):
            desc = c.get("description") or c.get("desc") or ""
            tag = c.get("tag") or c.get("ref") or _auto_tag(len(components))
            comp = Component(
                tag=str(tag),
                raw_description=str(desc),
                spec=parse_specification(str(desc)),
                quantity=int(c.get("quantity", c.get("qty", 1)) or 1),
                board=board_name,
                parent_tag=c.get("parent_tag", parent),
            )
            components.append(comp)
    return components


# --------------------------------------------------------------------------
# DXF path
# --------------------------------------------------------------------------
def extract_from_dxf(path: str) -> List[Component]:
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()

    components: List[Component] = []
    texts: List[Tuple[Tuple[float, float], str, str]] = []  # (pos, text, layer)

    # 1) gather free text for proximity association
    for e in msp.query("TEXT MTEXT"):
        txt = _entity_text(e)
        if not txt:
            continue
        pos = _entity_pos(e)
        texts.append((pos, txt, e.dxf.layer))

    # 1a) if there are no attributed device blocks but the drawing is a
    #     graphical SLD (breaker labels as free text), use the graphical
    #     extractor — it recovers panels, MCB+ELCB pairs and quantities.
    has_attr_blocks = any(len(list(ins.attribs)) > 0 for ins in msp.query("INSERT"))
    if not has_attr_blocks:
        from .graphical import extract_graphical, is_graphical
        plain = [t for (_p, t, _l) in texts]
        if is_graphical(plain):
            entries = [((p[0], p[1]), t) for (p, t, _l) in texts]
            comps = extract_graphical(entries)
            if comps:
                return comps

    # 2) walk block references (device symbols)
    used_text_ids = set()
    for ins in msp.query("INSERT"):
        attribs = {a.dxf.tag.upper(): a.dxf.text for a in ins.attribs}
        pos = _entity_pos(ins)
        board = _first(attribs, _ATTR_BOARD) or _infer_board(ins.dxf.layer)

        tag = _first(attribs, _ATTR_TAG)
        desc = _first(attribs, _ATTR_DESC)

        if desc is None:
            # no attribute description → grab nearest free text
            nearest = _nearest_text(pos, texts, used_text_ids)
            if nearest is not None:
                idx, txt = nearest
                used_text_ids.add(idx)
                desc = txt
        if desc is None and tag is None:
            # a symbol block with neither attributes nor nearby text — skip
            continue

        qty_raw = _first(attribs, _ATTR_QTY)
        qty = int(float(qty_raw)) if qty_raw and _is_number(qty_raw) else 1

        comp = Component(
            tag=str(tag or ins.dxf.name or _auto_tag(len(components))),
            raw_description=str(desc or ins.dxf.name or ""),
            spec=parse_specification(str(desc or ins.dxf.name or "")),
            quantity=qty,
            board=board,
            source_handle=str(ins.dxf.handle),
        )
        components.append(comp)

    # 3) fallback: if the drawing carried no usable block symbols, mine
    #    stand-alone text that looks like a device description.
    if not components:
        for idx, (pos, txt, layer) in enumerate(texts):
            spec = parse_specification(txt)
            if spec.device_type.name != "UNKNOWN" or spec.rating_amps:
                components.append(Component(
                    tag=_auto_tag(idx),
                    raw_description=txt,
                    spec=spec,
                    board=_infer_board(layer),
                ))

    _assign_hierarchy(components)
    return components


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _entity_text(e) -> str:
    try:
        if e.dxftype() == "MTEXT":
            return e.plain_text().strip()
        return str(e.dxf.text).strip()
    except Exception:
        return ""


def _entity_pos(e) -> Tuple[float, float]:
    try:
        if e.dxftype() == "INSERT":
            p = e.dxf.insert
        elif e.dxftype() == "MTEXT":
            p = e.dxf.insert
        else:
            p = e.dxf.insert if e.dxf.hasattr("insert") else e.dxf.align_point
        return (float(p[0]), float(p[1]))
    except Exception:
        return (0.0, 0.0)


def _nearest_text(pos, texts, used) -> Optional[Tuple[int, str]]:
    best = None
    best_d = None
    for idx, (tpos, txt, _layer) in enumerate(texts):
        if idx in used:
            continue
        d = math.hypot(pos[0] - tpos[0], pos[1] - tpos[1])
        if best_d is None or d < best_d:
            best, best_d = (idx, txt), d
    # only associate if reasonably close (within a symbol's neighbourhood)
    if best is not None and best_d is not None and best_d < 250.0:
        return best
    return None


def _first(attribs: Dict[str, str], names) -> Optional[str]:
    for n in names:
        if n in attribs and str(attribs[n]).strip():
            return str(attribs[n]).strip()
    return None


def _infer_board(layer: str) -> str:
    if not layer:
        return "MDB"
    up = layer.upper()
    for token in ("MDB", "MSB", "SMDB", "DB", "PANEL", "LV"):
        if token in up:
            return layer
    return "MDB"


def _assign_hierarchy(components: List[Component]) -> None:
    """Best-effort parent assignment: incomers/main breakers become parents.

    A component whose board differs from ``MDB`` is treated as a branch feeder
    parented to the main board's incomer when one is identifiable.
    """
    main_incomer = None
    for c in components:
        if c.board in (None, "MDB") and c.spec.device_type.name in ("ACB", "MCCB"):
            if main_incomer is None or (c.spec.rating_amps or 0) > (main_incomer.spec.rating_amps or 0):
                main_incomer = c
    for c in components:
        if c.parent_tag:
            continue
        if main_incomer and c is not main_incomer:
            c.parent_tag = main_incomer.tag


def _auto_tag(i: int) -> str:
    return f"Q{i + 1}"


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except (TypeError, ValueError):
        return False
