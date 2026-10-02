"""Revise only a still prompt through the project model after an actual image failure."""
from pathlib import Path
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.content_factory.ark_opening_frame import _run_inputs, _validate_plan
from src.shared.llm_client import LLMClient
from src.shared.config import settings
from src.trend_intelligence.production_revision import parse_unique_json

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('run-dir', 'previous-plan', 'feedback', 'output-dir'):
        parser.add_argument('--' + key, required=True)
    args = parser.parse_args()
    folder, _, _, binding = _run_inputs(args.run_dir)
    previous_path, feedback_path, output = map(lambda p: Path(p).resolve(),
        (args.previous_plan, args.feedback, args.output_dir))
    for path in (previous_path, feedback_path, output):
        path.relative_to(folder)
    previous_raw = previous_path.read_bytes()
    previous = parse_unique_json(previous_raw)
    _validate_plan(previous, binding)
    feedback_raw = feedback_path.read_bytes()
    # Re-read the frozen source on every revision; the previous prompt is not
    # an authoritative substitute for the actual S01 or character appearance.
    script_raw = (folder / 'locked_script.json').read_bytes()
    if hashlib.sha256(script_raw).hexdigest() != binding['script_sha256']:
        raise ValueError('Locked script changed while preparing the revision')
    script = parse_unique_json(script_raw)
    shot = script['shots'][0]
    frozen_opening = {'script_sha256': binding['script_sha256'],
        'shot': {key: shot[key] for key in (
            'shot_id', 'participants', 'scene', 'blocking', 'camera', 'shot_size',
            'camera_angle', 'camera_movement', 'lighting', 'start_frame') if key in shot},
        'characters': [{key: character[key] for key in (
            'name', 'identity', 'appearance', 'wardrobe') if key in character}
            for character in script['characters']]}
    output.mkdir(parents=True, exist_ok=False)
    def save(name, data):
        raw = json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')
        (output / name).write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()
    messages = [{'role': 'system', 'content':
        '你是本项目的开场静帧提示词编辑。只能改写一张图片的摄影表达以落实已经冻结的场景、人物、机位和初始状态。'
        '不得改写剧情、对白、左右手、人数、道具数量、座位或光线；不新增动作，不把尾态写入静帧。'
        '只输出JSON对象，唯一键prompt，值为适合Seedream的简明中文纯文生图提示词。'
        '用自然连贯的静态画面描述落实空间关系，不照搬JSON字段名或写长篇审核口号。'
        'frozen_opening来自本轮重新读取的锁定剧本，是静帧事实依据；旧提示词或反馈与其冲突时不得覆盖冻结事实。'
        '反馈来自人的实际看图，模型未看到图片；不可声称你已经看图或输出通过。'},
        {'role': 'user', 'content': json.dumps({'previous_plan': previous,
            'frozen_opening': frozen_opening,
            'actual_visual_feedback': feedback_raw.decode('utf-8')}, ensure_ascii=False)}]
    model = settings.SCRIPT_LLM_MODEL or settings.LLM_MODEL
    extra = {'thinking': {'type': 'disabled'}, 'reasoning_split': True} if model.lower() == 'minimax-m3' else None
    run = {'schema': 'opening_frame_prompt_revision/v1', 'status': 'prepared',
        'started_at': datetime.now(timezone.utc).isoformat(), 'model_calls': 0, 'model': model,
        'binding': binding, 'previous_plan_sha256': hashlib.sha256(previous_raw).hexdigest(),
        'feedback_sha256': hashlib.sha256(feedback_raw).hexdigest(), 'request_sha256': save('request.json', messages)}
    save('run.json', run)
    client = None
    metadata = {}
    output_received = False
    try:
        client = LLMClient(model=model, extra_body=extra, max_retries=0, max_tokens=2400,
                           preserve_invalid_json=True, timeout_seconds=180)
        if client.provider_name == 'mock':
            raise ValueError('A real configured project model is required')
        run.update(status='outcome_unknown', model_calls=1)
        save('run.json', run)
        try:
            raw = client.chat_completion_tracked(messages, caller='pre_video_opening_still_revision',
                                                temperature=0.4, json_mode=True, use_cache=False)
        finally:
            metadata = getattr(client.provider, 'last_response_metadata', {})
            save('response_metadata.json', metadata)
        run['output_sha256'] = save('model_output.json', raw)
        output_received = raw is not None or bool(metadata.get('finish_reason'))
        value = parse_unique_json(raw)
        if (not isinstance(value, dict) or set(value) != {'prompt'}
                or not isinstance(value['prompt'], str) or not value['prompt'].strip()):
            raise ValueError('Model must return only the revised nonempty prompt')
    except Exception as exc:
        run.update(status=('failed_model_output' if output_received else
                           'outcome_unknown' if run['model_calls'] else 'preflight_rejected'),
                   error_type=type(exc).__name__, finished_at=datetime.now(timezone.utc).isoformat())
        if metadata.get('error_type'):
            run['provider_error_type'] = metadata['error_type']
        save('run.json', run)
        raise
    plan = {**previous, 'prompt': value['prompt'], 'provenance': {
        'method': 'project_model_static_prompt_revision', 'model_calls': 1, 'story_changed': False,
        'parent_plan': str(previous_path), 'parent_plan_sha256': run['previous_plan_sha256'],
        'feedback_path': str(feedback_path), 'feedback_sha256': run['feedback_sha256'],
        'model_output_sha256': run['output_sha256'], 'text_review': 'pending', 'media_review': 'pending'}}
    _validate_plan(plan, binding)
    run['candidate_sha256'] = save('opening_frame_plan.json', plan)
    run.update(status='candidate_pending_independent_review', finished_at=datetime.now(timezone.utc).isoformat())
    save('run.json', run)
    print(json.dumps({'status': run['status'], 'plan': str(output / 'opening_frame_plan.json'),
                      'sha256': run['candidate_sha256'], 'prompt_chars': len(value['prompt'])}, ensure_ascii=False))

if __name__ == '__main__':
    main()
