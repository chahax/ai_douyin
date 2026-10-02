from copy import deepcopy
import json
from src.content_factory.creative_original_director import VERSION, PROMPT, SHOT_SHAPE
from src.content_factory.creative_narrative_focus import prompt_for_stage
from src.content_factory.creative_workflow import CreativeWorkflow, CREATE_REVIEW_PROFILE, _hash, PROMPTS
from src.content_factory.creative_original_prompt import VERSION as WRITER_VERSION
from src.content_factory.reusable_production import read, write
from test_creative_model_profile import setup
from test_creative_event_script import as_events
from test_creative_workflow import FakeClients
from test_reusable_production import design_for


def run_fixture(tmp_path):
    a,b=setup(tmp_path)
    b.metadata['creative_brief']['duration_seconds']=[20,20]
    a[2]=as_events(a[2]);root=tmp_path/'original_director'
    state=CreativeWorkflow(root,clients=FakeClients([*a[:4],design_for(a[3]),a[4]]),model_profile=CREATE_REVIEW_PROFILE,writer_prompt_version=WRITER_VERSION,review_policy_version='legacy').run(b)
    return root,state,b


def test_new_original_director_has_complete_standalone_contract_and_resumes(tmp_path,monkeypatch):
    root,state,b=run_fixture(tmp_path)
    binding=state['original_director_binding']
    assert binding=={'version':VERSION,'prompt':PROMPT}
    record=read(root/'director_shots.json');system=record['request']['messages'][0]['content']
    assert system==PROMPT+prompt_for_stage(state["narrative_focus_binding"], "director_shots")
    assert "purpose不能独自承载叙事" in system
    check_record=read(root/'writer_check__00.json')
    check_context=json.loads(check_record['request']['messages'][-1]['content'])
    assert 'final_video_prompts' in check_context
    transfer=read(root/'NARRATIVE_TRANSFER.json')
    handoff=read(root/'MEDIA_HANDOFF.json')
    assert handoff['narrative_transfer_sha256']==_hash(transfer)
    assert transfer['semantic_approval'] is False
    assert transfer['additional_model_calls']==0
    for row,segment in zip(transfer['shots'],read(root/'SEEDANCE_SEGMENT_PLAN.json')['segments']):
        assert row['compiled_prompt']==segment['payload_template']['content'][0]['text']
    output=read(root/'CREATIVE_OUTPUT_MANIFEST.json')
    assert any(a['path']=='NARRATIVE_TRANSFER.json' for a in output['artifacts'])
    assert json.loads(record['request']['messages'][-1]['content'])['creative_brief']==b.metadata['creative_brief']
    for clause in ('before → 第一条dialogue → during','反应不得抢在刺激之前','开合状态','dialogue_lock','planned_cut_requires_adapter','已被助手驳回','缺少分镜不是故事问题'):
        assert clause in system
    for stale in ('slate','马修','原文旁白','桥头','安妮'):
        assert stale not in system
    assert set(SHOT_SHAPE)=={'style','shots','media_assumptions'}
    expected={'id','beat_id','duration_seconds','purpose','composition','camera','visible_performance','event_lock','dialogue_lock','start_state','end_state','cut_reason','dialogue_mode','continuity_mode','prompt','production_choices'}
    assert set(SHOT_SHAPE['shots'][0])==expected
    monkeypatch.setattr('src.content_factory.creative_original_director.PROMPT','future changed prompt')
    assert CreativeWorkflow(root,clients=FakeClients([])).run(b)['calls_started']==6
    # Also exercise the cached stage rather than only the completed manifest.
    wf=CreativeWorkflow(root,clients=FakeClients([]));wf.state=state
    payload=json.loads(record['request']['messages'][-1]['content'])
    assert wf._stage('director_shots','director',payload,lambda value:None)==record['output']


def test_pre_version_original_director_keeps_old_prompt_and_request_hash(tmp_path):
    root,state,b=run_fixture(tmp_path)
    state.pop('original_director_binding')
    state.pop('narrative_focus_binding')
    record=read(root/'director_shots.json')
    payload=json.loads(record['request']['messages'][-1]['content']);payload.pop('creative_brief')
    old_prompt=PROMPTS['director_shots'].replace('DeepSeek','MiniMax')+'\n'+state['original_brief_priority_binding']['director_execution_prompt']
    record['request']['messages'][0]['content']=old_prompt
    record['request']['messages'][-1]['content']=json.dumps(payload,ensure_ascii=False)
    record['prompt_sha256']=_hash(old_prompt);record['input_sha256']=_hash(payload)
    write(root/'director_shots.json',record);write(root/'state.json',state)
    wf=CreativeWorkflow(root,clients=FakeClients([]));wf.state=state
    assert wf._stage('director_shots','director',payload,lambda value:None)==record['output']
    assert wf.state['calls_started']==6


def test_legacy_run_does_not_bind_original_director(tmp_path):
    a,b=setup(tmp_path);root=tmp_path/'legacy_director'
    state=CreativeWorkflow(root,clients=FakeClients([*a[:4],design_for(a[3]),a[4]]),model_profile=CREATE_REVIEW_PROFILE,review_policy_version='legacy').run(b)
    assert state.get('original_director_binding') is None
    assert PROMPT not in read(root/'director_shots.json')['request']['messages'][0]['content']


