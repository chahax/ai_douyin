"""Frozen spatial blocking -> local Klein still candidates, never approved guides.

Preparation is file-only. Execution uses the original native image-job receipts;
known IDs are collected, unknown/failed jobs are not submitted again.
"""
from pathlib import Path
from copy import deepcopy
import json,time,math
from PIL import Image
from . import visual_image_jobs_v3 as jobs
from . import visual_spatial_scene_v24 as scene
from . import visual_opening_frame as opening

SCHEMA='spatial_photoreal_stills/v24'
PREFIX='spatial_stills_v24'
ROOT=Path(__file__).resolve().parents[2]
CAST=('su_mo','ye_nan','ye_xijue')
DESCRIPTIONS={
 'su_mo':('blue','Su Mo, an adult Chinese father wearing a dark jacket over a gray buttoned shirt and dark trousers'),
 'ye_nan':('teal','Ye Nan, the older Chinese boy wearing a gray collared polo shirt and dark long trousers'),
 'ye_xijue':('orange','Ye Xijue, the younger Chinese boy wearing a beige round-neck T-shirt and gray shorts'),
}
class StillsError(ValueError):pass
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def bind(p):return dict(path=str(Path(p).resolve()),sha256=jobs.file_sha(p))
def check(v):
 if set(v)!={'path','sha256'} or bind(v['path'])!=v:raise StillsError('bound_file_changed')
 return Path(v['path'])
def _config(value):
 # Never pass the H3 superset (gpu_lock_root, width, base_workflow...) to Config.
 source=value.get('config',value)
 keys=('service_url','input_root','output_root','protected_pause_path','timeout','verify_service_paths')
 selected={k:source[k] for k in keys if k in source};selected['allowed_prefix']=PREFIX
 return jobs.Config(**selected).normalized()
def _state(plan,name):
 if name.startswith('room_'):return None
 for shot in plan['shots']:
  if name==shot['id']+'_start':return opening.render_state(shot,shot['start_state'])
  if name==shot['id']+'_end':return shot['end_state']
  for intermediate in shot.get('intermediate_states',[]):
   if name==shot['id']+'_at_'+str(intermediate['segment_seconds']):return intermediate['state']
 raise StillsError('unknown_render_state')
SCREEN_PACKING='screen_order/v26'
def _screen_slots(plan,state,render):
 """Project design head centers with the actual Blender camera matrices.

 This associates blocking positions with slots, not faces with identities.
 IDs and metric staging positions come from the immutable source design.
 """
 if state is None:return []
 world=render['camera_world_matrix'];projection=render['camera_projection_matrix']
 if any(len(m)!=4 or any(len(row)!=4 for row in m) for m in (world,projection)):raise StillsError('actual_camera_matrix_shape_required')
 if not all(type(v) in (int,float) and math.isfinite(v) for m in (world,projection) for row in m for v in row):raise StillsError('finite_actual_camera_matrix_required')
 if any(abs(world[3][i]-v)>1e-6 for i,v in enumerate((0,0,0,1))):raise StillsError('rigid_actual_camera_required')
 if any(abs(sum(world[k][i]*world[k][j] for k in range(3))-(1 if i==j else 0))>1e-5 for i in range(3) for j in range(3)):raise StillsError('rigid_actual_camera_required')
 specs={a['id']:a for a in plan['actors']};rows=[]
 for who in CAST:
  a=state['actors'][who]
  if not a['visible']:continue
  x,y,z=a['position'];h=specs[who]['design_height'];pose=a['pose']
  head=[x,y+.58,z+.27] if pose=='lying' else [x,y,z+h*(.63 if pose=='sitting' else .56 if pose=='kneeling' else 1.)-.13]
  camera=[sum(world[k][i]*(head[k]-world[k][3]) for k in range(3)) for i in range(3)]+[1]
  clip=[sum(projection[i][k]*camera[k] for k in range(4)) for i in range(4)]
  if -camera[2]<=0 or clip[3]<=0:raise StillsError('named_head_behind_actual_camera')
  u=(clip[0]/clip[3]+1)/2;v=(1-clip[1]/clip[3])/2
  rows.append(dict(entity_id=who,screen_x=u,screen_y=v,camera_depth=-camera[2],world_head_center=head,derived_from='source head geometry + actual Blender camera world/projection matrices; not face recognition',clothing_marker=DESCRIPTIONS[who][0]))
 rows.sort(key=lambda x:(x['screen_x'],CAST.index(x['entity_id'])))
 for index,row in enumerate(rows,2):row.update(image_number=index,screen_order=index-1)
 return rows
