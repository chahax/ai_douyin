"""Four scoped offline examples for current resignation facts and completion gate."""
from copy import deepcopy
import json
from pathlib import Path
import re
import socket
import pytest
from src.content_factory.creative_legal_current_facts_gate_v1 import check_current_scene_facts
from scripts import run_legal_complete_revision_v4 as m

GOOD=m.PROJECT/'data/production_revisions/legal_natural_interaction_20261010/round_05/REVIEWED_CANDIDATE/FULL_SCRIPT.json'
BAD=m.PROJECT/'data/production_revisions/legal_spoken_dialogue_revision_20261010/round_04/FULL_MODEL_SCRIPT.json'


def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args,**kwargs):raise AssertionError('scoped fact gate test must stay offline')
    monkeypatch.setattr(socket.socket,'connect',denied)
    monkeypatch.setattr(socket,'create_connection',denied)


def test_real380_passes_and_real410_dates_system_family_penalty_push_are_caught():
    good=read(GOOD);before=deepcopy(good)
    assert check_current_scene_facts(good)==[] and good==before
    bad=read(BAD);before=deepcopy(bad)
    findings=check_current_scene_facts(bad)
    assert {q['code'] for q in findings}.issuperset({'UNAPPROVED_WORKING_DATE','UNAPPROVED_SYSTEM_CAUSE',
        'UNAPPROVED_PERSONAL_HISTORY','UNAPPROVED_PENALTY','UNAPPROVED_FOLLOWUP_PROMISE','PAPER_BEFORE_COMPANY_NOTICE'})
    assert any(q['code']=='UNAPPROVED_WORKING_DATE' and '周五' in q['evidence_text'] for q in findings)
    assert bad==before


def test_moving_only_good380_delivery_before_notice_is_rejected():
    s=read(GOOD)
    steps=s['beats'][0]['steps']
    index=next(i for i,q in enumerate(steps) if q['kind']=='action' and re.search('推|送',q['text']) and re.search('纸|申请|笔',q['text']))
    step=steps.pop(index);steps.insert(0,step)
    findings=check_current_scene_facts(s)
    assert [q['code'] for q in findings]==['PAPER_BEFORE_COMPANY_NOTICE']
    assert findings[0]['evidence_ref']=='B1.S01' and findings[0]['evidence_text']==step['text']


def test_event_title_cannot_substitute_for_an_actual_company_departure_notice():
    s=read(GOOD)
    for q in s['beats'][0]['steps']:
        if q['kind']=='dialogue' and q['speaker'].startswith('周姐') and '公司' in q['text']:
            q['text']='我们先看看这张表。'
    s['beats'][0]['event']='周姐已经明确通知公司让小林离开。'
    codes={q['code'] for q in check_current_scene_facts(s)}
    assert 'COMPANY_DEPARTURE_NOTICE_NOT_EXPLICIT' in codes
    assert 'PAPER_BEFORE_COMPANY_NOTICE' in codes


def test_v4_finish_blocks_local_finding_even_when_model_and_independent_review_are_clean(monkeypatch,tmp_path):
    s=read(BAD);local=check_current_scene_facts(s)
    assert local
    op=object.__new__(m.Revision);op.root=tmp_path
    monkeypatch.setattr(op,'script',lambda:deepcopy(s))
    draft={'output':{},'validation':{'local_current_fact_findings':local}}
    review={'validation':{'needs_revision':False}}
    monkeypatch.setattr(op,'accepted',lambda label:deepcopy(draft if label=='complete_draft' else review))
    gate={'script_sha256':m.control.digest(s),'text_candidate_qualified':True,'unresolved_mandatory_findings':[]}
    monkeypatch.setattr(m.control,'read',lambda path:deepcopy(gate))
    writes=[]
    monkeypatch.setattr(m.control,'write',lambda *args,**kwargs:writes.append(args))
    with pytest.raises(ValueError,match='full current review unresolved'):op.finish()
    assert writes==[]
