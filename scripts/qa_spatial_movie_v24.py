"""Independent, local-file-only CPU checks for existing spatial H3 v24 movies.

This module never imports an executor, calls HTTP, dispatches media, or grants
semantic approval. ASR is optional and uses the project's offline CPU program.
"""
import argparse
from copy import deepcopy
from difflib import SequenceMatcher
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from PIL import Image, ImageDraw, ImageStat, ImageChops

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Only CPU subprocess/file helpers are reused. The v20 validator is not used.
from scripts.qa_h3_reference_full_minute_cpu import command, probe, transcribe

PROJECT = Path(__file__).resolve().parents[1]
EXPERIMENT = 'data/video_generation/spatial_minute_experiments_20261107_v1'
SCHEMA = 'spatial_movie_cpu_qa/v24'
DELIVERY = 'spatial_h3_delivery/v24'
IDS = ('S01', 'S02', 'S03', 'S04')
ROLES = ('video', 'audio', 'first', 'last')
COUNTS = dict(S01=3, S02=2, S03=2, S04=3)
REFERENCE_IDS = ('character:su_mo:front', 'character:ye_nan:front',
                 'character:ye_xijue:front', 'place:su_mo_room:front', 'place:su_mo_room:side')
NATIVE_SECTIONS = ('subject_definitions', 'summary', 'retention_analysis',
                   'detailed_description', 'overall_soundscape', 'non_diegetic_music')
ROOM_ONLY_VARIANT = 'C_room_only_20261108_v1'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def binding(path):
    return dict(path=str(Path(path).resolve()), sha256=sha(path))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # QA is CPU-derived; authoritative files are never passed to this function.
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def freeze(path, value):
    if Path(path).exists():
        if fingerprint(read(path)) != fingerprint(value):
            raise ValueError('CPU QA binding changed; preserve the prior evidence')
    else:
        write(path, value)


def inside(root, path):
    root, path = Path(root).resolve(), Path(path).resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError('file outside required scope')
    return path


def check(value, project):
    if not isinstance(value, dict) or set(value) != {'path', 'sha256'}:
        raise ValueError('explicit physical file binding required')
    path = inside(project, value['path'])
    if not path.is_file() or sha(path) != value['sha256']:
        raise ValueError('bound source file changed')
    return path


def variant(run, project):
    root = Path(project).resolve() / EXPERIMENT / 'variants'
    run = inside(root, run)
    if run.parent != root or not re.fullmatch('[A-Za-z0-9_-]{1,100}', run.name):
        raise ValueError('direct v24 variant namespace required')
    return run


def quoted(text):
    return re.findall('[“「]([^”」]+)[”」]', text)


def normalized(text):
    return ''.join(c for c in text if c.isalnum())


def native_text_contract(text):
    """Independent CPU format guard; no compiler/executor import."""
    if re.findall(r'(?m)^([a-z_]+):\s*$', text) != list(NATIVE_SECTIONS):
        raise ValueError('native prompt must retain exactly six official sections')
    blocks = re.findall(r'<d>\[Mandarin Chinese\] (.*?)</d>', text, re.S)
    if (not blocks or text.count('<d>') != len(blocks) or text.count('</d>') != len(blocks)
            or any(not re.fullmatch('“[^”]*”|「[^」]*」', b) for b in blocks)):
        raise ValueError('one source quote per complete Mandarin d block required')
    outside = re.sub(r'<d>.*?</d>', '', text, flags=re.S)
    if re.search('[\u3400-\u9fff“”「」]', outside):
        raise ValueError('legacy Chinese appendix/non-dialogue text in native prompt')
    if set(map(int, re.findall(r'<Picture (\d+)>', text))) != {1, 2, 3, 4, 5}:
        raise ValueError('five native reference picture tags required')
    if set(map(int, re.findall(r'<Subject (\d+)>', text))) != {1, 2, 3, 4}:
        raise ValueError('native subject declarations changed')
    return blocks


def prompt_preflight(run, plan, sid, graph, project):
    if plan['settings'].get('prompt_format') != 'official_ref2va_v29':
        return None
    source = next(s for s in plan['settings']['segments'] if s['id'] == sid)
    text = graph['condition']['inputs']['prompt']
    blocks = native_text_contract(text)
    path = inside(Path(project) / EXPERIMENT, run.parent.parent / 'B_NATIVE_COMPILED_PREFLIGHT.json')
    preflight = read(path)
    rows = preflight.get('rows', [])
    if preflight.get('native_spec') != plan['spec'] or [r.get('id') for r in rows] != list(IDS):
        raise ValueError('native preflight does not bind the current four-segment SPEC')
    check(preflight['native_spec'], project)
    row = next(r for r in rows if r['id'] == sid)
    digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
    if (row.get('actual_compiled_text_exact_source') is not True or row.get('utf8_sha256') != digest
            or row.get('quote_count') != len(blocks) or row.get('end_guide') is not bool(source.get('end_guide'))
            or text != check(source['prompt'], project).read_text(encoding='utf-8')):
        raise ValueError('actual native REQUEST prompt differs from preflight/source')
    return dict(preflight=binding(path), segment=sid, actual_request_prompt_utf8_sha256=digest,
                preflight_prompt_utf8_sha256=row['utf8_sha256'], exact_source_text=True,
                legacy_chinese_appendix_present=False, quote_count=len(blocks))


def image_size(value, project):
    path = check(value, project)
    with Image.open(path) as image:
        size = image.size
        if getattr(image, 'n_frames', 1) != 1:
            raise ValueError('single native/reference image required')
        image.verify()
    return size


def original_guide(value, project):
    image_size(value['image'], project)
    review = read(check(value['root_review'], project))
    if (review.get('reviewed_by') != 'root_agent' or review.get('accepted_for_guide') is not True
            or review.get('image') != value['image']):
        raise ValueError('original guide review binding changed')
    if value.get('native_result'):
        previous = read(check(value['native_result'], project))
        if (previous.get('technical_status') != 'technical_saved' or not previous.get('prompt_id')
                or value.get('role') not in ('first', 'last')
                or {k: previous['files'][value['role']][k] for k in ('path', 'sha256')} != value['image']):
            raise ValueError('guide not the bound original native endpoint')
    elif review.get('producer_receipt') != value.get('producer_receipt'):
        raise ValueError('guide producer receipt not reviewed')
    else:
        check(value['producer_receipt'], project)


