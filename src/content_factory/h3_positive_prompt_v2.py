"""Content-only H3 prompt projection and an independent S01 graph preview; no client."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'data/video_generation/h3_positive_revision_20261018'
INPUT_ROOT = ROOT / 'data/local_media_tests/minimax_h3_20261015/input'
BASELINE = ROOT / 'data/video_generation/h3_project_script_20261015/revision_02/media/workflow_api.json'
BASE_SHA = 'b17945cf1589a4ec5685776b29b19d3187a55ece8f6b74cbb53c7c7903fdc672'
ACTORS = {'C01': '周桂芳', 'C02': '马涛'}
SEGMENTS = [f'S{i:02d}' for i in range(1, 13)]
PREFIX = 'h3_positive_revision_20261018'

# Specific production directives, rather than the ordinary Chinese words 不/没.
CONTROL = re.compile(
    r'(?:本段|本镜|本片|当前镜头|当前段落|本次).{0,8}(?:只|仅).{0,5}(?:生成|演|输出|呈现)'
    r'|(?:不要|不能|禁止|不得|不许|避免|无需|不应|不可).{0,12}'
    r'(?:生成|添加|出现|加入|朗读|字幕|旁白|配乐|演员|台词|角色|复制|提前|表演|出镜|改变|显示|使用|叠加)'
    r'|(?:不生成|不添加|不出现|不朗读|不复制|不提前|无字幕|无旁白|无配乐|只生成|仅生成|只演|仅演|仅限)'
    r'|(?:WORLD_CURRENT|NEGATIVE_PROMPT|SYSTEM\s*PROMPT|IGNORE\s+(?:ALL\s+)?PREVIOUS|提示词|模型输入|审核状态|预算|回执|接口|制作说明|字段名|编码网格)',
    re.IGNORECASE)


def sha(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def binding(path):
    return {'path': str(Path(path).resolve()), 'sha256': sha(path)}


def bound(row):
    path = Path(row['path']).resolve()
    if sha(path) != row['sha256']:
        raise ValueError('source file identity differs: ' + path.name)
    return path


def text(value, field, *, visual=False):
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise ValueError('nonempty text required: ' + field)
    if visual and CONTROL.search(value):
        raise ValueError('production directive is not visual story content: ' + field)
    return value


def number(value, field):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('finite timing required: ' + field)
    return float(value)


def speaker_id(speaker):
    if speaker in ACTORS:
        return speaker
    for key, name in ACTORS.items():
        if speaker == name:
            return key
    raise ValueError('unknown actor in dialogue')


def validate_screenplay(screenplay):
    world = screenplay['world']
    text(world['scene_visual'], 'world.scene_visual', visual=True)
    text(world['sound_visual'], 'world.sound_visual', visual=True)
    if set(world['character_visuals']) != set(ACTORS):
        raise ValueError('exactly C01 and C02 visual identities are required')
    for actor in ACTORS:
        text(world['character_visuals'][actor], 'character_visuals.' + actor, visual=True)
    if [segment['id'] for segment in screenplay['segments']] != SEGMENTS:
        raise ValueError('exactly twelve ordered segments S01-S12 are required')
    for segment in screenplay['segments']:
        if number(segment['duration_seconds'], 'duration_seconds') != 15:
            raise ValueError('each authored segment must last 15 seconds')
        text(segment['shot_visual'], 'shot_visual', visual=True)
        # These remain source/continuity metadata. They never enter model text.
        for key in ('location_time', 'start_state', 'end_state', 'causal_context'):
            if key not in segment:
                raise ValueError('missing sidecar continuity field: ' + key)
        if not isinstance(segment['beats'], list) or not segment['beats']:
            raise ValueError('each segment needs timed performance beats')
        previous = 0.0
        for beat in segment['beats']:
            start, end = number(beat['start_s'], 'start_s'), number(beat['end_s'], 'end_s')
            if abs(start - previous) > 1e-8 or not 0 <= start < end <= 15:
                raise ValueError('beats must form an ordered contiguous 0-15 second timeline')
            previous = end
            text(beat['action_visual'], 'action_visual', visual=True)
            if not isinstance(beat['dialogue'], list):
                raise ValueError('dialogue must be a list')
            for line in beat['dialogue']:
                speaker_id(line['speaker'])
                text(line['text'], 'dialogue.text')
        if abs(previous - 15) > 1e-8:
            raise ValueError('performance beats must finish at 15 seconds')
    return screenplay


def compile_prompt(screenplay, segment):
    """An explicit allowlist projection; metadata is never serialized into the prompt."""
    world = screenplay['world']
    lines = ['<Picture 1>：' + world['scene_visual'],
             '<Picture 2>：' + world['character_visuals']['C01'],
             '<Picture 3>：' + world['character_visuals']['C02'],
             world['sound_visual'], segment['shot_visual']]
    for beat in segment['beats']:
        lines.append(f"{beat['start_s']:g}—{beat['end_s']:g}秒。" + beat['action_visual'])
        for line in beat['dialogue']:
            lines.append(ACTORS[speaker_id(line['speaker'])] + '用自然普通话说：“' + line['text'] + '”')
    return '\n'.join(lines) + '\n'


def source_recipe():
    return dict(schema='h3_positive_content_source_recipe/v2', baseline_graph_sha256=BASE_SHA,
                parameters=['prompt', 'noise_seed', 'reference_images', 'output_prefix'],
                nodes=dict(condition='condition', noise='129', guider='126', sampler='125',
                           references=['ref_scene', 'ref_C01', 'ref_C02'],
                           saves=dict(video='save_video', audio='save_audio', first='save_first', last='save_last')),
                fixed=dict(width=1280, height=704, fps=24, length=362, steps=20),
                input_mode='three_original_reference_images', native_tail_input=False, audio_reference_input=False,
                source_graph_is_immutable=True, graph_output_is_preview_only=True)


def relative_image(value):
    text(value, 'staged_image_relative_path')
    normalized = value.replace('\\', '/')
    parts = normalized.split('/')
    if ':' in normalized or normalized.startswith('/') or any(part in ('', '.', '..') for part in parts):
        raise ValueError('staged image must be a safe relative input path')
    if not normalized.startswith(PREFIX + '/'):
        raise ValueError('staged images must belong to this independent revision')
    return normalized


def compile_graph(baseline, recipe, parameters):
    if recipe != source_recipe() or set(parameters) != set(recipe['parameters']):
        raise ValueError('unexpected named source recipe parameters')
    if (len(baseline) != 22 or any(node['class_type'] in ('LoadAudio', 'MiniMaxH3AddGuide') for node in baseline.values())
            or baseline['126']['inputs']['conditioning'] != ['condition', 0]
            or baseline['125']['inputs']['latent_image'] != ['condition', 1]):
        raise ValueError('only the original 22-node reference-only S01 baseline is allowed')
    graph = copy.deepcopy(baseline)
    condition = graph['condition']['inputs']
    if (graph['condition']['class_type'] != 'MiniMaxH3ReferenceToVideo'
            or graph['127']['inputs']['unet_name'] != 'minimax_h3_ref2va_pruned_int8_convrot.safetensors'
            or any('lora' in node['class_type'].lower() for node in graph.values())
            or [condition[k] for k in ('width', 'height', 'length')] != [1280, 704, 362]
            or graph['124']['inputs']['steps'] != 20 or graph['130']['inputs']['fps'] != 24
            or any('ref_audio' in key or key == 'audio_vae' for key in condition)):
        raise ValueError('native REF2VA baseline or input mode changed')
    if len(parameters['reference_images']) != 3:
        raise ValueError('three ordered scene/C01/C02 references required')
    for index, (node, filename) in enumerate(zip(recipe['nodes']['references'], parameters['reference_images'])):
        if condition[f'ref_images.ref_image_{index}'] != [node, 0]:
            raise ValueError('scene/C01/C02 reference socket order changed')
        graph[node]['inputs']['image'] = relative_image(filename)
    condition['prompt'] = text(parameters['prompt'], 'compiled_prompt')
    if type(parameters['noise_seed']) is not int or parameters['noise_seed'] < 0:
        raise ValueError('nonnegative integer seed required')
    if parameters['output_prefix'] != PREFIX + '/S01':
        raise ValueError('this preparation compiles the new S01 graph only')
    graph['129']['inputs']['noise_seed'] = parameters['noise_seed']
    for role, node in recipe['nodes']['saves'].items():
        graph[node]['inputs']['filename_prefix'] = parameters['output_prefix'] + '/' + role
    return graph


def validate_references(rows):
    if not isinstance(rows, list) or len(rows) != 3:
        raise ValueError('three source-reference mappings required')
    for row, picture, role, kind in zip(rows, (1,2,3), ('scene','C01','C02'), ('empty_scene','single_person_portrait','single_person_portrait')):
        if (row['picture'] != picture or row['role'] != role or row['kind'] != kind
                or row.get('human_approved') is not False):
            raise ValueError('reference identity, single-person format or approval scope changed')
        original = bound(row['source'])
        if original.drive.upper() != 'D:' or original.suffix.lower() not in ('.png','.jpg','.jpeg'):
            raise ValueError('original reference must be a D-drive image')
        if role != 'scene' and re.search(r'board|turnaround|三视|多视',original.stem,re.I):
            raise ValueError('multi-view boards cannot be used in this revision')
        relative_image(row['staged_image_relative_path'])
    if len({row['source']['sha256'] for row in rows}) != 3 or len({row['staged_image_relative_path'] for row in rows}) != 3:
        raise ValueError('three distinct scene/actor sources and input paths required')


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def prepare(out=OUT, input_root=INPUT_ROOT):
    out, input_root = Path(out).resolve(), Path(input_root).resolve()
    if out.drive.upper() != 'D:' or input_root.drive.upper() != 'D:':
        raise ValueError('preparation files and staging remain on D:')
    plan = read(out/'REVISION_PLAN.json')
    if (plan.get('schema') != 'h3_positive_content_revision_plan/v1'
            or plan.get('new_media_dispatch_authorized_by_this_preparation') is not False):
        raise ValueError('this independent entry is preparation-only')
    baseline_path = Path(plan['baseline_graph']).resolve()
    if baseline_path != BASELINE.resolve() or sha(baseline_path) != BASE_SHA:
        raise ValueError('immutable original baseline bytes changed')
    screenplay = validate_screenplay(read(out/'SCREENPLAY.json'))
    refs = read(out/'REFERENCE_MAP.json')
    validate_references(refs)
    staged = []
    for row in refs:
        original=bound(row['source'])
        target=(input_root/relative_image(row['staged_image_relative_path'])).resolve()
        if not target.is_relative_to(input_root):
            raise ValueError('staged path escaped input root')
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists() and sha(target)!=row['source']['sha256']:
            raise ValueError('never overwrite a different original staged image')
        if not target.exists():
            shutil.copy2(original,target)
        if sha(target)!=row['source']['sha256']:
            raise ValueError('reference staging changed original bytes')
        staged.append(dict(picture=row['picture'],role=row['role'],source=row['source'],input=binding(target),
                           relative_input=row['staged_image_relative_path']))
    prompt_bindings=[]
    for segment in screenplay['segments']:
        directory=out/'segments'/segment['id'];directory.mkdir(parents=True,exist_ok=True)
        prompt=compile_prompt(screenplay,segment)
        (directory/'PROMPT.txt').write_text(prompt,encoding='utf-8',newline='\n')
        sidecar=dict(schema='h3_positive_content_projection/v2',segment_id=segment['id'],
                     screenplay=binding(out/'SCREENPLAY.json'),reference_map=binding(out/'REFERENCE_MAP.json'),
                     source_segment=segment,world_metadata={key:value for key,value in screenplay['world'].items()
                         if key not in ('scene_visual','character_visuals','sound_visual')},
                     compiled_prompt=binding(directory/'PROMPT.txt'),
                     projection_allowlist=['world.scene_visual','world.character_visuals.C01','world.character_visuals.C02',
                         'world.sound_visual','segment.shot_visual','beats.start_s','beats.end_s','beats.action_visual','beats.dialogue.speaker','beats.dialogue.text'],
                     media_submissions=0,content_status='awaiting_human_review')
        write_json(directory/'PROMPT_PROJECTION.json',sidecar)
        prompt_bindings.append(dict(segment_id=segment['id'],prompt=binding(directory/'PROMPT.txt')))
    recipe=source_recipe();write_json(out/'SOURCE_RECIPE.json',recipe)
    parameters=dict(prompt=(out/'segments/S01/PROMPT.txt').read_text(encoding='utf-8'),noise_seed=2026101801,
                    reference_images=[row['staged_image_relative_path'] for row in refs],output_prefix=PREFIX+'/S01')
    graph=compile_graph(read(baseline_path),recipe,parameters)
    write_json(out/'segments/S01/PARAMETERS.json',parameters)
    write_json(out/'segments/S01/GRAPH_PREVIEW.json',graph)
    result=dict(schema='h3_positive_content_preflight/v2',state='prepared_not_submitted',
                revision_plan=binding(out/'REVISION_PLAN.json'),screenplay=binding(out/'SCREENPLAY.json'),
                reference_map=binding(out/'REFERENCE_MAP.json'),baseline_graph=binding(baseline_path),
                source_recipe=binding(out/'SOURCE_RECIPE.json'),staged_references=staged,prompts=prompt_bindings,
                S01_graph=binding(out/'segments/S01/GRAPH_PREVIEW.json'),graph_nodes=len(graph),
                source_graph_preserved=sha(baseline_path)==BASE_SHA,media_submissions=0,api_calls=0,
                following_segments='prompt_preparation_only_no_graphs_or_dispatch',pixel_inspection=False)
    write_json(out/'PREFLIGHT.json',result)
    return result
