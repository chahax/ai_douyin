"""Typed local Qwen-2511 fallback; preparation never reserves or submits media.

No mutation of Klein's stable runtime. Explicit root approval is required for
POST; known IDs/unknown claims always survive. The board is appearance input,
not an output guide. Image budgets include all prior Klein/native branches.
"""
from pathlib import Path
from copy import deepcopy
import json,time,uuid,urllib.error
from PIL import Image
from . import visual_spatial_stills_v24 as spatial
from . import visual_image_jobs_v3 as native

SCHEMA='spatial_qwen_fallback/v27';JOB='spatial_qwen_native_job/v27';PREFIX='spatial_qwen_v27'
MODELS=dict(unet='qwen_image_edit_2511_int8_convrot.safetensors',clip='qwen_2.5_vl_7b_fp8_scaled.safetensors',vae='qwen_image_vae.safetensors',lora='Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors')
CLASSES={'UNETLoader','ModelSamplingAuraFlow','CFGNorm','CLIPLoader','VAELoader','LoraLoaderModelOnly','LoadImage','ImageScale','TextEncodeQwenImageEditPlus','VAEEncode','KSampler','VAEDecode','SaveImage'}
IDS=('S01_start','S03_end','S02_end','S04_end')
class QwenError(ValueError):pass
read=spatial.read;bind=spatial.bind;check=spatial.check
def _board(run,item):
 children=[x['entity_id'] for x in item['reference_slots'][1:] if x['entity_id']!='su_mo']
 refs={x.get('entity_id'):x['image'] for x in item['references'] if x['kind']=='character'}
 if not children:return None
 if len(children)==1:return dict(image=refs[children[0]],panels=[dict(entity_id=children[0],source=refs[children[0]],roi=None,target=None)],appearance_only=True)
 roi=dict(x=128,y=16,width=512,height=608);path=run/'appearance'/(item['id']+'_brothers.png');path.parent.mkdir(exist_ok=True)
 board=Image.new('RGB',(1024,608),'white');panels=[]
 for index,who in enumerate(children):
  source=check(refs[who])
  with Image.open(source) as image:
   if image.size!=(768,1024):raise QwenError('explicit_canonical_crop_requires_768x1024')
   crop=image.convert('RGB').crop((128,16,640,624));board.paste(crop,(index*512,0))
  panels.append(dict(entity_id=who,source=refs[who],roi=roi,target=dict(x=index*512,y=0,width=512,height=608)))
 if path.exists():
  with Image.open(path) as old:
   if old.size!=board.size or old.convert('RGB').tobytes()!=board.tobytes():raise QwenError('appearance_board_changed')
 else:board.save(path)
 return dict(image=bind(path),panels=panels,appearance_only=True,labels_rendered=False)
def _prompt(item,board):
 visible=item['visible_cast'];text=('Edit image 1 into one photorealistic live-action Chinese family film still. Preserve its camera perspective, visible room architecture, furniture, blocked body positions and relative heights. '
 'Use natural human skin and the final named-reference clothing. Image 1 is the spatial stage. ')
 if 'su_mo' in visible:text+='Image 2 is Su Mo, the adult father, dark jacket over a gray buttoned shirt and dark trousers. '
 if board:
  number=3 if 'su_mo' in visible else 2
  for index,panel in enumerate(board['panels']):
   who=panel['entity_id'];description=spatial.DESCRIPTIONS[who][1];position=('left' if index==0 else 'right') if len(board['panels'])==2 else 'single'
   text+=f'The {position} portrait in image {number} is {description}. '
 for slot in item['reference_slots'][1:]:
  who=slot['entity_id'];a=item['state']['actors'][who];number=2 if who=='su_mo' else 3 if 'su_mo' in visible else 2
  text+=f'The {slot["clothing_marker"]} clothing-marker figure in image 1 is {spatial.DESCRIPTIONS[who][1].split(",")[0]}; its appearance comes from image {number}. '
  text+=f'This person is {a["pose"]}, eyes {a["eyes"]}. '
  text+='This person securely holds the single transparent-bagged bread portion in natural hands. ' if who==item['state']['props']['bread_bag']['holder'] else 'This person has empty hands. '
 text+='The portrait board supplies appearance only. The final output is the single continuous scene from image 1, with natural faces and hand grips.'
 return text
