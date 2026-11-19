"""Generate fictional demo customers: python -m poste_sales_agent.data.generate_sample"""
import json, random, datetime
from pathlib import Path
random.seed(42)
first = ["Giulia","Marco","Francesca","Luca","Chiara","Alessandro","Sara","Matteo","Elena","Davide","Anna","Giuseppe","Martina","Paolo","Valentina","Roberto","Federica","Stefano","Silvia","Andrea","Laura","Francesco","Paola","Giovanni","Rosa","Antonio","Lucia","Salvatore","Maria","Lorenzo"]
last = ["Rossi","Russo","Ferrari","Esposito","Bianchi","Romano","Colombo","Ricci","Marino","Greco","Bruno","Gallo","Conti","De Luca","Mancini","Costa","Giordano","Rizzo","Lombardi","Moretti"]
cities = ["Roma","Milano","Napoli","Torino","Palermo","Bologna","Firenze","Bari","Catania","Verona"]
mobile = ["TIM","Vodafone","WindTre","Iliad","PosteMobile","Fastweb"]
energy = ["Enel","Edison","A2A","Hera","Poste Energia","Iren"]
events = ["new_job","child_born","moving_house","retirement","wedding","inheritance"]
outcomes = [None,None,None,"no_answer","callback","not_interested","sold"]
today = datetime.date(2026,11,18)
cust = []
for i in range(60):
    age = random.randint(19,82)
    owned = []
    if random.random()<0.55: owned.append("conto_bancoposta")
    if age<45 and random.random()<0.4: owned.append("postepay_evolution")
    if random.random()<0.3: owned.append("libretto_smart")
    if age>40 and random.random()<0.3: owned.append("buoni_fruttiferi")
    m = random.choice(mobile); e = random.choice(energy)
    if m=="PosteMobile": owned.append("postemobile")
    if e=="Poste Energia": owned.append("poste_energia")
    savings = int(random.choice([0.2,1,3,8,15,30,60,120])*1000*random.uniform(0.8,1.3))
    income = 0 if age>67 and random.random()<0.2 else int(random.uniform(900,4200))
    lc = None; lo = random.choice(outcomes)
    if lo: lc = (today-datetime.timedelta(days=random.randint(2,200))).isoformat()
    if age >= 67: emp = "retired"
    elif age < 24 and random.random() < 0.5: emp = "student"
    else: emp = random.choice(["employee", "employee", "employee", "self_employed", "unemployed"])
    if emp in ("unemployed", "student"): income = 0
    homeowner = random.random() < 0.6
    cust.append({
        "id": f"C{1000+i}",
        "name": f"{random.choice(first)} {random.choice(last)}",
        "age": age,
        "city": random.choice(cities),
        "phone": f"+39 3{random.randint(10,99)} 000 {random.randint(1000,9999)}",
        "products_owned": owned,
        "liquid_savings_eur": savings,
        "monthly_income_eur": income,
        "homeowner": homeowner,
        "has_mortgage": homeowner and 28 <= age <= 65 and random.random() < 0.45,
        "employment": emp,
        "risk_profile": random.choice(["conservative", "moderate", "dynamic", None, None]),
        "has_pension_fund": emp == "employee" and random.random() < 0.3,
        "children_under_18": random.choice([0,0,0,1,2,3]) if age<55 else 0,
        "mobile_operator": m,
        "energy_provider": e,
        "life_events": random.sample(events, k=random.choice([0,0,0,1])),
        "consent_marketing": random.random()<0.85,
        "in_registro_opposizioni": random.random()<0.1,
        "preferred_time": random.choice(["morning","afternoon","evening",None]),
        "last_contact_date": lc,
        "last_outcome": lo
    })
json.dump({"_note":"Fictional sample customers for demo purposes only. Phone numbers are fake.","customers":cust}, open(Path(__file__).parent / "sample_customers.json", "w"), indent=2, ensure_ascii=False)
