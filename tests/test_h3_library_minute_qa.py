"""Independent library/actual-input counterexamples; no service/GPU/model calls."""
from copy import deepcopy
import json
from pathlib import Path

from PIL import Image
import pytest

from scripts import qa_h3_library_minute as qa


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def library_fixture(root):
    home = root / 'library'
    home.mkdir()
    index = dict(schema=qa.BINDING_SCHEMA, book_id='CPU_fixture_only', characters={}, places={}, production_approved=False)
    refs = []
    for entity in (*qa.ACTORS, qa.PLACE):
        kind = 'place' if entity == qa.PLACE else 'character'
        images = {}
        for view in ('front', 'side') if kind == 'place' else ('front', 'left_oblique'):
            asset_id = entity + '_' + view
            path = home / (asset_id + '_v1.png')
            Image.new('RGB', (64, 64), (len(refs)*23, len(refs)*17, 80)).save(path)
            record = dict(schema='visual_asset/v3', asset_id=asset_id, version=1, book_id=index['book_id'],
                          entity_id=entity, kind=kind, view=view, design_version='CPU_v1',
                          identity_group=entity + '_CPU_identity', sha256=qa.sha(path), file=path.name)
            record_path = home / (asset_id + '_v1.json')
            write(record_path, record)
            pinned = {k:record[k] for k in ('asset_id', 'version', 'entity_id', 'kind', 'view', 'design_version', 'identity_group')}
            pinned.update(image=qa.bind(path), registry_record=qa.bind(record_path), status_at_binding='candidate' if view == 'left_oblique' else 'reviewed')
            images[view] = pinned
            refs.append(dict(**{k:pinned[k] for k in ('asset_id', 'version', 'entity_id', 'kind', 'view', 'design_version', 'identity_group', 'image')},
                             actor_id=entity if kind == 'character' else None))
        card = dict(schema=qa.CARD_SCHEMA, book_id=index['book_id'], entity_id=entity, kind=kind,
                    description='CPU visual fixture details ' + entity, appearance_description='CPU visual fixture details ' + entity,
                    features=dict(hair='short' if kind == 'character' else 'not applicable'), images=images,
                    wardrobe='plain shirt' if kind == 'character' else None, production_approved=False)
        card_path = home / (entity + '_CARD.json')
        write(card_path, card)
        index['characters' if kind == 'character' else 'places'][entity] = dict(feature_card=qa.bind(card_path), images=images)
        for row in refs:
            if row['entity_id'] == entity: row['feature_card'] = qa.bind(card_path)
    path = home / 'BINDING_INDEX.json'
    write(path, index)
    approval = home / 'APPROVAL.json'
    write(approval, dict(schema='visual_library_binding_approval/v1', binding_index=qa.bind(path),
          approved_by='CPU_fixture_only_not_production', evidence=['Protocol fixture only'],
          confirmed_entities=[*qa.ACTORS, qa.PLACE],
          allow_candidate_assets=[dict(asset_id=r['asset_id'], version=r['version'], sha256=r['image']['sha256']) for r in refs],
          production_approved=False))
    return path, refs, approval


def source_fixture(sid='S02'):
    p = qa.PROJECT / 'data/video_generation/h3_story_opening_minute_20261111_v1/segments' / sid / 'SOURCE_CASE.json'
    if not p.exists():
        p = qa.PROJECT / 'data/video_generation/h3_full_asset_continuation_20261111_v1/segments' / sid / 'SOURCE_CASE.json'
    entry = deepcopy(qa.read(p)['shots'][0])
    spans = {s['id']:s for s in entry['source_spans']}
    original_quotes = [s['text'][1:-1] for s in entry['source_spans'] if s['kind'] == 'audio']
    fields = dict(characters=list(entry['character_names']),
        time=dict(story_time='原文未明确具体时刻', clip_start_seconds=qa.IDS.index(sid)*362/24, clip_duration_seconds=362/24),
        location=dict(place_id=qa.PLACE, name='苏墨的房间'),
        actions=[dict(start=b['start'], end=b['end'], text=''.join(spans[s]['text'] for s in b['source_span_ids']),
                      source_span_ids=b['source_span_ids']) for b in entry['camera_beats']],
        language=[dict(a, text=original_quotes[a['quote_index']]) for a in entry['audio']],
        visuals=deepcopy(entry['camera_beats']))
    return entry, fields


