"""Local web application wrapping the quotation engine.

A thin Flask layer over :func:`ntt_pricing.quotation.generate_quotation`:
upload a single line diagram, a supplier price list and (optionally) a load
schedule + pricing config, tweak the commercial inputs in a form, and get
back the rendered quotation with HTML / JSON / CSV downloads.

Designed to be run locally::

    python -m ntt_pricing.web        # opens http://127.0.0.1:5000

Each submission is processed into its own run directory under the system
temp folder; nothing is persisted to a database.
"""
from __future__ import annotations

import datetime
import os
import shutil
import tempfile
import traceback
import uuid

from flask import (Flask, abort, redirect, render_template, request,
                   send_file, url_for)
from werkzeug.utils import secure_filename

from ..config import PricingConfig
from ..eplan import EplanClient
from ..quotation import generate_quotation, write_csv, write_html, write_json

# where uploads + generated quotations for each run are stored
RUNS_DIR = os.path.join(tempfile.gettempdir(), "ntt_pricing_runs")
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "..", "data")
DATA_DIR = os.path.normpath(DATA_DIR)

_ALLOWED_SLD = {".dxf", ".json"}
_ALLOWED_TABLE = {".csv", ".xlsx", ".xlsm"}
_ALLOWED_CONFIG = {".json"}
_MAX_MB = 25


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = _MAX_MB * 1024 * 1024
    os.makedirs(RUNS_DIR, exist_ok=True)

    @app.route("/")
    def index():
        return render_template("index.html", error=request.args.get("error"),
                               max_mb=_MAX_MB)

    @app.route("/quote", methods=["POST"])
    def quote():
        token = uuid.uuid4().hex[:12]
        run_dir = os.path.join(RUNS_DIR, token)
        os.makedirs(run_dir, exist_ok=True)
        try:
            result = _process(request, run_dir)
        except _UserError as exc:
            shutil.rmtree(run_dir, ignore_errors=True)
            return redirect(url_for("index", error=str(exc)))
        except Exception:  # engine / parsing failure — show a friendly message
            shutil.rmtree(run_dir, ignore_errors=True)
            detail = traceback.format_exc(limit=2).strip().splitlines()[-1]
            return redirect(url_for("index",
                                    error=f"Could not process the files: {detail}"))
        return redirect(url_for("result", token=token))

    @app.route("/demo")
    def demo():
        """Run the pipeline on the bundled sample data for a quick look."""
        token = "demo-" + uuid.uuid4().hex[:8]
        run_dir = os.path.join(RUNS_DIR, token)
        os.makedirs(run_dir, exist_ok=True)
        cfg = PricingConfig.load(os.path.join(DATA_DIR, "sample_config.json"))
        res = generate_quotation(
            sld_path=os.path.join(DATA_DIR, "sample_sld.json"),
            catalog_path=os.path.join(DATA_DIR, "sample_pricing.csv"),
            schedule_path=os.path.join(DATA_DIR, "sample_load_schedule.csv"),
            config=cfg, project_name="Warehouse MDB-01 (sample)",
            client_name="Acme Foods Ltd", quote_number="Q-DEMO",
            date=datetime.date.today().isoformat(),
            eplan_client=EplanClient(offline=True))
        _write_outputs(res.quotation, run_dir, company="NTT Switchgear")
        _write_meta(run_dir, res)
        return redirect(url_for("result", token=token))

    @app.route("/result/<token>")
    def result(token):
        run_dir = _safe_run_dir(token)
        meta = _read_meta(run_dir)
        return render_template("result.html", token=token, meta=meta)

    @app.route("/result/<token>/view")
    def result_view(token):
        run_dir = _safe_run_dir(token)
        path = os.path.join(run_dir, "quote.html")
        if not os.path.exists(path):
            abort(404)
        return send_file(path)

    @app.route("/result/<token>/download/<fmt>")
    def download(token, fmt):
        run_dir = _safe_run_dir(token)
        if fmt not in ("html", "json", "csv"):
            abort(404)
        path = os.path.join(run_dir, f"quote.{fmt}")
        if not os.path.exists(path):
            abort(404)
        return send_file(path, as_attachment=True,
                         download_name=f"quotation.{fmt}")

    return app


# --------------------------------------------------------------------------
# request processing
# --------------------------------------------------------------------------
class _UserError(Exception):
    """A problem with the user's input worth showing verbatim."""


