"""CPU evidence for full-asset H3 Ref2VA continuations.

Every reference must be real pixels on the positive path.  A manifest, actor
count, bound observation or successful graph alone is never an identity pass.
No HTTP, GPU, model submission, media retry, or automatic content approval.
"""
import argparse
import ast
from copy import deepcopy
import hashlib
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
import qa_h3_identity_continuation as previous_qa

DEFAULT_RUN = PROJECT / 'data/video_generation/h3_full_asset_continuation_20261111_v1'
FIXED_SCHEMA = 'accepted_video_fixed_reference_assets/v1'
FIXED_VERSION = 'accepted_S02_identity_environment_20261111_v1'
EXPECTED_ACTORS = ('su_mo', 'ye_nan', 'ye_xijue')
NODE_SOURCE = Path('D:/IT/AI_vido/ComfyUI/comfy_extras/nodes_minimax_h3.py')
MODEL_SOURCE = Path('D:/IT/AI_vido/ComfyUI/comfy/model_base.py')
DIT_SOURCE = Path('D:/IT/AI_vido/ComfyUI/comfy/ldm/minimax/model.py')
CONDITIONING_HELPER_SOURCE = Path('D:/IT/AI_vido/ComfyUI/node_helpers.py')
REF_MODEL = 'minimax_h3_ref2va_pruned_int8_convrot.safetensors'
SERIES_SCHEMA = 'h3_full_asset_continuation_series/v1'
NATIVE_SCHEMA = 'h3_full_asset_continuation_native/v1'
INPUT_SCHEMA = 'actual_full_assets_and_native_guide/v1'
CONDITIONING_MODE = 'Ref2VA_six_references_and_frame0_guide'
IDS = previous_qa.IDS
NEW_IDS = previous_qa.NEW_IDS
EXPECTED_QUOTES = previous_qa.EXPECTED_QUOTES


def rgb_bytes(path):
    with Image.open(path) as image:
        require(getattr(image, 'n_frames', 1) == 1, 'one_reference_must_be_one_static_image_not_hidden_batch')
        return image.size, image.convert('RGB').tobytes()


def fixed_assets(manifest_binding, project=PROJECT):
    """Verify the actual approved-video crop pixels, never invented views."""
    path = checked(manifest_binding, project)
    value = read(path)
    require(value.get('schema') == FIXED_SCHEMA and value.get('asset_version') == FIXED_VERSION
            and value.get('fixed_reference_count') == 5 and value.get('fixed_order') == ['P1', 'P2', 'P3', 'P4', 'P5']
            and value.get('source_native_id') == previous_qa.RETAINED['S02'][0]
            and value.get('source_video', {}).get('sha256') == previous_qa.RETAINED['S02'][1],
            'exact_accepted_video_fixed_asset_version_required')
    checked(value['source_video'], project)
    checked(value['source_native_result'], project)
    checked(value['source_QA_binding'], project)
    verification_path = checked(value['source_frame_verification'], project)
    verification = read(verification_path)
    require(verification.get('source_video') == value['source_video']
            and verification.get('native_id') == value['source_native_id']
            and verification.get('CPU_only') is True, 'source_frame_CPU_decode_receipt_changed')
    refs = value.get('references', [])
    require(len(refs) == 5, 'exact_five_fixed_reference_rows_required')
    observations = []
    for index, row in enumerate(refs):
        require(row.get('slot') == index and row.get('label') == f'P{index+1}'
                and row.get('tag') == f'<Picture {index+1}>' and row.get('asset_version') == FIXED_VERSION,
                'fixed_slot_label_or_reference_order_changed')
        if index < 3:
            require(row.get('entity_id') == row.get('actor_id') == EXPECTED_ACTORS[index]
                    and row.get('kind') == 'character', 'fixed_actor_slot_identity_changed')
        else:
            require(row.get('intended_person_count') == 0 and row.get('kind') in ('environment', 'environment_detail'),
                    'P4_P5_are_environment_details_not_additional_cast')
        source = row['source']
        require(source.get('native_id') == value['source_native_id'] and source.get('video') == value['source_video']
                and source.get('fps') == 24 and type(source.get('frame_index')) is int
                and 0 <= source['frame_index'] < 362, 'reference_source_video_or_frame_changed')
        frame = checked(source['frame'], project)
        checked(source['qa_report'], project)
        image_path = checked(row['image'], project)
        derivation = row['derivation']
        require(derivation.get('operation') == 'PIL_RGB_integer_crop_only' and derivation.get('resize') is None
                and derivation.get('rotation_degrees') == 0 and derivation.get('upscale') is False
                and derivation.get('source_orientation_preserved') is True
                and derivation.get('exact_pixels_sha256_kind') == 'RGB24_row_major_bytes',
                'fixed_asset_must_preserve_declared_source_crop_pixels')
        roi = row['roi']
        require(set(roi) == {'x', 'y', 'width', 'height'}
                and all(type(v) is int for v in roi.values())
                and min(roi['x'], roi['y']) >= 0 and min(roi['width'], roi['height']) > 0,
                'explicit_integer_crop_required')
        with Image.open(frame) as original:
            require(roi['x'] + roi['width'] <= original.width and roi['y'] + roi['height'] <= original.height,
                    'source_crop_out_of_bounds')
            source_rgb = original.convert('RGB')
            expected = source_rgb.crop((roi['x'], roi['y'], roi['x'] + roi['width'], roi['y'] + roi['height'])).tobytes()
            frame_hash = hashlib.sha256(source_rgb.tobytes()).hexdigest()
        size, actual = rgb_bytes(image_path)
        require(size == (roi['width'], roi['height']) and actual == expected
                and hashlib.sha256(actual).hexdigest() == derivation['exact_pixels_sha256']
                and all(v % 32 == 0 for v in size), 'fixed_crop_actual_RGB_pixels_changed')
        decoded = [r for r in verification.get('frames', []) if r.get('frame_index') == source['frame_index']]
        require(len(decoded) == 1 and decoded[0].get('frame') == source['frame']
                and decoded[0].get('rgb24_pixels_sha256') == frame_hash
                and decoded[0].get('exact_source_decode_pixels') is True,
                'source_frame_pixels_not_bound_to_actual_CPU_decode')
        observations.append(dict(slot=index, label=row['label'], entity_id=row['entity_id'], image=bind(image_path),
                                 source_frame=source['frame'], source_frame_index=source['frame_index'], roi=roi,
                                 actual_RGB_pixels_sha256=hashlib.sha256(actual).hexdigest(), size=list(size),
                                 semantic_identity_verified_by_CPU=False))
    return dict(manifest=bind(path), source_frame_verification=bind(verification_path), references=observations,
                reference_order=['P1', 'P2', 'P3', 'P4', 'P5'], identity_quality_passed=False,
                environment_scope='two real background detail crops, not invented complete room views')


