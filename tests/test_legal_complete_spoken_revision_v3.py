"""One offline v3 projection check: no complete rejected dialogue in writer, full new review."""
from copy import deepcopy
import json
from pathlib import Path
import socket
from types import SimpleNamespace
from scripts import run_legal_complete_revision_v3 as m

PRIOR=m.PROJECT/'data/production_revisions/legal_spoken_dialogue_revision_20261010/round_02'


def test_v3_writer_has_current_facts_reference_feedback_findings_and_review_full_new(monkeypatch,tmp_path):
    def denied(*args,**kwargs):raise AssertionError('v3 projection test must stay offline')
    monkeypatch.setattr(socket.socket,'connect',denied)
    monkeypatch.setattr(socket,'create_connection',denied)
    settings=deepcopy(m.control.read(PRIOR/'SETUP.json'))
    settings['parent_text_directory']=str(PRIOR.relative_to(m.PROJECT))
    settings['previous_revision_directory']=str(PRIOR.relative_to(m.PROJECT))
    root=tmp_path/'v3';root.mkdir()
    (root/'SETUP.json').write_text(json.dumps(settings,ensure_ascii=False),encoding='utf-8')
    op=m.Revision(root);stored={};original=m.control.read
    monkeypatch.setattr(m.control,'write',lambda path,value,*args:stored.update({str(path):deepcopy(value)}))
    monkeypatch.setattr(m.control,'read',lambda path:deepcopy(stored[str(path)]) if str(path) in stored else original(path))
    monkeypatch.setattr(op,'runtime',lambda:SimpleNamespace(prepare=lambda:None))
    monkeypatch.setattr(op,'summary',lambda:{})
    op.prepare()
    x=stored[str(root/'INPUT.json')];a=stored[str(root/'ANCHOR.json')]
    ledger=original(PRIOR/'CALL_LEDGER.json');draft,review=[original(PRIOR/q['receipt']) for q in ledger['calls']]
    failed=original(PRIOR/'FULL_MODEL_SCRIPT.json');gate=original(PRIOR/'INDEPENDENT_EDITORIAL_GATE.json')
    assert draft['ordinal']==406 and review['ordinal']==407 and review['validation']['needs_revision'] is False
    assert gate['text_candidate_qualified'] is False and gate['unresolved_mandatory_findings']
    assert gate['script_sha256']==review['validation']['script_sha256']==m.control.digest(failed)
    assert a['inherited']['calls_started']==407 and a['inherited']['reported_tokens']==6552462
    assert a['inherited']['unknown_token_reservations']==93117 and a['inherited']['pending_ordinals']==[70,160]
    assert a['automatic_retry'] is False and a['budget_reset'] is False and a['media_authorized'] is False
    assert x['draft_to_replace_not_facts']==failed and x['previous_full_review']==review['output']
    source380=original(m.PROJECT/settings['source_directory']/'REVIEWED_CANDIDATE/FULL_SCRIPT.json')
    assert stored[str(root/'CURRENT_BRIEF.json')]['source_identity']['sha256']==m.control.digest(source380)
    for p in [PRIOR/'FULL_MODEL_SCRIPT.json',PRIOR/'INDEPENDENT_EDITORIAL_GATE.json',PRIOR/ledger['calls'][1]['receipt']]:
        assert a['parent_files'][str(p)]==m.control.sha_file(p)
    new_raw=deepcopy(draft['output'])
    n=0
    for b in new_raw['beats']:
        for q in b['steps']:
            if q['kind']=='dialogue':n+=1;q['text']='离线完整新稿对白'+str(n)+'。'
    calls=[]
    def dispatch(label,request,validator):
        calls.append((label,deepcopy(request),validator));return {'ordinal':999,'status':'contract_rejected'}
    monkeypatch.setattr(op,'prepare',lambda:None)
    monkeypatch.setattr(op,'runtime',lambda:SimpleNamespace(dispatch=dispatch))
    monkeypatch.setattr(op,'accepted',lambda label:{'ordinal':999,'output':deepcopy(new_raw)})
    op.dispatch('draft')
    label,req,validator=calls[0];body=json.loads(req['messages'][1]['content'])
    assert label=='complete_draft' and req['model']=='MiniMax-M3'
    assert set(body)=={'authoring','reference_fulltext','feedback','spoken_language_revision_criteria','legal_expression_boundaries','evidenced_revision_findings'}
    assert 'draft_to_replace_not_facts' not in body and 'previous_full_review' not in body
    assert body['authoring']==x['current_projection']['writer_context']
    assert body['reference_fulltext']==x['reference_fulltext'] and body['feedback']==x['feedback']
    assert body['spoken_language_revision_criteria']==settings['criteria'] and len(settings['criteria'])==4
    assert body['evidenced_revision_findings']==gate['unresolved_mandatory_findings']
    for old_beat in failed['beats']:
        assert json.dumps(old_beat,ensure_ascii=False,separators=(',',':')) not in req['messages'][1]['content']
    assert req['input_provenance']['rejected_full_dialogue_excluded_from_writer'] is True
    assert req['input_provenance']['previous_complete_script_in_actual_messages'] is False
    assert validator(new_raw)['creative_quality_passed'] is False
    op.dispatch('review')
    label,req,_=calls[1];body=json.loads(req['messages'][1]['content'])
    expected=m.compile_writer_script(new_raw,x['source_direction'])
    assert label=='full_review' and req['model']=='deepseek-flash'
    assert body['full_current_script']==expected and body['source_catalog']==m.baseline.evidence(expected)
    assert [b['id'] for b in expected['beats']]==['B1','B2','B3','B4']
    assert [q['text'] for b in expected['beats'] for q in b['steps'] if q['kind']=='dialogue']==[q['text'] for b in new_raw['beats'] for q in b['steps'] if q['kind']=='dialogue']
    assert body['reference_fulltext']==x['reference_fulltext']
    assert body['previous_full_review']==review['output'] and body['draft_to_replace_not_facts']==failed
    assert len(calls)==2 and original(PRIOR/ledger['calls'][1]['receipt'])['validation']['needs_revision'] is False
