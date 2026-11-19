"""
HTTP API for the Poste Italiane daily call planner.

    uvicorn poste_sales_agent.api:app --port 8001

Endpoints
  POST /plan      -> today's call list (target number of calls, operators, campaign)
  POST /outcome   -> record the result of a call (updates the customer base)
  GET  /products  -> product catalog

If GOOGLE_API_KEY is set and the request has "personalize_scripts": true,
Gemini rewrites each call script in a more natural, personal tone. The
ranking itself is always deterministic and explainable.
"""

import datetime as dt
import json
import os
from typing import Optional

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import planner

CUSTOMERS_FILE = os.environ.get("POSTE_CUSTOMERS_FILE", str(planner.DEFAULT_CUSTOMERS_FILE))
PRODUCTS_FILE = os.environ.get("POSTE_PRODUCTS_FILE", str(planner.DEFAULT_PRODUCTS_FILE))
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-1.5-pro-latest")

app = FastAPI(
    title="Poste Italiane Call Planner Agent",
    description="Suggests which customers to call each day and which Poste Italiane product to propose.",
    version="1.0.0",
)


class PlanRequest(BaseModel):
    daily_calls: int = Field(..., ge=1, le=1000, description="Number of calls to make today")
    date: Optional[dt.date] = None
    operators: Optional[list[str]] = None
    campaign_weights: dict[str, float] = Field(default_factory=dict)
    area_weights: dict[str, float] = Field(default_factory=dict)
    max_share_per_product: float = Field(0.4, gt=0, le=1)
    personalize_scripts: bool = False


class OutcomeRequest(BaseModel):
    customer_id: str
    outcome: str = Field(..., description=f"One of {sorted(planner.VALID_OUTCOMES)}")
    product_id: Optional[str] = None
    date: Optional[dt.date] = None


UI_FILE = Path(__file__).parent / "ui" / "index.html"


@app.get("/", include_in_schema=False)
def ui() -> FileResponse:
    """Operator console (single page, no build step)."""
    return FileResponse(UI_FILE)


@app.get("/products")
def products() -> dict:
    return {"products": planner.load_products(PRODUCTS_FILE)}


@app.post("/plan")
def plan(req: PlanRequest) -> dict:
    cfg = planner.PlannerConfig(campaign_weights=req.campaign_weights,
                                area_weights=req.area_weights,
                                max_share_per_product=req.max_share_per_product)
    result = planner.plan_daily_calls(
        planner.load_customers(CUSTOMERS_FILE), planner.load_products(PRODUCTS_FILE),
        req.daily_calls, today=req.date, operators=req.operators, cfg=cfg)
    if req.personalize_scripts:
        result["warnings"].extend(_personalize(result["calls"]))
    return result


@app.post("/outcome")
def outcome(req: OutcomeRequest) -> dict:
    customers = planner.load_customers(CUSTOMERS_FILE)
    try:
        c = planner.record_outcome(customers, req.customer_id, req.outcome,
                                   req.product_id, req.date)
    except KeyError:
        raise HTTPException(404, f"Unknown customer {req.customer_id}")
    except ValueError as e:
        raise HTTPException(422, str(e))
    planner.save_customers(customers, CUSTOMERS_FILE)
    return {"customer": c}


def _personalize(calls: list[dict]) -> list[str]:
    """Rewrite scripts with Gemini. Returns warnings; never fails the request."""
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return ["personalize_scripts ignorato: GOOGLE_API_KEY non impostata."]
    try:
        import google.generativeai as genai
    except ImportError:
        return ["personalize_scripts ignorato: google-generativeai non installato."]

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        GEMINI_MODEL,
        system_instruction=(
            "Sei un coach commerciale per operatori di Poste Italiane. Riscrivi lo script "
            "di chiamata in italiano, tono cortese e naturale, massimo 120 parole. "
            "Non inventare tassi, prezzi o condizioni; non promettere rendimenti. "
            "Se il prodotto richiede un consulente, l'obiettivo è solo fissare un appuntamento. "
            'Rispondi in JSON: {"script": "..."}'),
    )
    cfg = genai.GenerationConfig(response_mime_type="application/json", temperature=0.4)
    failed = 0
    for call in calls:
        prompt = json.dumps({k: call[k] for k in
                             ("customer_name", "product_name", "reasons", "script",
                              "requires_qualified_advisor")}, ensure_ascii=False)
        try:
            call["script"] = json.loads(model.generate_content(prompt, generation_config=cfg).text)["script"]
        except Exception:
            failed += 1
    return [f"{failed} script non personalizzati (errore LLM)."] if failed else []


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)