def build_graph(items,scope):
 graph={
 'model':dict(class_type='UNETLoader',inputs=dict(unet_name=MODELS['unet'],weight_dtype='default')),
 'sampling':dict(class_type='ModelSamplingAuraFlow',inputs=dict(model=['model',0],shift=3.1)),
 'norm':dict(class_type='CFGNorm',inputs=dict(model=['sampling',0],strength=1.0)),
 'lightning4':dict(class_type='LoraLoaderModelOnly',inputs=dict(model=['norm',0],lora_name=MODELS['lora'],strength_model=1.0)),
 'clip':dict(class_type='CLIPLoader',inputs=dict(clip_name=MODELS['clip'],type='qwen_image',device='default')),
 'vae':dict(class_type='VAELoader',inputs=dict(vae_name=MODELS['vae']))}
 for item in items:
  key=native._slug(item['id']);refs=item['references']
  if not 1<=len(refs)<=3:raise QwenError('EditPlus_accepts_at_most_three_images')
  def node(name,kind,**inputs):
   nid=key+'__'+name;graph[nid]=dict(class_type=kind,inputs=inputs);return[nid,0]
  links=[node('image'+str(i),'LoadImage',image=native._relative(x['input_name'])) for i,x in enumerate(refs,1)]
  links[0]=node('scale','ImageScale',image=links[0],upscale_method='lanczos',width=736,height=1312,crop='disabled')
  condition=dict(clip=['clip',0],vae=['vae',0],**{'image'+str(i):link for i,link in enumerate(links,1)})
  positive=node('positive','TextEncodeQwenImageEditPlus',prompt=item['prompt'],**condition);negative=node('negative','TextEncodeQwenImageEditPlus',prompt='',**condition)
  latent=node('latent','VAEEncode',pixels=links[0],vae=['vae',0]);sample=node('sample','KSampler',model=['lightning4',0],positive=positive,negative=negative,latent_image=latent,seed=item['seed'],steps=4,cfg=1,sampler_name='euler',scheduler='simple',denoise=1.0)
  decoded=node('decode','VAEDecode',samples=sample,vae=['vae',0]);node('save','SaveImage',images=decoded,filename_prefix=scope+'/'+key)
 return graph
def _graph(graph,scope):
 if not graph or any(n['class_type'] not in CLASSES for n in graph.values()):raise QwenError('typed_Qwen_graph_required')
 for node in graph.values():
  if node['class_type']=='TextEncodeQwenImageEditPlus' and any(k.startswith('image') and k not in ('image1','image2','image3') for k in node['inputs']):raise QwenError('unsupported_fourth_reference')
  if node['class_type']=='SaveImage' and not node['inputs']['filename_prefix'].startswith(scope+'/'):raise QwenError('output_scope_changed')
 if graph['model']['inputs']['unet_name']!=MODELS['unet'] or graph['clip']['inputs']['clip_name']!=MODELS['clip'] or graph['vae']['inputs']['vae_name']!=MODELS['vae'] or graph['lightning4']['inputs']['lora_name']!=MODELS['lora']:raise QwenError('exact_local_Qwen_models_required')
 if graph['clip']['inputs']['type']!='qwen_image' or graph['sampling']['inputs']['shift']!=3.1 or graph['norm']['inputs']['strength']!=1 or graph['lightning4']['inputs']['strength_model']!=1:raise QwenError('known_Qwen_loader_contract_changed')
 for node in graph.values():
  if node['class_type']=='KSampler' and any(node['inputs'].get(k)!=v for k,v in dict(steps=4,cfg=1,sampler_name='euler',scheduler='simple',denoise=1.0).items()):raise QwenError('known_Lightning4_sampler_contract_changed')
  if node['class_type']=='ImageScale' and (node['inputs']['width'],node['inputs']['height'])!=(736,1312):raise QwenError('formal_Qwen_output_dimensions_required')
 return {n['inputs']['image'] for n in graph.values() if n['class_type']=='LoadImage'}