def _prompt(name,state,visible,material_contract=None,screen_slots=None,*,opening_frame=None):
 opening=('Create one photorealistic live-action film still from reference image 1. '
 'Preserve its camera viewpoint, perspective, room proportions and the screen positions of its bed, small wooden table, doorway and two windows. '
 'Use worn gray plaster, an aged concrete floor, brown wooden furniture, subdued gray-brown bedding and natural window light in this modest Chinese home. ')
 if material_contract is not None:
  opening=('Create one photorealistic live-action film still from reference image 1. '
   'Preserve its camera viewpoint, perspective, room proportions and the visible architecture and furniture in their current screen positions. '
   'Use worn gray plaster, an aged concrete floor, brown wooden furniture, subdued gray-brown bedding and natural window light in this modest Chinese home. ')
 if state is None:return opening+'The room is unoccupied. Present the complete image as one continuous photographic frame.'
 instruction=''
 if opening_frame is not None:
  from .visual_opening_frame import still_instruction
  instruction=still_instruction(opening_frame)
 text=opening+instruction+f'The frame contains {len(visible)} named people at the blocking positions in image 1. '
 ordered=[x['entity_id'] for x in screen_slots] if screen_slots is not None else visible
 for index,who in enumerate(ordered,2):
  color,description=DESCRIPTIONS[who];a=state['actors'][who]
  if screen_slots is not None:
   labels=['leftmost','middle','rightmost'] if len(ordered)==3 else ['leftmost','rightmost'] if len(ordered)==2 else ['visible']
   text+=f'The {labels[index-2]} figure in image 1, identified by its {color} clothing marker, represents {description}; use reference image {index} for this named person\'s face, hair and final clothing. Retain this figure\'s blocked body position and relative height in image 1. '
  elif material_contract is not None:
   text+=f'The figure with the {color} clothing marker represents {description}; use reference image {index} for this person\'s face, hair, body appearance and final clothing. '
  else:text+=f'The {color} blocking figure represents {description}; use reference image {index} for this person\'s face, hair, body appearance and clothing. '
  pose={'lying':'lying on the bed','sitting':'sitting at the bed edge','standing':'standing','kneeling':'kneeling on the floor'}[a['pose']]
  text+=f'{description.split(",")[0]} is {pose}, eyes {a["eyes"]}. '
  show_hands=opening_frame is None or 'hands' in opening_frame['camera_beat']['actors'][who]['visible_parts']
  if show_hands:
   if who==state['props']['bread_bag']['holder']:
    text+='This person holds the single bread portion enclosed in a transparent plastic bag securely with natural hands. '
   else:text+='This person has empty hands. '
 if material_contract is not None:
  text+='Clothing marker colors identify the blocked body positions. Every visible face, head and hand has natural human skin matching the named person\'s reference photograph. '
  text+=('Render the photographed visible body parts as natural live-action anatomy with the corresponding reference clothing, within the specified shot framing. '
         if opening_frame is not None else 'Render each person as a complete live-action human with the corresponding reference clothing. ')
 else:text+='The colored blocking figures are identity and position markers; render natural human skin and the corresponding reference clothing. '
 text+=('Realize the photographed anatomy and source-established pose within the specified shot framing. '
        if opening_frame is not None else 'Realize hand grips and arm poses according to the named bread holder while retaining the blocked body positions. ')
 text+='Present a single coherent photographic frame with natural facial expressions and anatomy.'
 return text
