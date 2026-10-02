from pathlib import Path
import runpy
import json

OUT = Path(__file__).resolve().parent

def test_must_fix_during_model_call_survives_runner_save():
    # Exercise the real command service and runner during a fake provider call.
    # The command uses both version hashes, as the Streamlit page does.
    runpy.run_path(str(OUT / 'inventory_and_probe.py'), run_name='__review_probe__')
    proof = json.loads((OUT / 'inflight_feedback_probe.json').read_text(encoding='utf-8'))
    assert proof['expected_version_hashes_supplied']
    assert proof['feedback_present_during_call']
    assert proof['feedback_receipt_retained']
    assert proof['feedback_present_after_call'], 'runner save discarded accepted user must_fix feedback'
    assert proof['pending_feedback_count'] == 1
    assert proof['final_feedback_status'] == 'revision_required'
