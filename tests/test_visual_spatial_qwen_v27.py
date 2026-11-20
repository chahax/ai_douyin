"""Real file staging plus isolated fake HTTP/native receipt integration, no GPU."""
import json,threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from copy import deepcopy
from PIL import Image
import pytest
from test_visual_spatial_stills_v24 import prepared,skin_receipt,write
from src.content_factory import visual_spatial_stills_v24 as s
from src.content_factory import visual_spatial_qwen_v27 as q

@pytest.fixture
def server():
 shared=dict(posts=0,mode='success',graph=None,output=None)
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def send(self,value,status=200):
   data=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
  def do_POST(self):
   shared['posts']+=1;data=json.loads(self.rfile.read(int(self.headers['Content-Length'])));shared['graph']=data['prompt']
   if shared['mode']=='reject':self.send({'error':'fixture rejection'},400)
   elif shared['mode']=='missing_id':self.send({'accepted':True})
   else:self.send({'prompt_id':'fixture_qwen_id'})
  def do_GET(self):
   if self.path=='/queue':self.send(dict(queue_running=[],queue_pending=[]));return
   if self.path.startswith('/history/'):
    graph=deepcopy(shared['graph']);outputs={}
    for nid,n in graph.items():
     if n['class_type']=='SaveImage':
      rel=Path(n['inputs']['filename_prefix']+'_00001_.png');p=shared['output']/rel;p.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(736,1312),'gray').save(p);outputs[nid]=dict(images=[dict(filename=p.name,subfolder=rel.parent.as_posix(),type='output')])
    if shared['mode']=='wrong_graph':graph['model']['inputs']['unet_name']='tampered'
    self.send({'fixture_qwen_id':dict(prompt=[0,'fixture_qwen_id',graph],outputs=outputs,status=dict(status_str='success',completed=True,messages=[]))});return
   self.send({},404)
 http=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
 yield shared,'http://127.0.0.1:'+str(http.server_port)
 http.shutdown();http.server_close();thread.join()

@pytest.fixture
def ready(prepared,server):
 source,kw=prepared;shared,url=server;kw['config']['config']['service_url']=url;shared['output']=Path(kw['config']['config']['output_root']);skin_receipt(kw);s.prepare(source,**kw,reference_packing=s.SCREEN_PACKING)
 baseline=write(source.parent/'known_workflow_fixture.json',dict(positive=dict(class_type='TextEncodeQwenImageEditPlus'),sample=dict(inputs=dict(steps=4)),model=dict(inputs=dict(unet_name=q.MODELS['unet']))))
 run=source.with_name('qwen_fallback');q.prepare(run,source,old_success_workflow=baseline);q.prepare_batch(run,'canary',['S01_start','S03_end'])
 pp=q.read(run/'PLAN.json');jp=q.read(run/'batches/canary/PLAN.json');approval=write(run/'ROOT_APPROVAL_FIXTURE.json',dict(schema='root_Qwen_fallback_execution/v27',reviewed_by='root_agent',allow_post=True,plan=q.bind(run/'PLAN.json'),job=q.bind(run/'batches/canary/PLAN.json'),approved_items=jp['item_ids'],appearance_sheets=[x['appearance_board']['image'] for x in pp['items'] if x['id'] in jp['item_ids'] and x['appearance_board']],publication=False))
 return run,source,approval,shared,kw

def test_CPU_prepare_stages_real_inputs_without_claim_or_budget_reservation(ready):
 run,source,approval,shared,kw=ready;job=run/'batches/canary';p=q.read(job/'PLAN.json');assert q.status(run,'canary')['status']=='prepared'
 assert shared['posts']==0 and not (job/'CLAIM.json').exists();assert q._budget(run,q.read(run/'PLAN.json'))['qwen_claimed_branches']==0
 q.native._inputs_ok(p);assert len(p['inputs'])==6

