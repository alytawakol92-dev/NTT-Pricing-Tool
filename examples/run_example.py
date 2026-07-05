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
from ntt_pricing.quotation import generate_quotation, write_csv, write_html, write_json

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
        quote_number="Q-2026-014",
        date="2026-07-05",
        eplan_client=EplanClient(offline=True),   # use estimator/cache offline
    )

    q = result.quotation
    write_html(q, os.path.join(OUT, "sample_quote.html"), company="NTT Switchgear")
    write_json(q, os.path.join(OUT, "sample_quote.json"))
    write_csv(q, os.path.join(OUT, "sample_quote.csv"))

    print(f"Devices: {len(result.components)}  "
          f"Panel: {result.panel.width_mm:.0f}x{result.panel.height_mm:.0f}x{result.panel.depth_mm:.0f} mm  "
          f"Total: {q.currency} {q.grand_total():,.2f}")
    print(f"Wrote quotation to {OUT}/sample_quote.html")


if __name__ == "__main__":
    main()
