"""
backend.py — FastAPI + LangGraph Orchestrator
--------------------------------------------------
Flow:
  [extract] → [validate] → (pass) → [update_excel] → END
                         ↑             ↓
                  (fail, retry<2)   SUCCESS
                         ↓
                    [increment_retry]
                         ↓
                    (retry) → [extract]  (with error context)
                    (fail after 2)  → [fail_node] → END
"""

import os
import json
from typing import Optional

import httpx
from fastapi import FastAPI
from groq import Groq
from langgraph.graph import END, StateGraph
from pydantic import BaseModel

# ── Clients ───────────────────────────────────────────────────────────────────
app         = FastAPI(title="Solar Bill Processor")
groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])

MCP_SERVER_URL = "http://localhost:8001"   # where mcp_server.py listens
MAX_RETRIES    = 2


# ═══════════════════════════════════════════════════════════════════════════════
# 1.  DATA SCHEMA  (strict Pydantic — used for validation in the graph)
# ═══════════════════════════════════════════════════════════════════════════════
class BillData(BaseModel):
    customer_name:      str
    consumer_number:    str    # 12-digit MSEDCL number
    sanctioned_load_kw: float  # e.g. 3.30
    tariff_category:    str    # e.g. "90/LT I Res 1-Phase"
    units_consumed:     int    # Total units (एकूण वापर)
    bill_amount:        float  # Final bill amount (देयक रक्कम रु)
    bill_month:         str    # "YYYY-MM"  e.g. "2026-01"


# ═══════════════════════════════════════════════════════════════════════════════
# 2.  LANGGRAPH STATE  (a plain TypedDict — the "memory" flowing between nodes)
# ═══════════════════════════════════════════════════════════════════════════════
from typing import TypedDict

class GraphState(TypedDict):
    image_b64:        str
    media_type:       str
    extracted_data:   Optional[dict]   # raw dict from LLM
    validation_error: Optional[str]    # set when validation fails
    retries:          int              # how many times we've retried
    final_result:     Optional[dict]   # what gets returned to the API


# ═══════════════════════════════════════════════════════════════════════════════
# 3.  NODE 1 — Vision Extraction
#     Sends the image to Groq llama-3.2-11b-vision-preview.
#     If a previous validation_error exists, it's injected into the prompt
#     so the model can self-correct on the retry.
# ═══════════════════════════════════════════════════════════════════════════════
def extract_from_bill(state: GraphState) -> GraphState:
    error_hint = ""
    if state.get("validation_error"):
        error_hint = (
            f"\n\n⚠️ YOUR PREVIOUS RESPONSE WAS REJECTED because: "
            f"{state['validation_error']}\n"
            "Please read the bill more carefully and fix the value(s) above."
        )

    prompt = f"""You are an expert at reading MSEDCL (Mahavitaran) electricity bills from Maharashtra, India.
These bills mix Marathi and English. Extract the following fields precisely:

• customer_name       — Account holder's name (English, e.g. "SHRI MADHUSHAM ROOPCHAND KHOBRAGADE")
• consumer_number     — The 12-digit number next to "ग्राहक क्रमांक" or "Consumer No"
• sanctioned_load_kw  — Number after "मंजूर भार" / "Sanctioned Load" (float, e.g. 3.30)
• tariff_category     — Tariff code next to "दर संकेत" / "Rate Code" (e.g. "90/LT I Res 1-Phase")
• units_consumed      — Integer from "एकूण वापर" / "Total Consumption" column
• bill_amount         — Final amount from "देयक रक्कम रु" / "Bill Amount" box (float)
• bill_month          — Bill month as "YYYY-MM" (e.g. "2026-01" for January 2026).
                        Look at "चालू रिडिंग दिनांक" (Current Reading Date) or the bill header month.

Rules:
- Respond with ONLY a valid JSON object — no explanation, no markdown.
- consumer_number must be digits only (no spaces).
- units_consumed must be a positive integer.
- bill_amount must be the total payable amount (देयक रक्कम रु), a positive float.{error_hint}

JSON format:
{{"customer_name":"...","consumer_number":"...","sanctioned_load_kw":0.0,"tariff_category":"...","units_consumed":0,"bill_amount":0.0,"bill_month":"YYYY-MM"}}"""

    response = groq_client.chat.completions.create(
        model="llama-3.2-11b-vision-preview",
        max_tokens=512,
        temperature=0.1,   # low temp = deterministic / less hallucination
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{state['media_type']};base64,{state['image_b64']}"},
                },
                {"type": "text", "text": prompt},
            ],
        }],
    )

    raw = response.choices[0].message.content.strip()
    # Strip accidental markdown fences (```json … ```)
    raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        data = json.loads(raw)
        return {**state, "extracted_data": data, "validation_error": None}
    except json.JSONDecodeError as exc:
        return {**state, "extracted_data": None,
                "validation_error": f"LLM returned invalid JSON: {exc}. Raw output: {raw[:300]}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 4.  NODE 2 — Validation
#     Uses the Pydantic model to validate types and business rules.
#     Sets validation_error if anything is wrong.
# ═══════════════════════════════════════════════════════════════════════════════
def validate_data(state: GraphState) -> GraphState:
    if not state.get("extracted_data"):
        # Carry the existing validation_error forward
        return state

    try:
        bill = BillData(**state["extracted_data"])

        # Business-rule checks
        if bill.units_consumed <= 0:
            raise ValueError(f"units_consumed must be > 0, got {bill.units_consumed}")
        if bill.sanctioned_load_kw <= 0:
            raise ValueError(f"sanctioned_load_kw must be > 0, got {bill.sanctioned_load_kw}")
        if bill.bill_amount <= 0:
            raise ValueError(f"bill_amount must be > 0, got {bill.bill_amount}")
        if len(bill.consumer_number.strip()) < 10:
            raise ValueError(f"consumer_number looks incomplete: '{bill.consumer_number}'")

        # Validation passed — store clean validated dict
        return {**state, "extracted_data": bill.model_dump(), "validation_error": None}

    except Exception as exc:
        return {**state, "validation_error": str(exc)}


# ═══════════════════════════════════════════════════════════════════════════════
# 5.  CONDITIONAL EDGE — Decide what to do after validation
# ═══════════════════════════════════════════════════════════════════════════════
def route_after_validation(state: GraphState) -> str:
    if state.get("validation_error"):
        if state["retries"] < MAX_RETRIES:
            return "retry"
        else:
            return "fail"      # exhausted retries
    return "update"            # all good — proceed to Excel update


# ═══════════════════════════════════════════════════════════════════════════════
# 6.  NODE — Increment retry counter (sits between validate → extract on retry)
# ═══════════════════════════════════════════════════════════════════════════════
def increment_retry(state: GraphState) -> GraphState:
    return {**state, "retries": state["retries"] + 1}


# ═══════════════════════════════════════════════════════════════════════════════
# 7.  NODE 3 — Call MCP Server to update the Excel file
#     Uses a synchronous httpx call so LangGraph's sync invoke() works fine.
# ═══════════════════════════════════════════════════════════════════════════════
def update_excel_via_mcp(state: GraphState) -> GraphState:
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                f"{MCP_SERVER_URL}/update-excel",
                json=state["extracted_data"],
            )
        result = resp.json()
    except Exception as exc:
        result = {"success": False, "error": str(exc)}

    return {**state, "final_result": result}


