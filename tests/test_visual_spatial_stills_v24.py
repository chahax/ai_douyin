"""CPU tests with real files and native image-job preparation; no model/network."""
from pathlib import Path
import json,shutil,math
from copy import deepcopy
import pytest
from PIL import Image
from src.content_factory import visual_spatial_stills_v24 as s
from src.content_factory import visual_spatial_scene_v24 as scene
from src.content_factory import visual_image_jobs_v3 as jobs

def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v),encoding='utf-8');return p
@pytest.fixture
def prepared(tmp_path):
 source=tmp_path/'source';(source/'sources').mkdir(parents=True)
 for sid in ('S01','S02','S03','S04'):(source/'sources'/(sid+'.prompt.txt')).write_text(sid+' original source “exact line”',encoding='utf-8')
 spatial=tmp_path/'spatial';scene.prepare(spatial,source)
 handoff=spatial/'HANDOFF.json';h=s.read(handoff);plan=s.read(spatial/'SPATIAL_PLAN.json');render=spatial/'blender_fixture';render.mkdir()
 names=['room_front','room_side','room_reverse']+[sid+'_'+stage for sid in ('S01','S02','S03','S04') for stage in ('start','end')]+['S04_at_7'];files=[];rows=[]
 for name in names:
  path=render/(name+'.png');Image.new('RGB',(736,1312),'gray').save(path);files.append(s.bind(path));state=s._state(plan,name);sid=name.split('_')[0]
  camera=next((shot['camera_id'] for shot in plan['shots'] if shot['id']==sid),next(iter(plan['cameras'])))
  cam=plan['cameras'][camera];forward=scene.unit(scene.sub(cam['target'],cam['position']));right=scene.unit(scene.cross(forward,[0,0,1]));up=scene.cross(right,forward);world=[[right[k],up[k],-forward[k],cam['position'][k]] for k in range(3)]+[[0,0,0,1]];f=1/math.tan(math.radians(cam['vertical_fov_deg'])/2);projection=[[f*1312/736,0,0,0],[0,f,0,0],[0,0,-1,-.1],[0,0,-1,0]]
  rows.append(dict(name=name,camera_id=camera,visible_actor_ids=[who for who in s.CAST if state and state['actors'][who]['visible']],bread_holder=state['props']['bread_bag']['holder'] if state else None,camera_world_matrix=world,camera_projection_matrix=projection))
 fake_blender=tmp_path/'fixture_blender.exe';fake_blender.write_bytes(b'CPU test fixture, never executed');script=render/'script.py';script.write_text('# structural fixture only')
 metadata=write(render/'RENDER_METADATA.json',dict(plan_sha256=h['plan']['sha256'],engine='CYCLES',device='CPU',renders=rows))
 (render/'CONTACT.jpg').write_bytes(b'fixture contact');(render/'scene.blend').write_bytes(b'fixture scene')
 request=write(render/'REQUEST.json',dict(blender=s.bind(fake_blender),plan=h['plan'],script=s.bind(script)))
 result=write(render/'RESULT.json',dict(schema='spatial_blender_cpu_result/v24',device='CPU',model_posts=0,production_approved=False,request_sha256=jobs.file_sha(request),files=files,metadata=s.bind(metadata),contact=s.bind(render/'CONTACT.jpg'),scene=s.bind(render/'scene.blend')))
 refs=[]
 for who in s.CAST:
  image=tmp_path/(who+'.png');Image.new('RGB',(768,1024),'white').save(image);refs.append(dict(kind='character',entity_id=who,view='front',reference_id='character:'+who+':front',image=s.bind(image)))
 inputs=write(tmp_path/'INPUTS.json',dict(references=refs));authorization=write(tmp_path/'AUTH.json',dict(user_statement='Generate diagnostic versions',max_image_submissions=12,new_cloud_media_calls=0,publication=False))
 inp=tmp_path/'native_input';out=tmp_path/'native_output';inp.mkdir();out.mkdir();pause=tmp_path/'OLD_PAUSE.json';pause.write_text('{}')
 config=dict(config=dict(service_url='http://127.0.0.1:8190',input_root=str(inp),output_root=str(out),protected_pause_path=str(pause),gpu_lock_root='not_a_Config_field',width=736,base_workflow='not_a_Config_field',verify_service_paths=False))
 run=tmp_path/'stills';kwargs=dict(handoff=handoff,render_result=result,inputs=inputs,authorization=authorization,config=config)
 return run,kwargs

