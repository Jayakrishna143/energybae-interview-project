
import base64
import io
import json
import math
import os
from pathlib import Path
from typing import Dict, List, TypedDict

import google.generativeai as genai
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from langgraph.graph import END, StateGraph
from openpyxl import Workbook
from PIL import Image
from pydantic import BaseModel, Field

# ── Config ────────────────────────────────────────────────────────────────────
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
EXCEL_PATH = Path(__file__).resolve().parent / "Solar_Report.xlsx"
PANEL_KW = 0.6  # each panel is 600 W = 0.6 kW

genai.configure(api_key=GEMINI_API_KEY)

# ── Pydantic models ───────────────────────────────────────────────────────────

class BillData(BaseModel):
    customer_name: str = ""
    consumer_number: str = ""
    sanctioned_load_kw: float = 0.0
    tariff_category: str = ""
    units_consumed: int = 0
    bill_amount: float = 0.0
    fixed_charges: float = 0.0
    bill_month: str = ""
    historical_consumption: Dict[str, int] = Field(default_factory=dict)

class ProcessRequest(BaseModel):
    images: List[str]  # list of base64-encoded images

class ProcessResponse(BaseModel):
    bills: List[BillData]
    errors: List[str] = []

# ── LangGraph state ───────────────────────────────────────────────────────────

class State(TypedDict):
    base64_images: List[str]
    extracted_bills: List[BillData]
    errors: List[str]
    excel_path: str

# ── Node 1: Extract bills with Gemini Vision ──────────────────────────────────

PROMPT = """Extract fields from this MSEDCL electricity bill image.
Return ONLY valid JSON with exactly these keys:
{
  "customer_name": "",
  "consumer_number": "",
  "sanctioned_load_kw": 0.0,
  "tariff_category": "",
  "units_consumed": 0,
  "bill_amount": 0.0,
  "fixed_charges": 0.0,
  "bill_month": "YYYY-MM",
  "historical_consumption": {"YYYY-MM": units_integer}
}
Rules: no markdown fences, no explanation, just the JSON object.
If a value is missing use its default (0, "", or {})."""

def extract_node(state: State) -> State:
    model = genai.GenerativeModel("gemini-2.5-flash")
    bills = []
    errors = []

    for i, b64 in enumerate(state["base64_images"]):
        try:
            img = Image.open(io.BytesIO(base64.b64decode(b64)))
            response = model.generate_content([PROMPT, img])
            text = response.text.strip()

            # Strip markdown code fences if model adds them
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            bills.append(BillData(**json.loads(text)))
            print(f"[Extract] Bill {i+1} OK")
        except Exception as e:
            msg = f"Bill {i+1} failed: {e}"
            errors.append(msg)
            print(f"[Extract] {msg}")
            bills.append(BillData(consumer_number=f"ERROR_{i+1}"))

    return {**state, "extracted_bills": bills, "errors": errors}

# ── Node 2: Write Excel ───────────────────────────────────────────────────────