# ═══════════════════════════════════════════════════════════════════════════════
# 8.  NODE — Fail terminal: max retries reached
# ═══════════════════════════════════════════════════════════════════════════════
def fail_node(state: GraphState) -> GraphState:
    return {**state, "final_result": {
        "success": False,
        "error": f"Extraction failed after {MAX_RETRIES} retries. "
                 f"Last error: {state.get('validation_error')}",
    }}


# ═══════════════════════════════════════════════════════════════════════════════
# 9.  BUILD THE LANGGRAPH
# ═══════════════════════════════════════════════════════════════════════════════
def build_pipeline():
    g = StateGraph(GraphState)

    g.add_node("extract",        extract_from_bill)
    g.add_node("validate",       validate_data)
    g.add_node("increment_retry",increment_retry)
    g.add_node("update_excel",   update_excel_via_mcp)
    g.add_node("fail",           fail_node)

    g.set_entry_point("extract")
    g.add_edge("extract", "validate")

    # Conditional routing after validation
    g.add_conditional_edges(
        "validate",
        route_after_validation,
        {
            "retry":  "increment_retry",   # → bump counter → re-extract
            "update": "update_excel",       # → write to Excel
            "fail":   "fail",               # → terminal failure
        },
    )
    g.add_edge("increment_retry", "extract")   # loop back with error context
    g.add_edge("update_excel",    END)
    g.add_edge("fail",            END)

    return g.compile()


pipeline = build_pipeline()


# ═══════════════════════════════════════════════════════════════════════════════
# 10.  FastAPI endpoint
# ═══════════════════════════════════════════════════════════════════════════════
class BillRequest(BaseModel):
    image_b64:  str
    media_type: str


@app.post("/process-bill")
def process_bill(req: BillRequest):
    initial_state: GraphState = {
        "image_b64":        req.image_b64,
        "media_type":       req.media_type,
        "extracted_data":   None,
        "validation_error": None,
        "retries":          0,
        "final_result":     None,
    }

    result = pipeline.invoke(initial_state)

    if result["final_result"] and result["final_result"].get("success"):
        return {"success": True, "extracted_data": result["extracted_data"]}

    error = (
        result.get("final_result", {}).get("error")
        or result.get("validation_error")
        or "Unknown error"
    )
    return {"success": False, "error": error}


@app.get("/health")
def health():
    return {"status": "ok"}