def source_method(path, class_name, method_name):
    """Return the exact installed official function AST for CPU protocol tests."""
    module = ast.parse(Path(path).read_text(encoding='utf-8'))
    body = (next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == class_name).body
            if class_name is not None else module.body)
    method = deepcopy(next(node for node in body if isinstance(node, ast.FunctionDef) and node.name == method_name))
    method.decorator_list = []
    method.returns = None
    for argument in method.args.args + method.args.kwonlyargs:
        argument.annotation = None
    if method.args.vararg:
        method.args.vararg.annotation = None
    if method.args.kwarg:
        method.args.kwarg.annotation = None
    return method


def cpu_source_protocol(reference_rows, tail_binding, project=PROJECT):
    """Execute installed node/model methods with CPU-only encoder doubles.

    This proves their data-flow protocol, not real VAE quality or attention.
    Actual generation proof must additionally bind the saved POST and history.
    """
    require(len(reference_rows) == 5, 'five_fixed_refs_required_for_six_slot_protocol')
    images = []
    for index, row in enumerate(reference_rows):
        path = checked(row['image'], project)
        size, pixels = rgb_bytes(path)
        images.append((f'P{index+1}', size, hashlib.sha256(pixels).hexdigest()))
    tail = checked(tail_binding, project)
    tail_size, tail_pixels = rgb_bytes(tail)
    require(tail_size == (736, 1312), 'guide_tail_native_geometry_required')
    images.append(('P6', tail_size, hashlib.sha256(tail_pixels).hexdigest()))

    class Tensor:
        def __init__(self, tag, shape, pixel_sha=None):
            self.tag, self.shape, self.pixel_sha = tag, shape, pixel_sha
            self.ndim = len(shape)
        def __getitem__(self, item):
            require(isinstance(item, slice), 'source_protocol_unexpected_tensor_index')
            return self
    resize_calls, encodes = [], []
    def resize(image, width, height, crop):
        resize_calls.append(dict(tag=image.tag, source_shape=image.shape, width=width, height=height, crop=crop))
        require((width, height) == (image.shape[2], image.shape[1]),
                'current_six_assets_must_not_be_implicitly_cropped_or_resized')
        return image
    class VAE:
        def encode(self, image):
            encodes.append(dict(tag=image.tag, pixel_sha=image.pixel_sha, shape=image.shape))
            return Tensor(image.tag, (1, 24, 1, image.shape[1] // 16, image.shape[2] // 16))
    class Clip:
        def tokenize(self, prompt, **kwargs):
            return kwargs
        def encode_from_tokens_scheduled(self, tokens):
            self.items = tokens['minimax_ref_items']
            return [[None, {}]]
    samples = SimpleNamespace(is_nested=True, tensors=(
        Tensor('video', (1, 24, 107, 82, 46)), Tensor('audio', (1, 32, 2, 603))))
    def empty(width, height, length):
        require((width, height, length) == (736, 1312, 362), 'source_protocol_profile_changed')
        return {'samples': samples}, 362
    namespace = dict(math=math, CANVAS_MULTIPLE=32, REF_IMAGE_SHORT_EDGE=2048, FRAME_PER_TOKEN=(1, 4, 4, 4, 4),
                     FRAME_RESCALE=5.0/3.0, FPS=24, _empty_av_latent=empty, _resize=resize,
                     io=SimpleNamespace(NodeOutput=lambda *items: items))
    setter = source_method(CONDITIONING_HELPER_SOURCE, None, 'conditioning_set_values')
    exec(compile(ast.fix_missing_locations(ast.Module(body=[setter], type_ignores=[])), str(CONDITIONING_HELPER_SOURCE), 'exec'), namespace)
    namespace['node_helpers'] = SimpleNamespace(conditioning_set_values=namespace['conditioning_set_values'])
    ref_method = source_method(NODE_SOURCE, 'MiniMaxH3ReferenceToVideo', 'execute')
    guide_method = source_method(NODE_SOURCE, 'MiniMaxH3AddGuide', 'execute')
    exec(compile(ast.fix_missing_locations(ast.Module(body=[ref_method], type_ignores=[])), str(NODE_SOURCE), 'exec'), namespace)
    ref_execute = namespace['execute']
    exec(compile(ast.fix_missing_locations(ast.Module(body=[guide_method], type_ignores=[])), str(NODE_SOURCE), 'exec'), namespace)
    guide_execute = namespace['execute']
    tensors = {f'ref_image_{index}': Tensor(tag, (1, size[1], size[0], 3), pixel_sha)
               for index, (tag, size, pixel_sha) in enumerate(images)}
    clip, vae = Clip(), VAE()
    positive, latent = ref_execute(None, clip=clip, vae=vae, prompt='source protocol only',
                                  width=736, height=1312, length=362, ref_image_size='match', ref_images=tensors)
    require([r['tag'] for r in encodes] == ['P1', 'P2', 'P3', 'P4', 'P5', 'P6']
            and len(positive[0][1].get('minimax_refs', [])) == 6
            and [item['data'].tag for item in clip.items] == ['P1', 'P2', 'P3', 'P4', 'P5', 'P6'],
            'installed_reference_node_did_not_encode_all_six_positive_refs_in_order')
    positive, = guide_execute(None, positive=positive, latent=latent, frame_idx=0, vae=vae, image=tensors['ref_image_5'])
    require([r['tag'] for r in encodes] == ['P1', 'P2', 'P3', 'P4', 'P5', 'P6', 'P6']
            and positive[0][1]['minimax_keyframes'][0]['resolved_frame_index'] == 0,
            'installed_guide_node_did_not_encode_actual_tail_at_frame_zero')

    class Base:
        def extra_conds(self, **kwargs):
            return {}
    method = source_method(MODEL_SOURCE, 'MiniMaxH3', 'extra_conds')
    extra_namespace = dict(Base=Base, comfy=SimpleNamespace(conds=SimpleNamespace(CONDConstant=lambda x: x)))
    cls = ast.ClassDef(name='ProtocolMiniMaxH3', bases=[ast.Name(id='Base', ctx=ast.Load())], keywords=[],
                       body=[method], decorator_list=[])
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), str(MODEL_SOURCE), 'exec'), extra_namespace)
    model = extra_namespace['ProtocolMiniMaxH3']()
    model.audio_scale = lambda: 1.0
    payload = model.extra_conds(**positive[0][1])['minimax_payload']
    require(len(payload.get('refs', [])) == 6 and len(payload.get('keyframes', [])) == 1
            and [tensor.tag for tensor in payload['cond_video_latents']] == ['P6', 'P1', 'P2', 'P3', 'P4', 'P5', 'P6'],
            'installed_model_did_not_consume_refs_and_guide_in_positive_payload')
    return dict(schema='installed_H3_reference_source_CPU_protocol/v1', official_nodes=bind(NODE_SOURCE),
                official_model=bind(MODEL_SOURCE), official_conditioning_helper=bind(CONDITIONING_HELPER_SOURCE),
                fixed_reference_count=5, total_reference_count=6,
                reference_VAE_calls=encodes[:6], guide_VAE_call=encodes[6], resize_calls=resize_calls,
                model_positive_refs=6, model_positive_keyframes=1, guide_frame=0,
                CPU_protocol_doubles=True, GPU_model_inference=False, identity_quality_passed=False)


