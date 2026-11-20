"""Synthetic native production contracts and installed-SDK MockTransport only."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import socket
from types import SimpleNamespace
import httpx
import pytest
from scripts import creative_world_scene_production_probe_v1 as m
from tests.test_creative_goal_context_workflow_v28 import case as world_case, profile
from tests.test_creative_director_endpoint_contract_v4 import generic_native
from src.content_factory import creative_complete_production_pipeline_v2 as ranges


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **kw): raise AssertionError('real network forbidden in production bridge tests')
    monkeypatch.setattr(socket.socket, 'connect', deny); monkeypatch.setattr(socket, 'create_connection', deny)
    monkeypatch.setattr(m.clients.text, 'role_config', lambda role: SimpleNamespace(
        model='MiniMax-M3.1-Flash-Preview' if role=='writer' else 'deepseek-flash', api_key='offline-test-key',
        base_url='https://api.minimax.cn/v1' if role=='writer' else 'https://api.deepseek.com/v1'))


def parent_fixture(tmp_path):
    inputs, goal, setup, raw = world_case.__wrapped__()
    views=m.workflow.compile_native_views(goal,setup,**m.workflow.origin_ids(inputs))
    compiled=m.workflow.validate_script_document(raw,views,inputs['production_preferences'])['script']
    root=tmp_path/'synthetic_text'; root.mkdir()
    paths={}
    for key,value in dict(inputs=inputs,profile=profile(),goal=goal,setup=setup,raw_script=raw,compiled_script=compiled).items():
        p=root/(key+'.json');m.write(p,value,True);paths[key]=str(p)
    m.write(root/'TEXT_HANDOFF.json',{'OFFLINE':'not a real text approval'},True)
    inherited={'calls_started':701,'reported_tokens':12345000,'calls_with_known_usage':699,'pending_ordinals':[70,160], 'unknown_token_reservations':93117}
    return {'schema':'OFFLINE-text-verifier-fixture','valid':True,'accepted':True,'status':'text_ready_for_director',
        'root':str(root),'source_root':str(root),'paths':paths,'handoff_path':str(root/'TEXT_HANDOFF.json'),
        'handoff_sha256':m.sha(root/'TEXT_HANDOFF.json'),'identity':{'native_goal_sha256':m.digest(goal),
            'native_script_sha256':m.digest(raw),'compiled_script_sha256':m.digest(compiled),'native_setup_sha256':m.digest(setup)},
        'inherited':inherited,'source_files':m._hashes([*paths.values(),root/'TEXT_HANDOFF.json']),
        'parent_identity':{'root':str(root),'end_ordinal':701,'terminal_state_sha256':'OFFLINE', 'native_ledger_sha256':'OFFLINE'}}


def whole_direction(material):
    graph=ranges.candidate_graph(material['script'],material['manifest']); bank=m.source.catalog(material['script'])
    size=len(graph['source_refs']); outgoing={i:[] for i in range(size)}
    for edge in graph['ranges']: outgoing[edge['start_index']].append(edge)
    costs={size:(0,[])}
    for i in range(size-1,-1,-1):
        options=[]
        for e in outgoing[i]:
            if e['end_index_exclusive'] not in costs:continue
            budget=min(e['budget_options'],key=lambda b:b['target_seconds'])
            cost,tail=costs[e['end_index_exclusive']]
            options.append((budget['target_seconds']+cost,[(e['end_source_ref'],budget['budget_tier'])]+tail))
        if options: costs[i]=min(options,key=lambda x:x[0])
    first_beat=material['script']['beats'][0]['id']; candidates=[]
    for edge in outgoing[0]:
        refs=graph['source_refs'][:edge['end_index_exclusive']]
        natural=next((b for b in edge['budget_options'] if b['budget_tier']=='natural'),None)
        if (natural and all(bank[r]['beat_id']==first_beat for r in refs) and
            any(bank[r]['kind']=='dialogue' for r in refs) and edge['end_index_exclusive'] in costs):
            remaining,tail=costs[edge['end_index_exclusive']]
            if remaining+natural['target_seconds']<=180:candidates.append((len(refs),edge,natural,tail))
    assert candidates,'explicit synthetic complete plan must exist'
    _,edge,budget,tail=max(candidates,key=lambda x:x[0])
    native=generic_native([(edge['end_source_ref'],budget['budget_tier']),*tail])
    return {'direction':native,'cast_by_picture':{'image2':'c_employee','image3':'c_manager'}}


def first_performance(material,direction):
    segment=m.compile_direction(direction,material)['compiled_direction']['segments'][0]
    bank=m.source.catalog(material['script']); refs=segment['source_refs']
    return {'availability':'known','continuous_performance':'OFFLINE synthetic continuous acting contract only',
        'actor_goals':[{'actor_id':a['id'],'immediate_objective':'OFFLINE synthetic objective',
            'source_reception':{'stimuli':[],'response':'OFFLINE synthetic response'}} for a in material['manifest']['actors']],
        'dialogue_delivery':[{'source_ref':r,'speech_tone':'OFFLINE synthetic tone','listener_behavior':'OFFLINE synthetic listening'} for r in refs if bank[r]['kind']=='dialogue'],
        'action_timings':[{'source_ref':r,'duration_seconds':.25,'overlap_with':'','overlap_offset_seconds':0} for r in refs if bank[r]['kind']=='action'],
        'post_reaction_seconds':segment['reaction_reserve_seconds'],'ending_state':deepcopy(material['initial']),'state_changes':[]}


def review_document(prepared,status='pass'):
    return {'schema':m.VERSION+'/production_review','context_sha256':prepared['context_sha256'],
        'checks':{k:{'status':status,'reason':'OFFLINE synthetic schema result, not content evaluation',
            'evidence':[{'ref':ref,'path':prepared['evidence_catalog'][ref]['path'],'quote':prepared['evidence_catalog'][ref]['quote'][:80]}
                for ref in dict.fromkeys(group[0] for group in prepared['required_evidence_groups'][k])],
            'counterevidence':[],'required_revision':'OFFLINE complete acting revision' if status=='fail' else ''} for k in m.CHECKS}}


@pytest.fixture
def material(tmp_path):return m.load_material(parent_fixture(tmp_path))


def test_real_world_material_pending_qualification_r01_images_and_exact_horizontal_prompt(material):
    p=material['values']['profile']; request=m.direction_request(material,p)
    assert request['payload']['reference_fulltext']==material['values']['inputs']['reference_fulltext']
    assert sum(v==material['values']['inputs']['reference_fulltext'] for v in m.source._strings(json.loads(request['request']['messages'][1]['content'])))==1
    assert len(request['request']['messages'][-1]['content'])==4
    assert all(a['asset_binding']['status']=='unknown' for a in material['manifest']['actors'])
    assert material['initial']['scene_id']==material['values']['goal']['whole_plan']['beats'][0]['scene_id']
    direction=whole_direction(material); native=first_performance(material,direction)
    pr=m.performance_request(material,p,direction)
    assert pr['payload']['current_ensemble']==material['values']['raw_script']['beats'][0]['ensemble']
    rendered=m.render_prompt(material,direction,native); prompt=rendered['prompt']
    assert '1280×704' in prompt and '9:16' not in prompt
    assert rendered['frame_length']%17==5 and rendered['encoded_duration_seconds']<=362/24
    assert abs(rendered['encoded_duration_seconds']-rendered['native_source_duration_seconds']-rendered['encoding_hold_seconds'])<1e-7
    assert rendered['encoding_hold_seconds']<=17/24
    qr=m.review_request(material,p,direction,native)
    assert sum(v==material['values']['inputs']['reference_fulltext'] for v in m.source._strings(json.loads(qr['request']['messages'][1]['content'])))==1
    assert m.validate_review(review_document(qr),qr)['accepted']
    for key,row in m.source.catalog(material['script']).items():
        if row['kind']=='dialogue' and len(row['text'])>=4:
            assert prompt.count(row['text'])==sum(s['kind']=='dialogue' and s['original_text']==row['text'] for s in rendered['performance']['schedule'])


def test_review_exact_field_evidence_unknown_and_cross_context_reject(material):
    d=whole_direction(material); n=first_performance(material,d); q=m.review_request(material,material['values']['profile'],d,n)
    u=review_document(q,'unknown'); assert m.validate_review(u,q)['uncertainties'] and not m.validate_review(u,q)['accepted']
    bad=review_document(q);bad['checks'][m.CHECKS[0]]['evidence'][0]['path']='invented.path'
    with pytest.raises(ValueError,match='exact original'):m.validate_review(bad,q)
    bad=review_document(q);bad['context_sha256']='0'*64
    with pytest.raises(Exception):m.validate_review(bad,q)
    bad=review_document(q)
    title_ref=next(ref for ref,row in q['evidence_catalog'].items() if row['path']=='full_current_script.title')
    bad['checks']['identity_asset_mapping']['evidence']=[{'ref':title_ref,**q['evidence_catalog'][title_ref]}]
    with pytest.raises(Exception):m.validate_review(bad,q)
    bad=deepcopy(d);bad['cast_by_picture']['image3']=bad['cast_by_picture']['image2']
    with pytest.raises(ValueError,match='distinct'):m.compile_direction(bad,material)


def session_fixture(tmp_path,monkeypatch,fault=None):
    parent=parent_fixture(tmp_path); material=m.load_material(parent); holder={}; sent=[]
    counter=m.CountedExecution(tmp_path/'counter');m.write(tmp_path/'counter/AUTH.json',{'OFFLINE':True},True)
    counter.initialize(tmp_path/'counter/AUTH.json');counter.begin_round('round14','OFFLINE production SDK test')
    cfg=m.Config(str(tmp_path/'production'),parent['root'],'offline-first-production',str(tmp_path/'AUTH.json'),
        str(tmp_path/'counter'),'round14',dispatch_lock_path=str(tmp_path/'dispatch.lock'))
    def builder(request):
        def handler(outgoing):
            s=holder['session'];label=s.pending_intent['label'];sent.append(label)
            if fault=='transport':raise httpx.ReadTimeout('offline unknown',request=outgoing)
            d=whole_direction(material)
            n=first_performance(material,d)
            if label.startswith('whole_direction'):value=d
            elif label.startswith('first_performance'):value=n
            else:value=review_document(m.review_request(material,material['values']['profile'],d,n),'unknown' if fault=='semantic_unknown' else 'pass')
            if fault=='direction_unknown' and label.startswith('whole_direction'):value['direction']['availability']='unknown'
            if fault=='performance_unknown' and label.startswith('first_performance'):value['availability']='unknown'
            message={'role':'assistant','content':None,'tool_calls':[{'id':'offline-tool','type':'function',
                'function':{'name':m.clients.text.TOOL_NAME,'arguments':json.dumps(value,ensure_ascii=False)}}]}
            if fault=='missing_tool':message={'role':'assistant','content':json.dumps(value,ensure_ascii=False)}
            payload={'id':'offline-'+label,'model':request['model'],'choices':[{'index':0,'message':message,
                'finish_reason':'length' if fault=='truncated' else 'stop' if fault=='missing_tool' else 'tool_calls'}],
                'usage':{'prompt_tokens':90,'completion_tokens':10,'total_tokens':100}}
            return httpx.Response(200,content=json.dumps(payload,ensure_ascii=False).encode())
        return m.clients.make_client_factory(request,http_client_factory=lambda **kw:httpx.Client(transport=httpx.MockTransport(handler),verify=False,**kw))
    session=m.Session(cfg,text_verifier=lambda root:deepcopy(parent),client_factory_builder=builder);holder['session']=session
    # Keep tests bounded to their explicitly synthetic sources. The actual
    # production preview freezes the whole project import closure.
    actual_hash=m._hashes
    def small_hash(paths):
        paths=list(paths)
        return actual_hash(p for p in paths if not str(Path(p).resolve()).startswith(str(m.PROJECT/'scripts')) and not str(Path(p).resolve()).startswith(str(m.PROJECT/'src')))
    monkeypatch.setattr(m,'_hashes',small_hash)
    p=session.preview();m.write(cfg.authorization_path,session.authorization_template(p),True);session.prepare()
    return session,sent,parent,counter


def test_installed_sdk_three_stage_full_original_handoff_and_sql(tmp_path,monkeypatch):
    session,sent,parent,_=session_fixture(tmp_path,monkeypatch);result=session.run()
    assert result['status']=='first_segment_ready_for_media',result
    assert sent==['whole_direction_01','first_performance_01','first_production_review_01']
    assert result['spend']['effective_calls_started']==704 and result['spend']['effective_reported_tokens']==12345300
    assert result['spend']['historical_pending_ordinals']==[70,160]
    monkeypatch.setattr(m.Session,'open',classmethod(lambda cls,root:session))
    proof=m.verify_first_segment_handoff(session.root,text_verified=parent)
    assert proof['valid'] and proof['first_segment_only'] and not proof['later_segments_acting_approved']
    assert proof['reference_map'][1]['gender_mapping_reviewed']
    with pytest.raises(FileExistsError):session.run()
    altered=deepcopy(parent);altered['identity']['native_script_sha256']='changed'
    with pytest.raises(ValueError,match='text proof differs'):m.verify_first_segment_handoff(session.root,text_verified=altered)
    path=session.root/'FIRST_PRODUCTION_DECISION.json';decision=m.read(path);decision['accepted']=False;m.write(path,decision)
    hp=session.root/'FIRST_SEGMENT_HANDOFF.json';h=m.read(hp);h['artifact_files'][str(path.resolve())]=m.sha(path);m.write(hp,h)
    state=m.read(session.root/'STATE.json');state['production_handoff_sha256']=m.sha(hp);m.write(session.root/'STATE.json',state)
    with pytest.raises(ValueError,match='derived production artifact'):m.verify_first_segment_handoff(session.root,text_verified=parent)


@pytest.mark.parametrize('fault,expected',[
    ('transport','halt_interface_or_unknown'),('missing_tool','halt_interface_or_unknown'),('truncated','halt_interface_or_unknown'),
    ('semantic_unknown','halt_production_review_uncertain')])
def test_unknown_incomplete_or_missing_native_stops_without_restart(tmp_path,monkeypatch,fault,expected):
    session,sent,parent,_=session_fixture(tmp_path,monkeypatch,fault);result=session.run()
    assert result['status']==expected,result
    assert len(sent)==(3 if fault=='semantic_unknown' else 1)
    with pytest.raises(FileExistsError):session.run()
    with pytest.raises((ValueError,FileNotFoundError)):m.verify_first_segment_handoff(session.root,text_verified=parent)


def test_same_parent_regrant_and_completed_round_stop_before_sdk(tmp_path,monkeypatch):
    session,sent,parent,counter=session_fixture(tmp_path,monkeypatch)
    other=m.Session(replace(session.config,root=str(tmp_path/'second'),grant_id='different-grant'),text_verifier=lambda root:deepcopy(parent))
    p=other.preview();m.write(other.config.authorization_path,other.authorization_template(p))
    with pytest.raises((FileExistsError,ValueError)):other.prepare()
    # Restore the separately frozen original authorization, then complete the
    # real counter round; no generic exception is mistaken for a stop gate.
    m.write(session.config.authorization_path,session.authorization_template(m.read(session.root/'PREVIEW.json')))
    counter.complete_round('round14',action='offline stop test',conclusion='completed',evidence_paths=[session.root/'USER_SCOPE.json'])
    assert counter.read()['active_round'] is None
    result=session.run();assert not sent and result['status']=='halt_execution_reconciliation'


@pytest.mark.parametrize('fault,expected,count',[
    ('direction_unknown','halt_whole_direction_uncertain',1),('performance_unknown','halt_first_performance_uncertain',2)])
def test_native_creative_unavailability_is_known_spend_but_never_auto_revised(tmp_path,monkeypatch,fault,expected,count):
    session,sent,_,_=session_fixture(tmp_path,monkeypatch,fault);result=session.run()
    assert result['status']==expected and len(sent)==count,result
    assert result['spend']['new_calls_with_known_usage']==count and result['spend']['new_reported_tokens']==100*count
    assert not (session.root/'FIRST_SEGMENT_HANDOFF.json').exists()