def test_real_file_prepare_whitelists_Config_and_preserves_old_pause(prepared):
 run,kw=prepared;r=s.prepare(run,**kw);p=s.read(run/'PLAN.json')
 assert r['model_posts']==0 and len(p['items'])==12
 assert 'gpu_lock_root' not in p['config'] and 'width' not in p['config']
 assert p['width']==736 and p['height']==1312 and p['steps']==4
 assert p['publication'] is False and p['production_approved'] is False

def test_duplicate_state_alias_and_departed_cast(prepared):
 run,kw=prepared;s.prepare(run,**kw);rows={x['id']:x for x in s.read(run/'PLAN.json')['items']}
 assert rows['S01_end']['alias_of']=='S01_start' and rows['S02_start']['alias_of']=='S01_start'
 assert rows['S04_end']['visible_cast']==['su_mo'] and len(rows['S04_end']['references'])==2
 assert len(rows['S01_start']['references'])==4 and len(rows['room_front']['references'])==1

def test_deterministic_prompt_explicit_holder_eyes_and_identity(prepared):
 run,kw=prepared;s.prepare(run,**kw);rows={x['id']:x for x in s.read(run/'PLAN.json')['items']}
 text=rows['S01_start']['prompt'];assert 'blue blocking figure' in text and 'gray buttoned shirt' in text and 'eyes closed' in text
 assert 'Ye Xijue' in text and 'transparent plastic bag' in text
 assert 'Ye Nan' not in rows['S04_end']['prompt'] and 'unoccupied' in rows['room_front']['prompt']

def test_actual_native_prepare_batch_real_staging_shared_loaders(prepared):
 run,kw=prepared;s.prepare(run,**kw);r=s.prepare_batch(run,'canary',['S01_start','S03_end']);folder=run/'batches/canary';p=s.read(folder/'PLAN.json');g=s.read(folder/'workflow_api.json')
 assert r['state']['status']=='prepared' and r['state']['prompt_id'] is None
 assert len([x for x in g.values() if x['class_type']=='UNETLoader'])==1
 assert len([x for x in g.values() if x['class_type']=='SaveImage'])==2
 assert len(p['inputs'])==5 and all(Path(x['staged_path']).is_file() for x in p['inputs'])
 jobs._inputs_ok(p)
 assert not (folder/'REQUEST.json').exists()

def test_alias_selection_rejected(prepared):
 run,kw=prepared;s.prepare(run,**kw)
 with pytest.raises(s.StillsError,match='canonical'):s.prepare_batch(run,'bad',['S01_end'])

def test_duplicate_reservation_prevents_second_native_branch(prepared):
 run,kw=prepared;s.prepare(run,**kw);s.prepare_batch(run,'first',['S01_start'])
 with pytest.raises(s.StillsError,match='already_reserved'):s.prepare_batch(run,'second',['S01_start'])

def test_native_unknown_claim_does_not_post(prepared):
 run,kw=prepared;s.prepare(run,**kw);s.prepare_batch(run,'first',['S01_start']);folder=run/'batches/first';write(folder/'CLAIM.json',dict(unknown=True))
 assert s.tick(run,'first')['status']=='outcome_unknown'
 assert not (folder/'REQUEST.json').exists() and not (folder/'RESPONSE.json').exists()

def test_native_failed_does_not_post(prepared):
 run,kw=prepared;s.prepare(run,**kw);s.prepare_batch(run,'first',['S01_start']);folder=run/'batches/first';state=s.read(folder/'STATE.json');state['status']='failed';write(folder/'STATE.json',state)
 assert s.tick(run,'first')['status']=='failed' and not (folder/'REQUEST.json').exists()

def test_paused_native_does_not_post(prepared):
 run,kw=prepared;s.prepare(run,**kw);s.prepare_batch(run,'first',['S01_start']);folder=run/'batches/first';jobs.set_paused(folder,True)
 assert s.tick(run,'first')['dispatch']=='paused_before_submit' and not (folder/'REQUEST.json').exists()