def prepare(run,source_stills,*,old_success_workflow=None):
 run=Path(run).resolve();run.mkdir(parents=True,exist_ok=True);source,p=spatial._load(source_stills)
 if p.get('reference_packing')!=spatial.SCREEN_PACKING:raise QwenError('source_screen_slots_required')
 known=Path(old_success_workflow or spatial.ROOT/'data/image_model_trials/20261105_klein_qwen/cases/qwen_edit_two_people_lightning4_512/workflow_api.json')
 old=read(known)
 if old['positive']['class_type']!='TextEncodeQwenImageEditPlus' or old['sample']['inputs']['steps']!=4 or old['model']['inputs']['unet_name']!=MODELS['unet']:raise QwenError('known_Qwen_baseline_required')
 rows=[];byid={x['id']:x for x in p['items']}
 for name in IDS:
  item=byid[name];board=_board(run,item);refs=[dict(role='stage',image=item['stage'])]
  canon={x.get('entity_id'):x['image'] for x in item['references'] if x['kind']=='character'}
  if 'su_mo' in item['visible_cast']:refs.append(dict(role='su_mo',image=canon['su_mo']))
  if board:refs.append(dict(role='brothers_appearance',image=board['image']))
  rows.append(dict(id=name,stage=item['stage'],state=item['state'],visible_cast=item['visible_cast'],source_slots=item['reference_slots'],references=refs,appearance_board=board,prompt=_prompt(item,board),seed=item['seed']))
 cfg=dict(p['config'],allowed_prefix=PREFIX);result=dict(schema=SCHEMA,source_stills_plan=bind(source/'PLAN.json'),source_authorization=p['source']['authorization'],known_success_workflow=bind(known),config=cfg,gpu_lock_root=p['gpu_lock_root'],items=rows,width=736,height=1312,steps=4,requires_root_execution_approval=True,prepare_reserves_budget=False,production_approved=False,publication=False)
 native._freeze(run/'PLAN.json',result);return dict(status='prepared_CPU_only',plan=bind(run/'PLAN.json'),items=[dict(id=x['id'],images=len(x['references']),board=x['appearance_board']) for x in rows],model_posts=0,budget_reserved=0)
def _load(run):
 run=Path(run).resolve();p=read(run/'PLAN.json')
 if p.get('schema')!=SCHEMA or p.get('production_approved') is not False or p.get('publication') is not False:raise QwenError('candidate_Qwen_plan_required')
 check(p['source_stills_plan']);check(p['source_authorization']);check(p['known_success_workflow'])
 for item in p['items']:
  for ref in item['references']:check(ref['image'])
  if item['appearance_board']:
   for panel in item['appearance_board']['panels']:check(panel['source'])
 return run,p
