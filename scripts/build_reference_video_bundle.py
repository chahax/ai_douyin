"""Source-bound, review-gated Seedance prompts; no submission side effects."""
import argparse
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.plan_reference_video import build_plan
from scripts.run_reference_director import approved,read,digest,check

def reviewed_file(path,review):
    proof=read(review)
    check(proof.get('decision')=='passed' and proof.get('unresolved')==[], 'Actual review required')
    check(proof.get('candidate_sha256')==digest(path),'Review is stale')
    check(proof.get('findings') and all(r.get('evidence') and r.get('finding') for r in proof['findings']),'Review evidence missing')

def compile_bundle(run):
    plan_path=run/'delivery/execution_plan.json'
    plan=build_plan(run)
    check(read(plan_path)==plan,'Execution plan differs from reviewed source projection')
    reviewed_file(plan_path,run/'delivery/execution_plan.review.json')
    casting=approved(run/'casting')
    names={key:value['name'] for key,value in casting['characters'].items()}
    rows=[]
    for index,segment in enumerate(plan['segments']):
        text=[f"竖屏9:16，写实生活短片《{plan['title']}》，本段{segment['duration']}秒。"]
        if not index:
            text += [plan['space']['layout']]
            if segment['reference']=='text_only':
                text += ['纯文本生成本段虚构家庭场景。空间中只有一个入户门洞；门轴：'+plan['space']['door_hinge']+
                         '；门扇开向：'+plan['space']['door_opening']+'；固定地标：'+'、'.join(plan['space']['landmarks'])+'。',
                         '父亲与东侧鞋柜之间留出已排定侧步所需空间，门槛与两人双脚在建立全景中可见。']
            for key,c in casting['characters'].items():
                text += [f"{c['name']}：{c['appearance']}。开场：{casting['opening_expression'][key]}。"]
            text += [f"{names[key]}初态：{position}" for key,position in plan['space']['opening_positions'].items()]
        else:
            text += ['从紧邻已审上段的原始尾帧开始，保留人物外貌、衣着、场景与身体位置；不重置表情或动作。',
                     '0—0.125秒保留上段末尾构图，随后按下列镜头切换。']
        text += ['光线：'+casting['lighting'],'表演只按人物动作时间表发生一次。摄影段落中的姿态描述是观察对象，不得触发重复动作；对白只按唯一对白时间表发声。','摄影时间表（本段局部秒数，只规定观察与构图）：']
        for s in segment['proposed_camera']:
            size=({'wide':'全景','medium':'中景','close':'近景','detail':'细节特写'}[s['size']]+'，') if plan.get('generation_options') else ''
            text += [f"{s['start']}—{s['end']}秒，{s['id']}：{size}{s['composition']}。机位：{s['camera_side']}。"]
        text += ['人物动作时间表：']
        text += [f"{a['start']}—{a['end']}秒，{names[a['actor']]}：{a['description']}。" for a in segment['performance']['actions']]
        text += ['本段唯一对白与声音时刻：']
        text += [f"{l['start']}—{l['end']}秒，{names[l['speaker']]}说：{l['text']}" for l in segment['performance']['lines']]
        if not segment['performance']['lines']:text += ['本段无对白。']
        text += ['固定声线：'+'；'.join(c['name']+'：'+c['voice'] for c in casting['characters'].values()),
                 '声线描述不增加咳嗽、清嗓、叹词或其他发声。语速服从已列对白窗口；自然完整说完，未说话者不对口型。',
                 '剪到听者反应时，说话者可以在画外继续原句；不得把声音转给画内听者。',
                 '末态：'+json.dumps({names[k]:v for k,v in segment['performance']['end_positions'].items()},ensure_ascii=False),
                 '不加字幕、旁白、配乐、额外人声、手持物或新剧情动作。']
        rows.append({'shot_id':segment['id'],'duration_seconds':segment['duration'],'beat_id':segment['beat_id'],
                     'model_prompt_zh':'\n'.join(text),'reference_requirement':segment['reference']})
    return {'schema':'reference_seedance_prompt_bundle/v1','title':plan['title'],'duration_seconds':plan['duration'],
            'plan':{'path':str(plan_path),'sha256':digest(plan_path),'review_sha256':digest(run/'delivery/execution_plan.review.json')},
            'casting':{'path':str(run/'casting/candidate.json'),'sha256':digest(run/'casting/candidate.json'),'review_sha256':digest(run/'casting/review.json')},
            'sources':plan['sources'],'shots':rows,'status':'compiled_pending_prompt_review','media_calls':0,'ready_to_submit':False}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run-dir',required=True)
    parser.add_argument('--output-name',default='seedance_prompts')
    args=parser.parse_args()
    check(args.output_name.replace('_','').isalnum(),'Output must be a simple directory name')
    run=Path(args.run_dir).resolve();value=compile_bundle(run)
    target=run/'delivery'/args.output_name;target.mkdir(exist_ok=False)
    (target/'bundle.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    for shot in value['shots']:
        (target/(shot['shot_id']+'.txt')).write_text(shot['model_prompt_zh'],encoding='utf-8')
    print(target)
