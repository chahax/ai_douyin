"""
Start the Streamlit admin web app with the project-local dependency path.

This script is intended to be launched with pythonw.exe on Windows so the
server stays in the background without holding the current terminal open.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCAL_SITE_PACKAGES = ROOT / ".local_py" / "site-packages"
LOG_DIR = ROOT / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(LOCAL_SITE_PACKAGES))
os.chdir(ROOT)

log_file = open(LOG_DIR / "streamlit_combined.log", "a", encoding="utf-8", buffering=1)
sys.stdout = log_file
sys.stderr = log_file

sys.argv = [
    "streamlit",
    "run",
    "src/web/app.py",
    "--server.address",
    "127.0.0.1",
    "--server.port",
    "8501",
    "--server.headless",
    "true",
]

from streamlit.web.cli import main


raise SystemExit(main())
