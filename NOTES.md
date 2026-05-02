# Project Design Notes

## Overview
The original approach was to receive an image or PDF of a bill from the user, run it through an OCR model to extract raw text, and then feed that text to a language model (LLM) for further processing. However, advertisements and other noise in the input images caused the OCR Model to struggle with producing clean data for the Excel report.

## Revised Strategy
1. **Primary Path – Vision‑enabled LLM**
   - The vision‑capable Gemini‑2.5‑Flash model processes the image directly, eliminating the need for a separate OCR step.
   - If the initial OCR attempt fails, the workflow falls back to the vision model, which can handle the image end‑to‑end.

2. **Simplified Pipeline**
   - The OCR stage was removed entirely because the vision model proved reliable and simpler.
   - For users who only require an Excel output, the data can be generated using `pandas` or `openpyxl` without involving an external MCP (Microsoft Excel) server.
   - This Excel generation is implemented as a dedicated node in the LangGraph workflow, acting as a lightweight tool directly connected to the model.

3. **System Architecture**
   - **Frontend**: Streamlit application for user interaction (file upload, processing button, and Excel download).
   - **Backend**: FastAPI service handling asynchronous processing and exposing endpoints for bill processing and file download.
   - **Model**: Google Gemini‑2.5‑Flash, which supports vision inputs, is used for both extraction and any additional reasoning.
   - The backend constructs a LangGraph consisting of:
     - An **extract** node (vision model) that returns structured bill data.
     - An **excel** node that writes the structured data to an Excel file.
   - The graph is compiled and invoked from the FastAPI endpoint.

## Key Benefits
- **Reduced Complexity** – Eliminating the OCR step lowers the chance of data corruption and simplifies maintenance.
- **Performance** – Direct vision processing by Gemini reduces latency and avoids unnecessary intermediate transformations.
- **Flexibility** – The Excel generation node can be swapped for other output formats if needed.
- **User Experience** – Streamlit provides an intuitive UI, while FastAPI ensures fast, asynchronous handling of requests.

---

*These notes capture the evolution of the design decisions and the final architecture of the Solar Load Calculator project.*