def one_node(graph, class_type):
    found = [node for node, value in graph.items() if value.get('class_type') == class_type]
    require(len(found) == 1, 'exactly_one_' + class_type + '_required')
    return found[0]


def graph_pixel_routes(graph, references, project=PROJECT):
    """Independent six-slot positive/VAE/guide trace, including real stage bytes.

    Each normalized row has slot/label/source/staged/node_id/input_name.  This
    function never infers that a face is correct merely because a row exists.
    """
    require(len(references) == 6 and [r.get('slot') for r in references] == list(range(6))
            and [r.get('label') for r in references] == ['P1', 'P2', 'P3', 'P4', 'P5', 'P6'],
            'six_ordered_real_pixel_reference_slots_required')
    node_ids = [row['node_id'] for row in references]
    require(len(set(node_ids)) == 6 and set(node_ids) == {
        node for node, value in graph.items() if value.get('class_type') == 'LoadImage'},
        'six_independent_LoadImage_nodes_no_disconnected_extra_assets_required')
    receipts = []
    for row in references:
        source = checked(row['source'], project)
        staged = checked(row['staged'], project)
        source_size, source_pixels = rgb_bytes(source)
        staged_size, staged_pixels = rgb_bytes(staged)
        require(bind(source)['sha256'] == bind(staged)['sha256'] and source_size == staged_size
                and source_pixels == staged_pixels, 'actual_source_to_staged_reference_pixels_changed')
        require(graph[row['node_id']].get('inputs') == {'image': row['input_name']},
                'actual_LoadImage_must_read_this_staged_reference')
        receipts.append(dict(slot=row['slot'], label=row['label'], source=bind(source), staged=bind(staged),
                             source_RGB_sha256=hashlib.sha256(source_pixels).hexdigest(),
                             node_id=row['node_id'], input_name=row['input_name'], image_size=list(source_size)))
    ref_id, guide_id = one_node(graph, 'MiniMaxH3ReferenceToVideo'), one_node(graph, 'MiniMaxH3AddGuide')
    ref, guide = graph[ref_id]['inputs'], graph[guide_id]['inputs']
    ports = [f'ref_images.ref_image_{index}' for index in range(6)]
    require([key for key in ref if key.startswith('ref_images.')] == ports
            and all(ref[port] == [node_ids[index], 0] for index, port in enumerate(ports))
            and 'ref_images' not in ref and not any(key.startswith(('ref_videos', 'ref_audios', 'ref_video_audios')) for key in ref),
            'actual_six_autogrow_image_inputs_or_order_changed')
    require((ref.get('width'), ref.get('height'), ref.get('length')) == (736, 1312, 362)
            and ref.get('ref_image_size') == 'match', 'Ref2VA_reference_profile_changed')
    tags = re.findall(r'<Picture (\d+)>', ref.get('prompt', ''))
    require(set(tags) == set('123456'), 'prompt_must_address_exact_actual_six_reference_slots')
    vae_id = ref.get('vae', [None])[0]
    require(ref.get('vae') == [vae_id, 0] and graph.get(vae_id, {}).get('class_type') == 'VAELoader'
            and 'minimax_h3' in graph[vae_id]['inputs'].get('vae_name', '').lower()
            and 'audio' not in graph[vae_id]['inputs'].get('vae_name', '').lower(),
            'real_video_VAE_required_for_all_reference_images')
    clip_id = ref.get('clip', [None])[0]
    require(ref.get('clip') == [clip_id, 0] and graph.get(clip_id, {}).get('class_type') == 'CLIPLoader',
            'real_reference_text_encoder_required')
    require(guide.get('positive') == [ref_id, 0] and guide.get('latent') == [ref_id, 1]
            and guide.get('vae') == [vae_id, 0] and guide.get('image') == [node_ids[5], 0]
            and guide.get('frame_idx') == 0 and 'audio' not in guide,
            'P6_must_also_be_actual_frame_zero_VAE_guide_on_positive_path')
    guider_id, sampler_id = one_node(graph, 'BasicGuider'), one_node(graph, 'SamplerCustomAdvanced')
    guider, sampler = graph[guider_id]['inputs'], graph[sampler_id]['inputs']
    require(guider.get('conditioning') == [guide_id, 0] and sampler.get('guider') == [guider_id, 0]
            and sampler.get('latent_image') == [ref_id, 1],
            'reference_and_guide_conditioning_must_reach_actual_positive_sampler')
    unet_id = guider.get('model', [None])[0]
    require(guider.get('model') == [unet_id, 0] and graph.get(unet_id, {}).get('class_type') == 'UNETLoader'
            and graph[unet_id]['inputs'].get('unet_name') == REF_MODEL,
            'real_Ref2VA_checkpoint_required_not_FL2VA_name_or_metadata')
    previous_qa.exact_endpoint_selection(graph)
    return dict(reference_slots=receipts, ref_node=ref_id, video_vae_node=vae_id, guide_node=guide_id,
                positive_guider=guider_id, sampler=sampler_id, ref2va_model_node=unet_id,
                actual_positive_reference_count=6, actual_positive_guide_frame=0,
                path='source bytes -> staged bytes -> independent LoadImage -> ref_images -> video VAE -> positive -> sampler',
                CPU_identity_quality_verified=False)


