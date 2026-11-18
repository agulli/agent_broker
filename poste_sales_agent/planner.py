"""
Daily call planner for selling Poste Italiane products.

Given a customer base, a product catalog and a daily call target, the planner:
  1. filters out customers who must not be called (no marketing consent,
     registered in the Registro Pubblico delle Opposizioni, recently contacted,
     recently declined, explicit do-not-call);
  2. scores every (customer, product) pair with transparent business rules;
  3. keeps the best product per customer and ranks customers by score;
  4. returns the top N calls for the day (plus a backup list), each with a
     suggested product, the reasons for the suggestion and a short script;
  5. optionally spreads the calls across operators and time slots.

Only the standard library is used, so the planner runs anywhere and is easy
to test. An LLM can optionally rewrite the scripts (see api.py).
"""

from __future__ import annotations

import datetime as dt
import heapq
import json
import math
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Optional

DATA_DIR = Path(__file__).parent / "data"
DEFAULT_PRODUCTS_FILE = DATA_DIR / "products.json"
DEFAULT_CUSTOMERS_FILE = DATA_DIR / "sample_customers.json"


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
@dataclass
class PlannerConfig:
    # Do not call again within this many days of any contact.
    min_days_between_calls: int = 14
    # After a "not_interested", wait this long before calling again.
    cooldown_after_refusal_days: int = 90
    # After a sale, wait this long before proposing something new.
    cooldown_after_sale_days: int = 30
    # Callbacks the customer asked for get a boost.
    callback_boost: float = 0.25
    # Minimum score for a call to be worth making.
    min_score: float = 0.30
    # How many extra customers to propose as backup (unreachable, etc.).
    backup_ratio: float = 0.3
    # Calling window (local time). Calls are not planned on Sundays.
    call_window_start: str = "09:00"
    call_window_end: str = "20:00"
    # Average minutes per call (incl. notes), used to build the schedule.
    minutes_per_call: int = 10
    # Max share of the day's calls for a single product (keeps the mix varied).
    # 1.0 disables the cap.
    max_share_per_product: float = 0.4
    # Optional campaign weights per product id (e.g. {"buoni_fruttiferi": 1.5}).
    campaign_weights: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Product fit rules: each returns (score 0..1, list of reasons)
# --------------------------------------------------------------------------- #
Rule = Callable[[dict], tuple]


def _owns(c: dict, pid: str) -> bool:
    return pid in c.get("products_owned", [])


def fit_conto_bancoposta(c):
    if c["age"] < 18:
        return 0, []
    s, r = 0.4, ["Non ha ancora un conto BancoPosta"]
    if c.get("monthly_income_eur", 0) > 0:
        s += 0.2
        r.append("Reddito mensile da accreditare")
    if c["age"] >= 60:
        s += 0.2
        r.append("Età da accredito pensione")
    if "new_job" in c.get("life_events", []):
        s += 0.3
        r.append("Nuovo lavoro: accredito stipendio")
    return s, r


def fit_postepay_evolution(c):
    if not 18 <= c["age"] <= 45:
        return 0, []
    s, r = 0.4, [f"Età {c['age']}: target carte digitali"]
    if not _owns(c, "conto_bancoposta"):
        s += 0.2
        r.append("Nessun conto: Evolution come alternativa con IBAN")
    if "new_job" in c.get("life_events", []):
        s += 0.2
        r.append("Nuovo lavoro")
    return s, r


def fit_libretto_smart(c):
    sav = c.get("liquid_savings_eur", 0)
    if sav < 3000:
        return 0, []
    s, r = 0.4, [f"Liquidità disponibile ~{sav:,} €".replace(",", ".")]
    if sav >= 10000:
        s += 0.2
    if c["age"] >= 55:
        s += 0.1
        r.append("Profilo orientato alla sicurezza")
    return s, r


def fit_buoni_fruttiferi(c):
    sav = c.get("liquid_savings_eur", 0)
    kids = c.get("children_under_18", 0)
    if sav < 5000 and kids == 0:
        return 0, []
    s, r = 0.3, []
    if sav >= 5000:
        s += 0.2
        r.append(f"Liquidità ~{sav:,} € da far fruttare".replace(",", "."))
    if sav >= 20000:
        s += 0.1
    if kids:
        s += 0.3
        r.append(f"{kids} figli minori: Buono dedicato ai minori")
    if "child_born" in c.get("life_events", []):
        s += 0.2
        r.append("Nascita recente")
    if "inheritance" in c.get("life_events", []):
        s += 0.2
        r.append("Eredità recente")
    return s, r


