"""
app.py
- Upload multiple bill images/PDFs
- Click one button to process
- Download the Excel report
"""

import base64
import io
import os
from pathlib import Path

import requests
import streamlit as st
from dotenv import load_dotenv
from PIL import Image

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=True)
BACKEND = os.getenv("BACKEND_URL", "http://localhost:8000")

st.title("Solar Load Calculator")
st.write("Upload MSEDCL bill images → get a solar sizing Excel report.")

files = st.file_uploader(
    "Upload bill images or PDFs",
    type=["jpg", "jpeg", "png", "pdf"],
    accept_multiple_files=True,
)

if st.button("Process Bills", disabled=not files):

    # Convert all uploads to base64 strings
    images = []
    for f in files:
        raw = f.read()
        if f.type == "application/pdf":
            try:
                from pdf2image import convert_from_bytes
                for page in convert_from_bytes(raw, dpi=200):
                    buf = io.BytesIO()
                    page.save(buf, format="JPEG")
                    images.append(base64.b64encode(buf.getvalue()).decode())
            except Exception as e:
                st.error(f"PDF conversion failed for {f.name}: {e}")
        else:
            images.append(base64.b64encode(raw).decode())

    if not images:
        st.error("No images to process.")
        st.stop()

    with st.spinner(f"Processing {len(images)} bill(s) with Gemini..."):
        try:
            resp = requests.post(
                f"{BACKEND}/process-bills",
                json={"images": images},
                timeout=300,
            )
            resp.raise_for_status()
        except requests.exceptions.ConnectionError:
            st.error("Cannot reach backend. Is run.py running?")
            st.stop()
        except requests.exceptions.HTTPError as e:
            st.error(f"Backend error: {e.response.text}")
            st.stop()

    data = resp.json()

    # Show any extraction warnings
    for err in data.get("errors", []):
        st.warning(err)

    st.success(f"Done! Processed {len(data['bills'])} bill(s).")

    # Fetch and offer the Excel file for download
    excel_resp = requests.get(f"{BACKEND}/download", timeout=30)
    st.download_button(
        label="Download Solar_Report.xlsx",
        data=excel_resp.content,
        file_name="Solar_Report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
