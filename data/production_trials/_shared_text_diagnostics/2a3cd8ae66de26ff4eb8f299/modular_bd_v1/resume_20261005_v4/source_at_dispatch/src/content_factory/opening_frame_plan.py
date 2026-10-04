"""Prepare a source-bound still plan from the current reviewed S01, without API calls."""
from __future__ import annotations

import json

from .ark_opening_frame import (
    PLAN_SCHEMA, _bytes, _inside, _now, _run_inputs, _sha, _unique, _validate_plan,
    _write, render_opening_prompt,
)

RENDER_TEMPLATE = 'locked_static_opening/v1'
SHOT_FIELDS = ('scene', 'blocking', 'camera', 'shot_size', 'camera_angle',
               'camera_movement', 'lighting', 'start_frame', 'participants')
CHARACTER_FIELDS = ('name', 'appearance', 'wardrobe')


def prepare_opening_frame_plan(run_dir, output_path):
    """Extract only approved static fields; creating this plan grants no approval."""
    folder, _, direction, binding = _run_inputs(run_dir)
    output = _inside(output_path, folder)
    if output.suffix.lower() != '.json' or output == folder:
        raise ValueError('Use a new JSON plan path inside this video run')
    if output.exists():
        raise FileExistsError('Opening plan already exists; preserve its original bytes')
    script_path = folder / 'locked_script.json'
    script_raw = script_path.read_bytes()
    if _sha(script_raw) != binding['script_sha256']:
        raise ValueError('Locked script changed while extracting the opening plan')
    script = json.loads(script_raw, object_pairs_hook=_unique)
    shot = script['shots'][0]
    if shot != direction['shots'][0]['storyboard']:
        raise ValueError('S01 differs from the currently reviewed direction binding')
    characters = script['characters']
    if script.get('aspect_ratio') != '9:16' or len(characters) != 2:
        raise ValueError('This opening plan requires the reviewed 9:16 two-character story')
    for character in characters:
        for key in CHARACTER_FIELDS:
            if not isinstance(character.get(key), str) or not character[key].strip():
                raise ValueError('Opening plan requires a source character ' + key)
    names = [character['name'] for character in characters]
    if len(set(names)) != 2 or set(shot['participants']) != set(names):
        raise ValueError('Opening participants must be exactly the two source characters')
    spatial = shot['blocking'] + '\n' + shot['camera_angle'] + '\n' + shot['camera']
    if '西侧' not in spatial or not any(word in spatial for word in ('相对', '相向', '对坐')):
        raise ValueError('The locked source must establish the west-side camera and opposing seats; do not invent them')
    # The same extraction used at image submission supplies names and quantity.
    _, prop_source = render_opening_prompt(shot['start_frame'], shot['start_frame'])
    props = list(prop_source['prop_names'].values())
    if not props:
        raise ValueError('Opening state must define the actual props and their natural names')
    source_fields = {}

    def capture(pointer, value):
        source_fields[pointer] = {'value': value, 'sha256': _sha(_bytes(value))}

    capture('/aspect_ratio', script['aspect_ratio'])
    for index, character in enumerate(characters):
        for key in CHARACTER_FIELDS:
            capture(f'/characters/{index}/{key}', character[key])
    for key in SHOT_FIELDS:
        capture('/shots/0/' + key, shot[key])

    # Fixed static framing instructions contain no story action or state invention.
    lines = [
        '9:16竖屏，单张真人写实短剧开场静帧。仅呈现以下两位人物，不增加其他人。',
        '空间呈现：保留已审隔桌对坐、相向侧脸，桌面隔在两人躯干之间；'
        '西侧整条近镜头桌沿保持可辨，双方近侧嘴部可辨，允许远侧眼被遮挡。',
        '场景：' + shot['scene'],
        '座位与空间：' + shot['blocking'],
        '机位：' + shot['camera'],
        '景别：' + shot['shot_size'],
        '相机角度：' + shot['camera_angle'],
        '摄影机：' + shot['camera_movement'],
        '光线：' + shot['lighting'],
    ]
    for character in characters:
        lines.append('人物：' + character['name'] + '；外貌：' + character['appearance']
                     + '；服装：' + character['wardrobe'])
    lines.extend([
        '道具仅为以下' + str(len(props)) + '件，每项对应一件原有道具，不额外复制：' + '；'.join(props),
        '真实开场初态（只表现此刻，尚未开始动作）：' + shot['start_frame'],
        '保留初态规定的纸张版式与签署状态；不要额外字幕、画面标题、水印或道具，'
        '不要把制作编号或字段标签印到纸上。仅表现上述静态初态，不擅自移动手、视线或道具。',
    ])
    prompt, render_recipe = render_opening_prompt('\n'.join(lines), shot['start_frame'])
    plan = {'schema': PLAN_SCHEMA, 'shot_id': 'S01',
        'script_sha256': binding['script_sha256'], 'direction_sha256': binding['direction_sha256'],
        'prompt': prompt, 'provenance': {'schema': 'mechanical_opening_frame_plan/v1',
            'method': 'mechanical', 'model_calls': 0, 'media_review': 'pending', 'text_review': 'pending',
            'created_at': _now().isoformat(), 'source_fields': source_fields,
            'render_recipe': render_recipe, 'render_template': RENDER_TEMPLATE,
            'character_count': len(characters), 'prop_count': len(props)}}
    _validate_plan(plan, binding)
    output.parent.mkdir(parents=True, exist_ok=True)
    _write(output, plan, exclusive=True)
    return plan