def checked_code(binding, project=PROJECT):
    path = Path(binding['path']).resolve()
    allowed = {p.resolve() for p in (NODE_SOURCE, MODEL_SOURCE, DIT_SOURCE)}
    if path in allowed:
        require(path.is_file() and sha(path) == binding['sha256'], 'explicit_Comfy_capability_source_changed')
        return path
    return checked(binding, project)


def input_context(binding):
    from src.content_factory.visual_h3_full_asset_continuation_v1 import validate_input
    return validate_input(binding)


def prepared_graph(native_run, sid, project=PROJECT):
    project, nr = Path(project).resolve(), Path(native_run).resolve()
    require(nr.is_relative_to(project / 'data/video_generation') and sid in NEW_IDS,
            'explicit_project_new_reference_native_run_required')
    folder, plan = nr / 'shots' / sid, read(nr / 'PLAN.json')
    require(plan.get('schema') == NATIVE_SCHEMA and plan.get('upstream_contract') == INPUT_SCHEMA
            and plan.get('conditioning_mode') == CONDITIONING_MODE and plan.get('publication') is False
            and plan.get('production_approved') is False and plan.get('old_batch_resume') is False
            and plan.get('full_video_quality_passed') is False and len(plan.get('shots', [])) == 1,
            'explicit_full_asset_reference_contract_required')
    row = plan['shots'][0]
    require(row.get('id') == sid and 'continuity_input' not in row, 'new_reference_contract_must_not_forge_old_ready_proof')
    context = input_context(plan['input'])
    proof = row['full_asset_input']
    require(context['proof'] == proof and proof.get('schema') == INPUT_SCHEMA
            and proof.get('input') == plan['input'] and proof['source_case'] == plan['source']
            and context.get('conditioning_mode') == CONDITIONING_MODE
            and context.get('quality_passed') is False and context.get('full_video_quality_passed') is False,
            'actual_full_asset_input_proof_changed')
    source = checked(proof['source_case'], project)
    fixed = fixed_assets(proof['asset_manifest'], project)
    observed_path = checked(proof['asset_observation'], project)
    observed = read(observed_path)
    require(observed.get('schema') == 'root_fixed_reference_asset_observation/v1'
            and observed.get('manifest') == fixed['manifest'] and observed.get('asset_version') == FIXED_VERSION
            and observed.get('completion_known') is True and observed.get('outcome_unknown') is False
            and observed.get('fixed_reference_set_eligible') is True and len(observed.get('reviewed_assets', [])) == 5,
            'actual_fixed_asset_observation_binding_changed')
    manifest = read(Path(fixed['manifest']['path']))
    for expected, seen in zip(manifest['references'], observed['reviewed_assets']):
        require(seen.get('image') == {k: expected['image'][k] for k in ('path', 'sha256')}
                and seen.get('observed') is True
                and all(seen.get(k) == expected[k] for k in ('reference_id', 'slot', 'tag', 'entity_id', 'intended_person_count')),
                'root_observation_must_name_actual_five_crop_files')
    require(set(context.get('required_actor_assets', [])) == set(EXPECTED_ACTORS)
            and len(context['required_actor_assets']) == 3
            and len(context['guide_visible_actor_ids']) == len(set(context['guide_visible_actor_ids']))
            and set(context['guide_visible_actor_ids']) <= set(EXPECTED_ACTORS)
            and set(context['world_actor_state']) == set(EXPECTED_ACTORS),
            'required_actor_assets_must_not_be_filtered_by_guide_visibility')
    predecessor = checked(proof['predecessor_result'], project)
    pred_sid = 'S02' if sid == 'S03' else 'S03'
    pred_nr = predecessor.parents[2]
    previous = (previous_qa.saved_originals(pred_nr, pred_sid, project) if sid == 'S03'
                else validate_new_native(pred_nr, pred_sid, project))
    require(previous['result_binding'] == proof['predecessor_result'], 'actual_predecessor_result_changed')
    tail = previous['originals']['last']['local']
    require(context['first_image'] == row['first_frame'] == tail, 'guide_must_use_actual_predecessor_native_last')
    series_path = checked(plan['series_plan'], project)
    series_root, series = series_path.parent, read(series_path)
    require(nr == series_root / 'visual_h3_v3' / (series_root.name + '_' + sid)
            and series['asset_manifest'] == fixed['manifest'] and series['asset_observation'] == proof['asset_observation']
            and series['asset_version'] == context['asset_version'] == FIXED_VERSION,
            'same_fixed_reference_version_required_for_every_new_clip')
    if sid == 'S03':
        imported = read(series_root / 'imported/S02/IMPORT.json')
        require(proof['predecessor_result'] == imported['native_result']
                and previous['native_id'] == previous_qa.RETAINED['S02'][0]
                and previous['originals']['video']['local']['sha256'] == previous_qa.RETAINED['S02'][1],
                'first_new_clip_must_continue_the_preserved_S02')
    else:
        require(predecessor == series_root / 'visual_h3_v3' / (series_root.name + '_S03') / 'shots/S03/RESULT.json',
                'second_new_clip_must_continue_this_Ref2VA_runs_new_S03')
    guide_path = checked(proof['guide_review'], project)
    guide = read(guide_path)
    require(guide.get('schema') == 'h3_full_asset_guide_state/v1' and guide.get('shot_id') == sid
            and guide.get('predecessor_result') == proof['predecessor_result'] and guide.get('guide_image') == tail
            and guide.get('completion_known') is True and guide.get('outcome_unknown') is False
            and guide.get('guide_visible_actor_ids') == context['guide_visible_actor_ids']
            and guide.get('world_actor_state') == context['world_actor_state']
            and set(guide.get('screen_identity_map', {})) == set(context['guide_visible_actor_ids']),
            'actual_guide_screen_and_world_observation_changed')
    refs = row['reference_map']
    require(len(refs) == len(context['references']) == 6, 'actual_six_reference_map_required')
    normalized = []
    input_root = Path(plan['config']['input_root']).resolve()
    require(input_root.is_relative_to(project), 'project_staged_reference_root_required')
    for index, (mapping, expected) in enumerate(zip(refs, context['references'])):
        require(all(mapping.get(k) == v for k, v in expected.items())
                and mapping.get('slot') == index and mapping.get('tag') == f'<Picture {index+1}>',
                'slot_labels_or_reference_relationship_map_changed')
        image = fixed['references'][index]['image'] if index < 5 else tail
        require(mapping['image'] == image, 'reference_source_file_is_not_this_fixed_asset_or_actual_tail')
        staged = (input_root / mapping['input_name']).resolve()
        require(staged.is_relative_to(input_root), 'staged_reference_path_escaped')
        normalized.append(dict(slot=index, label=f'P{index+1}', source=image, staged=bind(staged),
                               node_id=f'ref_{index}', input_name=mapping['input_name']))
    require(row['input_name'] == refs[5]['input_name'], 'guide_input_name_must_be_actual_P6')
    graph = read(folder / 'workflow_api.json')
    routes = graph_pixel_routes(graph, normalized, project)
    require(digest(graph) == row['graph_sha256'] and graph['condition']['inputs']['prompt'] == context['compiled_prompt']
            and quotes(context['compiled_prompt']) == EXPECTED_QUOTES[sid]
            and proof['compiled_prompt_utf8_sha256'] == context['compiled_prompt_utf8_sha256'],
            'actual_compiled_prompt_or_five_original_quotes_changed')
    require((graph['124']['inputs']['steps'], graph['130']['inputs']['fps'], row['timing']['native_frames'],
             row['timing']['requested_seconds'], context['entry']['duration']) == (12, 24, 362, 15, 15)
            and row['timing'].get('automatic_audio_cut') is False, 'native_reference_clock_profile_changed')
    for item in (plan['series_plan'], plan['base_workflow'], *plan['code']):
        checked_code(item, project)
    return dict(nr=nr, folder=folder, plan=plan, row=row, graph=graph, context=context, fixed=fixed, routes=routes,
                first_input=tail, source=bind(source),
                binding=dict(plan=bind(nr / 'PLAN.json'), input=plan['input'], source=bind(source),
                    graph=bind(folder / 'workflow_api.json'), predecessor_result=proof['predecessor_result'],
                    fixed_manifest=fixed['manifest'], fixed_observation=proof['asset_observation'], guide_review=bind(guide_path)))