def test_exact_2511_Lightning4_graph_and_three_slots(ready):
 run,_,_,_,_=ready;g=q.read(run/'batches/canary/workflow_api.json');q._graph(g,q.PREFIX+'/'+q.read(run/'batches/canary/PLAN.json')['job_id'])
 assert len([v for v in g.values() if v['class_type']=='UNETLoader'])==1
 for name in ('S01_start','S03_end'):
  pos=g[name+'__positive']['inputs'];assert all(k in pos for k in ('image1','image2','image3')) and 'image4' not in pos
  assert g[name+'__sample']['inputs']['steps']==4 and g[name+'__sample']['inputs']['scheduler']=='simple'
  assert g[name+'__scale']['inputs']['width']==736 and g[name+'__scale']['inputs']['height']==1312

def test_board_has_exact_source_crops_and_no_head_loss_assertion_claim(ready):
 run,*_=ready;p=q.read(run/'PLAN.json')
 for item in p['items']:
  b=item['appearance_board']
  if not b:continue
  with Image.open(b['image']['path']) as board:
   assert board.size==(1024,608)
   for panel in b['panels']:
    with Image.open(panel['source']['path']) as source:
     expected=source.convert('RGB').crop((128,16,640,624));target=panel['target'];actual=board.crop((target['x'],0,target['x']+512,608));assert actual.tobytes()==expected.tobytes()
 final=next(x for x in p['items'] if x['id']=='S04_end');assert len(final['references'])==2 and final['appearance_board'] is None

def test_real_mock_HTTP_submit_poll_collect_preserves_original_id(ready):
 run,source,approval,shared,kw=ready;r=q.submit(run,'canary',approval);assert r['prompt_id']=='fixture_qwen_id' and shared['posts']==1
 assert q.poll(run,'canary')['status']=='native_complete';result=q.collect(run,'canary');assert result['prompt_id']=='fixture_qwen_id' and len(result['images'])==2 and result['production_approved'] is False
 assert q.status(run,'canary')['status']=='saved';assert q.submit(run,'canary',approval)['status']=='saved' and shared['posts']==1
 assert len((run/'job_ids.txt').read_text().splitlines())==1

def test_missing_root_approval_cannot_submit(ready):
 run,_,approval,shared,_=ready;v=q.read(approval);v['allow_post']=False;write(approval,v)
 with pytest.raises(q.QwenError,match='root_Qwen'):q.submit(run,'canary',approval)
 assert shared['posts']==0 and not (run/'batches/canary/CLAIM.json').exists()

def test_missing_id_unknown_is_not_replayed(ready):
 run,_,approval,shared,_=ready;shared['mode']='missing_id';assert q.submit(run,'canary',approval)['status']=='outcome_unknown';assert shared['posts']==1
 assert q.execute(run,'canary',approval,max_seconds=1)['status']=='outcome_unknown' and shared['posts']==1
 b=q._budget(run,q.read(run/'PLAN.json'));assert b['qwen_claimed_branches']==2 and b['qwen_unresolved_claim_without_id_branches']==2

def test_unknown_cannot_be_replayed_through_new_namespace(ready):
 run,source,approval,shared,kw=ready;shared['mode']='missing_id';q.submit(run,'canary',approval)
 new=run.with_name('qwen_successor');q.prepare(new,source,old_success_workflow=q.read(run/'PLAN.json')['known_success_workflow']['path']);q.prepare_batch(new,'canary',['S01_start','S03_end']);value=q.read(approval);value.update(plan=q.bind(new/'PLAN.json'),job=q.bind(new/'batches/canary/PLAN.json'),appearance_sheets=[x['appearance_board']['image'] for x in q.read(new/'PLAN.json')['items'] if x['id'] in value['approved_items'] and x['appearance_board']]);newapproval=write(new/'ROOT_APPROVAL_FIXTURE.json',value)
 with pytest.raises(q.QwenError,match='prior_unknown'):q.submit(new,'canary',newapproval)
 assert shared['posts']==1 and not (new/'batches/canary/CLAIM.json').exists()