def graph_fixture(root):
    index, refs, approval = library_fixture(root)
    guide = root / 'actual_guide.png'
    Image.new('RGB', (736, 1312), 'gray').save(guide)
    images = [r['image'] for r in refs] + [qa.bind(guide)]
    graph, rows = {}, []
    for i, image in enumerate(images):
        staged = root / 'staged' / f'P{i+1}.png'; staged.parent.mkdir(exist_ok=True)
        staged.write_bytes(Path(image['path']).read_bytes())
        graph[f'ref_{i}'] = dict(class_type='LoadImage', inputs=dict(image=f'fixture/P{i+1}.png'))
        rows.append(dict(slot=i, label=f'P{i+1}', source=image, staged=qa.bind(staged), node_id=f'ref_{i}', input_name=f'fixture/P{i+1}.png'))
    inputs = dict(clip=['128',0], vae=['119',0], width=736, height=1312, length=362,
                  ref_image_size='match', prompt=' '.join(f'<Picture {i+1}>' for i in range(9)))
    inputs.update({f'ref_images.ref_image_{i}':[f'ref_{i}',0] for i in range(9)})
    graph.update(condition=dict(class_type='MiniMaxH3ReferenceToVideo', inputs=inputs),
                 guide_start=dict(class_type='MiniMaxH3AddGuide', inputs=dict(positive=['condition',0],latent=['condition',1],vae=['119',0],image=['ref_8',0],frame_idx=0)),
                 **{'119':dict(class_type='VAELoader',inputs=dict(vae_name='minimax_h3_video_vae.safetensors')),
                    '128':dict(class_type='CLIPLoader',inputs=dict(clip_name='CPU_fixture_encoder')),
                    '127':dict(class_type='UNETLoader',inputs=dict(unet_name=qa.REF_MODEL)),
                    '126':dict(class_type='BasicGuider',inputs=dict(conditioning=['guide_start',0],model=['127',0])),
                    '125':dict(class_type='SamplerCustomAdvanced',inputs=dict(guider=['126',0],latent_image=['condition',1]))})
    for role, frame in (('first',0),('last',361)):
        graph['pick_'+role] = dict(class_type='ImageFromBatch',inputs=dict(image=['122',0],batch_index=frame,length=1))
        graph['save_'+role] = dict(class_type='SaveImage',inputs=dict(images=['pick_'+role,0]))
    return graph, rows, refs, index, approval


def test_full_clip_keeps_children_even_when_first_camera_is_only_father(tmp_path):
    entry, fields = source_fixture('S02')
    assert set(entry['camera_beats'][0]['actors']) == {'su_mo'}
    value = qa.minimum_script(entry, fields, 'S02')
    path, refs, approval = library_fixture(tmp_path)
    library = qa.library_reference_cards(qa.bind(path), refs, value['required_actor_ids'], qa.PLACE, tmp_path)
    assert len(library['references']) == 8
    assert set(library['cards']) == {*qa.ACTORS, qa.PLACE}
    assert library['CPU_identity_quality_verified'] is False
    assert qa.binding_confirmation(qa.bind(path), qa.bind(approval), library, tmp_path) == qa.bind(approval)


def test_opening_actor_subset_cannot_replace_entire_script_requirements():
    entry, fields = source_fixture('S02'); fields['characters'] = ['su_mo']
    with pytest.raises(ValueError, match='cannot_be_filtered_to_opening'):
        qa.minimum_script(entry, fields, 'S02')


@pytest.mark.parametrize('key', ['time','location','actions','language','visuals'])
def test_each_minimum_script_field_is_required(key):
    entry, fields = source_fixture('S02'); fields.pop(key)
    with pytest.raises(ValueError): qa.minimum_script(entry, fields, 'S02')


def test_missing_actual_dialogue_text_cannot_pass_with_speaker_labels():
    entry, fields = source_fixture('S02'); fields['language'][0].pop('text')
    with pytest.raises(ValueError, match='actual_original_quote'):
        qa.minimum_script(entry, fields, 'S02')