def _source(handoff,render_result,inputs,authorization,require_material_policy=None):
 h=read(handoff);r=read(render_result);i=read(inputs);a=read(authorization)
 if h.get('schema')!='spatial_reference_handoff/v24' or h.get('production_approved') is not False or h.get('publication') is not False:raise StillsError('explicit_spatial_handoff_required')
 plan=read(check(h['plan']));scene.validate(plan)
 if (r.get('schema')!='spatial_blender_cpu_result/v24' or r.get('device')!='CPU' or r.get('model_posts')!=0 or r.get('production_approved') is not False):raise StillsError('actual_cpu_blender_receipt_required')
 request=read(Path(render_result).parent/'REQUEST.json')
 if jobs.file_sha(Path(render_result).parent/'REQUEST.json')!=r['request_sha256'] or request['plan']!=h['plan']:raise StillsError('renderer_source_plan_changed')
 for key in ('blender','plan','script'):check(request[key])
 for row in r['files']+[r[k] for k in ('metadata','contact','scene')]:check(row)
 meta=read(r['metadata']['path'])
 if meta.get('plan_sha256')!=h['plan']['sha256'] or meta.get('engine')!='CYCLES' or meta.get('device')!='CPU':raise StillsError('renderer_actual_plan_changed')
 material=request.get('material_contract')
 if require_material_policy is not None and require_material_policy!=scene.SKIN_MATERIALS:raise StillsError('unsupported_material_policy')
 if material is not None or require_material_policy is not None:
  if material!=scene.material_contract() or meta.get('material_contract')!=material or r.get('material_policy')!=scene.SKIN_MATERIALS:raise StillsError('explicit_skin_material_receipt_required')
  checked=scene.validate_skin_metadata(meta)
  if r.get('skin_material_check')!=checked or checked.get('skin_materials_verified') is not True:raise StillsError('actual_skin_material_verification_required')
 if not a.get('user_statement') or a.get('max_image_submissions',0)<1 or a.get('new_cloud_media_calls')!=0 or a.get('publication') is not False:raise StillsError('local_image_authorization_required')
 refs={x['entity_id']:x for x in i['references'] if x['kind']=='character' and x['view']=='front'}
 if set(refs)!=set(CAST):raise StillsError('three_canonical_cast_sources_required')
 mapping={x['id']:x for x in h['cast_mapping']}
 for who in CAST:
  check(refs[who]['image'])
  if mapping[who]['identity_image']!=refs[who]['reference_id']:raise StillsError('cast_identity_mapping_changed')
 return h,r,i,a,plan,refs,meta,material