def prepare_batch(run,batch_id,item_ids):
 run,p=_load(run);native._slug(batch_id);byid={x['id']:x for x in p['items']}
 if not item_ids or len(set(item_ids))!=len(item_ids) or any(x not in byid for x in item_ids):raise QwenError('known_unique_keyframes_required')
 for f in (run/'batches').glob('*/PLAN.json'):
  if f.parent.name!=batch_id and set(read(f)['item_ids'])&set(item_ids):raise QwenError('keyframe_already_assigned_to_another_batch')
 job=run/'batches'/batch_id;job.mkdir(parents=True,exist_ok=True);jid=native._slug(run.name+'_'+batch_id);scope=PREFIX+'/'+jid;items=[];bindings={}
 for name in item_ids:
  row=byid[name];refs=[]
  for ref in row['references']:
   image=ref['image'];input_name=scope+'/references/'+name+'_'+ref['role']+'.png';bindings[input_name]=dict(input_name=input_name,**image);refs.append(dict(input_name=input_name))
  items.append(dict(id=name,prompt=row['prompt'],seed=row['seed'],references=refs))
 graph=build_graph(items,scope);names=_graph(graph,scope);cfg=native.Config(**p['config']).normalized()
 actual=[native.stage_input(cfg,b['path'],b['input_name'],b['sha256']) for b in bindings.values()]
 if names!={x['input_name'] for x in actual}:raise QwenError('staged_reference_bindings_changed')
 protected=cfg['protected_pause_path'];plan=dict(version=JOB,job_id=jid,parent=bind(run/'PLAN.json'),config=cfg,item_ids=list(item_ids),graph_sha256=native.digest(graph),inputs=sorted(actual,key=lambda x:x['input_name']),protected_pause=bind(protected) if protected else None)
 with native.run_lock(job):
  native._freeze(job/'PLAN.json',plan);native._freeze(job/'workflow_api.json',graph)
  if not (job/'STATE.json').exists():native._write(job/'STATE.json',dict(status='prepared',job_id=jid,prompt_id=None,plan_sha256=native.digest(plan)))
 return status(run,batch_id)
def _job(run,batch_id):
 run,p=_load(run);job=run/'batches'/native._slug(batch_id);plan=read(job/'PLAN.json');graph=read(job/'workflow_api.json');check(plan['parent'])
 if plan['version']!=JOB or plan['parent']!=bind(run/'PLAN.json') or native.digest(graph)!=plan['graph_sha256'] or read(job/'STATE.json')['plan_sha256']!=native.digest(plan):raise QwenError('frozen_native_job_changed')
 _graph(graph,plan['config']['allowed_prefix']+'/'+plan['job_id'])
 if sum(n['class_type']=='SaveImage' for n in graph.values())!=len(plan['item_ids']):raise QwenError('native_branch_count_changed')
 return run,p,job,plan,graph
def status(run,batch_id):
 run,p,job,plan,g=_job(run,batch_id);s=native._state(job,plan)
 if (job/'CLAIM.json').exists() and not s.get('prompt_id') and s['status']!='rejected':s['status']='outcome_unknown'
 return s
def _approval(run,p,job,plan,approval):
 value=read(check(bind(approval)))
 sheets=[i['appearance_board']['image'] for i in p['items'] if i['id'] in plan['item_ids'] and i['appearance_board']]
 if value.get('schema')!='root_Qwen_fallback_execution/v27' or value.get('reviewed_by')!='root_agent' or value.get('allow_post') is not True or value.get('plan')!=bind(run/'PLAN.json') or value.get('job')!=bind(job/'PLAN.json') or value.get('approved_items')!=plan['item_ids'] or value.get('appearance_sheets')!=sheets or value.get('publication') is not False:raise QwenError('explicit_root_Qwen_window_and_sheet_approval_required')
 return bind(approval)
def _budget(run,p):
 source=Path(p['source_stills_plan']['path']).parent;sp=read(check(p['source_stills_plan']));budget=spatial._global_budget(source,sp);own=[]
 for f in run.parent.glob('*/batches/*/PLAN.json'):
  value=read(f)
  if value.get('version')!=JOB:continue
  pp=read(check(value['parent']))
  if pp['source_authorization']!=p['source_authorization']:continue
  if (f.parent/'CLAIM.json').exists():own.append(dict(native_plan=bind(f),item_ids=value['item_ids'],branches=len(value['item_ids']),state=status(f.parents[2],f.parent.name)))
 budget.update(qwen_claimed_branches=sum(x['branches'] for x in own),qwen_known_native_branches=sum(x['branches'] for x in own if x['state'].get('prompt_id')),qwen_saved_branches=sum(x['branches'] for x in own if x['state']['status']=='saved'),qwen_unresolved_claim_without_id_branches=sum(x['branches'] for x in own if not x['state'].get('prompt_id') and x['state']['status']=='outcome_unknown'),qwen_claims=own,total_with_Qwen=budget['reserved_branches']+sum(x['branches'] for x in own));return budget
