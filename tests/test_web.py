import io
import os

import pytest

from ntt_pricing.web import create_app

DATA = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _file(name):
    with open(os.path.join(DATA, name), "rb") as fh:
        return io.BytesIO(fh.read())


def test_index_ok(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"NTT Pricing Tool" in r.data


def test_demo_flow(client):
    r = client.get("/demo")
    assert r.status_code == 302
    token = r.headers["Location"].rstrip("/").split("/")[-1]
    # result page + documents
    assert client.get(f"/result/{token}").status_code == 200
    for name in ("commercial", "technical", "quote", "csv", "json"):
        assert client.get(f"/result/{token}/doc/{name}").status_code == 200
        assert client.get(f"/result/{token}/download/{name}").status_code == 200
    # commercial offer content is present
    comm = client.get(f"/result/{token}/doc/commercial")
    assert b"COMMERCIAL OFFER" in comm.data
    assert b"Financial Offer" in comm.data


def test_quote_upload(client):
    data = {
        "sld": (_file("sample_sld.json"), "sample_sld.json"),
        "catalog": (_file("sample_pricing.csv"), "sample_pricing.csv"),
        "schedule": (_file("sample_load_schedule.csv"), "sample_load_schedule.csv"),
        "project_name": "Web Test", "offline": "on", "include_panel": "on",
    }
    r = client.post("/quote", data=data, content_type="multipart/form-data")
    assert r.status_code == 302
    assert "/result/" in r.headers["Location"]
    token = r.headers["Location"].rstrip("/").split("/")[-1]
    tech = client.get(f"/result/{token}/doc/technical")
    assert b"TECHNICAL OFFER" in tech.data
    assert b"INCOMING" in tech.data


def test_unknown_doc_404(client):
    r = client.get("/demo")
    token = r.headers["Location"].rstrip("/").split("/")[-1]
    assert client.get(f"/result/{token}/doc/nope").status_code == 404


def test_missing_required_file_redirects_with_error(client):
    data = {"catalog": (_file("sample_pricing.csv"), "sample_pricing.csv")}
    r = client.post("/quote", data=data, content_type="multipart/form-data")
    assert r.status_code == 302
    assert "error=" in r.headers["Location"]


def test_bad_token_404(client):
    assert client.get("/result/nonexistent123").status_code == 404


def test_rejects_bad_extension(client):
    data = {
        "sld": (io.BytesIO(b"nope"), "diagram.txt"),
        "catalog": (_file("sample_pricing.csv"), "sample_pricing.csv"),
    }
    r = client.post("/quote", data=data, content_type="multipart/form-data")
    assert r.status_code == 302
    assert "error=" in r.headers["Location"]


def _json_board(name, tag, desc):
    import json
    payload = {"boards": [{"name": name,
                           "components": [{"tag": tag, "description": desc}]}]}
    return io.BytesIO(json.dumps(payload).encode())


def test_multiple_sld_upload_combines_panels(client):
    # two drawings uploaded together must both appear as panels in one offer
    data = {
        "sld": [
            (_json_board("DB-ALPHA", "Q1", "MCCB 3P 100A 25kA"), "alpha.json"),
            (_json_board("DB-BETA", "Q1", "MCCB 3P 250A 36kA"), "beta.json"),
        ],
        "catalog": (_file("sample_pricing.csv"), "sample_pricing.csv"),
        "project_name": "Multi", "offline": "on",
    }
    r = client.post("/quote", data=data, content_type="multipart/form-data")
    assert r.status_code == 302
    assert "/result/" in r.headers["Location"]
    token = r.headers["Location"].rstrip("/").split("/")[-1]
    tech = client.get(f"/result/{token}/doc/technical").data
    assert b"DB-ALPHA" in tech and b"DB-BETA" in tech