def prepare(run,*,handoff,render_result,inputs,authorization,config,require_material_policy=None,reference_packing=None):
 run=Path(run).resolve();run.mkdir(parents=True,exist_ok=True)
 h,r,i,a,spatial,refs,meta,material=_source(handoff,render_result,inputs,authorization,require_material_policy);cfg=_config(read(config) if isinstance(config,(str,Path)) else config)
 if reference_packing not in (None,SCREEN_PACKING):raise StillsError('explicit_reference_packing_required')
 if reference_packing is not None and material is None:raise StillsError('screen_order_requires_verified_skin_stage')
 render_files={Path(v['path']).stem:v for v in r['files']};rows=[];duplicates={}
 for render in meta['renders']:
  name=render['name'];state=_state(spatial,name);visible=[who for who in CAST if state and state['actors'][who]['visible']]
  if render['visible_actor_ids']!=visible or render['bread_holder']!=(state['props']['bread_bag']['holder'] if state else None):raise StillsError('render_actual_cast_or_prop_mismatch')
  image=render_files[name]
  with Image.open(image['path']) as im:
   if im.size!=(736,1312):raise StillsError('real_stage_dimensions_changed')
  digest=jobs.digest(dict(state=state,camera=render['camera_id']))
  alias=duplicates.get(digest);duplicates.setdefault(digest,name)
  slots=_screen_slots(spatial,state,render) if reference_packing is not None else None
  ordered=[x['entity_id'] for x in slots] if slots is not None else visible
  itemrefs=[dict(kind='stage',image=image)]+[dict(kind='character',entity_id=who,image=refs[who]['image']) for who in ordered]
  source_shot=next((s for s in spatial['shots'] if name==s['id']+'_start'),None)
  first=source_shot.get('opening_frame') if source_shot else None
  row=dict(id=name,stage=image,render=deepcopy(render),state=deepcopy(state),visible_cast=visible,references=itemrefs,prompt=_prompt(name,state,visible,material,slots,**({'opening_frame':first} if first else {})),seed=int(jobs.digest(dict(stage=image,state=state))[:15],16),alias_of=alias,production_approved=False)
  if first:row['opening_frame']=deepcopy(first)
  if slots is not None:row['reference_slots']=[dict(image_number=1,kind='stage',image=image)]+[dict(kind='character',image=refs[x['entity_id']]['image'],**x) for x in slots]
  rows.append(row)
 if not rows or len(rows)>12:raise StillsError('bounded_twelve_stage_contract_required')
 result=dict(schema=SCHEMA,source=dict(handoff=bind(handoff),render_result=bind(render_result),inputs=bind(inputs),authorization=bind(authorization)),spatial_plan=h['plan'],config=cfg,gpu_lock_root=str((ROOT/'data/visual_asset_pipeline/gpu').resolve()),width=736,height=1312,steps=4,max_branches=min(12,a['max_image_submissions']),items=rows,model_called=False,production_approved=False,publication=False)
 if material is not None:result.update(material_contract=deepcopy(material),prompt_contract='skin_markers_visible_architecture/v25')
 if reference_packing is not None:result.update(reference_packing=reference_packing,prompt_contract='screen_order_named_reference_mapping/v26')
 with jobs.run_lock(run,'PLAN.lock'):
  jobs._freeze(run/'PLAN.json',result);jobs._freeze(run/'PROMPT_AUDIT.json',dict(schema='spatial_stills_prompt_audit/v24',plan=bind(run/'PLAN.json'),items=[dict(id=x['id'],prompt=x['prompt'],prompt_sha256=jobs.digest(x['prompt']),visible_cast=x['visible_cast'],state_sha256=jobs.digest(x['state']),alias_of=x['alias_of'],**(dict(reference_slots=x['reference_slots']) if 'reference_slots' in x else {})) for x in rows],text_model_calls=0))
 return dict(status='prepared',plan=bind(run/'PLAN.json'),items=[dict(id=x['id'],visible_cast=x['visible_cast'],alias_of=x['alias_of']) for x in rows],model_posts=0)
def _load(run):
 run=Path(run).resolve();p=read(run/'PLAN.json')
 if p.get('schema')!=SCHEMA or p.get('publication') is not False or p.get('production_approved') is not False:raise StillsError('not_a_candidate_stills_plan')
 for value in p['source'].values():check(value)
 check(p['spatial_plan'])
 for row in p['items']:
  for ref in row['references']:check(ref['image'])
 return run,p
