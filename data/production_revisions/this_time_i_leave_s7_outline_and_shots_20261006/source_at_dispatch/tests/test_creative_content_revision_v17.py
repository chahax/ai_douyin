"""Focused offline binding, evidence transport and no-redelivery checks."""
from copy import deepcopy
from pathlib import Path
import json
from types import SimpleNamespace
import pytest
from scripts import run_creative_content_revision_v17 as run
from scripts import creative_resume_dispatch_v3 as control


def test_full_reference_feedback_and_original_s6_really_enter_writer_request():
    request=run.writer_request(1)
    payload=json.loads(request['messages'][1]['content'])
    assert payload['context']['reference_pack']==run.source.original()['reference_pack']
    assert payload['previous_script']==control.read(run.parent.ROOT/'DELIVERABLE_s6_d6/FULL_SCRIPT.json')
    assert payload['issues']['user_feedback']==control.read(run.FEEDBACK)
    assert request['role']=='writer' and request['model']=='MiniMax-M3'
    assert request['parameters']=={'max_completion_tokens':6500,'temperature':.4,'thinking':'disabled'}


def test_inherited_spend_no_redelivery_and_unknown_blocks_next(tmp_path):
    original=control.read(run.parent.ROOT/'DELIVERABLE_s6_d6/FULL_SCRIPT.json')
    calls=[]
    class FakeClients:
        def call(self,role,messages,**kwargs):
            calls.append((role,deepcopy(messages)))
            response={'payload_json':json.dumps(original,ensure_ascii=False)}
            return SimpleNamespace(text=json.dumps(response,ensure_ascii=False),metadata={'total_tokens':20,'response_id':'offline-fixture-one','finish_reason':'tool_calls','output_mode':'tool_call','tool_calls':[{'function':{'name':'submit_creative_json'}}]},response_payload={'offline_fixture':True})
    inherited={'calls_started':158,'reported_tokens':2915735,'calls_with_known_usage':157,'unknown_token_reservations':64010,'pending_ordinals':[70]}
    models=control.read(run.parent.ROOT/'CALL_LEDGER.json')['model_configs']
    rt=control.ContinuationRuntime(run.PROJECT,tmp_path,[Path(run.__file__)],inherited,models,client_factory=FakeClients)
    rt.prepare();request=run.writer_request(1)
    first=rt.dispatch('offline_s7_full',request,lambda raw:{'fixture_only':True,'source_equal':raw==original})
    assert first['status']=='contract_valid' and first['ordinal']==159
    second=rt.dispatch('offline_s7_full',request,lambda raw:{'fixture_only':True})
    assert second['ordinal']==159 and len(calls)==1
    assert rt.summary()['effective_calls_started']==159 and rt.summary()['effective_reported_tokens']==2915755
    assert control.read(rt.ledger)['starting_spend']['unknown_token_reservations']==64010
    receipt=control.read(rt.root/control.read(rt.ledger)['calls'][0]['receipt']);receipt['status']='outcome_unknown';receipt['response_metadata']={}
    control.write(rt.root/control.read(rt.ledger)['calls'][0]['receipt'],receipt)
    ledger=control.read(rt.ledger);ledger['calls'][0]['receipt_sha256']=control.sha_file(rt.root/ledger['calls'][0]['receipt']);control.write(rt.ledger,ledger)
    another=deepcopy(request);another['messages'].append({'role':'user','content':'distinct offline fixture'})
    with pytest.raises(RuntimeError,match='unknown outcome/usage'):
        rt.dispatch('offline_unknown_next',another,lambda raw:{})
    assert len(calls)==1


def test_source_id_exact_leaf_binding_does_not_create_valid_review():
    raw=control.read(run.parent.ROOT/'DELIVERABLE_s6_d6/FULL_SCRIPT.json');ctx=run.source.original();ctx['script']=run.source.derive(raw);ctx['script'].pop('screenplay_markdown')
    ctx['script_timing_status']=run.source.linear.TIMING_STATUS
    entries=run.review_catalog(ctx);key=next(k for k,v in entries.items() if v['path'].startswith('script.beats.0.'))
    expected=entries[key]
    check=['not_applicable','offline fixture',[key],[]]
    wire={'schema':run.ID_VERSION,'context_sha256':run.source.compact.context_digest(ctx),'story_preserved':True,'issues':[],'suggestions':[],'calibration_focus':[],'coverage':[[b['id']]+[deepcopy(check) for _ in range(6)] for b in ctx['script']['beats']]}
    expanded=run.expand_review(wire,ctx)
    assert expanded['coverage'][0][1][2]==[[expected['path'],expected['quote']]]
    stale=deepcopy(ctx);stale['script']['premise']='offline changed context'
    with pytest.raises(Exception):run.expand_review(wire,stale)
    with pytest.raises(Exception):run.source.review_wire.validate_script_review(expanded,ctx)