def submit(run,batch_id,approval):
 run,p,job,plan,g=_job(run,batch_id)
 with native.run_lock(job),native.run_lock(run.parent,'BUDGET.lock'),native.run_lock(Path(p['gpu_lock_root']),'GPU.lock'),native.run_lock(Path(plan['config']['input_root']),'VISUAL_GPU.lock'):
  s=status(run,batch_id)
  if s.get('prompt_id') or s['status']!='prepared':return s
  approved=_approval(run,p,job,plan,approval);native._inputs_ok(plan)
  if plan['protected_pause']:check(plan['protected_pause'])
  budget=_budget(run,p)
  if any(x['state']['status']=='outcome_unknown' and set(x['item_ids'])&set(plan['item_ids']) for x in budget['qwen_claims']):raise QwenError('preserve_prior_unknown_keyframe_claim_no_successor_POST')
  if budget['total_with_Qwen']+len(plan['item_ids'])>budget['limit']:raise QwenError('global_twelve_image_budget_exceeded')
  native._service_paths(plan['config']);q=native._queue(plan['config'])
  if q['queue_running'] or q['queue_pending']:return dict(s,dispatch='waiting_gpu_queue')
  native._freeze(job/'ROOT_APPROVAL.json',approved);native._freeze(job/'BUDGET_ADMISSION.json',dict(prior_budget=budget,new_branches=len(plan['item_ids']),expected_total=budget['total_with_Qwen']+len(plan['item_ids'])))
  native._freeze(job/'REQUEST.json',dict(prompt=g,client_id=uuid.uuid4().hex));native._freeze(job/'CLAIM.json',dict(at=time.time(),graph_sha256=plan['graph_sha256'],input_sha256=native.digest(plan['inputs'])))
  native._write(run.parent/'QWEN_IMAGE_BRANCH_BUDGET.json',_budget(run,p))
  try:response=native._http(plan['config'],'/prompt',read(job/'REQUEST.json'))
  except urllib.error.HTTPError as e:
   native._freeze(job/'SUBMISSION_ERROR.json',dict(type='HTTPError',code=e.code,body=e.read().decode(errors='replace')[:16000]));s.update(status='rejected' if e.code in (400,422) else 'outcome_unknown')
  except Exception as e:native._freeze(job/'SUBMISSION_ERROR.json',dict(type=type(e).__name__,message=str(e)));s.update(status='outcome_unknown')
  else:
   native._freeze(job/'RESPONSE.json',response)
   if isinstance(response,dict) and isinstance(response.get('prompt_id'),str) and response['prompt_id']:s.update(status='submitted',prompt_id=native._slug(response['prompt_id']),submitted_at=time.time())
   else:s.update(status='outcome_unknown')
  native._write(job/'STATE.json',s)
  native._write(run.parent/'QWEN_IMAGE_BRANCH_BUDGET.json',_budget(run,p))
  if s.get('prompt_id'):
   with (run/'job_ids.txt').open('a',encoding='utf-8') as f:f.write(batch_id+' '+s['prompt_id']+'\n')
   with (run/'LOG.md').open('a',encoding='utf-8') as f:f.write(f'\n- {time.time()} SUBMIT {batch_id} {s["prompt_id"]}\n')
  return status(run,batch_id)
