"""Independent CPU evidence for a fresh, library-bound four-segment H3 film.

No HTTP/GPU/media dispatch or retry. Physical library bindings and positive
conditioning are checked separately from visual identity/acting quality. CPU
evidence never supplies a face, speaker, caption, or content-quality pass.
"""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import time
import traceback
import uuid
from types import SimpleNamespace

from PIL import Image

SCRIPTS = Path(__file__).resolve().parent
for item in (SCRIPTS, SCRIPTS.parent):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))
from qa_h3_baseline_two_rounds_v38 import (
    PROJECT, LIMITS, read, bind, checked, digest, freeze, require, sha, quotes,
    inspect_clock, extract_batch, make_board, first_comparison, cpu_asr,
)
import qa_h3_identity_continuation as media_qa
import qa_h3_full_asset_continuation as old_reference_qa

IDS = ('S01', 'S02', 'S03', 'S04')
ACTORS = ('su_mo', 'ye_nan', 'ye_xijue')
PLACE = 'su_mo_room'
SERIES_SCHEMA = 'h3_library_bound_minute_series/v2'
NATIVE_SCHEMA = 'h3_library_bound_minute_native/v2'
INPUT_SCHEMA = 'library_bound_segment_input/v2'
CARD_SCHEMA = 'visual_asset_feature_card/v1'
BINDING_SCHEMA = 'visual_library_binding_index/v1'
STATE_SCHEMA = 'library_segment_state/v2'
REF_MODEL = old_reference_qa.REF_MODEL
EXPECTED_QUOTES = {
    'S01': ['二哥，今天没偷到钱，怎么办呀？', '哥哥发传单挣了十块，先给你。', '不行，你没交上钱，他会打你的。'],
    'S02': ['我竟然穿成了六个孩子的恶毒继父。书里，他们长大后会报复我。', '爸爸，这是好心人给我的面包。'],
    **media_qa.EXPECTED_QUOTES,
}


def rgb_bytes(path):
    with Image.open(path) as image:
        require(getattr(image, 'n_frames', 1) == 1, 'one_reference_one_actual_static_image_required')
        return image.size, image.convert('RGB').tobytes()


def one_node(graph, class_type):
    matches = [key for key, value in graph.items() if value.get('class_type') == class_type]
    require(len(matches) == 1, 'exactly_one_' + class_type + '_required')
    return matches[0]


def graph_pixel_routes(graph, references, project=PROJECT):
    """Trace every independent source/staged image through actual VAE/positive.

    references use normalized slot,label,source,staged,node_id,input_name. The
    last image is the actual initial/native-tail guide, not an extra actor.
    """
    count = len(references)
    require(2 <= count <= 9 and [r.get('slot') for r in references] == list(range(count))
            and [r.get('label') for r in references] == [f'P{i+1}' for i in range(count)],
            'ordered_complete_reference_slots_within_nine_required')
    nodes = [r['node_id'] for r in references]
    require(len(set(nodes)) == count and set(nodes) == {
        node for node, value in graph.items() if value.get('class_type') == 'LoadImage'},
        'all_reference_images_must_be_independent_LoadImage_nodes')
    receipts = []
    for row in references:
        source, staged = checked(row['source'], project), checked(row['staged'], project)
        original_size, original = rgb_bytes(source)
        staged_size, staged_pixels = rgb_bytes(staged)
        require(original_size == staged_size and original == staged_pixels and sha(source) == sha(staged),
                'actual_source_to_staged_reference_pixels_changed')
        require(graph[row['node_id']].get('inputs') == dict(image=row['input_name']),
                'actual_LoadImage_not_this_staged_reference')
        receipts.append(dict(slot=row['slot'], label=row['label'], source=bind(source), staged=bind(staged),
                             source_RGB_sha256=hashlib.sha256(original).hexdigest(),
                             image_size=list(original_size), node_id=row['node_id'], input_name=row['input_name']))
    ref_id, guide_id = one_node(graph, 'MiniMaxH3ReferenceToVideo'), one_node(graph, 'MiniMaxH3AddGuide')
    ref, guide = graph[ref_id]['inputs'], graph[guide_id]['inputs']
    ports = [f'ref_images.ref_image_{i}' for i in range(count)]
    require(set(k for k in ref if k.startswith('ref_images.')) == set(ports)
            and all(ref[p] == [nodes[i], 0] for i, p in enumerate(ports))
            and 'ref_images' not in ref and not any(k.startswith(('ref_videos', 'ref_audios', 'ref_video_audios')) for k in ref),
            'every_declared_reference_must_reach_its_actual_positive_slot')
    require((ref.get('width'), ref.get('height'), ref.get('length')) == (736, 1312, 362)
            and ref.get('ref_image_size') == 'match', 'reference_native_geometry_changed')
    tags = set(re.findall(r'<Picture (\d+)>', ref.get('prompt', '')))
    require(tags == {str(i+1) for i in range(count)}, 'prompt_reference_labels_must_match_actual_slots')
    vae_id = ref.get('vae', [None])[0]
    require(ref.get('vae') == [vae_id, 0] and graph.get(vae_id, {}).get('class_type') == 'VAELoader'
            and 'minimax_h3' in graph[vae_id]['inputs'].get('vae_name', '').lower()
            and 'audio' not in graph[vae_id]['inputs'].get('vae_name', '').lower(),
            'real_video_VAE_required_for_reference_pixels')
    clip_id = ref.get('clip', [None])[0]
    require(ref.get('clip') == [clip_id, 0] and graph.get(clip_id, {}).get('class_type') == 'CLIPLoader',
            'reference_text_encoder_required')
    require(guide.get('positive') == [ref_id, 0] and guide.get('latent') == [ref_id, 1]
            and guide.get('vae') == [vae_id, 0] and guide.get('image') == [nodes[-1], 0]
            and guide.get('frame_idx') == 0 and 'audio' not in guide,
            'actual_last_reference_must_also_be_frame_zero_guide')
    guider_id, sampler_id = one_node(graph, 'BasicGuider'), one_node(graph, 'SamplerCustomAdvanced')
    guider, sampler = graph[guider_id]['inputs'], graph[sampler_id]['inputs']
    require(guider.get('conditioning') == [guide_id, 0] and sampler.get('guider') == [guider_id, 0]
            and sampler.get('latent_image') == [ref_id, 1], 'all_reference_and_guide_conditions_must_reach_sampler')
    model_id = guider.get('model', [None])[0]
    require(guider.get('model') == [model_id, 0] and graph.get(model_id, {}).get('class_type') == 'UNETLoader'
            and graph[model_id]['inputs'].get('unet_name') == REF_MODEL, 'real_Ref2VA_checkpoint_required')
    media_qa.exact_endpoint_selection(graph)
    return dict(reference_slots=receipts, actual_positive_reference_count=count, actual_positive_guide_frame=0,
                ref_node=ref_id, video_vae_node=vae_id, guide_node=guide_id, positive_guider=guider_id,
                sampler=sampler_id, path='source pixels -> staged pixels -> independent LoadImage -> Ref2VA VAE/positive -> guide -> sampler',
                CPU_identity_quality_verified=False)


