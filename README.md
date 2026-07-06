# NTT Pricing Tool

Automated **quotation and panel-design generation** for electrical switchgear.

Feed it a single line diagram, a client load schedule and your Schneider
component price list, and it produces the NTT / Al-Tawakol house offer —
a **Technical Offer** (per-panel spec sheets with grouped bills of material
and suggested dimensions) and a **Commercial Offer** (per-panel pricing,
grand total + VAT, terms & conditions and signatures) — validated against
the load schedule and backed by a fully dimensioned 3D panel layout.

```
 AutoCAD SLD ─┐
 Load sched. ─┼─▶  extract → match → validate → dimension → layout → price → QUOTE
 Price list  ─┘        (Phase 1: costing)          (Phase 2: panel design)
```

---

## What it does

**Phase 1 — Costing**
1. **Extract** every device from the AutoCAD single line diagram (DXF block
   attributes, nearby text, or a JSON export), preserving the MDB → branch
   circuit hierarchy.
2. **Parse specifications** from the free-text descriptions (device type,
   rating, poles, breaking capacity, curve…).
3. **Fuzzy-match** each device to your supplier price list, blending text
   similarity with specification agreement so a *100 A MCCB* never matches a
   *100 A contactor*.
4. **Cross-reference the load schedule** — flags devices undersized for the
   declared load current, rating mismatches, and missing circuits.
5. **Price** every component (with per-part overrides and a default fallback).

**Phase 2 — Panel design**
6. **Retrieve dimensions** from the EPLAN Data Portal (cached locally; a
   physics-based estimator fills any gaps so it always works offline).
7. **Place** components in 3D on the mounting plate (banded bin-packing with
   clearances and wiring ducts).
8. **Route copper** between devices along the hierarchy, sizing each
   conductor from its current.
9. **Size the enclosure** — the smallest standard box that fits everything
   (or a custom size), then price enclosure + copper + labour.
10. **Output** the NTT two-document offer plus supporting files.

## Output: the NTT offer format

Each **board** on the diagram (MDB, DB-1, …) becomes a separate physical
panel with its own enclosure, spec sheet and price. The tool produces:

* **Technical Offer** — a cover page then one spec sheet per panel: the
  construction parameters block (voltage system, mounting, IP, material,
  main busbar rating, RAL, form…), the bill of materials as
  `QTY · REF · Brand · Description` grouped into **INCOMING /
  INDICATION & INSTRUMENTS / OUTGOING** (with the standard indication lamps
  + fuse fitted automatically), and the suggested panel dimensions. No prices.
* **Commercial Offer** — a per-panel price table (`Item · Panel · Qty ·
  Unit · Total`), the grand total with VAT, the bilingual (EN/AR) terms &
  conditions and the signature block.

The letterhead, panel defaults, standard accessories, VAT, currency,
signatories and contacts are all overridable from the pricing config, so the
same engine can serve a different panel builder. Two supporting files are
also emitted: a component-level **BOM (CSV)** and the **panel-layout
quotation** (HTML with the 3D layout diagram).

## Install

```bash
pip install -r requirements.txt      # or: pip install -e .
```

Dependencies: `ezdxf`, `openpyxl`, `rapidfuzz`, `requests`, `Jinja2`.

## Quick start

### Web interface (upload files in your browser)

**Non-technical? See [GETTING_STARTED.md](GETTING_STARTED.md)** — download the
ZIP and double-click `run.bat` (Windows) or `run.sh` (Mac/Linux).

```bash
python -m ntt_pricing.web        # opens http://127.0.0.1:5000
```

A local upload page: drop in the single line diagram and price list (load
schedule and pricing config optional), fill in the project details and any
commercial overrides, and hit **Generate quotation**. You get the **Technical
Offer** and **Commercial Offer** (open/print to PDF), a per-panel price
summary, and downloads for both offers, the component BOM (CSV) and the
panel-layout quotation — all processed locally, no data leaves your machine.
Click **▶ Try with sample data** to see it run on the bundled example instantly.

