"""Run the full quotation pipeline on the bundled sample data.

    python examples/run_example.py

Writes the quotation to ``output/sample_quote.{html,json,csv}``.
"""
from __future__ import annotations

import os
import sys

# allow running directly ("python examples/run_example.py") without installing
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ntt_pricing.config import PricingConfig
from ntt_pricing.eplan import EplanClient
from ntt_pricing.offer import (offer_from_result, write_commercial,
                               write_technical)
from ntt_pricing.quotation import generate_quotation, write_csv, write_html

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "output")


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    config = PricingConfig.load(os.path.join(DATA, "sample_config.json"))

    result = generate_quotation(
        sld_path=os.path.join(DATA, "sample_sld.json"),
        catalog_path=os.path.join(DATA, "sample_pricing.csv"),
        schedule_path=os.path.join(DATA, "sample_load_schedule.csv"),
        config=config,
        project_name="Warehouse MDB-01",
        client_name="Acme Foods Ltd",
        quote_number="121-6-2026-R01",
        date="2026-07-05",
        eplan_client=EplanClient(offline=True),   # use estimator/cache offline
    )

    # NTT two-document offer (primary deliverable)
    offer = offer_from_result(
        result, config, offer_no="121-6-2026-R01", client="Acme Foods Ltd",
        project_name="Warehouse MDB-01", date="2026-07-05",
        attention="Eng. Ahmed")
    write_technical(offer, os.path.join(OUT, "technical_offer.html"))
    write_commercial(offer, os.path.join(OUT, "commercial_offer.html"))

    # supporting component BOM + panel-layout quotation
    write_csv(result.quotation, os.path.join(OUT, "bill_of_materials.csv"))
    write_html(result.quotation, os.path.join(OUT, "panel_quotation.html"),
               company="NTT Switchgear")

    print(f"Panels: {len(offer.panels)}  Devices: {len(result.components)}  "
          f"Grand total: {offer.currency_symbol} {offer.grand_total():,.2f}")
    for p in offer.panels:
        print(f"  Item {p.item_no}  {p.name:<10} {offer.currency_symbol} {p.unit_price:>11,.2f}")
    print(f"Wrote technical + commercial offers to {OUT}/")


if __name__ == "__main__":
    main()
