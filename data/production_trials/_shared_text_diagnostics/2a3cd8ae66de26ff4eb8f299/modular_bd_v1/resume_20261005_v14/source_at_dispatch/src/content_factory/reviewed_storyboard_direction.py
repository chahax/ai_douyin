"""Bind an already reviewed fixed-camera storyboard without new authoring."""
from __future__ import annotations

import copy
import hashlib
import math
from pathlib import Path

SCHEMA = 'reviewed_storyboard_direction/v1'
CAMERA_ID = 'reviewed_fixed_master'
FIXED_FIELDS = ('scene', 'blocking', 'shot_size', 'camera_angle', 'camera_movement', 'lighting')
GENERATION = {'method': 'mechanical_reviewed_storyboard_binding', 'model_calls': 0,
              'story_text_changed': False, 'media_review_performed': False}


def _facts(script):
    if (script.get('schema') != 'detailed_video_script/v4' or script.get('format_kind') != 'short'
            or script.get('target_duration_seconds') != 45 or script.get('aspect_ratio') != '9:16'
            or script.get('generation', {}).get('method') != 'staged_screenplay_bundle'
            or not isinstance(script['generation'].get('staged_screenplay_bundle'), dict)):
        raise ValueError('Reviewed storyboard binding requires the staged, reviewed 45-second short script')
    characters = script.get('characters')
    if not isinstance(characters, list) or len(characters) != 2:
        raise ValueError('Reviewed storyboard binding requires exactly two characters')
    names = [c.get('name') for c in characters]
    if any(not isinstance(name, str) or not name.strip() for name in names) or len(set(names)) != 2:
        raise ValueError('Reviewed storyboard character identities are invalid')
    shots = script.get('shots')
    if not isinstance(shots, list) or len(shots) != 6:
        raise ValueError('Reviewed storyboard binding requires the complete six-shot story')
    fixed = {key: shots[0].get(key) for key in FIXED_FIELDS}
    if any(not isinstance(v, str) or not v.strip() for v in fixed.values()) or fixed['camera_movement'] != '固定':
        raise ValueError('Reviewed storyboard requires one explicit fixed camera and lighting setup')
    cursor = 0
    for index, shot in enumerate(shots):
        start, end = shot.get('start_seconds'), shot.get('end_seconds')
        if (shot.get('shot_id') != f'S{index+1:02d}'
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in (start, end))
                or start != cursor or end - start != int(end - start) or not 4 <= end - start <= 15):
            raise ValueError('Reviewed storyboard timeline must be contiguous with 4-15 second integer shots')
        if any(shot.get(key) != value for key, value in fixed.items()):
            raise ValueError('Reviewed storyboard cannot change the fixed scene, blocking, camera or lighting')
        if (not isinstance(shot.get('participants'), (list, tuple)) or len(shot['participants']) != 2
                or set(shot['participants']) != set(names) or shot.get('dialogue_mode') != 'in_scene'
                or shot.get('dialogue_speaker') not in names):
            raise ValueError('Reviewed storyboard requires both characters visible and one in-scene speaker')
        for key in ('action', 'dialogue', 'model_prompt_zh', 'composition', 'camera', 'start_frame',
                    'end_frame', 'audio', 'emotion_and_performance', 'continuity', 'transition'):
            if not isinstance(shot.get(key), str) or not shot[key].strip():
                raise ValueError('Reviewed storyboard lacks an unchanged production field: ' + key)
        if index and shot['start_frame'] != shots[index-1]['end_frame']:
            raise ValueError('Reviewed storyboard start/end states must inherit the preceding shot exactly')
        cursor = end
    if cursor != 45:
        raise ValueError('Reviewed storyboard duration must be exactly 45 seconds')
    return fixed


def _proof(current_review, script_path, script_sha):
    from src.trend_intelligence.script_pair import CURRENT_SCRIPT_REVIEW_SCHEMA
    if (not isinstance(current_review, dict) or current_review.get('current_passed') is not True
            or current_review.get('status') != 'current_passed'
            or current_review.get('schema') != CURRENT_SCRIPT_REVIEW_SCHEMA
            or current_review.get('script_json_path') != str(Path(script_path).resolve())
            or current_review.get('script_json_sha256') != script_sha
            or any(not isinstance(current_review.get(key), str) or not current_review[key]
                   for key in ('report_path', 'candidate_sha256', 'evidence_sha256', 'full_source_evidence_sha256'))):
        raise ValueError('Reviewed storyboard binding requires current saved pair review for these exact script bytes')


def _plan(script, script_path, script_sha, current_review):
    fixed = _facts(script)
    _proof(current_review, script_path, script_sha)
    return {'schema': SCHEMA, 'script_sha256': script_sha, 'source_script': str(Path(script_path).resolve()),
            'script_editorial_review': copy.deepcopy(current_review), 'fixed_camera': fixed,
            'staged_screenplay_bundle': copy.deepcopy(script['generation']['staged_screenplay_bundle']),
            'shots': [{'shot_id': shot['shot_id'], 'camera_id': CAMERA_ID, 'storyboard': copy.deepcopy(shot)}
                      for shot in script['shots']], 'generation': copy.deepcopy(GENERATION)}


def build_plan(script, script_path, current_review):
    source = Path(script_path).resolve()
    raw = source.read_bytes()
    import json
    if json.loads(raw) != script:
        raise ValueError('Reviewed storyboard differs from its source file')
    return _plan(script, source, hashlib.sha256(raw).hexdigest(), current_review)


def validate_plan(plan, script, script_sha):
    if not isinstance(plan, dict) or plan.get('schema') != SCHEMA:
        raise ValueError('Expected a reviewed storyboard mechanical binding')
    expected = _plan(script, plan.get('source_script', ''), script_sha, plan.get('script_editorial_review'))
    if plan != expected:
        raise ValueError('Reviewed storyboard plan changed: every shot field must equal the locked reviewed script')


def compile_prompt(script, shot, plan, *, use_input_first_frame=False, timing_mode='ordered'):
    validate_plan(plan, script, plan.get('script_sha256'))
    original = next((item for item in script['shots'] if item['shot_id'] == shot.get('shot_id')), None)
    if original != shot:
        raise ValueError('Requested shot differs from the exact reviewed storyboard')
    prompt = shot['model_prompt_zh']
    if use_input_first_frame:
        if shot['shot_id'] == script['shots'][0]['shot_id']:
            return prompt + ('\n首镜静态开场约束：输入图是本镜动作发生前、已核对故事初态的开场静帧。'
                '从该初态连续执行上述本镜动作和对白，开场发声与动作并行；保持图中身份、固定机位、光线与道具数量，'
                '不得先跳到动作完成后的尾态，不额外增加动作或对白。')
        prompt += ('\n首帧衔接约束：以提供的真实首帧中人物姿态、视线、手和道具的实际状态为本镜起点，'
                   '连续执行上述本镜已审动作和对白。不得为匹配文字首帧而重新摆位、复位道具或重演上一段已完成的叙事；'
                   '保持输入帧的构图、固定机位与光线，沿原动作推进至本镜规定尾态，不额外增加动作或对白。')
    return prompt