def expected_graph(plan, segment, scope):
    """Independent pure reconstruction of the submitted v24 graph contract."""
    settings = plan['settings']
    graph = deepcopy(plan['base'])
    for key in list(graph):
        if graph[key].get('class_type') == 'LoadImage' or key.startswith('guide_'):
            graph.pop(key)
    inputs = {k: deepcopy(plan['base']['condition']['inputs'][k]) for k in ('clip', 'vae')}
    lines = ['参考身份与环境：']
    for i, ref in enumerate(settings['references']):
        key = 'ref_' + str(i)
        graph[key] = dict(class_type='LoadImage', inputs=dict(image=scope + '/references/' + str(i) + '.png'))
        inputs['ref_images.ref_image_' + str(i)] = [key, 0]
        lines.append('<Picture ' + str(i + 1) + '>：' + ref['description'])
    text = Path(segment['prompt']['path']).read_text(encoding='utf-8')
    if settings.get('prompt_format') == 'official_ref2va_v29':
        native_text_contract(text)
        compiled = text
    else:
        compiled = text + '\n\n' + '\n'.join(lines)
    inputs.update(prompt=compiled,
                  width=settings['width'], height=settings['height'], length=settings['frames'], ref_image_size='match')
    graph['condition'] = dict(class_type='MiniMaxH3ReferenceToVideo', inputs=inputs)
    graph['127']['inputs']['unet_name'] = 'minimax_h3_ref2va_pruned_int8_convrot.safetensors'
    index = [s['id'] for s in settings['segments']].index(segment['id'])
    graph['129']['inputs']['noise_seed'] = settings.get('seed', 12345) + index
    graph['124']['inputs'].update(steps=12, denoise=1)
    graph['guide_start_image'] = dict(class_type='LoadImage', inputs=dict(image=scope + '/guides/start.png'))
    graph['guide_start'] = dict(class_type='MiniMaxH3AddGuide', inputs=dict(
        positive=['condition', 0], latent=['condition', 1], vae=inputs['vae'], image=['guide_start_image', 0], frame_idx=0))
    positive = ['guide_start', 0]
    if segment.get('end_guide'):
        graph['guide_end_image'] = dict(class_type='LoadImage', inputs=dict(image=scope + '/guides/end.png'))
        graph['guide_end'] = dict(class_type='MiniMaxH3AddGuide', inputs=dict(
            positive=positive, latent=['condition', 1], vae=inputs['vae'], image=['guide_end_image', 0], frame_idx=settings['frames'] - 1))
        positive = ['guide_end', 0]
    graph['126']['inputs']['conditioning'] = positive
    graph['pick_first']['inputs']['batch_index'] = 0
    graph['pick_last']['inputs']['batch_index'] = settings['frames'] - 1
    graph['130']['inputs']['fps'] = 24
    for role in ROLES:
        graph['save_' + role]['inputs']['filename_prefix'] = scope + '/' + role
    return graph


def native_equivalence(expected, observed):
    """Comfy's two documented FLOAT normalizations only; bool is never numeric."""
    actual = deepcopy(observed)
    changes = []
    for node, key, number in (('124', 'denoise', 1), ('130', 'fps', 24)):
        wanted = expected.get(node, {}).get('inputs', {}).get(key)
        got = actual.get(node, {}).get('inputs', {}).get(key)
        if type(wanted) is int and wanted == number and type(got) is float and got == number:
            actual[node]['inputs'][key] = number
            changes.append(node + '.inputs.' + key)
    if fingerprint(actual) != fingerprint(expected):
        raise ValueError('executed HISTORY graph differs from the claimed graph')
    return changes


def _without_staging_namespace(graph, scope):
    result = deepcopy(graph)
    for node in result.values():
        keys = ('image',) if node.get('class_type') == 'LoadImage' else ()
        if 'filename_prefix' in node.get('inputs', {}):
            keys += ('filename_prefix',)
        for key in keys:
            value = node['inputs'][key]
            if not isinstance(value, str) or not value.startswith(scope + '/'):
                raise ValueError('single-factor graph has unexpected staging/output namespace')
            node['inputs'][key] = '<VARIANT_NAMESPACE>/' + value[len(scope)+1:]
    return result


