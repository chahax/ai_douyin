"""Render reviewed model-authored text without creating or changing dialogue."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_narrative_workflow import verify_workflow, read_candidate, new_output, now, save
from src.trend_intelligence.narrative_workflow import identity, read, require_review


def render_version(kind, outline, script, production, review_path):
    version = outline[kind]
    story = script[kind]
    plans = {r['shot_id']: r for r in production[kind]}
    scenes = {r['id']: r for r in story['scenes']}
    names = {r['id']: r['name'] for r in outline['characters']}
    duration = sum(s['duration_seconds'] for s in story['shots'])
    lines = [f"# {version['title']} · {'短视频' if kind == 'short' else '长视频'} · {duration:g}秒", '',
        '本文件由项目模型候选机械排版，未改写动作或对白。已完成文本与分镜审查，待用户审核；尚未生成视频或完成音画验证。', '',
        f"核心：{outline['core']}", '', f"开场问题：{version['opening_question']}", '',
        f"实际结局：{version['payoff']}", '', f"结尾余味：{version['aftertaste']}", '',
        '## 人物', '']
    for c in outline['characters']:
        lines += [f"- **{c['name']}（{c['id']}）**：目标：{c['wants']}；掌握的信息：{c['hidden_or_known']}；代价：{c['stakes']}"]
    lines += ['', '## 事件与情绪', '', '| 事件 | 时段 | 可见行动与结果 | 人物表现 | 预期观众感受（设计假说） |', '| --- | --- | --- | --- | --- |']
    elapsed = 0
    for e in version['events']:
        end = elapsed + e['duration_seconds']
        cells = [e['event_id'], f'{elapsed:g}—{end:g}秒', e['visible_action'] + ' → ' + e['consequence'], e['character_emotion'], e['audience_effect']]
        lines.append('| ' + ' | '.join(c.replace('|', '／').replace('\n', ' ') for c in cells) + ' |')
        elapsed = end
    lines += ['', '## 分镜、对白与声音', '']
    elapsed = 0
    for s in story['shots']:
        end = elapsed + s['duration_seconds']; p = plans[s['shot_id']]; scene = scenes[s['scene_id']]
        lines += [f"### {s['shot_id']} · {elapsed:g}—{end:g}秒 · {s['event_id']}", '',
            f"场景：{scene['location']}；{scene['time_context']}", '',
            f"画面：{p['camera']}", '', f"光线：{p['lighting']}", '',
            f"动作：{s['action']}", '', f"结果：{s['result']}", '',
            f"表演：{p['performance']}", '']
        for d in s['dialogue']:
            lines += [f"**{names[d['speaker']]}（全片{elapsed + d['start']:g}—{elapsed + d['end']:g}秒）**：{d['text']}", '', f"语气与节奏：{d['delivery']}", '']
        if not s['dialogue']:lines += ['无对白；以本镜动作、信息或反应推进。', '']
        lines += [f"声音设计：{p['sound_design']}", '', f"切镜理由：{p['cut_reason']}", '',
            f"执行要求：{p['continuity_mode']}；{p['execution_requirement']}", '']
        for key, label in [('state_before', '首态'), ('state_after', '尾态')]:
            state = s[key]
            values = [f'{names.get(k, k)}：{v}' for group in state.values() for k, v in group.items()]
            lines += [label + '：' + '；'.join(values), '']
        elapsed = end
    lines += ['## 参考使用', '']
    for ref in outline['reference_usage']:
        lines += [f"- {ref['source_id']} / {', '.join(ref['evidence_ids'])}：{ref['borrowed_mechanism']} 原创转化：{ref['original_change']}"]
    lines += ['', f"[本稿摄影审核记录]({Path(review_path).resolve().as_posix()})", '',
        '情节为原创演绎；参考素材的法律主张不自动视为核实结论。涉及个案应结合事实与证据判断。', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('workflow', 'outline-run', 'script-run', 'production-run', 'review', 'output-dir'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    _, context, _ = verify_workflow(args.workflow)
    outline = read_candidate(args.outline_run, args.workflow, 'outline', context)
    script = read_candidate(args.script_run, args.workflow, 'script', context)
    production = read_candidate(args.production_run, args.workflow, 'production', context)
    if read(Path(args.script_run) / 'run.json')['parent']['run'] != identity(Path(args.outline_run) / 'run.json'):
        raise ValueError('Selected outline is not the script parent')
    if read(Path(args.production_run) / 'run.json')['parent']['run'] != identity(Path(args.script_run) / 'run.json'):
        raise ValueError('Selected script is not the production parent')
    require_review(read(args.review), 'production', Path(args.production_run) / 'candidate.json', args.workflow)
    output = new_output(args.output_dir)
    for kind in ('short', 'long'):
        (output / (kind + '.md')).write_text(render_version(kind, outline, script, production, args.review), encoding='utf-8')
    save(output / 'delivery.json', {'status': 'reviewed_text_pending_user_review', 'rendered_at_bjt': now(),
        'inputs': {name: identity(Path(value) / 'candidate.json') for name, value in (
            ('outline', args.outline_run), ('script', args.script_run), ('production', args.production_run))},
        'review': identity(args.review), 'media_generated': False,
        'outputs': {kind: identity(output / (kind + '.md')) for kind in ('short', 'long')}})
    print(output)


if __name__ == '__main__':main()
