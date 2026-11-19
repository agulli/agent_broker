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


# --- insurance & investment rules ----------------------------------------- #
def options(products, **kw):
    return [o["product"]["id"] for o in
            planner.score_customer(customer(**kw), products, TODAY, planner.PlannerConfig())]


def test_catalog_has_insurance_and_investment(products):
    areas = {p["area"] for p in products}
    assert {"insurance", "investment"} <= areas
    for p in products:
        assert p["id"] in planner.RULES
        if p["area"] in ("insurance", "investment"):
            assert p["requires_qualified_advisor"] and p["regulatory_note"]


def test_conservative_profile_gets_no_risky_investments(products):
    opts = options(products, age=60, liquid_savings_eur=100000, risk_profile="conservative")
    assert "fondi_bancoposta" not in opts and "polizza_multiramo" not in opts
    assert "polizza_rivalutabile" in opts


def test_dynamic_profile_gets_funds_not_ramo_i(products):
    opts = options(products, age=45, liquid_savings_eur=60000, risk_profile="dynamic")
    assert "fondi_bancoposta" in opts and "polizza_rivalutabile" not in opts


def test_self_employed_gets_pension_and_accident(products):
    opts = options(products, age=35, employment="self_employed", monthly_income_eur=3000,
                   products_owned=["conto_bancoposta"])
    assert "piano_pensionistico" in opts and "polizza_infortuni" in opts


def test_pension_fund_holder_not_offered_pip(products):
    opts = options(products, age=35, employment="employee", has_pension_fund=True)
    assert "piano_pensionistico" not in opts


def test_family_with_mortgage_gets_term_life(products):
    opts = options(products, age=38, children_under_18=2, has_mortgage=True, homeowner=True,
                   products_owned=["conto_bancoposta", "postepay_evolution"])
    assert opts[0] == "protezione_vita_tcm"


def test_investment_script_contains_regulatory_note(products):
    c = customer(age=50, liquid_savings_eur=90000, risk_profile="moderate",
                 products_owned=["conto_bancoposta", "libretto_smart", "buoni_fruttiferi"])
    call = planner.plan_daily_calls([c], products, 1, today=TODAY)["calls"][0]
    assert call["product_area"] == "investment"
    assert "MiFID" in call["script"]
