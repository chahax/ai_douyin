"""Two exact-contract receiver regressions; all history and stores are private."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from src.operations_accounts import manual_republication_runtime_v7 as bridge

_spec=importlib.util.spec_from_file_location('_manual_v6_private_fixture',Path(__file__).with_name('test_manual_republication_runtime_v6.py'))
_support=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_support)
v2_case=_support.v2_case
v3_case=_support.v3_case
v4_case=_support.v4_case
v5_case=_support.v5_case
v6_case=_support.case

FAILED='''from src.operations_accounts import manual_republication_runtime_v6 as runtime
def run_action(actor,resource,config,request,outdir):
 outdir.mkdir(parents=True,exist_ok=True)
 runtime._once(outdir/'INITIAL_FIELD_PROJECTION.json',{'schema':'manual_draft_field_projection/v5','location':{'origin':'https://creator.douyin.com','path':'/creator-micro/content/post/video'},'authorized_field_values_read':True,'unrelated_input_values_read':False})
 screenshot=outdir/'FAILURE_SCREENSHOT.png';screenshot.write_bytes(b'private protocol screenshot bytes')
 runtime._once(outdir/'PREPARE_FAILURE.json',{'schema':'manual_existing_draft_failure/v6','reason_code':'repair_editor_unconfirmed','cause_code':'draft_field_not_unique',
  'metadata_mutation_dispatched':False,'file_selected':False,'navigation_performed':False,'submitted':False,
  'failure_capture':{'screenshot':{'status':'saved','file':runtime.reference(screenshot)}}})
 raise RuntimeError('stable editor needs explicit continuation')
'''
FLOW='''import json
from pathlib import Path
def run_action(actor,resource,config,request,outdir):
 outdir.mkdir(parents=True,exist_ok=True)
 with (outdir/'COMPLETED_ONCE').open('x') as f:f.write('protocol only')
 metadata=json.loads(Path(config['metadata']['path']).read_text(encoding='utf-8'))
 return {'schema':'manual_republication_existing_draft/v7','action':'complete_existing_form','metadata_readback_matched':True,'hashtag_readback_verified':True,
  'submitted':False,'declaration_selected':False,'navigation_performed':False,'file_selected':False,
  'title_readback':{'content':metadata['title']},'description_readback':{'content':'\\u200b'+metadata['description']}}
'''

def put(path,value):
 path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');return bridge.reference(path)

@pytest.fixture
def case(v6_case,monkeypatch):
 c=v6_case;base=bridge.base
 c.paths_v6['flow_v6'].write_text(FAILED,encoding='utf-8');c.config['sources']['flow_v6']=bridge.reference(c.paths_v6['flow_v6'])
 cfg6=put(c.run/'CONFIG_V6.json',c.config);req6=put(c.run/'REQUEST_V6.json',dict(c.request,config=cfg6))
 oldplan=base.prepare(cfg6,req6,c.run/'failed_v6');put(base.ARM,{'schema':'manual_republication_runtime_arm/v6','plan':oldplan})
 assert base.install_if_armed()['status'].startswith('callback_registered')
 c.namespace['_poll_manual_windows'](c.actor,c.resource)
 assert base.status(oldplan)['status']=='outcome_unknown'
 monkeypatch.setattr(bridge,'ROOT',base.ROOT);monkeypatch.setattr(bridge,'RUN',c.run);monkeypatch.setattr(bridge,'ARM',c.run/'runtime_v7/ARM.json')
 paths=dict(base.SOURCE_PATHS)
 for key in ('runtime_v7','flow_v7'):
  path=base.ROOT/'src/operations_accounts'/f'{key}.py';path.write_text(FLOW if key=='flow_v7' else '# reviewed v7',encoding='utf-8');paths[key]=path
 monkeypatch.setattr(bridge,'SOURCE_PATHS',paths)
 cfg=dict(c.config,schema=bridge.CONFIG_SCHEMA,sources={k:bridge.reference(p) for k,p in paths.items()})
 cfgref=put(c.run/'CONFIG_V7.json',cfg);folder=Path(oldplan['path']).parent
 request=dict(schema=bridge.REQUEST_SCHEMA,config=cfgref,action='complete_existing_form',prior_repair_plan=oldplan,prior_repair_action=bridge.reference(folder/'ACTION_CLAIM.json'),
  prior_unknown=bridge.reference(folder/'UNKNOWN.json'),prior_failure=bridge.reference(folder/'preparation/PREPARE_FAILURE.json'),
  initial_field_projection=bridge.reference(folder/'preparation/INITIAL_FIELD_PROJECTION.json'),failure_screenshot=bridge.reference(folder/'preparation/FAILURE_SCREENSHOT.png'))
 return NS(**{**vars(c),'config':cfg,'config_ref':cfgref,'request':request,'request_ref':put(c.run/'REQUEST_V7.json',request)})

def test_actual_completion_receiver_exact_contract_and_old_evidence_preserved(case):
 before={p['path']:Path(p['path']).read_bytes() for p in [case.prior_claim,*[case.request[k] for k in bridge.PRIOR_FIELDS]]}
 ref=bridge.prepare(case.config_ref,case.request_ref,case.run/'form_001')
 put(bridge.ARM,{'schema':'manual_republication_runtime_arm/v7','plan':ref})
 assert bridge.install_if_armed()['status'].startswith('callback_registered')
 case.namespace['_poll_manual_windows'](case.actor,case.resource)
 assert bridge.status(ref)['status']=='draft_prepared_no_submission'
 assert bridge.install_if_armed()['status']=='draft_prepared_no_submission'
 assert all(Path(p).read_bytes()==raw for p,raw in before.items())

def test_unbound_failure_screenshot_or_publication_request_rejected(case):
 bad=put(case.run/'BAD_SCREENSHOT.json',dict(case.request,failure_screenshot=case.prior_claim))
 with pytest.raises(ValueError,match='original_bound_editor_failure'):
  bridge.prepare(case.config_ref,bad,case.run/'bad_screen')
 bad=put(case.run/'BAD_ACTION.json',dict(case.request,action='submit_once'))
 with pytest.raises(ValueError,match='metadata_only'):
  bridge.prepare(case.config_ref,bad,case.run/'bad_action')