@pytest.mark.parametrize('target',['handoff','render_result','inputs','authorization'])
def test_bound_source_changes_rejected_before_batch(prepared,target):
 run,kw=prepared;s.prepare(run,**kw);Path(kw[target]).write_text('{}')
 with pytest.raises(s.StillsError,match='bound_file_changed'):s.prepare_batch(run,'first',['S01_start'])

def test_missing_renderer_receipt_rejected_no_plan(prepared):
 run,kw=prepared;Path(kw['render_result']).unlink()
 with pytest.raises(FileNotFoundError):s.prepare(run,**kw)
 assert not (run/'PLAN.json').exists()

def test_actual_render_cast_mismatch_rejected(prepared):
 run,kw=prepared;result=s.read(kw['render_result']);p=Path(result['metadata']['path']);m=s.read(p);m['renders'][3]['visible_actor_ids']=['su_mo'];write(p,m);result['metadata']=s.bind(p);write(kw['render_result'],result)
 with pytest.raises(s.StillsError,match='actual_cast'):s.prepare(run,**kw)

def test_canonical_reference_mapping_mismatch_rejected(prepared):
 run,kw=prepared;h=s.read(kw['handoff']);h['cast_mapping'][1]['identity_image']='character:su_mo:front';write(Path(kw['handoff']),h)
 with pytest.raises(s.StillsError,match='identity_mapping'):s.prepare(run,**kw)

def test_stage_pixel_change_rejected_before_batch(prepared):
 run,kw=prepared;s.prepare(run,**kw);p=s.read(run/'PLAN.json');Path(p['items'][3]['stage']['path']).write_bytes(b'changed')
 with pytest.raises(s.StillsError,match='bound_file_changed'):s.prepare_batch(run,'first',['S01_start'])

def test_changed_batch_plan_rejected(prepared):
 run,kw=prepared;s.prepare(run,**kw);s.prepare_batch(run,'first',['S01_start']);p=run/'batches/first/PLAN.json';v=s.read(p);v['config']['timeout']=1;write(p,v)
 with pytest.raises(s.StillsError,match='bound_file_changed'):s.tick(run,'first')

def test_real_native_completed_history_collect_and_candidate_receipt(prepared):
 run,kw=prepared;s.prepare(run,**kw);s.prepare_batch(run,'first',['S01_start','S03_end']);folder=run/'batches/first';p=s.read(folder/'PLAN.json');graph=s.read(folder/'workflow_api.json');pid='cpu_fixture_known_native_id'
 write(folder/'REQUEST.json',dict(prompt=graph));write(folder/'CLAIM.json',dict(graph_sha256=p['graph_sha256'],input_sha256=jobs.digest(p['inputs'])));write(folder/'RESPONSE.json',dict(prompt_id=pid))
 state=s.read(folder/'STATE.json');state.update(status='native_complete',prompt_id=pid);write(folder/'STATE.json',state);outputs={}
 for nid,node in graph.items():
  if node['class_type']=='SaveImage':
   relative=Path(node['inputs']['filename_prefix']+'_00001_.png');path=Path(p['config']['output_root'])/relative;path.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(736,1312),'gray').save(path)
   outputs[nid]=dict(images=[dict(filename=path.name,subfolder=relative.parent.as_posix(),type='output')])
 write(folder/'HISTORY.json',{pid:dict(prompt=[0,pid,graph],status=dict(completed=True,status_str='success'),outputs=outputs)})
 result=s.tick(run,'first');assert result['status']=='saved'
 candidates=s.read(folder/'CANDIDATES.json');assert [x['id'] for x in candidates['items']]==['S01_start','S03_end']
 assert candidates['production_approved'] is False and all(x['prompt_id']==pid for x in candidates['items'])
 assert len((run/'job_ids.txt').read_text().splitlines())==1
 s.tick(run,'first');assert len((run/'job_ids.txt').read_text().splitlines())==1

def skin_receipt(kw):
 result=s.read(kw['render_result']);folder=Path(kw['render_result']).parent;request=s.read(folder/'REQUEST.json');contract=scene.material_contract();request['material_contract']=contract;write(folder/'REQUEST.json',request)
 meta=s.read(result['metadata']['path']);meta['material_contract']=contract
 for row in meta['renders']:
  row['actor_material_bindings']=[]
  for who in row['visible_actor_ids']:
   for part in ('head','nose_direction','arm','torso','leg'):
    row['actor_material_bindings'].append(dict(object=who+'_'+part,material=contract['actors'][who][part],base_color=contract['skin']['base_color'] if part in ('head','nose_direction','arm') else contract['actors'][who]['shirt_base_color']))
 write(Path(result['metadata']['path']),meta);result['metadata']=s.bind(result['metadata']['path']);result['request_sha256']=jobs.file_sha(folder/'REQUEST.json');result['material_policy']=scene.SKIN_MATERIALS;result['skin_material_check']=scene.validate_skin_metadata(meta);write(kw['render_result'],result)
 return result

