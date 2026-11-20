"""Temporary HTTP protocol/flow tests only; no live model or GPU is called."""
from contextlib import contextmanager
from copy import deepcopy
import http.server
import json
from pathlib import Path
import socket
import subprocess
import sys
import threading

import pytest

from src.content_factory import visual_asset_handoff_v3 as handoff
from src.content_factory.serial_story_contract_v1 import split_shots


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


class FakeOllama:
    def __init__(self):
        self.mode='valid';self.chats=[];self.shows=0;self.busy=False;self.completion=True;self.context=32768

    def output(self,payload):
        if 'scene' in payload:
            scene=payload['scene'];people=['a'] if 'a' in scene['cast'] else []
            if self.mode=='hidden':people=[]
            if self.mode=='new_person':people=['outsider']
            result=dict(shots=[dict(shot_id=w['id'],visible_cast=people,
                character_views={p:'front' for p in people},place_view='reverse' if self.mode=='reverse' else 'side' if self.mode=='side' else 'front',
                visual_prompt='The child opens the wooden door in this same room.',
                evidence=['Unstated invention' if self.mode=='bad_quote' else scene['actions'][0]['description']]) for w in payload['shot_windows']])
            if self.mode=='duplicate_shot' and len(result['shots'])>1:result['shots'][1]['shot_id']=result['shots'][0]['shot_id']
            return result
        entity=payload['entity']
        if entity['id']=='room':return dict(layout_design='A modest lived-in room with simple wood furniture.',front_prompt='One empty modest room.',evidence=[entity['name']])
        return dict(appearance_design='A plain cotton shirt as a casting choice.',front_prompt='One fictional child, plain cotton shirt, full figure.',evidence=[entity['name']],age_band='child')


@contextmanager
def server():
    fake=FakeOllama()
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def respond(self,value,status=200):
            raw=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            if self.path=='/api/tags':self.respond(dict(models=[dict(name='qwen2.5:7b',digest='fixture-digest')]))
            elif self.path=='/queue':self.respond(dict(queue_running=[[0,'foreign',{}]] if fake.busy else [],queue_pending=[]))
            else:self.respond({},404)
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if self.path=='/api/show':
                fake.shows+=1;self.respond(dict(capabilities=['completion'] if fake.completion else ['embedding'],model_info={'qwen2.context_length':fake.context}));return
            if self.path!='/api/chat':self.respond({},404);return
            fake.chats.append(body)
            if fake.mode=='reject':self.respond(dict(error='invalid request'),400);return
            if fake.mode=='lost':self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
            payload=json.loads(body['messages'][1]['content']);result=fake.output(payload)
            content='broken json' if fake.mode=='malformed' else json.dumps(result)
            self.respond(dict(model='qwen2.5:7b',done=True,done_reason='length' if fake.mode=='truncated' else 'stop',message=dict(content=content)))
    httpd=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=httpd.serve_forever,daemon=True);thread.start()
    fake.url=f'http://127.0.0.1:{httpd.server_port}'
    try:yield fake
    finally:httpd.shutdown();httpd.server_close();thread.join(timeout=5)


def material(root,*,seconds=10,empty=False):
    bible=dict(characters=[dict(id='a',name='Alice',aliases=[],source_ids=['c1']),dict(id='b',name='Bob',aliases=[],source_ids=['c1']),dict(id='unused',name='Unseen',source_ids=['c9'])],
        places=[dict(id='room',name='The family room',source_ids=['c1']),dict(id='unvisited',name='Distant school',source_ids=['c9'])],
        claims=[dict(id='cl1',category='character',statement='Alice is a child.',evidence=[dict(source_id='c1',quote='Alice is a child.')])],
        visual_style='Warm naturalistic photography.',creative_additions=[],unresolved=[])
    scene=dict(id='s1',timeline='present',story_time='morning',place_id='room',cast=[] if empty else ['a','b'],seconds=seconds,
        source_ids=['c1'],information='The door opens.',plot='The door opens.',performance='Attentive.',camera='Steady camera.',
        introductions=[],actions=[dict(id='act1',people=[] if empty else ['a'],description='Alice opens the wooden door.' if not empty else 'The wooden door remains closed.',start=0,end=6,source_ids=['c1'])],changes=[],
        audio=[] if empty else [dict(id='au1',speaker='a',mode='onscreen',text='Hello.',start=0,end=2),dict(id='au2',speaker='b',mode='voiceover',text='A remembered voice.',start=3,end=5)])
    bound=dict(script=dict(episode_id='e1',title='Door',scenes=[scene]),continuity=[dict(scene_id='s1',before=[],after=[])])
    accepted=dict(episode_id='e1',binding=dict(simulation=False,candidate_sha256=handoff._legacy(bound),bible_sha256=handoff._legacy(bible),reviews=['reviewed-text']),bound=bound)
    path=root/'accepted.json';write(path,accepted)
    return accepted,bible,dict(path=str(path.resolve()),sha256=handoff._sha(path))


