"""Small resume protocol checks; all Store/media/flow data are private fixtures."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from src.operations_accounts import manual_republication_runtime_v4 as bridge

_spec=importlib.util.spec_from_file_location('_manual_v3_private_fixture',Path(__file__).with_name('test_manual_republication_runtime_v3.py'))
_support=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_support)
v2_case=_support.v2_case
v3_case=_support.case

OBSERVE='''import json
from pathlib import Path
def run_action(actor,resource,config,request,outdir):
 return {'schema':'manual_republication_observation/v3','action':'observe_current','uploaded':False,'submitted':False,
 'input_performed':False,'navigation_performed':False,'file_selected':False,'owner_id':actor.owner_id,
 'generation':actor.generation,'tab_id':config['tab_id'],'location':{'origin':'https://www.douyin.com','path':'/user/self'},
 'observed_public_uids':[json.loads(Path(config['authority']['path']).read_text())['expected_public_uid']],
 'stable_render_observed':True,'same_page_rendered_expected_uid_observed':True}
'''
FLOW='''import json,time,threading
from pathlib import Path
from src.operations_accounts import manual_republication_runtime_v4 as runtime
def run_action(actor,resource,config,request,outdir):
 outdir.mkdir(parents=True,exist_ok=True)
 metadata=json.loads(Path(config['metadata']['path']).read_text(encoding='utf-8'))
 action=runtime.reference(outdir.parent/'ACTION_CLAIM.json')
 proof={'schema':'manual_file_selection_preflight/v4','action_claim':action,'media':metadata['media'],
  'owner_id':actor.owner_id,'generation':actor.generation,'tab_id':config['tab_id'],'actor_thread_id':threading.get_ident(),
  'observed_at':time.time(),'identity':{'verified':True,'actual_public_uid':'7589','observed_at':time.time()},
  'preselection':{'schema':'manual_upload_preselection/v1','origin':'https://creator.douyin.com',
   'path':'/creator-micro/content/upload','file_count':1,'visible_file_count':1,'upload_button_count':1,'editor_count':0,'file_disabled':False}}
 evidence=runtime._once(outdir/'FILE_SELECTION_PREFLIGHT.json',proof)
 # BEFORE_SELECTION
 ref=runtime.claim_file_selection(actor,resource,config,request,outdir,metadata['media'],evidence)
 # AFTER_SELECTION_CLAIM
 with (Path(config['authority']['path']).parent/'SELECTED').open('x') as f:f.write('protocol-only marker')
 runtime.validate_live(actor,resource,config)
 return {'schema':'manual_republication_prepare_upload/v4','action':'resume_prepare_upload','file_selection_claim':ref,
  'upload_ready':True,'uploaded':True,'upload_attempted':True,'upload_completion_verified':True,
  'metadata_readback_matched':True,'hashtag_readback_verified':True,'submitted':False,'declaration_selected':False,
  'title_readback':{'content':metadata['title']},'description_readback':{'content':metadata['description']}}
'''

def put(path,value):
 path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');return bridge.reference(path)

@pytest.fixture
def case(v3_case,monkeypatch):
 c=v3_case;v3=bridge.v3
 c.paths_v3['flow_v3'].write_text(OBSERVE,encoding='utf-8');c.config['sources']['flow_v3']=bridge.reference(c.paths_v3['flow_v3'])
 config3=put(c.run/'CONFIG_V3.json',c.config);request3=put(c.run/'REQUEST_V3.json',dict(c.request,config=config3))
 oldplan=v3.prepare(config3,request3,c.run/'observed_v3')
 put(v3.ARM,{'schema':'manual_republication_runtime_arm/v3','plan':oldplan})
 assert v3.install_if_armed()['status'].startswith('callback_registered')
 c.namespace['_poll_manual_windows'](c.actor,c.resource)
 observation=v3.status(oldplan)['result']
 monkeypatch.setattr(bridge,'ROOT',v3.ROOT);monkeypatch.setattr(bridge,'RUN',c.run)
 monkeypatch.setattr(bridge,'ARM',c.run/'runtime_v4/ARM.json');monkeypatch.setattr(bridge,'FILE_SELECTION_CLAIM',c.run/'FILE_SELECTION_CLAIM.json')
 paths=dict(v3.SOURCE_PATHS)
 for name in ('runtime_v4','flow_v4'):
  path=v3.ROOT/'src/operations_accounts'/f'{name}.py';path.write_text(FLOW if name=='flow_v4' else '# reviewed v4',encoding='utf-8');paths[name]=path
 monkeypatch.setattr(bridge,'SOURCE_PATHS',paths)
 config=dict(c.config,schema=bridge.CONFIG_SCHEMA,sources={k:bridge.reference(p) for k,p in paths.items()})
 config_ref=put(c.run/'CONFIG_V4.json',config)
 request=dict(c.request,schema=bridge.REQUEST_SCHEMA,config=config_ref,action='resume_prepare_upload',observation=observation)
 request_ref=put(c.run/'REQUEST_V4.json',request)
 return NS(**{**vars(c),'config':config,'config_ref':config_ref,'request':request,'request_ref':request_ref,'paths_v4':paths})

def prepare(c,name='resume_001'):
 return bridge.prepare(c.config_ref,c.request_ref,c.run/name)

def arm(c,ref):
 put(bridge.ARM,{'schema':'manual_republication_runtime_arm/v4','plan':ref})
 assert bridge.install_if_armed()['status'].startswith('callback_registered')
 c.namespace['_poll_manual_windows'](c.actor,c.resource)

def rewrite_flow(c,source):
 c.paths_v4['flow_v4'].write_text(source,encoding='utf-8');c.config['sources']['flow_v4']=bridge.reference(c.paths_v4['flow_v4'])
 c.config_ref=put(c.run/'CONFIG_V4.json',c.config);c.request_ref=put(c.run/'REQUEST_V4.json',dict(c.request,config=c.config_ref))

def test_late_global_selection_once_and_cross_directory_no_second_slot(case):
 old=Path(case.prior_claim['path']).read_bytes();manual=case.store.get(case.manual['command_id'])
 first,second=prepare(case),prepare(case,'other_request')
 assert not bridge.FILE_SELECTION_CLAIM.exists()
 arm(case,first)
 assert bridge.status(first)['status']=='prepared_no_submission'
 assert (case.run/'SELECTED').exists() and Path(case.prior_claim['path']).read_bytes()==old
 assert case.store.get(case.manual['command_id'])==manual
 assert bridge.status(second)['status']=='file_selection_slot_already_claimed'
 with pytest.raises(ValueError,match='slot_already_claimed'):prepare(case,'third')

@pytest.mark.parametrize('where,claimed',[('BEFORE_SELECTION',False),('AFTER_SELECTION_CLAIM',True)])
def test_nav_failure_preserves_media_slot_but_after_claim_never_reselects(case,where,claimed):
 rewrite_flow(case,FLOW.replace('# '+where,"raise RuntimeError('lost acknowledgement')"))
 ref=prepare(case);arm(case,ref)
 assert bridge.status(ref)['status']=='outcome_unknown'
 assert bridge.FILE_SELECTION_CLAIM.exists() is claimed
 assert bridge.install_if_armed()['status']=='outcome_unknown'
 assert not (case.run/'SELECTED').exists()
 if claimed:
  with pytest.raises(ValueError,match='slot_already_claimed'):prepare(case,'newdir')

def test_incomplete_native_file_surface_cannot_reserve_media_slot(case):
 rewrite_flow(case,FLOW.replace("'visible_file_count':1","'visible_file_count':0"))
 ref=prepare(case);arm(case,ref)
 assert bridge.status(ref)['status']=='outcome_unknown'
 assert not bridge.FILE_SELECTION_CLAIM.exists() and not (case.run/'SELECTED').exists()

def test_other_observation_or_old_claim_cannot_be_borrowed(case):
 request=dict(case.request,observation=case.prior_claim)
 bad=put(case.run/'WRONG_OBSERVATION.json',request)
 with pytest.raises((ValueError,KeyError)):
  bridge.prepare(case.config_ref,bad,case.run/'bad_observation')
 assert not bridge.FILE_SELECTION_CLAIM.exists()