def test_known_http_rejection_not_replayed(ready):
 run,_,approval,shared,_=ready;shared['mode']='reject';assert q.submit(run,'canary',approval)['status']=='rejected';q.submit(run,'canary',approval);assert shared['posts']==1

def test_wrong_history_graph_cannot_collect(ready):
 run,_,approval,shared,_=ready;q.submit(run,'canary',approval);shared['mode']='wrong_graph'
 with pytest.raises(q.QwenError,match='history_graph'):q.poll(run,'canary')
 assert not (run/'batches/canary/RESULT.json').exists()

def test_input_tamper_stops_before_POST(ready):
 run,_,approval,shared,_=ready;p=q.read(run/'batches/canary/PLAN.json');Path(p['inputs'][0]['staged_path']).write_bytes(b'tampered')
 with pytest.raises(q.native.JobIntegrityError):q.submit(run,'canary',approval)
 assert shared['posts']==0

def test_same_authority_budget_includes_old_Klein_reservations(ready):
 run,source,approval,shared,kw=ready;s.prepare_batch(source,'old_klein',['S01_start','S03_end']);b=q._budget(run,q.read(run/'PLAN.json'));assert b['reserved_branches']==2 and b['qwen_claimed_branches']==0
 q.submit(run,'canary',approval);b=q._budget(run,q.read(run/'PLAN.json'));assert b['total_with_Qwen']==4 and b['qwen_claimed_branches']==2

def test_old_Klein_reservation_blocks_over_budget_before_POST(prepared,server):
 source,kw=prepared;shared,url=server;kw['config']['config']['service_url']=url;shared['output']=Path(kw['config']['config']['output_root']);a=q.read(kw['authorization']);a['max_image_submissions']=3;write(Path(kw['authorization']),a);skin_receipt(kw);s.prepare(source,**kw,reference_packing=s.SCREEN_PACKING);s.prepare_batch(source,'old_klein',['S01_start','S03_end'])
 run=source.with_name('qwen_fallback');baseline=write(source.parent/'baseline.json',dict(positive=dict(class_type='TextEncodeQwenImageEditPlus'),sample=dict(inputs=dict(steps=4)),model=dict(inputs=dict(unet_name=q.MODELS['unet']))));q.prepare(run,source,old_success_workflow=baseline);q.prepare_batch(run,'canary',['S01_start','S03_end']);p=q.read(run/'PLAN.json');jp=q.read(run/'batches/canary/PLAN.json');approval=write(run/'APPROVAL_FIXTURE.json',dict(schema='root_Qwen_fallback_execution/v27',reviewed_by='root_agent',allow_post=True,plan=q.bind(run/'PLAN.json'),job=q.bind(run/'batches/canary/PLAN.json'),approved_items=jp['item_ids'],appearance_sheets=[x['appearance_board']['image'] for x in p['items'] if x['id'] in jp['item_ids'] and x['appearance_board']],publication=False))
 with pytest.raises(q.QwenError,match='twelve_image_budget'):q.submit(run,'canary',approval)
 assert shared['posts']==0 and not (run/'batches/canary/CLAIM.json').exists()

def test_duplicate_keyframe_cannot_move_to_another_batch(ready):
 run,*_=ready
 with pytest.raises(q.QwenError,match='already_assigned'):q.prepare_batch(run,'again',['S01_start'])

@pytest.mark.parametrize('change',['image4','model','steps'])
def test_typed_graph_rejects_wrong_model_slots_or_sampler(ready,change):
 run,*_=ready;g=q.read(run/'batches/canary/workflow_api.json');scope=q.PREFIX+'/'+q.read(run/'batches/canary/PLAN.json')['job_id']
 if change=='image4':g['S01_start__positive']['inputs']['image4']=['S01_start__image1',0]
 elif change=='model':g['model']['inputs']['unet_name']='unverified_model.safetensors'
 else:g['S01_start__sample']['inputs']['steps']=40
 with pytest.raises(q.QwenError):q._graph(g,scope)