def test_new_director_revision_stage_binds_original_contract_and_replays(tmp_path):
    root,state,b=run_fixture(tmp_path)
    wf=CreativeWorkflow(root,clients=FakeClients([{'replace_beats':[]}]))
    wf.state=state
    name='director_revise__01';payload={'affected_beat_ids':[],'script':{},'previous_shots':{},'issues':[]}
    assert wf._stage(name,'director',payload,lambda value:None)=={'replace_beats':[]}
    binding=wf.state['original_director_revision_bindings'][name]
    assert binding['version']=='original_director_revision_v1'
    record=read(root/f'{name}.json')
    assert record['request']['messages'][0]['content']==binding['prompt']+prompt_for_stage(state["narrative_focus_binding"], name)
    assert '局部导演返修' in binding['prompt']
    assert 'slate' not in binding['prompt'] and '原文旁白' not in binding['prompt']
    assert json.loads(record['request']['messages'][-1]['content'])['creative_brief']==b.metadata['creative_brief']
    wf.clients=FakeClients([])
    assert wf._stage(name,'director',payload,lambda value:None)=={'replace_beats':[]}
    assert wf.state['calls_started']==7


def test_existing_director_revision_stage_keeps_legacy_prompt_when_no_binding(tmp_path):
    root,state,b=run_fixture(tmp_path)
    payload={'affected_beat_ids':[],'script':{},'previous_shots':{},'issues':[]}
    # Produce a pre-upgrade cached revision with the same task's director binding absent.
    saved=state.pop('original_director_binding')
    wf=CreativeWorkflow(root,clients=FakeClients([{'replace_beats':[]}]))
    wf.state=state
    name='director_revise__01';wf._stage(name,'director',payload,lambda value:None)
    old=read(root/f'{name}.json')
    wf.state['original_director_binding']=saved
    wf.clients=FakeClients([])
    assert wf._stage(name,'director',payload,lambda value:None)=={'replace_beats':[]}
    assert read(root/f'{name}.json')==old
    assert name not in wf.state.get('original_director_revision_bindings',{})


def test_revision_scope_covers_multiple_evidence_shots_and_shared_assets(tmp_path):
    from src.content_factory.creative_workflow import _director_revision_beats, _bound_director_revision_beats
    script={'beats':[{'id':f'B{i}'} for i in range(1,6)]}
    shots={'shots':[{'id':f'SH{i:02}','beat_id':f'B{i}','start_state':f'首态{i}'} for i in range(1,6)]}
    design={'assets':[{'id':'BG_SHARED','prompt':'共享布局'}], 'shots':[
        {'shot_id':f'SH{i:02}','opening_prompt':f'首帧{i}','asset_ids':['BG_SHARED'] if i in (2,5) else []} for i in range(1,6)]}
    issues=[{'owner':'director','location':'SH01','evidence_refs':[
        {'path':'shots.shots.2.start_state','quote':'首态3'},
        {'path':'production_design.shots.3.opening_prompt','quote':'首帧4'},
        {'path':'production_design.assets.0.prompt','quote':'共享布局'},
        {'path':'shots.shots.99.start_state','quote':'无效'},
    ]}]
    assert _director_revision_beats(script,script,shots,issues,design)==['B1','B2','B3','B4','B5']
    path=tmp_path/'director_revise__01.json'
    assert _bound_director_revision_beats(path,script,script,shots,issues,design)==['B1','B2','B3','B4','B5']
    assert read(tmp_path/'director_revise__01__scope_binding.json')['affected_beat_ids']==['B1','B2','B3','B4','B5']
    # Old cached stages keep their original narrow scope even under new evidence.
    write(path,{'request':{'messages':[{'role':'user','content':json.dumps({'affected_beat_ids':['B1']})}]}})
    assert _bound_director_revision_beats(path,script,script,shots,issues,design)==['B1']
    assert _bound_director_revision_beats(path,script,script,shots,issues,design,force_all=True)==['B1']


def test_revision_scope_uses_shot_ids_not_asset_list_order_and_ignores_invalid_quote():
    from src.content_factory.creative_workflow import _director_revision_beats
    script={'beats':[{'id':'B1'},{'id':'B2'},{'id':'B3'}]}
    shots={'shots':[{'id':'SH01','beat_id':'B1'},{'id':'SH02','beat_id':'B2'},{'id':'SH03','beat_id':'B3'}]}
    design={'shots':[{'shot_id':'SH03','opening_prompt':'正确首帧'}]}
    issues=[{'owner':'director','location':'SH01','evidence_refs':[{'path':'production_design.shots.0.opening_prompt','quote':'正确首帧'}]}]
    assert _director_revision_beats(script,script,shots,issues,design)==['B1','B3']
    issues[0]['evidence_refs'][0]['quote']='错误引文'
    assert _director_revision_beats(script,script,shots,issues,design)==['B1']
