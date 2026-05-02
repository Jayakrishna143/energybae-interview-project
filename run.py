"""
run.py — starts backend and frontend together.
Press Ctrl+C to stop both.
"""

import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent

procs = []

def shutdown(sig=None, frame=None):
    print("\nStopping...")
    for p in procs:
        p.terminate()
    sys.exit(0)

signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)

print("Starting FastAPI backend on http://localhost:8000 ...")
procs.append(subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "backend:app", "--host", "0.0.0.0", "--port", "8000"],
    cwd=ROOT,
))

time.sleep(2)  # give backend a head-start

print("Starting Streamlit frontend on http://localhost:8501 ...")
procs.append(subprocess.Popen(
    [sys.executable, "-m", "streamlit", "run", str(ROOT / "app.py"),
     "--server.port", "8501", "--server.headless", "true"],
    cwd=ROOT,
))

print("\nBoth services running. Press Ctrl+C to stop.\n")

while True:
    time.sleep(3)
