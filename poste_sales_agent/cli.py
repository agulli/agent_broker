"""
Command-line entry point: print today's call plan for the sales team.

    python -m poste_sales_agent.cli --calls 20
    python -m poste_sales_agent.cli --calls 30 --operators Anna Marco Luca --json
    python -m poste_sales_agent.cli --record C1003 sold --product libretto_smart
"""

import argparse
import datetime as dt
import json

from . import planner


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Poste Italiane daily call planner")
    ap.add_argument("--calls", type=int, default=20, help="number of calls to make today")
    ap.add_argument("--date", type=dt.date.fromisoformat, default=None,
                    help="planning date (YYYY-MM-DD), default today")
    ap.add_argument("--operators", nargs="*", default=None, help="operator names")
    ap.add_argument("--customers", default=str(planner.DEFAULT_CUSTOMERS_FILE))
    ap.add_argument("--products", default=str(planner.DEFAULT_PRODUCTS_FILE))
    ap.add_argument("--campaign", default=None,
                    help='JSON campaign weights, e.g. \'{"buoni_fruttiferi": 1.5}\'')
    ap.add_argument("--json", action="store_true", help="print raw JSON")
    ap.add_argument("--record", nargs=2, metavar=("CUSTOMER_ID", "OUTCOME"),
                    help="record a call outcome instead of planning")
    ap.add_argument("--product", default=None, help="product id sold (with --record)")
    args = ap.parse_args(argv)

    customers = planner.load_customers(args.customers)

    if args.record:
        cid, outcome = args.record
        c = planner.record_outcome(customers, cid, outcome, args.product, args.date)
        planner.save_customers(customers, args.customers)
        print(f"Esito registrato per {c['id']} ({c['name']}): {outcome}")
        return

    cfg = planner.PlannerConfig()
    if args.campaign:
        cfg.campaign_weights = json.loads(args.campaign)

    plan = planner.plan_daily_calls(
        customers, planner.load_products(args.products), args.calls,
        today=args.date, operators=args.operators, cfg=cfg)

    if args.json:
        print(json.dumps(plan, indent=2, ensure_ascii=False))
        return
    print_plan(plan)


def print_plan(plan: dict) -> None:
    s = plan["summary"]
    print(f"\n=== Piano chiamate del {plan['date']} ===")
    print(f"Obiettivo: {plan['target_calls']} chiamate | Pianificate: {plan['planned_calls']} "
          f"| Candidati idonei: {s['eligible_candidates']} su {s['customers_in_base']}")
    if s["excluded"]:
        print("Esclusi: " + ", ".join(f"{k}={v}" for k, v in s["excluded"].items()))
    print("Mix prodotti: " + ", ".join(f"{k} ({v})" for k, v in s["calls_by_product"].items()))
    for w in plan["warnings"]:
        print(f"ATTENZIONE: {w}")
    print()
    for c in plan["calls"]:
        when = ""
        if "operator" in c:
            when = f"[{c['operator']} {c.get('scheduled_time') or 'fuori orario'}] "
        flag = " (consulente)" if c["requires_qualified_advisor"] else ""
        print(f"#{c['priority_rank']:>2} {when}{c['customer_name']} - {c['phone']} - "
              f"{c['product_name']}{flag}  score={c['score']}")
        print(f"     Perché: {'; '.join(c['reasons'])}")
    if plan["backup_calls"]:
        print("\nRiserve (se qualcuno non risponde):")
        for c in plan["backup_calls"]:
            print(f"     {c['customer_name']} - {c['phone']} - {c['product_name']}")
    print()


if __name__ == "__main__":
    main()
