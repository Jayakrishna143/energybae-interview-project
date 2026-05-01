# ☀️ Automated Solar Load Calculator Pipeline

Extracts data from MSEDCL (Mahavitaran) electricity bills and auto-populates
the `Copy of Pranay HOME E-Bill Analysis.xlsx` tracker.

## Architecture

```
[Streamlit UI]  →  POST image/b64  →  [FastAPI + LangGraph]
                                              │
                              ┌───────────────┘
                              ↓
                    Node 1: Groq Vision LLM
                    (llama-3.2-11b-vision-preview)
                              │
                    Node 2: Pydantic Validation
                              │
                     ┌────────┴────────┐
                   PASS             FAIL (retry ≤2)
                     │                 └─→ Node 1 (with error context)
                     ↓
                    Node 3: MCP Server  →  openpyxl Excel update
```

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt

# Also install poppler for PDF support:
# macOS:  brew install poppler
# Ubuntu: sudo apt install poppler-utils
```

### 2. Set your Groq API key
```bash
cp .env.example .env
# Edit .env and paste your key from https://console.groq.com
```

### 3. Place the Excel file in this folder
```
Copy of Pranay HOME E-Bill Analysis.xlsx   ← must be in same directory
```

### 4. Run everything
```bash
# Load env and launch all services
source .env && python run.py
# Windows: set GROQ_API_KEY=gsk_... && python run.py
```

### 5. Open the UI
Visit **http://localhost:8501** in your browser.

---

## File Structure

```
solar_pipeline/
├── app.py          ← Streamlit frontend
├── backend.py      ← FastAPI + LangGraph orchestrator
├── mcp_server.py   ← Excel execution server (port 8001)
├── run.py          ← Master launcher (starts all 3)
├── requirements.txt
├── .env.example
└── Copy of Pranay HOME E-Bill Analysis.xlsx   ← your Excel file
```

## Excel Column Mapping (do not modify)

| Column | Consumer 1 (Madhusham) | Consumer 2 (Ranjana) |
|--------|------------------------|----------------------|
| Month  | C                      | G                    |
| Units  | D                      | H                    |
| Bill ₹ | E                      | I                    |
| Unit Cost | F *(formula)*       | J *(formula)*        |

The system **only writes** to C/D/E (consumer 1) or G/H/I (consumer 2).
Formula cells F and J are **never overwritten** — openpyxl preserves them.

## Supported Bills

- ✅ MSEDCL / Mahavitaran residential bills (Marathi + English)
- ✅ JPG, PNG, PDF formats
- ✅ Both consumer numbers: `439320095567` and `439322232375`