def _global_budget(run,p,*,exclude=None):
 """Same-authorization image branches across sibling runs, including failures.

 Prepared reservations also count, so starting a new namespace cannot reset the
 allowance. Unknown claims retain their reservation. This never changes H3's
 budget, old job state or any native result.
 """
 rows=[];auth=p['source']['authorization'];limit=min(12,read(check(auth))['max_image_submissions'])
 for f in sorted(run.parent.glob('*/batches/*/BATCH.json')):
  if exclude is not None and f.resolve()==Path(exclude).resolve():continue
  parent=f.parents[2];parent_plan=parent/'PLAN.json'
  if not parent_plan.exists():continue
  pp=read(parent_plan)
  if pp.get('schema')!=SCHEMA or pp.get('source',{}).get('authorization')!=auth:continue
  b=read(f)
  if b['plan']!=bind(parent_plan):raise StillsError('global_budget_parent_changed')
  check(b['native_plan']);native=read(b['native_plan']['path']);graph=read(f.parent/'workflow_api.json')
  if jobs.digest(graph)!=native['graph_sha256']:raise StillsError('global_budget_native_graph_changed')
  saves=sum(x['class_type']=='SaveImage' for x in graph.values())
  if saves!=len(b['item_ids']):raise StillsError('global_budget_branch_count_changed')
  state=jobs.status(f.parent)
  rows.append(dict(batch=bind(f),item_ids=b['item_ids'],branches=saves,status=state['status'],prompt_id=state.get('prompt_id'),claim_preserved=(f.parent/'CLAIM.json').exists(),native_result=bind(f.parent/'RESULT.json') if (f.parent/'RESULT.json').exists() else None))
 return dict(schema='spatial_stills_global_branch_budget/v25',authorization=auth,root=str(run.parent),limit=limit,
  reserved_branches=sum(x['branches'] for x in rows),
  known_native_branches=sum(x['branches'] for x in rows if x['prompt_id']),
  saved_branches=sum(x['branches'] for x in rows if x['status']=='saved'),
  unknown_claim_branches=sum(x['branches'] for x in rows if x['claim_preserved'] and not x['prompt_id'] and x['status']=='outcome_unknown'),
  unsubmitted_reserved_branches=sum(x['branches'] for x in rows if not x['claim_preserved'] and not x['prompt_id']),
  batches=rows,failed_and_unknown_count=True)
def prepare_batch(run,batch_id,item_ids):
 run,p=_load(run);jobs._slug(batch_id)
 if not item_ids or len(set(item_ids))!=len(item_ids):raise StillsError('distinct_nonempty_items_required')
 byid={x['id']:x for x in p['items']}
 if any(x not in byid or byid[x]['alias_of'] is not None for x in item_ids):raise StillsError('select_unique_canonical_stage_not_alias')
 with jobs.run_lock(run.parent,'BUDGET.lock'),jobs.run_lock(run,'BATCHES.lock'):
  batch_file=run/'batches'/batch_id/'BATCH.json';budget=_global_budget(run,p,exclude=batch_file)
  if budget['reserved_branches']+len(item_ids)>budget['limit']:raise StillsError('global_image_branch_budget_exceeded')
  reserved=[]
  for f in (run/'batches').glob('*/BATCH.json'):
   if f.parent.name!=batch_id:reserved.extend(read(f)['item_ids'])
  if set(item_ids)&set(reserved):raise StillsError('stage_already_reserved_in_other_batch')
  if len(reserved)+len(item_ids)>p['max_branches']:raise StillsError('image_branch_budget_exceeded')
  jid=jobs._slug(run.name+'_'+batch_id);scope=PREFIX+'/'+jid;items=[];bindings={}
  for name in item_ids:
   row=byid[name];rr=[]
   for index,ref in enumerate(row['references']):
    key='stage_'+name if ref['kind']=='stage' else 'cast_'+ref['entity_id'];image=ref['image'];input_name=scope+'/references/'+key+'.png'
    bindings[input_name]=dict(input_name=input_name,**image);rr.append(dict(input_name=input_name))
   items.append(dict(id=name,prompt=row['prompt'],seed=row['seed'],references=rr))
  graph=jobs.build_graph(items,scope,width=736,height=1312,steps=4);folder=run/'batches'/batch_id
  state=jobs.prepare_job(folder,graph,p['config'],list(bindings.values()),job_id=jid)
  b=dict(schema=SCHEMA,plan=bind(run/'PLAN.json'),item_ids=list(item_ids),graph_sha256=jobs.digest(graph),native_plan=bind(folder/'PLAN.json'),production_approved=False)
  jobs._freeze(folder/'BATCH.json',b)
  receipt=_global_budget(run,p);jobs._write(run.parent/'IMAGE_BRANCH_BUDGET.json',receipt)
  if not (folder/'BUDGET_ADMISSION.json').exists():jobs._freeze(folder/'BUDGET_ADMISSION.json',dict(schema='spatial_stills_budget_admission/v25',batch=bind(folder/'BATCH.json'),authorization=p['source']['authorization'],reserved_after=receipt['reserved_branches'],limit=receipt['limit'],prior_batches=budget['batches'],new_branches=len(items)))
  return dict(batch=batch_id,state=state,binding=bind(folder/'BATCH.json'),branches=len(items),global_reserved_branches=receipt['reserved_branches'],global_limit=receipt['limit'],model_posts=0)
