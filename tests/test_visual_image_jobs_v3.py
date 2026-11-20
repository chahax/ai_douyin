"""State/HTTP black boxes; fixture server does not run a model or touch live Comfy."""
from contextlib import contextmanager
import http.server
import json
from pathlib import Path
import socket
import subprocess
import sys
import threading

from PIL import Image
import pytest

from src.content_factory import visual_image_jobs_v3 as jobs


class FixtureComfy:
    def __init__(self,root):
        self.root=root; self.inputs=root/'input';self.outputs=root/'output'
        self.inputs.mkdir();self.outputs.mkdir();self.graph=None;self.posts=0
        self.done=False;self.mode='accept';self.error=False;self.interrupted=False
        self.traversal=False;self.busy=False;self.wrong_graph=False;self.pid='fixture-native-id'
        self.windows_subfolders=False

    def queue(self):
        return dict(queue_running=([[0,'foreign-id',{}]] if self.busy else
                                  [[0,self.pid,self.graph]] if self.graph and not self.done else []),queue_pending=[])

    def history(self):
        if not self.done:return {}
        outputs={}
        for nid,node in self.graph.items():
            if node['class_type']=='SaveImage':
                p=Path(node['inputs']['filename_prefix']);filename=p.name+'_00001_.png'
                path=self.outputs/p.parent/filename;path.parent.mkdir(parents=True,exist_ok=True)
                if not path.exists():Image.new('RGB',(32,48),'navy').save(path)
                folder=p.parent.as_posix().replace('/','\\') if self.windows_subfolders else p.parent.as_posix()
                outputs[nid]=dict(images=[dict(filename=filename,subfolder='../../outside' if self.traversal else folder,type='output')])
        graph={} if self.wrong_graph else self.graph
        return {self.pid:dict(prompt=[0,self.pid,graph],status=dict(completed=True,
              status_str='error' if self.error else 'success',messages=[['execution_interrupted',{}]] if self.interrupted else []),outputs=outputs)}


@contextmanager
def server(root):
    fixture=FixtureComfy(root)
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def respond(self,value,code=200):
            data=json.dumps(value).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def do_GET(self):
            if self.path=='/system_stats':
                self.respond(dict(system=dict(argv=['main.py','--input-directory',str(fixture.inputs),'--output-directory',str(fixture.outputs)])))
            elif self.path=='/queue':self.respond(fixture.queue())
            elif self.path.startswith('/history/'):self.respond(fixture.history())
            else:self.respond({},404)
        def do_POST(self):
            if self.path!='/prompt':self.respond({},404);return
            fixture.posts+=1
            request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if fixture.mode=='reject':self.respond(dict(error='validation_failed',node_errors={}),400);return
            if fixture.mode=='server_error':self.respond(dict(error='uncertain'),500);return
            fixture.graph=request['prompt']
            if fixture.mode=='lost_response':
                self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
            if fixture.mode=='malformed':self.respond(['unexpected']);return
            self.respond(dict(prompt_id=fixture.pid,node_errors={}))
    httpd=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=httpd.serve_forever,daemon=True);thread.start()
    fixture.url=f'http://127.0.0.1:{httpd.server_port}'
    try:yield fixture
    finally:httpd.shutdown();httpd.server_close();thread.join(timeout=5)


def prepared(root,fake,refs=False,protected=None,job_id='case1'):
    items=[dict(id='portrait',prompt='The selected fictional child in a neutral studio.',seed=4)]
    inputs=[]
    if refs:
        source=root/'source.png';Image.new('RGB',(32,48),'gray').save(source)
        items[0]['references']=[dict(input_name='bound_source.png',roi=dict(x=0,y=0,width=16,height=16))]
        inputs=[dict(input_name='bound_source.png',path=str(source),sha256=jobs.file_sha(source))]
    graph=jobs.build_graph(items,'tests/'+job_id,width=128,height=128)
    config=jobs.Config(fake.url,fake.inputs,fake.outputs,'tests',protected_pause_path=protected)
    path=root/job_id
    jobs.prepare_job(path,graph,config,inputs,job_id)
    return path,graph,config,inputs


