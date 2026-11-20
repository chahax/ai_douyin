"""Isolated Chrome + immutable source-bound UI evidence, never a platform call."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import pytest

from src.platform_adapter import fanqie_form_feedback_v1 as f
from src.operations_accounts import fanqie_managed_promotion_v1 as m
from test_fanqie_application_readback_v1 import BOOK,NAME,INTENT,ENTRY,browser,page
from test_fanqie_alias_validation_v1 import prepared,MESSAGE

local=pytest.mark.skipif(os.environ.get('RUN_LOCAL_FANQIE_FORM_TEST')!='1',reason='Isolated local DOM opt-in')
ROOT=Path(__file__).resolve().parents[1]
DEV=ROOT/'data/flow_development/fanqie_postclick_empty_binding_20261117_v1'


def post(page,mode='empty'):
    page.evaluate('''({mode,message})=>{
      document.querySelector('.submit').onclick=()=>{events.submit++;
       setTimeout(()=>{
        state.alias=mode==='other'?'另一条未授权词':'';
        if(mode==='wrongbook')state.book='8302660145530539062';
        render();document.querySelector('.submit').disabled=true;
        const modal=document.querySelector('.arco-modal-content');
        modal.insertAdjacentHTML('beforeend','<div class="err-list-h4mOz7"></div>');
        modal.querySelector('.err-list-h4mOz7').textContent=mode==='mixed'?message+'\\n网络异常，请稍后再试':message;
        if(mode==='missing')modal.querySelector('input').remove();
        if(mode==='multiple')modal.insertAdjacentHTML('beforeend','<input class="alias-input-EBp1Sw">');
        if(mode==='success')document.body.insertAdjacentHTML('beforeend','<div class="title-azi_qL">申请成功</div>');
       },100);};}''',dict(mode=mode,message=MESSAGE))


def bound(p):
    return dict(path=str(p.resolve()),sha256=hashlib.sha256(p.read_bytes()).hexdigest())


def save(p,v):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(v,ensure_ascii=False),encoding='utf8')
    return bound(p)


@local
def test_current_empty_is_bound_to_once_submitted_alias_without_faking_current_value(page):
    prepared(page);post(page)
    value=page.evaluate(m._form_js(INTENT,submit=True,entry_evidence=ENTRY))
    check=f.validate_alias_validation(value,INTENT)
    assert check['schema']=='fanqie_alias_validation/v2'
    assert check['current_alias']==''and check['same_alias']is False
    assert check['submitted_alias']==INTENT['alias']and check['submitted_alias_bound']is True
    assert check['observation']['alias_input_count']==1 and check['observation']['alias_input_attached']is True
    assert check['alias_binding']['react_internal_state_verified']is False
    assert page.evaluate('events.submit')==1
    outcome=m._alias_validation_failure(value,INTENT,dict(path='local-evidence',sha256='test'))
    assert outcome.state=='failed'and outcome.result['submitted']is True
    assert outcome.result['retry_with_new_alias']is True and outcome.result['alias_reusable']is False


@local
@pytest.mark.parametrize('mode',['other','missing','multiple','wrongbook','mixed','success'])
def test_conflicting_or_incomplete_postclick_evidence_never_authorizes_next_alias(page,mode):
    prepared(page);post(page,mode)
    value=page.evaluate(m._form_js(INTENT,submit=True,entry_evidence=ENTRY))
    assert not f.confirmed_alias_validation(value,INTENT)
    assert not value.get('retry_with_new_alias',False)
    assert page.evaluate('events.submit')==1


@local
def test_v2_validator_rechecks_intermediate_samples_stale_hints_counts_and_success(page):
    prepared(page);post(page)
    valid=page.evaluate(m._form_js(INTENT,submit=True,entry_evidence=ENTRY))
    assert f.confirmed_alias_validation(valid,INTENT)
    for field,value in [('current_alias',None),('current_alias','其他词'),('alias_input_count',2),('alias_input_attached',False)]:
        bad=deepcopy(valid);sample=bad['form_feedback']['post_click'][0]
        # Keep all copies consistent: rejection must be semantic, not only inequality.
        old=deepcopy(sample);sample[field]=value
        bad['form_feedback']['latest']=sample
        bad['form_feedback']['observations']=[sample if s==old else s for s in bad['form_feedback']['observations']]
        bad['alias_validation']['observation']=sample
        with pytest.raises(ValueError):f.validate_alias_validation(bad,INTENT)
    for change in ['click_count','stale','success','intermediate_other']:
        bad=deepcopy(valid);h=bad['form_feedback'];u=bad['submission_feedback']
        if change=='click_count':h['click_count']=2
        elif change=='stale':h['pre_click']['messages']=deepcopy(h['latest']['messages'])
        elif change=='success':u['observations'][0]['titles']=[dict(visible=True,attached=True,text='申请成功')]
        else:
            s=deepcopy(h['post_click'][0]);s['phase']='post_click_0';s['current_alias']='另一条词';s['same_alias']=False
            s['observed_at']-=0.1
            h['post_click'][0]['phase']='post_click_1';h['post_click'].insert(0,s);h['observations'].append(s)
            first=deepcopy(u['observations'][0]);first['observed_at']=s['observed_at'];u['observations'][0]['index']=2
            u['observations'].insert(0,first)
        with pytest.raises(ValueError):f.validate_alias_validation(bad,INTENT)


def legacy_fixture(tmp_path,prepared_value,live):
    folder=tmp_path/'command';folder.mkdir()
    raw=deepcopy(live)
    for key in ['alias_validation','retry_with_new_alias','alias_reusable','reason']:raw.pop(key,None)
    raw.update(ready=True,result='post_submit_feedback_observed',feedback_classification='unverified_form_feedback')
    raw['form_feedback'].pop('click_count');raw['form_feedback'].pop('post_click_field_writes')
    # Serialize each legacy observation exactly without adding missing fields.
    for h in [raw['form_feedback'],prepared_value['form_feedback']]:
        for s in h['observations']+[h['baseline'],h['pre_click'],h['latest']]+h['post_click']:
            for key in ['modal_count','alias_input_count','alias_input_attached']:s.pop(key,None)
    intent=dict(INTENT,resource_id='fanqie:test',binding_version='b',platform_identity_key='uid:test')
    auth=save(tmp_path/'AUTH.json',dict(confirmed_by='user',intent=intent,max_submissions=1))
    request=save(tmp_path/'REQUEST.json',dict(intent,schema='fanqie_promotion_apply_request/v1',authorization=auth))
    claim=save(folder/'SUBMIT_CLAIM.json',dict(command_id=folder.name,intent=intent,request=request,owner_id='owner',generation=1,
        automatic_retry=False,at_epoch=(prepared_value['form_feedback']['pre_click']['observed_at']+raw['form_feedback']['pre_click']['observed_at'])/2))
    prep=save(folder/'FORM_PREPARED.json',prepared_value);response=save(folder/'SUBMIT_RESPONSE.json',raw)
    paths={'managed_source_ref':DEV/'fanqie_managed_promotion_v1.py.before','feedback_source_ref':DEV/'fanqie_form_feedback_v1.py.before'}
    sources=[dict(path=str(ROOT/'src/operations_accounts/fanqie_managed_promotion_v1.py'),sha256=f._LEGACY_SOURCE_SHA['managed']),
             dict(path=str(ROOT/'src/platform_adapter/fanqie_form_feedback_v1.py'),sha256=f._LEGACY_SOURCE_SHA['feedback'])]
    manifest=save(tmp_path/'MANIFEST.json',dict(schema='fanqie_alias_flow_source_seal/v1',sources=sources))
    spec=save(tmp_path/'SPEC.json',dict(book=INTENT,aliases=[INTENT['alias']],resource_binding=intent))
    approval=save(tmp_path/'APPROVAL.json',dict(schema='fanqie_alias_flow_search_scope_fix_approval/v1',source_manifest=manifest,continuation_spec=spec))
    plan=save(tmp_path/'PLAN.json',dict(schema='fanqie_alias_flow/v1',spec=spec))
    state=save(tmp_path/'STATE.json',dict(schema='fanqie_alias_flow/v1',spec=spec,
        last_application=dict(command_id=folder.name,alias=INTENT['alias'],result=dict(feedback_ref=response,form_prepared=prep)),
        operations=[dict(kind='apply',command_id=folder.name,alias=INTENT['alias'])]))
    args=dict(form_prepared_ref=prep,submit_claim_ref=claim,code_manifest_ref=manifest,
        execution_approval_ref=approval,execution_plan_ref=plan,execution_state_ref=state,**{k:bound(p)for k,p in paths.items()})
    return response,args


@local
def test_legacy_derivation_preserves_missing_fields_and_raw_bytes_then_revalidates_all_refs(page,tmp_path):
    good=prepared(page);post(page);live=page.evaluate(m._form_js(INTENT,submit=True,entry_evidence=ENTRY))
    # Real production UI has disabled empty baseline; the local fixture exposes
    # a trivial initially-enabled button, so explicitly model that observed state.
    good['form_feedback']['baseline']['submit_buttons'][0].update(disabled=True,enabled=False)
    ref,args=legacy_fixture(tmp_path,good,live);before=Path(ref['path']).read_bytes()
    result=f.derive_alias_validation(ref,INTENT,**args);value=f.validate_alias_validation(result,INTENT)
    assert value['alias_binding']['evidence_mode']=='legacy_source_bound_derivation'
    assert value['same_alias']is False and value['submitted_alias']==INTENT['alias']
    assert 'alias_input_count'not in value['observation']and 'alias_input_attached'not in value['observation']
    assert Path(ref['path']).read_bytes()==before
    changed=deepcopy(result);changed['alias_validation']['same_alias']=True
    with pytest.raises(ValueError):f.validate_alias_validation(changed,INTENT)
    wrong=deepcopy(args);wrong['managed_source_ref']=wrong['feedback_source_ref']
    with pytest.raises(ValueError):f.derive_alias_validation(ref,INTENT,**wrong)
    wrong=deepcopy(args);p=tmp_path/'BAD_APPROVAL.json'
    wrong['execution_approval_ref']=save(p,dict(schema='fanqie_alias_flow_search_scope_fix_approval/v1',source_manifest=args['code_manifest_ref']))
    with pytest.raises(ValueError):f.derive_alias_validation(ref,INTENT,**wrong)
    Path(args['form_prepared_ref']['path']).write_text('{}',encoding='utf8')
    with pytest.raises(ValueError,match='evidence_changed'):f.validate_alias_validation(result,INTENT)


@local
def test_legacy_missing_or_other_current_value_is_not_inferred_from_code_pin(page,tmp_path):
    good=prepared(page);post(page);live=page.evaluate(m._form_js(INTENT,submit=True,entry_evidence=ENTRY))
    good['form_feedback']['baseline']['submit_buttons'][0].update(disabled=True,enabled=False)
    ref,args=legacy_fixture(tmp_path,good,live)
    for invalid in [None,'其他别名']:
        raw=json.loads(Path(ref['path']).read_text('utf8'));raw['form_feedback']['latest']['current_alias']=invalid
        changed=save(Path(ref['path']),raw)
        with pytest.raises(ValueError):f.derive_alias_validation(changed,INTENT,**args)