def minimum_script(entry, fields, sid):
    require(sid in IDS and isinstance(fields, dict), 'explicit_segment_minimum_script_required')
    actors = set(entry.get('character_names', {}))
    required = set().union(*(set(b.get('actors', {})) for b in entry.get('camera_beats', [])))
    required.update(a.get('speaker') for a in entry.get('audio', []))
    require(actors == required == set(ACTORS) and len(fields.get('characters', [])) == len(actors)
            and set(fields['characters']) == actors, 'full_segment_actor_list_cannot_be_filtered_to_opening')
    timing, location = fields.get('time', {}), fields.get('location', {})
    require(isinstance(timing.get('story_time'), str) and bool(timing['story_time'].strip())
            and timing.get('clip_start_seconds') == IDS.index(sid) * 362 / 24
            and timing.get('clip_duration_seconds') == 362 / 24,
            'explicit_story_time_and_native_clip_timeline_required')
    require(location.get('place_id') == PLACE and isinstance(location.get('name'), str)
            and bool(location['name'].strip()), 'explicit_bound_location_required')
    require(fields.get('visuals') == entry.get('camera_beats') and bool(fields['visuals']),
            'minimum_visuals_must_preserve_source_camera_and_actions')
    spans = {r['id']: r for r in entry.get('source_spans', [])}
    quote_rows = [r for r in entry.get('source_spans', []) if r.get('kind') == 'audio']
    languages = fields.get('language', [])
    require(len(languages) == len(entry.get('audio', [])), 'actual_script_dialogue_text_required')
    for row, original in zip(languages, entry['audio']):
        require({k: row.get(k) for k in original} == original, 'script_speaker_mode_or_timing_changed')
        index = original['quote_index']
        require(0 <= index < len(quote_rows) and row.get('text') == quote_rows[index]['text'][1:-1],
                'script_dialogue_text_must_be_actual_original_quote')
    require([r['text'] for r in languages] == EXPECTED_QUOTES[sid], 'ten_original_quotes_must_be_preserved')
    actions = fields.get('actions', [])
    require(isinstance(actions, list) and len(actions) == len(entry['camera_beats']), 'minimum_actions_for_every_camera_beat_required')
    for action, beat in zip(actions, entry['camera_beats']):
        ids = action.get('source_span_ids', [])
        require(ids == beat.get('source_span_ids') and all(i in spans for i in ids)
                and (action.get('start'), action.get('end')) == (beat['start'], beat['end'])
                and action.get('text') == ''.join(spans[i]['text'] for i in ids),
                'actions_must_preserve_bound_source_spans_without_new_narration')
    return dict(required_actor_ids=sorted(actors), place_id=PLACE, fields=deepcopy(fields),
                opening_actor_ids=list(entry['camera_beats'][0]['actors']), content_quality_verified=False)


def library_reference_cards(binding, references, actor_ids, place_id, project=PROJECT, *, expected_place_views=None):
    """Match each physical ref to its registered ID/version/card, no similarity scores."""
    index_path = checked(binding, project)
    index = read(index_path)
    require(index.get('schema') == BINDING_SCHEMA, 'explicit_library_binding_index_required')
    require(len(references) <= 8, 'fixed_refs_must_leave_one_guide_slot_within_nine')
    cards, views, normalized = {}, {}, []
    required_entities = set(actor_ids) | {place_id}
    for ref in references:
        entity = ref.get('entity_id')
        require(entity in required_entities and ref.get('kind') in ('character', 'place'), 'reference_entity_not_in_segment_requirements')
        is_character = entity in actor_ids
        require(ref.get('kind') == ('character' if is_character else 'place')
                and (ref.get('actor_id') == entity if is_character else True), 'reference_actor_or_place_label_changed')
        rows = index.get('characters' if is_character else 'places', {})
        require(entity in rows, 'required_entity_missing_library_binding')
        declared = rows[entity]
        card_binding = ref.get('feature_card')
        require(card_binding == declared.get('feature_card'), 'reference_must_use_this_bound_feature_card')
        card_path = checked(card_binding, project)
        card = read(card_path)
        require(card.get('schema') == CARD_SCHEMA and card.get('entity_id') == entity
                and card.get('kind') == ref['kind'] and card.get('book_id') == index.get('book_id'),
                'feature_card_identity_or_book_binding_changed')
        description = card.get('description')
        require(isinstance(description, str) and bool(description.strip())
                and card.get('appearance_description', description) == description,
                'required_asset_description_missing')
        require(isinstance(card.get('features'), dict) and bool(card['features'])
                and any(bool(v) for v in card['features'].values()), 'required_asset_feature_details_missing')
        if is_character:
            require(bool(card.get('wardrobe')), 'required_character_wardrobe_details_missing')
        selected = card.get('images', {}).get(ref.get('view'))
        require(isinstance(selected, dict) and selected == declared.get('images', {}).get(ref.get('view')),
                'registered_selected_asset_view_required')
        for key in ('entity_id', 'kind', 'view', 'asset_id', 'version', 'design_version', 'identity_group', 'image'):
            require(ref.get(key) == selected.get(key), 'reference_registered_asset_' + key + '_changed')
        image_path = checked(ref['image'], project)
        record_path = checked(selected['registry_record'], project)
        record = read(record_path)
        require(record.get('schema') == 'visual_asset/v3' and record.get('book_id') == index.get('book_id')
                and all(record.get(k) == ref.get(k) for k in ('asset_id', 'version', 'entity_id', 'kind', 'view',
                                                             'design_version', 'identity_group'))
                and record.get('sha256') == ref['image']['sha256']
                and (record_path.parent / record.get('file', '')).resolve() == image_path,
                'actual_registered_ID_version_and_pixel_record_changed')
        rgb_bytes(image_path)
        views.setdefault(entity, []).append(ref['view'])
        cards[entity] = dict(card_binding=card_binding, card=card)
        normalized.append(dict(ref, image=bind(image_path), feature_card=bind(card_path)))
    require(set(views) == required_entities, 'all_required_actors_and_place_need_actual_refs')
    for actor in actor_ids:
        require(len(views[actor]) == 2 and 'front' in views[actor]
                and len(set(views[actor])) == 2, 'each_actor_needs_front_and_one_actual_angle_reference')
    required_views = set(expected_place_views) if expected_place_views is not None else set(views[place_id])
    require(set(views[place_id]) == required_views and len(views[place_id]) == 2
            and len(required_views) == 2 and 'front' in required_views,
            'actual_selected_two_place_reference_views_required')
    return dict(binding_index=bind(index_path), references=normalized, cards=cards,
                required_entities=sorted(required_entities), CPU_identity_quality_verified=False)