def validate_room_only_spec(spec, run, *, project=PROJECT):
    """Independent CPU v31 authority and exact A→C six-field comparison.

    Reads preserved A native requests, never imports or calls an executor. This
    can run before the C PLAN or any C native submission exists.
    """
    project = Path(project).resolve()
    root = project / EXPERIMENT
    run = variant(run, project)
    if run != root / 'variants' / ROOM_ONLY_VARIANT or spec.get('variant') != ROOM_ONLY_VARIANT:
        raise ValueError('room-only fixed variant required')
    auth_path = root / 'C_ROOM_ONLY_USER_AUTHORIZATION.json'
    if spec.get('authorization') != binding(auth_path):
        raise ValueError('room-only fixed physical authorization required')
    auth = read(check(spec['authorization'], project))
    if (auth.get('schema') != 'spatial_room_only_authorization/v31' or auth.get('user_statement') != '好'
            or not isinstance(auth.get('approved_proposal'), str) or not auth['approved_proposal'].strip()
            or not isinstance(auth.get('interpretation'), str) or not auth['interpretation'].strip()
            or auth.get('engineering_scope_not_user_quoted_numeric_limit') is not True
            or type(auth.get('max_full_video_submissions')) is not int or auth['max_full_video_submissions'] != 4
            or type(auth.get('max_probe_video_submissions')) is not int or auth['max_probe_video_submissions'] != 0
            or type(auth.get('new_cloud_media_calls')) is not int or auth['new_cloud_media_calls'] != 0
            or auth.get('publication') is not False or auth.get('old_authorization_and_usage_preserved') is not True
            or any(auth.get(key) is not False for key in ('service_restarts', 'downloads', 'unknown_native_replay'))):
        raise ValueError('room-only four full, zero probe, local-only authorization required')
    for key, name in (('baseline_a_spec', 'A_SPEC.json'), ('spatial_room_donor_spec', 'B_NATIVE_SPEC.json')):
        if auth.get(key) != binding(root / name):
            raise ValueError('room-only fixed A and B source bindings required')
    baseline = read(check(auth['baseline_a_spec'], project))
    donor = read(check(auth['spatial_room_donor_spec'], project))
    if (baseline.get('schema') != 'spatial_h3_spec/v24' or baseline.get('variant') != 'A' or baseline.get('profile') != 'minute'
            or donor.get('schema') != 'spatial_h3_spec/v24' or donor.get('variant') != 'B' or donor.get('profile') != 'minute'
            or len(baseline.get('references', [])) != 5 or len(donor.get('references', [])) != 5):
        raise ValueError('room-only known complete A baseline and B room donor required')
    expected = deepcopy(baseline)
    expected['variant'] = ROOM_ONLY_VARIANT
    expected['authorization'] = spec['authorization']
    for i, view in ((3, 'front'), (4, 'side')):
        ref = donor['references'][i]
        if (ref.get('kind'), ref.get('entity_id'), ref.get('view')) != ('place', 'su_mo_room', view):
            raise ValueError('room-only B donor room view/entity changed')
        image_size(ref['image'], project)
        check(ref['provenance'], project)
        review = read(check(ref['root_review'], project))
        if (review.get('reviewed_by') != 'root_agent' or review.get('accepted_for_reference') is not True
                or review.get('entity_id') != 'su_mo_room' or review.get('image') != ref['image']
                or review.get('provenance') != ref['provenance']):
            raise ValueError('room-only donor image/provenance/review mismatch')
        for key in ('image', 'provenance', 'root_review'):
            expected['references'][i][key] = deepcopy(ref[key])
    # Fingerprints distinguish JSON types (e.g. integer seed from float/bool).
    if fingerprint(spec) != fingerprint(expected):
        raise ValueError('room-only SPEC changed outside exactly six room reference fields')
    candidate = root / 'C_ROOM_ONLY_SPEC.json'
    if fingerprint(read(candidate)) != fingerprint(spec):
        raise ValueError('room-only candidate physical SPEC differs')
    preflight_path = root / 'room_only_v31/SINGLE_FACTOR_PREFLIGHT.json'
    preflight = read(preflight_path)
    if (preflight.get('schema') != 'spatial_room_only_preflight/v31'
            or preflight.get('baseline_spec') != auth['baseline_a_spec']
            or preflight.get('test_spec') != binding(candidate)
            or [r.get('id') for r in preflight.get('rows', [])] != list(IDS)
            or preflight.get('changed_reference_slots_zero_based') != [3, 4]):
        raise ValueError('room-only frozen single-factor preflight binding changed')
    check(preflight['baseline_spec'], project)
    check(preflight['test_spec'], project)
    base = read(check(spec['config']['base_workflow'], project))
    rows = []
    for i, sid in enumerate(IDS):
        actual_a = validate_segment(root / 'variants/A', sid, project=project)
        if fingerprint(actual_a['plan']['settings']) != fingerprint(baseline):
            raise ValueError('room-only preserved A native plan differs from bound A SPEC')
        a_request = actual_a['folder'] / 'REQUEST.json'
        a_graph = read(a_request)['prompt']
        segment = next(s for s in spec['segments'] if s['id'] == sid)
        scope = 'visual_spatial_h3_v24/' + ROOM_ONLY_VARIANT + '/' + sid
        c_graph = expected_graph(dict(base=base, settings=spec), segment, scope)
        a_text = a_graph['condition']['inputs']['prompt']
        c_text = c_graph['condition']['inputs']['prompt']
        if a_text.encode('utf-8') != c_text.encode('utf-8'):
            raise ValueError('room-only compiled text differs from actual A native REQUEST')
        if fingerprint(_without_staging_namespace(a_graph, 'visual_spatial_h3_v24/A/' + sid)) != fingerprint(_without_staging_namespace(c_graph, scope)):
            raise ValueError('room-only graph differs beyond staging/output namespaces')
        digest = hashlib.sha256(c_text.encode('utf-8')).hexdigest()
        declared = preflight['rows'][i]
        if (declared.get('actual_a_prompt_utf8_sha256') != digest or declared.get('c_compiled_prompt_utf8_sha256') != digest
                or declared.get('exact_prompt_equal') is not True or declared.get('graph_equal_except_output_and_staging_namespace') is not True
                or fingerprint(declared.get('seed')) != fingerprint(spec.get('seed', 12345) + i)
                or declared.get('guide_end') is not bool(segment.get('end_guide'))):
            raise ValueError('room-only preflight statement differs from independently computed graph/text')
        rows.append(dict(id=sid, actual_a_request=binding(a_request),
                         actual_a_prompt_utf8_sha256=digest, c_compiled_prompt_utf8_sha256=digest,
                         graph_equal_except_output_and_staging_namespace=True))
    return dict(schema='independent_room_only_cpu_contract/v31', variant=ROOM_ONLY_VARIANT,
                authorization=spec['authorization'], baseline_spec=auth['baseline_a_spec'], donor_spec=auth['spatial_room_donor_spec'],
                candidate_spec=binding(candidate), preflight=binding(preflight_path),
                changed_fields=[f'references[{i}].{key}' for i in (3, 4) for key in ('image', 'provenance', 'root_review')],
                compiled_prompt_comparison=rows, production_approved=False,
                scope='Exactly two auxiliary room references changed under A initial guide and native-tail policy. No causal, actor-count or spatial semantic improvement is inferred.')