def test_graph_batch_shared_models_but_independent_subjects():
    graph=jobs.build_graph([dict(id='a',prompt='one',seed=1),dict(id='b',prompt='two',seed=2,
        references=[dict(input_name='room.png'),dict(input_name='adult.png'),dict(input_name='child.png')])],'test/job')
    assert sum(n['class_type']=='UNETLoader' for n in graph.values())==1
    assert sum(n['class_type']=='SamplerCustomAdvanced' for n in graph.values())==2
    assert graph['a__positive']['inputs']['text']=='one' and graph['b__positive']['inputs']['text']=='two'
    assert len([n for n in graph.values() if n['class_type']=='ReferenceLatent'])==6
    assert graph['b__save']['inputs']['filename_prefix']=='test/job/b'


@pytest.mark.parametrize('bad',[dict(id='a',prompt='x',seed=1,render_text=True),
    dict(id='../bad',prompt='x',seed=1),dict(id='a',prompt='x',seed=1,references=[dict(input_name='../outside')]),
    dict(id='a',prompt='x',seed=1,references=[dict(input_name='a',roi=dict(x=0,y=0,width=2,height=2)),dict(input_name='b')])])
def test_graph_rejects_caption_traversal_or_mixed_roi_references(bad):
    with pytest.raises(ValueError):jobs.build_graph([bad],'test/job')


def test_real_http_lifecycle_prepare_resume_poll_collect_once(tmp_path):
    with server(tmp_path) as fake:
        job,graph,config,inputs=prepared(tmp_path,fake,refs=True)
        assert jobs.prepare_job(job,graph,config,inputs,'case1')['status']=='prepared'
        assert jobs.submit(job)['status']=='submitted'
        recovered=jobs.submit(job)
        assert recovered['prompt_id']==fake.pid and recovered['status']=='submitted' and fake.posts==1
        assert jobs.poll(job)['status']=='running'
        fake.done=True
        assert jobs.poll(job)['status']=='native_complete'
        result=jobs.collect(job)
        assert result['technical_status']=='saved' and result['production_approved'] is False
        assert result['content_status']=='candidate_pending_visual_review'
        assert jobs.collect(job)==result and jobs.submit(job)['status']=='saved' and fake.posts==1


@pytest.mark.parametrize('mode,expected',[('reject','rejected'),('server_error','outcome_unknown'),('lost_response','outcome_unknown'),('malformed','outcome_unknown')])
def test_submit_failures_never_blindly_replayed(tmp_path,mode,expected):
    with server(tmp_path) as fake:
        job,*_=prepared(tmp_path,fake);fake.mode=mode
        assert jobs.submit(job)['status']==expected
        assert jobs.submit(job)['status']==expected and fake.posts==1


def test_crash_claim_without_response_preserves_unknown_and_zero_post(tmp_path):
    with server(tmp_path) as fake:
        job,*_=prepared(tmp_path,fake)
        (job/'CLAIM.json').write_text('{}')
        assert jobs.submit(job)['status']=='outcome_unknown' and fake.posts==0
        with pytest.raises(ValueError):jobs.cancel_before_submit(job)


def test_response_written_before_state_is_recovered_without_repost(tmp_path):
    with server(tmp_path) as fake:
        job,*_=prepared(tmp_path,fake);jobs.submit(job)
        state=json.loads((job/'STATE.json').read_text());state.update(status='prepared',prompt_id=None)
        (job/'STATE.json').write_text(json.dumps(state))
        recovered=jobs.submit(job)
        assert recovered['prompt_id']==fake.pid and recovered['status']=='submitted' and fake.posts==1
        fake.done=True;assert jobs.poll(job)['status']=='native_complete'