def validate_new_native(native_run, sid, project=PROJECT):
    prepared = prepared_graph(native_run, sid, project)
    folder, plan, row, graph = [prepared[k] for k in ('folder', 'plan', 'row', 'graph')]
    require(read(folder / 'REQUEST.json').get('prompt') == graph, 'actual_POST_reference_graph_changed')
    state, result = read(folder / 'STATE.json'), read(folder / 'RESULT.json')
    pid = state.get('prompt_id')
    require(state.get('status') == 'technical_saved' and state.get('id') == sid and pid
            and state.get('plan_sha256') == digest(plan)
            and result.get('prompt_id') == read(folder / 'RESPONSE.json').get('prompt_id') == pid,
            'original_saved_reference_native_ID_required')
    require(result.get('schema') == previous_qa.native.SCHEMA and result.get('shot_id') == sid
            and result.get('technical_status') == 'technical_saved' and result.get('graph_sha256') == row['graph_sha256']
            and result.get('first_frame_sha256') == row['first_frame']['sha256']
            and result.get('timing') == row['timing'] and result.get('production_approved') is False
            and result.get('publication') is False and result.get('continuity_input') is None,
            'reference_native_RESULT_must_preserve_actual_technical_contract')
    claim = read(folder / 'CLAIM.json')
    require(claim.get('graph_sha256') == row['graph_sha256']
            and claim.get('first_frame_sha256') == row['first_frame']['sha256'], 'actual_reference_CLAIM_changed')
    history = read(folder / 'HISTORY.json').get(pid, {})
    hp, hs = history.get('prompt', []), history.get('status', {})
    require(len(hp) > 2 and hp[1] == pid
            and previous_qa.native.native_graph_equivalence(graph, hp[2]) is not None
            and hs.get('completed') is True and hs.get('status_str') == 'success', 'actual_reference_success_history_changed')
    output_root = Path(plan['config']['output_root']).resolve()
    scope = (output_root / row['scope']).resolve()
    require(output_root.is_relative_to(Path(project).resolve()) and scope.is_relative_to(output_root)
            and set(result.get('files', {})) == {'video', 'audio', 'first', 'last'}, 'four_scoped_native_originals_required')
    originals = {}
    for role, item in result['files'].items():
        local, origin = checked(item, project), Path(item['source_path']).resolve()
        require(local.is_relative_to(folder / 'artifacts') and local.stat().st_size > 0
                and origin.parent == scope and origin.is_file() and sha(origin) == item['sha256'],
                'actual_reference_native_original_pixels_changed')
        mapped = history.get('outputs', {}).get('save_' + role, {}).get('audio' if role == 'audio' else 'images', [])
        require(len(mapped) == 1 and mapped[0].get('type') == 'output'
                and (output_root / mapped[0].get('subfolder', '') / mapped[0]['filename']).resolve() == origin,
                'actual_reference_native_output_history_changed')
        originals[role] = dict(local=bind(local), native_original=bind(origin))
    sidecar_path = Path(native_run) / 'FULL_ASSET_RESULT.json'
    sidecar = read(sidecar_path)
    records = dict(plan=bind(Path(native_run) / 'PLAN.json'), request=bind(folder / 'REQUEST.json'), history=bind(folder / 'HISTORY.json'))
    require(sidecar.get('schema') == INPUT_SCHEMA and sidecar.get('native_result') == bind(folder / 'RESULT.json')
            and sidecar.get('input') == plan['input'] and sidecar.get('full_asset_input') == row['full_asset_input']
            and sidecar.get('native_records') == records and sidecar.get('production_approved') is False,
            'actual_full_asset_result_receipt_changed')
    return dict(id=sid, kind='new', native_id=pid, result_binding=bind(folder / 'RESULT.json'), originals=originals,
                first_input=prepared['first_input'], actual_seed=graph['129']['inputs']['noise_seed'],
                expected_quotes=EXPECTED_QUOTES[sid], source_entry=prepared['context']['entry'],
                full_asset_receipt=bind(sidecar_path),
                input_status=dict(contract=INPUT_SCHEMA, actual_positive_reference_count=6, dynamic_tail_guide_frame=0,
                     pixel_routes=prepared['routes'], fixed_manifest=prepared['fixed']['manifest'],
                     required_actor_assets=prepared['context']['required_actor_assets'],
                     guide_visible_actor_ids=prepared['context']['guide_visible_actor_ids'],
                     guide_review=prepared['binding']['guide_review'], identity_quality_verified_by_CPU=False),
                binding=dict(**prepared['binding'], request=bind(folder / 'REQUEST.json'), result=bind(folder / 'RESULT.json'),
                             history=bind(folder / 'HISTORY.json'), full_asset_receipt=bind(sidecar_path)))


