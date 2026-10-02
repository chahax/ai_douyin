"""Bounded original-script module evaluation with explicit, evidence-based revisions."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
from copy import deepcopy
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.evaluate_minimax_scripts import request_once,machine_review
from src.content_factory.creative_workflow_contract import WRITER_TOOL_SCHEMAS,parse_json_object,compile_beat_screenplay
from src.content_factory.creative_writer_prompt_pack import build_writer_prompt
from src.content_factory.creative_workflow_inputs import file_binding
from src.content_factory.reusable_production import read,write
CASES=ROOT/'config/minimax_script_eval_cases_v2_20260927.json'
PACK=ROOT/'config/prompts/creative_writer_modules_v2.json'
REVIEW_PROMPT='''你是DeepSeek独立剧本审查员。对每份稿按brief审查需求兑现、因果、物理状态、对白自然、情绪反应与可执行时长。只报告真正错误，不改写。实际播放顺序before→首句dialogue→during→第二句dialogue→after；event/trigger是摘要不会播放。未看视频不能声称媒体通过。\n逐项检查：结尾行动主体是否符合关系角色；禁止桥段和物品是否被引入；前半段线索按累计时长而不是拍号判断；反应是否在真实刺激之后；关键物是否有唯一位置及合理交接。剧本拍不是视频单镜，不受单镜15秒上限。\n正常跨拍省略普通走路、摘要与正文重复、符合要求的规则、无矛盾的动作不得列为issues。读到明确“正在封箱”就不能说开箱到封箱无过程。对白前后反应以实际编译为准。剧情合理但不合个人喜好不判major。\n只返回JSON {"reviews":[{"sample_id":"输入ID","issues":[{"severity":"major或minor","category":"requirements/causality/timing/props/space/dialogue/ending","evidence":[{"path":"beats.0.before","quote":"从字段逐字摘录"}],"impact":"具体矛盾与影响","proposal":"修复目标"}],"strength":"具体优点"}]}。每份完整覆盖。不把优点和无问题内容列issues；缺乏证据不要猜测。'''

def check(script,case):
    r=machine_review(script,case)
    if not r['structural_errors']:
        if case.get('max_ending_seconds') and script['beats'][-1]['duration_seconds']>case['max_ending_seconds']:
            if 'ending_duration_over_limit' not in r['requirement_errors']:r['requirement_errors'].append('ending_duration_over_limit')
        if any(len(b['dialogue'])>2 for b in script['beats']):r['requirement_errors'].append('too_many_dialogue_turns')
    return r

def evidence_errors(review,samples):
    lookup={s['sample_id']:s['script'] for s in samples};errors=[]
    rows=review.get('reviews',[])
    if len(rows)!=len(samples) or {r.get('sample_id') for r in rows}!=set(lookup):return ['sample_coverage']
    for row in rows:
        for i,issue in enumerate(row.get('issues',[])):
            if issue.get('severity') not in ('major','minor'):errors.append(f"{row['sample_id']}:{i}:severity")
            if not issue.get('evidence'):errors.append(f"{row['sample_id']}:{i}:missing_evidence")
            for e in issue.get('evidence',[]):
                try:
                    value=lookup[row['sample_id']]
                    for part in e['path'].split('.'):value=value[int(part)] if isinstance(value,list) else value[part]
                    if not isinstance(value,str) or not e.get('quote') or e['quote'] not in value:raise ValueError()
                except (KeyError,TypeError,IndexError,ValueError):errors.append(f"{row['sample_id']}:{i}:unverified_quote:{e.get('path')}")
    return errors

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--run-dir',type=Path,required=True);ap.add_argument('--phase',choices=['generate','review'],required=True);ap.add_argument('--round',type=int,default=0);ap.add_argument('--cases',nargs='*');a=ap.parse_args()
    run=a.run_dir.resolve();run.mkdir(parents=True,exist_ok=True);plan=read(CASES)
    if not 0<=a.round<=plan['maximum_revision_rounds']:raise RuntimeError('revision limit')
    scope={'cases':file_binding(CASES),'pack':file_binding(PACK),'maximum_remote_calls':plan['maximum_remote_calls'],'media_calls':0,'authorization':'持续更新，直接更新到可用版本'}
    if (run/'SCOPE.json').exists() and read(run/'SCOPE.json')!=scope:raise RuntimeError('scope changed')
    write(run/'SCOPE.json',scope)
    cases=[c for c in plan['cases'] if not a.cases or c['id'] in a.cases]
    if not cases:raise RuntimeError('empty selection')
    folder=run/f'round_{a.round:02}';folder.mkdir(exist_ok=True)
    if a.phase=='generate':
        for case in cases:
            dest=folder/case['id'];dest.mkdir(exist_ok=True)
            prompt=build_writer_prompt(case['prompt_modules'],pack_path=PACK)+'\n用submit_creative_json提交完整稿。'
            payload={'brief':case['brief'],'required_beat_ids':case['required_beat_ids'],'candidate_lock':{'id':'C01','title':case['label']}}
            if a.round:
                feedback=read(run/f'feedback_{a.round:02}.json')[case['id']]
                payload.update(previous_script=read(run/f"round_{feedback['previous_round']:02}"/case['id']/'script.json'),review_issues=feedback['issues'])
                prompt+='\n这是有证据的返修。保留已成立的内容，逐项解决review_issues，必要时简化或重建因果。仍提交完整稿，不输出补丁，不只改event摘要。'
            schema=deepcopy(WRITER_TOOL_SCHEMAS['writer_script']);schema['properties']['selected_candidate_id']['enum']=['C01'];bs=schema['properties']['beats'];bs.update(minItems=case['beat_count'],maxItems=case['beat_count']);bs['items']['properties']['id']['enum']=case['required_beat_ids'];bs['items']['properties']['dialogue']['maxItems']=2
            print(f"GENERATE {a.round} {case['id']}",flush=True)
            receipt=request_once(dest/'call.json','writer',[{'role':'system','content':prompt},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}],schema,plan['maximum_remote_calls'],run)
            if receipt['response_metadata'].get('finish_reason')=='length':raise RuntimeError('truncated; no automatic resend')
            try:
                result=parse_json_object(receipt['response_text']);write(dest/'script.json',result);checks=check(result,case)
                if not checks['structural_errors']:(dest/'script.md').write_text(compile_beat_screenplay(result),encoding='utf-8')
            except (ValueError,TypeError,KeyError) as e:checks={'structural_errors':[str(e)]}
            write(dest/'machine_review.json',checks);print(json.dumps({'case':case['id'],**checks},ensure_ascii=False),flush=True)
    else:
        for i in range(0,len(cases),3):
            group=cases[i:i+3];dest=folder/('review_'+'_'.join(c['id'] for c in group));dest.mkdir(exist_ok=True)
            samples=[{'sample_id':c['id'],'brief':c['brief'],'script':read(folder/c['id']/'script.json')} for c in group]
            print('REVIEW '+str(a.round)+' '+str([c['id'] for c in group]),flush=True)
            receipt=request_once(dest/'call.json','director',[{'role':'system','content':REVIEW_PROMPT},{'role':'user','content':json.dumps({'samples':samples},ensure_ascii=False)}],None,plan['maximum_remote_calls'],run)
            if receipt['response_metadata'].get('finish_reason')=='length':raise RuntimeError('review truncated')
            result=parse_json_object(receipt['response_text']);write(dest/'review.json',result);write(dest/'evidence_check.json',{'errors':evidence_errors(result,samples),'automatic_approval':False})
if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');main()