Options: `--port 8080`, `--host 0.0.0.0` (share on your LAN), `--no-browser`.

### Command line / batch

```bash
python examples/run_example.py
# → output/sample_quote.html  (open in a browser, print to PDF)
```

Or the full CLI:

```bash
python -m ntt_pricing.cli quote \
    --sld       data/sample_sld.json \
    --catalog   data/sample_pricing.csv \
    --schedule  data/sample_load_schedule.csv \
    --config    data/sample_config.json \
    --project   "Warehouse MDB-01" \
    --client    "Acme Foods Ltd" \
    --company   "NTT Switchgear" \
    --quote-number 121-6-2026-R01 \
    --offline \
    --out output/offer
```

Outputs `offer_technical.html`, `offer_commercial.html` (+ a supporting
`offer.csv` / `offer.json`). Add `--format generic` for the single-document
panel quotation instead, or `--format both`.

### Key CLI options

| Option | Purpose |
|---|---|
| `--sld` | Single line diagram: `.dxf` or `.json` |
| `--catalog` | Supplier price list: `.xlsx` or `.csv` |
| `--schedule` | Client load schedule (optional): `.csv` / `.xlsx` |
| `--config` | Pricing config JSON (enclosures, copper, markup, letterhead…) |
| `--format` | `ntt` (technical + commercial, default), `generic`, or `both` |
| `--offline` | Skip the EPLAN API; use cache + estimator |
| `--no-panel` | Phase 1 only (costing, no panel design) |
| `--markup / --tax / --copper-price` | Quick overrides |
| `--eplan-key` | EPLAN Data Portal API key (or `EPLAN_API_KEY`) |

## Inputs

### Single line diagram
* **DWG** — AutoCAD's binary format. Converted to DXF automatically when a
  converter is installed: **LibreDWG** (`dwg2dxf`) or the **ODA File
  Converter**, or point the tool at one with `NTT_DWG2DXF=/path/to/converter`.
  If none is present, export the drawing to DXF from AutoCAD instead.
* **DXF** — two styles are handled:
  * **Block-based** — device symbols as block references (`INSERT`) carrying
    `TAG`, `DESC`/`RATING`, `BOARD` attributes are read directly.
  * **Graphical** — consultant drawings with no attributes, where devices are
    free-text labels (`"50A / 10KA / MCB / ELCB / 30mA"`). The graphical
    extractor recovers panels (by board-name proximity), MCB + ELCB pairs,
    quantities and incomers, and aggregates identical ways into `N × …` lines.
    **Pole count (1P/3P) is not in these labels** — it is shown graphically —
    so it is inferred (default: ≥25A → 3P) and can be corrected via a load
    schedule with a phases column.
* **PDF** — a drawing exported to PDF (with a text layer). The tokens are
  scattered — the rating (`16A,1∅`), the device keyword (`MCB`) and the
  quantity (`X9`) sit at different points — so a spatial reconstructor
  re-associates them into components (needs `pymupdf`). Quantities from
  scattered PDF text are approximate and worth a review.
* **JSON** — a lossless export: `{"boards": [{"name", "parent", "components":
  [{"tag","description","quantity"}]}]}`. See `data/sample_sld.json`.

### Load schedule / price list
CSV or XLSX. Column headers are matched flexibly by alias (e.g. *Part
Number / Ref / Catalog*, *Unit Price / List Price / Cost*), so your existing
sheets usually work unchanged.

**Multi-sheet price books** are detected automatically: a workbook with a
tab per product family (CVS, NS, NSX, DIN-rail MCBs, ACB, Motor Starters,
Meters, enclosures…), each with a `Descripion … Ref. No. … F.P` header, is
parsed across all tabs, using the **F.P** (net final price) column. The whole
Schneider catalog (10k+ refs) loads in one pass; keep it out of version
control (`.gitignore` already excludes `*Data_Base*.xlsx`).

