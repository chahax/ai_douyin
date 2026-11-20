"""Run one explicit authoring stage; human/agent review is a separate action."""
from __future__ import annotations
import argparse
import json
import sys
import shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_cohort_scene_flow import model_attempt,save,read,identity,verify_file,now,context
from src.content_factory.director_pipeline import (validate_outline,replay,validate_photography,
    compile_cards,initial_state,fingerprint,CHECKS,require,fit_speech_windows)

PROMPTS=ROOT/'src/content_factory/prompts'


def author_stage(folder,prompt,payload,stage,*,temperature=1.0,thinking='disabled',max_tokens=8192,model='MiniMax-M3'):
    from src.shared.llm_client import LLMClient
    from src.trend_intelligence.cohort_scene_flow import strict_json
    folder.mkdir(exist_ok=False)
    messages=[{'role':'system','content':prompt},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}]
    save(folder/'request.json',messages)
    effective_thinking=thinking if model=='MiniMax-M3' else 'provider_default'
    record={'status':'reserved','model_calls':0,'media_calls':0,'started_at':now(),'model':model,'thinking':effective_thinking,'temperature':temperature,'max_tokens':max_tokens}
    save(folder/'run.json',record)
    extra={'reasoning_split':True}
    if model=='MiniMax-M3':extra['thinking']={'type':thinking}
    client=LLMClient(model=model,extra_body=extra,max_tokens=max_tokens,max_retries=0,timeout_seconds=600,preserve_invalid_json=True)
    require(client.provider_name!='mock','Actual text model required')
    try:
        record.update(status='running',model_calls=1);save(folder/'run.json',record)
        try:raw=client.chat_completion_tracked(messages,caller='director_pipeline_'+stage,temperature=temperature,json_mode=True,use_cache=False)
        finally:save(folder/'response.json',getattr(client.provider,'last_response_metadata',{}))
        (folder/'raw.txt').write_text(raw or '',encoding='utf-8')
        require(read(folder/'response.json').get('finish_reason')!='length','Truncated output')
        value=strict_json(raw or '');save(folder/'candidate.json',value)
        record['status']='candidate_pending_validation';return value
    except Exception as exc:
        record.update(status='failed_or_unknown',error=str(exc));raise
    finally:
        record['finished_at']=now();save(folder/'run.json',record)


def protocol():
    files=[ROOT/'src/content_factory/director_pipeline.py',Path(__file__),
           *[PROMPTS/f'director_{stage}_v2.md' for stage in ('outline','script','photography')]]
    return fingerprint([identity(p) for p in files])


def reviewed(folder,stage):
    r=read(folder/f'{stage}.review.json')
    require(r['decision']=='passed' and r['unresolved']==[], 'Actual passed review required')
    require(r['candidate']==identity(folder/stage/'candidate.json'),'Reviewed candidate changed')
    require(set(r['checks'])==set(CHECKS),'Six review checks required')
    require(all(v.get('passed') is True and v.get('evidence') and v.get('finding') for v in r['checks'].values()),'Uninspected review item')
    candidate=read(verify_file(r['candidate']))
    from src.trend_intelligence.cohort_scene_flow import strict_json
    authored=strict_json((folder/stage/'raw.txt').read_text(encoding='utf-8'))
    if (folder/stage/'timing_projection.json').exists():
        require(read(folder/stage/'model_output.json')==authored,'Original authored data changed')
        expected,projection=fit_speech_windows(read(folder/'outline/candidate.json'),authored)
        require(candidate==expected and read(folder/stage/'timing_projection.json')==json.loads(json.dumps(projection)),'Timing projection cannot be replayed')
    else:require(candidate==authored,'Candidate differs from actual model output')
    require(read(folder/stage/'run.json')['model_calls']==1,'Actual model call required')
    return candidate


def streak(suite):
    consecutive=0;version=None;rows=[]
    records=sorted((read(p) for p in suite.glob('*/trial.json')),key=lambda r:r['started_at'])
    for r in records:
        if r['protocol']!=version:consecutive=0;version=r['protocol']
        if r['status']=='accepted_text_only':
            folder=suite/r['id']
            review=read(folder/'final.review.json')
            for item in review['artifacts'].values():verify_file(item)
            for stage in ('outline','script_a','script_b','photography'):reviewed(folder,stage)
            consecutive+=1
        else:consecutive=0
        rows.append({'id':r['id'],'status':r['status'],'consecutive':consecutive,'protocol':r['protocol']})
    result={'criterion_met':consecutive>=3,'consecutive_passes':consecutive,'trials':rows,'updated_at':now(),'media_calls':0}
    save(suite/'results.json',result)
    return result