def poll(run,batch_id):
 run,p,job,plan,g=_job(run,batch_id)
 with native.run_lock(job):
  s=status(run,batch_id)
  if not s.get('prompt_id') or s['status'] in ('saved','failed','interrupted','rejected','cancelled','native_complete'):return s
  pid=s['prompt_id'];history=native._http(plan['config'],'/history/'+pid);entry=history.get(pid)
  if entry:
   if entry.get('prompt',[None,None,None])[2]!=g:raise QwenError('native_history_graph_changed')
   native._write(job/'HISTORY.json',history);terminal=entry.get('status',{});events=[x[0] for x in terminal.get('messages',[]) if isinstance(x,list) and x]
   s['status']='interrupted' if 'execution_interrupted' in events else 'failed' if terminal.get('status_str')=='error' else 'native_complete' if terminal.get('completed') is True else 'running'
  else:
   q=native._queue(plan['config']);found=[x for x in q['queue_running']+q['queue_pending'] if x[1]==pid]
   if any(x[2]!=g for x in found):raise QwenError('native_queue_graph_changed')
   s['status']='running' if found else 'outcome_unknown'
  native._write(job/'STATE.json',s);return s
def collect(run,batch_id):
 run,p,job,plan,g=_job(run,batch_id)
 with native.run_lock(job):
  s=status(run,batch_id)
  if s['status']=='saved':
   result=read(job/'RESULT.json')
   for image in result['images']:check(image['image'])
   return result
  if s['status']!='native_complete':raise QwenError('native_completion_required')
  entry=read(job/'HISTORY.json')[s['prompt_id']]
  if entry['prompt'][2]!=g or entry['status'].get('status_str')!='success' or entry['status'].get('completed') is not True:raise QwenError('successful_original_history_required')
  images=[];scope=Path(plan['config']['output_root'])/PREFIX/plan['job_id']
  for nid,node in g.items():
   if node['class_type']!='SaveImage':continue
   outputs=entry['outputs'].get(nid,{}).get('images',[])
   if len(outputs)!=1:raise QwenError('one_saved_image_per_branch_required')
   o=outputs[0]
   if o.get('type')!='output' or '/' in o['filename'] or '\\' in o['filename']:raise QwenError('native_output_basename_required')
   path=native._bound(plan['config']['output_root'],(o.get('subfolder','').replace('\\','/')+'/'+o['filename']).lstrip('/'))
   if not path.is_relative_to(scope) or not path.name.startswith(Path(node['inputs']['filename_prefix']).name+'_'):raise QwenError('native_output_scope_changed')
   with Image.open(path) as im:
    if im.size!=(736,1312):raise QwenError('native_Qwen_size_changed')
   target=job/'artifacts'/nid/path.name;target.parent.mkdir(parents=True,exist_ok=True)
   if not target.exists():native._copy_new(path,target)
   if native.file_sha(path)!=native.file_sha(target):raise QwenError('saved_output_changed')
   images.append(dict(id=nid.removesuffix('__save'),image=bind(target),source_path=str(path),save_node=nid,prompt_id=s['prompt_id']))
  result=dict(schema=SCHEMA,job=bind(job/'PLAN.json'),prompt_id=s['prompt_id'],images=images,technical_status='saved',content_status='root_visual_review_required',production_approved=False,publication=False)
  native._freeze(job/'RESULT.json',result);s['status']='saved';native._write(job/'STATE.json',s);native._write(run.parent/'QWEN_IMAGE_BRANCH_BUDGET.json',_budget(run,p));return result
def execute(run,batch_id,approval,*,poll_seconds=10,max_seconds=3600):
 run,p=_load(run);deadline=time.monotonic()+max_seconds
 with native.run_lock(run,'WORKER.lock'):
  while True:
   s=status(run,batch_id)
   if s['status']=='prepared':s=submit(run,batch_id,approval)
   elif s.get('prompt_id') and s['status'] not in ('saved','failed','interrupted','rejected','cancelled','native_complete','outcome_unknown'):s=poll(run,batch_id)
   if s['status']=='native_complete':collect(run,batch_id);s=status(run,batch_id)
   if s['status'] in ('saved','failed','interrupted','rejected','cancelled','outcome_unknown'):return s
   if time.monotonic()>=deadline:return dict(s,wait_budget_exhausted=True)
   time.sleep(min(60,max(1,poll_seconds),max(0,deadline-time.monotonic())))