def test_missing_character_image_cannot_be_replaced_by_names(tmp_path):
    path, refs, _ = library_fixture(tmp_path)
    refs = [r for r in refs if r['entity_id'] != 'ye_xijue']
    with pytest.raises(ValueError, match='all_required_actors_and_place'):
        qa.library_reference_cards(qa.bind(path), refs, qa.ACTORS, qa.PLACE, tmp_path)


def test_missing_feature_description_rejected_even_with_rebound_metadata(tmp_path):
    path, refs, _ = library_fixture(tmp_path)
    index = qa.read(path); slot = index['characters']['ye_nan']; card_path = Path(slot['feature_card']['path'])
    card = qa.read(card_path); card['description'] = card['appearance_description'] = ''
    write(card_path, card); slot['feature_card'] = qa.bind(card_path)
    for r in refs:
        if r['entity_id']=='ye_nan': r['feature_card'] = qa.bind(card_path)
    write(path, index)
    with pytest.raises(ValueError, match='required_asset_description_missing'):
        qa.library_reference_cards(qa.bind(path), refs, qa.ACTORS, qa.PLACE, tmp_path)


def test_wrong_asset_version_rejected_for_same_actor_id(tmp_path):
    path, refs, _ = library_fixture(tmp_path); refs[2]['version'] += 1
    with pytest.raises(ValueError, match='asset_version_changed'):
        qa.library_reference_cards(qa.bind(path), refs, qa.ACTORS, qa.PLACE, tmp_path)


def test_rebound_card_cannot_forge_a_different_version_than_registry(tmp_path):
    path, refs, _ = library_fixture(tmp_path)
    index=qa.read(path); group=index['characters']['ye_nan']; card_path=Path(group['feature_card']['path']);card=qa.read(card_path)
    card['images']['front']['version']=2;group['images']['front']['version']=2
    write(card_path,card);group['feature_card']=qa.bind(card_path)
    for r in refs:
        if r['entity_id']=='ye_nan':
            r['feature_card']=qa.bind(card_path)
            if r['view']=='front':r['version']=2
    write(path,index)
    with pytest.raises(ValueError,match='registered_ID_version_and_pixel_record'):
        qa.library_reference_cards(qa.bind(path),refs,qa.ACTORS,qa.PLACE,tmp_path)


def test_candidate_angle_requires_exact_confirmation_without_changing_registry(tmp_path):
    path, refs, approval = library_fixture(tmp_path)
    lib=qa.library_reference_cards(qa.bind(path),refs,qa.ACTORS,qa.PLACE,tmp_path)
    original={p:qa.sha(p) for p in (tmp_path/'library').glob('*_v1.json')}
    v=qa.read(approval);v['allow_candidate_assets']=[];write(approval,v)
    with pytest.raises(ValueError,match='candidate_view_not_explicitly_confirmed'):
        qa.binding_confirmation(qa.bind(path),qa.bind(approval),lib,tmp_path)
    assert original=={p:qa.sha(p) for p in original}


def test_missing_notice_is_actionable_and_forbids_dispatch():
    notice=dict(status='missing_notice',notification_required=True,model_dispatch_allowed=False,
                notices=[dict(code='character_binding_missing',entity_id='new_character',reason='素材库未绑定人物',action='补齐人物图与特点卡后再继续本段')])
    value=qa.missing_notice(notice)
    assert value['notification_required'] and not value['model_dispatch_allowed']
    notice['model_dispatch_allowed']=True
    with pytest.raises(ValueError,match='actionable_non_dispatch_notice'):qa.missing_notice(notice)


def test_nine_physical_refs_reach_real_VAE_positive_and_guide(tmp_path):
    graph, rows, _, _, _=graph_fixture(tmp_path)
    result=qa.graph_pixel_routes(graph,rows,tmp_path)
    assert result['actual_positive_reference_count']==9 and result['actual_positive_guide_frame']==0
    assert result['CPU_identity_quality_verified'] is False


def test_registered_metadata_does_not_count_if_child_image_is_disconnected(tmp_path):
    graph,rows,_,_,_=graph_fixture(tmp_path)
    graph['condition']['inputs']['ref_images.ref_image_4']=['ref_0',0]
    with pytest.raises(ValueError,match='every_declared_reference_must_reach'):
        qa.graph_pixel_routes(graph,rows,tmp_path)