def run(args):
    suite=Path(args.suite).resolve()
    if args.stage=='prepare':
        suite.mkdir(parents=True,exist_ok=False)
        old=read(ROOT/'data/qa/cohort_flow_upgrade_20260913/short_trial_r8/run.json')
        compact,allowed,cards,bindings=context(Path(old['trial_dir']),Path(old['summary']['path']).parent,old['summary_review']['path'])
        # Full evidence remains bound on disk; send only concise mechanisms, never old topic instructions.
        payload={'source_overview':[{'source_id':s['source_id'],'core':s['core']['text']} for s in compact['all_20_core_analyses']],
          'reference_evidence':{sid:[e for e in es if e['id'] in ('V0001','V0007','V0009','A0001','A0005')] for sid,es in compact['allowed_reference_evidence'].items()},
          'scope':'来源仅供借鉴表达；本轮原创生活冲突，不沿用旧押金剧情，不宣称法律效果。'}
        save(suite/'sources.json',{'payload':payload,'allowed':{sid:list(es) for sid,es in allowed.items()},'bindings':bindings,'full_context':compact})
        save(suite/'suite.json',{'started_at':now(),'sources':identity(suite/'sources.json'),'criterion':'same protocol, three consecutive independent full text approvals; any rejection resets streak','media_calls':0})
        return
    info=read(suite/'suite.json');sources=read(verify_file(info['sources']))
    folder=suite/args.trial
    if args.stage=='adopt_outline':
        origin=Path(args.origin).resolve()
        require(origin.is_relative_to(suite) and origin.name=='outline','Only a completed outline in this suite can be adopted')
        prior=read(origin/'candidate.json')
        from src.trend_intelligence.cohort_scene_flow import strict_json
        require(prior==strict_json((origin/'raw.txt').read_text(encoding='utf-8')),'Source differs from original model text')
        require(read(origin/'request.json')[0]['content']==(PROMPTS/'director_outline_v2.md').read_text(encoding='utf-8'),'Generation prompt changed; author afresh')
        source_trial=read(origin.parent/'trial.json')
        require(source_trial['sources']==info['sources'],'Different research binding')
        validate_outline(prior,sources['allowed'])
        folder.mkdir(exist_ok=False);(folder/'outline').mkdir()
        for name in ('candidate.json','raw.txt','request.json','response.json','run.json'):
            shutil.copy2(origin/name,folder/'outline'/name)
        save(folder/'outline/origin.json',{'method':'revalidate_original_model_output_after_harness_fix','new_model_calls':0,'files':{name:identity(origin/name) for name in ('candidate.json','raw.txt','request.json','response.json','run.json')}})
        save(folder/'trial.json',{'id':args.trial,'started_at':now(),'brief':source_trial['brief'],'protocol':protocol(),'sources':info['sources'],'status':'in_progress','media_calls':0,'outline_origin':identity(origin/'candidate.json')})
        save(folder/'outline/validation.json',{'status':'structure_valid_semantics_pending','at':now(),'candidate':identity(folder/'outline/candidate.json')})
        source_trial.update(status='superseded_for_revalidation',revalidated_as=args.trial);save(origin.parent/'trial.json',source_trial)
        return
    if args.stage=='finalize':
        r=read(folder/'trial.json');require(r['status']=='in_progress' and r['protocol']==protocol(),'Invalid trial status/protocol')
        final=read(folder/'final.review.json')
        require(final['decision']=='passed' and final['unresolved']==[] and set(final['checks'])==set(CHECKS),'Actual final review required')
        require(all(v.get('passed') is True and v.get('evidence') and v.get('finding') for v in final['checks'].values()),'Final review incomplete')
        expected={'outline':folder/'outline/candidate.json','script':folder/'script.json','photography':folder/'photography/candidate.json','delivery':folder/'delivery/SCREENPLAY.md'}
        require(final['artifacts']=={k:identity(v) for k,v in expected.items()},'Final review bindings changed')
        outline=reviewed(folder,'outline');first=reviewed(folder,'script_a');second=reviewed(folder,'script_b');photo=reviewed(folder,'photography')
        script={'shots':first['shots']+second['shots']}
        require(read(folder/'script.json')==script,'Final script differs from reviewed author outputs')
        from scripts.build_director_workbench import node
        for card in compile_cards(outline,script,photo):
            prompt,_=node.compile_card(card)
            require((folder/'delivery'/card['shot_id']/'prompt.txt').read_text(encoding='utf-8')==prompt,'Compiled prompt changed')
        r.update(status='accepted_text_only',reviewed_at=now());save(folder/'trial.json',r)
        print(json.dumps(streak(suite),ensure_ascii=False,indent=2));return
    if args.stage=='outline':
        folder.mkdir(exist_ok=False)
        save(folder/'trial.json',{'id':args.trial,'started_at':now(),'brief':args.brief,'protocol':protocol(),'sources':info['sources'],'status':'in_progress','media_calls':0})
        payload={**sources['payload'],'test_brief':args.brief}
    else:
        record=read(folder/'trial.json');require(record['protocol']==protocol(),'Protocol changed: start a new trial')
        require(record['status']=='in_progress','Trial already closed')
        outline=reviewed(folder,'outline')
        if args.stage in ('script_a','script_b'):
            all_ids=[e['id'] for e in outline['events']];split=(len(all_ids)+1)//2
            if args.stage=='script_a':ids=all_ids[:split];initial=initial_state(outline)
            else:
                first=reviewed(folder,'script_a');initial=replay(outline,first,ids=all_ids[:split])[-1]['after'];ids=all_ids[split:]
            payload={'outline':outline,'requested_shots':ids,'initial':initial,'review_findings':read(folder/'outline.review.json')['checks']}
            if args.stage=='script_b':payload['previous_shots']=first
        else:
            first=reviewed(folder,'script_a');second=reviewed(folder,'script_b')
            script={'shots':first['shots']+second['shots']}
            trace=replay(outline,script)
            save(folder/'script.json',script);save(folder/'trace.json',trace)
            if args.stage=='export':
                photography=reviewed(folder,'photography')
                from scripts.build_director_workbench import export
                output=folder/'delivery';output.mkdir(exist_ok=False)
                lines=['# '+outline['title'],'',outline['logline'],'',f"{sum(e['duration'] for e in outline['events'])}秒，文本审核候选；未生成视频。",'']
                for card in compile_cards(outline,script,photography):
                    export(card,output/card['shot_id'])
                    lines += ['## '+card['shot_id'],card['story_lock'],'','**动作**：'+card['beats'],'','**表演**：'+card['performance'],'','**摄影**：'+card['composition']+' '+card['camera'],'','**声音**：'+card['audio'],'']
                (output/'SCREENPLAY.md').write_text('\n'.join(lines),encoding='utf-8')
                return
            # The event outline is intent, not executable blocking. Photography must
            # not resurrect movements already simplified during actual script review.
            setup={k:outline[k] for k in ('scene','characters','props','locations','state')}
            setup['events']=[{k:e[k] for k in ('id','duration')} for e in outline['events']]
            payload={'outline':setup,'script':{'shots':[{k:v for k,v in s.items() if k!='emotion'} for s in script['shots']]},'trace':trace}
    stage='script' if args.stage.startswith('script_') else args.stage
    prompt=(PROMPTS/f'director_{stage}_v2.md').read_text(encoding='utf-8')
    try:
        candidate=author_stage(folder/args.stage,prompt,payload,args.stage)
        if stage=='outline':validate_outline(candidate,sources['allowed'])
        elif stage=='script':
            save(folder/args.stage/'model_output.json',candidate)
            candidate,projection=fit_speech_windows(outline,candidate)
            save(folder/args.stage/'candidate.json',candidate);save(folder/args.stage/'timing_projection.json',projection)
            replay(outline,candidate,initial,ids)
        else:validate_photography(outline,candidate)
        save(folder/args.stage/'validation.json',{'status':'structure_valid_semantics_pending','at':now(),'candidate':identity(folder/args.stage/'candidate.json')})
    except Exception as exc:
        save(folder/args.stage/'validation.json',{'status':'rejected','at':now(),'error':str(exc)})
        record=read(folder/'trial.json');record.update(status='rejected',failed_stage=args.stage,error=str(exc));save(folder/'trial.json',record)
        raise
    print(str(folder/args.stage/'candidate.json'))


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage',choices=('prepare','outline','adopt_outline','script_a','script_b','photography','export','finalize'))
    p.add_argument('--suite',required=True);p.add_argument('--trial');p.add_argument('--brief');p.add_argument('--origin')
    run(p.parse_args())