def fit_polizza_vita(c):
    sav = c.get("liquid_savings_eur", 0)
    if sav < 30000 or not 35 <= c["age"] <= 75:
        return 0, []
    s, r = 0.5, [f"Patrimonio liquido elevato (~{sav:,} €)".replace(",", ".")]
    if sav >= 80000:
        s += 0.2
    if "inheritance" in c.get("life_events", []):
        s += 0.2
        r.append("Eredità recente da pianificare")
    if "retirement" in c.get("life_events", []):
        s += 0.2
        r.append("Pensionamento: TFR da investire")
    return s, r


def fit_vivere_protetti(c):
    s, r = 0.0, []
    if c.get("homeowner"):
        s += 0.35
        r.append("Proprietario di casa")
    if c.get("children_under_18", 0):
        s += 0.2
        r.append("Famiglia con figli")
    if "moving_house" in c.get("life_events", []):
        s += 0.3
        r.append("Trasloco/nuova casa")
    if c["age"] >= 50:
        s += 0.1
        r.append("Interesse per copertura salute")
    return s, r


def fit_postemobile(c):
    if c.get("mobile_operator") == "PosteMobile":
        return 0, []
    s, r = 0.3, [f"Operatore attuale: {c.get('mobile_operator', 'n.d.')}"]
    if _owns(c, "conto_bancoposta") or _owns(c, "postepay_evolution"):
        s += 0.15
        r.append("Già cliente Poste: cross-selling semplice")
    return s, r


def fit_poste_energia(c):
    if c.get("energy_provider") == "Poste Energia":
        return 0, []
    s, r = 0.25, [f"Fornitore attuale: {c.get('energy_provider', 'n.d.')}"]
    if c.get("homeowner"):
        s += 0.15
        r.append("Intestatario utenze")
    if "moving_house" in c.get("life_events", []):
        s += 0.35
        r.append("Trasloco: nuova attivazione utenze")
    return s, r


def fit_prestito(c):
    inc = c.get("monthly_income_eur", 0)
    if inc < 1200 or c["age"] > 70 or not _owns(c, "conto_bancoposta"):
        return 0, []
    s, r = 0.2, ["Correntista con reddito regolare"]
    for ev, label in (("wedding", "Matrimonio"), ("moving_house", "Trasloco"),
                      ("child_born", "Nascita")):
        if ev in c.get("life_events", []):
            s += 0.35
            r.append(f"{label}: possibile esigenza di finanziamento")
            break
    return s, r


RULES: dict[str, Rule] = {
    "conto_bancoposta": fit_conto_bancoposta,
    "postepay_evolution": fit_postepay_evolution,
    "libretto_smart": fit_libretto_smart,
    "buoni_fruttiferi": fit_buoni_fruttiferi,
    "polizza_vita_investimento": fit_polizza_vita,
    "poste_vivere_protetti": fit_vivere_protetti,
    "postemobile": fit_postemobile,
    "poste_energia": fit_poste_energia,
    "prestito_bancoposta": fit_prestito,
}


# --------------------------------------------------------------------------- #
# Eligibility (compliance first)
# --------------------------------------------------------------------------- #
def _days_since(date_str: Optional[str], today: dt.date) -> Optional[int]:
    if not date_str:
        return None
    return (today - dt.date.fromisoformat(date_str)).days


def eligibility(c: dict, today: dt.date, cfg: PlannerConfig) -> tuple[bool, str]:
    """Return (can_call, reason_if_not)."""
    if not c.get("consent_marketing"):
        return False, "no_marketing_consent"
    if c.get("in_registro_opposizioni"):
        return False, "registro_pubblico_opposizioni"
    outcome = c.get("last_outcome")
    if outcome == "do_not_call":
        return False, "do_not_call"
    days = _days_since(c.get("last_contact_date"), today)
    if days is not None:
        if outcome == "callback":
            return True, ""  # customer asked to be called back
        if days < cfg.min_days_between_calls:
            return False, "contacted_recently"
        if outcome == "not_interested" and days < cfg.cooldown_after_refusal_days:
            return False, "refusal_cooldown"
        if outcome == "sold" and days < cfg.cooldown_after_sale_days:
            return False, "recent_sale_cooldown"
    return True, ""


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
def score_customer(c: dict, products: list[dict], today: dt.date,
                   cfg: PlannerConfig) -> list[dict]:
    """Return the customer's product options, best first (empty if none fit)."""
    options = []
    for p in products:
        if _owns(c, p["id"]):
            continue
        rule = RULES.get(p["id"])
        if rule is None:
            continue
        fit, reasons = rule(c)
        if fit <= 0:
            continue
        weight = p.get("priority", 1.0) * cfg.campaign_weights.get(p["id"], 1.0)
        options.append({"product": p, "score": min(fit, 1.0) * weight,
                        "reasons": list(reasons)})
    if not options:
        return []

    # Customer-level adjustments apply to every option.
    bonus, extra = 0.0, []
    days = _days_since(c.get("last_contact_date"), today)
    if c.get("last_outcome") == "callback":
        bonus += cfg.callback_boost
        extra.append("Il cliente ha chiesto di essere richiamato")
    elif days is None:
        bonus += 0.05  # never contacted: fresh lead
    if c.get("life_events"):
        bonus += 0.05
    for o in options:
        o["score"] = round(o["score"] + bonus, 3)
        o["reasons"] += extra
    options.sort(key=lambda o: o["score"], reverse=True)
    return options


