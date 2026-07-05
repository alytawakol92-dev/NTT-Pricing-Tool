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
    # result page + downloads
    assert client.get(f"/result/{token}").status_code == 200
    assert client.get(f"/result/{token}/view").status_code == 200
    for fmt in ("html", "json", "csv"):
        assert client.get(f"/result/{token}/download/{fmt}").status_code == 200


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
    view = client.get(f"/result/{token}/view")
    assert b"QUOTATION" in view.data


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