def excel_node(state: State) -> State:
    bills = state["extracted_bills"]
    wb = Workbook()
    ws = wb.active
    ws.title = "Bill Analysis"

    # Single sheet layout (mirrors reference format):
    #
    #   METER 1
    #   Customer Name     : ...
    #   Consumer No       : ...
    #   Tariff Category   : ...
    #   Sanctioned Load   : ... kW
    #   <blank>
    #   Month | Units Consumed | Bill Amount (Rs.)
    #   2024-01 | 320 | ...
    #   ...
    #   <blank>
    #   Avg Monthly Units        : X
    #   Required Solar kW        : X
    #   No. of Panels (600W)     : X
    #   <blank><blank>
    #   METER 2  ... (same block repeated)
    #   ...
    #   SOLAR SIZING SUMMARY
    #   Meter | Consumer No | Avg Units/Month | Required kW | Panels
    #   Meter 1 | ...
    #   Meter 2 | ...
    #   <blank>
    #   TOTAL HOUSEHOLD COMBINED | | | total_kw | total_panels

    sizing_results = []  # (meter_label, consumer_no, avg, kw, panels)

    for i, bill in enumerate(bills, start=1):

        # ── Meter header block ────────────────────────────────────────────────
        ws.append([f"METER {i}"])
        ws.append(["Customer Name",         bill.customer_name])
        ws.append(["Consumer No",           bill.consumer_number])
        ws.append(["Tariff Category",       bill.tariff_category])
        ws.append(["Sanctioned Load (kW)",  bill.sanctioned_load_kw])
        ws.append([])

        # ── Monthly consumption table ─────────────────────────────────────────
        ws.append(["Month", "Units Consumed", "Bill Amount (Rs.)"])

        months = dict(bill.historical_consumption)
        if bill.bill_month:
            months[bill.bill_month] = bill.units_consumed

        for month, units in sorted(months.items()):
            amount = bill.bill_amount if month == bill.bill_month else ""
            ws.append([month, units, amount])

        ws.append([])

        # ── Per-meter solar sizing ────────────────────────────────────────────
        all_units = list(bill.historical_consumption.values())
        if bill.units_consumed:
            all_units.append(bill.units_consumed)

        if all_units:
            avg    = round(sum(all_units) / len(all_units), 1)
            kw     = round((avg * 12 * 1.1) / 1400, 2)   # Load formula
            panels = math.ceil(kw / PANEL_KW)              # ceil(kW / 0.6)
        else:
            avg, kw, panels = 0, 0, 0

        ws.append(["Avg Monthly Units",           avg])
        ws.append(["Required Solar Capacity (kW)", kw])
        ws.append(["No. of Panels (600W each)",   panels])
        ws.append([])
        ws.append([])   # extra spacer before next meter block

        sizing_results.append((f"Meter {i}", bill.consumer_number, avg, kw, panels))

    # ── Combined Solar Sizing Summary ─────────────────────────────────────────
    ws.append(["SOLAR SIZING SUMMARY"])
    ws.append(["Meter", "Consumer No", "Avg Units/Month", "Required kW", "Panels (600W)"])

    total_kw     = 0.0
    total_panels = 0

    for meter_label, consumer_no, avg, kw, panels in sizing_results:
        ws.append([meter_label, consumer_no, avg, kw, panels])
        total_kw     += kw
        total_panels += panels

    ws.append([])
    ws.append(["TOTAL HOUSEHOLD COMBINED", "", "", round(total_kw, 2), total_panels])

    wb.save(EXCEL_PATH)
    print(f"[Excel] Saved → {EXCEL_PATH}")
    return {**state, "excel_path": str(EXCEL_PATH)}

# ── Build LangGraph ───────────────────────────────────────────────────────────

builder = StateGraph(State)
builder.add_node("extract", extract_node)
builder.add_node("excel", excel_node)
builder.set_entry_point("extract")
builder.add_edge("extract", "excel")
builder.add_edge("excel", END)
graph = builder.compile()

# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(title="Solar Load Calculator")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/process-bills", response_model=ProcessResponse)
def process_bills(req: ProcessRequest):
    if not GEMINI_API_KEY:
        raise HTTPException(500, "GEMINI_API_KEY not set in .env")
    if not req.images:
        raise HTTPException(400, "No images provided")

    result = graph.invoke({
        "base64_images": req.images,
        "extracted_bills": [],
        "errors": [],
        "excel_path": "",
    })
    return ProcessResponse(bills=result["extracted_bills"], errors=result["errors"])

@app.get("/download")
def download():
    if not EXCEL_PATH.exists():
        raise HTTPException(404, "Run /process-bills first")
    return FileResponse(
        EXCEL_PATH,
        filename="Solar_Report.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

if __name__ == "__main__":
    uvicorn.run("backend:app", host="0.0.0.0", port=8000, reload=False)