def client(fake,**extra):return handoff.LocalPlanningClient(dict(service_url=fake.url,**extra))


def text_run(root):
    run=root/'text';run.mkdir();accepted,bible,source=material(root)
    write(run/'PLAN.json',dict(version='serial_story_production/v2',media=False,publication=False))
    write(run/'STATE.json',dict(status='machine_review_passed_awaiting_primary_review',pending=None))
    write(run/'START.json',dict(simulation=False));write(run/'SOURCE.json',dict(manifest=dict(book_id='book1')))
    index={}
    def artifact(name,value):
        path=run/'attempts'/'0000'/name;write(path,value);index[name]=dict(path=str(path.relative_to(run)),sha256=handoff._legacy(value))
    artifact('SERIES_BOUND.json',dict(bible=bible,outline={}))
    artifact('EPISODE_000_ACCEPTED.json',accepted)
    artifact('EPISODE_000_SHOTS.json',dict(shots=split_shots(accepted['bound'],15),candidate_sha256=handoff._legacy(accepted['bound'])))
    write(run/'ARTIFACT_INDEX.json',index)
    return run,accepted,bible,index


def policy_for(root,run,fake):
    inputs=root/'inputs';outputs=root/'outputs';inputs.mkdir(exist_ok=True);outputs.mkdir(exist_ok=True)
    return handoff.make_policy(run,'book1',dict(library=str(root/'library'),gpu_lock_root=str(root/'gpu'),
        image_service=dict(service_url=fake.url,input_root=str(inputs),output_root=str(outputs))),
        actor='operator',user_statement='Enable independent image preparation for this accepted story.',planning=dict(service_url=fake.url))


def test_plan_keeps_script_audio_and_only_explicit_visible_cast(tmp_path):
    accepted,bible,source=material(tmp_path);before=Path(source['path']).read_bytes()
    with server() as fake:
        packet=client(fake).plan_episode(accepted,bible,'book1',source,evidence_dir=tmp_path/'evidence')
        assert len(fake.chats)==3
        assert all(r['keep_alive']==0 and r['stream'] is False and r['format']['additionalProperties'] is False for r in fake.chats)
        assert [c['id'] for c in packet['characters']]==['a']
        assert [p['id'] for p in packet['places']]==['room']
        assert packet['shots'][0]['audio']==accepted['bound']['script']['scenes'][0]['audio']
        assert packet['shots'][0]['visible_cast']==['a']
        assert packet['source']==source and packet['accepted_sha256']==handoff.fingerprint(accepted)
        assert packet['characters'][0]['required_views']==handoff.VIEWS
        assert packet['characters'][0]['production_approved'] is False
        assert packet['planning']['story_rewritten'] is False
    assert Path(source['path']).read_bytes()==before


def test_planning_reuses_known_response_without_chat(tmp_path):
    accepted,bible,source=material(tmp_path)
    with server() as fake:
        c=client(fake);first=c.plan_episode(accepted,bible,'book1',source,evidence_dir=tmp_path/'evidence')
        second=c.plan_episode(accepted,bible,'book1',source,evidence_dir=tmp_path/'evidence')
        assert first==second and len(fake.chats)==3


@pytest.mark.parametrize('mode,reason',[('bad_quote','quote_not_in_input'),('hidden','hid_onscreen'),('new_person','output_invalid'),('malformed','output_invalid'),('truncated','incomplete')])
def test_invalid_planning_blocks_before_design(tmp_path,mode,reason):
    accepted,bible,source=material(tmp_path)
    with server() as fake:
        fake.mode=mode
        with pytest.raises(handoff.PlanningBlocked,match=reason):client(fake).plan_episode(accepted,bible,'book1',source,evidence_dir=tmp_path/'ev')
        assert len(fake.chats)==1