### Component selection (least cost meeting spec)
The estimator's governing rule is **meet the electrical spec at the lowest
cost**: for each device it takes every catalog part that satisfies the
requirement (device type, poles, rating, and breaking capacity ≥ the fault
level) and picks the **cheapest** — regardless of series — because the chosen
ratings and enclosure size also drive the copper/wiring. Non-breaker rows
(mounting plates, blanking strips, bus-bar supports…) are filtered out so a
€3 accessory is never chosen as a "160A MCCB". Set `selection.objective`
to `"series"` with a `preferred_series` allow-list to pin a family when a
client mandates one. Enclosures are likewise chosen as the cheapest standard
NTT box that fits (loaded from the price book). See `SelectionPolicy` in
[`ntt_pricing/config.py`](ntt_pricing/config.py).

### Custom pricing (`--config`)
All commercial inputs live in one JSON file (`data/sample_config.json`):
copper & busbar price, per-CSA wire rates, the **enclosure catalog** with
sizes and prices, markup/discount/tax, labour rate, per-part price
**overrides**, and the matching thresholds. See
[`ntt_pricing/config.py`](ntt_pricing/config.py) for every field.

## EPLAN Data Portal & panel dimensions

The suggested panel size is **computed by the layout engine**: it places the
components on the mounting plate and then selects the smallest enclosure from
the configured catalog that fits. The component footprints come from the
EPLAN Data Portal when an `EPLAN_API_KEY` is set, otherwise from the local
cache (`data/eplan_dimensions.json`) and finally a device-physics estimator —
so the pipeline always yields dimensions, but **offline runs use estimates,
not authoritative EPLAN data**.

Because the size is snapped to your enclosure catalog, the result matches your
house standard only when that catalog holds your real stock sizes. Use
`data/ntt_config.json` (NTT wall/floor sizes incl. 120×80×25) as a starting
point — on the reference project the tool then suggests 100×80×25 cm against
the engineer's 120×80×25 (same height/depth; sized up one step for spare
ways). Set `EPLAN_API_KEY` (or `--eplan-key`) for authoritative footprints;
omit it (or pass `--offline`) to run fully offline.

## Library API

```python
from ntt_pricing import generate_quotation, PricingConfig, write_html

result = generate_quotation(
    sld_path="data/sample_sld.json",
    catalog_path="data/sample_pricing.csv",
    schedule_path="data/sample_load_schedule.csv",
    config=PricingConfig.load("data/sample_config.json"),
    project_name="Warehouse MDB-01", client_name="Acme Foods Ltd",
)
q = result.quotation
print(q.grand_total(), result.panel.width_mm, result.panel.height_mm)
write_html(q, "quote.html", company="NTT Switchgear")
```

## Project layout

```
ntt_pricing/
  extraction/   AutoCAD DWG/DXF (block-based + graphical) + spec parsing
  database/     price-list loading + fuzzy matching
  loadschedule/ load-schedule parsing + cross-validation
  eplan/        EPLAN Data Portal client + dimension estimator
  layout/       3D placement, copper routing, enclosure sizing
  pricing/      component / copper / enclosure / labour line items
  quotation/    generic quotation orchestration + HTML/JSON/CSV rendering
  offer/        NTT technical + commercial offer format (profile, builder, docs)
  web/          local Flask upload interface (python -m ntt_pricing.web)
  cli.py        command-line interface
data/           sample SLD, price list, load schedule, config
examples/       run_example.py, generate_sample_dxf.py
tests/          pytest suite
```

## Tests

```bash
python -m pytest
```

## Notes & assumptions

* Dimension estimates are conservative (slightly generous) so the panel is
  never undersized; live EPLAN data supersedes them when available.
* Copper sizing uses a configurable current density (default 4 A/mm²) — set
  it to your standard in the config.
* The load-schedule validation is advisory; always have a qualified engineer
  review flagged items before issuing a quotation.
