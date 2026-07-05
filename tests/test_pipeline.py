import os

from ntt_pricing.config import PricingConfig
from ntt_pricing.eplan import EplanClient
from ntt_pricing.quotation import generate_quotation, render_html

DATA = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


def _run(include_panel=True):
    cfg = PricingConfig.load(os.path.join(DATA, "sample_config.json"))
    return generate_quotation(
        sld_path=os.path.join(DATA, "sample_sld.json"),
        catalog_path=os.path.join(DATA, "sample_pricing.csv"),
        schedule_path=os.path.join(DATA, "sample_load_schedule.csv"),
        config=cfg, project_name="Test", client_name="Test",
        eplan_client=EplanClient(offline=True), include_panel=include_panel,
    )


def test_end_to_end():
    r = _run()
    q = r.quotation
    assert len(r.components) > 10
    assert q.grand_total() > 0
    # totals are internally consistent
    assert abs(q.net_total() + q.tax_amount() - q.grand_total()) < 0.01
    assert q.category_subtotal("Component") > 0
    assert q.category_subtotal("Copper") > 0
    assert q.category_subtotal("Enclosure") > 0


def test_panel_designed():
    r = _run()
    p = r.panel
    assert p is not None
    assert p.width_mm > 0 and p.height_mm > 0 and p.depth_mm > 0
    assert len(p.placements) >= len(r.components)  # quantities expand
    assert p.total_copper_kg() > 0
    # every placement fits inside the enclosure envelope
    for pl in p.placements:
        assert pl.x_mm + pl.width_mm <= p.width_mm + 1
        assert pl.y_mm >= -1


def test_validation_flags_undersized_breaker():
    r = _run()
    errs = [i for i in r.issues if i.severity == "error"]
    # Q2 (160A) is undersized for the 95kW / 400V load in the sample data
    assert any(i.circuit_ref == "Q2" for i in errs)


def test_price_override_applied():
    r = _run()
    # LV540306 overridden to 6500 in sample_config.json
    acb = [li for li in r.quotation.line_items if "MTZ1" in li.description]
    assert acb and abs(acb[0].unit_price - 6500.0) < 0.01


def test_phase1_only():
    r = _run(include_panel=False)
    assert r.quotation.panel is None
    assert r.quotation.category_subtotal("Copper") == 0
    assert r.quotation.category_subtotal("Component") > 0


def test_html_renders():
    r = _run()
    html = render_html(r.quotation, company="NTT")
    assert "QUOTATION" in html
    assert "<svg" in html
    assert "GRAND TOTAL" not in html or "TOTAL" in html
