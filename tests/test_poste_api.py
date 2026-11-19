import json
import shutil

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from poste_sales_agent import planner  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    data = tmp_path / "customers.json"
    shutil.copy(planner.DEFAULT_CUSTOMERS_FILE, data)
    from poste_sales_agent import api
    monkeypatch.setattr(api, "CUSTOMERS_FILE", str(data))
    return TestClient(api.app), data


def test_ui_is_served(client):
    c, _ = client
    r = c.get("/")
    assert r.status_code == 200 and "Piano chiamate" in r.text


def test_plan_with_area_weights_and_outcome_loop(client):
    c, data = client
    plan = c.post("/plan", json={"daily_calls": 10, "date": "2026-11-19",
                                 "operators": ["Anna"], "area_weights": {"insurance": 3}}).json()
    assert plan["summary"]["calls_by_area"].get("insurance", 0) >= 3
    first = plan["calls"][0]
    r = c.post("/outcome", json={"customer_id": first["customer_id"], "outcome": "appointment",
                                 "date": "2026-11-19"})
    assert r.status_code == 200
    saved = json.loads(data.read_text())["customers"]
    assert next(x for x in saved if x["id"] == first["customer_id"])["last_outcome"] == "appointment"
    again = c.post("/plan", json={"daily_calls": 10, "date": "2026-11-19"}).json()
    assert first["customer_id"] not in [x["customer_id"] for x in again["calls"]]
