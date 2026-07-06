"""Tests for the multi-sheet NTT/Schneider price-book loader.

A small synthetic workbook is built in-memory (openpyxl) with the same
per-family tab structure as the real price book — a header row of
``Descripion … Ref. No. … F.P`` and the net price in the F.P column — so no
proprietary pricing is committed.
"""
import os

import pytest

openpyxl = pytest.importorskip("openpyxl")

from ntt_pricing.database import ComponentDatabase
from ntt_pricing.database.excel_db import load_ntt_workbook


def _make_workbook(path):
    from openpyxl import Workbook
    wb = Workbook()
    # sheet 1: CVS MCCBs
    ws = wb.active
    ws.title = "CVS"
    ws.append(["MCCB , CVS100-25KA"])
    ws.append(["Descripion", "", "", "Qty", "Ref. No.", "Manufacture",
               "price list", "DIS", "P.A.D", "F.P"])
    for a, ref, fp in [(100, "LV510307", 98.46), (160, "LV516303", 145.82),
                       (200, "LV525302", 186.32)]:
        ws.append([f"MCCB , 3P , {a}A , 25KA , CVS", "", "", 1, ref,
                   "Schneider", fp / 0.55, 0.45, fp, fp])
    # sheet 2: DIN-rail MCBs (need >=50 rows total to be accepted)
    ws2 = wb.create_sheet("Dil Rail")
    ws2.append(["MCB , iC60N"])
    ws2.append(["Descripion", "", "", "Qty", "Ref. No.", "Manufacture",
                "price list", "DIS", "P.A.D", "F.P"])
    for i in range(60):
        a = 10 + i % 40
        ws2.append([f"MCB , 3P , {a}A , 10KA , iC60N .", "", "", 1,
                    f"A9F773{i:02d}", "Schneider", 20.0, 0.42, 11.6, 11.6])
    wb.save(path)


def test_loads_multi_sheet(tmp_path):
    p = str(tmp_path / "book.xlsx")
    _make_workbook(p)
    items = load_ntt_workbook(p)
    assert len(items) >= 60
    parts = {i.part_number for i in items}
    assert {"LV510307", "LV516303", "LV525302"} <= parts


def test_component_database_uses_workbook(tmp_path):
    p = str(tmp_path / "book.xlsx")
    _make_workbook(p)
    db = ComponentDatabase.load(p)
    cvs = db.by_part_number("LV525302")
    assert cvs is not None
    assert abs(cvs.unit_price - 186.32) < 0.01
    assert cvs.currency == "EUR"
    # the parsed spec should recover the rating from the description
    assert cvs.spec.rating_amps == 200


def test_flat_sheet_still_works(tmp_path):
    """A plain single-sheet price list must still load via the fallback."""
    p = str(tmp_path / "flat.csv")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("Part Number,Description,Unit Price,Currency\n")
        fh.write("A9F74116,Acti9 iC60N MCB 1P 16A,12.8,USD\n")
    db = ComponentDatabase.load(p)
    assert db.by_part_number("A9F74116") is not None
