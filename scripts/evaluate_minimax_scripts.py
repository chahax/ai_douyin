"""Bounded paired script evaluation. Raw responses are immutable; no video API."""
from __future__ import annotations
import argparse,json,hashlib,sys
from copy import deepcopy
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.content_factory.creative_workflow_contract import PROMPTS,WRITER_TOOL_SCHEMAS,parse_json_object,compile_beat_screenplay,validate_script
from src.content_factory.creative_workflow_roles import CreativeRoleClients
from src.content_factory.creative_writer_prompt_pack import build_writer_prompt,PACK
from src.content_factory.creative_workflow_inputs import file_binding
from src.content_factory.reusable_production import read,write,digest
CASES=ROOT/'config/minimax_script_eval_cases_20260927.json'

def structural_errors(value,case):
    errors=[]
    if not isinstance(value,dict):return ['root_not_object']
    keys=set(WRITER_TOOL_SCHEMAS['writer_script']['properties'])
    if set(value)!=keys:errors.append('top_level_keys')
    if not all(isinstance(value.get(k),str) and value[k].strip() for k in ('title','premise','selected_candidate_id')):errors.append('required_text')
    if value.get('selected_candidate_id')!='C01':errors.append('candidate_id')
    if type(value.get('duration_seconds')) is not int:errors.append('duration_type')
    beats=value.get('beats')
    if not isinstance(beats,list):return errors+['beats_not_array']
    if [b.get('id') if isinstance(b,dict) else None for b in beats]!=case['required_beat_ids']:errors.append('beat_coverage_or_order')
    for i,b in enumerate(beats):
        if not isinstance(b,dict):errors.append(f'beat_{i}_not_object');continue
        if set(b)!=set(WRITER_TOOL_SCHEMAS['writer_script']['properties']['beats']['items']['properties']):errors.append(f'beat_{i}_keys')
        if type(b.get('duration_seconds')) is not int or b['duration_seconds']<=0:errors.append(f'beat_{i}_duration')
        if not all(isinstance(b.get(k),str) and b[k].strip() for k in ('id','event','trigger','before','during','after')):errors.append(f'beat_{i}_text')
        if not isinstance(b.get('dialogue'),list):errors.append(f'beat_{i}_dialogue_type');continue
        for line in b['dialogue']:
            if not isinstance(line,dict) or set(line)!={'speaker','text'} or not all(isinstance(line.get(k),str) and line[k].strip() for k in ('speaker','text')):errors.append(f'beat_{i}_dialogue_line')
    return errors

def machine_review(value,case):
    errors=structural_errors(value,case)
    result={'structural_errors':errors,'contract_error':None,'requirement_errors':[]}
    if errors:return result
    duration=sum(b['duration_seconds'] for b in value['beats'])
    result['actual_duration_seconds']=duration
    if duration!=value['duration_seconds']:result['requirement_errors'].append('declared_duration_not_sum')
    if not case['brief']['duration_seconds'][0]<=duration<=case['brief']['duration_seconds'][1]:result['requirement_errors'].append('duration_outside_brief')
    if 'silent' in case['prompt_modules'] and any(b['dialogue'] for b in value['beats']):result['requirement_errors'].append('silent_case_has_dialogue')
    if case['id'] in ('C01','C02') and value['beats'][-1]['duration_seconds']>({'C01':12,'C02':10}[case['id']]):result['requirement_errors'].append('ending_duration_over_limit')
    script=deepcopy(value);script['screenplay_markdown']=compile_beat_screenplay(value)
    try:validate_script(script,'C01','','original')
    except (ValueError,KeyError,TypeError) as exc:result['contract_error']=str(exc)
    return result

