"""Local armed metadata upgrade; no business submission or browser operation."""
import json
import os
from pathlib import Path


def install_if_armed():
    root=Path(__file__).resolve().parents[2]
    here=root/'data/development_checkpoints/manual_display_close_race_20261103'
    arm=here/'CLAIM_GUARD_ARM.json'
    if not arm.exists():return
    config=json.loads(arm.read_text(encoding='utf8'))
    if os.getpid()!=config['backend_pid']:return
    import psutil
    if psutil.Process().create_time()!=config['backend_create_time']:return
    from importlib import reload
    from src.operations_accounts import paused_claim_deployment
    reload(paused_claim_deployment).install_if_armed()
    from .tracked_refresh_gate import install_live_gate
    install_live_gate()
    (here/'TRACKED_GATE_INSTALLED.json').write_text(json.dumps({
        'backend_pid':os.getpid(),'browser_operations':False,'account_resume':False,
        'source':'armed_scheduler_metadata_upgrade'}),encoding='utf8')