def series_inputs(run, project=PROJECT):
    project, run = Path(project).resolve(), Path(run).resolve()
    require(run.parent == project / 'data/video_generation', 'project_full_asset_series_required')
    plan = read(run / 'PLAN.json')
    require(plan.get('schema') == SERIES_SCHEMA and plan.get('publication') is False and plan.get('production_approved') is False
            and plan.get('new_video_submissions') == 2 and plan.get('new_image_submissions') == 0
            and plan.get('preserved_prefix_frames') == 724 and plan.get('prefix_source_media_unchanged') is True
            and plan.get('output_prefix_pixel_identity_claimed') is False
            and tuple(plan.get(k) for k in ('width', 'height', 'frames_per_segment', 'fps', 'steps', 'expected_frames'))
            == (736, 1312, 362, 24, 12, 1448), 'two_import_two_full_asset_series_profile_required')
    checked(plan['config'], project)
    checked(plan['authority'], project)
    fixed = fixed_assets(plan['asset_manifest'], project)
    checked(plan['asset_observation'], project)
    require(plan.get('asset_version') == FIXED_VERSION
            and [r.get('shot_id') for r in plan.get('prefix', [])] == list(IDS[:2])
            and [r.get('shot_id') for r in plan.get('sources', [])] == list(NEW_IDS),
            'fixed_version_and_four_segment_order_required')
    values = []
    for descriptor in plan['prefix']:
        sid = descriptor['shot_id']
        path = checked(descriptor['imported'], project)
        require(path == run / 'imported' / sid / 'IMPORT.json', 'prefix_descriptor_path_changed')
        imported = read(path)
        result_path = checked(imported['native_result'], project)
        value = previous_qa.prior_qa.validate_native(result_path.parents[2], sid, project)
        previous_qa.exact_endpoint_selection(read(result_path.parent / 'workflow_api.json'))
        require(imported.get('schema') == SERIES_SCHEMA and imported.get('shot_id') == sid
                and imported.get('kind') == 'preserved_native_prefix'
                and imported.get('native_result') == value['result_binding']
                and imported.get('native_files') == read(result_path)['files']
                and imported.get('prompt_id') == value['native_id'] == previous_qa.RETAINED[sid][0]
                and imported.get('file') == value['originals']['video']['local']
                and imported['file']['sha256'] == previous_qa.RETAINED[sid][1]
                and imported.get('new_model_calls') == 0 and imported.get('source_media_unchanged') is True
                and imported.get('native_records') == {k: value['binding'][k] for k in ('plan', 'request', 'history', 'result')},
                'actual_preserved_prefix_ID_pixels_or_records_changed')
        value.update(kind='imported', descriptor=bind(path), full_asset_receipt=None)
        values.append(value)
    for descriptor in plan['sources']:
        sid = descriptor['shot_id']
        path = checked(descriptor['source_case'], project)
        require(path == run / 'segments' / sid / 'SOURCE_CASE.json'
                and Path(descriptor['native_run']).resolve() == run / 'visual_h3_v3' / (run.name + '_' + sid),
                'new_full_asset_source_or_namespace_changed')
        entries = previous_qa.prior_qa.core._entries(bind(path))
        require(len(entries) == 1 and entries[0]['shot_id'] == sid
                and quotes(previous_qa.prior_qa.core.compile_prompt(entries[0])['compiled_prompt']) == EXPECTED_QUOTES[sid],
                'five_source_quotes_must_be_preserved')
    return dict(run=run, plan=plan, plan_binding=bind(run / 'PLAN.json'), values=values, fixed=fixed)


