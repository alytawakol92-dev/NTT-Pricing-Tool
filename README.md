# NTT Pricing Tool

Automated **quotation and panel-design generation** for electrical switchgear.

Feed it a single line diagram, a client load schedule and your Schneider
component price list, and it produces a professional, itemised quotation —
bill of materials, validated against the load schedule, plus a fully
dimensioned 3D panel layout with copper and enclosure costs.

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
10. **Output** a professional quotation: HTML (print-to-PDF) with a panel
    diagram, plus JSON and CSV.

## Install

```bash
pip install -r requirements.txt      # or: pip install -e .
```

Dependencies: `ezdxf`, `openpyxl`, `rapidfuzz`, `requests`, `Jinja2`.

## Quick start

### Web interface (upload files in your browser)

```bash
python -m ntt_pricing.web        # opens http://127.0.0.1:5000
```

A local upload page: drop in the single line diagram and price list (load
schedule and pricing config optional), fill in the project details and any
commercial overrides, and hit **Generate quotation**. You get the rendered
quotation with a panel diagram plus HTML / PDF / CSV / JSON downloads — all
processed locally, no data leaves your machine. Click **▶ Try with sample
data** to see it run on the bundled example instantly.

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
    --quote-number Q-2026-014 \
    --offline \
    --out output/quote
```

Outputs `quote.html`, `quote.json`, `quote.csv`.

### Key CLI options

| Option | Purpose |
|---|---|
| `--sld` | Single line diagram: `.dxf` or `.json` |
| `--catalog` | Supplier price list: `.xlsx` or `.csv` |
| `--schedule` | Client load schedule (optional): `.csv` / `.xlsx` |
| `--config` | Pricing config JSON (enclosures, copper, markup…) |
| `--offline` | Skip the EPLAN API; use cache + estimator |
| `--no-panel` | Phase 1 only (costing, no panel design) |
| `--markup / --tax / --copper-price` | Quick overrides |
| `--eplan-key` | EPLAN Data Portal API key (or `EPLAN_API_KEY`) |

## Inputs

### Single line diagram
* **DXF** — device symbols as block references (`INSERT`) carrying `TAG`,
  `DESC`/`RATING`, `BOARD` attributes are read directly; otherwise text near a
  symbol is associated by proximity. `examples/generate_sample_dxf.py` shows
  the expected structure.
* **JSON** — a lossless export: `{"boards": [{"name", "parent", "components":
  [{"tag","description","quantity"}]}]}`. See `data/sample_sld.json`.

### Load schedule / price list
CSV or XLSX. Column headers are matched flexibly by alias (e.g. *Part
Number / Ref / Catalog*, *Unit Price / List Price / Cost*), so your existing
sheets usually work unchanged.

### Custom pricing (`--config`)
All commercial inputs live in one JSON file (`data/sample_config.json`):
copper & busbar price, per-CSA wire rates, the **enclosure catalog** with
sizes and prices, markup/discount/tax, labour rate, per-part price
**overrides**, and the matching thresholds. See
[`ntt_pricing/config.py`](ntt_pricing/config.py) for every field.

## EPLAN Data Portal

`EplanClient` queries the portal for a matched part's mechanical envelope,
caches every hit in `data/eplan_dimensions.json`, and falls back to a
device-physics estimator when neither the API nor the cache can answer — so
the pipeline always yields dimensions. Set `EPLAN_API_KEY` (or `--eplan-key`)
to enable live lookups; omit it (or pass `--offline`) to run fully offline.

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
  extraction/   AutoCAD DXF + spec parsing
  database/     price-list loading + fuzzy matching
  loadschedule/ load-schedule parsing + cross-validation
  eplan/        EPLAN Data Portal client + dimension estimator
  layout/       3D placement, copper routing, enclosure sizing
  pricing/      component / copper / enclosure / labour line items
  quotation/    pipeline orchestration + HTML/JSON/CSV rendering
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