@pytest.mark.parametrize('case', ['VAE','guide','model'])
def test_TE_only_refs_or_bypassed_guide_or_old_model_are_not_accepted(tmp_path,case):
    graph,rows,_,_,_=graph_fixture(tmp_path)
    if case=='VAE':graph['condition']['inputs'].pop('vae')
    elif case=='guide':graph['126']['inputs']['conditioning']=['condition',0]
    else:graph['127']['inputs']['unet_name']='minimax_h3_fl2va_pruned_int8_convrot.safetensors'
    with pytest.raises(ValueError):qa.graph_pixel_routes(graph,rows,tmp_path)


def test_actual_guide_is_not_a_static_portrait_relabelled_as_tail(tmp_path):
    graph,rows,_,_,_=graph_fixture(tmp_path);graph['guide_start']['inputs']['image']=['ref_0',0]
    with pytest.raises(ValueError,match='actual_last_reference_must_also'):
        qa.graph_pixel_routes(graph,rows,tmp_path)


def test_installed_official_nodes_consume_all_nine_refs_plus_actual_guide(tmp_path):
    _,rows,_,_,_=graph_fixture(tmp_path)
    result=qa.cpu_source_protocol([dict(image=r['source']) for r in rows],tmp_path)
    assert result['total_reference_count']==result['model_positive_refs']==9
    assert [r['tag'] for r in result['reference_VAE_calls']]==[f'P{i}' for i in range(1,10)]
    assert result['guide_VAE_call']['tag']=='P9' and result['model_positive_keyframes']==1
    assert result['GPU_model_inference'] is False and result['identity_quality_passed'] is False


@pytest.mark.parametrize('bad', [dict(prefix=[]),dict(all_segments_new=False),dict(new_video_submissions=2)])
def test_old_prefix_import_is_refused_even_if_original_files_were_valid(tmp_path,bad):
    run=tmp_path/'data/video_generation/new_library_minute';run.mkdir(parents=True)
    write(run/'PLAN.json',dict(schema=qa.SERIES_SCHEMA,all_segments_new=True,new_video_submissions=4,
          publication=False,production_approved=False,**{k:v for k,v in bad.items() if k not in ('all_segments_new','new_video_submissions')}))
    if 'all_segments_new' in bad or 'new_video_submissions' in bad:
        v=qa.read(run/'PLAN.json');v.update(bad);write(run/'PLAN.json',v)
    with pytest.raises(ValueError,match='no_old_import_or_preserved_prefix'):
        qa.series_inputs(run,tmp_path)


def test_all_ten_source_quotes_are_covered():
    assert [len(qa.EXPECTED_QUOTES[s]) for s in qa.IDS]==[3,2,2,3]
    for sid in qa.IDS:
        entry,fields=source_fixture(sid)
        assert qa.minimum_script(entry,fields,sid)['fields']['language']==fields['language']


def test_four_new_ASR_calls_are_once_per_bound_native_and_tamper_stops(tmp_path,monkeypatch):
    script=tmp_path/'scripts/transcribe_video_local.py';script.parent.mkdir();script.write_text('# CPU fixture, no model',encoding='utf-8')
    calls=[]
    def command(args):Path(args[-1]).write_bytes(b'CPU_fixture_not_WAV')
    def transcribe(project,wav,output,folder):
        calls.append(Path(folder).name)
        sid=Path(folder).name;text=''.join(qa.EXPECTED_QUOTES[sid])
        import re
        clean=re.sub(r'[^\w\u4e00-\u9fff]','',text)
        write(output,dict(result=[dict(text=' '.join(clean),timestamp=[[i*20,(i+1)*20] for i in range(len(clean))])]))
    monkeypatch.setitem(qa.cpu_asr.__globals__,'command',command)
    monkeypatch.setitem(qa.cpu_asr.__globals__,'transcribe',transcribe)
    for iteration in range(2):
        for sid in qa.IDS:
            movie=tmp_path/(sid+'.mp4');movie.write_bytes(('CPU fixture only '+sid).encode())
            row=dict(originals=dict(video=dict(local=qa.bind(movie))),expected_quotes=qa.EXPECTED_QUOTES[sid])
            result=qa.cpu_asr(tmp_path,row,tmp_path/'asr'/sid,True)
            assert all(r['exactly_detected'] for r in result['quote_intervals'])
            assert result['limits']['asr_identifies_acoustic_speaker'] is False
    assert calls==list(qa.IDS)
    path=tmp_path/'asr/S04/ASR.json';path.write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError,match='existing_ASR_binding_changed'):
        qa.cpu_asr(tmp_path,row,tmp_path/'asr/S04',True)
    assert calls==list(qa.IDS)


