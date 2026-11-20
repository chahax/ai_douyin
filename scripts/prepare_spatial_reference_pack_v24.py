"""CPU-only experiment inputs from the actual, completed reference-minute run.

This creates new prompts and an explicit provenance audit. It does not confer
production asset approval or submit any model job.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT / 'data/video_generation/spatial_minute_experiments_20261107_v1'
SOURCE = PROJECT / 'data/video_generation/h3_reference_full_minute_20261107_v1'


def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8-sig'))


def bound(p):
    p = Path(p).resolve()
    return {'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}


def freeze(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    if p.exists():
        if p.read_text(encoding='utf-8') != data:
            raise ValueError('existing experiment artifact differs; use a new revision')
    else:
        p.write_text(data, encoding='utf-8')


IDENTITIES = '''人物与参考图逐一对应：
苏墨是<Picture 1>中的成年父亲，灰色纽扣衬衫外穿深色夹克、深色长裤。
叶南是<Picture 2>中的哥哥，灰色翻领短袖上衣、深色长裤；他比弟弟高。
叶西决是<Picture 3>中的弟弟，米色圆领短袖上衣、灰色短裤；他比哥哥矮。
正文中的苏墨、叶南、叶西决始终分别指向上述人物。对白段落中指定人物说台词，另一人以倾听或反应的表演承接。人物的内心独白以该人物的画外音呈现，画面中的本人闭嘴思考。'''


def adapted(text):
    anchor = '场景是苏墨的房间，人物外观、服装与场景环境采用本段具名参考图。'
    if text.count(anchor) != 1:
        raise ValueError('expected original reference mechanism paragraph')
    changes = [dict(old=anchor, new=anchor + '\n' + IDENTITIES, count=1)]
    if '男童心声：' in text:
        changes.append(dict(old='男童心声：', new='叶西决的内心独白，以叶西决的画外音呈现：', count=1))
    result = text
    for c in changes:
        if result.count(c['old']) != c['count']:
            raise ValueError('ambiguous adaptation')
        result = result.replace(c['old'], c['new'])
    quotes = lambda s: re.findall('“[^”]*”', s)
    if quotes(text) != quotes(result):
        raise ValueError('original dialogue changed')
    return result, changes


def prepare(root=ROOT, source=SOURCE):
    root, source = Path(root).resolve(), Path(source).resolve()
    if not root.is_relative_to(PROJECT / 'data/video_generation') or root == source:
        raise ValueError('new experiment namespace required')
    plan = read(source / 'RUNNER_PLAN.json')
    if read(source / 'ROOT_CHECKPOINT.json').get('task_status') != 'diagnostic_movie_complete':
        raise ValueError('completed original inputs required')
    records = []
    references = None
    for row in plan['segments']:
        sid = row['id']
        delivery = Path(row['delivery_run'])
        result = read(delivery / 'shots' / sid / 'RESULT.json')
        state = read(delivery / 'shots' / sid / 'STATE.json')
        if state['status'] != 'technical_saved' or state['prompt_id'] != result['prompt_id']:
            raise ValueError('known saved originals required')
        source_file = Path(row['source_prompt_file']['path'])
        if bound(source_file) != row['source_prompt_file']:
            raise ValueError('original prompt SHA changed')
        text, changes = adapted(source_file.read_text(encoding='utf-8'))
        path = root / 'sources' / (sid + '.prompt.txt')
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != text.encode('utf-8'):
            raise ValueError('frozen adapted prompt changed')
        path.write_bytes(text.encode('utf-8'))
        records.append(dict(id=sid, original_source_prompt=bound(source_file),
                            adapted_prompt=bound(path), changes=changes,
                            original_request=row['source_request'],
                            original_native_id=result['prompt_id'],
                            original_result=bound(delivery/'shots'/sid/'RESULT.json'),
                            dialogue_unchanged=True))
        bundle = read(delivery/'shots'/sid/'REFERENCE_BUNDLE.json')
        refs = bundle['references']
        for ref in refs:
            if bound(ref['image']['path']) != ref['image']:
                raise ValueError('original actual reference changed')
        if references is None:
            references = refs
        elif [(x['reference_id'], x['image']) for x in refs] != [(x['reference_id'], x['image']) for x in references]:
            raise ValueError('original four segments reference mismatch')
    guide_result = read(Path(plan['segments'][0]['delivery_run'])/'shots/S01/RESULT.json')
    start_guide = guide_result['files']['first']
    if bound(start_guide['path']) != {k:start_guide[k] for k in ('path','sha256')}:
        raise ValueError('known S01 original first changed')
    value = dict(schema='spatial_experiment_inputs/v24', parent_runner_plan=bound(source/'RUNNER_PLAN.json'),
                 original_reuse_manifest=bound(source/'MANIFEST.json'), references=references,
                 first_guide={k:start_guide[k] for k in ('path','sha256')},
                 first_guide_provenance=records[0]['original_result'], segments=records,
                 preparation_only=True, model_calls=0, production_approved=False, publication=False)
    freeze(root/'INPUTS.json', value)
    return value


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, default=ROOT)
    a = p.parse_args()
    v = prepare(a.root)
    print(json.dumps({'inputs':str(a.root/'INPUTS.json'), 'segments':len(v['segments']), 'model_calls':0}))