def test_unknown_request_never_reposted(tmp_path):
    accepted,bible,source=material(tmp_path)
    with server() as fake:
        fake.mode='lost';c=client(fake)
        with pytest.raises(handoff.PlanningBlocked,match='result_unknown'):c.plan_episode(accepted,bible,'book1',source,evidence_dir=tmp_path/'ev')
        fake.mode='valid'
        with pytest.raises(handoff.PlanningBlocked,match='unknown_local_planning'):c.plan_episode(accepted,bible,'book1',source,evidence_dir=tmp_path/'ev')
        assert len(fake.chats)==1
        assert len(list((tmp_path/'ev').rglob('CLAIM.json')))==1


def test_empty_scene_does_not_force_people(tmp_path):
    accepted,bible,source=material(tmp_path,empty=True)
    with server() as fake:
        packet=client(fake).plan_episode(accepted,bible,'book1',source,evidence_dir=tmp_path/'ev')
        assert packet['characters']==[] and packet['shots'][0]['visible_cast']==[] and len(fake.chats)==2


def test_definitive_http_rejection_is_not_unknown(tmp_path):
    run,accepted,bible,index=text_run(tmp_path)
    with server() as fake:
        p=policy_for(tmp_path,run,fake);root=tmp_path/'media';fake.mode='reject'
        receipt=handoff.enqueue_accepted(root,run,p)
        assert receipt['blocked'][0]['reason']=='local_planning_request_rejected:400'
        assert not list((root/'unknown_planning').glob('*.json'))
        fake.mode='valid';p['planning']['prompt_revision']='fixed'
        next_receipt=handoff.enqueue_accepted(root,run,p)
        assert len(next_receipt['created'])==1 and len(fake.chats)==4


@pytest.mark.parametrize('condition,reason',[('embedding','completion_unconfirmed'),('context','context_exceeds'),('budget','input_exceeds')])
def test_capability_and_context_verified(tmp_path,condition,reason):
    accepted,bible,source=material(tmp_path)
    with server() as fake:
        extra={}
        if condition=='embedding':fake.completion=False
        if condition=='context':fake.context=4096
        if condition=='budget':extra['max_input_chars']=100
        with pytest.raises(handoff.PlanningBlocked,match=reason):client(fake,**extra).plan_episode(accepted,bible,'book1',source,evidence_dir=tmp_path/'ev')
        assert fake.chats==[]


def test_source_and_accepted_digest_guard(tmp_path):
    accepted,bible,source=material(tmp_path)
    with server() as fake:
        accepted['bound']['script']['title']='tampered'
        with pytest.raises(handoff.PlanningBlocked,match='binding_changed'):client(fake).plan_episode(accepted,bible,'book1',source,evidence_dir=tmp_path/'ev')
        accepted,bible,source=material(tmp_path);Path(source['path']).write_text('{}')
        with pytest.raises(handoff.PlanningBlocked,match='source_changed'):client(fake).plan_episode(accepted,bible,'book1',source,evidence_dir=tmp_path/'ev')
        assert fake.chats==[]


def test_twins_require_explicit_quote_and_named_pair():
    chars=[dict(id='a',name='Alice'),dict(id='b',name='Bob')]
    claim=dict(statement='Alice and Bob share an appearance.',evidence=[dict(quote='They looked alike.')])
    assert handoff._identity_groups(chars,[claim])==dict(a='a',b='b')
    claim['evidence'][0]['quote']='Alice and Bob are identical twins.'
    groups=handoff._identity_groups(chars,[claim]);assert groups['a']==groups['b'] and groups['a'].startswith('twins_')


def test_enqueue_idempotent_independent_authorization(tmp_path):
    run,accepted,bible,index=text_run(tmp_path);old=(run/'PLAN.json').read_bytes()
    with server() as fake:
        policy=policy_for(tmp_path,run,fake);root=tmp_path/'media'
        first=handoff.enqueue_accepted(root,run,policy);second=handoff.enqueue_accepted(root,run,policy)
        assert len(first['created'])==1 and second['reused']==first['created'] and len(fake.chats)==3
        plan=handoff._read(Path(first['created'][0])/'PLAN.json')
        assert plan['publication'] is False and plan['old_h3_resume'] is False
        assert plan['packet']['source']['path']==str((run/index['EPISODE_000_ACCEPTED.json']['path']).resolve())
    assert (run/'PLAN.json').read_bytes()==old