def request_once(path,role,messages,schema,cap,run,*,thinking="disabled",max_tokens=6000,writer_model=None,temperature=0.2):
    req={'role_route':role,'messages':messages,'schema':schema,'temperature':temperature,'max_tokens':max_tokens,'thinking':thinking}
    if writer_model is not None:req['writer_model']=writer_model
    if path.exists():
        record=read(path)
        if record['request']!=req:raise RuntimeError('请求改变，不允许复用该回执: '+str(path))
        if record['status']!='response_received':raise RuntimeError('已有失败或未决请求，不自动重发: '+str(path))
        return record
    if len(list(run.glob('**/call.json')))>=cap:raise RuntimeError('达到本试验总调用上限')
    record={'status':'pending_response','request':req,'started_at':datetime.now(timezone.utc).isoformat()};write(path,record)
    try:r=CreativeRoleClients().call(role,messages,max_tokens=max_tokens,temperature=temperature,thinking=thinking,structured_schema=schema,**({'writer_model':writer_model} if writer_model else {}))
    except Exception as exc:record.update(status='failed_or_uncertain',error=str(exc));write(path,record);raise
    record.update(status='response_received',response_text=r.text,response_metadata=r.metadata);write(path,record)
    return record

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--run-dir',type=Path,required=True);ap.add_argument('--phase',choices=['generate','review'],required=True);args=ap.parse_args()
    run=args.run_dir.resolve();run.mkdir(parents=True,exist_ok=True)
    cases=read(CASES);plan=cases['evaluation_plan']
    binding={'schema':'paired_script_eval_scope/v1','authorization':'生成多个不同的需求测试minimax生成的剧本质量和错误率，是否需要扩展提示词模块和内容','cases':file_binding(CASES),'modules':file_binding(PACK),'baseline_prompt_sha256':digest(PROMPTS['writer_script']),'plan':plan,'media_submit':False,'production_default_changed':False}
    if (run/'SCOPE.json').exists() and read(run/'SCOPE.json')!=binding:raise RuntimeError('实验计划已改变')
    write(run/'SCOPE.json',binding)
    if args.phase=='generate':
        outcomes=[]
        for ci,case in enumerate(cases['cases']):
            # Alternate order to reduce a simple first/second-arm timing confound.
            arms=plan['arms'] if ci%2==0 else list(reversed(plan['arms']))
            for arm in arms:
                folder=run/arm/case['id'];folder.mkdir(parents=True,exist_ok=True)
                brief=case['brief'];prompt=PROMPTS['writer_script'] if arm=='baseline' else build_writer_prompt(case['prompt_modules'])
                prompt+='\n本次是原创简报测试，required_beat_ids和brief是本次要求，不套用其他故事的例子。调用submit_creative_json提交。'
                payload={'brief':brief,'creative_brief':brief,'required_beat_ids':case['required_beat_ids'],'candidate_lock':{'id':'C01','title':case['label'],'duration_seconds':sum(brief['duration_seconds'])//2,'aftermath':brief['ending']},'creative_focus':json.dumps(brief,ensure_ascii=False),'materials':{'source_driver':'original','story_source':json.dumps(brief,ensure_ascii=False)},'selected_source':{'text':json.dumps(brief,ensure_ascii=False)}}
                schema=deepcopy(WRITER_TOOL_SCHEMAS['writer_script']);schema['properties']['beats'].update(minItems=case['beat_count'],maxItems=case['beat_count'])
                print('GENERATE '+arm+' '+case['id'],flush=True)
                record=request_once(folder/'call.json','writer',[{'role':'system','content':prompt},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}],schema,14,run)
                try:
                    if record['response_metadata'].get('finish_reason')=='length':raise ValueError('provider_output_truncated')
                    output=parse_json_object(record['response_text']);write(folder/'script.json',output)
                    evaluation=machine_review(output,case)
                    if not evaluation['structural_errors']:(folder/'script.md').write_text(compile_beat_screenplay(output),encoding='utf-8')
                except (ValueError,KeyError,TypeError) as exc:evaluation={'structural_errors':[str(exc)],'contract_error':None,'requirement_errors':[]}
                write(folder/'machine_review.json',evaluation)
                outcomes.append({'arm':arm,'case_id':case['id'],**evaluation,'receipt':file_binding(folder/'call.json')})
                print(json.dumps({'arm':arm,'case':case['id'],**evaluation},ensure_ascii=False),flush=True)
        write(run/'MACHINE_RESULTS.json',outcomes)
    else:
        # Two balanced blind batches. Variant names and machine findings are withheld.
        for batch in range(2):
            samples=[];mapping={}
            for i,case in enumerate(cases['cases']):
                arm=plan['arms'][(i+batch)%2];label=f'S{batch+1}{i+1:02}'
                folder=run/arm/case['id'];script=read(folder/'script.json')
                samples.append({'sample_id':label,'brief':case['brief'],'script':script})
                mapping[label]={'arm':arm,'case_id':case['id'],'script':file_binding(folder/'script.json')}
            folder=run/f'blind_review_{batch+1}';folder.mkdir(exist_ok=True)
            write(folder/'mapping.json',mapping)
            prompt='''你是独立短片剧本审查员。评审六份匿名样本，不知它们的提示词版本。不改写正文，不猜测作者模型，不用模糊自评分代替证据。
按brief逐份检查因果动机、信息推进、人物关系、对白自然度、结尾、物理道具连续性及要求遵守。播放顺序固定为before→首句dialogue→during→其余dialogue→after，零对白则before→during→after；指出具体时序矛盾，但不要把明确无声嘴唇动作、持续动作的可定格姿态或正常短暂停顿自动判错。剧本节拍不是视频单镜，不能用视频15秒限制判长节拍错误。
每份给quality字段0到4的因果、情绪、对白（无对白用null）、结尾评分，仅作参考。issues只列实际可定位问题，含location/evidence/impact/severity(major或minor)/category(causality,timing,props,space,requirements,dialogue,ending)。没有足够证据的不猜测；不因创意与偏好不同判major；不同问题不要重复列。不能宣称视频或声音已经合格。
只输出JSON：{"reviews":[{"sample_id":"输入ID","quality":{"causality":0,"emotion":0,"dialogue":null,"ending":0},"issues":[],"strength":"一句具体优点"}]}。完整覆盖全部六份，不遗漏。'''
            print('REVIEW '+str(batch+1),flush=True)
            receipt=request_once(folder/'call.json','director',[{'role':'system','content':prompt},{'role':'user','content':json.dumps({'samples':samples},ensure_ascii=False)}],None,14,run)
            review=parse_json_object(receipt['response_text'])
            if {r.get('sample_id') for r in review.get('reviews',[])}!=set(mapping) or len(review['reviews'])!=6:raise ValueError('盲审样本缺失或重复')
            write(folder/'review.json',review)
            print('REVIEW RECEIVED '+str(batch+1),flush=True)
if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