def test_explicit_skin_material_contract_and_actual_staging(prepared):
 run,kw=prepared;skin_receipt(kw);s.prepare(run,**kw,require_material_policy=scene.SKIN_MATERIALS);p=s.read(run/'PLAN.json');assert p['material_contract']==scene.material_contract()
 byid={x['id']:x for x in p['items']};text=byid['S01_start']['prompt']
 assert 'teal clothing marker' in text and 'teal blocking figure' not in text
 assert 'visible architecture and furniture' in text and 'two windows' not in text and 'doorway' not in text
 assert 'Every visible face, head and hand has natural human skin' in text
 assert s.prepare_batch(run,'canary',['S01_start','S03_end'])['global_reserved_branches']==2

def test_legacy_material_cannot_be_claimed_as_skin(prepared):
 run,kw=prepared
 with pytest.raises(s.StillsError,match='skin_material_receipt'):s.prepare(run,**kw,require_material_policy=scene.SKIN_MATERIALS)

def test_null_skin_verification_cannot_pass(prepared):
 run,kw=prepared;r=skin_receipt(kw);r['skin_material_check']=None;write(kw['render_result'],r)
 with pytest.raises(s.StillsError,match='skin_material_verification'):s.prepare(run,**kw,require_material_policy=scene.SKIN_MATERIALS)

def test_colored_head_actual_metadata_rejected(prepared):
 run,kw=prepared;r=skin_receipt(kw);meta=s.read(r['metadata']['path']);obj=next(x for row in meta['renders'] for x in row['actor_material_bindings'] if x['object']=='ye_nan_head');obj['base_color']=[0,.5,.5];write(Path(r['metadata']['path']),meta);r['metadata']=s.bind(r['metadata']['path']);write(kw['render_result'],r)
 with pytest.raises(scene.SpatialError,match='color_changed'):s.prepare(run,**kw,require_material_policy=scene.SKIN_MATERIALS)

def test_new_namespace_does_not_reset_global_image_allowance(prepared):
 run,kw=prepared;a=s.read(kw['authorization']);a['max_image_submissions']=3;write(Path(kw['authorization']),a)
 s.prepare(run,**kw);s.prepare_batch(run,'first',['S01_start','S03_end']);new=run.with_name('new_stills_revision');s.prepare(new,**kw)
 with pytest.raises(s.StillsError,match='global_image_branch_budget'):s.prepare_batch(new,'second',['S01_start','S03_end'])
 assert not (new/'batches/second/CLAIM.json').exists()

def test_global_budget_audits_previous_unknown_claim(prepared):
 run,kw=prepared;a=s.read(kw['authorization']);a['max_image_submissions']=1;write(Path(kw['authorization']),a);s.prepare(run,**kw);s.prepare_batch(run,'first',['S01_start']);write(run/'batches/first/CLAIM.json',dict(unknown=True))
 new=run.with_name('new_stills_revision');s.prepare(new,**kw)
 with pytest.raises(s.StillsError,match='global_image_branch_budget'):s.prepare_batch(new,'second',['S03_end'])
 budget=s._global_budget(run,s.read(run/'PLAN.json'));assert budget['reserved_branches']==1 and budget['batches'][0]['claim_preserved'] is True and budget['batches'][0]['status']=='outcome_unknown'
 assert budget['known_native_branches']==0 and budget['unknown_claim_branches']==1 and budget['saved_branches']==0

