"""
app.py — Streamlit Frontend
Uploads MSEDCL bills, sends to FastAPI backend, shows results + download link.
"""

import io
import base64
from pathlib import Path

import requests
import streamlit as st

# ── Config ────────────────────────────────────────────────────────────────────
BACKEND_URL = "http://localhost:8000"
EXCEL_FILE  = "Copy of Pranay HOME E-Bill Analysis.xlsx"

st.set_page_config(page_title="Solar Load Calculator ☀️", page_icon="☀️", layout="centered")

st.title("☀️ MSEDCL Bill → Solar Load Calculator")
st.caption(
    "Upload a Maharashtra electricity bill (JPG / PNG / PDF). "
    "The AI will extract the data and update your Excel tracker automatically."
)
st.divider()

# ── File Upload ───────────────────────────────────────────────────────────────
uploaded = st.file_uploader(
    "Drop your MSEDCL Bill here",
    type=["jpg", "jpeg", "png", "pdf"],
    help="Supports JPG, PNG, or PDF bills from MSEDCL / Mahavitaran.",
)

if uploaded is None:
    st.info("⬆️  Upload a bill to get started.")
    st.stop()

# ── Convert to base64 image ───────────────────────────────────────────────────
if uploaded.type == "application/pdf":
    st.info("📄 PDF detected — converting first page to image…")
    try:
        from pdf2image import convert_from_bytes
        pages = convert_from_bytes(uploaded.read(), dpi=200)
        buf = io.BytesIO()
        pages[0].save(buf, format="JPEG")
        image_bytes = buf.getvalue()
        media_type  = "image/jpeg"
        st.image(pages[0], caption="Bill Preview (Page 1)", use_column_width=True)
    except Exception as e:
        st.error(f"PDF conversion failed: {e}\nMake sure `poppler` is installed.")
        st.stop()
else:
    image_bytes = uploaded.read()
    media_type  = uploaded.type
    st.image(image_bytes, caption="Bill Preview", use_column_width=True)

image_b64 = base64.b64encode(image_bytes).decode()

# ── Process Button ────────────────────────────────────────────────────────────
st.divider()
if not st.button("🔍  Extract Data & Update Excel", type="primary", use_container_width=True):
    st.stop()

with st.spinner("🤖 AI is reading the bill… this takes ~10 seconds"):
    try:
        resp = requests.post(
            f"{BACKEND_URL}/process-bill",
            json={"image_b64": image_b64, "media_type": media_type},
            timeout=90,
        )
        result = resp.json()
    except requests.exceptions.ConnectionError:
        st.error("❌ Cannot reach the backend. Is `run.py` running?")
        st.stop()
    except Exception as e:
        st.error(f"❌ Request failed: {e}")
        st.stop()

# ── Show Results ──────────────────────────────────────────────────────────────
if not result.get("success"):
    st.error(f"❌ Processing failed: {result.get('error', 'Unknown error')}")
    st.stop()

st.success("✅ Bill processed and Excel updated!")
data = result["extracted_data"]

col1, col2, col3 = st.columns(3)
col1.metric("Consumer",        data["customer_name"])
col2.metric("Consumer No.",    data["consumer_number"])
col3.metric("Tariff",          data["tariff_category"])

col4, col5, col6 = st.columns(3)
col4.metric("Units Consumed",  f"{data['units_consumed']} kWh")
col5.metric("Sanctioned Load", f"{data['sanctioned_load_kw']} kW")
col6.metric("Bill Amount",     f"₹ {data['bill_amount']:,.2f}")

# ── Download updated Excel ────────────────────────────────────────────────────
st.divider()
excel_path = Path(EXCEL_FILE)
if excel_path.exists():
    with open(excel_path, "rb") as fh:
        st.download_button(
            label="📥  Download Updated Excel",
            data=fh,
            file_name=EXCEL_FILE,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
else:
    st.warning("Excel file not found in the working directory. Place it next to the scripts.")
