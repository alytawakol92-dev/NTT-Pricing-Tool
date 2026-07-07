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
import time
import traceback
import uuid

from flask import (Flask, Response, abort, redirect, render_template, request,
                   send_file, url_for)
from werkzeug.utils import secure_filename

from ..config import PricingConfig
from ..eplan import EplanClient
from ..offer import offer_from_result, write_commercial, write_technical
from ..quotation import generate_quotation, write_csv, write_html, write_json

# where uploads + generated quotations for each run are stored
RUNS_DIR = os.path.join(tempfile.gettempdir(), "ntt_pricing_runs")
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "..", "data")
DATA_DIR = os.path.normpath(DATA_DIR)

_ALLOWED_SLD = {".dxf", ".dwg", ".pdf", ".json"}
_ALLOWED_TABLE = {".csv", ".xlsx", ".xlsm"}
_ALLOWED_CONFIG = {".json"}
_MAX_MB = 25


# privacy controls (set as environment variables on the host)
_APP_PASSWORD = os.environ.get("APP_PASSWORD", "").strip()
_RETENTION_MIN = int(os.environ.get("RUN_RETENTION_MINUTES", "120"))


def _sweep_old_runs() -> None:
    """Delete run folders (uploads + generated offers) older than the
    retention window, so nothing lingers on the server."""
    cutoff = time.time() - _RETENTION_MIN * 60
    try:
        names = os.listdir(RUNS_DIR)
    except OSError:
        return
    for name in names:
        p = os.path.join(RUNS_DIR, name)
        try:
            if os.path.isdir(p) and os.path.getmtime(p) < cutoff:
                shutil.rmtree(p, ignore_errors=True)
        except OSError:
            pass


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = _MAX_MB * 1024 * 1024
    os.makedirs(RUNS_DIR, exist_ok=True)

    @app.route("/healthz")
    def healthz():
        return "ok", 200

    @app.before_request
    def _require_password():
        # health check is always open so the host can probe the service
        if request.path == "/healthz":
            return None
        # if APP_PASSWORD is set, gate the whole site behind HTTP basic auth
        if not _APP_PASSWORD:
            return None
        auth = request.authorization
        if auth and auth.password == _APP_PASSWORD:
            return None
        return Response(
            "Authentication required.", 401,
            {"WWW-Authenticate": 'Basic realm="NTT Pricing Tool"'})

    @app.route("/")
    def index():
        return render_template("index.html", error=request.args.get("error"),
                               max_mb=_MAX_MB)

    @app.route("/quote", methods=["POST"])
    def quote():
        _sweep_old_runs()
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
            client_name="Acme Foods Ltd", quote_number="121-6-2026-R01",
            date=datetime.date.today().isoformat(),
            eplan_client=EplanClient(offline=True))
        _finalize(run_dir, res, cfg, {
            "quote_number": "121-6-2026-R01", "client_name": "Acme Foods Ltd",
            "project_name": "Warehouse MDB-01 (sample)",
            "date": datetime.date.today().isoformat()}, company="NTT Switchgear")
        return redirect(url_for("result", token=token))

    @app.route("/result/<token>")
    def result(token):
        run_dir = _safe_run_dir(token)
        meta = _read_meta(run_dir)
        return render_template("result.html", token=token, meta=meta)

    # inline document view (for the iframe / open-in-tab)
    @app.route("/result/<token>/doc/<name>")
    def result_doc(token, name):
        return _serve(_safe_run_dir(token), name, attachment=False)

    @app.route("/result/<token>/download/<name>")
    def download(token, name):
        return _serve(_safe_run_dir(token), name, attachment=True)

    return app


# map friendly document names → (filename, download name)
_DOCS = {
    "commercial": ("commercial.html", "commercial_offer.html"),
    "technical": ("technical.html", "technical_offer.html"),
    "quote": ("quote.html", "panel_quotation.html"),
    "csv": ("quote.csv", "bill_of_materials.csv"),
    "json": ("quote.json", "quotation_data.json"),
}


def _serve(run_dir, name, attachment):
    if name not in _DOCS:
        abort(404)
    fname, dl = _DOCS[name]
    path = os.path.join(run_dir, fname)
    if not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=attachment, download_name=dl)


# --------------------------------------------------------------------------
# request processing
# --------------------------------------------------------------------------
class _UserError(Exception):
    """A problem with the user's input worth showing verbatim."""