def initial_fixture(root):
    run=root/'data/video_generation/new_initial';run.mkdir(parents=True)
    output_root=root/'native_outputs';origin=output_root/run.name/'initial/image.png';origin.parent.mkdir(parents=True)
    Image.new('RGB',(736,1312),'gray').save(origin)
    local=run/'initial.png';local.write_bytes(origin.read_bytes())
    cfg=run/'CONFIG.json';write(cfg,dict(output_root=str(output_root)))
    write(run/'PLAN.json',dict(config=qa.bind(cfg)))
    graph={'save':dict(class_type='SaveImage',inputs=dict(filename_prefix=run.name+'/initial/image'))}
    records=run/'native_initial';records.mkdir()
    write(records/'PLAN.json',dict(CPU_fixture_only=True))
    write(records/'REQUEST.json',dict(prompt=graph))
    write(records/'HISTORY.json',{'CPU_new_image':dict(prompt=[1,'CPU_new_image',graph],status=dict(completed=True,status_str='success'),
          outputs=dict(save=dict(images=[dict(filename='image.png',subfolder=run.name+'/initial',type='output')])) )})
    write(records/'RESULT.json',dict(image=qa.bind(origin)))
    value=dict(schema='library_initial_guide/v2',native_prompt_id='CPU_new_image',image=qa.bind(local),source_image=qa.bind(origin),
               native_output=dict(node_id='save',index=0,source_path=str(origin)),
               generation_records={k:qa.bind(records/(k.upper()+'.json')) for k in ('plan','request','history','result')},
               completion_known=True,outcome_unknown=False)
    write(run/'INITIAL_GUIDE.json',value)
    return run,value


def test_S01_initial_frame_bound_to_same_successful_native_output(tmp_path):
    run,value=initial_fixture(tmp_path)
    result=qa._initial_guide(run,value['image'],value,tmp_path)
    assert result['native_id']=='CPU_new_image'
    other=run/'unrelated.png';Image.new('RGB',(736,1312),'red').save(other)
    value['image']=qa.bind(other);write(run/'INITIAL_GUIDE.json',value)
    with pytest.raises(ValueError,match='pixels_must_match_same_native_output'):
        qa._initial_guide(run,value['image'],value,tmp_path)


def test_independent_prepared_reader_accepts_real_library_and_source_contract(tmp_path):
    # Real source/library bytes, but controlled gray initial frame and no model
    # or service calls. The fixture stays inside the project data QA directory.
    from tests import test_visual_h3_library_minute_v2 as producer_fixture
    run=producer_fixture.run.__wrapped__(tmp_path)
    producer_fixture.prepare(run);producer_fixture.initial_guide(run);producer_fixture.review(run,'S01')
    producer_fixture.flow.prepare_video(run,'S01')
    native_run=producer_fixture.flow.native_run(run,'S01')
    result=qa.prepared_graph(native_run,'S01',qa.PROJECT)
    assert result['routes']['actual_positive_reference_count']==9
    assert result['script']['fields']['characters']==result['context']['required_actor_assets']
    assert {r['view'] for r in result['context']['references'] if r['kind']=='place'}=={'front','reverse'}
    assert result['routes']['CPU_identity_quality_verified'] is False
    state_path=native_run/'shots/S01/STATE.json';state=qa.read(state_path);state['status']='outcome_unknown';write(state_path,state)
    before=state_path.read_bytes()
    with pytest.raises((OSError,ValueError)):
        qa.validate_new_native(native_run,'S01',qa.PROJECT)
    assert state_path.read_bytes()==before and not (native_run/'shots/S01/CLAIM.json').exists()