def binding_confirmation(binding, approval_binding, library, project=PROJECT):
    path = checked(approval_binding, project)
    approval, index = read(path), read(checked(binding, project))
    require(approval.get('schema') == 'visual_library_binding_approval/v1'
            and approval.get('binding_index') == binding and bool(approval.get('approved_by'))
            and bool(approval.get('evidence')) and approval.get('production_approved') is False
            and set(approval.get('confirmed_entities', [])) == set(index['characters']) | set(index['places']),
            'actual_first_project_library_binding_confirmation_required')
    allowed = {(a['asset_id'], a['version'], a['sha256']) for a in approval.get('allow_candidate_assets', [])}
    for ref in library['references']:
        card = library['cards'][ref['entity_id']]['card']
        item = card['images'][ref['view']]
        require(item.get('status_at_binding') in ('reviewed', 'candidate'), 'unavailable_library_view_cannot_be_dispatched')
        if item['status_at_binding'] == 'candidate':
            require((ref['asset_id'], ref['version'], ref['image']['sha256']) in allowed,
                    'actual_candidate_view_not_explicitly_confirmed_for_this_binding')
    return bind(path)


def missing_notice(value):
    require(isinstance(value, dict) and value.get('status') in ('missing_notice', 'waiting_asset')
            and value.get('notification_required') is True and value.get('model_dispatch_allowed') is False
            and isinstance(value.get('notices'), list) and bool(value['notices']),
            'missing_assets_must_have_actionable_non_dispatch_notice')
    for notice in value['notices']:
        require(isinstance(notice, dict) and isinstance(notice.get('code'), str) and bool(notice['code'])
                and bool(notice.get('reason')) and bool(notice.get('action')), 'specific_missing_asset_reason_and_action_required')
    return dict(status=value['status'], notification_required=True, model_dispatch_allowed=False,
                notices=deepcopy(value['notices']), CPU_identity_quality_verified=False)


def cpu_source_protocol(reference_rows, project=PROJECT):
    """Execute the installed reference, guide and model payload methods on CPU doubles."""
    require(2 <= len(reference_rows) <= 9, 'reference_protocol_capacity_exceeded')
    images = []
    for index, row in enumerate(reference_rows):
        path = checked(row['image'], project)
        size, pixels = rgb_bytes(path)
        images.append((f'P{index+1}', size, hashlib.sha256(pixels).hexdigest()))
    require(images[-1][1] == (736, 1312), 'native_geometry_guide_image_required')
    class Tensor:
        def __init__(self, tag, shape, pixel_sha=None):
            self.tag, self.shape, self.pixel_sha = tag, shape, pixel_sha
            self.ndim = len(shape)
        def __getitem__(self, item):
            require(isinstance(item, slice), 'unexpected_protocol_tensor_index')
            return self
    calls, resized = [], []
    def resize(image, width, height, crop):
        resized.append(dict(tag=image.tag, source_shape=image.shape, width=width, height=height, crop=crop))
        return Tensor(image.tag, (image.shape[0], height, width, image.shape[-1]), image.pixel_sha)
    class VAE:
        def encode(self, image):
            calls.append(dict(tag=image.tag, source_pixel_sha=image.pixel_sha, shape=image.shape))
            return Tensor(image.tag, (1, 24, 1, image.shape[1] // 16, image.shape[2] // 16))
    class Clip:
        def tokenize(self, prompt, **kwargs): return kwargs
        def encode_from_tokens_scheduled(self, tokens):
            self.items = tokens['minimax_ref_items']
            return [[None, {}]]
    samples = SimpleNamespace(is_nested=True, tensors=(Tensor('video', (1, 24, 107, 82, 46)), Tensor('audio', (1, 32, 2, 603))))
    def empty(width, height, length):
        require((width, height, length) == (736, 1312, 362), 'reference_protocol_profile_changed')
        return {'samples': samples}, 362
    helper = old_reference_qa.CONDITIONING_HELPER_SOURCE
    nodes = old_reference_qa.NODE_SOURCE
    model = old_reference_qa.MODEL_SOURCE
    namespace = dict(math=math, CANVAS_MULTIPLE=32, REF_IMAGE_SHORT_EDGE=2048, FRAME_PER_TOKEN=(1, 4, 4, 4, 4),
                     FRAME_RESCALE=5.0/3.0, FPS=24, _empty_av_latent=empty, _resize=resize,
                     io=SimpleNamespace(NodeOutput=lambda *items: items))
    def install(path, class_name, method):
        method_ast = old_reference_qa.source_method(path, class_name, method)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method_ast], type_ignores=[])), str(path), 'exec'), namespace)
        return namespace[method]
    setter = install(helper, None, 'conditioning_set_values')
    namespace['node_helpers'] = SimpleNamespace(conditioning_set_values=setter)
    ref_execute = install(nodes, 'MiniMaxH3ReferenceToVideo', 'execute')
    guide_execute = install(nodes, 'MiniMaxH3AddGuide', 'execute')
    tensors = {f'ref_image_{i}': Tensor(tag, (1, size[1], size[0], 3), pixel_sha)
               for i, (tag, size, pixel_sha) in enumerate(images)}
    clip, vae = Clip(), VAE()
    positive, latent = ref_execute(None, clip=clip, vae=vae, prompt='CPU protocol only', width=736, height=1312,
                                  length=362, ref_image_size='match', ref_images=tensors)
    labels = [r[0] for r in images]
    count = len(labels)
    require([r['tag'] for r in calls] == labels and len(positive[0][1].get('minimax_refs', [])) == count
            and [item['data'].tag for item in clip.items] == labels, 'installed_node_did_not_encode_every_reference')
    positive, = guide_execute(None, positive=positive, latent=latent, frame_idx=0, vae=vae,
                              image=tensors[f'ref_image_{count-1}'])
    require([r['tag'] for r in calls] == labels + [labels[-1]]
            and positive[0][1]['minimax_keyframes'][0]['resolved_frame_index'] == 0,
            'installed_guide_did_not_encode_actual_last_reference_at_frame_zero')
    class Base:
        def extra_conds(self, **kwargs): return {}
    method = old_reference_qa.source_method(model, 'MiniMaxH3', 'extra_conds')
    cls = ast.ClassDef(name='ProtocolMiniMaxH3', bases=[ast.Name(id='Base', ctx=ast.Load())], keywords=[], body=[method], decorator_list=[])
    extra = dict(Base=Base, comfy=SimpleNamespace(conds=SimpleNamespace(CONDConstant=lambda x: x)))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), str(model), 'exec'), extra)
    obj = extra['ProtocolMiniMaxH3'](); obj.audio_scale = lambda: 1.0
    payload = obj.extra_conds(**positive[0][1])['minimax_payload']
    require(len(payload.get('refs', [])) == count and len(payload.get('keyframes', [])) == 1
            and [tensor.tag for tensor in payload['cond_video_latents']] == [labels[-1]] + labels,
            'installed_model_did_not_consume_all_refs_and_actual_guide')
    return dict(schema='installed_library_H3_CPU_protocol/v1', official_nodes=bind(nodes), official_model=bind(model),
                official_conditioning_helper=bind(helper), total_reference_count=count, reference_VAE_calls=calls[:count],
                guide_VAE_call=calls[count], resize_calls=resized, model_positive_refs=count, model_positive_keyframes=1,
                guide_frame=0, CPU_protocol_doubles=True, GPU_model_inference=False, identity_quality_passed=False)