def validate_prepared(run=DEFAULT_RUN, project=PROJECT):
    value = series_inputs(run, project)
    segments = []
    for descriptor in value['plan']['sources']:
        sid, nr = descriptor['shot_id'], Path(descriptor['native_run'])
        if not (nr / 'PLAN.json').exists():
            segments.append(dict(id=sid, status='not_prepared_no_future_tail_invented', model_calls_by_QA=0))
            continue
        current = prepared_graph(nr, sid, project)
        protocol = cpu_source_protocol(current['fixed']['references'], current['first_input'], project)
        segments.append(dict(id=sid, status='actual_six_reference_pixels_and_guide_graph_verified',
                             binding=current['binding'], pixel_routes=current['routes'], source_protocol=protocol,
                             CPU_identity_quality_verified=False, model_calls_by_QA=0))
    return dict(schema='full_asset_prepared_CPU_QA/v1', plan=value['plan_binding'], fixed_assets=value['fixed'],
                preserved_native_ids=[r['native_id'] for r in value['values']], new_segments=segments,
                HTTP_calls_by_QA=0, GPU_inference_by_QA=0, production_approved=False)


def validate(run=DEFAULT_RUN, project=PROJECT):
    value = series_inputs(run, project)
    run, values = value['run'], value['values']
    for descriptor in value['plan']['sources']:
        sid = descriptor['shot_id']
        row = validate_new_native(descriptor['native_run'], sid, project)
        require(row['binding']['source'] == descriptor['source_case'], 'new_full_asset_source_binding_changed')
        path = run / 'segments' / sid / 'FINAL_RESULT.json'
        final = read(path)
        require(final.get('native_result') == row['result_binding'] and final.get('file') == row['originals']['video']['local']
                and final.get('prompt_id') == row['native_id'] and final.get('postprocessing') == []
                and final.get('full_asset_receipt') == row['full_asset_receipt'] and final.get('production_approved') is False,
                'new_segment_final_must_bind_actual_reference_native_output')
        row['descriptor'] = bind(path)
        values.append(row)
    require([r['id'] for r in values] == list(IDS) and len({r['native_id'] for r in values}) == 4
            and len({r['originals']['video']['local']['sha256'] for r in values}) == 4,
            'four_distinct_source_ordered_native_outputs_required')
    require(values[2]['input_status']['fixed_manifest'] == values[3]['input_status']['fixed_manifest'] == value['fixed']['manifest'],
            'new_clips_must_use_the_same_fixed_five_pixel_version')
    rows = [dict(shot_id=r['id'], native_result=r['result_binding'], file=r['originals']['video']['local'],
                 prompt_id=r['native_id'], kind=r['kind'], descriptor=r['descriptor']) for r in values]
    inputs = dict(plan=value['plan_binding'], segments=rows)
    final = read(run / 'FINAL_RESULT.json')
    require(final.get('schema') == SERIES_SCHEMA and final.get('segments') == rows
            and final.get('native_ids') == [r['native_id'] for r in values]
            and final.get('assembly_inputs_sha256') == digest(inputs) and final.get('prefix_source_media_unchanged') is True
            and final.get('output_prefix_pixel_identity_claimed') is False and final.get('publication') is False
            and final.get('production_approved') is False, 'final_full_asset_sources_or_order_changed')
    request = read(run / 'ASSEMBLY_REQUEST.json')
    require(request.get('inputs') == inputs and request.get('prefix_source_media_unchanged') is True
            and request.get('output_prefix_pixel_identity_claimed') is False and request.get('temporal_leading_trim') is False,
            'full_asset_assembly_prefix_or_clock_policy_changed')
    movie = checked(final['file'], project)
    require(movie == run / 'H3_FULL_ASSET_CONTINUATION_MINUTE_736x1312.mp4', 'new_full_asset_movie_path_changed')
    expected_command, expected_filter = previous_qa.assembly_clock.assembly_command(
        [r['file']['path'] for r in rows], run / 'ASSEMBLY_FILTER.txt', movie, frames=362)
    require(previous_qa.normalize_assembly_command(request['command'], project)
            == previous_qa.normalize_assembly_command(expected_command, project)
            and (run / 'ASSEMBLY_FILTER.txt').read_text(encoding='utf-8') == expected_filter,
            'actual_full_asset_assembly_command_or_source_order_changed')
    value.update(values=values, final=final, final_binding=bind(run / 'FINAL_RESULT.json'), movie=movie)
    return value


