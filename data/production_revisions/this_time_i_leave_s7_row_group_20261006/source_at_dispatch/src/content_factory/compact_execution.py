"""Explicit S01 execution projection; no script rewriting or media approval."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .ark_opening_frame import _bytes, _inside, _now, _read, _run_inputs, _sha, _write, render_opening_prompt
from .seedance_frames import reviewed_frame_reference

PLAN_SCHEMA = 'compact_execution_plan/v1'
PROFILE = 'compact_execution/v1'
GROUNDED_PROFILE = 'compact_execution/v2'
GROUNDED_PLAN_SCHEMA = 'compact_execution_plan/v2'
REVIEW_SCHEMA = 'compact_execution_review/v1'
REVIEW_CHECKS = frozenset({'source_action_preserved', 'performance_voice_preserved',
    'dialogue_once_subtitle_separate', 'terminal_state_preserved',
    'first_frame_identity_preserved', 'no_added_story_action'})
SOURCE_FIELDS = ('action', 'emotion_and_performance', 'audio', 'end_frame',
                 'dialogue', 'subtitle', 'dialogue_speaker', 'start_frame',
                 'participants', 'start_seconds', 'end_seconds')


def _identity(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': _sha(path.read_bytes())}


def render_compact_prompt(shot, aspect_ratio, grounding=None, *, focus=None, continuation=False):
    """Copy actual execution text once; only mechanical prop-name replacement."""
    valid_position = (shot.get('shot_id') == 'S01' and shot.get('start_seconds') == 0)
    if continuation:
        valid_position = (shot.get('shot_id') in ('S02', 'S03', 'S04', 'S05', 'S06')
                          and isinstance(shot.get('start_seconds'), (int, float))
                          and shot['start_seconds'] > 0 and grounding is None)
    if (not valid_position
            or shot.get('dialogue_mode') != 'in_scene' or aspect_ratio != '9:16'
            or not isinstance(shot.get('participants'), list) or len(shot['participants']) != 2
            or shot.get('dialogue_speaker') not in shot['participants']):
        raise ValueError('Compact execution is only the actual two-person S01 in-scene opening')
    for key in ('action', 'emotion_and_performance', 'audio', 'end_frame', 'dialogue', 'subtitle', 'start_frame'):
        if not isinstance(shot.get(key), str) or not shot[key].strip():
            raise ValueError('Compact execution requires the complete source field: ' + key)
    if shot['dialogue'] != shot['subtitle']:
        raise ValueError('Postproduction subtitle must exactly equal the unique source dialogue')
    duration = shot['end_seconds'] - shot['start_seconds']
    if type(duration) not in (int, float) or duration != int(duration) or not 4 <= duration <= 15:
        raise ValueError('Compact S01 requires the actual integer shot duration')
    # Never rewrite a spoken prop code into different dialogue. This profile
    # only supports source speech that survives the prop-name renderer exactly.
    if render_opening_prompt(shot['dialogue'], shot['start_frame'])[0] != shot['dialogue']:
        raise ValueError('Source dialogue contains a prop ID; compact projection cannot alter spoken words')
    lines = [
        f'本段{duration:g}秒，9:16。以已审输入首帧为动作起点，保持其中两人的身份外观、座位、场景、构图和既有光线。固定单镜头，不切镜、不变焦，保留下方字幕预留区。',
        '动作（保留原顺序及并行关系）：' + shot['action'],
        '表演与节奏：' + shot['emotion_and_performance'],
        '声音：' + shot['audio'],
        f'唯一对白（仅{shot["dialogue_speaker"]}完整说一遍，口型匹配，其他人物不代说）：“{shot["dialogue"]}”',
        '片尾达到：' + shot['end_frame'],
        '只执行所列动作，保持原有物件数量，不增加动作或对白。禁止旁白和未列出的声音。',
        '不生成字幕、水印或额外画面标题，保留首图合同已有印刷文字；后期按唯一对白统一字幕。',
    ]
    if continuation:
        lines.insert(1, '输入为紧邻已通过片段的原始尾帧，直接承接其真实姿态和道具位置；不复位、不重演上一段动作。')
    if grounding is not None:
        from .execution_grounding import validate_model_value, FOCUS_NAME
        if focus not in (None, FOCUS_NAME):
            raise ValueError('Unsupported compact grounding focus')
        validate_model_value(grounding, _bytes(shot).decode('utf-8'))
        lines[1:1] = ['主体与纸张对应：' + '；'.join(grounding['visual_bindings']),
                      ('原末态注意力与接触：' if focus else '原动作接触范围：') + '；'.join(grounding['action_constraints'])]
    raw = '\n'.join(lines)
    rendered, recipe = render_opening_prompt(raw, shot['start_frame'])
    if rendered.count(shot['dialogue']) != 1:
        raise ValueError('The exact source dialogue must occur once in the execution request')
    return rendered, recipe


def _build(run_dir, image, config, grounding_plan=None):
    from scripts.run_script_video import compile_default_first_frame_prompt
    folder, manifest, direction, binding = _run_inputs(run_dir)
    if (config.provider != 'ark_api' or config.base_url != manifest['api_base_url']
            or config.model != manifest['api_model']):
        raise ValueError('Compact execution must use the current locked Ark configuration')
    image = _inside(image, folder)
    reference, frame = reviewed_frame_reference(folder, 'S01', image, manifest, direction, config=config)
    origin = frame.get('original_ark_image')
    if not isinstance(origin, dict) or not reference.source.startswith('https://'):
        raise ValueError('Compact execution requires the reviewed original Ark opening image')
    review_identity = origin.get('source_frame_review')
    if review_identity is None:
        review_identity = _identity(folder / 'frame_reviews/S01.json')
    elif _identity(review_identity['path']) != review_identity:
        raise ValueError('Inherited original image review bytes changed')
    script = _read(folder / 'locked_script.json')
    shot = script['shots'][0]
    if _sha(_bytes(shot)) != binding['shot_sha256']:
        raise ValueError('Locked shot changed during compact projection')
    grounding = grounding_proof = None
    if grounding_plan is not None:
        from .execution_grounding import require_grounding
        grounding, grounding_proof = require_grounding(folder, image, grounding_plan, config)
    focus = grounding_proof.get('focus', {}).get('name') if grounding_proof else None
    prompt, recipe = render_compact_prompt(shot, script['aspect_ratio'], grounding, focus=focus)
    original = compile_default_first_frame_prompt(script, shot, direction)
    result = {'schema': PLAN_SCHEMA, 'profile': PROFILE, 'shot_id': 'S01', 'run_dir': str(folder),
        'source': {**binding, 'script': _identity(folder / 'locked_script.json'),
            'direction': _identity(folder / 'direction_plan.json'),
            'first_frame': {**_identity(image), **frame['image_info']},
            'first_frame_review': review_identity,
            'first_frame_binding_sha256': _sha(_bytes(frame)),
            'original_ark_image_proof': origin, 'original_ark_image_proof_sha256': _sha(_bytes(origin))},
        'source_fields': {key: {'value': shot[key], 'sha256': _sha(_bytes(shot[key]))} for key in SOURCE_FIELDS},
        'original_prompt': original, 'original_prompt_sha256': _sha(original.encode('utf-8')),
        'prompt': prompt, 'prompt_sha256': _sha(prompt.encode('utf-8')), 'render_recipe': recipe,
        'omitted_redundant_fields': ['model_prompt_zh', 'transition', 'continuity',
                                   'composition', 'scene', 'blocking', 'camera', 'lighting', 'character_appearance'],
        'omission_scope': 'Initial appearance, composition and light remain bound by the reviewed image; repeated state and production commentary are retained in the original prompt audit only.',
        'subtitle_source': {'text': shot['subtitle'], 'sha256': _sha(shot['subtitle'].encode('utf-8')),
            'model_burn_in': False, 'policy': 'postproduction_from_unique_dialogue'},
        'model_calls': 0, 'text_review': 'pending', 'media_review': 'pending'}
    if grounding_proof is not None:
        result.update(schema=GROUNDED_PLAN_SCHEMA, profile=GROUNDED_PROFILE,
                      grounding=grounding_proof, grounding_text=grounding)
    return result


def prepare_compact_execution(run_dir, image, output_path, config, *, grounding_plan=None):
    output = _inside(output_path, run_dir)
    if output.suffix.lower() != '.json' or output.exists():
        raise ValueError('Use a new JSON execution-plan path inside this run')
    plan = _build(run_dir, image, config, grounding_plan)
    plan['created_at'] = _now().isoformat()
    output.parent.mkdir(parents=True, exist_ok=True)
    _write(output, plan, exclusive=True)
    return plan


def require_compact_execution(run_dir, image, plan_path, review_path, config):
    """Reproduce the exact current plan and require a separate real text review."""
    plan_path, review_path = _inside(plan_path, run_dir), _inside(review_path, run_dir)
    plan_raw, review_raw = plan_path.read_bytes(), review_path.read_bytes()
    plan, review = _read(plan_path), _read(review_path)
    grounding_plan = None
    if plan.get('profile') == GROUNDED_PROFILE and plan.get('schema') == GROUNDED_PLAN_SCHEMA:
        grounding_plan = plan.get('grounding', {}).get('plan_path')
        if not isinstance(grounding_plan, str) or not grounding_plan:
            raise ValueError('Grounded execution requires its real source-bound grounding plan')
    elif plan.get('profile') != PROFILE or plan.get('schema') != PLAN_SCHEMA:
        raise ValueError('Unsupported compact execution profile')
    expected = _build(run_dir, image, config, grounding_plan)
    created = datetime.fromisoformat(plan.get('created_at', ''))
    if created.utcoffset() is None:
        raise ValueError('Execution plan creation time must include its timezone')
    expected['created_at'] = plan['created_at']
    if plan != expected:
        raise ValueError('Compact plan does not reproduce from the actual current source and reviewed frame')
    required_bindings = {'plan_path': str(plan_path), 'plan_sha256': _sha(plan_raw),
        'prompt_sha256': plan['prompt_sha256'], 'script_sha256': plan['source']['script_sha256'],
        'direction_sha256': plan['source']['direction_sha256'],
        'first_frame_sha256': plan['source']['first_frame']['sha256']}
    if (not isinstance(review, dict) or review.get('schema') != REVIEW_SCHEMA
            or review.get('decision') != 'passed'
            or any(review.get(key) != value for key, value in required_bindings.items())
            or set(review.get('checks', {})) != REVIEW_CHECKS
            or any(value is not True for value in review['checks'].values())
            or not isinstance(review.get('notes'), str) or not review['notes'].strip()):
        raise ValueError('Compact execution requires its exact-bound passed independent text review')
    if datetime.fromisoformat(review.get('reviewed_at', '')).utcoffset() is None:
        raise ValueError('Independent execution review needs its actual timezone-aware reviewed_at')
    if plan_path.read_bytes() != plan_raw or review_path.read_bytes() != review_raw:
        raise ValueError('Execution plan or independent review changed during verification')
    proof = {'schema': 'compact_execution_binding/v1', 'profile': plan['profile'],
        **required_bindings, 'review_path': str(review_path), 'review_sha256': _sha(review_raw),
        'original_prompt_sha256': plan['original_prompt_sha256'],
        'first_frame_review': plan['source']['first_frame_review'],
        'original_ark_image_proof_sha256': plan['source']['original_ark_image_proof_sha256'],
        'subtitle_source': plan['subtitle_source'], 'scope': 'execution_text_projection_only; no_media_approval'}
    if grounding_plan is not None:
        proof['grounding'] = plan['grounding']
    return plan['prompt'], proof