def source_entry(binding, sid, project=PROJECT):
    path = checked(binding, project)
    value = read(path)
    rows = value.get('shots', [])
    require(len(rows) == 1 and rows[0].get('shot_id') == sid, 'one_exact_source_segment_required')
    from src.content_factory import visual_h3_continuity_input_v33 as source_core
    source_core.validate_entry(rows[0])
    return rows[0]


def series_inputs(run, project=PROJECT):
    project, run = Path(project).resolve(), Path(run).resolve()
    require(run.is_relative_to(project / 'data'), 'project_fresh_minute_run_required')
    path = run / 'PLAN.json'
    plan = read(path)
    require(plan.get('schema') == SERIES_SCHEMA and plan.get('all_segments_new') is True
            and plan.get('new_video_submissions') == 4 and plan.get('publication') is False
            and plan.get('production_approved') is False and 'prefix' not in plan and 'prefix_results' not in plan
            and 'imports' not in plan and not (run / 'imported').exists(),
            'four_fresh_segments_no_old_import_or_preserved_prefix_allowed')
    require((plan.get('frames_per_segment'), plan.get('expected_frames'), plan.get('width'), plan.get('height'),
             plan.get('fps'), plan.get('steps')) == (362, 1448, 736, 1312, 24, 12), 'fresh_minute_clock_profile_changed')
    require([s.get('shot_id') for s in plan.get('sources', [])] == list(IDS), 'four_fresh_source_segments_in_order_required')
    for name in ('config', 'authority', 'library_binding', 'binding_approval', 'library_selection'):
        checked(plan[name], project)
    entries = {}
    for row in plan['sources']:
        sid = row['shot_id']
        require(checked(row['source_case'], project) == run / 'segments' / sid / 'SOURCE_CASE.json'
                and Path(row['native_run']).resolve() == run / 'visual_h3_v3' / (run.name + '_' + sid),
                'all_fresh_sources_and_native_namespaces_must_belong_to_this_run')
        entries[sid] = source_entry(row['source_case'], sid, project)
    return dict(run=run, plan=plan, plan_binding=bind(path), entries=entries)


def _initial_guide(run, image, receipt, project):
    path = run / 'INITIAL_GUIDE.json'
    value = read(path)
    require(value.get('schema') == 'library_initial_guide/v2' and value.get('completion_known') is True
            and value.get('outcome_unknown') is False and value.get('image') == image and value == receipt,
            'S01_requires_its_actually_completed_initial_guide')
    require(set(value.get('generation_records', {})) == {'plan', 'request', 'history', 'result'},
            'actual_initial_guide_generation_records_required')
    for item in value['generation_records'].values():
        checked(item, project)
    request = read(Path(value['generation_records']['request']['path']))
    history = read(Path(value['generation_records']['history']['path']))
    pid = value.get('native_prompt_id')
    event = history.get(pid, {})
    hp, status = event.get('prompt', []), event.get('status', {})
    require(isinstance(pid, str) and len(hp) >= 3 and hp[1] == pid and request.get('prompt') == hp[2]
            and status.get('completed') is True and status.get('status_str') == 'success',
            'initial_guide_success_must_match_actual_request_and_history')
    checked(image, project)
    require(Path(image['path']).resolve().is_relative_to(run), 'fresh_initial_guide_must_be_saved_under_this_run')
    output = value.get('native_output', {})
    node, index = output.get('node_id'), output.get('index')
    require(isinstance(node, str) and type(index) is int and index >= 0, 'actual_initial_native_output_locator_required')
    emitted = event.get('outputs', {}).get(node, {}).get('images', [])
    require(index < len(emitted) and emitted[index].get('type') == 'output', 'actual_initial_native_saved_image_required')
    cfg = read(checked(read(run / 'PLAN.json')['config'], project))
    output_root = Path(cfg['output_root']).resolve()
    source = (output_root / emitted[index].get('subfolder', '') / emitted[index].get('filename', '')).resolve()
    require(output_root.is_relative_to(Path(project).resolve()) and source.is_relative_to(output_root)
            and run.name in source.relative_to(output_root).parts
            and Path(output.get('source_path', '')).resolve() == source,
            'initial_native_output_must_belong_to_this_fresh_run_namespace')
    require(value.get('source_image') == bind(source) and sha(source) == image['sha256'],
            'initial_guide_pixels_must_match_same_native_output')
    result = read(checked(value['generation_records']['result'], project))
    def has_image_binding(data):
        if isinstance(data, dict):
            if data.get('sha256') == image['sha256']: return True
            return any(has_image_binding(v) for v in data.values())
        if isinstance(data, list): return any(has_image_binding(v) for v in data)
        return False
    require(has_image_binding(result), 'initial_native_RESULT_must_bind_the_same_image_SHA')
    return dict(binding=bind(path), value=value, native_id=pid)