def test_pause_only_stops_dispatch_known_id_can_finish_without_touching_h3_pause(tmp_path):
    protected=tmp_path/'old_h3_PAUSE.json';protected.write_text('{"original":"keep"}')
    before=protected.read_bytes()
    with server(tmp_path) as fake:
        job,*_=prepared(tmp_path,fake,protected=protected)
        jobs.set_paused(job);assert jobs.submit(job)['dispatch']=='paused_before_submit' and fake.posts==0
        jobs.set_paused(job,False);jobs.submit(job);jobs.set_paused(job)
        fake.done=True;assert jobs.poll(job)['status']=='native_complete';jobs.collect(job)
        assert jobs.status(job)['paused'] is True and fake.posts==1
        assert protected.read_bytes()==before


def test_cancel_pre_submit_and_foreign_pause_protection(tmp_path):
    with server(tmp_path) as fake:
        job,*_=prepared(tmp_path,fake)
        jobs.cancel_before_submit(job);assert jobs.submit(job)['status']=='cancelled' and fake.posts==0
        (job/'PAUSE.json').write_text('{"foreign":true}')
        with pytest.raises(jobs.JobIntegrityError):jobs.set_paused(job,False)
        with pytest.raises(jobs.JobIntegrityError):jobs.set_paused(job,True)


@pytest.mark.parametrize('which',['source','staged','graph','plan','protected_pause'])
def test_bound_source_or_task_changes_block_before_post(tmp_path,which):
    pause=tmp_path/'old_pause';pause.write_text('keep')
    with server(tmp_path) as fake:
        job,graph,_,inputs=prepared(tmp_path,fake,refs=True,protected=pause)
        if which=='source':Path(inputs[0]['path']).write_bytes(b'changed')
        elif which=='staged':(fake.inputs/'bound_source.png').write_bytes(b'changed')
        elif which=='graph':graph['portrait__positive']['inputs']['text']='different';(job/'workflow_api.json').write_text(json.dumps(graph))
        elif which=='plan':
            plan=json.loads((job/'PLAN.json').read_text());plan['config']['output_root']=str(tmp_path/'other');(job/'PLAN.json').write_text(json.dumps(plan))
        else:pause.unlink()
        with pytest.raises(jobs.JobIntegrityError):jobs.submit(job)
        assert fake.posts==0 and not (job/'CLAIM.json').exists()


def test_foreign_queue_waits_without_claim(tmp_path):
    with server(tmp_path) as fake:
        job,*_=prepared(tmp_path,fake);fake.busy=True
        assert jobs.submit(job)['dispatch']=='waiting_gpu_queue' and not (job/'CLAIM.json').exists()
        fake.busy=False;assert jobs.submit(job)['status']=='submitted'


@pytest.mark.parametrize('interrupted',[False,True])
def test_native_known_error_or_interrupt_is_terminal_without_replay(tmp_path,interrupted):
    with server(tmp_path) as fake:
        job,*_=prepared(tmp_path,fake);jobs.submit(job);fake.error=True;fake.done=True;fake.interrupted=interrupted
        assert jobs.poll(job)['status']==('interrupted' if interrupted else 'failed')
        jobs.submit(job);assert fake.posts==1


def test_missing_native_id_is_unknown_not_finished(tmp_path):
    with server(tmp_path) as fake:
        job,*_=prepared(tmp_path,fake);jobs.submit(job);fake.graph=None
        assert jobs.poll(job)['status']=='outcome_unknown'
        jobs.submit(job);assert fake.posts==1


@pytest.mark.parametrize('failure',['wrong_graph','traversal','changed_saved'])
def test_completion_does_not_accept_wrong_graph_escaped_output_or_changed_file(tmp_path,failure):
    with server(tmp_path) as fake:
        job,*_=prepared(tmp_path,fake);jobs.submit(job);fake.done=True
        if failure=='wrong_graph':
            fake.wrong_graph=True
            with pytest.raises(jobs.JobIntegrityError):jobs.poll(job)
        else:
            fake.traversal=failure=='traversal';jobs.poll(job)
            if fake.traversal:
                with pytest.raises(jobs.JobIntegrityError):jobs.collect(job)
            else:
                result=jobs.collect(job);Path(result['images'][0]['path']).write_bytes(b'changed')
                with pytest.raises(jobs.JobIntegrityError):jobs.collect(job)
        assert fake.posts==1


