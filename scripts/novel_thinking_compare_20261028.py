"""One-shot prose comparison; no production defaults or old runs modified."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def parameters(model, text, enabled):
    result = dict(model=model, messages=[dict(role='user', content=text)],
                  max_tokens=24000, extra_body={'thinking': {'type': 'enabled' if enabled else 'disabled'}})
    if enabled:
        result['reasoning_effort'] = 'high'
    return result


def save(path, value):
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)


def main():
    from openai import OpenAI
    from src.content_factory.creative_workflow_roles import role_config, _response_model_matches
    cfg = role_config('director')
    text = (ROOT/'data/model_comparison_exports/20261028_first_three_chapters/一键发送_要求加前三章.md').read_text(encoding='utf-8')
    run = ROOT/'data/corpus_production_trials/20261028_deepseek_thinking_compare'
    run.mkdir(exist_ok=False)
    save(run/'PLAN.json', dict(calls_max=2, source_chapters=[1,2,3],
         input_sha256=hashlib.sha256(text.encode()).hexdigest(),
         authorization='用户要求尝试与网页版相同的完整章节分析及深度思考', production_defaults_changed=False))
    client = OpenAI(api_key=cfg.api_key, base_url=cfg.base_url, timeout=600, max_retries=0)
    for enabled in (False, True):
        label = 'thinking_high' if enabled else 'thinking_disabled'
        stage = run/label
        stage.mkdir()
        args = parameters(cfg.model, text, enabled)
        save(stage/'REQUEST.json', args)
        save(stage/'START.json', dict(pending=True))
        try:
            response = client.chat.completions.create(**args)
        except Exception as e:
            save(stage/'ERROR.json', dict(type=type(e).__name__, pending=True, status='outcome_unknown'))
            print(label+': outcome_unknown', flush=True)
            return
        save(stage/'RESPONSE.json', response.model_dump(mode='json'))
        choice = response.choices[0] if len(response.choices)==1 else None
        content = choice.message.content if choice else None
        ok = bool(choice and choice.finish_reason=='stop' and content and _response_model_matches('director',cfg.model,response.model))
        save(stage/'RESULT.json', dict(pending=None, response_complete=ok,
             semantic_acceptance='not_reviewed', usage=response.usage.model_dump() if response.usage else None))
        if content:
            (stage/'ANSWER.md').write_text(content, encoding='utf-8')
        print(label+': '+('complete' if ok else 'unaccepted_response'), flush=True)
        if not ok:
            return


if __name__ == '__main__':
    main()
