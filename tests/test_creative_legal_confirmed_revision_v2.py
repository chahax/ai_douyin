import json
from copy import deepcopy
from pathlib import Path
import pytest
from scripts.run_confirmed_legal_script_trial_v12 import verify_files
from scripts import creative_resume_dispatch_v3 as control
from src.content_factory.creative_legal_confirmed_revision_v2 import build_wire
from test_creative_confirmed_case_graph_context_v1 import inputs

def test_complete_raw_sources_remain_exact_and_calibration_not_pass_decision():
    (p,f,g,s,d,c),now=inputs();root=Path(__file__).resolve().parents[1]/'data/production_revisions/legal_trend_text_trial_20261008/round_08'
    script=json.loads((root/'DRAFT_r6.json').read_text(encoding='utf-8'));review=json.loads((root/'REVIEW_r6.json').read_text(encoding='utf-8'))
    revision={'previous_complete_script':script,'review':review};before=deepcopy(revision)
    w=build_wire(p,f,g,s,'draft',now=now,direction=d,confirmation=c,revision=revision)
    x=json.loads(w['messages'][1]['content']);assert revision==before and x['complete_content_revision']==before
    assert x['revision_contract']['required_issue_ids']==[i['id'] for i in review['full_text_review']['issues']]
    assert x['reference_fulltext']==p['inputs']['reference_fulltext'] and w['model']=='MiniMax-M3'
    w=build_wire(p,f,g,s,'review',now=now,direction=d,confirmation=c,script=script)
    x=json.loads(w['messages'][1]['content']);assert x['script']==script and x['source_evidence_directory'] and x['review_stage_boundaries']

def test_parent_snapshot_detects_change_and_deletion(tmp_path):
    a=tmp_path/'source.json';b=tmp_path/'ledger.json';a.write_text('original');b.write_text('historical budget')
    files={str(p):control.sha_file(p) for p in (a,b)};verify_files(files)
    b.write_text('budget reset')
    with pytest.raises(ValueError):verify_files(files)
    b.write_text('historical budget');a.unlink()
    with pytest.raises(FileNotFoundError):verify_files(files)
