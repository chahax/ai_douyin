"""A real zero-issue model review cannot override independently known text defects."""
import json
from pathlib import Path
import pytest
from scripts import run_legal_dialogue_refinement_v7_20261009 as run
from scripts import creative_resume_dispatch_v3 as c
SOURCE=Path('data/production_revisions/legal_dialogue_refinement_20261009/round_06')

def test_model_zero_issues_does_not_release_known_physical_defect(tmp_path,monkeypatch):
 script=c.read(SOURCE/'DRAFT.json');review=c.read(SOURCE/'call_349_craft_review_r06.json')
 assert review['validation']['needs_revision'] is False
 gate={'script_sha256':c.digest(script),'text_only_editorial_checked':True,'unresolved_mandatory_findings':['E01']}
 (tmp_path/'TEXT_EDITORIAL_GATE.json').write_text(json.dumps(gate),encoding='utf-8')
 monkeypatch.setattr(run,'root',lambda n:tmp_path)
 monkeypatch.setattr(run,'accepted',lambda n,label:{'output':script})
 with pytest.raises(ValueError,match='editorial issues unresolved'):run.finish(7)
 assert not (tmp_path/'DELIVERABLE').exists()

def test_old_source_editorial_approval_is_not_reusable(tmp_path,monkeypatch):
 script=c.read(SOURCE/'DRAFT.json');gate={'script_sha256':'0'*64,'text_only_editorial_checked':True,'unresolved_mandatory_findings':[]}
 (tmp_path/'TEXT_EDITORIAL_GATE.json').write_text(json.dumps(gate),encoding='utf-8')
 monkeypatch.setattr(run,'root',lambda n:tmp_path)
 monkeypatch.setattr(run,'accepted',lambda n,label:{'output':script})
 with pytest.raises(ValueError,match='editorial issues unresolved'):run.finish(7)
 assert not (tmp_path/'DELIVERABLE').exists()