def prepared_graph(native_run, sid, project=PROJECT):
    project, nr = Path(project).resolve(), Path(native_run).resolve()
    require(sid in IDS and nr.is_relative_to(project / 'data'), 'explicit_new_library_native_run_required')
    plan_path, folder = nr / 'PLAN.json', nr / 'shots' / sid
    plan = read(plan_path)
    require(plan.get('schema') == NATIVE_SCHEMA and plan.get('upstream_contract') == INPUT_SCHEMA
            and plan.get('old_batch_resume') is False and plan.get('publication') is False
            and plan.get('production_approved') is False and plan.get('full_video_quality_passed') is False
            and len(plan.get('shots', [])) == 1, 'fresh_library_native_contract_required_no_imports')
    row = plan['shots'][0]
    require(row.get('id') == sid and 'continuity_input' not in row and 'full_asset_input' not in row,
            'exact_new_library_proof_not_old_continuation_schema_required')
    series_path = checked(plan['series_plan'], project)
    series = series_inputs(series_path.parent, project)
    run = series['run']
    require(nr == run / 'visual_h3_v3' / (run.name + '_' + sid), 'fresh_native_namespace_changed')
    input_path = checked(plan['input'], project)
    require(input_path == run / 'segments' / sid / 'LIBRARY_INPUT.json', 'per_segment_actual_library_input_required')
    context = read(input_path)
    require(context.get('schema') == INPUT_SCHEMA and context.get('shot_id') == sid
            and context.get('production_approved') is False and context.get('publication') is False
            and context.get('full_video_quality_passed') is False,
            'actual_library_input_cannot_claim_generated_content_passed')
    entry = series['entries'][sid]
    require(context.get('source_case') == plan.get('source') == bind(run / 'segments' / sid / 'SOURCE_CASE.json')
            and context.get('entry_sha256') == digest(entry), 'current_segment_source_binding_changed')
    script = minimum_script(entry, context.get('script_fields'), sid)
    require(set(context.get('required_actor_assets', [])) == set(script['required_actor_ids'])
            and len(context['required_actor_assets']) == len(script['required_actor_ids']),
            'all_segment_actor_assets_cannot_be_filtered_by_first_shot')
    refs = context.get('references', [])
    require(2 <= len(refs) <= 9 and refs[-1].get('kind') == 'dynamic_guide'
            and refs[-1].get('entity_id') == 'current_scene_state' and refs[-1].get('view') == 'guide_start'
            and refs[-1].get('version') == 1, 'last_reference_must_be_real_dynamic_guide')
    require(context.get('library_binding') == series['plan']['library_binding']
            and context.get('binding_approval') == series['plan']['binding_approval'], 'same_library_binding_and_confirmation_for_all_segments')
    selection = read(checked(series['plan']['library_selection'], project))
    library = library_reference_cards(context['library_binding'], refs[:-1], script['required_actor_ids'], script['place_id'], project,
                                      expected_place_views=selection['place_views'])
    binding_confirmation(context['library_binding'], context['binding_approval'], library, project)
    resolution = context.get('library_resolution', {})
    require(resolution.get('status') == 'ready' and resolution.get('model_dispatch_allowed') is True
            and resolution.get('binding_index') == context['library_binding']
            and resolution.get('binding_approval') == context['binding_approval']
            and resolution.get('production_approved') is False
            and len(resolution.get('references', [])) == len(refs)-1,
            'real_resolved_library_bundle_and_descriptions_required')
    for actual, base in zip(refs[:-1], resolution['references']):
        require({k: actual.get(k) for k in base} == base, 'declared_reference_differs_from_actual_library_resolution')
    for actor in script['required_actor_ids']:
        require(resolution.get('character_descriptions', {}).get(actor) == library['cards'][actor]['card'],
                'character_description_must_be_this_registered_feature_card')
    require(resolution.get('environment_description') == library['cards'][script['place_id']]['card'],
            'environment_description_must_be_this_registered_feature_card')
    image = context.get('first_image')
    require(image == row.get('first_frame') == refs[-1].get('image'), 'actual_dynamic_guide_image_changed')
    checked(image, project)
    require(rgb_bytes(image['path'])[0] == (736, 1312), 'native_geometry_current_guide_required')
    predecessor = context.get('predecessor_result')
    if sid == 'S01':
        require(predecessor is None, 'S01_has_no_fabricated_previous_video')
        initial = _initial_guide(run, image, context.get('generation_receipt'), project)
        require(refs[-1].get('asset_id') == 'initial:' + initial['native_id'], 'initial_guide_reference_ID_changed')
    else:
        previous_sid = IDS[IDS.index(sid)-1]
        previous_path = run / 'visual_h3_v3' / (run.name + '_' + previous_sid) / 'shots' / previous_sid / 'RESULT.json'
        require(checked(predecessor, project) == previous_path, 'previous_tail_must_be_this_fresh_runs_immediate_predecessor')
        previous = validate_new_native(previous_path.parents[2], previous_sid, project)
        require(previous['originals']['last']['local'] == image
                and refs[-1].get('asset_id') == 'native_tail:' + previous['native_id'],
                'actual_saved_current_run_native_last_is_required_not_an_old_or_future_frame')
        require(context.get('generation_receipt', {}).get('result_binding') == predecessor,
                'actual_predecessor_generation_receipt_required')
    review_path = checked(context['guide_review'], project)
    review = read(review_path)
    visible = context.get('guide_visible_actor_ids', [])
    world = context.get('world_actor_state', {})
    require(review_path == run / 'segments' / sid / 'GUIDE_STATE_REVIEW.json'
            and review.get('schema') == STATE_SCHEMA and review.get('shot_id') == sid
            and review.get('predecessor_result') == predecessor and review.get('guide_image') == image
            and review.get('completion_known') is True and review.get('outcome_unknown') is False
            and bool(review.get('reviewed_by')) and bool(review.get('evidence'))
            and review.get('guide_visible_actor_ids') == visible and review.get('world_actor_state') == world
            and len(visible) == len(set(visible)) and set(visible) <= set(script['required_actor_ids'])
            and set(review.get('screen_identity_map', {})) == set(visible)
            and set(world) == set(script['required_actor_ids'])
            and all(isinstance(t, str) and t.strip() for t in [*world.values(), *review['screen_identity_map'].values()]),
            'actual_guide_state_and_visible_subset_must_not_replace_whole_clip_assets')
    proof = {k: deepcopy(context[k]) for k in ('schema', 'source_case', 'first_image', 'predecessor_result', 'guide_review',
        'library_binding', 'binding_approval', 'library_resolution', 'references', 'required_actor_assets',
        'guide_visible_actor_ids', 'world_actor_state', 'script_fields', 'compiled_prompt_utf8_sha256')}
    proof['input'] = plan['input']
    require(row.get('library_input') == proof, 'native_frozen_library_input_proof_changed')
    refs_map = row.get('reference_map', [])
    require(len(refs_map) == len(refs), 'no_declared_reference_can_be_silently_dropped')
    root = Path(plan['config']['input_root']).resolve()
    require(root.is_relative_to(project), 'actual_staged_assets_must_stay_in_project')
    normalized = []
    for i, (mapping, expected) in enumerate(zip(refs_map, refs)):
        require({k: mapping.get(k) for k in expected} == expected and mapping.get('slot') == i
                and mapping.get('tag') == f'<Picture {i+1}>', 'actual_library_reference_map_or_slot_changed')
        staged = (root / mapping['input_name']).resolve()
        require(staged.is_relative_to(root), 'staged_reference_path_escaped')
        normalized.append(dict(slot=i, label=f'P{i+1}', source=expected['image'], staged=bind(staged),
                               node_id=f'ref_{i}', input_name=mapping['input_name']))
    require(row.get('input_name') == refs_map[-1]['input_name'], 'guide_input_name_is_not_actual_dynamic_reference')
    graph_path = folder / 'workflow_api.json'
    graph = read(graph_path)
    routes = graph_pixel_routes(graph, normalized, project)
    prompt = graph[routes['ref_node']]['inputs']['prompt']
    require(prompt == context.get('compiled_prompt') and digest(graph) == row.get('graph_sha256')
            and hashlib.sha256(prompt.encode()).hexdigest() == context.get('compiled_prompt_utf8_sha256')
            and quotes(prompt) == EXPECTED_QUOTES[sid], 'actual_prompt_or_ten_original_quotes_changed')
    for item in library['cards'].values():
        require(item['card']['description'] in prompt, 'bound_asset_description_not_actually_sent_in_prompt')
    require((graph['124']['inputs']['steps'], graph['130']['inputs']['fps'], row['timing']['native_frames'],
             row['timing']['requested_seconds']) == (12, 24, 362, 15)
            and row['timing'].get('automatic_audio_cut') is False, 'fresh_native_video_profile_changed')
    for item in (plan['series_plan'], plan['base_workflow'], *plan['code']):
        old_reference_qa.checked_code(item, project)
    return dict(nr=nr, folder=folder, plan=plan, row=row, graph=graph, context=context, library=library,
                routes=routes, first_input=image, source=plan['source'], script=script, entry=entry,
                binding=dict(plan=bind(plan_path), input=plan['input'], graph=bind(graph_path),
                             series_plan=plan['series_plan'], library_binding=context['library_binding'],
                             binding_approval=context['binding_approval'], guide_review=bind(review_path)))


