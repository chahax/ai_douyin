"""One offline actual-request check of full404/405 evidence revision with380 facts."""
from copy import deepcopy
import json
from types import SimpleNamespace
import socket
from pathlib import Path
from scripts import run_legal_complete_revision_v2 as m

PRIOR=m.PROJECT/'data/production_revisions/legal_spoken_dialogue_revision_20261010/round_01'


def test_complete_404_405_gate_enter_actual_new_request_but380_remains_facts(monkeypatch,tmp_path):
    def denied(*args,**kwargs):raise AssertionError('v2 complete revision check must remain offline')
    monkeypatch.setattr(socket.socket,'connect',denied)
    monkeypatch.setattr(socket,'create_connection',denied)
    settings=m.control.read(PRIOR/'SETUP.json')
    settings=deepcopy(settings)
    settings['parent_text_directory']=str(PRIOR.relative_to(m.PROJECT))
    settings['previous_revision_directory']=str(PRIOR.relative_to(m.PROJECT))
    root=tmp_path/'revision_v2';root.mkdir()
    (root/'SETUP.json').write_text(json.dumps(settings,ensure_ascii=False),encoding='utf-8')
    op=m.Revision(root)
    stored={}
    original_read=m.control.read
    monkeypatch.setattr(m.control,'write',lambda path,value,*args:stored.update({str(path):deepcopy(value)}))
    monkeypatch.setattr(m.control,'read',lambda path:deepcopy(stored[str(path)]) if str(path) in stored else original_read(path))
    monkeypatch.setattr(op,'runtime',lambda:SimpleNamespace(prepare=lambda:None))
    monkeypatch.setattr(op,'summary',lambda:{})
    op.prepare()
    x=stored[str(root/'INPUT.json')];a=stored[str(root/'ANCHOR.json')]
    ledger=original_read(PRIOR/'CALL_LEDGER.json')
    draft,review=[original_read(PRIOR/row['receipt']) for row in ledger['calls']]
    failed=original_read(PRIOR/'FULL_MODEL_SCRIPT.json')
    gate=original_read(PRIOR/'INDEPENDENT_EDITORIAL_GATE.json')
    assert draft['ordinal']==404 and review['ordinal']==405
    assert review['validation']['needs_revision'] is True and gate['text_candidate_qualified'] is False
    assert a['inherited']['calls_started']==405 and a['inherited']['reported_tokens']==6529230
    assert a['inherited']['unknown_token_reservations']==93117 and a['inherited']['pending_ordinals']==[70,160]
    assert a['budget_reset'] is False and a['automatic_retry'] is False and a['media_authorized'] is False
    assert x['draft_to_replace_not_facts']==failed
    assert m.compile_writer_script(draft['output'],x['source_direction'])==failed
    assert x['previous_full_review']==review['output'] and x['independent_editorial_revision']==gate
    source380=original_read(m.PROJECT/settings['source_directory']/'REVIEWED_CANDIDATE/FULL_SCRIPT.json')
    brief=stored[str(root/'CURRENT_BRIEF.json')]
    assert brief['source_identity']['sha256']==m.control.digest(source380)
    assert brief['source_identity']['sha256']!=m.control.digest(failed)
    assert x['feedback']['source_script_sha256']==m.control.digest(source380)
    assert gate['script_sha256']==m.control.digest(failed)
    for path in [PRIOR/'FULL_MODEL_SCRIPT.json',PRIOR/'INDEPENDENT_EDITORIAL_GATE.json',PRIOR/ledger['calls'][1]['receipt']]:
        assert a['parent_files'][str(path)]==m.control.sha_file(path)
    calls=[]
    def dispatch(label,request,validator):
        calls.append((label,deepcopy(request)))
        return {'ordinal':999,'status':'contract_rejected'}
    monkeypatch.setattr(op,'prepare',lambda:None)
    monkeypatch.setattr(op,'runtime',lambda:SimpleNamespace(dispatch=dispatch))
    op.dispatch('draft')
    assert len(calls)==1
    label,request=calls[0]
    assert label=='complete_draft' and request['model']=='MiniMax-M3'
    body=json.loads(request['messages'][1]['content'])
    assert body['draft_to_replace_not_facts']==failed
    assert body['previous_full_review']==review['output'] and body['independent_editorial_revision']==gate
    assert body['reference_fulltext']==x['reference_fulltext'] and body['feedback']==x['feedback']
    assert body['authoring']==x['current_projection']['writer_context']
    assert request['input_provenance']['creative_text_changed_locally'] is False
    assert request['input_provenance']['new_media_authorized'] is False
    assert stored[str(root/'request_previews/draft.json')]==request
    assert original_read(PRIOR/ledger['calls'][1]['receipt'])['validation']['needs_revision'] is True