def _process(req, run_dir: str):
    sld = _save_upload(req, "sld", run_dir, _ALLOWED_SLD, required=True)
    catalog = _save_upload(req, "catalog", run_dir, _ALLOWED_TABLE, required=True)
    schedule = _save_upload(req, "schedule", run_dir, _ALLOWED_TABLE, required=False)
    config_path = _save_upload(req, "config", run_dir, _ALLOWED_CONFIG, required=False)

    config = PricingConfig.load(config_path) if config_path else PricingConfig()
    _apply_form_overrides(config, req.form)

    offline = req.form.get("offline") == "on"
    include_panel = req.form.get("include_panel", "on") == "on"
    eplan_key = req.form.get("eplan_key", "").strip() or None

    result = generate_quotation(
        sld_path=sld, catalog_path=catalog, schedule_path=schedule,
        config=config,
        project_name=req.form.get("project_name", "Untitled Project").strip() or "Untitled Project",
        client_name=req.form.get("client_name", "Client").strip() or "Client",
        quote_number=req.form.get("quote_number", "Q-0001").strip() or "Q-0001",
        date=req.form.get("date", "").strip() or datetime.date.today().isoformat(),
        eplan_client=EplanClient(api_key=eplan_key, offline=offline),
        include_panel=include_panel,
    )
    _write_outputs(result.quotation, run_dir,
                   company=req.form.get("company", "").strip())
    _write_meta(run_dir, result)
    return result


def _apply_form_overrides(config: PricingConfig, form) -> None:
    if form.get("currency", "").strip():
        config.currency = form["currency"].strip()
    for field, attr in (("markup", "markup_pct"), ("discount", "discount_pct"),
                        ("tax", "tax_pct"), ("copper_price", "copper_price_per_kg"),
                        ("labour_rate", "labour_rate_per_component")):
        val = form.get(field, "").strip()
        if val:
            try:
                setattr(config, attr, float(val))
            except ValueError:
                raise _UserError(f"'{field}' must be a number.")


def _save_upload(req, field, run_dir, allowed, required):
    file = req.files.get(field)
    if file is None or not file.filename:
        if required:
            raise _UserError(f"The {field} file is required.")
        return None
    name = secure_filename(file.filename)
    ext = os.path.splitext(name)[1].lower()
    if ext not in allowed:
        raise _UserError(
            f"{field}: '{ext or 'no extension'}' is not supported "
            f"(allowed: {', '.join(sorted(allowed))}).")
    path = os.path.join(run_dir, f"{field}{ext}")
    file.save(path)
    return path


def _write_outputs(quote, run_dir, company=""):
    write_html(quote, os.path.join(run_dir, "quote.html"), company=company)
    write_json(quote, os.path.join(run_dir, "quote.json"))
    write_csv(quote, os.path.join(run_dir, "quote.csv"))


def _write_meta(run_dir, result) -> None:
    import json
    q = result.quotation
    panel = result.panel
    meta = {
        "project_name": q.project_name, "client_name": q.client_name,
        "quote_number": q.quote_number, "date": q.date, "currency": q.currency,
        "device_count": len(result.components),
        "matched": sum(1 for c in result.components if c.match and c.match.confident),
        "grand_total": q.grand_total(),
        "subtotal": q.subtotal(),
        "category_totals": {li.category: 0 for li in q.line_items},
        "errors": sum(1 for i in result.issues if i.severity == "error"),
        "warnings": sum(1 for i in result.issues if i.severity == "warning"),
        "panel": None,
    }
    for li in q.line_items:
        meta["category_totals"][li.category] = round(
            meta["category_totals"].get(li.category, 0) + li.total, 2)
    if panel:
        meta["panel"] = {
            "width": round(panel.width_mm), "height": round(panel.height_mm),
            "depth": round(panel.depth_mm),
            "copper_kg": round(panel.total_copper_kg(), 1),
            "utilisation": round(panel.utilisation * 100),
            "devices_placed": len(panel.placements),
        }
    with open(os.path.join(run_dir, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh)


def _read_meta(run_dir):
    import json
    path = os.path.join(run_dir, "meta.json")
    if not os.path.exists(path):
        abort(404)
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _safe_run_dir(token: str) -> str:
    # token is generated server-side; still guard against path traversal
    if not token.replace("-", "").isalnum():
        abort(404)
    run_dir = os.path.join(RUNS_DIR, token)
    if not os.path.isdir(run_dir):
        abort(404)
    return run_dir
