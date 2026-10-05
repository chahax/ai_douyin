from pathlib import Path
from copy import deepcopy
import json
import pytest
from jsonschema import Draft202012Validator
from scripts import creative_review_wire_v14 as wire
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/modular_bd_v1/resume_20261005_v13'

def case():
    r=json.loads((RUN/'call_156_full_review_s6_d6_view13_r1.json').read_text(encoding='utf-8'))
    return r['output'],json.loads(r['request']['messages'][1]['content'])

def test_real_container_reference_rejected_by_schema():
    bad,ctx=case();assert len(wire.diagnostics(bad,ctx))==8
    with pytest.raises(Exception):Draft202012Validator(wire.schema(ctx)).validate(bad)
    assert 'shots.shots.1.dialogue_lock' not in wire.scalar_leaves(ctx)
    assert 'shots.shots.1.dialogue_lock.0.text' in wire.scalar_leaves(ctx)

def test_evidence_repair_cannot_change_any_conclusion():
    bad,ctx=case();candidate=deepcopy(bad);candidate['coverage'][0][1][2]=[]
    wire.validate_repair_preserves_conclusions(bad,candidate)
    candidate['coverage'][0][1][1]+=' invented'
    with pytest.raises(Exception):wire.validate_repair_preserves_conclusions(bad,candidate)
    candidate=deepcopy(bad);candidate['story_preserved']=False
    with pytest.raises(Exception):wire.validate_repair_preserves_conclusions(bad,candidate)