@pytest.mark.parametrize('condition,status',[('disabled','disabled'),('paused_file','paused'),('paused_state','paused'),('pending','blocked_text_unknown')])
def test_enqueue_control_stops_before_any_model(tmp_path,condition,status):
    run,accepted,bible,index=text_run(tmp_path)
    with server() as fake:
        p=policy_for(tmp_path,run,fake)
        if condition=='disabled':p['enabled']=False
        if condition=='paused_file':write(run/'PAUSE_REQUESTED.json',{})
        if condition=='paused_state':write(run/'STATE.json',dict(status='paused',pending=None))
        if condition=='pending':write(run/'STATE.json',dict(status='running',pending={'unknown':'original'}))
        assert handoff.enqueue_accepted(tmp_path/'media',run,p)['status']==status
        assert fake.chats==[]


@pytest.mark.parametrize('condition,reason',[('simulation','simulation_run'),('book','book_mismatch'),('artifact','text_artifact_changed'),('policy','separate_bound')])
def test_enqueue_rejects_wrong_origin_and_artifacts(tmp_path,condition,reason):
    run,accepted,bible,index=text_run(tmp_path)
    with server() as fake:
        p=policy_for(tmp_path,run,fake)
        if condition=='simulation':write(run/'START.json',dict(simulation=True))
        if condition=='book':p['book_id']='other'
        if condition=='artifact':write(run/index['EPISODE_000_ACCEPTED.json']['path'],{})
        if condition=='policy':p['media']=False
        with pytest.raises((handoff.PlanningBlocked,PermissionError,ValueError),match=reason):handoff.enqueue_accepted(tmp_path/'media',run,p)
        assert fake.chats==[]


def test_changed_text_creates_new_bound_run_retains_old(tmp_path):
    run,accepted,bible,index=text_run(tmp_path)
    with server() as fake:
        p=policy_for(tmp_path,run,fake);root=tmp_path/'media';first=handoff.enqueue_accepted(root,run,p)['created'][0]
        accepted['bound']['script']['title']='A revised title';accepted['binding']['candidate_sha256']=handoff._legacy(accepted['bound'])
        path=run/index['EPISODE_000_ACCEPTED.json']['path'];write(path,accepted);index['EPISODE_000_ACCEPTED.json']['sha256']=handoff._legacy(accepted)
        shots=dict(shots=split_shots(accepted['bound'],15),candidate_sha256=handoff._legacy(accepted['bound']))
        write(run/index['EPISODE_000_SHOTS.json']['path'],shots);index['EPISODE_000_SHOTS.json']['sha256']=handoff._legacy(shots);write(run/'ARTIFACT_INDEX.json',index)
        second=handoff.enqueue_accepted(root,run,p)['created'][0]
        assert first!=second and (Path(first)/'PLAN.json').exists() and (Path(second)/'PLAN.json').exists()
        assert len(fake.chats)==4  # same stable casting/place designs, new scene staging request


def test_unknown_cannot_bypass_by_policy_revision(tmp_path):
    run,accepted,bible,index=text_run(tmp_path)
    with server() as fake:
        p=policy_for(tmp_path,run,fake);root=tmp_path/'media';fake.mode='lost'
        first=handoff.enqueue_accepted(root,run,p);assert 'unknown' in first['blocked'][0]['reason']
        p['planning']['prompt_revision']='new';fake.mode='valid'
        again=handoff.enqueue_accepted(root,run,p)
        assert again['blocked'][0]['reason']=='prior_unknown_planning_retained' and len(fake.chats)==1


def test_crash_orphan_claim_preserved_across_policy_revision(tmp_path):
    run,accepted,bible,index=text_run(tmp_path)
    with server() as fake:
        p=policy_for(tmp_path,run,fake);root=tmp_path/'media';path=run/index['EPISODE_000_ACCEPTED.json']['path']
        source=dict(path=str(path.resolve()),sha256=handoff._sha(path));orphan=root/'planning'/'crashed'
        write(orphan/'SOURCE.json',source);write(orphan/'scene_any'/'CLAIM.json',dict(request='sent'))
        receipt=handoff.enqueue_accepted(root,run,p)
        assert receipt['blocked'][0]['reason']=='prior_unknown_planning_retained' and fake.chats==[]
        assert Path(receipt['blocked'][0]['evidence']).is_file()