def _process(req, run_dir: str):
    # one or more single line diagrams (a project may be split across sheets)
    slds = _save_uploads(req, "sld", run_dir, _ALLOWED_SLD, required=True)
    sld, extra_slds = slds[0], slds[1:]
    catalog = _save_upload(req, "catalog", run_dir, _ALLOWED_TABLE, required=True)
    schedule = _save_upload(req, "schedule", run_dir, _ALLOWED_TABLE, required=False)
    config_path = _save_upload(req, "config", run_dir, _ALLOWED_CONFIG, required=False)

    # default to the bundled NTT config (branding + least-cost selection +
    # local enclosures) when the user does not upload their own
    if config_path:
        config = PricingConfig.load(config_path)
    else:
        default_cfg = os.path.join(DATA_DIR, "ntt_config.json")
        config = (PricingConfig.load(default_cfg) if os.path.exists(default_cfg)
                  else PricingConfig())
    _apply_form_overrides(config, req.form)

    offline = req.form.get("offline") == "on"
    include_panel = req.form.get("include_panel", "on") == "on"
    eplan_key = req.form.get("eplan_key", "").strip() or None

    meta_form = {
        "project_name": req.form.get("project_name", "Untitled Project").strip() or "Untitled Project",
        "client_name": req.form.get("client_name", "Client").strip() or "Client",
        "quote_number": req.form.get("quote_number", "Q-0001").strip() or "Q-0001",
        "date": req.form.get("date", "").strip() or datetime.date.today().isoformat(),
        "code": req.form.get("code", "").strip(),
        "attention": req.form.get("attention", "").strip(),
    }
    result = generate_quotation(
        sld_path=sld, catalog_path=catalog, schedule_path=schedule,
        config=config, project_name=meta_form["project_name"],
        client_name=meta_form["client_name"], quote_number=meta_form["quote_number"],
        date=meta_form["date"],
        eplan_client=EplanClient(api_key=eplan_key, offline=offline),
        include_panel=include_panel, extra_sld_paths=extra_slds,
    )
    if not result.components:
        drawings = "the single line diagram" if not extra_slds \
            else "any of the single line diagrams"
        raise _UserError(
            f"No devices could be read from {drawings}, so the offer is empty. "
            "The drawing's format may not be recognised — try exporting it to "
            "DXF (or PDF with a text layer), or send the file so the extractor "
            "can be tuned to it.")
    _finalize(run_dir, result, config, meta_form,
              company=req.form.get("company", "").strip())
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


def _save_uploads(req, field, run_dir, allowed, required):
    """Save every file uploaded under *field* (the input allows multiple) and
    return their paths.  Each is checked against *allowed* and stored under a
    distinct name so several drawings can be processed together."""
    files = [f for f in req.files.getlist(field) if f and f.filename]
    if not files:
        if required:
            raise _UserError(f"At least one {field} file is required.")
        return []
    paths = []
    for i, file in enumerate(files):
        name = secure_filename(file.filename)
        ext = os.path.splitext(name)[1].lower()
        if ext not in allowed:
            raise _UserError(
                f"{field} '{name}': '{ext or 'no extension'}' is not supported "
                f"(allowed: {', '.join(sorted(allowed))}).")
        path = os.path.join(run_dir, f"{field}_{i}{ext}")
        file.save(path)
        paths.append(path)
    return paths


def _finalize(run_dir, result, config, meta_form, company="") -> None:
    """Build the NTT offer + generic quotation, write all documents and meta."""
    offer = offer_from_result(
        result, config, offer_no=meta_form["quote_number"],
        client=meta_form["client_name"], project_name=meta_form["project_name"],
        date=meta_form["date"], code=meta_form.get("code", ""),
        attention=meta_form.get("attention", ""))

    write_commercial(offer, os.path.join(run_dir, "commercial.html"))
    write_technical(offer, os.path.join(run_dir, "technical.html"))
    write_html(result.quotation, os.path.join(run_dir, "quote.html"), company=company)
    write_json(result.quotation, os.path.join(run_dir, "quote.json"))
    write_csv(result.quotation, os.path.join(run_dir, "quote.csv"))

    _write_meta(run_dir, result, offer)


def _write_meta(run_dir, result, offer) -> None:
    import json
    panel = result.panel
    meta = {
        "project_name": offer.project_name, "client_name": offer.client,
        "quote_number": offer.offer_no, "date": offer.date,
        "currency": offer.currency, "currency_symbol": offer.currency_symbol,
        "device_count": len(result.components),
        "matched": sum(1 for c in result.components if c.match and c.match.confident),
        "net_total": offer.net_total(), "tax_pct": offer.tax_pct,
        "tax_amount": offer.tax_amount(), "grand_total": offer.grand_total(),
        "panel_count": len(offer.panels),
        "panels": [{"item_no": p.item_no, "name": p.name,
                    "dims": f"{p.width_cm:g}×{p.height_cm:g}×{p.depth_cm:g} cm",
                    "unit_price": p.unit_price, "total_price": p.total_price}
                   for p in offer.panels],
        "errors": sum(1 for i in result.issues if i.severity == "error"),
        "warnings": sum(1 for i in result.issues if i.severity == "warning"),
        "copper_kg": round(panel.total_copper_kg(), 1) if panel else 0,
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
