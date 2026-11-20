"""Isolated same-input medium/max comparison with a parent wall-clock deadline."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'MiniMax-M3.1-Flash'
RUN = ROOT/'data/corpus_production_trials/20261028_minimax_effort_compare'


def save(path, value):
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)


def parameters(text, effort):
    if effort not in ('medium', 'max'):
        raise ValueError('unsupported_trial_effort')
    return dict(model=MODEL, messages=[{'role': 'user', 'content': text}],
                max_completion_tokens=24000, reasoning_effort=effort,
                extra_body={'thinking': {'type': 'adaptive'}, 'reasoning_split': True},
                stream=True, stream_options={'include_usage': True})


def bounded_process(command, seconds):
    """Only terminate the specific child created here; never enumerate processes."""
    p = subprocess.Popen(command, cwd=ROOT)
    try:
        return p.wait(timeout=seconds), False
    except subprocess.TimeoutExpired:
        p.terminate()
        p.wait(timeout=10)
        return p.returncode, True


def worker(stage):
    from dotenv import dotenv_values
    from openai import OpenAI
    cfg = dotenv_values(ROOT/'.env')
    key = cfg.get('WRITER_AGENT_API_KEY') or os.environ.get('WRITER_AGENT_API_KEY')
    if not key:
        save(stage/'RESULT.json', {'status': 'preflight_failed', 'pending': None, 'calls_started': 0})
        return
    args = json.loads((stage/'REQUEST.json').read_text(encoding='utf-8'))
    client = OpenAI(api_key=key, base_url=cfg.get('WRITER_AGENT_BASE_URL') or 'https://api.minimaxi.com/v1',
                    max_retries=0, timeout=90)
    save(stage/'START.json', {'pending': True, 'calls_started': 1})
    started = time.monotonic()
    content, reasoning, finishes, models, usage = [], [], [], set(), None
    try:
        with (stage/'CHUNKS.jsonl').open('x', encoding='utf-8') as log:
            with client.chat.completions.create(**args) as stream:
                for chunk in stream:
                    raw = chunk.model_dump(mode='json')
                    log.write(json.dumps(raw, ensure_ascii=False)+'\n'); log.flush()
                    if chunk.model:
                        models.add(chunk.model)
                    if chunk.usage:
                        usage = chunk.usage.model_dump(mode='json')
                    for c in chunk.choices:
                        if c.index != 0:
                            raise ValueError('unexpected_choice_index')
                        if c.delta.content:
                            content.append(c.delta.content)
                        r = getattr(c.delta, 'reasoning_content', None)
                        if r:
                            reasoning.append(r)
                        if c.finish_reason:
                            finishes.append(c.finish_reason)
        answer = ''.join(content)
        (stage/'ANSWER.md').write_text(answer, encoding='utf-8')
        ok = bool(answer and finishes == ['stop'] and models == {MODEL})
        save(stage/'RESULT.json', {'status': 'response_complete' if ok else 'response_unaccepted',
             'pending': None if finishes else True, 'finish_reasons': finishes, 'models': sorted(models),
             'usage': usage, 'reasoning_characters': sum(map(len, reasoning)),
             'answer_characters': len(answer), 'elapsed_seconds': time.monotonic()-started,
             'semantic_acceptance': 'not_reviewed'})
    except Exception as e:
        # Exception strings may include credentials or request bodies.
        save(stage/'ERROR.json', {'type': type(e).__name__, 'status': 'outcome_unknown', 'pending': True,
                                 'usage': usage, 'elapsed_seconds': time.monotonic()-started})


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--worker':
        worker(Path(sys.argv[2])); return
    text = (ROOT/'data/model_comparison_exports/20261028_first_three_chapters/一键发送_要求加前三章.md').read_text(encoding='utf-8')
    RUN.mkdir(exist_ok=False)
    save(RUN/'PLAN.json', {'authorization': '用户：测试下吧；MiniMax前三章同输入medium/max文本对照',
         'max_calls': 2, 'wall_seconds_per_call': 600, 'retry': False,
         'input_sha256': hashlib.sha256(text.encode()).hexdigest(), 'defaults_changed': False})
    for effort in ('medium', 'max'):
        stage = RUN/effort
        stage.mkdir()
        save(stage/'REQUEST.json', parameters(text, effort))
        code, expired = bounded_process([sys.executable, str(Path(__file__).resolve()), '--worker', str(stage)], 600)
        save(stage/'PROCESS.json', {'exit_code': code, 'deadline_expired': expired})
        if expired or not (stage/'RESULT.json').exists():
            save(stage/'PARENT_STATUS.json', {'status': 'outcome_unknown' if (stage/'START.json').exists() else 'preflight_failed',
                 'pending': bool((stage/'START.json').exists()), 'retry': False})
            print(effort+': stopped; see evidence', flush=True); return
        result = json.loads((stage/'RESULT.json').read_text(encoding='utf-8'))
        print(effort+': '+result['status'], flush=True)
        if result['status'] != 'response_complete':
            return


if __name__ == '__main__':
    main()