def test_gpu_busy_does_not_dispatch_planning(tmp_path):
    run,accepted,bible,index=text_run(tmp_path)
    with server() as fake:
        fake.busy=True;receipt=handoff.enqueue_accepted(tmp_path/'media',run,policy_for(tmp_path,run,fake))
        assert receipt['blocked'][0]['reason']=='gpu_busy' and fake.chats==[]


def test_pause_arriving_during_plan_does_not_prepare(tmp_path):
    run,accepted,bible,index=text_run(tmp_path)
    with server() as fake:
        p=policy_for(tmp_path,run,fake);root=tmp_path/'media';delegate=client(fake)
        class PausingPlanner:
            def plan_episode(self,*a,**kw):
                packet=delegate.plan_episode(*a,**kw);write(root/'PAUSE.json',dict(actor='operator'));return packet
        receipt=handoff.enqueue_accepted(root,run,p,planner=PausingPlanner())
        assert receipt['status']=='paused' and receipt['created']==[]
        assert not list((root/'runs').glob('*/PLAN.json'))


def test_local_url_only_and_admin_policy(tmp_path):
    for url in ('https://localhost:11434','http://example.com:11434','http://localhost:11434/path','http://u:p@localhost:11434'):
        with pytest.raises(ValueError,match='local_planning'):handoff.LocalPlanningClient(dict(service_url=url))
    run,accepted,bible,index=text_run(tmp_path)
    with pytest.raises(PermissionError):handoff.make_policy(run,'book1',{},actor='viewer',user_statement='enable',role='viewer')
    with pytest.raises(ValueError,match='boolean'):handoff.make_policy(run,'book1',{},actor='admin',user_statement='enable',enabled=1)


def test_independent_process_handoff_http_blackbox(tmp_path):
    run,accepted,bible,index=text_run(tmp_path)
    with server() as fake:
        p=policy_for(tmp_path,run,fake);path=tmp_path/'policy.json';write(path,p)
        code='from pathlib import Path; import json,sys; from src.content_factory.visual_asset_handoff_v3 import enqueue_accepted; p=json.loads(Path(sys.argv[1]).read_text()); print(json.dumps(enqueue_accepted(sys.argv[2],sys.argv[3],p)))'
        command=[sys.executable,'-B','-c',code,str(path),str(tmp_path/'media'),str(run)]
        first=subprocess.run(command,capture_output=True,text=True,timeout=30)
        assert first.returncode==0,first.stderr
        created=json.loads(first.stdout)['created'];assert len(created)==1
        second=subprocess.run(command,capture_output=True,text=True,timeout=30)
        assert second.returncode==0,second.stderr
        assert json.loads(second.stdout)['reused']==created and len(fake.chats)==3


def test_cached_packet_changed_blocks_before_prepare(tmp_path):
    run,accepted,bible,index=text_run(tmp_path)
    with server() as fake:
        p=policy_for(tmp_path,run,fake);root=tmp_path/'media';delegate=client(fake)
        class PausingPlanner:
            def plan_episode(self,*a,**kw):
                packet=delegate.plan_episode(*a,**kw);write(root/'PAUSE.json',dict(actor='operator'));return packet
        handoff.enqueue_accepted(root,run,p,planner=PausingPlanner())
        packet_path=next((root/'planning').glob('*/PACKET.json'));packet=handoff._read(packet_path);packet['book_id']='other';write(packet_path,packet)
        (root/'PAUSE.json').unlink()
        with pytest.raises(handoff.PlanningBlocked,match='packet_binding_changed'):handoff.enqueue_accepted(root,run,p)
        assert len(fake.chats)==3 and not list((root/'runs').glob('*/PLAN.json'))


