"""Real frozen S03 inputs, synthetic CPU media, completely mocked native HTTP."""
from copy import deepcopy
from pathlib import Path
import shutil
import subprocess
import wave

import pytest
from PIL import Image

from src.content_factory import h3_repair_generation_adapter_v1 as repair
from src.content_factory import h3_universal_direction_execution_v1 as universal
from src.content_factory import h3_asset_flow_execution_v1 as frozen_transport

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT/'data/video_generation/h3_universal_direction_minute_20261114_v1'
OLD_NR = OLD/'visual_h3_v3'/(OLD.name+'_S03')


def write(path, value):
    import json
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


@pytest.fixture(scope='module')
def CPU_files(tmp_path_factory):
    folder = tmp_path_factory.mktemp('synthetic_CPU_media')
    audio = folder/'raw.wav'
    with wave.open(str(audio), 'wb') as wav:
        wav.setnchannels(2); wav.setsampwidth(2); wav.setframerate(32000)
        wav.writeframes(b'\x64\x00\x9c\xff'*482400)
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','color=c=blue:s=736x1312:r=24',
        '-i',str(audio),'-frames:v','362','-c:v','libx264','-threads','1','-preset','ultrafast',
        '-c:a','aac','-ar','32000','-ac','2',str(folder/'video_00001_.mp4')],capture_output=True,check=True,timeout=60)
    subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(audio),'-c:a','flac',str(folder/'audio_00001.flac')],
                   capture_output=True,check=True,timeout=30)
    for role in ('first','last'): Image.new('RGB',(736,1312),'blue').save(folder/(role+'_00001_.png'))
    return folder


@pytest.fixture
def env(tmp_path, monkeypatch, CPU_files):
    case = tmp_path/'new_repair_case'; case.mkdir()
    plan = repair.read(OLD_NR/'PLAN.json')
    old_profiles = repair.flow._bound(plan['prompt_profiles'])
    active = dict(schema='library_voice_profiles/v1', profiles={c:old_profiles['profiles'][c] for c in repair.ACTIVE})
    profiles = repair.freeze(case/'ACTIVE_PROFILES.json', active)
    evidence = repair.freeze(case/'EVIDENCE.json', dict(CPU_fixture_only=True, reported_issue='opening_extra_audio'))
    recipe = dict(schema=repair.RECIPE, segment_id='S03', original_native_plan=repair.bind(OLD_NR/'PLAN.json'),
        offline_output=plan['offline_output'], source_case=repair.flow._bound(plan['live_manifest'])['source_case'],
        asset_manifest=repair.bind(Path(plan['offline_output'])/'INPUT_MANIFEST.json'),
        policy=repair.bind(OLD/'UNIVERSAL_POLICY.json'), origin_profiles=plan['prompt_profiles'],active_profiles=profiles,evidence=[evidence])
    recipe_binding = repair.freeze(case/'RECIPE.json', recipe)
    cfg = repair.read(OLD/'EXECUTION_CONFIG.json')
    for key in ('input_root','output_root','gpu_lock_root'):
        p=case/key;p.mkdir();cfg[key]=str(p)
    cfg['runs_root']=str(case/'visual_h3_v3')
    pause=case/'protected_old_PAUSE.json';write(pause,dict(immutable_old_pause=True));cfg['protected_pause_path']=str(pause)
    run=case/'visual_h3_v3'/'fresh_S03_A001';api=repair.for_run(run,recipe_binding)
    monkeypatch.setattr(api,'_service_anchor',lambda m:cfg)
    calls=dict(posts=0,gets=[],response=dict(prompt_id='CPU_FRESH_S03_UUID'),histories={})
    def http(config,route,value=None):
        if value is not None:
            assert route=='/prompt';calls['posts']+=1
            if isinstance(calls['response'],Exception):raise calls['response']
            pid=calls['response'].get('prompt_id')
            if pid:
                g=deepcopy(value['prompt']);outputs={}
                for role in ('video','audio','first','last'):
                    scope=Path(g['save_'+role]['inputs']['filename_prefix']).parent
                    target=Path(cfg['output_root'])/scope;target.mkdir(parents=True,exist_ok=True)
                    source=next(CPU_files.glob(role+'_*'));shutil.copyfile(source,target/source.name)
                    outputs['save_'+role]={('audio' if role=='audio' else 'images'):
                        [dict(filename=source.name,subfolder=scope.as_posix(),type='output')]}
                calls['histories'][pid]=dict(prompt=[1,pid,g],outputs=outputs,status=dict(completed=True,status_str='success'))
            return deepcopy(calls['response'])
        calls['gets'].append(route)
        if route=='/system_stats':return dict(system=dict(argv=['main.py','--input-directory',cfg['input_root'],'--output-directory',cfg['output_root']]))
        if route=='/queue':return dict(queue_running=[],queue_pending=[])
        if route.startswith('/history/'):return {k:v for k,v in calls['histories'].items() if k==route.rsplit('/',1)[1]}
        raise AssertionError('unexpected mocked endpoint '+route)
    monkeypatch.setattr(api.native,'_http',http)
    auth=repair.freeze(case/'AUTH.json',dict(max_attempts=1,local_H3_only=True,CPU_fixture_only=True))
    original_result=repair.read(OLD_NR/'shots/S03/RESULT.json')
    original=dict(id='S03',native_id=original_result['prompt_id'],result=repair.bind(OLD_NR/'shots/S03/RESULT.json'),
        media={k:original_result['files']['video'][k] for k in ('path','sha256')},source_case=recipe['source_case'],
        asset_manifest=recipe['asset_manifest'],frames=362,fps=24,audio_rate=48000,audio_samples=724000)
    spec=dict(max_attempts=1,repair_segment_id='S03',mode='regen_segment',case_binding=recipe['source_case'],
        asset_manifest=recipe['asset_manifest'],evidence=[evidence],authorization=auth,segments=[original])
    sb=repair.freeze(case/'SPEC.json',spec)
    req=dict(schema='media_repair_request/v1',run=str(case),spec=sb,attempt_id='A001',attempt_dir=str(case/'attempts/A001'),
        segment_id='S03',phase='submission',mode='regen_segment',original=original,case_binding=recipe['source_case'],
        asset_manifest=recipe['asset_manifest'],evidence=[evidence],authorization=auth,candidate=None)
    return dict(case=case,run=run,api=api,cfg=cfg,recipe=recipe,rb=recipe_binding,auth=auth,req=req,calls=calls)