def test_nonlocal_service_and_hidden_nonimage_node_rejected(tmp_path):
    with pytest.raises(ValueError):jobs.Config('https://example.com',tmp_path,tmp_path).normalized()
    with server(tmp_path) as fake:
        _,graph,cfg,_=prepared(tmp_path,fake)
        graph['hidden']=dict(class_type='HTTPUpload',inputs={})
        with pytest.raises(ValueError):jobs.prepare_job(tmp_path/'hidden',graph,cfg,[],job_id='case1')


def test_roi_outside_actual_bound_image_rejected(tmp_path):
    with server(tmp_path) as fake:
        job,graph,cfg,inputs=prepared(tmp_path,fake,refs=True)
        graph['portrait__crop_0']['inputs']['width']=100
        with pytest.raises(ValueError,match='roi_outside_bound_source'):
            jobs.prepare_job(tmp_path/'out_of_bounds',graph,cfg,inputs,job_id='case1')
        assert fake.posts==0


def test_saved_state_requires_actual_receipt(tmp_path):
    with server(tmp_path) as fake:
        job,*_=prepared(tmp_path,fake);jobs.submit(job);fake.done=True;jobs.poll(job);jobs.collect(job)
        (job/'RESULT.json').unlink()
        with pytest.raises(jobs.JobIntegrityError):jobs.status(job)


def test_windows_native_subfolder_separator_is_supported_without_allowing_escape(tmp_path):
    with server(tmp_path) as fake:
        job,*_=prepared(tmp_path,fake);fake.windows_subfolders=True
        jobs.submit(job);fake.done=True;jobs.poll(job)
        assert jobs.collect(job)['technical_status']=='saved'


def test_second_job_cannot_submit_while_first_native_id_is_in_queue(tmp_path):
    with server(tmp_path) as fake:
        one,*_=prepared(tmp_path,fake)
        two,*_=prepared(tmp_path,fake,job_id='case2')
        jobs.submit(one)
        assert jobs.submit(two)['dispatch']=='waiting_gpu_queue'
        assert fake.posts==1 and not (two/'CLAIM.json').exists()


@pytest.mark.parametrize('record',['CLAIM.json','REQUEST.json'])
def test_changed_native_submission_proof_is_not_trusted(tmp_path,record):
    with server(tmp_path) as fake:
        job,*_=prepared(tmp_path,fake);jobs.submit(job)
        (job/record).write_text('{}')
        with pytest.raises(jobs.JobIntegrityError):jobs.poll(job)
        assert fake.posts==1


def test_result_cannot_self_promote_production_approval(tmp_path):
    with server(tmp_path) as fake:
        job,*_=prepared(tmp_path,fake);jobs.submit(job);fake.done=True;jobs.poll(job);jobs.collect(job)
        result=json.loads((job/'RESULT.json').read_text());result['production_approved']=True
        (job/'RESULT.json').write_text(json.dumps(result))
        with pytest.raises(jobs.JobIntegrityError):jobs.collect(job)


def test_blackbox_fresh_process_runs_http_worker_without_in_process_monkeypatch(tmp_path):
    with server(tmp_path) as fake:
        job,*_=prepared(tmp_path,fake)
        command=[sys.executable,'-B','-c',
                 'from src.content_factory.visual_image_jobs_v3 import submit; import sys,json; print(json.dumps(submit(sys.argv[1])))',str(job)]
        proc=subprocess.run(command,capture_output=True,text=True,cwd=Path(__file__).resolve().parents[1],timeout=30)
        assert proc.returncode==0,proc.stderr
        assert json.loads(proc.stdout)['status']=='submitted' and fake.posts==1
        again=subprocess.run(command,capture_output=True,text=True,cwd=Path(__file__).resolve().parents[1],timeout=30)
        assert again.returncode==0 and fake.posts==1