def validate_new_native(native_run, sid, project=PROJECT):
    value = prepared_graph(native_run, sid, project)
    nr, folder, plan, row, graph = [value[k] for k in ('nr', 'folder', 'plan', 'row', 'graph')]
    require(read(folder / 'REQUEST.json').get('prompt') == graph, 'actual_POST_library_graph_changed')
    state, result = read(folder / 'STATE.json'), read(folder / 'RESULT.json')
    pid = state.get('prompt_id')
    require(state.get('status') == 'technical_saved' and state.get('id') == sid and pid
            and state.get('plan_sha256') == digest(plan)
            and result.get('prompt_id') == read(folder / 'RESPONSE.json').get('prompt_id') == pid,
            'original_saved_fresh_native_ID_required_unknown_is_not_success')
    require(result.get('schema') == media_qa.native.SCHEMA and result.get('shot_id') == sid
            and result.get('technical_status') == 'technical_saved'
            and result.get('graph_sha256') == row['graph_sha256']
            and result.get('first_frame_sha256') == row['first_frame']['sha256']
            and result.get('timing') == row['timing'] and result.get('production_approved') is False
            and result.get('publication') is False and result.get('old_batch_resume') is False
            and result.get('continuity_input') is None, 'fresh_native_RESULT_technical_contract_changed')
    claim = read(folder / 'CLAIM.json')
    require(claim.get('graph_sha256') == row['graph_sha256']
            and claim.get('first_frame_sha256') == row['first_frame']['sha256'], 'actual_library_submission_CLAIM_changed')
    history = read(folder / 'HISTORY.json').get(pid, {})
    hp, status = history.get('prompt', []), history.get('status', {})
    require(len(hp) > 2 and hp[1] == pid
            and media_qa.native.native_graph_equivalence(graph, hp[2]) is not None
            and status.get('completed') is True and status.get('status_str') == 'success',
            'actual_original_fresh_success_history_required')
    output_root = Path(plan['config']['output_root']).resolve()
    scope = (output_root / row['scope']).resolve()
    require(output_root.is_relative_to(Path(project).resolve()) and scope.is_relative_to(output_root)
            and set(result.get('files', {})) == {'video', 'audio', 'first', 'last'}, 'four_fresh_scoped_originals_required')
    originals = {}
    for role, item in result['files'].items():
        local, origin = checked(item, project), Path(item['source_path']).resolve()
        require(local.is_relative_to(folder / 'artifacts') and local.stat().st_size > 0
                and origin.parent == scope and origin.is_file() and sha(origin) == item['sha256'],
                'actual_fresh_native_original_pixels_changed')
        emitted = history.get('outputs', {}).get('save_' + role, {}).get('audio' if role == 'audio' else 'images', [])
        require(len(emitted) == 1 and emitted[0].get('type') == 'output'
                and (output_root / emitted[0].get('subfolder', '') / emitted[0]['filename']).resolve() == origin,
                'actual_fresh_native_output_history_changed')
        originals[role] = dict(local=bind(local), native_original=bind(origin))
    sidecar_path = nr / 'LIBRARY_RESULT.json'
    sidecar = read(sidecar_path)
    records = dict(plan=bind(nr / 'PLAN.json'), request=bind(folder / 'REQUEST.json'), history=bind(folder / 'HISTORY.json'))
    require(sidecar.get('schema') == INPUT_SCHEMA and sidecar.get('native_result') == bind(folder / 'RESULT.json')
            and sidecar.get('input') == plan['input'] and sidecar.get('library_input') == row['library_input']
            and sidecar.get('native_records') == records and sidecar.get('production_approved') is False,
            'actual_library_result_receipt_changed')
    return dict(id=sid, kind='new', native_id=pid, result_binding=bind(folder / 'RESULT.json'), originals=originals,
                first_input=value['first_input'], actual_seed=graph['129']['inputs']['noise_seed'],
                expected_quotes=EXPECTED_QUOTES[sid], source_entry=value['entry'], library_receipt=bind(sidecar_path),
                input_status=dict(contract=INPUT_SCHEMA, actual_positive_reference_count=len(value['context']['references']),
                                  dynamic_guide_frame=0, pixel_routes=value['routes'], library_binding=value['context']['library_binding'],
                                  required_actor_assets=value['context']['required_actor_assets'],
                                  guide_visible_actor_ids=value['context']['guide_visible_actor_ids'],
                                  version_bound_feature_cards={k:v['card_binding'] for k,v in value['library']['cards'].items()},
                                  script_minimum_fields_verified=True, CPU_identity_quality_verified=False),
                references=value['context']['references'], binding=dict(native_result=bind(folder / 'RESULT.json'),
                    plan=bind(nr / 'PLAN.json'), request=records['request'], history=records['history'],
                    library_input=plan['input'], library_receipt=bind(sidecar_path)))


