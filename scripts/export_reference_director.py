"""Render reviewed layers without rewriting model-authored content."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_reference_director import STAGES, approved, validate, read, digest, check

def export(run):
    selected=read(run/'stage_selection.json')
    layers={}
    bindings={}
    for stage in STAGES:
        folder=run/selected.get(stage,stage)
        value=approved(folder)
        validate(stage,value,layers)
        layers[stage]=value
        bindings[stage]={'folder':str(folder),'candidate_sha256':digest(folder/'candidate.json'),'review_sha256':digest(folder/'review.json')}
    output=run/'delivery'
    output.mkdir(exist_ok=False)
    names={k:c['name'] for k,c in layers['story']['characters'].items()}
    duration=sum(b['duration'] for b in layers['story']['beats'])
    lines=['# '+layers['story']['title'],'',f'{duration}秒文字导演稿；当前各层已审，成片未生成。不是独立连续三次通过的证明。','',
           '## 空间','',layers['visual']['space']['layout'],'',layers['story']['initial'],'']
    segments=[]
    for beat,emotion,performance in zip(layers['story']['beats'],layers['emotion']['beats'],layers['performance']['beats']):
        shots=[s for s in layers['visual']['shots'] if s['beat_id']==beat['id']]
        lines += ['## '+beat['id']+' · '+str(beat['duration'])+'秒','',beat['event'],'',
                  '**情绪**：'+emotion['before']+' → '+emotion['after'],'',
                  '**触发与选择**：'+emotion['trigger']+'；'+emotion['choice'],'','**镜头**','']
        for shot in shots:
            lines += [f"- {shot['id']} {shot['start']}–{shot['end']}秒，{shot['size']}：{shot['composition']}"]
        lines += ['','**动作**','']
        for action in performance['actions']:
            lines += [f"- {action['start']}–{action['end']}秒，{names[action['actor']]}：{action['description']}（{action['readable_in_shot']}）"]
        lines += ['','**对白**','']
        for speech in performance['lines']:
            lines += [f"- {speech['start']}–{speech['end']}秒，{names[speech['speaker']]}：{speech['text']}"]
        lines += ['']
        segments.append({'beat':beat,'emotion':emotion,'shots':shots,'performance':performance,'media_review':'not_generated'})
    lines += ['## 结尾','',layers['story']['ending'],'','## 未完成验证','',
              '首图空间、实际表情可读性、镜内动作、切点连续性和同步声音尚未验证。以下段落不是已授权执行器请求，仍需生成段与镜头映射及逐段尾帧审核。']
    (output/'SCREENPLAY.md').write_text('\n'.join(lines),encoding='utf-8')
    (output/'reviewed_layers.json').write_text(json.dumps({'schema':'reference_director_reviewed_layers/v1','source_bindings':bindings,'segments':segments,'media_ready':False},ensure_ascii=False,indent=2),encoding='utf-8')
    print(output/'SCREENPLAY.md')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--run-dir',required=True)
    export(Path(parser.parse_args().run_dir).resolve())
