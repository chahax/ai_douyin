"""Four scoped v2 examples distinguish leave dates, office urging and prefilled reasons."""
from copy import deepcopy
import json
from pathlib import Path
import socket
import pytest
from src.content_factory import creative_legal_current_facts_gate_v2 as gate
from scripts import run_legal_complete_revision_v5 as operator

PROJECT=operator.PROJECT
SOURCE380=PROJECT/'data/production_revisions/legal_natural_interaction_20261010/round_05/REVIEWED_CANDIDATE/FULL_SCRIPT.json'
SOURCE410=PROJECT/'data/production_revisions/legal_spoken_dialogue_revision_20261010/round_04/FULL_MODEL_SCRIPT.json'
SOURCE412=PROJECT/'data/production_revisions/legal_spoken_dialogue_revision_20261010/round_05/FULL_MODEL_SCRIPT.json'


def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))

def scene_with(text):
    return {'beats':[{'id':'B1','steps':[
        {'kind':'dialogue','speaker':'周姐（虚构人事主管）','text':'公司决定让你离开。'},
        {'kind':'action','text':'周姐把纸和笔一次推到小林近桌沿。'},
        {'kind':'dialogue','speaker':'周姐（虚构人事主管）','text':text}]}]}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args,**kwargs):raise AssertionError('scoped v2 fact checks must remain offline')
    monkeypatch.setattr(socket.socket,'connect',denied)
    monkeypatch.setattr(socket,'create_connection',denied)


def test_real380_stays_clean_real410_material_violations_stay_detected():
    original=read(SOURCE380);before=deepcopy(original)
    assert gate.check_current_scene_facts(original)==[] and original==before
    bad=read(SOURCE410);before=deepcopy(bad)
    findings=gate.check_current_scene_facts(bad)
    assert {q['code'] for q in findings}.issuperset({'UNAPPROVED_WORKING_DATE','UNAPPROVED_SYSTEM_CAUSE',
        'UNAPPROVED_PERSONAL_HISTORY','UNAPPROVED_PENALTY','PAPER_BEFORE_COMPANY_NOTICE'})
    assert any(q['code']=='UNAPPROVED_WORKING_DATE' and '周五' in q['evidence_text'] for q in findings)
    assert bad==before
    assert operator.check_current_scene_facts is gate.check_current_scene_facts


def test_real412_wrong_date_removed_but_employee_rewriting_prefilled_reason_is_caught():
    s=read(SOURCE412);before=deepcopy(s)
    findings=gate.check_current_scene_facts(s)
    assert 'UNAPPROVED_WORKING_DATE' not in {q['code'] for q in findings}
    found=[q for q in findings if q['code']=='PRE_FILLED_REASON_REWRITING']
    assert len(found)==1 and found[0]['evidence_ref']=='B2.S02'
    assert '你不写这一行' in found[0]['evidence_text']
    assert s==before


def test_today_signature_reporting_and_personal_thinking_are_not_leave_dates_or_promises():
    for text in ['今天签一下吧。','今天不交上去，我交不了差。','我回去再想想怎么办。']:
        assert gate.check_current_scene_facts(scene_with(text))==[]
    for text in ['你的东西今天就开始交接。','公司的意思是到这周五你就离开。']:
        assert 'UNAPPROVED_WORKING_DATE' in {q['code'] for q in gate.check_current_scene_facts(scene_with(text))}


def test_describing_prefilled_column_is_not_requesting_employee_rewrite():
    for text in ['你看，这一行写着个人原因。','你看，这里写的是个人原因。','这一行已经写好了，你只在签名处签。','这是你们写的个人原因。']:
        assert gate.check_current_scene_facts(scene_with(text))==[]
    assert 'PRE_FILLED_REASON_REWRITING' in {q['code'] for q in gate.check_current_scene_facts(scene_with('你填一下个人原因。'))}
