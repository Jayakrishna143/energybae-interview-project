"""
run.py — Master Launcher
--------------------------
Starts all three services simultaneously and shuts them all down on Ctrl+C.

Ports:
  8501  →  Streamlit  (app.py)
  8000  →  FastAPI     (backend.py)
  8001  →  MCP Server  (mcp_server.py)
"""

import subprocess
import sys
import time


PROCESSES = [
    {
        "name":    "MCP Server",
        "cmd":     [sys.executable, "-m", "uvicorn", "mcp_server:app", "--host", "0.0.0.0", "--port", "8001"],
        "color":   "\033[93m",   # yellow
    },
    {
        "name":    "FastAPI Backend",
        "cmd":     [sys.executable, "-m", "uvicorn", "backend:app", "--host", "0.0.0.0", "--port", "8000"],
        "color":   "\033[94m",   # blue
    },
    {
        "name":    "Streamlit",
        "cmd":     [sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", "8501"],
        "color":   "\033[92m",   # green
    },
]

RESET = "\033[0m"


def log(name, color, msg):
    print(f"{color}[{name}]{RESET}  {msg}", flush=True)


def main():
    procs = []

    # ── Launch each service ──────────────────────────────────────────────────
    for svc in PROCESSES:
        p = subprocess.Popen(
            svc["cmd"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,      # line-buffered
        )
        log(svc["name"], svc["color"], f"started (pid {p.pid})  →  {' '.join(svc['cmd'])}")
        svc["proc"] = p
        procs.append((svc, p))

    print()
    print("  ☀️  Solar Load Calculator is running!")
    print("      Streamlit   →  http://localhost:8501")
    print("      Backend API →  http://localhost:8000/docs")
    print("      MCP Server  →  http://localhost:8001/docs")
    print()
    print("  Press Ctrl+C to stop all services.\n")

    # ── Give services a moment to boot, then check health ────────────────────
    time.sleep(3)
    for svc, p in procs:
        if p.poll() is not None:
            log(svc["name"], svc["color"],
                f"⚠️  exited early with code {p.returncode}. Check for errors above.")

    # ── Stream logs from all processes ────────────────────────────────────────
    try:
        import threading

        def stream(svc, proc):
            for line in proc.stdout:
                log(svc["name"], svc["color"], line.rstrip())

        threads = []
        for svc, p in procs:
            t = threading.Thread(target=stream, args=(svc, p), daemon=True)
            t.start()
            threads.append(t)

        # Block main thread — wait for Ctrl+C
        for t in threads:
            t.join()

    except KeyboardInterrupt:
        print("\n\n  🛑  Shutting down all services…")
        for svc, p in procs:
            if p.poll() is None:
                p.terminate()
                log(svc["name"], svc["color"], "terminated.")
        # Give processes a moment to exit gracefully
        time.sleep(1)
        for svc, p in procs:
            if p.poll() is None:
                p.kill()   # force-kill if still alive
        print("  ✅  All services stopped. Ports are free.\n")


if __name__ == "__main__":
    main()