def test_global_budget_admission_retains_previous_batch(prepared):
 run,kw=prepared;s.prepare(run,**kw);s.prepare_batch(run,'first',['S01_start','S03_end']);new=run.with_name('new_stills_revision')
 old_renderer=Path(kw['render_result']).parent;new_renderer=old_renderer.with_name('skin_renderer_fixture');shutil.copytree(old_renderer,new_renderer);newkw=dict(kw,render_result=new_renderer/'RESULT.json')
 receipt=s.read(newkw['render_result']);receipt['metadata']=s.bind(new_renderer/'RENDER_METADATA.json');write(newkw['render_result'],receipt);skin_receipt(newkw)
 s.prepare(new,**newkw,require_material_policy=scene.SKIN_MATERIALS);r=s.prepare_batch(new,'skin',['S01_start','S03_end']);admission=s.read(new/'batches/skin/BUDGET_ADMISSION.json')
 assert r['global_reserved_branches']==4 and admission['reserved_after']==4 and admission['prior_batches'][0]['branches']==2
 budget=s._global_budget(new,s.read(new/'PLAN.json'));assert budget['known_native_branches']==0 and budget['unsubmitted_reserved_branches']==4 and budget['saved_branches']==0
 s._load(run)

def test_legacy_prompt_replay_unchanged_with_new_optional_contract(prepared):
 run,kw=prepared;s.prepare(run,**kw);p=s.read(run/'PLAN.json')
 for row in p['items']:assert row['prompt']==s._prompt(row['id'],row['state'],row['visible_cast'],None)

def test_screen_slot_projection_matches_independent_design_projector(prepared):
 run,kw=prepared;skin_receipt(kw);s.prepare(run,**kw,reference_packing=s.SCREEN_PACKING);p=s.read(run/'PLAN.json');spatial=s.read(p['spatial_plan']['path'])
 for item in p['items']:
  slots=item['reference_slots'];assert slots[0]['image_number']==1 and slots[0]['kind']=='stage'
  people=slots[1:];assert [x['screen_x'] for x in people]==sorted(x['screen_x'] for x in people)
  for person in people:
   projected=scene.project(person['world_head_center'],spatial['cameras'][item['render']['camera_id']]);assert person['screen_x']==pytest.approx(projected['uv'][0]) and person['screen_y']==pytest.approx(projected['uv'][1])

def test_screen_slots_reference_order_prompt_and_real_staging(prepared):
 run,kw=prepared;skin_receipt(kw);s.prepare(run,**kw,reference_packing=s.SCREEN_PACKING);p=s.read(run/'PLAN.json')
 for item in p['items']:
  order=[x['entity_id'] for x in item['reference_slots'][1:]];assert order==[x['entity_id'] for x in item['references'][1:]]
  assert set(order)==set(item['visible_cast'])
  for slot in item['reference_slots'][1:]:assert f'reference image {slot["image_number"]}' in item['prompt']
 s.prepare_batch(run,'canary',['S01_start','S03_end']);g=s.read(run/'batches/canary/workflow_api.json')
 for name in ('S01_start','S03_end'):
  item=next(x for x in p['items'] if x['id']==name)
  for index,who in enumerate([x['entity_id'] for x in item['references'][1:]],1):assert g[name+'__image_'+str(index)]['inputs']['image'].endswith('cast_'+who+'.png')

def test_new_packing_keeps_seeds_geometry_states_and_legacy_prompt_replay(prepared):
 run,kw=prepared;skin_receipt(kw);s.prepare(run,**kw);old=s.read(run/'PLAN.json');new=run.with_name('screen_stills');s.prepare(new,**kw,reference_packing=s.SCREEN_PACKING);p=s.read(new/'PLAN.json')
 for a,b in zip(old['items'],p['items']):
  assert a['state']==b['state'] and a['render']==b['render'] and a['stage']==b['stage'] and a['seed']==b['seed']
  assert a['prompt']==s._prompt(a['id'],a['state'],a['visible_cast'],old['material_contract'])

def test_screen_packing_requires_verified_skin_receipt(prepared):
 run,kw=prepared
 with pytest.raises(s.StillsError,match='verified_skin_stage'):s.prepare(run,**kw,reference_packing=s.SCREEN_PACKING)

def test_invalid_actual_camera_projection_rejected(prepared):
 run,kw=prepared;r=skin_receipt(kw);meta=s.read(r['metadata']['path']);meta['renders'][3]['camera_world_matrix'][0][0]=None;write(Path(r['metadata']['path']),meta);r['metadata']=s.bind(r['metadata']['path']);write(kw['render_result'],r)
 with pytest.raises(s.StillsError,match='finite_actual_camera'):s.prepare(run,**kw,reference_packing=s.SCREEN_PACKING)
