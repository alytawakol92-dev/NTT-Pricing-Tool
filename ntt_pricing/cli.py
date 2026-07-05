"""Command-line interface for the NTT Pricing Tool.

Example
-------
    python -m ntt_pricing.cli quote \
        --sld data/sample_sld.json \
        --catalog data/sample_pricing.csv \
        --schedule data/sample_load_schedule.csv \
        --config data/sample_config.json \
        --project "Warehouse MDB" --client "Acme Foods" \
        --out output/quote

Produces ``quote.html``, ``quote.json`` and ``quote.csv``.
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys

from .config import PricingConfig
from .eplan import EplanClient
from .offer import offer_from_result, write_commercial, write_technical
from .quotation import generate_quotation, write_csv, write_html, write_json


def _today() -> str:
    return datetime.date.today().isoformat()


def cmd_quote(args) -> int:
    config = PricingConfig.load(args.config)
    if args.currency:
        config.currency = args.currency
    if args.markup is not None:
        config.markup_pct = args.markup
    if args.tax is not None:
        config.tax_pct = args.tax
    if args.copper_price is not None:
        config.copper_price_per_kg = args.copper_price

    eplan = EplanClient(api_key=args.eplan_key, offline=args.offline)

    date = args.date or _today()
    result = generate_quotation(
        sld_path=args.sld,
        catalog_path=args.catalog,
        schedule_path=args.schedule,
        config=config,
        project_name=args.project,
        client_name=args.client,
        quote_number=args.quote_number,
        date=date,
        eplan_client=eplan,
        include_panel=not args.no_panel,
    )
    quote = result.quotation

    out_base = args.out
    os.makedirs(os.path.dirname(os.path.abspath(out_base)) or ".", exist_ok=True)
    written = []

    fmt = args.format
    if fmt in ("ntt", "both"):
        offer = offer_from_result(
            result, config, offer_no=args.quote_number, client=args.client,
            project_name=args.project, date=date, code=args.code,
            attention=args.attention)
        tech = write_technical(offer, out_base + "_technical.html")
        comm = write_commercial(offer, out_base + "_commercial.html")
        written += [("Technical offer", tech), ("Commercial offer", comm)]
        _print_offer_summary(offer)

    if fmt in ("generic", "both"):
        written.append(("Quotation HTML", write_html(quote, out_base + ".html", company=args.company)))
        written.append(("Quotation JSON", write_json(quote, out_base + ".json")))
        written.append(("BOM CSV", write_csv(quote, out_base + ".csv")))

    if fmt == "ntt":
        # still emit the component BOM + data alongside the NTT offer
        written.append(("BOM CSV", write_csv(quote, out_base + ".csv")))
        written.append(("Data JSON", write_json(quote, out_base + ".json")))

    _print_summary(result)
    print("\nOutputs written:")
    for label, path in written:
        print(f"  {label:<18}: {path}")
    return 0


def _print_offer_summary(offer) -> None:
    print("=" * 64)
    print(f" NTT Offer {offer.offer_no} — {offer.project_name}")
    print("=" * 64)
    for p in offer.panels:
        print(f"  Item {p.item_no}  {p.name:<12} {offer.currency_symbol} "
              f"{p.unit_price:>12,.2f}   ({p.width_cm:g}x{p.height_cm:g}x{p.depth_cm:g} cm)")
    print("-" * 64)
    print(f"  {'Net total':<20}{offer.currency_symbol} {offer.net_total():>12,.2f}")
    print(f"  {'VAT ' + str(offer.tax_pct) + '%':<20}{offer.currency_symbol} {offer.tax_amount():>12,.2f}")
    print(f"  {'GRAND TOTAL':<20}{offer.currency_symbol} {offer.grand_total():>12,.2f}")
    print("=" * 64)


def _print_summary(result) -> None:
    q = result.quotation
    print("=" * 64)
    print(f" Quotation {q.quote_number} — {q.project_name}")
    print(f" Client: {q.client_name}   Date: {q.date}")
    print("=" * 64)
    print(f" Devices extracted : {len(result.components)}")
    matched = sum(1 for c in result.components if c.match and c.match.confident)
    print(f" Confident matches : {matched}/{len(result.components)}")
    if result.panel:
        p = result.panel
        print(f" Panel envelope    : {p.width_mm:.0f} x {p.height_mm:.0f} x {p.depth_mm:.0f} mm")
        print(f" Copper mass       : {p.total_copper_kg():.1f} kg")
        print(f" Plate utilisation : {p.utilisation*100:.0f}%")
    issues = result.issues
    errs = sum(1 for i in issues if i.severity == "error")
    warns = sum(1 for i in issues if i.severity == "warning")
    if issues:
        print(f" Validation        : {errs} error(s), {warns} warning(s)")
    print("-" * 64)
    for cat, amt in _cat_totals(q).items():
        print(f"   {cat:<24}{q.currency} {amt:>12,.2f}")
    print("-" * 64)
    print(f"   {'Material subtotal':<24}{q.currency} {q.subtotal():>12,.2f}")
    print(f"   {'Markup':<24}{q.currency} {q.markup_amount():>12,.2f}")
    if q.discount_pct:
        print(f"   {'Discount':<24}{q.currency} {-q.discount_amount():>12,.2f}")
    print(f"   {'Tax':<24}{q.currency} {q.tax_amount():>12,.2f}")
    print(f"   {'GRAND TOTAL':<24}{q.currency} {q.grand_total():>12,.2f}")
    print("=" * 64)


def _cat_totals(q):
    cats = {}
    for li in q.line_items:
        cats[li.category] = round(cats.get(li.category, 0.0) + li.total, 2)
    return cats


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ntt-pricing",
        description="Automated quotation & panel design generation tool.")
    sub = parser.add_subparsers(dest="command", required=True)

    q = sub.add_parser("quote", help="Generate a quotation from a single line diagram.")
    q.add_argument("--sld", required=True, help="AutoCAD SLD file (.dxf or .json).")
    q.add_argument("--catalog", required=True, help="Supplier pricing sheet (.xlsx or .csv).")
    q.add_argument("--schedule", help="Client load schedule (.csv or .xlsx).")
    q.add_argument("--config", help="Pricing config JSON (enclosures, copper, markup...).")
    q.add_argument("--format", choices=["ntt", "generic", "both"], default="ntt",
                   help="Output format: 'ntt' technical+commercial offers (default), "
                        "'generic' single quotation, or 'both'.")
    q.add_argument("--project", default="Untitled Project")
    q.add_argument("--client", default="Client")
    q.add_argument("--company", default="", help="Your company name for the header.")
    q.add_argument("--quote-number", default="Q-0001",
                   help="Offer / quote number.")
    q.add_argument("--code", default="", help="Client code (commercial offer).")
    q.add_argument("--attention", default="", help="Attention contact (commercial offer).")
    q.add_argument("--date", default="", help="Quote date (default: today).")
    q.add_argument("--out", default="quotation", help="Output path prefix.")
    q.add_argument("--currency")
    q.add_argument("--markup", type=float, help="Override markup percent.")
    q.add_argument("--tax", type=float, help="Override tax percent.")
    q.add_argument("--copper-price", type=float, help="Override copper price per kg.")
    q.add_argument("--eplan-key", help="EPLAN Data Portal API key (or set EPLAN_API_KEY).")
    q.add_argument("--offline", action="store_true",
                   help="Skip EPLAN API; use cache + estimator only.")
    q.add_argument("--no-panel", action="store_true",
                   help="Phase 1 only — costing without panel design.")
    q.set_defaults(func=cmd_quote)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