def test_shot_window_audio_and_duplicate_coverage_guard(tmp_path):
    accepted,bible,source=material(tmp_path,seconds=20);shots=split_shots(accepted['bound'],15)
    with server() as fake:
        bad=deepcopy(shots);bad[0]['audio_ids']=[]
        with pytest.raises(handoff.PlanningBlocked,match='audio_binding'):client(fake).plan_episode(accepted,bible,'book1',source,shots=bad,evidence_dir=tmp_path/'bad')
        assert fake.chats==[]
        fake.mode='duplicate_shot'
        with pytest.raises(handoff.PlanningBlocked,match='shot_coverage'):client(fake).plan_episode(accepted,bible,'book1',source,shots=shots,evidence_dir=tmp_path/'dup')


def test_planning_does_not_mutate_bible_or_accepted(tmp_path):
    accepted,bible,source=material(tmp_path);a=deepcopy(accepted);b=deepcopy(bible)
    with server() as fake:client(fake).plan_episode(accepted,bible,'book1',source,evidence_dir=tmp_path/'ev')
    assert accepted==a and bible==b


def test_unknown_shared_design_survives_host_exit_and_revision(tmp_path):
    run,accepted,bible,index=text_run(tmp_path)
    with server() as fake:
        p=policy_for(tmp_path,run,fake);root=tmp_path/'media';path=run/index['EPISODE_000_ACCEPTED.json']['path']
        source=dict(path=str(path.resolve()),sha256=handoff._sha(path));orphan=root/'planning'/'crashed';design=root/'design_cache'/'shared'
        write(orphan/'SOURCE.json',source);write(design/'CLAIM.json',dict(sent=True));write(orphan/'CALLS'/'request.json',dict(folder=str(design.resolve())))
        receipt=handoff.enqueue_accepted(root,run,p)
        assert receipt['blocked'][0]['reason']=='prior_unknown_planning_retained' and fake.chats==[]


def test_source_file_must_be_the_same_accepted_value(tmp_path):
    accepted,bible,source=material(tmp_path);write(Path(source['path']),dict(other='artifact'));source['sha256']=handoff._sha(source['path'])
    with server() as fake:
        with pytest.raises(handoff.PlanningBlocked,match='source_content_mismatch'):client(fake).plan_episode(accepted,bible,'book1',source,evidence_dir=tmp_path/'ev')
        assert fake.shows==0 and fake.chats==[]


def test_same_planning_folder_serializes_dispatch(tmp_path):
    accepted,bible,source=material(tmp_path);evidence=tmp_path/'ev';evidence.mkdir()
    with server() as fake:
        with handoff.jobs.run_lock(evidence,'PLANNING.lock'):
            with pytest.raises(handoff.jobs.JobBusyError):client(fake).plan_episode(accepted,bible,'book1',source,evidence_dir=evidence)
        assert fake.chats==[]


def test_handoff_image_endpoint_is_also_loopback_only(tmp_path):
    run,accepted,bible,index=text_run(tmp_path)
    with server() as fake:
        p=policy_for(tmp_path,run,fake);p['pipeline_config']['image_service']['service_url']='http://example.com'
        with pytest.raises(ValueError,match='local_planning_endpoint'):handoff.enqueue_accepted(tmp_path/'media',run,p)
        assert fake.chats==[]


def test_unavailable_image_guard_is_reported_as_blocked(tmp_path):
    run,accepted,bible,index=text_run(tmp_path)
    with server() as fake:
        p=policy_for(tmp_path,run,fake)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        p['pipeline_config']['image_service']['service_url']=f'http://127.0.0.1:{port}'
        receipt=handoff.enqueue_accepted(tmp_path/'media',run,p)
        assert receipt['blocked'][0]['reason'].startswith('image_service_unavailable:') and fake.chats==[]


@pytest.mark.parametrize('view',['reverse','side'])
def test_place_generation_includes_actual_staging_view(tmp_path,view):
    from src.content_factory.visual_asset_pipeline_v3 import asset_requirements
    accepted,bible,source=material(tmp_path)
    with server() as fake:
        fake.mode=view;packet=client(fake).plan_episode(accepted,bible,'book1',source,evidence_dir=tmp_path/'ev')
        assert packet['shots'][0]['place_view']==view
        assert set(packet['places'][0]['required_views'])=={'front','layout',view}
        needed=[r for r in asset_requirements(packet) if r['kind']=='place']
        assert view in {r['view'] for r in needed} and packet['places'][0]['view_prompts'][view]