def prepare(e):
    return e['api'].prepare(e['run'],e['recipe']['offline_output'],e['cfg'],prompt_profiles=e['recipe']['active_profiles'],authorization=e['auth'])


def executor(e,monkeypatch):
    obj=repair.GenerationExecutor(e['run'],e['rb'])
    # Isolated test factory retains same synthetic service anchor; production
    # uses the unchanged real anchor and full recomputed staging checks.
    monkeypatch.setattr(obj.api,'_service_anchor',lambda m:e['cfg'])
    return obj


def approve(e):
    repair.freeze(e['run']/'LAUNCH_APPROVAL.json',dict(schema=e['api'].LAUNCH,request=e['api'].launch_request(e['run']),
        approved_by='root',evidence=['Synthetic CPU fixture, zero real native POST.']))


def test_actual_derive_changes_only_audio_layout_and_two_voice_lines(env):
    e=env;api=e['api'];old_functions=(frozen_transport._derive,frozen_transport._load,universal.asset_for_run)
    old_api=universal.asset_for_run(e['run'],e['recipe']['policy'])
    before,g,_,_=old_api._derive(e['recipe']['offline_output'],e['run'],e['recipe']['origin_profiles'])
    after,patched,entry,_=api._derive(e['recipe']['offline_output'],e['run'],e['recipe']['active_profiles'])
    restored=deepcopy(patched);restored['condition']['inputs']['prompt']=g['condition']['inputs']['prompt']
    assert restored==g and after['references']==before['references'] and after['actor_state']==before['actor_state']
    text=after['compiled_prompt'];names=entry['character_names']
    assert [line.split('的声线：')[0] for line in text.splitlines() if '的声线：' in line]==['叶西决','叶东']
    assert text.index('我被踹倒了')<text.index('<Picture 1>')
    assert repair.flow.core.QUOTE.findall(text)==repair.flow.core.QUOTE.findall(before['compiled_prompt'])
    assert after['repair_generation']['active_speaker_ids']==list(repair.ACTIVE)
    assert after['guide']['image']['sha256'].startswith('5410bdda')
    assert (frozen_transport._derive,frozen_transport._load,universal.asset_for_run)==old_functions and e['calls']['posts']==0


def test_prepared_actual_nine_refs_enter_VAE_and_guide_with_active_profiles(env):
    e=env;assert prepare(e)['status']=='prepared'
    _,plan,row,folder=e['api']._load(e['run']);g=repair.read(folder/'workflow_api.json');m=repair.flow._bound(plan['live_manifest'])
    assert len(m['references'])==9 and plan['prompt_profiles']==e['recipe']['active_profiles']
    assert g['condition']['inputs']['vae']==['119',0] and g['guide_start']['inputs']['image']==['ref_8',0]
    for i,r in enumerate(m['references']):
        assert repair.bind(Path(plan['config']['input_root'])/r['input_name'])['sha256']==r['image']['sha256']
        assert g['condition']['inputs'][f'ref_images.ref_image_{i}']==[f'ref_{i}',0]
    assert e['calls']['posts']==0 and row['timing']['native_frames']==362


def test_controller_submit_unknown_has_one_claim_and_never_rePOSTs(env,monkeypatch):
    e=env;prepare(e);approve(e);obj=executor(e,monkeypatch);e['calls']['response']=TimeoutError('CPU uncertain POST')
    assert obj.submit(e['req'])['status']=='outcome_unknown'
    original=(e['run']/'shots/S03/CLAIM.json').read_bytes()
    assert obj.submit(e['req'])['status']=='outcome_unknown' and e['calls']['posts']==1
    assert (e['run']/'shots/S03/CLAIM.json').read_bytes()==original


