"""CPU contracts and actual local input staging; no model/media inference."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import json
import shutil

from PIL import Image
import pytest

from src.content_factory import visual_h3_continuity_input_v33 as c
from src.content_factory import visual_h3_handoff_v3 as h


def write(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8');return c.binding(path)


def make_entry(tmp_path):
    text='苏墨躺在床上。\n0—5秒，苏墨转头，轻声说：“你们去吧。”镜头转向房门。'
    src=tmp_path/'source.txt';src.write_text(text,encoding='utf-8')
    pieces=[('context','苏墨躺在床上。\n'),('camera','0—5秒，'),('action','苏墨转头，轻声说：'),('audio','“你们去吧。”'),('camera','镜头转向房门。')]
    spans=[];start=0
    for i,(kind,raw) in enumerate(pieces):
        spans.append(dict(id='s'+str(i),kind=kind,start=start,end=start+len(raw),text=raw,sha256=c.sha(raw)));start+=len(raw)
    refs={}
    for who,color in [('su_mo','gray'),('ye_nan','green'),('room','brown'),('first','yellow')]:
        path=tmp_path/(who+'.png');Image.new('RGB',(96,128),color).save(path);refs[who]=c.binding(path)
    row=dict(shot_id='shot1',handoff_binding=None,source=c.binding(src),source_scope=dict(start=0,end=len(text)),source_spans=spans,
        duration=5,audio=[dict(quote_index=0,quote_sha256=c.sha('“你们去吧。”'),speaker='su_mo',mode='onscreen',start=0,end=5)],
        camera_beats=[dict(start=0,end=5,cut=False,framing='medium',actors={'su_mo':dict(visible_parts=['face','torso'],pose='躺在床上')},source_span_ids=['s2'])],
        character_names=dict(su_mo='苏墨',ye_nan='叶南'),canonical_characters={k:refs[k] for k in ('su_mo','ye_nan')},
        canonical_room=refs['room'],actual_first_image=refs['first'],source_state_span_ids=['s0'],
        character_description_span_ids=dict(su_mo=['s0']),postproduction_subtitles=False)
    review=dict(schema=c.REVIEW,reviewed_by='CPU fixture observer, not model inference',target_image=refs['first'],
        canonical_characters=row['canonical_characters'],canonical_room=refs['room'],completion_known=True,outcome_unknown=False,
        checks=dict(topology_coherent=True,room_identity=True,faces=dict(su_mo=True,ye_nan=None),identities=dict(su_mo=True,ye_nan=None)),
        evidence=['Controlled image protocol fixture; actual production needs visual observation.'])
    row['coverage_review']=write(tmp_path/'review.json',review)
    return row


def update_review(row,**changes):
    review=c.read(row['coverage_review'])
    for k,v in changes.items():
        if k=='checks':review['checks'].update(v)
        else:review[k]=v
    row['coverage_review']=write(row['coverage_review']['path'],review)


def test_source_actions_once_independent_audio_and_camera(tmp_path):
    row=make_entry(tmp_path);out=c.evaluate(row)
    assert out['status']=='ready' and out['required_faces']==['su_mo'] and out['direct_video_reference_slots']==0
    text=out['compiled_prompt'];assert text.count('苏墨转头，轻声说：')==1 and text.count('“你们去吧。”')==1
    assert '镜头转向房门。' not in text and '躺在床上' in text
    assert out['postproduction_subtitles'] is False and out['native_text_absence_guaranteed'] is False


def test_audio_voice_does_not_expand_visible_actor_union(tmp_path):
    row=make_entry(tmp_path);row['audio'][0].update(speaker='ye_nan',mode='inner_voice')
    out=c.evaluate(row);assert out['status']=='ready' and out['required_faces']==['su_mo']
    assert '叶南的内心独白，以叶南的画外音呈现' in out['compiled_prompt']
    assert '叶南入镜时嘴唇自然闭合' in out['compiled_prompt'] and '画面中的叶南' not in out['compiled_prompt']


def test_optional_source_audio_context_keeps_exact_known_direction_once(tmp_path):
    row=make_entry(tmp_path);original=Path(row['source']['path']).read_text(encoding='utf-8');prefix='普通话。角色声线为自然中低男声。\n'
    Path(row['source']['path']).write_text(prefix+original,encoding='utf-8');row['source']=c.binding(row['source']['path'])
    row['source_scope']['end']+=len(prefix)
    for span in row['source_spans']:span['start']+=len(prefix);span['end']+=len(prefix)
    row['source_spans'].insert(0,dict(id='sound',kind='context',start=0,end=len(prefix),text=prefix,sha256=c.sha(prefix)))
    row['audio_context_span_ids']=['sound'];text=c.compile_prompt(row)['compiled_prompt']
    assert text.count(prefix.strip())==1 and text.count('“你们去吧。”')==1


@pytest.mark.parametrize('sid',['s4','missing'])
def test_audio_context_cannot_reintroduce_old_camera_or_unbound_text(tmp_path,sid):
    row=make_entry(tmp_path);row['audio_context_span_ids']=[sid]
    with pytest.raises(ValueError,match='audio_context'):c.compile_prompt(row)


@pytest.mark.parametrize('offscreen_voice',[False,True])
def test_canonical_library_extra_actor_description_stays_outside_picture(tmp_path,offscreen_voice):
    row=make_entry(tmp_path);original=Path(row['source']['path']).read_text(encoding='utf-8');prefix='叶南是穿绿色上衣的男孩。\n'
    Path(row['source']['path']).write_text(prefix+original,encoding='utf-8');row['source']=c.binding(row['source']['path']);row['source_scope']['end']+=len(prefix)
    for span in row['source_spans']:span['start']+=len(prefix);span['end']+=len(prefix)
    row['source_spans'].insert(0,dict(id='extra_actor',kind='context',start=0,end=len(prefix),text=prefix,sha256=c.sha(prefix)))
    row['character_description_span_ids']['ye_nan']=['extra_actor']
    if offscreen_voice:row['audio'][0].update(speaker='ye_nan',mode='inner_voice')
    out=c.evaluate(row);assert out['status']=='ready' and out['visible_actors']==['su_mo']
    assert prefix.strip() not in out['compiled_prompt'] and '绿色上衣' not in out['compiled_prompt']
    assert row['source_spans'][0]['text']==prefix
    if offscreen_voice:assert '叶南的内心独白' in out['compiled_prompt']


@pytest.mark.parametrize('value',[None,False])
def test_missing_face_and_ambiguous_topology_make_work_order_not_fourth_person(tmp_path,value):
    row=make_entry(tmp_path);update_review(row,checks=dict(topology_coherent=value))
    out=c.evaluate(row);assert out['status']=='reanchor_required'
    assert out['work_order']['canonical_characters']==row['canonical_characters']
    assert out['work_order']['tail_role']=='continuity_context_only_not_truth_for_bad_or_unknown_topology'
    assert 'head_body_topology_bad_or_unknown' in out['work_order']['reasons']
    assert 'compiled_prompt' not in out


@pytest.mark.parametrize('change',[
    lambda r:r['audio'].clear(),
    lambda r:r['audio'][0].update(quote_sha256='0'*64),
    lambda r:r['audio'].append(deepcopy(r['audio'][0])),
    lambda r:r['audio'][0].update(speaker='foreign'),
    lambda r:r['audio'][0].update(mode='unknown'),
    lambda r:r['audio'][0].pop('mode'),
    lambda r:r['source_spans'][2].update(text='新增开门动作'),
    lambda r:r['source_spans'][2].update(start=0),
    lambda r:r.update(shot_id='../escape'),
    lambda r:r.update(postproduction_subtitles=True),
    lambda r:r['camera_beats'][0]['actors']['su_mo'].update(pose='凭空站起来'),
])
def test_source_audio_and_camera_tamper_rejected(tmp_path,change):
    row=make_entry(tmp_path);change(row)
    with pytest.raises((ValueError,KeyError)):c.evaluate(row)


def test_all_context_cannot_hide_source_quotes(tmp_path):
    row=make_entry(tmp_path)
    for s in row['source_spans']:s['kind']='context'
    row['audio']=[];row['camera_beats'][0].update(actors={},source_span_ids=[])
    with pytest.raises(ValueError,match='all_source_quote'):c.evaluate(row)


def test_unclassified_nonwhitespace_gap_and_old_camera_need_source_classification(tmp_path):
    row=make_entry(tmp_path);row['source_spans'].pop()
    assert c.evaluate(row)['status']=='source_classification_required'
    row=make_entry(tmp_path);row['source_spans'][-1]['kind']='action';row['camera_beats'][0]['source_span_ids'].append('s4')
    assert c.evaluate(row)['classification_issues'][0]['span_id']=='s4'


@pytest.mark.parametrize('change',[
    lambda r:r.update(evidence=[]),lambda r:r.pop('evidence'),
    lambda r:r.update(completion_known=False),lambda r:r.pop('outcome_unknown'),
    lambda r:r['checks'].update(topology_coherent=1),
    lambda r:r.update(target_image=dict(path='wrong',sha256='0'*64)),
])
def test_review_must_be_target_bound_known_evidenced_tristate(tmp_path,change):
    row=make_entry(tmp_path);review=c.read(row['coverage_review']);change(review);row['coverage_review']=write(row['coverage_review']['path'],review)
    with pytest.raises(ValueError):c.evaluate(row)


def test_preview_and_prepare_are_cpu_not_ready_approval(tmp_path):
    row=make_entry(tmp_path);update_review(row,checks=dict(identities=dict(su_mo=None,ye_nan=None)))
    plan=write(tmp_path/'spec.json',dict(schema=c.SCHEMA,shots=[row]))
    draft=c.preview_prompt(plan,'shot1');assert draft['dispatchable'] is False and draft['status']=='draft_not_dispatchable'
    assert draft['compiled_prompt'].count('“你们去吧。”')==1
    report=c.prepare(plan,tmp_path/'reports');assert report['ready']==0 and report['shots'][0]['status']=='reanchor_required'
    assert not (tmp_path/'reports/REQUEST.json').exists()


def test_actual_png_bytes_and_frozen_plan_are_checked(tmp_path):
    row=make_entry(tmp_path);plan=write(tmp_path/'spec.json',dict(schema=c.SCHEMA,shots=[row]))
    Image.new('RGB',(96,128),'blue').save(row['actual_first_image']['path'])
    with pytest.raises(ValueError,match='bound_input'):c.preflight(plan,'shot1')
    write(plan['path'],dict(schema=c.SCHEMA,shots=[]))
    with pytest.raises(ValueError,match='bound_input'):c.preflight(plan,'shot1')


def test_reanchor_metadata_without_original_work_order_or_generation_refused(tmp_path):
    row=make_entry(tmp_path);update_review(row,checks=dict(identities=dict(su_mo=None,ye_nan=None)))
    row['reanchor']=dict(image=row['canonical_characters']['su_mo'],coverage_review=row['coverage_review'],
        work_order_sha256='0'*64,generation_receipt=dict(kind='metadata_only'))
    with pytest.raises(ValueError,match='upstream_asset_generation'):c.evaluate(row)


def _legacy_fixture(tmp_path):
    path=Path(__file__).with_name('test_visual_h3_handoff_v3.py')
    spec=importlib.util.spec_from_file_location('v33_legacy_fixture',path);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    service=SimpleNamespace(input=tmp_path/'input',output=tmp_path/'output',url='http://127.0.0.1:19997')
    service.input.mkdir();service.output.mkdir()
    return mod.setup(tmp_path,service,shots=1),service


def _hook_setup(tmp_path):
    (asset,run,cfg),service=_legacy_fixture(tmp_path);snapshot,ready,bindings=h.validate_ready(asset)
    row=make_entry(tmp_path);frame=ready['first_frames']['shot1'];row['actual_first_image']={k:frame[k] for k in ('path','sha256')}
    review=c.read(row['coverage_review']);review['target_image']=row['actual_first_image'];row['coverage_review']=write(tmp_path/'review.json',review)
    row['handoff_binding']=dict(packet_sha256=c.digest(snapshot['plan']['packet']),shot_sha256=c.digest(bindings['shots'][0]))
    spec=write(tmp_path/'continuity.json',dict(schema=c.SCHEMA,shots=[row]));cfg['continuity_input_plan']=spec
    return asset,run,cfg,row,service


def test_explicit_hook_stages_real_png_and_revalidates_before_dispatch(tmp_path):
    asset,run,cfg,row,service=_hook_setup(tmp_path)
    result=h.prepare_from_ready(asset,run,cfg);assert result['status']=='prepared'
    plan=h.read(run/'PLAN.json');shot=plan['shots'][0];graph=h.read(run/'shots/shot1/workflow_api.json')
    assert c.binding(service.input/shot['input_name'])['sha256']==row['actual_first_image']['sha256']
    assert graph['condition']['inputs']['prompt']==c.compile_prompt(row)['compiled_prompt']
    assert shot['subtitles']['enabled'] is False and 'native_prompt' not in shot
    # A current review change blocks new dispatch, frozen original collection
    # data stays loadable through current=False without consulting that file.
    original_entry_sha=c.digest(row);update_review(row,checks=dict(topology_coherent=None))
    with pytest.raises(ValueError):h._load(run)
    assert h._load(run,current=False)[1]['shots'][0]['continuity_input']['entry_sha256']==original_entry_sha


def test_hook_work_order_is_saved_before_staging_or_any_plan(tmp_path):
    asset,run,cfg,row,service=_hook_setup(tmp_path);update_review(row,checks=dict(topology_coherent=None))
    cfg['continuity_input_plan']=write(tmp_path/'continuity.json',dict(schema=c.SCHEMA,shots=[row]))
    with pytest.raises(ValueError,match='reanchor_required'):h.prepare_from_ready(asset,run,cfg)
    assert list((run/'continuity_workorders').glob('*.json')) and not (run/'PLAN.json').exists()
    assert not list(service.input.rglob('first_frame*'))


def test_hook_explicit_mutual_exclusion_and_legacy_graph_default(tmp_path):
    (asset,run,cfg),service=_legacy_fixture(tmp_path)
    h.prepare_from_ready(asset,run,cfg);old=h.read(run/'shots/shot1/workflow_api.json');plan=h.read(run/'PLAN.json')
    assert 'continuity_input_plan' not in plan['config'] and 'continuity_input' not in plan['shots'][0]
    shot=h.validate_ready(asset)[2]['shots'][0];frame=plan['shots'][0]['first_frame'];row=plan['shots'][0]
    rebuilt=h.build_graph(h.read(cfg.get('base_workflow',h.DEFAULT_BASE)),shot,frame,row['timing'],row['input_name'],row['scope'],96,128)
    assert old==rebuilt
    cfg.update(continuity_input_plan=dict(path='unused',sha256='0'*64),native_prompt_plan=dict(path='unused',sha256='0'*64),native_prompt_contract='official_multimodal/v19')
    with pytest.raises(ValueError,match='exclusive'):h.prepare_from_ready(asset,run,cfg)


def test_legacy_ready_metadata_is_not_new_reanchor_generation_proof(tmp_path):
    (asset,run,cfg),service=_legacy_fixture(tmp_path)
    snapshot,ready,bindings=h.validate_ready(asset)
    child=tmp_path/'entry';child.mkdir();row=make_entry(child)
    refs=bindings['shots'][0]['references']
    row['canonical_characters']={'man':c.binding(h.pipeline._image_path(snapshot['plan'],next(r for r in refs if r['kind']=='character')))};row['character_names']={'man':'苏墨'}
    row['canonical_room']=c.binding(h.pipeline._image_path(snapshot['plan'],next(r for r in refs if r['kind']=='place')));row['audio'][0]['speaker']='man'
    row['character_description_span_ids']={'man':['s0']}
    row['camera_beats'][0]['actors']={'man':dict(visible_parts=['face','torso'],pose='躺在床上')}
    rev=c.read(row['coverage_review']);rev.update(canonical_characters=row['canonical_characters'],canonical_room=row['canonical_room'])
    rev['checks'].update(faces=dict(man=None),identities=dict(man=None));row['coverage_review']=write(tmp_path/'review.json',rev)
    work=c.evaluate(row)['work_order'];frame=ready['first_frames']['shot1']
    row['reanchor']=dict(image={k:frame[k] for k in ('path','sha256')},coverage_review=row['coverage_review'],work_order_sha256=c.digest(work),
        generation_receipt=dict(kind='asset_ready',asset_run=str(asset),shot_id='shot1',ready=c.binding(asset/'H3_INPUT_READY.json')))
    with pytest.raises(ValueError,match='native_still_generation_proof'):c.evaluate(row)


def test_scope_must_not_cut_through_source_quote(tmp_path):
    row=make_entry(tmp_path);text=Path(row['source']['path']).read_text(encoding='utf-8');start=text.index('你们');end=start+2
    row['source_scope']=dict(start=start,end=end)
    row['source_spans']=[dict(id='inside',kind='context',start=start,end=end,text=text[start:end],sha256=c.sha(text[start:end]))]
    row['audio']=[];row['source_state_span_ids']=[];row['camera_beats'][0].update(actors={},source_span_ids=[])
    row['character_description_span_ids']={}
    with pytest.raises(ValueError,match='scope_cuts_quote'):c.evaluate(row)


def test_compiler_uses_photographic_language_and_preserves_actions_once(tmp_path):
    row=make_entry(tmp_path);text=c.compile_prompt(row)['compiled_prompt']
    for word in ('face_close','hands_close','medium','wide','detail','torso','source_span','【本句'):
        assert word not in text
    assert text.count('苏墨转头，轻声说：')==1
    assert '<d>' not in text and '[Mandarin' not in text and 'says in' not in text


def _three_adapter(tmp_path,enabled=False):
    row=make_entry(tmp_path)
    path=tmp_path/'third.png';Image.new('RGB',(96,128),'red').save(path)
    row['canonical_characters']['third']=c.binding(path);row['character_names']['third']='叶西决'
    row['character_description_span_ids'].update(ye_nan=['s0'],third=['s0'])
    actor=dict(visible_parts=['face','torso'],pose='躺在床上')
    row['camera_beats'][0]['actors'].update(ye_nan=deepcopy(actor),third=deepcopy(actor))
    update_review(row,canonical_characters=row['canonical_characters'],checks=dict(faces={k:True for k in row['canonical_characters']},identities={k:True for k in row['canonical_characters']}))
    spec=write(tmp_path/'three_spec.json',dict(schema=c.SCHEMA,shots=[row]))
    for name in ('input','output','gpu'):(tmp_path/name).mkdir()
    pause=tmp_path/'legacy_pause.json';pause.write_text('{}',encoding='utf-8')
    cfg=dict(service_url='http://127.0.0.1:19997',input_root=str(tmp_path/'input'),output_root=str(tmp_path/'output'),gpu_lock_root=str(tmp_path/'gpu'),
        protected_pause_path=str(pause),runs_root=str(tmp_path/'visual_h3_v3'),width=96,height=128,video_enabled=enabled)
    run=tmp_path/'visual_h3_v3'/'explicit_three'
    h.prepare_from_continuity(spec,run,cfg)
    return row,spec,cfg,run


def test_explicit_v33_adapter_supports_three_people_without_v3_ready(tmp_path):
    row,spec,cfg,run=_three_adapter(tmp_path)
    p=h.read(run/'PLAN.json');assert p['upstream_contract']=='h3_continuity_input/v33'
    assert len(c.handoff_snapshot(spec,cfg)[2]['shots'][0]['visible_cast'])==3
    assert not (tmp_path/'H3_INPUT_READY.json').exists()
    assert h.submit_next(run)['dispatch']=='video_policy_disabled'
    frozen=h.read(run/'shots/shot1/workflow_api.json')
    assert frozen['condition']['class_type']=='MiniMaxH3ImageToVideo' and set(frozen)==set(h.CLASSES)
    update_review(row,checks=dict(topology_coherent=None))
    with pytest.raises(ValueError):h._load(run)
    assert h._load(run,current=False)[1]==p


@pytest.fixture(scope='module')
def cpu_av(tmp_path_factory):
    path=Path(__file__).with_name('test_visual_h3_handoff_v3.py')
    spec=importlib.util.spec_from_file_location('v33_media_fixture',path);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod.native_media.__wrapped__(tmp_path_factory)


def _native_stub(monkeypatch,cfg):
    calls=[];histories={}
    def request(config,route,value=None):
        calls.append((route,deepcopy(value)))
        if route=='/system_stats':return dict(system=dict(argv=['main.py','--input-directory',cfg['input_root'],'--output-directory',cfg['output_root']]))
        if route=='/queue':return dict(queue_running=[],queue_pending=[])
        if route=='/prompt':return dict(prompt_id='v33_cpu_original_native',node_errors={})
        if route.startswith('/history/'):return histories
        raise AssertionError(route)
    monkeypatch.setattr(h,'_http',request)
    return calls,histories


def test_explicit_enabled_dispatch_and_original_id_collect_after_source_review_change(tmp_path,monkeypatch,cpu_av):
    row,spec,cfg,run=_three_adapter(tmp_path,True);calls,histories=_native_stub(monkeypatch,cfg)
    result=h.submit_next(run);assert result['status']=='running'
    folder=run/'shots/shot1';request=h.read(folder/'REQUEST.json');pid='v33_cpu_original_native'
    assert h.read(folder/'RESPONSE.json')['prompt_id']==pid and (folder/'CLAIM.json').is_file()
    assert not (tmp_path/'PLAN.json').exists() and (tmp_path/'CONTINUITY_INPUT_DISPATCH.lock').exists()
    assert len([x for x in calls if x[0]=='/prompt'])==1
    h.submit_next(run);assert len([x for x in calls if x[0]=='/prompt'])==1
    graph=request['prompt'];outputs={}
    for role,key,extension,source in [('video','images','mp4','video.mp4'),('audio','audio','flac','audio.flac'),('first','images','png','frame.png'),('last','images','png','frame.png')]:
        rel=Path(graph['save_'+role]['inputs']['filename_prefix']+'_00001_.'+extension);dest=Path(cfg['output_root'])/rel
        dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(cpu_av/source,dest)
        outputs['save_'+role]={key:[dict(filename=dest.name,subfolder=rel.parent.as_posix(),type='output')]}
    histories[pid]=dict(prompt=[0,pid,graph],status=dict(completed=True,status_str='success',messages=[['execution_success',{}]]),outputs=outputs)
    update_review(row,checks=dict(topology_coherent=None))
    collected=h.poll_collect(run)
    assert collected['status']=='blocked_upstream_changed' and h.read(folder/'STATE.json')['status']=='technical_saved'
    receipt=h.read(folder/'RESULT.json');assert receipt['prompt_id']==pid and set(receipt['files'])=={'video','audio','first','last'}
    assert receipt['continuity_input']['compiled_prompt_utf8_sha256']==c.sha(graph['condition']['inputs']['prompt'])
    assert len([x for x in calls if x[0]=='/prompt'])==1
    with pytest.raises(ValueError):h.submit_next(run)
    assert len([x for x in calls if x[0]=='/prompt'])==1


def test_enabled_dispatch_rechecks_png_after_queue_before_claim(tmp_path,monkeypatch):
    row,spec,cfg,run=_three_adapter(tmp_path,True);calls,histories=_native_stub(monkeypatch,cfg)
    shot=h.read(run/'PLAN.json')['shots'][0];Path(cfg['input_root'],shot['input_name']).write_bytes(b'changed')
    with pytest.raises(ValueError,match='staged_first_frame'):h.submit_next(run)
    assert not (run/'shots/shot1/CLAIM.json').exists() and not any(x[0]=='/prompt' for x in calls)


def _spatial_fixture(tmp_path):
    path=Path(__file__).with_name('test_visual_spatial_stills_v24.py')
    spec=importlib.util.spec_from_file_location('v33_spatial_fixture',path);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    run,kwargs=mod.prepared.__wrapped__(tmp_path);mod.skin_receipt(kwargs)
    child=tmp_path/'entry';child.mkdir();row=make_entry(child)
    refs=mod.s.read(kwargs['inputs'])['references'];row['canonical_characters']={r['entity_id']:r['image'] for r in refs}
    row['character_names']=dict(su_mo='苏墨',ye_nan='叶南',ye_xijue='叶西决')
    row['character_description_span_ids']={k:['s0'] for k in row['canonical_characters']}
    row['camera_beats'][0]['actors']={k:dict(visible_parts=['face','torso'],pose='躺在床上') for k in row['canonical_characters']}
    update_review(row,canonical_characters=row['canonical_characters'],checks=dict(faces={k:True for k in row['canonical_characters']},identities={k:None for k in row['canonical_characters']}))
    plan=write(tmp_path/'continuity.json',dict(schema=c.SCHEMA,shots=[row]));report=c.evaluate(row)
    spatial=mod.s.read(mod.s.read(kwargs['handoff'])['plan']['path']);item_state=mod.s._state(spatial,'S01_start')
    source_review=write(tmp_path/'state_review.json',dict(schema='h3_reanchor_source_state_review/v33',
        work_order_sha256=report['work_order_sha256'],entry_base_sha256=c.digest(row),spatial_plan=mod.s.read(kwargs['handoff'])['plan'],
        item_id='S01_start',state_sha256=c.digest(item_state),canonical_characters=row['canonical_characters'],canonical_room=row['canonical_room'],
        source_current_state_matches=True,room_identity_matches=True,completion_known=True,outcome_unknown=False,
        reviewed_by='Controlled CPU fixture',evidence=['Protocol-only stage/source review, no media semantic qualification.']))
    result=c.prepare_reanchor(plan,'shot1',run,**kwargs,item_id='S01_start',source_binding_review=source_review)
    return mod,run,row,result


def _complete_spatial_fixture(mod,run,row,prepared):
    folder=run/'batches/reanchor_shot1';p=mod.s.read(folder/'PLAN.json');graph=mod.s.read(folder/'workflow_api.json');pid='cpu_v33_saved_image'
    write(folder/'REQUEST.json',dict(prompt=graph));write(folder/'CLAIM.json',dict(graph_sha256=p['graph_sha256'],input_sha256=mod.jobs.digest(p['inputs'])))
    write(folder/'RESPONSE.json',dict(prompt_id=pid));state=mod.s.read(folder/'STATE.json');state.update(status='native_complete',prompt_id=pid);write(folder/'STATE.json',state)
    outputs={}
    for nid,node in graph.items():
        if node['class_type']=='SaveImage':
            relative=Path(node['inputs']['filename_prefix']+'_00001_.png');path=Path(p['config']['output_root'])/relative
            path.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(736,1312),'gray').save(path)
            outputs[nid]=dict(images=[dict(filename=path.name,subfolder=relative.parent.as_posix(),type='output')])
    write(folder/'HISTORY.json',{pid:dict(prompt=[0,pid,graph],status=dict(completed=True,status_str='success'),outputs=outputs)})
    # tick sees native_complete and only performs existing local CPU collection.
    mod.s.tick(run,'reanchor_shot1');candidate=mod.s.read(folder/'CANDIDATES.json')['items'][0]
    anchor_review=c.read(row['coverage_review']);anchor_review.update(target_image=candidate['image'],work_order_sha256=prepared['work_order_sha256'],source_current_state_matches=True)
    anchor_review['checks'].update(identities={k:True for k in row['canonical_characters']})
    receipt=deepcopy(prepared['receipt_template']);receipt['candidates']=c.binding(folder/'CANDIDATES.json')
    row['reanchor']=dict(image=candidate['image'],coverage_review=write(run/'anchor_review.json',anchor_review),
        work_order_sha256=prepared['work_order_sha256'],generation_receipt=receipt)
    return folder


def test_real_three_person_producer_prepare_stages_four_images_without_post(tmp_path):
    mod,run,row,result=_spatial_fixture(tmp_path);folder=run/'batches/reanchor_shot1'
    p=mod.s.read(folder/'PLAN.json');assert len(p['inputs'])==4
    assert all(Path(x['staged_path']).is_file() for x in p['inputs']) and not (folder/'REQUEST.json').exists()
    assert result['status']=='image_job_prepared_not_submitted' and result['model_calls']==0
    assert len([n for n in mod.s.read(folder/'workflow_api.json').values() if n['class_type']=='SaveImage'])==1


def test_saved_four_reference_still_receipt_allows_reviewed_three_person_reanchor(tmp_path):
    mod,run,row,result=_spatial_fixture(tmp_path);folder=_complete_spatial_fixture(mod,run,row,result)
    out=c.evaluate(row);assert out['status']=='ready' and out['required_faces']==['su_mo','ye_nan','ye_xijue']
    assert out['first_image']==row['reanchor']['image'] and len(out['generation_receipt']['consumed_inputs'])==4
    assert out['generation_receipt']['canonical_room_role']=='source_bound_review_of_designed_geometry_stage_not_direct_room_pixels'
    assert out['generation_receipt']['actual_generation_inputs_verified'] is True


@pytest.mark.parametrize('mutation',[
    'staged_pixel','request','history','result','source_state_review','review_unknown','anchor_state_unknown','orphan_portrait',
])
def test_spatial_receipt_requires_actual_conditioning_and_bound_known_reviews(tmp_path,mutation):
    mod,run,row,result=_spatial_fixture(tmp_path);folder=_complete_spatial_fixture(mod,run,row,result)
    if mutation=='staged_pixel':
        p=mod.s.read(folder/'PLAN.json');Path(p['inputs'][1]['staged_path']).write_bytes(b'changed')
    elif mutation=='request':
        value=mod.s.read(folder/'REQUEST.json');value['prompt']['S01_start__positive']['inputs']['text']='changed';write(folder/'REQUEST.json',value)
    elif mutation=='history':
        value=mod.s.read(folder/'HISTORY.json');value['cpu_v33_saved_image']['status']['completed']=False;write(folder/'HISTORY.json',value)
    elif mutation=='result':
        value=mod.s.read(folder/'RESULT.json');value['images'][0]['sha256']='0'*64;write(folder/'RESULT.json',value)
    elif mutation=='source_state_review':
        ref=row['reanchor']['generation_receipt']['source_binding_review'];v=c.read(ref);v['state_sha256']='0'*64
        row['reanchor']['generation_receipt']['source_binding_review']=write(ref['path'],v)
    elif mutation=='review_unknown':
        ref=row['reanchor']['coverage_review'];v=c.read(ref);v['checks']['identities']['su_mo']=None;row['reanchor']['coverage_review']=write(ref['path'],v)
    elif mutation=='anchor_state_unknown':
        ref=row['reanchor']['coverage_review'];v=c.read(ref);v['source_current_state_matches']=None;row['reanchor']['coverage_review']=write(ref['path'],v)
    elif mutation=='orphan_portrait':
        # Full graph/receipt hashes are re-frozen consistently to ensure the
        # dependency check itself detects a portrait disconnected from output.
        graph=mod.s.read(folder/'workflow_api.json')
        target=next(n for n,v in graph.items() if v['class_type']=='ReferenceLatent' and 'ref_3' in n)
        graph[target]['inputs']['latent']=['S01_start__ref_2',0]
        p=mod.s.read(folder/'PLAN.json');p['graph_sha256']=mod.jobs.digest(graph);write(folder/'PLAN.json',p);write(folder/'workflow_api.json',graph)
    with pytest.raises((ValueError,KeyError,StopIteration)):c.evaluate(row)
