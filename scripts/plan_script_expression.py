"""Create a model event outline using a saved, verified project workflow request."""
from __future__ import annotations
import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.shared.config import settings
from src.shared.llm_client import LLMClient
from src.trend_intelligence.script_outline import build_outline_messages, validate_outline, text_sha


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workflow-request', required=True)
    parser.add_argument('--editor-feedback-file', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--previous-outline', default='')
    parser.add_argument('--reference-source-id', action='append', default=[])
    args = parser.parse_args()
    source = Path(args.workflow_request).resolve()
    allowed = (Path(__file__).resolve().parents[1] / 'data/pre_video_scripts/_runs').resolve()
    if allowed not in source.parents or source.name != 'request.json':
        raise ValueError('只接受本项目已保存的原始工作流request.json')
    original = source.read_bytes().decode('utf-8')
    feedback = Path(args.editor_feedback_file).read_text(encoding='utf-8')
    previous = json.loads(Path(args.previous_outline).read_text(encoding='utf-8')) if args.previous_outline else None
    messages = build_outline_messages(json.loads(original), feedback, previous, reference_source_ids=args.reference_source_id)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=False)
    def save(name, value):
        (output / name).write_text(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8', newline='')
    state = {'schema': 'script_expression_outline_run/v1', 'status': 'running',
             'started_at': datetime.now(timezone(timedelta(hours=8))).isoformat(),
             'workflow_request_path': str(source), 'workflow_request_sha256': text_sha(original),
             'feedback_sha256': text_sha(feedback), 'media_generation': False}
    save('request.json', messages)
    state['prompt_sha256'] = text_sha(messages[0]['content'])
    state['request_sha256'] = text_sha((output/'request.json').read_bytes().decode('utf-8'))
    if args.previous_outline:
        state['previous_outline_path'] = str(Path(args.previous_outline).resolve())
        state['previous_outline_sha256'] = text_sha(Path(args.previous_outline).read_bytes().decode('utf-8'))
    save('run.json', state)
    model = settings.SCRIPT_LLM_MODEL or settings.LLM_MODEL
    extra = None
    try:
        if settings.SCRIPT_LLM_THINKING:
            if model.lower() != 'minimax-m3' or settings.SCRIPT_LLM_THINKING not in ('disabled', 'adaptive'):
                raise ValueError('提纲沿用项目支持的编剧thinking配置')
            extra = {'thinking': {'type': settings.SCRIPT_LLM_THINKING}, 'reasoning_split': True}
        limit = settings.SCRIPT_LLM_MAX_TOKENS if settings.SCRIPT_LLM_THINKING == 'adaptive' else min(settings.SCRIPT_LLM_MAX_TOKENS, 12000)
        client = LLMClient(timeout_seconds=settings.SCRIPT_LLM_TIMEOUT_SECONDS, max_retries=0,
                           max_tokens=limit, preserve_invalid_json=True,
                           model=settings.SCRIPT_LLM_MODEL or None, extra_body=extra)
        if client.provider_name == 'mock':
            raise ValueError('提纲不允许模拟模型')
        state.update(model=model, thinking=settings.SCRIPT_LLM_THINKING)
        save('run.json', state)
        raw = client.chat_completion_tracked(messages, caller='pre_video_script_outline', temperature=0.6,
                                              json_mode=True, use_cache=False)
        save('response.json', getattr(getattr(client, 'provider', None), 'last_response_metadata', {}))
        save('model_outline.json', raw or 'null')
        state['model_outline_sha256'] = text_sha(raw or 'null')
        if not raw:
            raise RuntimeError('提纲模型未返回可用内容')
        outline = validate_outline(json.loads(raw), messages)
        save('outline.json', outline)
        state.update(status='candidate_pending_independent_review', model=model,
                     outline_sha256=text_sha((output/'outline.json').read_text(encoding='utf-8')))
    except Exception as exc:
        state.update(status='failed', error=str(exc))
        raise
    finally:
        state['finished_at'] = datetime.now(timezone(timedelta(hours=8))).isoformat()
        save('run.json', state)
    print(json.dumps(state, ensure_ascii=False))


if __name__ == '__main__':
    main()