def build_script(c: dict, p: dict, reasons: list[str]) -> str:
    first_name = c["name"].split()[0]
    lines = [
        f"Buongiorno {first_name}, sono <operatore> di Poste Italiane. "
        f"La chiamo perché, in base al suo profilo, potrebbe interessarle {p['name']}. "
        "Ha due minuti?",
        p["pitch"],
        *[f"- {tp}" for tp in p.get("talking_points", [])],
    ]
    if p.get("requires_qualified_advisor"):
        lines.append("Obiettivo della chiamata: fissare un appuntamento con un "
                     "consulente in ufficio postale (non concludere al telefono).")
    lines.append("Chiusura: proporre appuntamento in ufficio postale o invio "
                 "informazioni via app/email; registrare l'esito.")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Scheduling
# --------------------------------------------------------------------------- #
_SLOT_ORDER = {"morning": 0, "afternoon": 1, "evening": 2, None: 1}


def _schedule(calls: list[dict], operators: list[str], cfg: PlannerConfig,
              today: dt.date) -> None:
    """Assign operator and time to each call, in place."""
    start = dt.datetime.combine(today, dt.time.fromisoformat(cfg.call_window_start))
    end = dt.datetime.combine(today, dt.time.fromisoformat(cfg.call_window_end))
    slot_starts = {
        "morning": start,
        "afternoon": max(start, start.replace(hour=14, minute=0)),
        "evening": max(start, start.replace(hour=17, minute=30)),
    }
    # Next free time for each operator.
    free_at = {op: start for op in operators}
    # Order calls by preferred time of day, then by priority.
    ordered = sorted(calls, key=lambda x: (_SLOT_ORDER[x["preferred_time"]],
                                           x["priority_rank"]))
    for i, call in enumerate(ordered):
        op = operators[i % len(operators)]
        slot = call["preferred_time"] or "morning"
        t = max(free_at[op], slot_starts[slot])
        call["operator"] = op
        if t + dt.timedelta(minutes=cfg.minutes_per_call) > end:
            call["scheduled_time"] = None
            call["warning"] = "outside_call_window"
            continue
        call["scheduled_time"] = t.strftime("%H:%M")
        free_at[op] = t + dt.timedelta(minutes=cfg.minutes_per_call)
    calls.sort(key=lambda x: (x.get("operator") or "", x.get("scheduled_time") or "99"))


