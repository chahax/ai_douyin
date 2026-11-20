"""Three offline checks of complete spoken-dialogue rewriting and whole-new-script review."""
from copy import deepcopy
import json
from pathlib import Path
import socket
from types import SimpleNamespace
import pytest
from scripts import run_legal_complete_revision as m

SETUP=m.PROJECT/'data/production_revisions/legal_spoken_dialogue_revision_20261010/round_01/SETUP.json'


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('complete script revision tests must remain offline')
    monkeypatch.setattr(socket.socket,'connect',denied)
    monkeypatch.setattr(socket,'create_connection',denied)


@pytest.fixture
def prepared(monkeypatch,tmp_path):
    root=tmp_path/'revision';root.mkdir()
    settings=m.control.read(SETUP)
    (root/'SETUP.json').write_text(json.dumps(settings,ensure_ascii=False),encoding='utf-8')
    op=m.Revision(root)
    stored={}
    original=m.control.read
    monkeypatch.setattr(m.control,'write',lambda path,value,*args:stored.update({str(path):deepcopy(value)}))
    monkeypatch.setattr(m.control,'read',lambda path:deepcopy(stored[str(path)]) if str(path) in stored else original(path))
    monkeypatch.setattr(op,'runtime',lambda:SimpleNamespace(prepare=lambda:None))
    monkeypatch.setattr(op,'summary',lambda:{})
    op.prepare()
    return SimpleNamespace(op=op,settings=settings,stored=stored,x=stored[str(root/'INPUT.json')],anchor=stored[str(root/'ANCHOR.json')])


@pytest.fixture
def captured(prepared,monkeypatch):
    op=prepared.op
    calls=[]
    raw=m.control.read(m.PROJECT/prepared.settings['source_directory']/'REVIEWED_CANDIDATE/RAW_MODEL_SCRIPT.json')
    new_raw=deepcopy(raw)
    index=0
    for beat in new_raw['beats']:
        for step in beat['steps']:
            if step['kind']=='dialogue':
                index+=1
                step['text']='离线模拟完整新稿对白'+str(index)+'。'
    def dispatch(label,request,validator):
        calls.append((label,deepcopy(request),validator))
        return {'ordinal':999,'status':'contract_rejected'}
    monkeypatch.setattr(op,'prepare',lambda:None)
    monkeypatch.setattr(op,'runtime',lambda:SimpleNamespace(dispatch=dispatch))
    monkeypatch.setattr(op,'accepted',lambda label:{'ordinal':999,'output':deepcopy(new_raw)})
    return SimpleNamespace(calls=calls,new_raw=new_raw,old_raw=raw)


def test_real_parent403_spend_and_full_old380_are_preserved(prepared):
    a=prepared.anchor
    assert a['inherited']['calls_started']==403 and a['inherited']['reported_tokens']==6514133
    assert a['inherited']['unknown_token_reservations']==93117 and a['inherited']['pending_ordinals']==[70,160]
    assert a['budget_reset'] is False and a['automatic_retry'] is False
    assert a['media_authorized'] is False and a['old_governance_migrated'] is False
    source=m.PROJECT/prepared.settings['source_directory']
    assert prepared.x['draft_to_replace_not_facts']==m.control.read(source/'REVIEWED_CANDIDATE/FULL_SCRIPT.json')
    assert prepared.x['reference_fulltext']==m.control.read(source/'INPUT.json')['reference_fulltext']
    assert prepared.x['feedback']['user_statement']==prepared.settings['user_statement']
    assert prepared.x['feedback']['assistant_viewed_or_listened'] is False
    assert prepared.x['feedback']['new_video_authorized'] is False


def test_writer_actual_complete_old_source_current_facts_reference_and_user_feedback(prepared,captured):
    prepared.op.dispatch('draft')
    assert len(captured.calls)==1
    label,request,validator=captured.calls[0]
    body=json.loads(request['messages'][1]['content'])
    assert label=='complete_draft' and request['model']=='MiniMax-M3'
    assert body['draft_to_replace_not_facts']==prepared.x['draft_to_replace_not_facts']
    assert body['authoring']==prepared.x['current_projection']['writer_context']
    assert body['reference_fulltext']==prepared.x['reference_fulltext']
    assert body['feedback']==prepared.x['feedback']
    assert body['spoken_language_revision_criteria']==prepared.settings['criteria']
    assert 'source_direction' not in body and 'current_projection' not in body
    result=validator(captured.new_raw)
    assert result['full_model_script'] is True
    assert result['creative_text_changed_locally'] is False and result['creative_quality_passed'] is False
    partial=deepcopy(captured.new_raw);partial['beats']=partial['beats'][:1]
    with pytest.raises(Exception):validator(partial)
    assert body['draft_to_replace_not_facts']==prepared.x['draft_to_replace_not_facts']


def test_review_reads_entire_new_object_and_compiles_without_old_dialogue_splicing(prepared,captured):
    prepared.op.dispatch('review')
    label,request,validator=captured.calls[0]
    assert label=='full_review' and request['model']=='deepseek-flash'
    body=json.loads(request['messages'][1]['content'])
    expected=m.compile_writer_script(captured.new_raw,prepared.x['source_direction'])
    assert prepared.op.script()==expected and body['full_current_script']==expected
    assert [b['id'] for b in expected['beats']]==['B1','B2','B3','B4']
    raw_lines=[q['text'] for b in captured.new_raw['beats'] for q in b['steps'] if q['kind']=='dialogue']
    compiled_lines=[q['text'] for b in expected['beats'] for q in b['steps'] if q['kind']=='dialogue']
    assert compiled_lines==raw_lines
    old_lines=[q['text'] for b in prepared.x['draft_to_replace_not_facts']['beats'] for q in b['steps'] if q['kind']=='dialogue']
    assert not set(compiled_lines).intersection(old_lines)
    assert body['source_catalog']==m.baseline.evidence(expected)
    assert body['reference_fulltext']==prepared.x['reference_fulltext'] and body['feedback']==prepared.x['feedback']
    review={'full_review_complete':True,'story_invariants_preserved':True,'human_spoken_language_feedback_addressed':True,
        'dialogue_and_character_tactics':'offline assessment','causal_and_physical_assessment':'offline assessment',
        'parallel_interaction_assessment':'offline assessment','evidence_refs':[next(iter(body['source_catalog']))],
        'issues':[],'suggestions':[],'assessment':'offline candidate only'}
    assert validator(review)['needs_revision'] is False and validator(review)['creative_quality_passed'] is False
    review['human_spoken_language_feedback_addressed']=False
    assert validator(review)['needs_revision'] is True
    assert not hasattr(prepared.op,'media')