def validate_segment(run, sid, *, project=PROJECT):
    project = Path(project).resolve()
    run = variant(run, project)
    plan = read(run / 'PLAN.json')
    if (plan.get('schema') != DELIVERY or plan.get('variant') != run.name
            or plan.get('production_approved') is not False or plan.get('publication') is not False):
        raise ValueError('independent diagnostic v24 PLAN required')
    settings = read(check(plan['spec'], project))
    if fingerprint(settings) != fingerprint(plan['settings']) or settings.get('schema') != 'spatial_h3_spec/v24':
        raise ValueError('frozen SPEC does not match PLAN')
    approval = read(check(plan['approval'], project))
    if (approval.get('reviewed_by') != 'root_agent' or approval.get('approved_for_generation') is not True
            or approval.get('spec') != plan['spec'] or approval.get('diagnostic_only') is not True):
        raise ValueError('v24 generation approval binding changed')
    if plan.get('authorization') != settings['authorization']:
        raise ValueError('authorization binding differs')
    auth = read(check(plan['authorization'], project))
    room_only = None
    if run.name == ROOM_ONLY_VARIANT or auth.get('schema') == 'spatial_room_only_authorization/v31':
        room_only = validate_room_only_spec(settings, run, project=project)
    elif (auth.get('schema') != 'spatial_minute_experiment_authorization/v24' or not auth.get('user_statement')
            or auth.get('publication') is not False or auth.get('new_cloud_media_calls') != 0):
        raise ValueError('bounded local experiment authorization required')
    source_root = project / 'data/video_generation/h3_reference_full_minute_20261107_v1'
    if check(settings['parent_runner_plan'], project).parent != source_root:
        raise ValueError('original reference-minute parent required')
    check(plan['protected_pause'], project)
    cfg = plan['config']
    spec_cfg = deepcopy(settings['config'])
    base = read(check(spec_cfg.pop('base_workflow'), project))
    if fingerprint(spec_cfg) != fingerprint(cfg) or fingerprint(base) != fingerprint(plan['base']):
        raise ValueError('frozen service/base graph source changed')
    for key in ('input_root', 'output_root'):
        inside(project, cfg[key])
    geometry = (settings['width'], settings['height'], settings['frames'])
    ids = [s['id'] for s in settings['segments']]
    if settings.get('profile') != plan.get('profile') or settings.get('variant') != run.name:
        raise ValueError('profile binding differs')
    if plan['profile'] == 'minute':
        if ids != list(IDS) or geometry != (736, 1312, 362):
            raise ValueError('four full native segments required')
    elif plan['profile'] != 'probe' or ids != ['S01'] or geometry not in ((288, 512, 124), (384, 672, 124)):
        raise ValueError('bounded native canary geometry required')
    if sid not in ids:
        raise ValueError('segment not in this v24 PLAN')
    refs = settings['references']
    roles = [tuple(key.split(':')) for key in REFERENCE_IDS]
    ref_ids = [r.get('reference_id') for r in refs]
    if (len(refs) != 5 or [(r.get('kind'), r.get('entity_id'), r.get('view')) for r in refs] != roles
            or any(not isinstance(key, str) or not key.strip() or len(key) > 200 or re.search(r'[\r\n\x00]', key) for key in ref_ids)
            or len(set(ref_ids)) != 5):
        raise ValueError('ordered five cast/environment references required')
    for i, ref in enumerate(refs):
        kind, entity, view = roles[i]
        # The ID is an asset key/version, not a camera field.
        # Geometry/view declarations must never be inferred from that string.
        image_size(ref['image'], project)
        proof = read(check(ref['root_review'], project))
        check(ref['provenance'], project)
        if (proof.get('reviewed_by') != 'root_agent' or proof.get('accepted_for_reference') is not True
                or proof.get('image') != ref['image'] or proof.get('entity_id') != entity
                or proof.get('provenance') != ref['provenance']):
            raise ValueError('reference provenance/review binding changed')
    segment = next(s for s in settings['segments'] if s['id'] == sid)
    source = check(segment['prompt'], project)
    original = check(segment['original_prompt'], project)
    if original != source_root / 'sources' / (sid + '.prompt.txt'):
        raise ValueError('original Seedance dialogue source required')
    quotes = quoted(source.read_text(encoding='utf-8'))
    original_quotes = quoted(original.read_text(encoding='utf-8'))
    if len(original_quotes) != COUNTS[sid] or quotes != (original_quotes if plan['profile'] == 'minute' else original_quotes[:1]):
        raise ValueError('source dialogue coverage changed')
    folder = run / 'shots' / sid
    state, result = read(folder / 'STATE.json'), read(folder / 'RESULT.json')
    pid = result.get('prompt_id')
    if (state.get('status') != 'technical_saved' or result.get('technical_status') != 'technical_saved'
            or state.get('id') != sid or result.get('shot_id') != sid or state.get('prompt_id') != pid
            or not isinstance(pid, str) or not re.fullmatch('[A-Za-z0-9_-]{1,100}', pid)
            or state.get('plan_sha256') != fingerprint(plan) or result.get('schema') != DELIVERY
            or state.get('result_sha256') != sha(folder / 'RESULT.json')):
        raise ValueError('bound technical_saved original ID/RESULT required')
    graph, row = read(folder / 'workflow_api.json'), read(folder / 'GRAPH_BINDING.json')
    scope = 'visual_spatial_h3_v24/' + run.name + '/' + sid
    digest = fingerprint(graph)
    if (row.get('id') != sid or row.get('scope') != scope
            or any(v != digest for v in (row.get('graph_sha256'), state.get('graph_sha256'), result.get('graph_sha256'), read(folder / 'CLAIM.json').get('graph_sha256')))
            or fingerprint(read(folder / 'REQUEST.json')['prompt']) != digest
            or read(folder / 'RESPONSE.json').get('prompt_id') != pid):
        raise ValueError('original native CLAIM/response/graph binding changed')
    if fingerprint(expected_graph(plan, segment, scope)) != digest:
        raise ValueError('Ref2VA + frame-zero AddGuide + five references graph contract changed')
    preflight = prompt_preflight(run, plan, sid, graph, project)
    if (row.get('reference_sha256') != fingerprint(refs) or result.get('references_sha256') != fingerprint(refs)
            or row.get('source_prompt') != segment['prompt'] or result.get('source_prompt') != segment['prompt']
            or result.get('guide') != row.get('guide') or row.get('end_guide') != segment.get('end_guide')):
        raise ValueError('native reference/source/guide binding differs')
    index = ids.index(sid)
    if index == 0:
        original_guide(settings['initial_guide'], project)
        if row.get('guide') != settings['initial_guide']:
            raise ValueError('initial guide binding changed')
    else:
        previous_sid = ids[index - 1]
        previous = validate_segment(run, previous_sid, project=project)
        expected_guide = dict(image={k: previous['result']['files']['last'][k] for k in ('path', 'sha256')},
                              native_result=binding(previous['folder'] / 'RESULT.json'), role='last',
                              native_id=previous['result']['prompt_id'], previous_segment=previous_sid,
                              policy='actual_previous_native_tail_even_if_semantically_imperfect')
        if row.get('guide') != expected_guide:
            raise ValueError('later guide is not the immediately preceding actual native tail')
    if segment.get('end_guide'):
        original_guide(segment['end_guide'], project)
    staged = [(scope + '/references/' + str(i) + '.png', r['image']) for i, r in enumerate(refs)]
    staged.append((scope + '/guides/start.png', row['guide']['image']))
    if segment.get('end_guide'):
        staged.append((scope + '/guides/end.png', segment['end_guide']['image']))
    for name, value in staged:
        stage = inside(cfg['input_root'], Path(cfg['input_root']) / name)
        if sha(stage) != value['sha256']:
            raise ValueError('actual staged guide/reference image changed')
    history = read(folder / 'HISTORY.json').get(pid, {})
    prompt, terminal = history.get('prompt', []), history.get('status', {})
    if (len(prompt) < 3 or prompt[1] != pid or terminal.get('completed') is not True
            or terminal.get('status_str') != 'success'):
        raise ValueError('original successful native HISTORY required')
    normalizations = native_equivalence(graph, prompt[2])
    if set(result.get('files', {})) != set(ROLES):
        raise ValueError('all four native outputs required')
    for role, key, extension in (('video', 'images', '.mp4'), ('audio', 'audio', '.flac'), ('first', 'images', '.png'), ('last', 'images', '.png')):
        value = result['files'][role]
        path = check({k: value[k] for k in ('path', 'sha256')}, project)
        inside(folder / 'artifacts', path)
        records = history.get('outputs', {}).get('save_' + role, {}).get(key)
        if not isinstance(records, list) or len(records) != 1 or records[0].get('type') != 'output':
            raise ValueError('four original native HISTORY save nodes required')
        record = records[0]
        name = record.get('filename', '')
        if '/' in name or '\\' in name or not name.startswith(role + '_') or Path(name).suffix.lower() != extension:
            raise ValueError('native filename changed')
        native_source = inside(cfg['output_root'], Path(cfg['output_root']) / record.get('subfolder', '').replace('\\', '/') / name)
        if (native_source.parent != Path(cfg['output_root']).resolve() / scope
                or native_source != Path(value['source_path']).resolve() or sha(native_source) != value['sha256']):
            raise ValueError('native output/copied output provenance differs')
        if role in ('first', 'last') and image_size({k: value[k] for k in ('path', 'sha256')}, project) != geometry[:2]:
            raise ValueError('saved native endpoint size differs')
    return dict(run=run, folder=folder, plan=plan, result=result, row=row,
                source=source, quotes=quotes, normalizations=normalizations, prompt_preflight=preflight,
                room_only_contract=room_only)


