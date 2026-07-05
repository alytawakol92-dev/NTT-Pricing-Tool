import os

from ntt_pricing.config import PricingConfig
from ntt_pricing.eplan import EplanClient
from ntt_pricing.offer import (build_offer, render_commercial, render_technical)
from ntt_pricing.offer.models import (GROUP_INCOMING, GROUP_INDICATION,
                                      GROUP_OUTGOING)

DATA = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


def _offer():
    cfg = PricingConfig.load(os.path.join(DATA, "sample_config.json"))
    return build_offer(
        sld_path=os.path.join(DATA, "sample_sld.json"),
        catalog_path=os.path.join(DATA, "sample_pricing.csv"),
        config=cfg, offer_no="121-6-2026-R01", client="Acme Foods Ltd",
        project_name="Warehouse MDB-01", date="2026-07-05",
        eplan_client=EplanClient(offline=True))


def test_one_panel_per_board():
    o = _offer()
    names = [p.name for p in o.panels]
    assert names == ["MDB", "DB-1", "DB-2"]
    assert all(p.item_no == i + 1 for i, p in enumerate(o.panels))


def test_incomer_is_switchgear_for_mdb():
    o = _offer()
    mdb = o.panels[0]
    incoming = mdb.grouped_lines().get(GROUP_INCOMING, [])
    assert len(incoming) == 1
    assert "ACB" in incoming[0].description  # the 1600A Masterpact


def test_db_incomer_prefers_highest_rating():
    o = _offer()
    db1 = next(p for p in o.panels if p.name == "DB-1")
    assert db1.main_bb_rating == "63A"   # the 3P 63A subfeed, not the 40A RCCB


def test_standard_accessories_added():
    o = _offer()
    for p in o.panels:
        ind = p.grouped_lines().get(GROUP_INDICATION, [])
        descs = " ".join(l.description for l in ind)
        assert "Indication Lamp Red" in descs
        assert "Fuse" in descs


def test_enclosure_line_present():
    o = _offer()
    for p in o.panels:
        out = p.grouped_lines().get(GROUP_OUTGOING, [])
        assert any("NTT Panel" == l.brand or l.ref.startswith("NTT-") for l in out)


def test_totals_consistent():
    o = _offer()
    assert abs(sum(p.total_price for p in o.panels) - o.net_total()) < 0.01
    assert abs(o.net_total() + o.tax_amount() - o.grand_total()) < 0.01
    assert o.tax_amount() > 0


def test_renders_both_documents():
    o = _offer()
    tech = render_technical(o)
    comm = render_commercial(o)
    assert "TECHNICAL OFFER" in tech
    assert "INCOMING" in tech and "OUTGOING" in tech
    assert "Suggested dimensions" in tech
    assert "COMMERCIAL OFFER" in comm
    assert "Grand Total" in comm
    assert o.currency_symbol in comm


def test_currency_symbol_from_config():
    cfg = PricingConfig()
    cfg.currency = "EUR"
    assert cfg.symbol() == "€"
    cfg.currency = "USD"
    assert cfg.symbol() == "$"