def qa(run=DEFAULT_RUN, *, asr=False, project=PROJECT):
    value = validate(run, project)
    run = value['run']
    folder = run / 'qc_full_asset' / value['final']['file']['sha256'] / ('with_asr' if asr else 'without_asr')
    folder.mkdir(parents=True, exist_ok=True)
    binding = dict(plan=value['plan_binding'], final=value['final_binding'], video=value['final']['file'],
                   fixed_manifest=value['fixed']['manifest'], originals=[r['binding'] for r in value['values']],
                   descriptors=[r['descriptor'] for r in value['values']], asr_requested=asr, prefix_retranscribed=False)
    freeze(folder / 'BINDING.json', binding)
    manifest = folder / 'FINAL_QA.json'
    if manifest.exists():
        prior = read(manifest)
        require(prior['binding'] == binding, 'existing_full_asset_QA_input_changed')
        for artifact in prior['artifacts']:
            checked(artifact, project)
        return dict(status='already_complete', manifest=bind(manifest), file=value['final']['file'])
    attempt = folder / 'attempts' / uuid.uuid4().hex
    attempt.mkdir(parents=True)
    code = attempt / 'qa_source.py'
    code.write_bytes(Path(__file__).read_bytes())
    freeze(attempt / 'START.json', dict(binding=binding, source_code=bind(code), at_epoch=time.time()))
    try:
        segments, artifacts = [], []
        for row in value['values']:
            sf = folder / row['id'] / row['native_id']
            segment, files = previous_qa.segment_evidence(row, sf, asr=asr, project=project)
            if row['kind'] == 'imported':
                segment['asr'] = previous_qa.retained_speech(run, row, project)
                artifacts.append(segment['asr']['prior_cpu_qa'])
            else:
                protocol = cpu_source_protocol(value['fixed']['references'], row['first_input'], project)
                segment['installed_source_protocol'] = freeze(sf / 'CPU_SOURCE_PROTOCOL.json', protocol)
                artifacts.append(segment['installed_source_protocol'])
            segments.append(segment)
            artifacts.extend(files)
        geometry, metadata = inspect_clock(value['movie'], 1448, final=True)
        artifacts.append(freeze(folder / 'FINAL_PROBE.json', metadata))
        samples = previous_qa.sample_plan()
        wanted = set(samples['timeline']) | set(samples['opening']) | set(samples['repair_boundary'])
        for join in samples['joins']:
            wanted.update(join['indices'])
        frames = extract_batch(value['movie'], wanted, folder / 'final_frames')
        artifacts.extend(dict(path=r['path'], sha256=r['sha256']) for r in frames.values())
        timeline = []
        for offset in range(0, len(samples['timeline']), 21):
            selected = samples['timeline'][offset:offset + 21]
            contact = make_board([frames[i] for i in selected], folder / f'TIMELINE_{offset//21+1:02d}.jpg', columns=5)
            timeline.append(dict(indices=selected, contact=contact))
            artifacts.append(contact)
        regions = {}
        for name in ('opening', 'repair_boundary'):
            contact = make_board([frames[i] for i in samples[name]], folder / (name.upper() + '.jpg'), columns=5)
            regions[name] = dict(indices=samples[name], contact=contact)
            artifacts.append(contact)
        for index, join in enumerate(samples['joins']):
            join['contact'] = make_board([frames[i] for i in join['indices']], folder / f'JOIN_{index+1:02d}.jpg', columns=5)
            artifacts.append(join['contact'])
        validate(run, project)
        report = dict(schema='full_asset_continuation_CPU_QA/v1', binding=binding, source_code=bind(code),
                      file=value['final']['file'], native_ids=value['final']['native_ids'], final_clock=geometry,
                      fixed_reference_manifest=value['fixed']['manifest'], positive_reference_slots_per_new_clip=6,
                      dynamic_native_tail_reference_and_guide_frame=0, preserved_prefix_frames=724,
                      output_prefix_pixel_identity_claimed=False, segments=segments, timeline=timeline,
                      regions=regions, joins=samples['joins'], limits=LIMITS,
                      artifacts=list({r['path']: r for r in artifacts}.values()),
                      CPU_identity_quality_verified=False, root_actual_visual_review=None, production_approved=False)
        freeze(manifest, report)
        freeze(attempt / 'COMPLETE.json', dict(manifest=bind(manifest), at_epoch=time.time()))
        return dict(status='CPU_QA_complete', manifest=bind(manifest), file=value['final']['file'],
                    timeline=[r['contact'] for r in timeline], joins=[r['contact'] for r in samples['joins']], regions=regions)
    except Exception as error:
        freeze(attempt / 'ERROR.json', dict(type=type(error).__name__, message=str(error),
                                          traceback=traceback.format_exc(), no_media_retry=True))
        raise


def preview_segment(run, sid, project=PROJECT):
    require(sid in NEW_IDS, 'preview_only_saved_new_full_asset_clips')
    run = Path(run).resolve()
    value = validate_new_native(run / 'visual_h3_v3' / (run.name + '_' + sid), sid, project)
    folder = run / 'qc_segment_previews' / sid / value['native_id']
    report, artifacts = previous_qa.segment_evidence(value, folder, preview=True, project=project)
    indices = list(range(0, 49, 3))
    frames = extract_batch(value['originals']['video']['local']['path'], indices, folder / 'frames')
    opening = make_board([frames[i] for i in indices], folder / 'OPENING_DENSE.jpg', columns=5)
    artifacts.extend([opening, *[dict(path=r['path'], sha256=r['sha256']) for r in frames.values()]])
    path = folder / 'PREVIEW.json'
    freeze(path, dict(schema='full_asset_saved_native_CPU_preview/v1', report=report,
                      native_binding=value['binding'], opening_dense=dict(indices=indices, contact=opening),
                      native_last=value['originals']['last']['local'], pixel_routes=value['input_status']['pixel_routes'],
                      artifacts=artifacts, ASR_executed=False, CPU_identity_quality_verified=False, production_approved=False))
    return dict(status='CPU_preview_complete', native_id=value['native_id'], manifest=bind(path),
                video=value['originals']['video']['local'], last=value['originals']['last']['local'],
                contacts=report['contacts'], opening_dense=opening)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, default=DEFAULT_RUN)
    parser.add_argument('--prepared', action='store_true')
    parser.add_argument('--preview', choices=NEW_IDS)
    parser.add_argument('--asr', action='store_true')
    parser.add_argument('--project-root', type=Path, default=PROJECT)
    args = parser.parse_args(argv)
    import json
    try:
        value = (validate_prepared(args.run, args.project_root) if args.prepared else
                 preview_segment(args.run, args.preview, args.project_root) if args.preview else
                 qa(args.run, asr=args.asr, project=args.project_root))
    except Exception as error:
        print(json.dumps(dict(status='CPU_QA_failed', error=type(error).__name__, message=str(error), no_media_retry=True), ensure_ascii=False))
        return 2
    print(json.dumps(value, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
