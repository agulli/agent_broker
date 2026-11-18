import datetime as dt

import pytest

from poste_sales_agent import planner

TODAY = dt.date(2026, 11, 18)


def customer(**kw):
    base = {
        "id": "X1", "name": "Mario Verdi", "age": 40, "phone": "+39 300 000 0000",
        "products_owned": [], "liquid_savings_eur": 0, "monthly_income_eur": 2000,
        "homeowner": False, "children_under_18": 0, "mobile_operator": "TIM",
        "energy_provider": "Enel", "life_events": [], "consent_marketing": True,
        "in_registro_opposizioni": False, "preferred_time": None,
        "last_contact_date": None, "last_outcome": None,
    }
    base.update(kw)
    return base


@pytest.fixture
def products():
    return planner.load_products()


def test_sample_plan_respects_daily_target(products):
    plan = planner.plan_daily_calls(planner.load_customers(), products, 10, today=TODAY)
    assert plan["planned_calls"] == 10
    assert len({c["customer_id"] for c in plan["calls"]}) == 10
    ranks = [c["priority_rank"] for c in plan["calls"]]
    assert ranks == sorted(ranks)


@pytest.mark.parametrize("kw,reason", [
    ({"consent_marketing": False}, "no_marketing_consent"),
    ({"in_registro_opposizioni": True}, "registro_pubblico_opposizioni"),
    ({"last_outcome": "do_not_call", "last_contact_date": "2025-01-01"}, "do_not_call"),
    ({"last_outcome": "no_answer", "last_contact_date": "2026-11-10"}, "contacted_recently"),
    ({"last_outcome": "not_interested", "last_contact_date": "2026-10-01"}, "refusal_cooldown"),
])
def test_compliance_exclusions(products, kw, reason):
    plan = planner.plan_daily_calls([customer(**kw)], products, 5, today=TODAY)
    assert plan["calls"] == []
    assert plan["summary"]["excluded"] == {reason: 1}


def test_callback_is_called_even_if_recent(products):
    c = customer(last_outcome="callback", last_contact_date="2026-11-17")
    plan = planner.plan_daily_calls([c], products, 1, today=TODAY)
    assert plan["planned_calls"] == 1
    assert "richiamato" in " ".join(plan["calls"][0]["reasons"])


def test_never_proposes_owned_product(products):
    c = customer(products_owned=["conto_bancoposta"], liquid_savings_eur=50000)
    plan = planner.plan_daily_calls([c], products, 1, today=TODAY)
    assert plan["calls"][0]["product_id"] != "conto_bancoposta"


def test_product_share_cap(products):
    # Ten identical customers would all get the same product without the cap.
    cs = [customer(id=f"X{i}") for i in range(10)]
    plan = planner.plan_daily_calls(cs, products, 10, today=TODAY)
    counts = plan["summary"]["calls_by_product"]
    assert max(counts.values()) <= 4
    assert len(counts) >= 2
    # Customers with no good alternative are not forced into a weak pitch.
    assert plan["planned_calls"] == sum(counts.values())
    if plan["planned_calls"] < 10:
        assert "max_share_per_product" in plan["warnings"][0]


def test_campaign_weight_changes_mix(products):
    cs = [customer(id=f"X{i}", children_under_18=1) for i in range(5)]
    cfg = planner.PlannerConfig(campaign_weights={"poste_energia": 5.0},
                                max_share_per_product=1.0)
    plan = planner.plan_daily_calls(cs, products, 5, today=TODAY, cfg=cfg)
    assert all(c["product_id"] == "poste_energia" for c in plan["calls"])


def test_scheduling_assigns_operators_within_window(products):
    plan = planner.plan_daily_calls(planner.load_customers(), products, 12,
                                    today=TODAY, operators=["A", "B", "C"])
    assert {c["operator"] for c in plan["calls"]} == {"A", "B", "C"}
    for c in plan["calls"]:
        assert "09:00" <= c["scheduled_time"] <= "19:50"


def test_too_few_customers_warns(products):
    plan = planner.plan_daily_calls([customer()], products, 5, today=TODAY)
    assert plan["planned_calls"] == 1
    assert plan["warnings"]


def test_record_outcome_sale_updates_customer():
    cs = [customer()]
    planner.record_outcome(cs, "X1", "sold", "libretto_smart", TODAY)
    assert cs[0]["last_outcome"] == "sold"
    assert "libretto_smart" in cs[0]["products_owned"]
    with pytest.raises(ValueError):
        planner.record_outcome(cs, "X1", "maybe")


def test_do_not_call_removes_consent():
    cs = [customer()]
    planner.record_outcome(cs, "X1", "do_not_call", today=TODAY)
    assert cs[0]["consent_marketing"] is False