def validate_prepared(run, project=PROJECT):
    value = series_inputs(run, project)
    from src.content_factory import visual_asset_feature_cards_v1 as features
    selection = read(checked(value['plan']['library_selection'], project))
    rows = []
    for sid in IDS:
        entry = value['entries'][sid]
        resolution = features.resolve_segment(value['plan']['library_binding'], actor_ids=list(entry['character_names']),
            place_id=selection['place_id'], angle_by_actor=selection['angle_by_actor'],
            place_views=tuple(selection['place_views']), approval_path=value['plan']['binding_approval'], reference_limit=8)
        if resolution.get('status') != 'ready':
            return dict(status='missing_assets_notification_required', shot_id=sid,
                        notice=missing_notice(resolution), model_posts=0, publication=False)
        library = library_reference_cards(value['plan']['library_binding'], resolution['references'],
                                          list(entry['character_names']), selection['place_id'], project,
                                          expected_place_views=selection['place_views'])
        binding_confirmation(value['plan']['library_binding'], value['plan']['binding_approval'], library, project)
        nr = value['run'] / 'visual_h3_v3' / (value['run'].name + '_' + sid)
        if (nr / 'PLAN.json').exists():
            prepared = prepared_graph(nr, sid, project)
            rows.append(dict(shot_id=sid, status='actual_prepared_graph_verified', binding=prepared['binding'],
                             reference_count=len(prepared['routes']['reference_slots']), CPU_identity_quality_verified=False))
        else:
            rows.append(dict(shot_id=sid, status='native_graph_not_prepared_yet', bound_library_refs=len(resolution['references']),
                             actual_positive_reference_count=None, CPU_identity_quality_verified=False))
    return dict(status='CPU_prepared_inspection_complete', series_plan=value['plan_binding'], all_segments_new=True,
                segments=rows, model_posts=0, GPU_calls=0, content_quality_passed=False)


def validate(run, project=PROJECT):
    value = series_inputs(run, project)
    run, plan = value['run'], value['plan']
    rows = []
    for sid in IDS:
        descriptor_path = run / 'segments' / sid / 'FINAL_RESULT.json'
        descriptor = read(descriptor_path)
        nr = run / 'visual_h3_v3' / (run.name + '_' + sid)
        row = validate_new_native(nr, sid, project)
        require(descriptor.get('native_result') == row['result_binding']
                and descriptor.get('file') == row['originals']['video']['local']
                and descriptor.get('prompt_id') == row['native_id'] and descriptor.get('postprocessing') == []
                and descriptor.get('library_receipt') == row['library_receipt']
                and descriptor.get('production_approved') is False, 'fresh_segment_descriptor_changed')
        row['descriptor'] = bind(descriptor_path)
        rows.append(row)
    require(len({r['native_id'] for r in rows}) == 4 and len({r['originals']['video']['local']['sha256'] for r in rows}) == 4
            and all(r['kind'] == 'new' for r in rows), 'four_distinct_fresh_native_outputs_required')
    require(all(r['input_status']['library_binding'] == plan['library_binding'] for r in rows),
            'all_four_segments_must_use_the_same_confirmed_library_binding')
    output_rows = [dict(shot_id=r['id'], native_result=r['result_binding'], file=r['originals']['video']['local'],
                       prompt_id=r['native_id'], kind='new', descriptor=r['descriptor']) for r in rows]
    inputs = dict(plan=value['plan_binding'], segments=output_rows)
    final = read(run / 'FINAL_RESULT.json')
    require(final.get('schema') == SERIES_SCHEMA and final.get('all_segments_new') is True
            and final.get('segments') == output_rows and final.get('native_ids') == [r['native_id'] for r in rows]
            and final.get('assembly_inputs_sha256') == digest(inputs) and final.get('publication') is False
            and final.get('production_approved') is False, 'final_movie_must_use_four_fresh_library_segments_in_order')
    request = read(run / 'ASSEMBLY_REQUEST.json')
    require(request.get('inputs') == inputs and request.get('all_segments_new') is True
            and request.get('temporal_leading_trim') is False, 'fresh_assembly_sources_or_clock_policy_changed')
    movie = checked(final['file'], project)
    require(movie == run / 'H3_LIBRARY_BOUND_MINUTE_736x1312.mp4', 'fresh_library_movie_path_changed')
    expected_command, expected_filter = media_qa.assembly_clock.assembly_command(
        [r['file']['path'] for r in output_rows], run / 'ASSEMBLY_FILTER.txt', movie, frames=362)
    require(media_qa.normalize_assembly_command(request['command'], project)
            == media_qa.normalize_assembly_command(expected_command, project)
            and (run / 'ASSEMBLY_FILTER.txt').read_text(encoding='utf-8') == expected_filter,
            'actual_fresh_assembly_command_or_source_order_changed')
    value.update(values=rows, final=final, final_binding=bind(run / 'FINAL_RESULT.json'), movie=movie)
    return value