def pixel_metrics(left, right):
    with Image.open(left) as a, Image.open(right) as b:
        a, b = a.convert('RGB'), b.convert('RGB')
        original_sizes = [list(a.size), list(b.size)]
        a = a.resize(b.size, Image.Resampling.LANCZOS)
        stats = ImageStat.Stat(ImageChops.difference(a, b))
        mae = sum(stats.mean) / 3 / 255
        rmse = (sum(x * x for x in stats.rms) / 3) ** .5 / 255
    return dict(rgb_mae_0_to_1=mae, rgb_rmse_0_to_1=rmse, original_sizes=original_sizes,
                resampling='left resized to right size with LANCZOS for numeric comparison only',
                semantic_pass=None, scope='Pixel differences only; no identity, position, action, OCR or continuity recognition.')


def card(image_path, title, width=288, height=512):
    with Image.open(image_path) as image:
        tile = Image.new('RGB', (width, height + 42), 'white')
        image = image.convert('RGB')
        image.thumbnail((width, height), Image.Resampling.LANCZOS)
        tile.paste(image, ((width - image.width) // 2, 42 + (height - image.height) // 2))
        ImageDraw.Draw(tile).text((5, 5), title, fill='black')
        return tile


def contact(cards, path, columns=2):
    width, height = cards[0].size
    board = Image.new('RGB', (width * columns, height * ((len(cards) + columns - 1) // columns)), 'white')
    for i, tile in enumerate(cards):
        board.paste(tile, ((i % columns) * width, (i // columns) * height))
    board.save(path, quality=93)
    return binding(path)


def extract(video, path, index):
    if not Path(path).exists():
        command(['ffmpeg', '-nostdin', '-v', 'error', '-hwaccel', 'none', '-i', str(video),
                 '-vf', 'select=eq(n\\,' + str(index) + ')', '-frames:v', '1', '-threads', '2', str(path)])
    return binding(path)


def spatial_plan(handoff, sid, folder, project):
    if handoff is None:
        return dict(status='not_supplied', scope='No planned spatial source assumed from neighboring folders.')
    path = inside(Path(project) / EXPERIMENT, handoff)
    data = read(path)
    plan = read(check(data['plan'], project))
    if data.get('schema') != 'spatial_reference_handoff/v24' or plan.get('schema') != 'explicit_spatial_scene/v24':
        raise ValueError('explicit v24 planned spatial handoff required')
    rows = [s for s in data['segments'] if s['id'] == sid]
    if len(rows) != 1:
        raise ValueError('one planned spatial segment required')
    row = rows[0]
    if 'source_prompt' in row:
        check(row['source_prompt'], project)
    diagrams = {}
    for suffix in ('start', 'end'):
        diagram = path.parent / 'diagrams' / (sid + '_' + suffix + '.png')
        if diagram.exists():
            image_size(binding(diagram), project)
            diagrams[suffix] = binding(diagram)
    value = dict(status='planned_only_not_actual_detection', handoff=binding(path), plan=data['plan'], segment=row, diagrams=diagrams,
                 scope='Staging design only; not measured novel fact, actual actor detection or proof the model followed it.')
    freeze(folder / 'PLANNED_SPATIAL_BINDING.json', value)
    return value


def signal_analysis(video, folder):
    log = folder / 'audio_levels.log'
    if not log.exists():
        command(['ffmpeg', '-nostdin', '-hide_banner', '-i', str(video), '-vn', '-af',
                 'silencedetect=noise=-38dB:d=0.5,volumedetect', '-f', 'null', '-'], log=log)
    raw = log.read_text(encoding='utf-8')
    def number(key):
        match = re.search(key + r':\s*(-?(?:[\d.]+|inf)) dB', raw)
        if not match:
            return None
        text = match.group(1)
        return text if 'inf' in text else float(text)
    return dict(mean_volume_db=number('mean_volume'), max_volume_db=number('max_volume'),
                silence_events=[line for line in raw.splitlines() if 'silence_' in line], log=binding(log))


def qa_segment(run, sid, *, asr=False, spatial_handoff=None, project=PROJECT):
    value = validate_segment(run, sid, project=project)
    run, native, plan, result = value['run'], value['folder'], value['plan'], value['result']
    if spatial_handoff is not None and binding(spatial_handoff) != plan['settings'].get('spatial_handoff'):
        raise ValueError('planned spatial handoff must be the actual frozen SPEC binding')
    pid = result['prompt_id']
    folder = inside(run, run / 'qc' / sid / pid)
    folder.mkdir(parents=True, exist_ok=True)
    bound_inputs = dict(route='v24 true Ref2VA + native frame-zero AddGuide + five reference inputs',
                        profile=plan['profile'], segment=sid, prompt_id=pid,
                        plan=binding(run / 'PLAN.json'), result=binding(native / 'RESULT.json'),
                        graph_binding=binding(native / 'GRAPH_BINDING.json'), history=binding(native / 'HISTORY.json'),
                        video=result['files']['video'], source_prompt=binding(value['source']),
                        graph_sha256=result['graph_sha256'], references_sha256=result['references_sha256'],
                        guide=result['guide'], spatial_handoff=binding(spatial_handoff) if spatial_handoff else None,
                        native_prompt_preflight=value['prompt_preflight'])
    if value['room_only_contract'] is not None:
        bound_inputs['room_only_contract'] = value['room_only_contract']
    freeze(folder / 'BINDING.json', bound_inputs)
    previous = read(folder / 'OBJECTIVE_QA.json') if (folder / 'OBJECTIVE_QA.json').exists() else None
    if previous:
        for produced in previous.get('derived_files', []):
            check(produced, project)
    video = result['files']['video']['path']
    metadata = probe(video)
    freeze(folder / 'PROBE.json', metadata)
    v = next(s for s in metadata['streams'] if s['codec_type'] == 'video')
    a = next(s for s in metadata['streams'] if s['codec_type'] == 'audio')
    width, height, frames = (plan['settings'][k] for k in ('width', 'height', 'frames'))
    if ((v['width'], v['height'], int(v['nb_frames']), int(v['nb_read_frames']), v['r_frame_rate'], v['avg_frame_rate'])
            != (width, height, frames, frames, '24/1', '24/1')
            or abs(Fraction(v['duration']) - Fraction(frames, 24)) > Fraction(1, 1000)):
        raise ValueError('actual native size/frame clock differs')
    audio_original = probe(result['files']['audio']['path'])
    if not any(s['codec_type'] == 'audio' for s in audio_original['streams']):
        raise ValueError('original native audio not decodable')
    indices = [int((frames - 1) * fraction) for fraction in (0, .1, .3, .5, .7, .9)]
    samples = []
    for i, index in enumerate(indices):
        item = extract(video, folder / ('frame_' + str(i).zfill(2) + '.png'), index)
        with Image.open(item['path']) as image:
            if image.size != (width, height):
                raise ValueError('sampled frame dimensions differ')
        samples.append(dict(**item, frame_index=index, seconds=index / 24))
    last = folder / 'native_last.png'
    if not last.exists():
        shutil.copyfile(result['files']['last']['path'], last)
    if sha(last) != result['files']['last']['sha256']:
        raise ValueError('native last copy changed')
    contact_path = folder / 'CONTACT.jpg'
    contact_value = contact([card(s['path'], f'ACTUAL {sid} frame {s["frame_index"]}') for s in samples]
                            + [card(last, sid + ' original native LAST')], contact_path)
    guide = result['guide']['image']['path']
    first = result['files']['first']['path']
    comparison = contact([card(guide, 'INPUT GUIDE (not generated frame)'), card(first, 'ACTUAL native FIRST'),
                          card(samples[0]['path'], 'ACTUAL decoded MP4 frame 0')], folder / 'GUIDE_VS_ACTUAL.jpg', columns=3)
    end_comparison = None
    if value['row'].get('end_guide'):
        end_input = value['row']['end_guide']
        # This exact input, root review, staged SHA and final-frame AddGuide
        # were already verified against SPEC and the original native graph.
        decoded_last = extract(video, folder / 'frame_last_decoded.png', frames - 1)
        end_board = contact([card(end_input['image']['path'], 'INPUT END GUIDE / SPEC target'),
                             card(last, 'ACTUAL original native LAST'),
                             card(decoded_last['path'], f'ACTUAL decoded MP4 frame {frames-1}')],
                            folder / 'END_GUIDE_VS_ACTUAL.jpg', columns=3)
        end_comparison = dict(input_guide=end_input, frame_index=frames-1,
                              original_native_last=result['files']['last'], decoded_last=decoded_last,
                              contact=end_board,
                              guide_to_native_last_metrics=pixel_metrics(end_input['image']['path'], last),
                              native_last_to_decoded_last_metrics=pixel_metrics(last, decoded_last['path']),
                              scope='Bound end-guide is an input target, not actual output. Pixel differences only; no semantic, identity, pose or object-transfer approval.')
    planned = spatial_plan(spatial_handoff, sid, folder, project)
    anchor_cards = [card(guide, 'INPUT GUIDE / declared source')]
    for ref in plan['settings']['references'][:3]:
        anchor_cards.append(card(ref['image']['path'], 'REFERENCE declared ' + ref['entity_id']))
    anchor_cards.extend([card(first, 'ACTUAL first / actors NOT identified'), card(last, 'ACTUAL last / actors NOT identified')])
    if spatial_handoff:
        for suffix, diagram in planned['diagrams'].items():
            anchor_cards.append(card(diagram['path'], 'PLANNED ' + suffix + ' / not detection'))
    anchor = contact(anchor_cards, folder / 'ANCHORBOARD.jpg', columns=3)
    wav = folder / 'embedded_audio_16k.wav'
    if not wav.exists():
        command(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(video), '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(wav)])
    signal = signal_analysis(video, folder)
    transcript = folder / 'ASR.json'
    if asr and not transcript.exists():
        transcribe(project, wav, transcript, folder)
    words = ''.join(r.get('text', '') for r in read(transcript).get('result', []) if isinstance(r, dict)) if transcript.exists() else None
    actual = normalized(words) if words is not None else None
    expected = normalized(''.join(value['quotes']))
    differences = []
    if actual is not None:
        for kind, i, j, m, n in SequenceMatcher(None, expected, actual, autojunk=False).get_opcodes():
            if kind != 'equal':
                differences.append(dict(kind=kind, expected=expected[i:j], recognized=actual[m:n]))
    derived = [dict(path=s['path'], sha256=s['sha256']) for s in samples]
    derived += [binding(last), contact_value, comparison, anchor, binding(wav), signal['log']]
    if end_comparison:
        derived += [end_comparison['decoded_last'], end_comparison['contact']]
    if transcript.exists():
        derived.append(binding(transcript))
    manifest = dict(schema=SCHEMA, binding=bound_inputs, native_graph_float_normalizations=value['normalizations'],
                    geometry=dict(width=width, height=height, native_frames=frames, decoded_frames=int(v['nb_read_frames']), fps=24, seconds=frames / 24),
                    audio_metadata={k: a.get(k) for k in ('codec_name', 'sample_rate', 'channels', 'start_time', 'duration')},
                    original_audio_metadata=audio_original, signal=signal, frames=samples, native_last=binding(last), contact=contact_value,
                    guide_vs_actual=comparison, guide_vs_native_first_metrics=pixel_metrics(guide, first),
                    native_first_vs_decoded_metrics=pixel_metrics(first, samples[0]['path']), anchorboard=anchor, planned_spatial=planned,
                    expected_quoted_speech=value['quotes'], asr_status='completed' if words is not None else 'not_requested',
                    asr_text=words, asr_normalized=actual, asr_differences=differences,
                    normalized_matches=expected == actual if actual is not None else None,
                    quoted_speech_exactly_detected=[dict(text=q, exactly_detected=normalized(q) in actual if actual is not None else None) for q in value['quotes']],
                    S03_child_inner_voice_exactly_detected=normalized('他一定在想怎么打我') in actual if sid == 'S03' and actual is not None else None,
                    derived_files=derived, scope='CPU decoded samples, numeric pixels and CPU ASR only. Unrecognized speech is not proof of omission. Names and reference crops are declarations, not actual actor recognition. Root visual/listening review required.',
                    production_approved=False, publication=False)
    if end_comparison:
        manifest['end_guide_vs_actual'] = end_comparison
    path = folder / 'OBJECTIVE_QA.json'
    validate_segment(run, sid, project=project)
    write(path, manifest)
    receipt = dict(status='cpu_qa_complete', segment=sid, prompt_id=pid, video_sha256=result['files']['video']['sha256'],
                   manifest=binding(path), contact=contact_value, guide_vs_actual=comparison, anchorboard=anchor, production_approved=False)
    if end_comparison:
        receipt['end_guide_vs_actual'] = end_comparison['contact']
    return receipt


def qa_final(run, *, project=PROJECT):
    run = variant(run, project)
    values = [validate_segment(run, sid, project=project) for sid in IDS]
    if any(v['plan']['profile'] != 'minute' for v in values):
        raise ValueError('probe cannot be a minute')
    final = read(run / 'FINAL_RESULT.json')
    video = check(final['file'], project)
    inside(run, video)
    native_ids = [v['result']['prompt_id'] for v in values]
    if len(set(native_ids)) != 4 or len({v['result']['files']['video']['sha256'] for v in values}) != 4:
        raise ValueError('four distinct native sources required')
    inputs = dict(plan=binding(run / 'PLAN.json'), results=[binding(v['folder'] / 'RESULT.json') for v in values])
    if final.get('schema') != DELIVERY or final.get('native_ids') != native_ids or final.get('assembly_inputs_sha256') != fingerprint(inputs):
        raise ValueError('final input/native-ID binding changed')
    data = probe(video)
    v = next(s for s in data['streams'] if s['codec_type'] == 'video')
    a = next(s for s in data['streams'] if s['codec_type'] == 'audio')
    target = Fraction(1448, 24)
    samples = Fraction(a['duration_ts']) * Fraction(a['time_base']) * int(a['sample_rate'])
    if ((v['width'], v['height'], int(v['nb_frames']), int(v['nb_read_frames']), v['r_frame_rate'], v['avg_frame_rate']) != (736, 1312, 1448, 1448, '24/1', '24/1')
            or Fraction(v['start_time']) != 0 or Fraction(a['start_time']) != 0
            or Fraction(v['duration_ts']) * Fraction(v['time_base']) != target or samples != 2896000
            or int(a['sample_rate']) != 48000 or int(a['channels']) != 2
            or abs(Fraction(data['format']['duration']) - target) > Fraction(1, 1000)):
        raise ValueError('final frame/sample/AV origin clock differs')
    folder = run / 'qc' / 'final'
    folder.mkdir(parents=True, exist_ok=True)
    freeze(folder / 'BINDING.json', dict(final=binding(run / 'FINAL_RESULT.json'), inputs=inputs, video=binding(video)))
    if (folder / 'FINAL_OBJECTIVE_QA.json').exists():
        for produced in read(folder / 'FINAL_OBJECTIVE_QA.json').get('derived_files', []):
            check(produced, project)
    joins, cards = [], []
    for i, boundary in enumerate((362, 724, 1086), 1):
        before = extract(video, folder / f'join_{i}_before.png', boundary - 1)
        after = extract(video, folder / f'join_{i}_after.png', boundary)
        cards.extend([card(before['path'], f'ACTUAL join {i} before #{boundary-1}'), card(after['path'], f'ACTUAL join {i} after #{boundary}')])
        joins.append(dict(join=i, frame_before=boundary - 1, frame_after=boundary, before=before, after=after,
                          pixel_difference=pixel_metrics(before['path'], after['path'])))
    joined = contact(cards, folder / 'JOINS_CONTACT.jpg')
    signal = signal_analysis(video, folder)
    out = dict(schema=SCHEMA, final_result=binding(run / 'FINAL_RESULT.json'), file=binding(video), native_ids=native_ids,
               native_frames=1448, decoded_frames=1448, width=736, height=1312, fps=24, seconds=float(target),
               video_start=0, audio_start=0, audio_rate=48000, stream_audio_samples=int(samples), target_clock_matches=True,
               joins=joins, join_contact=joined, signal=signal,
               derived_files=[p for j in joins for p in (j['before'], j['after'])] + [joined, signal['log']],
               scope='Clock and numeric join pixels only; pixel differences do not establish semantic continuity or actual identities.',
               production_approved=False, publication=False)
    path = folder / 'FINAL_OBJECTIVE_QA.json'
    # Recheck authoritative inputs after the CPU work without dispatching anything.
    if final != read(run / 'FINAL_RESULT.json') or binding(video) != final['file']:
        raise ValueError('final changed during CPU QA')
    for sid in IDS:
        validate_segment(run, sid, project=project)
    write(path, out)
    return dict(status='final_cpu_qa_complete', manifest=binding(path), join_contact=joined, clock=out, production_approved=False)


def quote_evidence(run, sid, *, project=PROJECT):
    """Actual timed frames for every recognized quote; no speaker recognition."""
    run = variant(run, project)
    if sid not in IDS:
        raise ValueError('known original segment required for quote evidence')
    state = read(run / 'shots' / sid / 'STATE.json')
    pid = state.get('prompt_id')
    if state.get('status') != 'technical_saved' or not isinstance(pid, str) or not re.fullmatch('[A-Za-z0-9_-]{1,100}', pid):
        raise ValueError('known technical-saved native ID required for quote evidence')
    folder = inside(run, run / 'qc' / sid / pid)
    report_path = folder / 'OBJECTIVE_QA.json'
    report = read(report_path)
    if report.get('schema') != SCHEMA or report.get('binding', {}).get('prompt_id') != pid or report['binding'].get('segment') != sid:
        raise ValueError('quote evidence CPU report/native ID differs')
    video = {key: report['binding']['video'][key] for key in ('path', 'sha256')}
    inside(run, check(video, project))
    asr_path = folder / 'ASR.json'
    chars, intervals = [], []
    for row in read(asr_path).get('result', []):
        tokens, stamps = row.get('text', '').split(), row.get('timestamp', [])
        if len(tokens) != len(stamps):
            raise ValueError('CPU ASR timestamp/token count differs; preserve evidence')
        for token, stamp in zip(tokens, stamps):
            for char in normalized(token):
                chars.append(char);intervals.append(stamp)
    text, rows, frames, cards = ''.join(chars), [], [], []
    for i, quote in enumerate(report['expected_quoted_speech']):
        wanted = normalized(quote);position = text.find(wanted)
        start = intervals[position][0] if position >= 0 else None
        end = intervals[position+len(wanted)-1][1] if position >= 0 else None
        rows.append(dict(quote_index=i, text=quote, exactly_detected=position >= 0, start_ms=start, end_ms=end))
        if position < 0:
            continue
        for fraction in (.25, .5, .75):
            index = max(0, min(report['geometry']['native_frames']-1, round((start+(end-start)*fraction)*24/1000)))
            item = extract(report['binding']['video']['path'], folder / f'quote_{i+1:02d}_frame_{index:03d}.png', index)
            frames.append(dict(**item, quote_index=i, frame_index=index, seconds=index/24))
            cards.append(card(item['path'], f'ACTUAL {index/24:.3f}s / quote {i+1}\nSpeaker and mouth state NOT identified'))
    board = contact(cards, folder / 'QUOTE_INTERVAL_ACTUAL_CONTACT.jpg', columns=3) if cards else None
    value = dict(schema='cpu_quote_interval_frames/v1', manifest=binding(report_path), asr=binding(asr_path),
                 source_prompt=report['binding']['source_prompt'], prompt_id=state['prompt_id'],
                 video_sha256=report['binding']['video']['sha256'], quotes=rows, frames=frames, contact=board,
                 scope='Approximate CPU ASR boundaries and actual decoded frames only. Includes the second utterance and inner-voice utterances when recognized; no actual identity, mouth state, hearing or semantic approval.',
                 production_approved=False)
    output = folder / 'ASR_QUOTE_INTERVALS.json'
    check(video, project)
    freeze(output, value)
    return dict(intervals=binding(output), contact=board)


def observe_room_only(run, observer_dir, first_native_id, helper_sha256, *, max_seconds=28800, project=PROJECT):
    """One bounded file observer; native execution and its state remain untouched."""
    project = Path(project).resolve();run = variant(run, project)
    if run.name != ROOM_ONLY_VARIANT or type(max_seconds) is not int or not 1 <= max_seconds <= 28800:
        raise ValueError('fixed C room-only observation up to eight hours required')
    if not isinstance(first_native_id, str) or not re.fullmatch('[A-Za-z0-9_-]{1,100}', first_native_id):
        raise ValueError('known original first native ID required')
    if sha(__file__) != helper_sha256:
        raise ValueError('observer helper source differs from frozen tested SHA')
    directory = inside(project / 'data/qa', observer_dir)
    directory.mkdir(parents=True, exist_ok=True)
    import psutil
    own = psutil.Process(os.getpid())
    identity = dict(pid=own.pid, create_time=own.create_time(), command=own.cmdline(), executable=own.exe(),
                    run=str(run), poll_seconds=30, max_seconds=max_seconds, helper=binding(__file__),
                    first_native_id=first_native_id, started_at=time.time(), no_http_gpu_post=True)
    claim = directory / 'OBSERVER_CLAIM.json'
    with claim.open('x', encoding='utf-8') as stream:
        json.dump(identity, stream, ensure_ascii=False, indent=2)
    write(directory / 'OBSERVER.json', identity)
    known = dict.fromkeys(IDS);known['S01'] = first_native_id
    completed = []
    deadline = time.monotonic()+max_seconds
    def progress(status, **extra):
        value = dict(status=status, observer_pid=own.pid, native_ids=known, completed=completed,
                     no_media_retry=True, production_approved=False, **extra)
        write(directory / 'PROGRESS.json', value)
        return value
    def cpu(action, sid=None):
        if sha(__file__) != helper_sha256:
            raise ValueError('frozen helper changed during observation; observer stops itself')
        args = [sys.executable, '-X', 'utf8', '-B', str(Path(__file__).resolve()), action, '--run', str(run), '--project-root', str(project)]
        if sid:
            args += ['--segment', sid, '--asr']
        if time.monotonic() >= deadline:
            raise TimeoutError('bounded observer deadline reached before CPU QA')
        process = subprocess.run(args, cwd=project, capture_output=True, text=True, encoding='utf-8', errors='replace',
                                 timeout=min(1200, max(1, int(deadline-time.monotonic()))),
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        stem = sid or 'FINAL'
        (directory / (stem+'.CPU.stdout.log')).write_text(process.stdout, encoding='utf-8')
        (directory / (stem+'.CPU.stderr.log')).write_text(process.stderr, encoding='utf-8')
        if process.returncode:
            raise ValueError('CPU QA failed; original worker is untouched: '+process.stdout[-2000:])
        return json.loads(process.stdout)
    try:
        validate_room_only_spec(read(check(read(run/'PLAN.json')['spec'], project)), run, project=project)
        progress('observing_original_local_files')
        for sid in IDS:
            while time.monotonic() < deadline:
                state = read(run/'shots'/sid/'STATE.json');pid = state.get('prompt_id')
                if pid:
                    if not isinstance(pid, str) or not re.fullmatch('[A-Za-z0-9_-]{1,100}', pid):
                        raise ValueError('unsafe original native ID')
                    if known[sid] is None:
                        known[sid] = pid
                    if known[sid] != pid:
                        raise ValueError('original native ID changed; observer does not resubmit')
                elif known[sid] is not None:
                    raise ValueError('original native ID lost; observer does not resubmit')
                if state.get('status') in ('failed', 'interrupted', 'rejected', 'outcome_unknown'):
                    raise ValueError('native terminal '+state['status']+'; observer does not resubmit')
                if state.get('status') == 'technical_saved':
                    result = cpu('segment', sid)
                    result['quote_evidence'] = quote_evidence(run, sid, project=project)
                    completed.append(result);progress('segment_cpu_qa_complete', segment=sid)
                    print(json.dumps(result, ensure_ascii=False), flush=True)
                    break
                time.sleep(min(30, max(0, deadline-time.monotonic())))
            else:
                return progress('bounded_observation_expired')
        while time.monotonic() < deadline:
            if (run/'FINAL_RESULT.json').exists():
                result = cpu('final');completed.append(result)
                return progress('all_cpu_qa_complete', final=result)
            time.sleep(min(30, max(0, deadline-time.monotonic())))
        return progress('bounded_observation_expired')
    except Exception as error:
        value = progress('observer_stopped_on_error', error=dict(type=type(error).__name__, message=str(error)))
        write(directory / 'ERROR.json', value)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['segment', 'final', 'observe-room-only'])
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--segment', choices=IDS)
    parser.add_argument('--asr', action='store_true')
    parser.add_argument('--spatial-handoff', type=Path)
    parser.add_argument('--project-root', type=Path, default=PROJECT)
    parser.add_argument('--observer-dir', type=Path)
    parser.add_argument('--first-native-id')
    parser.add_argument('--helper-sha256')
    parser.add_argument('--max-seconds', type=int, default=28800)
    args = parser.parse_args(argv)
    if args.action == 'segment':
        if not args.segment:
            parser.error('--segment is required')
        result = qa_segment(args.run, args.segment, asr=args.asr, spatial_handoff=args.spatial_handoff, project=args.project_root)
    elif args.action == 'final':
        result = qa_final(args.run, project=args.project_root)
    else:
        if not args.observer_dir or not args.first_native_id or not args.helper_sha256:
            parser.error('--observer-dir, --first-native-id and --helper-sha256 required')
        result = observe_room_only(args.run, args.observer_dir, args.first_native_id, args.helper_sha256,
                                   max_seconds=args.max_seconds, project=args.project_root)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0 if result['status'] == 'all_cpu_qa_complete' else 3
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps(dict(status='cpu_qa_failed', type=type(error).__name__, message=str(error), no_media_retry=True), ensure_ascii=False))
        raise SystemExit(2)
