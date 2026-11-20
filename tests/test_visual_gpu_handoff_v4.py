"""Real loopback HTTP/lease tests; no GPU, model, or production /free calls."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import threading

import pytest

from src.content_factory import visual_asset_pipeline_v3 as pipeline
from src.content_factory import visual_gpu_handoff_v4 as h


class Service:
    def __init__(self,root):
        self.input=root/'input';self.output=root/'output';self.input.mkdir();self.output.mkdir()
        self.posts=[];self.queue=dict(queue_running=[],queue_pending=[]);self.mode='ack';self.wrong_paths=False
        self.on_post=None;owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def reply(self,data,code=200):
                raw=b'' if data is None else json.dumps(data).encode();self.send_response(code)
                self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            def do_GET(self):
                if self.path=='/queue':self.reply(owner.queue)
                elif self.path=='/system_stats':self.reply(dict(system=dict(argv=['main.py','--input-directory',
                    str(owner.input)+'wrong' if owner.wrong_paths else str(owner.input),'--output-directory',str(owner.output)])))
                else:self.send_error(404)
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))));owner.posts.append((self.path,payload))
                if owner.on_post:owner.on_post()
                if owner.mode=='drop':self.connection.shutdown(2);self.connection.close();return
                if owner.mode=='redirect':
                    self.send_response(307);self.send_header('Location',owner.url+'/unexpected');self.send_header('Content-Length','0');self.end_headers();return
                if owner.mode=='reject':self.reply(None,422);return
                if owner.mode=='server_error':self.reply(None,500);return
                self.reply(None)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)
    def close(self):self.server.shutdown();self.server.server_close();self.thread.join(5)


@pytest.fixture
def setup(tmp_path):
    service=Service(tmp_path);pause=tmp_path/'PAUSE.json';pause.write_text('{}')
    config=dict(gpu_lock_root=str(tmp_path/'gpu'),protected_pause_path=str(pause),release_comfy_before_review=True,
        image_service=dict(service_url=service.url,input_root=str(service.input),output_root=str(service.output),timeout=2))
    try:yield service,config
    finally:service.close()


def resources(monkeypatch,*values):
    calls=[];pending=list(values)
    def probe():
        item=pending.pop(0) if len(pending)>1 else pending[0];calls.append(item)
        return dict(available_ram_gib=item[0],available_vram_gib=item[1])
    monkeypatch.setattr(h,'probe_resources',probe);monkeypatch.setattr(h,'POLL_SECONDS',0)
    return calls


def root(config):return h._scope(config)[2]


def test_default_disabled_preserves_old_plan_and_never_probes_or_frees(setup,monkeypatch):
    service,config=setup;config.pop(h.POLICY)
    def forbidden():pytest.fail('Legacy policy must not measure or unload models.')
    monkeypatch.setattr(h,'probe_resources',forbidden)
    with pipeline.gpu_access(dict(config=config)):pass
    assert not service.posts and not root(config).exists()


@pytest.mark.parametrize('value',[1,'true',None])
def test_new_policy_is_explicit_boolean(setup,value):
    service,config=setup;config[h.POLICY]=value
    with pytest.raises(ValueError,match='requires_boolean'):
        with pipeline.gpu_access(dict(config=config)):pytest.fail('Invalid policy entered successor.')
    assert not service.posts


def test_already_sufficient_headroom_skips_free(setup,monkeypatch):
    service,config=setup;calls=resources(monkeypatch,(8,7))
    with pipeline.gpu_access(dict(config=config)):assert len(calls)==1
    assert not service.posts and not root(config).exists()


@pytest.mark.parametrize('queue',[
    dict(queue_running=[[0,'busy',{}]],queue_pending=[]),
    dict(queue_running=[],queue_pending=[[0,'pending',{}]]),{},
    dict(queue_running=None,queue_pending=[]),dict(queue_running=[[0,'wrong']],queue_pending=[]),
])
def test_busy_or_malformed_queue_never_posts_free(setup,monkeypatch,queue):
    service,config=setup;service.queue=queue;calls=resources(monkeypatch,(8,1))
    with pytest.raises(ValueError,match='queue'):
        with pipeline.gpu_access(dict(config=config)):pytest.fail('Busy queue entered successor.')
    assert not service.posts and not calls


def test_free_requires_both_leases_and_measured_async_completion(setup,monkeypatch):
    service,config=setup;calls=resources(monkeypatch,(8,1),(8,2),(8,7));held=[]
    original=pipeline.images.run_lock
    @contextmanager
    def observed(folder,name='EXECUTION.lock'):
        with original(folder,name=name):
            held.append(name)
            try:yield
            finally:held.remove(name)
    monkeypatch.setattr(pipeline.images,'run_lock',observed)
    def post_check():assert held==['GPU.lock','VISUAL_GPU.lock']
    service.on_post=post_check
    with pipeline.gpu_access(dict(config=config)):
        assert len(calls)==3 and held==['GPU.lock','VISUAL_GPU.lock']
    assert service.posts==[('/free',dict(unload_models=True,free_memory=True))]
    assert not (root(config)/'PENDING.json').exists()
    states=list(root(config).glob('attempts/*/STATE.json'));assert len(states)==1
    assert json.loads(states[0].read_text())['status']=='resources_observed'


@pytest.mark.parametrize('mode',['drop','server_error','redirect'])
def test_unknown_free_is_retained_and_never_reposted_or_followed_by_any_dispatch(setup,monkeypatch,mode):
    service,config=setup;service.mode=mode;resources(monkeypatch,(8,1))
    with pytest.raises(h.GpuHandoffUnknown):
        with pipeline.gpu_access(dict(config=config)):pytest.fail('Unknown free dispatched VLM.')
    marker=root(config)/'UNKNOWN.json';before=marker.read_bytes()
    claim=next(root(config).glob('attempts/*/CLAIM.json'));original_claim=claim.read_bytes()
    resources(monkeypatch,(8,9))
    for review in (True,False):
        with pytest.raises(h.GpuHandoffUnknown):
            with pipeline.gpu_access(dict(config=config),for_review=review):pytest.fail('Unknown free dispatched successor.')
    assert len(service.posts)==1 and service.posts[0][0]=='/free'
    assert marker.read_bytes()==before and claim.read_bytes()==original_claim


def test_known_http_rejection_is_recorded_and_does_not_dispatch(setup,monkeypatch):
    service,config=setup;service.mode='reject';resources(monkeypatch,(8,1))
    with pytest.raises(ValueError,match='free_rejected'):
        with pipeline.gpu_access(dict(config=config)):pytest.fail('Rejected free dispatched VLM.')
    assert len(service.posts)==1 and list(root(config).glob('attempts/*/REJECTED.json'))
    assert not (root(config)/'UNKNOWN.json').exists() and not (root(config)/'PENDING.json').exists()


def test_ack_without_headroom_is_not_completion_and_recovery_does_not_repeat_free(setup,monkeypatch):
    service,config=setup;resources(monkeypatch,(8,1));monkeypatch.setattr(h,'WAIT_SECONDS',0)
    with pytest.raises(ValueError,match='resource_wait_timeout'):
        with pipeline.gpu_access(dict(config=config)):pytest.fail('HTTP200 alone dispatched VLM.')
    assert len(service.posts)==1 and (root(config)/'PENDING.json').exists()
    with pytest.raises(ValueError,match='waiting_resources_before_dispatch'):
        with pipeline.gpu_access(dict(config=config),for_review=False):pytest.fail('Pending free dispatched image model.')
    resources(monkeypatch,(8,7))
    with pipeline.gpu_access(dict(config=config)):pass
    assert len(service.posts)==1 and not (root(config)/'PENDING.json').exists()


def test_queue_becoming_busy_after_ack_blocks_successor(setup,monkeypatch):
    service,config=setup;resources(monkeypatch,(8,1),(8,7))
    def becomes_busy():service.queue=dict(queue_running=[[0,'external',{}]],queue_pending=[])
    service.on_post=becomes_busy
    with pytest.raises(ValueError,match='queue_busy'):
        with pipeline.gpu_access(dict(config=config)):pytest.fail('New busy queue dispatched VLM.')
    assert len(service.posts)==1 and (root(config)/'PENDING.json').exists()


def test_wrong_service_paths_or_missing_resource_measurement_never_free(setup,monkeypatch):
    service,config=setup;resources(monkeypatch,(8,1));service.wrong_paths=True
    with pytest.raises(ValueError,match='wrong_service_paths'):
        with pipeline.gpu_access(dict(config=config)):pytest.fail('Wrong Comfy was unloaded.')
    service.wrong_paths=False;resources(monkeypatch,(8,None))
    with pytest.raises(ValueError,match='measurement_unconfirmed'):
        with pipeline.gpu_access(dict(config=config)):pytest.fail('Unknown resources dispatched VLM.')
    assert not service.posts


def test_native_dispatch_does_not_run_release_policy_but_checks_retained_markers(setup,monkeypatch):
    service,config=setup
    def forbidden():pytest.fail('Image dispatch does not release its own model.')
    monkeypatch.setattr(h,'probe_resources',forbidden)
    with pipeline.gpu_access(dict(config=config),for_review=False):pass
    assert not service.posts


def test_claim_without_response_cannot_be_repeated_even_if_unknown_marker_was_not_written(setup,monkeypatch):
    service,config=setup;resources(monkeypatch,(8,1));service.mode='drop'
    with pytest.raises(h.GpuHandoffUnknown):
        with pipeline.gpu_access(dict(config=config)):pass
    (root(config)/'UNKNOWN.json').unlink()
    with pytest.raises(h.GpuHandoffUnknown):
        with pipeline.gpu_access(dict(config=config)):pytest.fail('Lost final marker replayed /free.')
    assert len(service.posts)==1 and (root(config)/'UNKNOWN.json').exists()


@pytest.mark.parametrize('lease',['GPU.lock','VISUAL_GPU.lock'])
def test_either_busy_lease_prevents_resource_probe_and_free(setup,monkeypatch,lease):
    service,config=setup;calls=resources(monkeypatch,(8,1))
    folder=Path(config['gpu_lock_root']) if lease=='GPU.lock' else service.input;folder.mkdir(exist_ok=True)
    with pipeline.images.run_lock(folder,name=lease):
        with pytest.raises(pipeline.images.JobBusyError):
            with pipeline.gpu_access(dict(config=config)):pytest.fail('A busy lease allowed resource release.')
    assert not service.posts and not calls
