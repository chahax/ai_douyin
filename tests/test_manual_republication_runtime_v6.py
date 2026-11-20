"""Four bounded repair regressions; previous failures and all stores are private."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from src.operations_accounts import manual_republication_runtime_v6 as bridge

_spec=importlib.util.spec_from_file_location('_manual_v5_private_fixture',Path(__file__).with_name('test_manual_republication_runtime_v5.py'))
_support=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_support)
v2_case=_support.v2_case
v3_case=_support.v3_case
v4_case=_support.v4_case
v5_case=_support.case

FAILED='''import json
from pathlib import Path
from src.operations_accounts import manual_republication_runtime_v5 as runtime
def run_action(actor,resource,config,request,outdir):
 outdir.mkdir(parents=True,exist_ok=True)
 action=runtime._read(runtime.reference(outdir.parent/'ACTION_CLAIM.json'))
 prior=runtime._read(action['plan'])['prior']
 runtime._once(outdir/'FIELD_PROJECTION.json',{'schema':'manual_draft_field_projection/v5','location':{'origin':'https://creator.douyin.com','path':'/creator-micro/content/post/video'},'authorized_field_values_read':True,'unrelated_input_values_read':False})
 runtime._once(outdir/'DRAFT_FENCE.json',{'schema':'manual_existing_draft_fence/v5','selection_nonce':prior['selection_nonce'],'original_journal':prior['upload_journal'],
  'native_upload_proof':{'selection_nonce':prior['selection_nonce'],'diagnostic':prior['upload_route_baseline']},
  'video':{'origin':'https://creator.douyin.com','path':'/creator-micro/content/post/video','duration':prior['source_duration_seconds'],'visible_video_count':1,'ready_state':4},
  'checker_verified_claimed':False,'fresh_document_handle_claimed':False,'platform_media_sha_verified':False})
 runtime._once(outdir/'PREPARE_FAILURE.json',{'schema':'manual_existing_draft_failure/v5','reason_code':'draft_mutation_unknown','error_type':'RuntimeError',
  'metadata_mutation_dispatched':True,'file_selected':False,'navigation_performed':False,'submitted':False})
 raise RuntimeError('unknown earlier native result')
'''
FLOW='''import json
from pathlib import Path
def run_action(actor,resource,config,request,outdir):
 outdir.mkdir(parents=True,exist_ok=True)
 with (outdir/'REPAIRED_ONCE').open('x') as f:f.write('protocol metadata repair')
 metadata=json.loads(Path(config['metadata']['path']).read_text(encoding='utf-8'))
 return {'schema':'manual_republication_existing_draft/v6','action':'repair_existing_draft',
  'metadata_readback_matched':True,'hashtag_readback_verified':True,'submitted':False,'declaration_selected':False,
  'navigation_performed':False,'file_selected':False,'title_readback':{'content':metadata['title']},
  'description_readback':{'content':'\\u200b'+metadata['description']}}
'''

def put(path,value):
 path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');return bridge.reference(path)

@pytest.fixture
def case(v5_case,monkeypatch):
 c=v5_case;base=bridge.base
 c.paths_v5['flow_v5'].write_text(FAILED,encoding='utf-8');c.config['sources']['flow_v5']=bridge.reference(c.paths_v5['flow_v5'])
 cfg5=put(c.run/'CONFIG_V5.json',c.config);req5=put(c.run/'REQUEST_V5.json',dict(c.request,config=cfg5))
 oldplan=base.prepare(cfg5,req5,c.run/'failed_v5');put(base.ARM,{'schema':'manual_republication_runtime_arm/v5','plan':oldplan})
 assert base.install_if_armed()['status'].startswith('callback_registered')
 c.namespace['_poll_manual_windows'](c.actor,c.resource)
 assert base.status(oldplan)['status']=='outcome_unknown'
 monkeypatch.setattr(bridge,'ROOT',base.ROOT);monkeypatch.setattr(bridge,'RUN',c.run);monkeypatch.setattr(bridge,'ARM',c.run/'runtime_v6/ARM.json')
 paths=dict(base.SOURCE_PATHS)
 for key in ('runtime_v6','flow_v6'):
  path=base.ROOT/'src/operations_accounts'/f'{key}.py';path.write_text(FLOW if key=='flow_v6' else '# reviewed v6',encoding='utf-8');paths[key]=path
 monkeypatch.setattr(bridge,'SOURCE_PATHS',paths)
 cfg=dict(c.config,schema=bridge.CONFIG_SCHEMA,sources={k:bridge.reference(p) for k,p in paths.items()})
 cfgref=put(c.run/'CONFIG_V6.json',cfg);folder=Path(oldplan['path']).parent
 request=dict(schema=bridge.REQUEST_SCHEMA,config=cfgref,action='repair_existing_draft',prior_draft_plan=oldplan,
  prior_draft_action=bridge.reference(folder/'ACTION_CLAIM.json'),prior_unknown=bridge.reference(folder/'UNKNOWN.json'),
  prior_failure=bridge.reference(folder/'preparation/PREPARE_FAILURE.json'),field_projection=bridge.reference(folder/'preparation/FIELD_PROJECTION.json'),
  draft_fence=bridge.reference(folder/'preparation/DRAFT_FENCE.json'))
 return NS(**{**vars(c),'config':cfg,'config_ref':cfgref,'request':request,'request_ref':put(c.run/'REQUEST_V6.json',request),'paths_v6':paths})

def plan(c):return bridge.prepare(c.config_ref,c.request_ref,c.run/'repair_001')
def arm(c,ref):
 put(bridge.ARM,{'schema':'manual_republication_runtime_arm/v6','plan':ref})
 assert bridge.install_if_armed()['status'].startswith('callback_registered')
 c.namespace['_poll_manual_windows'](c.actor,c.resource)

def test_named_repair_once_keeps_failed_history_and_media_claims(case):
 before={p['path']:Path(p['path']).read_bytes() for p in [case.prior_claim,*[case.request[k] for k in bridge.PRIOR_FIELDS]]}
 manual=case.store.get(case.manual['command_id']);ref=plan(case);arm(case,ref)
 assert bridge.status(ref)['status']=='draft_prepared_no_submission'
 assert bridge.install_if_armed()['status']=='draft_prepared_no_submission'
 assert all(Path(p).read_bytes()==raw for p,raw in before.items()) and case.store.get(case.manual['command_id'])==manual

def test_unbound_prior_action_cannot_be_used(case):
 bad=put(case.run/'BAD_REQUEST.json',dict(case.request,prior_draft_action=case.prior_claim))
 with pytest.raises((ValueError,KeyError)):
  bridge.prepare(case.config_ref,bad,case.run/'bad')

def test_file_navigation_submit_intents_are_rejected(case):
 for index,extra in enumerate([{'action':'submit_once'},{'action':'resume_prepare_upload'},{'url':'https://example.org'}]):
  bad=put(case.run/f'bad_{index}.json',dict(case.request,**extra))
  with pytest.raises(ValueError,match='metadata_only'):bridge.prepare(case.config_ref,bad,case.run/f'badplan_{index}')

def test_failure_diagnostics_are_bound_without_raw_error_in_runtime_result(case):
 source='''
from src.operations_accounts import manual_republication_runtime_v6 as runtime
def run_action(actor,resource,config,request,outdir):
 outdir.mkdir(parents=True,exist_ok=True)
 runtime._once(outdir/'PREPARE_FAILURE.json',{'safe_error':{'error_type':'RuntimeError','message':'redacted','phase':'title_fill'}})
 raise RuntimeError('raw native secret must not appear')
'''
 case.paths_v6['flow_v6'].write_text(source,encoding='utf-8');case.config['sources']['flow_v6']=bridge.reference(case.paths_v6['flow_v6'])
 case.config_ref=put(case.run/'CONFIG_V6.json',case.config);case.request_ref=put(case.run/'REQUEST_V6.json',dict(case.request,config=case.config_ref))
 ref=plan(case);arm(case,ref)
 raw=(Path(ref['path']).parent/'UNKNOWN.json').read_text(encoding='utf-8');unknown=json.loads(raw)
 assert 'raw native secret' not in raw and bridge._read(unknown['diagnostics'])['safe_error']['message']=='redacted'
 assert bridge.install_if_armed()['status']=='outcome_unknown'
