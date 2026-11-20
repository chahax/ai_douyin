"""Four targeted private metadata-only continuation checks; no platform I/O."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from src.operations_accounts import manual_republication_runtime_v5 as bridge

_spec=importlib.util.spec_from_file_location('_manual_v4_private_fixture',Path(__file__).with_name('test_manual_republication_runtime_v4.py'))
_support=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_support)
v2_case=_support.v2_case
v3_case=_support.v3_case
v4_case=_support.case

AFTER_FILE='''
 diagnostic={'initial_route':'upload','current_route':'editor','generation':1,'routes':[{'route':'upload','generation':0,'event':'begin'},{'route':'editor','generation':1,'event':'route_change'}],'route_history_truncated':False}
 (outdir/'UPLOAD_JOURNAL.jsonl').write_text(json.dumps({'stage':'upload_check_transition_observed','selection_nonce':'a'*32,'proof':{'diagnostic':diagnostic}})+'\\n'+json.dumps({'stage':'upload_ui_diagnostic','event':'success_marker'})+'\\n',encoding='utf-8')
 runtime._once(outdir/'POST_UPLOAD_EDITOR.json',{'schema':'manual_editor_declaration_inventory/v1','location':{'origin':'https://creator.douyin.com','path':'/creator-micro/content/post/video'},'submission_performed':False,'declaration_selected_by_this_action':False})
 runtime._once(outdir/'PREPARE_FAILURE.json',{'schema':'manual_resume_failure/v4','reason_code':'resume_post_selection_unknown','cause_code':'prepare_field_not_unique','upload_attempted':True,'file_claim_created':True,'file_selection_dispatched':True,'submitted':False})
 raise RuntimeError('metadata field ambiguity')
'''
FLOW='''import json
from pathlib import Path
def run_action(actor,resource,config,request,outdir):
 outdir.mkdir(parents=True,exist_ok=True)
 with (outdir/'METADATA_ONCE').open('x') as f:f.write('synthetic metadata only')
 metadata=json.loads(Path(config['metadata']['path']).read_text(encoding='utf-8'))
 return {'schema':'manual_republication_existing_draft/v5','action':'prepare_existing_draft',
  'metadata_readback_matched':True,'hashtag_readback_verified':True,'submitted':False,'declaration_selected':False,
  'navigation_performed':False,'file_selected':False,'title_readback':{'content':metadata['title']},
  'description_readback':{'content':metadata['description']}}
'''

def put(path,value):
 path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');return bridge.reference(path)

@pytest.fixture
def case(v4_case,monkeypatch):
 c=v4_case;v4=bridge.v4
 c.paths_v4['flow_v4'].write_text(_support.FLOW.replace('# AFTER_SELECTION_CLAIM',AFTER_FILE),encoding='utf-8')
 c.config['sources']['flow_v4']=bridge.reference(c.paths_v4['flow_v4'])
 cfg4=put(c.run/'CONFIG_V4.json',c.config);req4=put(c.run/'REQUEST_V4.json',dict(c.request,config=cfg4))
 oldplan=v4.prepare(cfg4,req4,c.run/'failed_v4');put(v4.ARM,{'schema':'manual_republication_runtime_arm/v4','plan':oldplan})
 assert v4.install_if_armed()['status'].startswith('callback_registered')
 c.namespace['_poll_manual_windows'](c.actor,c.resource)
 assert v4.status(oldplan)['status']=='outcome_unknown' and v4.FILE_SELECTION_CLAIM.exists()
 monkeypatch.setattr(bridge,'ROOT',v4.ROOT);monkeypatch.setattr(bridge,'RUN',c.run);monkeypatch.setattr(bridge,'ARM',c.run/'runtime_v5/ARM.json')
 paths=dict(v4.SOURCE_PATHS)
 for key in ('runtime_v5','flow_v5'):
  path=v4.ROOT/'src/operations_accounts'/f'{key}.py';path.write_text(FLOW if key=='flow_v5' else '# reviewed v5',encoding='utf-8');paths[key]=path
 monkeypatch.setattr(bridge,'SOURCE_PATHS',paths)
 cfg=dict(c.config,schema=bridge.CONFIG_SCHEMA,sources={key:bridge.reference(p) for key,p in paths.items()})
 config_ref=put(c.run/'CONFIG_V5.json',cfg);folder=Path(oldplan['path']).parent
 request=dict(schema=bridge.REQUEST_SCHEMA,config=config_ref,action='prepare_existing_draft',prior_upload_plan=oldplan,
  prior_upload_action=bridge.reference(folder/'ACTION_CLAIM.json'),file_selection_claim=bridge.reference(v4.FILE_SELECTION_CLAIM),
  prior_unknown=bridge.reference(folder/'UNKNOWN.json'),prior_failure=bridge.reference(folder/'preparation/PREPARE_FAILURE.json'),
  post_upload_editor=bridge.reference(folder/'preparation/POST_UPLOAD_EDITOR.json'))
 return NS(**{**vars(c),'config':cfg,'config_ref':config_ref,'request':request,'request_ref':put(c.run/'REQUEST_V5.json',request),'paths_v5':paths})

def plan(c):return bridge.prepare(c.config_ref,c.request_ref,c.run/'draft_001')
def arm(c,ref):
 put(bridge.ARM,{'schema':'manual_republication_runtime_arm/v5','plan':ref})
 assert bridge.install_if_armed()['status'].startswith('callback_registered')
 c.namespace['_poll_manual_windows'](c.actor,c.resource)

def test_existing_uploaded_draft_metadata_once_preserves_prior_claims(case):
 before={p['path']:Path(p['path']).read_bytes() for p in [case.prior_claim,*[case.request[k] for k in bridge.PRIOR_FIELDS]]}
 manual=case.store.get(case.manual['command_id']);ref=plan(case)
 assert bridge._read(ref)['prior']['selection_nonce']=='a'*32
 arm(case,ref)
 assert bridge.status(ref)['status']=='draft_prepared_no_submission'
 assert bridge.install_if_armed()['status']=='draft_prepared_no_submission'
 assert all(Path(p).read_bytes()==raw for p,raw in before.items())
 assert case.store.get(case.manual['command_id'])==manual and not (case.run/'SELECTED').exists()

def test_cannot_borrow_old_zero_file_claim_as_uploaded_draft(case):
 bad=put(case.run/'BAD_REQUEST.json',dict(case.request,file_selection_claim=case.prior_claim))
 with pytest.raises(ValueError,match='original_file_claim'):
  bridge.prepare(case.config_ref,bad,case.run/'bad_plan')

def test_file_navigation_and_publish_actions_are_not_supported(case):
 for index,extra in enumerate([{'action':'resume_prepare_upload'},{'action':'submit_once'},{'url':'https://example.org'}]):
  bad=put(case.run/f'bad_{index}.json',dict(case.request,**extra))
  with pytest.raises(ValueError,match='metadata_only'):bridge.prepare(case.config_ref,bad,case.run/f'badplan_{index}')

def test_lost_metadata_ack_never_replays_or_reuploads(case):
 case.paths_v5['flow_v5'].write_text('def run_action(*a):raise RuntimeError("metadata acknowledgement lost")',encoding='utf-8')
 case.config['sources']['flow_v5']=bridge.reference(case.paths_v5['flow_v5'])
 case.config_ref=put(case.run/'CONFIG_V5.json',case.config);case.request_ref=put(case.run/'REQUEST_V5.json',dict(case.request,config=case.config_ref))
 ref=plan(case);arm(case,ref)
 assert bridge.status(ref)['status']=='outcome_unknown' and bridge.install_if_armed()['status']=='outcome_unknown'
 assert bridge.reference(case.request['file_selection_claim']['path'])==case.request['file_selection_claim']

def test_platform_zero_width_description_formatting_keeps_exact_text(case):
 case.paths_v5['flow_v5'].write_text(FLOW.replace("'content':metadata['description']", "'content':'\\u200b'+metadata['description']+'\\u200b'"),encoding='utf-8')
 case.config['sources']['flow_v5']=bridge.reference(case.paths_v5['flow_v5'])
 case.config_ref=put(case.run/'CONFIG_V5.json',case.config);case.request_ref=put(case.run/'REQUEST_V5.json',dict(case.request,config=case.config_ref))
 ref=plan(case);arm(case,ref)
 assert bridge.status(ref)['status']=='draft_prepared_no_submission'
