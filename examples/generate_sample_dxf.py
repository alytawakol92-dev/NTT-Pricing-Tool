"""Generate a sample single line diagram DXF for testing the DXF extractor.

Builds a DXF whose device symbols are block references carrying ``TAG``,
``DESC`` and ``BOARD`` attributes — exactly the structure the extractor reads.
Run once to produce ``data/sample_sld.dxf``.

    python examples/generate_sample_dxf.py
"""
from __future__ import annotations

import json
import os

import ezdxf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "sample_sld.json")
OUT = os.path.join(ROOT, "data", "sample_sld.dxf")


def build() -> str:
    with open(SRC, "r", encoding="utf-8") as fh:
        sld = json.load(fh)

    doc = ezdxf.new("R2010", setup=True)
    msp = doc.modelspace()

    # define a device symbol block with attributes
    blk = doc.blocks.new(name="DEVICE")
    blk.add_lwpolyline([(0, 0), (40, 0), (40, 20), (0, 20), (0, 0)])
    blk.add_attdef("TAG", dxfattribs={"insert": (2, 22), "height": 3.0})
    blk.add_attdef("DESC", dxfattribs={"insert": (2, -6), "height": 2.5})
    blk.add_attdef("BOARD", dxfattribs={"insert": (2, -12), "height": 2.0})

    y = 0.0
    for board in sld["boards"]:
        board_name = board["name"]
        x = 0.0
        for comp in board["components"]:
            ins = msp.add_blockref("DEVICE", (x, y))
            ins.add_auto_attribs({
                "TAG": comp.get("tag", ""),
                "DESC": comp.get("description", ""),
                "BOARD": board_name,
            })
            x += 80.0
        y -= 60.0

    doc.saveas(OUT)
    return OUT


if __name__ == "__main__":
    path = build()
    print(f"Wrote {path}")