def _batch(run,batch_id):
 run,p=_load(run);jobs._slug(batch_id);folder=run/'batches'/batch_id;b=read(folder/'BATCH.json');check(b['plan']);check(b['native_plan'])
 if b['plan']!=bind(run/'PLAN.json'):raise StillsError('batch_parent_changed')
 return run,p,folder,b
def status(run,batch_id=None):
 run,p=_load(run)
 if batch_id:return jobs.status(run/'batches'/jobs._slug(batch_id))
 return dict(plan=bind(run/'PLAN.json'),batches={f.parent.name:jobs.status(f.parent) for f in (run/'batches').glob('*/BATCH.json')},production_approved=False)
def tick(run,batch_id):
 run,p,folder,b=_batch(run,batch_id);state=jobs.status(folder)
 if state['status']=='prepared':
  gpu=Path(p['gpu_lock_root']);gpu.mkdir(parents=True,exist_ok=True)
  with jobs.run_lock(run.parent,'BUDGET.lock'),jobs.run_lock(gpu,'GPU.lock'):
   budget=_global_budget(run,p)
   if budget['reserved_branches']>budget['limit']:raise StillsError('global_image_branch_budget_exceeded')
   jobs._write(run.parent/'IMAGE_BRANCH_BUDGET.json',budget)
   state=jobs.submit(folder)
 elif state.get('prompt_id') and state['status'] not in ('native_complete','saved','failed','interrupted','rejected','cancelled'):state=jobs.poll(folder)
 if state['status']=='native_complete':
  jobs.collect(folder)
  state=jobs.status(folder)
 if state.get('prompt_id'):
  line=batch_id+' '+state['prompt_id']+'\n';ledger=run/'job_ids.txt'
  with jobs.run_lock(run,'LEDGER.lock'):
   if not ledger.exists() or line not in ledger.read_text(encoding='utf-8'):
    with ledger.open('a',encoding='utf-8') as f:f.write(line)
    with (run/'LOG.md').open('a',encoding='utf-8') as f:f.write(f'\n- {time.time()} NATIVE_ID {batch_id} {state["prompt_id"]}\n')
 if state['status']=='saved':
  result=read(folder/'RESULT.json');images={x['save_node']:x for x in result['images']}
  selected=[]
  for name in b['item_ids']:
   image=images.get(name+'__save')
   if not image or image['dimensions']!=[736,1312]:raise StillsError('actual_klein_branch_missing_or_wrong_size')
   selected.append(dict(id=name,image={k:image[k] for k in ('path','sha256')},save_node=image['save_node'],prompt_id=result['prompt_id'],production_approved=False))
  jobs._freeze(folder/'CANDIDATES.json',dict(schema=SCHEMA,batch=bind(folder/'BATCH.json'),native_result=bind(folder/'RESULT.json'),items=selected,content_status='root_visual_review_required_before_video_guide',production_approved=False))
 return state
def execute(run,batch_id,poll_seconds=10,max_seconds=1800):
 run,p,folder,b=_batch(run,batch_id);deadline=time.monotonic()+max_seconds
 with jobs.run_lock(run,'WORKER.lock'):
  while True:
   state=tick(run,batch_id)
   if state['status'] in ('saved','outcome_unknown','failed','interrupted','rejected','cancelled'):return state
   if time.monotonic()>=deadline:return dict(state,wait_budget_exhausted=True)
   time.sleep(min(60,max(1,poll_seconds),max(0,deadline-time.monotonic())))