# --------------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------------- #
def plan_daily_calls(customers: list[dict], products: list[dict], daily_calls: int,
                     today: Optional[dt.date] = None,
                     operators: Optional[list[str]] = None,
                     cfg: Optional[PlannerConfig] = None) -> dict:
    today = today or dt.date.today()
    cfg = cfg or PlannerConfig()
    if daily_calls < 1:
        raise ValueError("daily_calls must be >= 1")

    excluded: dict[str, int] = {}
    scored = []  # (customer, options)
    for c in customers:
        ok, why = eligibility(c, today, cfg)
        if not ok:
            excluded[why] = excluded.get(why, 0) + 1
            continue
        options = [o for o in score_customer(c, products, today, cfg)
                   if o["score"] >= cfg.min_score]
        if not options:
            excluded["no_suitable_product"] = excluded.get("no_suitable_product", 0) + 1
            continue
        scored.append((c, options))

    # Greedy selection: best score first, but no product may exceed its share
    # of the day; a capped customer falls back to their next-best product.
    cap = max(1, math.ceil(daily_calls * cfg.max_share_per_product))
    per_product: dict[str, int] = {}
    heap = [(-opts[0]["score"], i, 0) for i, (_, opts) in enumerate(scored)]
    heapq.heapify(heap)
    selected, leftover = [], []
    while heap:
        neg, i, k = heapq.heappop(heap)
        c, opts = scored[i]
        pid = opts[k]["product"]["id"]
        if len(selected) < daily_calls and per_product.get(pid, 0) >= cap:
            if k + 1 < len(opts):
                heapq.heappush(heap, (-opts[k + 1]["score"], i, k + 1))
            else:
                leftover.append((c, opts, 0))
            continue
        if len(selected) < daily_calls:
            per_product[pid] = per_product.get(pid, 0) + 1
            selected.append((c, opts, k))
        else:
            leftover.append((c, opts, k))

    def to_call(c, opts, k, rank):
        o = opts[k]
        p = o["product"]
        return {
            "priority_rank": rank,
            "customer_id": c["id"],
            "customer_name": c["name"],
            "phone": c.get("phone"),
            "city": c.get("city"),
            "preferred_time": c.get("preferred_time"),
            "product_id": p["id"],
            "product_name": p["name"],
            "requires_qualified_advisor": p.get("requires_qualified_advisor", False),
            "score": o["score"],
            "reasons": o["reasons"],
            "alternative_products": [x["product"]["name"]
                                     for j, x in enumerate(opts) if j != k][:2],
            "script": build_script(c, p, o["reasons"]),
        }

    calls = [to_call(c, o, k, r) for r, (c, o, k) in enumerate(selected, 1)]
    backup_n = max(1, round(daily_calls * cfg.backup_ratio))
    leftover.sort(key=lambda t: t[1][t[2]]["score"], reverse=True)
    backup = [to_call(c, o, k, len(calls) + r)
              for r, (c, o, k) in enumerate(leftover[:backup_n], 1)]
    eligible = len(scored)

    warnings = []
    if today.weekday() == 6:
        warnings.append("Domenica: verificare se le chiamate commerciali sono consentite.")
    if len(calls) < daily_calls:
        msg = f"Pianificate solo {len(calls)} chiamate su {daily_calls} richieste: "
        if len(scored) > len(calls):
            msg += ("il limite per prodotto (max_share_per_product) lascia fuori "
                    "clienti senza alternative valide; alzarlo o ampliare la base clienti.")
        else:
            msg += "ampliare la base clienti o il catalogo."
        warnings.append(msg)
    if operators:
        _schedule(calls, operators, cfg, today)
        capacity = len(operators) * _window_minutes(cfg) // cfg.minutes_per_call
        if daily_calls > capacity:
            warnings.append(f"Obiettivo di {daily_calls} chiamate superiore alla "
                            f"capacità stimata ({capacity}) con {len(operators)} operatori.")

    by_product: dict[str, int] = {}
    for c in calls:
        by_product[c["product_name"]] = by_product.get(c["product_name"], 0) + 1

    return {
        "date": today.isoformat(),
        "target_calls": daily_calls,
        "planned_calls": len(calls),
        "summary": {
            "customers_in_base": len(customers),
            "eligible_candidates": eligible,
            "excluded": excluded,
            "calls_by_product": by_product,
        },
        "warnings": warnings,
        "calls": calls,
        "backup_calls": backup,
    }


def _window_minutes(cfg: PlannerConfig) -> int:
    s = dt.time.fromisoformat(cfg.call_window_start)
    e = dt.time.fromisoformat(cfg.call_window_end)
    return (e.hour * 60 + e.minute) - (s.hour * 60 + s.minute)


# --------------------------------------------------------------------------- #
# Outcome recording (closes the daily loop)
# --------------------------------------------------------------------------- #
VALID_OUTCOMES = {"sold", "appointment", "callback", "not_interested",
                  "no_answer", "do_not_call", "wrong_number"}


def record_outcome(customers: list[dict], customer_id: str, outcome: str,
                   product_id: Optional[str] = None,
                   today: Optional[dt.date] = None) -> dict:
    if outcome not in VALID_OUTCOMES:
        raise ValueError(f"outcome must be one of {sorted(VALID_OUTCOMES)}")
    today = today or dt.date.today()
    for c in customers:
        if c["id"] == customer_id:
            c["last_contact_date"] = today.isoformat()
            c["last_outcome"] = outcome
            if outcome == "do_not_call":
                c["consent_marketing"] = False
            if outcome == "sold" and product_id:
                c.setdefault("products_owned", [])
                if product_id not in c["products_owned"]:
                    c["products_owned"].append(product_id)
            return c
    raise KeyError(customer_id)


# --------------------------------------------------------------------------- #
# Loading helpers
# --------------------------------------------------------------------------- #
def load_products(path: Path = DEFAULT_PRODUCTS_FILE) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))["products"]


def load_customers(path: Path = DEFAULT_CUSTOMERS_FILE) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))["customers"]


def save_customers(customers: list[dict], path: Path = DEFAULT_CUSTOMERS_FILE) -> None:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["customers"] = customers
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def config_as_dict(cfg: PlannerConfig) -> dict:
    return asdict(cfg)