@pytest.mark.parametrize('change',['source','assets','attempt','authority'])
def test_controller_mismatched_request_blocked_before_POST(env,monkeypatch,change):
    e=env;prepare(e);approve(e);obj=executor(e,monkeypatch);req=deepcopy(e['req'])
    if change=='attempt':req['attempt_id']='A002'
    else:req[dict(source='case_binding',assets='asset_manifest',authority='authorization')[change]]=e['rb']
    with pytest.raises(ValueError):obj.submit(req)
    assert e['calls']['posts']==0 and not (e['run']/'shots/S03/CLAIM.json').exists()


def test_actual_mock_native_collect_three_clock_candidate_is_idempotent(env,monkeypatch):
    e=env;prepare(e);approve(e);obj=executor(e,monkeypatch)
    submitted=obj.submit(e['req']);assert submitted['status']=='submitted'
    req=dict(e['req'],phase='collection',native_id=submitted['native_id'],submission=submitted)
    saved=obj.collect(req);assert saved['status']=='saved';c=repair.flow._bound(saved['candidate'])
    assert c['nominal_frame_clock']==dict(frames=362,fps=24)
    assert c['native_audio_clock']['rate']==32000 and c['native_audio_clock']['samples']==482400
    assert c['delivery_clock']==dict(rate=48000,samples=724000)
    assert not ({'frames','fps','audio_rate','audio_samples'} & set(c))
    proof=repair.flow._bound(c['audio_clock_receipt']);assert proof['content_trimmed'] is False and proof['normalization_verified'] is True
    assert c['media']['sha256']==repair.flow._bound(c['result'])['files']['video']['sha256']
    assert obj.collect(req)==saved and e['calls']['posts']==1
    bad=dict(req,native_id='different');before=list(e['calls']['gets'])
    with pytest.raises(ValueError):obj.collect(bad)
    assert e['calls']['gets']==before
    clock_path=Path(c['audio_clock_receipt']['path']);changed=repair.read(clock_path)
    changed['native_audio_clock']['rate']=48000;write(clock_path,changed)
    with pytest.raises(ValueError,match='cached_three_clocks'):obj.collect(req)


def test_recipe_cannot_add_nonspeaker_profile(env):
    e=env;p=Path(e['recipe']['active_profiles']['path']);v=repair.read(p)
    v['profiles']['ye_nan']=repair.flow._bound(e['recipe']['origin_profiles'])['profiles']['ye_nan'];write(p,v)
    recipe=deepcopy(e['recipe']);recipe['active_profiles']=repair.bind(p);rb=repair.freeze(e['case']/'BAD_RECIPE.json',recipe)
    with pytest.raises(ValueError,match='two_speakers'):repair.recipe_value(rb)


def test_changed_pinned_profile_after_prepare_blocks_before_native_claim(env):
    e=env;prepare(e);approve(e)
    path=Path(e['recipe']['active_profiles']['path']);value=repair.read(path)
    value['profiles']['ye_xijue']['description']+=' CPU tamper'
    write(path,value)
    with pytest.raises(ValueError):e['api'].submit(e['run'])
    assert e['calls']['posts']==0 and not (e['run']/'shots/S03/CLAIM.json').exists()


def test_native_audio_longer_than_video_is_not_trimmed_or_marked_normalized(env,monkeypatch):
    e=env;dummy=e['case']/'dummy.flac';dummy.write_bytes(b'CPU placeholder')
    media=e['case']/'dummy.mp4';media.write_bytes(b'CPU placeholder video')
    result=repair.freeze(e['case']/'RAW_RESULT.json',dict(prompt_id='CPU_LONG',files=dict(
        video=repair.bind(media),audio=repair.bind(dummy))))
    monkeypatch.setattr(repair,'_probe',lambda p,**kw:dict(streams=[dict(codec_type='audio',sample_rate='32000',channels=2),
        dict(codec_type='video',width=736,height=1312,nb_read_frames='362',avg_frame_rate='24/1')]))
    monkeypatch.setattr(repair,'_command',lambda a:b'\0'*((16*32000)*4))
    with pytest.raises(ValueError,match='cannot_be_content_trimmed'):repair.audio_clock_receipt(e['case'],result,e['case']/'clock_long')
    assert not (e['case']/'clock_long/AUDIO_CLOCK_RECEIPT.json').exists()


def test_nonroot_launch_cannot_trigger_controller_native_POST(env,monkeypatch):
    e=env;prepare(e)
    repair.freeze(e['run']/'LAUNCH_APPROVAL.json',dict(schema=e['api'].LAUNCH,request=e['api'].launch_request(e['run']),
        approved_by='not_root',evidence=['CPU fixture']))
    with pytest.raises(ValueError,match='Root_launch'):executor(e,monkeypatch).submit(e['req'])
    assert e['calls']['posts']==0
