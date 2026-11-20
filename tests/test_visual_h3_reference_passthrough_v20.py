"""CPU-only raw prompt/ref-image graph checks; no inference acceptance claim."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from PIL import Image
import pytest
from src.content_factory import visual_h3_reference_passthrough_v20 as v


def bound(path):return dict(path=str(path.resolve()),sha256=hashlib.sha256(path.read_bytes()).hexdigest())


@pytest.fixture
def bundle(tmp_path,monkeypatch):
    refs=[]
    for kind,entity,view in [('character','su','front'),('character','su','side'),('place','room','front'),('place','room','side')]:
        p=tmp_path/(kind+'_'+view+'.png');Image.new('RGB',(96,128),'gray').save(p)
        refs.append(dict(reference_id=kind+':'+entity+':'+view,entity_id=entity,display_name='苏墨' if kind=='character' else '卧室',kind=kind,view=view,image=bound(p)))
    result=dict(schema=v.bundles.SCHEMA,book_id='book',source=dict(path='source',sha256='source_sha'),
        source_shot=dict(visible_cast=['su']),
        characters=[dict(entity_id='su',canonical_reference=refs[0]['reference_id'],shot_reference=refs[1]['reference_id'])],
        environment=dict(entity_id='room',canonical_reference=refs[2]['reference_id'],shot_reference=refs[3]['reference_id']),
        references=refs,bundle_sha256='CPU_fixture')
    monkeypatch.setattr(v.bundles,'validate',lambda b:b)
    return result


@pytest.fixture
def base():
    path=Path(__file__).resolve().parents[1]/'data/video_generation/h3_six_children_s01_720p_20261102/workflow_api.json'
    return json.loads(path.read_text(encoding='utf8'))


def build(base,bundle,prompt=b'\xef\xbb\xbfOriginal action.\r\nHe turns toward the child.\r\n',**kwargs):
    mapping={r['reference_id']:'v20/'+str(i)+'.png' for i,r in enumerate(bundle['references'])}
    if kwargs.get('auxiliary_tail'):mapping['auxiliary_tail']='v20/tail.png'
    return v.build_graph(base,bundle,prompt,mapping,'v20/test/segment',736,1312,362,123,**kwargs)


def test_raw_prefix_bytes_and_only_reference_appendix_no_director(base,bundle):
    raw=b'\xef\xbb\xbfCut to close-up.\r\n[Chinese] \xe4\xbd\xa0\xe5\xa5\xbd\xe3\x80\x82\r\n'
    original=deepcopy(base);result=build(base,bundle,raw)
    compiled=result['compiled_prompt'].encode('utf8');assert compiled[:len(raw)]==raw
    appendix=compiled[len(raw):].decode('utf8')
    assert '同一人物"苏墨"' in appendix and appendix.count('同一人物')==1
    for phrase in ['tripod','fixed camera','locked-off','保持构图','固定机位','禁止推拉','0.00 seconds','[Shot 1]']:
        assert phrase not in appendix
    assert base==original and result['source_prompt_sha256']==hashlib.sha256(raw).hexdigest()


def test_actual_ref2va_slots_separate_loader_and_no_firstframe(base,bundle):
    r=build(base,bundle);g=r['graph'];condition=g['condition']['inputs']
    assert g['condition']['class_type']=='MiniMaxH3ReferenceToVideo'
    assert g['127']['inputs']['unet_name']==v.REF2VA_MODEL
    assert 'first_frame' not in condition and 'last_frame' not in condition and 'ref_images' not in condition
    assert 'ref_scene' not in g and len(r['reference_map'])==4
    for index,item in enumerate(r['reference_map']):
        assert item['picture']==index+1 and item['slot']=='ref_images.ref_image_'+str(index)
        assert condition[item['slot']]==[item['node'],0] and g[item['node']]['class_type']=='LoadImage'
    assert len({m['node'] for m in r['reference_map']})==4
    assert condition['vae']==base['condition']['inputs']['vae']
    assert v.validate_graph(r)==r


def test_incompatible_base_cannot_keep_dangling_first_frame_link(base,bundle):
    base['pick_first']['inputs']['image']=['ref_scene',0]
    with pytest.raises(v.ReferencePassthroughError,match='dangling_reference'):build(base,bundle)


@pytest.mark.parametrize('role',['character','environment'])
def test_missing_required_global_reference_is_not_replaced_by_tail(base,bundle,role):
    changed=deepcopy(bundle)
    if role=='character':changed['characters']=[]
    else:changed['environment']={}
    with pytest.raises(v.ReferencePassthroughError):build(base,changed)


def test_real_bundle_validator_is_mandatory(base,bundle,monkeypatch):
    def reject(b):raise ValueError('real asset not reviewed')
    monkeypatch.setattr(v.bundles,'validate',reject)
    with pytest.raises(ValueError,match='not reviewed'):build(base,bundle)


def expand_to(bundle,number,tmp_path):
    b=deepcopy(bundle)
    for n in range((number-4)//2):
        cid='actor'+str(n);ids=[]
        for view in ['front','side']:
            path=tmp_path/(cid+view+'.png');Image.new('RGB',(64,96),'blue').save(path);rid='character:'+cid+':'+view
            b['references'].append(dict(reference_id=rid,entity_id=cid,display_name=cid,kind='character',view=view,image=bound(path)));ids.append(rid)
        b['characters'].append(dict(entity_id=cid,canonical_reference=ids[0],shot_reference=ids[1]))
        b['source_shot']['visible_cast'].append(cid)
    return b


def test_nine_is_real_limit_and_no_silent_truncation(base,bundle,tmp_path):
    b=expand_to(bundle,10,tmp_path)
    with pytest.raises(v.ReferencePassthroughError,match='maximum_nine'):build(base,b)


def tail_fixture(tmp_path,bundle):
    image=tmp_path/'last.png';Image.new('RGB',(736,1312),'gray').save(image);image_binding=bound(image)
    receipt=tmp_path/'RESULT.json';receipt.write_text(json.dumps(dict(prompt_id='known_native_id',files=dict(last=dict(image_binding,source_path='original_native_output')))),encoding='utf8')
    receipt_binding=bound(receipt);review=tmp_path/'ROOT_CONTINUITY_REVIEW.json'
    review.write_text(json.dumps(dict(schema='reviewed_h3_auxiliary_tail/v20',accepted_for_continuity=True,source=bundle['source'],book_id=bundle['book_id'],image=image_binding,native_result=receipt_binding)),encoding='utf8')
    return dict(image=image_binding,native_result=receipt_binding,review=bound(review))


def test_eight_global_plus_reviewed_auxiliary_tail_maps_ninth(base,bundle,tmp_path):
    b=expand_to(bundle,8,tmp_path);tail=tail_fixture(tmp_path,b)
    result=build(base,b,auxiliary_tail=tail)
    assert len(result['reference_map'])==9 and result['reference_map'][-1]['reference_id']=='auxiliary_tail'
    assert result['reference_map'][-1]['slot']=='ref_images.ref_image_8'
    assert '<Picture 9>' in result['compiled_prompt'] and '承接参考' in result['compiled_prompt']
    bad=deepcopy(tail);bad['native_result']=bad['review']
    with pytest.raises(v.ReferencePassthroughError):build(base,b,auxiliary_tail=bad)


@pytest.mark.parametrize('tamper',['prefix','appendix','model','slot','file','frames'])
def test_reloading_graph_catches_source_reference_or_condition_tamper(base,bundle,tamper):
    r=build(base,bundle)
    if tamper=='prefix':r['graph']['condition']['inputs']['prompt']='Changed'+r['compiled_prompt']
    elif tamper=='appendix':
        r['compiled_prompt']+='\nThe camera is fixed.';r['graph']['condition']['inputs']['prompt']=r['compiled_prompt']
    elif tamper=='model':r['graph']['127']['inputs']['unet_name']='minimax_h3_fl2va_pruned_int8_convrot.safetensors'
    elif tamper=='slot':r['graph']['condition']['inputs']['ref_images.ref_image_0']=r['graph']['condition']['inputs']['ref_images.ref_image_1']
    elif tamper=='file':Path(bundle['references'][0]['image']['path']).write_bytes(b'changed')
    else:r['graph']['condition']['inputs']['length']=361
    with pytest.raises(v.ReferencePassthroughError):v.validate_graph(r)


def test_structured_source_audio_is_kept_without_static_opening_pollution():
    audio=dict(speaker='kid',mode='offscreen_dialogue',text='你好。',source_speaker='孩子',source_channel='画外',source_direction='急',source_start=1,source_end=4)
    shot=dict(visual_prompt='原动作。镜头推进。',static_start_prompt='One frozen instant on a fixed tripod.',audio=[audio])
    text=v.prompt_from_shot(shot);assert text.startswith(shot['visual_prompt'])
    assert 'frozen' not in text and 'tripod' not in text
    for key,value in audio.items():assert (value if key=='text' else json.dumps(value,ensure_ascii=False)) in text
    assert v.audio_records_from_shot(shot)==[audio]
    quoted=dict(audio,text='他说："你好！"\n再见。')
    assert quoted['text'] in v.prompt_from_shot(dict(shot,audio=[quoted]))


def test_declared_complete_video_field_is_verbatim_and_missing_audio_is_rejected():
    complete='完整动作和说话人：孩子（画外，急）“你好。”\r\n'
    shot=dict(complete_video_prompt=complete,visual_prompt='not selected',audio=[dict(speaker='kid',mode='offscreen_dialogue',text='你好。')])
    assert v.prompt_from_shot(shot)==complete
    with pytest.raises(v.ReferencePassthroughError,match='missing_source_audio'):
        v.prompt_from_shot(dict(shot,complete_video_prompt='Only picture, no speech.'))
    with pytest.raises(v.ReferencePassthroughError,match='dynamic_visual_prompt'):
        v.prompt_from_shot(dict(static_start_prompt='Only the first instant.'))


@pytest.mark.parametrize('raw',[b'bad \xff UTF8','<Picture 9> has no mapped image.','<Audio 1> lacks audio input.'])
def test_unbound_or_wrong_encoding_source_is_not_silently_rewritten(base,bundle,raw):
    with pytest.raises(v.ReferencePassthroughError):build(base,bundle,raw)


def test_same_pixels_different_identity_keep_independent_slots(base,bundle):
    b=deepcopy(bundle);r=deepcopy(b['references'][0]);r.update(reference_id='character:twin:front',entity_id='twin',display_name='双胞胎')
    b['references'].insert(2,r);b['characters'].append(dict(entity_id='twin',canonical_reference=r['reference_id'],shot_reference=r['reference_id']))
    b['source_shot']['visible_cast'].append('twin')
    result=build(base,b);mapping=result['reference_map'];a=next(x for x in mapping if x['reference_id']=='character:su:front');t=next(x for x in mapping if x['entity_id']=='twin')
    assert a['image']==t['image'] and a['node']!=t['node'] and a['picture']!=t['picture']


def test_source_empty_cast_accepts_environment_only_but_never_adds_actor(base,bundle):
    b=deepcopy(bundle);b['source_shot']['visible_cast']=[];b['characters']=[]
    b['references']=[r for r in b['references'] if r['kind']=='place']
    result=build(base,b);assert len(result['reference_map'])==2
    assert '同一人物' not in result['compiled_prompt'] and '同一场景' in result['compiled_prompt']
    b['characters']=bundle['characters']
    with pytest.raises(v.ReferencePassthroughError,match='exactly_match_source_visible_cast'):build(base,b)


def test_legacy_v6_adapter_prose_cannot_impersonate_original_direct_prompt():
    old=dict(visual_prompt='固定侧面机位，单一连续拍摄，无切镜无变焦。',
        staging_provenance=dict(schema='continuous_source_home_staging/v6'),audio=[])
    with pytest.raises(v.ReferencePassthroughError,match='explicit_original_video_prompt'):v.prompt_from_shot(old)
    assert v.prompt_from_shot(dict(old,complete_video_prompt='原始镜头推进并切特写。'))=='原始镜头推进并切特写。'


def source_window_fixture():
    def action(i,a,b,text):return dict(id=i,start=a,end=b,people=['kid'],description=text,source_ids=['source'])
    raw='他说："你好！"\n再见。'
    scene=dict(id='scene',timeline='现在',story_time='傍晚',place_id='room',seconds=30,
        camera='先中景，再推进特写。\n保持原camera文字。',plot='未来在学校重逢。',information='随后去医院。',performance='整场最终大哭。',
        actions=[action('done',0,4,'已经结束的动作。'),action('ongoing',3,12,'正在持续的原动作。'),
            action('current',8,10,'当前动作中有"引号"。\n动作的下一原行。'),action('unselected',9,11,'没有选择的同期动作。'),action('future',20,25,'未来的动作。')],
        audio=[dict(id='a',start=9,end=11,speaker='kid',mode='offscreen_dialogue',text=raw,source_speaker='小孩',source_channel='画外',source_direction='急')])
    return scene,dict(id='window',scene_id='scene',start=8,end=15,action_ids=['current'],audio_ids=['a'])


def test_source_window_selects_current_and_persisting_rows_without_future_plot():
    scene,window=source_window_fixture();text=v.prompt_from_source_window(scene,window)
    for row in scene['actions']:
        assert (row['description'] in text)==(row['id'] in ('ongoing','current'))
    assert scene['audio'][0]['text'] in text and '\\"你好' not in text
    assert scene['camera'] in text and scene['story_time'] in text and '"place_id": "room"' in text
    for key in ['plot','information','performance']:assert scene[key] not in text
    complete=dict(complete_video_prompt=text,audio=scene['audio']);assert v.prompt_from_shot(complete)==text
    assert 'source_direction' in text and 'source_speaker' in text and 'source_channel' in text


def test_source_window_empty_action_and_audio_only_remains_legal():
    scene,window=source_window_fixture();scene['actions']=[];window['action_ids']=[]
    text=v.prompt_from_source_window(scene,window)
    assert '原动作资料' not in text and scene['audio'][0]['text'] in text and scene['camera'] in text
    scene['audio']=[];window['audio_ids']=[]
    assert '原音频资料' not in v.prompt_from_source_window(scene,window)


def test_later_source_window_interleaves_audio_and_actions_on_local_clock():
    spoken='他说："请等一下。"\n声音仍很轻。'
    scene=dict(id='later',seconds=40,timeline='现在',story_time='午后',place_id='room',camera='镜头缓缓推进。',
        actions=[dict(id='ongoing',start=12,end=18,description='持续的原动作。',people=['a']),
            dict(id='late',start=25,end=28,description='稍后的原动作。',people=['a'])],
        audio=[dict(id='early_voice',start=16,end=19,speaker='a',mode='onscreen',text=spoken)])
    window=dict(scene_id='later',start=15,end=30,action_ids=['late'],audio_ids=['early_voice'])
    text=v.prompt_from_source_window(scene,window)
    assert text.index('持续的原动作。')<text.index(spoken)<text.index('稍后的原动作。')
    assert '本段相对时间范围：{"start": 0, "end": 15}' in text
    for interval in ['{"start": 0, "end": 3}','{"start": 1, "end": 4}','{"start": 10, "end": 13}']:
        assert '（本段相对时间）：'+interval in text
    assert '"start": 12, "end": 18' in text and '"start": 16, "end": 19' in text and '"start": 25, "end": 28' in text
    assert spoken in text and scene['camera'] in text


@pytest.mark.parametrize('change',['future','done','unknown','split_audio','wrong_scene'])
def test_source_window_rejects_inconsistent_ids_instead_of_importing_other_events(change):
    scene,window=source_window_fixture()
    if change in ('future','done','unknown'):window['action_ids']=[change]
    elif change=='split_audio':scene['audio'][0]['end']=16
    else:window['scene_id']='another_scene'
    with pytest.raises(v.ReferencePassthroughError):v.prompt_from_source_window(scene,window)
