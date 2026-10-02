"""
Start the Streamlit admin web app with the project-local dependency path.

This script is intended to be launched with pythonw.exe on Windows so the
server stays in the background without holding the current terminal open.
"""

from __future__ import annotations

import os
import atexit
import socket
import sys
import threading
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCAL_SITE_PACKAGES = ROOT / ".local_py" / "site-packages"
LOG_DIR = ROOT / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
PID_PATH = LOG_DIR / "streamlit_web.pid"
HOST = os.getenv("STREAMLIT_HOST", "127.0.0.1").strip() or "127.0.0.1"
PORT = int(os.getenv("STREAMLIT_PORT", "8501"))

sys.path.insert(0, str(LOCAL_SITE_PACKAGES))
sys.path.insert(1, str(ROOT))
os.chdir(ROOT)

log_file = open(LOG_DIR / "streamlit_combined.log", "a", encoding="utf-8", buffering=1)
sys.stdout = log_file
sys.stderr = log_file


def _port_is_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def _remove_own_pid_file() -> None:
    try:
        if PID_PATH.exists() and PID_PATH.read_text(encoding="ascii").strip() == str(os.getpid()):
            PID_PATH.unlink()
    except OSError:
        pass


if _port_is_open(HOST, PORT):
    print(f"[{datetime.now().isoformat()}] Streamlit already listens on {HOST}:{PORT}; skip duplicate startup.")
    raise SystemExit(0)

PID_PATH.write_text(str(os.getpid()), encoding="ascii")
atexit.register(_remove_own_pid_file)
print(f"[{datetime.now().isoformat()}] Starting Streamlit PID={os.getpid()} on {HOST}:{PORT}")

def _start_background_services() -> None:
    """Initialize background services without delaying the web listener."""
    try:
        from src.scheduler.runner import start_scheduler

        start_scheduler()
    except Exception as exc:
        print(f"[{datetime.now().isoformat()}] Scheduler startup skipped: {exc}")


# Keep scheduler imports out of Streamlit reruns and let the health endpoint
# become available while the heavier background stack initializes.
threading.Thread(
    target=_start_background_services,
    name="streamlit-background-services",
    daemon=True,
).start()

sys.argv = [
    "streamlit",
    "run",
    "src/web/app.py",
    "--server.address",
    HOST,
    "--server.port",
    str(PORT),
    "--server.headless",
    "true",
]

from streamlit.web.cli import main


raise SystemExit(main())