def preview_segment(run, sid, project=PROJECT):
    run = Path(run).resolve()
    value = validate_new_native(run / 'visual_h3_v3' / (run.name + '_' + sid), sid, project)
    folder = run / 'qc_segment_previews' / sid / value['native_id']
    report, artifacts = media_qa.segment_evidence(value, folder, preview=True, project=project)
    indices = list(range(0, 49, 3))
    frames = extract_batch(value['originals']['video']['local']['path'], indices, folder / 'frames')
    opening = make_board([frames[i] for i in indices], folder / 'OPENING_DENSE.jpg', columns=5)
    artifacts.extend([opening, *[dict(path=r['path'], sha256=r['sha256']) for r in frames.values()]])
    manifest = folder / 'PREVIEW.json'
    freeze(manifest, dict(schema='library_bound_saved_native_CPU_preview/v2', report=report,
        native_binding=value['binding'], opening_dense=dict(indices=indices, contact=opening),
        native_last=value['originals']['last']['local'], pixel_routes=value['input_status']['pixel_routes'],
        artifacts=artifacts, ASR_executed=False, CPU_identity_quality_verified=False, production_approved=False))
    return dict(status='CPU_preview_complete', native_id=value['native_id'], manifest=bind(manifest),
                video=value['originals']['video']['local'], last=value['originals']['last']['local'],
                contacts=report['contacts'], opening_dense=opening)


def qa(run, *, asr=False, project=PROJECT):
    value = validate(run, project)
    run = value['run']
    folder = run / 'qc_library' / value['final']['file']['sha256'] / ('with_asr' if asr else 'without_asr')
    folder.mkdir(parents=True, exist_ok=True)
    binding = dict(plan=value['plan_binding'], final=value['final_binding'], video=value['final']['file'],
                   library_binding=value['plan']['library_binding'], library_confirmation=value['plan']['binding_approval'],
                   originals=[r['binding'] for r in value['values']], descriptors=[r['descriptor'] for r in value['values']],
                   all_segments_new=True, asr_requested=asr)
    freeze(folder / 'BINDING.json', binding)
    manifest = folder / 'FINAL_QA.json'
    if manifest.exists():
        prior = read(manifest)
        require(prior['binding'] == binding, 'existing_library_QA_input_changed')
        for item in prior['artifacts']: checked(item, project)
        return dict(status='already_complete', manifest=bind(manifest), file=value['final']['file'])
    attempt = folder / 'attempts' / uuid.uuid4().hex
    attempt.mkdir(parents=True)
    code = attempt / 'qa_source.py'; code.write_bytes(Path(__file__).read_bytes())
    freeze(attempt / 'START.json', dict(binding=binding, source_code=bind(code), at_epoch=time.time()))
    try:
        segments, artifacts = [], []
        for row in value['values']:
            sf = folder / row['id'] / row['native_id']
            segment, files = media_qa.segment_evidence(row, sf, asr=asr, project=project)
            protocol = cpu_source_protocol(row['references'], project)
            segment['installed_source_protocol'] = freeze(sf / 'CPU_SOURCE_PROTOCOL.json', protocol)
            artifacts.extend([*files, segment['installed_source_protocol']]); segments.append(segment)
        geometry, metadata = inspect_clock(value['movie'], 1448, final=True)
        artifacts.append(freeze(folder / 'FINAL_PROBE.json', metadata))
        samples = media_qa.sample_plan()
        wanted = set(samples['timeline']) | set(samples['opening']) | set(samples['repair_boundary'])
        for join in samples['joins']: wanted.update(join['indices'])
        frames = extract_batch(value['movie'], wanted, folder / 'final_frames')
        artifacts.extend(dict(path=r['path'], sha256=r['sha256']) for r in frames.values())
        timeline, regions = [], {}
        for offset in range(0, len(samples['timeline']), 21):
            indices = samples['timeline'][offset:offset+21]
            contact = make_board([frames[i] for i in indices], folder / f'TIMELINE_{offset//21+1:02d}.jpg', columns=5)
            timeline.append(dict(indices=indices, contact=contact)); artifacts.append(contact)
        for name in ('opening', 'repair_boundary'):
            contact = make_board([frames[i] for i in samples[name]], folder / (name.upper() + '.jpg'), columns=5)
            regions[name] = dict(indices=samples[name], contact=contact); artifacts.append(contact)
        for i, join in enumerate(samples['joins']):
            join['contact'] = make_board([frames[n] for n in join['indices']], folder / f'JOIN_{i+1:02d}.jpg', columns=5)
            artifacts.append(join['contact'])
        validate(run, project)
        freeze(manifest, dict(schema='library_bound_minute_CPU_QA/v2', binding=binding, source_code=bind(code),
            file=value['final']['file'], native_ids=value['final']['native_ids'], final_clock=geometry,
            library_binding=value['plan']['library_binding'], all_segments_new=True, preserved_prefix_frames=0,
            positive_reference_slots_per_clip=[r['input_status']['actual_positive_reference_count'] for r in value['values']],
            dynamic_guide_frame=0, segments=segments, timeline=timeline, regions=regions, joins=samples['joins'],
            limits=LIMITS, artifacts=list({r['path']:r for r in artifacts}.values()),
            CPU_identity_quality_verified=False, root_actual_visual_review=None, production_approved=False))
        freeze(attempt / 'COMPLETE.json', dict(manifest=bind(manifest), at_epoch=time.time()))
        return dict(status='CPU_QA_complete', manifest=bind(manifest), file=value['final']['file'],
                    timeline=[r['contact'] for r in timeline], joins=[r['contact'] for r in samples['joins']])
    except Exception as error:
        freeze(attempt / 'ERROR.json', dict(type=type(error).__name__, message=str(error),
               traceback=traceback.format_exc(), no_media_retry=True))
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--project-root', type=Path, default=PROJECT)
    parser.add_argument('--prepared', action='store_true')
    parser.add_argument('--preview', choices=IDS)
    parser.add_argument('--asr', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = (validate_prepared(args.run, args.project_root) if args.prepared else
                  preview_segment(args.run, args.preview, args.project_root) if args.preview else
                  qa(args.run, asr=args.asr, project=args.project_root))
    except Exception as error:
        print(json.dumps(dict(status='CPU_QA_failed', error=type(error).__name__, message=str(error), no_media_retry=True), ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
