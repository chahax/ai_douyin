"""Offline acceptance through the production runner; never invokes live services."""
from pathlib import Path
import os
import sys
import socket
import json

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
group = sys.argv[1]
os.environ["DATABASE_URL"] = "sqlite:///" + str(OUT / (group + "_runtime.sqlite3")).replace(chr(92), "/")
os.environ["LLM_PROVIDER"] = "mock"
os.environ["PYTHONIOENCODING"] = "utf-8"

def blocked(*args, **kwargs):
    raise RuntimeError("P1 acceptance prohibits network connections")

socket.socket.connect = blocked
socket.socket.connect_ex = blocked
prior = OUT.parent / "v20_confirmation"
selections = {
    "core": ["tests/" + name + ".py" for name in json.loads((prior / "core_selection.json").read_text())],
    "governance": ["tests/" + name + ".py" for name in json.loads((prior / "governance_selection.json").read_text())],
    "boundary": [str(prior / "test_recovery_boundaries.py"), str(prior / "test_extended_recovery.py")],
    "ui_replay": ["tests/test_creative_workflow_ui.py", "tests/test_creative_real_receipt_replay.py", "tests/test_creative_full_script_revision.py"],
}
selections["p1"] = selections["core"] + selections["governance"] + selections["boundary"] + [
    "tests/test_creative_workflow_ui.py", "tests/test_creative_full_script_revision.py"]
selected = selections[group]
(OUT / (group + "_selection.json")).write_text(json.dumps(selected, indent=2), encoding="utf-8")

class Tee:
    def __init__(self, stream, log):
        self.stream = stream
        self.log = log
    def write(self, value):
        self.log.write(value)
        self.log.flush()
        return self.stream.write(value)
    def flush(self):
        self.log.flush()
        self.stream.flush()
    def isatty(self):
        return False

import pytest
with (OUT / (group + "_tests.log")).open("w", encoding="utf-8") as log:
    sys.stdout = Tee(sys.stdout, log)
    sys.stderr = Tee(sys.stderr, log)
    code = pytest.main(selected + ["-q", "--tb=short", "-p", "no:cacheprovider",
                                  "--basetemp=" + str(OUT / (group + "_tmp")),
                                  "--junitxml=" + str(OUT / (group + "_tests.xml"))])
    print("ACCEPTANCE_EXIT_CODE=" + str(code))
    sys.stdout = sys.stdout.stream
    sys.stderr = sys.stderr.stream
raise SystemExit(code)
