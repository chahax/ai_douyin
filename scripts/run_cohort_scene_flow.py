"""Cohort v2: reviewed contract -> bounded scene authoring -> actual review.

No old failed screenplay in generation context; no media submission capability.
"""
import argparse,json,sys,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.run_narrative_workflow import new_output,now,save
from src.trend_intelligence.narrative_workflow import identity,read,verify_file
from src.trend_intelligence.cohort_scene_flow import FlowError,strict_json,signature,replay,scene_request,validate_lines,render,apply_plan_replacements
from src.trend_intelligence.cohort_scene_flow import fit_dialogue_timing
from src.trend_intelligence.cohort_scene_flow import apply_direction_revision,check_direction_quotes

PLAN_CHECKS=('causal_chain','physical_actions','emotional_arc','legal_bounds','reference_fit','version_value')

def require_actual_review(path,candidate,checks):
    review=read(path)
    if review.get('decision')!='passed' or review.get('candidate')!=identity(candidate) or review.get('unresolved')!=[]:
        raise ValueError('Actual review of this exact candidate required')
    if set(review.get('checks',{}))!=set(checks):raise ValueError('Missing actual review checks')
    for key,row in review['checks'].items():
        if row.get('passed') is not True or not row.get('finding') or not row.get('evidence'):
            raise ValueError('Unchecked item: '+key)
    from datetime import datetime,timedelta
    if datetime.fromisoformat(review['reviewed_at_bjt']).utcoffset()!=timedelta(hours=8):raise ValueError('Actual Beijing review timestamp required')
    return review

def model_attempt(folder,prompt,payload,caller,max_tokens=4000,model='MiniMax-M3'):
    folder.mkdir(parents=True,exist_ok=False)
    messages=[{'role':'system','content':prompt},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}]
    save(folder/'request.json',messages)
    record={'schema':'cohort_scene_attempt/v2','started_at_bjt':now(),'input_sha256':signature({'prompt':prompt,'payload':payload}),
        'status':'running','model_calls':0,'media_calls':0,'model':model,'thinking':'disabled' if model=='MiniMax-M3' else 'provider_default'}
    save(folder/'run.json',record)
    from src.shared.llm_client import LLMClient
    extra={'thinking':{'type':'disabled'},'reasoning_split':True} if model=='MiniMax-M3' else None
    client=LLMClient(model=model,extra_body=extra,max_tokens=max_tokens,max_retries=0,timeout_seconds=300,preserve_invalid_json=True)
    try:
        if client.provider_name=='mock':raise ValueError('Real project model required')
        record['model_calls']=1;save(folder/'run.json',record)
        try:raw=client.chat_completion_tracked(messages,caller=caller,temperature=.2,json_mode=True,use_cache=False)
        finally:save(folder/'response.json',getattr(client.provider,'last_response_metadata',{}))
        (folder/'raw.txt').write_text(raw or '',encoding='utf-8')
        if read(folder/'response.json').get('finish_reason')=='length':raise FlowError('truncated','Response truncated','format')
        value=strict_json(raw or '')
        save(folder/'candidate.json',value)
        record['status']='parsed_pending_validation'
        return value
    except Exception as exc:
        record.update(status='rejected',error=exc.report() if isinstance(exc,FlowError) else {'message':str(exc),'repair_stage':'transport'})
        raise
    finally:
        record['finished_at_bjt']=now();save(folder/'run.json',record)

def record_validation(folder,error=None):
    run=read(folder/'run.json');run['status']='rejected' if error else 'structurally_valid_pending_actual_review'
    if error:run['error']=error.report() if isinstance(error,FlowError) else {'message':str(error),'repair_stage':'contract'}
    save(folder/'run.json',run)

def context(trial,summary,review_path):
    from scripts.run_cohort_expression_trial import prepare,reviewed_summary_text
    payload,bindings,gate=prepare(trial)
    summary_run=read(summary/'run.json');review=read(review_path)
    if summary_run['status']!='candidate_pending_review' or summary_run['stage']!='summary':raise ValueError('Completed cohort summary required')
    for binding in summary_run['artifacts'].values():verify_file(binding)
    if review.get('decision')!='approved_for_trial' or review.get('candidate')!=identity(summary/'result.md') or review.get('unresolved'):
        raise ValueError('Summary not actually reviewed')
    if signature(read(verify_file(summary_run['cohort_cards'])))!=signature(payload):raise ValueError('Cohort changed')
    selected=review['selected_source_ids']
    if not selected or not set(selected)<={s['source_id'] for s in payload['sources']}:raise ValueError('Unknown source selection')
    allowed={s['source_id']:{e['id']:e for e in s['expression_analysis']['evidence']} for s in payload['sources'] if s['source_id'] in selected}
    compact={'approved_direction':reviewed_summary_text((summary/'result.md').read_text(encoding='utf-8'),review),
        'all_20_core_analyses':[{'source_id':s['source_id'],'core':s['expression_analysis']['core_message'],'modes':s['expression_analysis']['expression_modes']} for s in payload['sources']],
        'type_comparison':payload['type_comparison'],'account_positioning':payload['account_positioning'],
        'actual_review_findings':review.get('checked_evidence',[]),'constraints':review.get('author_constraints',[]),
        'allowed_reference_evidence':{sid:[{'id':e['id'],'start':e['start_seconds'],'end':e['end_seconds'],'text':e['text']} for e in es.values()] for sid,es in allowed.items()}}
    return compact,allowed,payload,bindings

def create_plan(trial_dir,summary_run,review_path,kind,output_dir,feedback_file=None,model='MiniMax-M3'):
    trial=Path(trial_dir).resolve();summary=Path(summary_run).resolve();out=new_output(output_dir)
    run={'schema':'cohort_scene_workflow/v2','status':'planning','kind':kind,'started_at_bjt':now(),
        'trial_dir':str(trial),'summary':identity(summary/'run.json'),'summary_review':identity(review_path),
        'model_calls':0,'media_calls':0,'model':model,'artifacts':{}}
    save(out/'run.json',run)
    try:
        compact,allowed,cards,bindings=context(trial,summary,review_path)
        save(out/'cohort_cards.json',cards);save(out/'allowed_evidence.json',allowed)
        run['cohort_cards']=identity(out/'cohort_cards.json');run['observations']=bindings
        # Every selected source remains available on disk; planner receives only
        # evidence explicitly used by the reviewed transfer (no giant transcripts).
        compact['allowed_reference_evidence']={sid:[e for e in es if e['id'] in {'V0001','V0007','V0009','V0010','A0001','A0005','A0010','A0011','A0026','A0024'}] for sid,es in compact['allowed_reference_evidence'].items()}
        compact['kind']=kind
        if feedback_file:
            compact['actual_plan_review_feedback']=Path(feedback_file).read_text(encoding='utf-8-sig')
            run['feedback']=identity(feedback_file)
        prompt=(ROOT/'src/trend_intelligence/prompts/cohort_event_contract_v2.md').read_text(encoding='utf-8')
        feedback=None
        for index in range(1,3):
            attempt=out/f'plan_attempt_{index:02d}'
            request=dict(compact)
            if feedback:request['previous_failure']=feedback
            try:
                candidate=model_attempt(attempt,prompt,request,'cohort_event_contract',6000,model)
                if candidate.get('kind')!=kind:raise FlowError('kind','Requested kind changed')
                trace=replay(candidate,allowed)
                save(out/'contract.json',candidate);save(out/'trace.json',trace)
                record_validation(attempt)
                run.update(status='contract_pending_actual_review',contract=identity(out/'contract.json'),trace=identity(out/'trace.json'))
                break
            except Exception as exc:
                if (attempt/'run.json').exists():record_validation(attempt,exc)
                feedback={'error':str(exc),'scope':'只修当前事件规划；没有对白稿可回填。不要改变已审选题和来源。'}
                if (attempt/'raw.txt').exists():feedback['previous_plan']=(attempt/'raw.txt').read_text(encoding='utf-8')
                run['status']='contract_rejected';run['error']=str(exc)
            finally:
                if (attempt/'run.json').exists():run['model_calls']+=read(attempt/'run.json')['model_calls']
                save(out/'run.json',run)
        return out
    finally:
        run['updated_at_bjt']=now();save(out/'run.json',run)

DIALOGUE_PROMPT='''你是项目编剧，只写当前一个已审事件段的实际现场对白。返回严格JSON：{"lines":[{"speaker":"输入允许的角色ID","text":"真实台词"}]}。1至3句，不要其他键。不要写动作、时间、解释、引用或对白中的括号。动作已由事件链确定，付款/收款及物件归属不能改；对白不能提前宣布尚未发生的结果。台词数字用汉字。按提供字数范围写，话要短、硬、有具体对抗和情绪触发，不是法律知识问答。不要重复该段动作说明，不添加法条、警方、旁白、外援、虚假日期不可更改保证或新金额。现场问题和新事实决定人物说什么，不能每段都改写成“你看—好的”。'''


def dialogue_projection(request,contract,row):
    visible={k:v for k,v in contract['facts'].items() if row['after']['shown_in_scene'].get(k) or (v['kind']=='agreement' and row['after']['confirmed'].get(k))}
    scoped={k:v for k,v in request.items() if k not in ('goal','facts','transactions')}
    scoped['facts']=visible
    scoped['props']={k:dict(v,location=row['after']['props'][k]) for k,v in contract['props'].items()}
    scoped['continuity_contract']={
        'only_existing_props':{k:v['name'] for k,v in contract['props'].items()},
        'planned_prop_destinations':contract['terminal']['props'],
        'rules':['台词不得新增清单、单据、聊天或其他证据；当前facts没有的证据不可提前透露。',
                 '不要求对白重复动作；如提到交接承诺，去向必须与planned_prop_destinations一致。',
                 '当前未到账不能说到账；只有提交不等于到账。只推进当前intent。',
                 '不要替对方提前承认后段才核实的事实，不提前和解。',
                 '现场短促回应可以有情绪余波；不要凭空加入法律结论或知识总结。',
                 '信息揭示顺序：扣款、索赔等要求首次出现时，原则上由提出要求者先说清金额与理由，对方再反驳。若金额由对方先提，必须有观众已看见或听见的明确铺垫；角色知道不等于观众知道。不得为此发明新金额。']}
    return scoped


def select_reviewed_scene(workflow,beat_id,review_path):
    """Reuse a real earlier response only after explicit content review; no edits."""
    folder=Path(workflow).resolve();run=read(folder/'run.json');review=read(review_path)
    candidate_path=verify_file(review['candidate'])
    beat_dir=folder/'beats'/beat_id
    if candidate_path.parent.parent!=beat_dir:raise ValueError('Candidate must belong to this beat')
    require_actual_review(review_path,candidate_path,('physical_actions','causal_chain','emotional_delivery'))
    contract=read(verify_file(run['contract']));trace=replay(contract)
    row=next(r for r in trace['beats'] if r['beat']['id']==beat_id)
    request_key=signature(scene_request(contract,row));attempt=read(candidate_path.parent/'run.json')
    if attempt.get('scene_request_sha256')!=request_key:raise ValueError('Old response belongs to a different event input')
    checked=validate_lines(read(candidate_path),contract,row,strict_timing=False)
    selected=beat_dir/'selected.json'
    if selected.exists():
        history=beat_dir/'selection_history';history.mkdir(exist_ok=True)
        saved=read(selected);dest=history/f'{signature(saved)}.json'
        if not dest.exists():save(dest,saved)
    save(selected,{'request_sha256':request_key,'candidate':identity(candidate_path),'scene_review':identity(review_path),
                   'status':'content_reviewed_pending_whole_schedule','timing':checked})
    run.update(status='dialogue_rejected',updated_at_bjt=now());save(folder/'run.json',run)

def write_scenes(workflow,review_path,beat_id=None,feedback_file=None):
    folder=Path(workflow).resolve();run=read(folder/'run.json')
    if run['status'] not in ('contract_pending_actual_review','dialogue_rejected','dialogue_pending_actual_review','ready_for_user_review'):raise ValueError('No completed event contract')
    if feedback_file and not beat_id:raise ValueError('Actual dialogue correction must target one beat')
    correction=Path(feedback_file).read_text(encoding='utf-8-sig') if feedback_file else None
    forbidden=[]
    if feedback_file and Path(feedback_file).suffix=='.json':
        correction_doc=read(feedback_file);forbidden=correction_doc.get('forbidden_phrases',[])
        if not isinstance(forbidden,list) or any(not isinstance(x,str) or not x for x in forbidden):raise ValueError('Invalid reviewer forbidden phrases')
    correction_binding=identity(feedback_file) if feedback_file else None
    verify_file(run['contract']);verify_file(run['trace']);verify_file(run['cohort_cards'])
    require_actual_review(review_path,folder/'contract.json',PLAN_CHECKS)
    _,allowed,cards,_=context(Path(run['trial_dir']),Path(run['summary']['path']).parent,run['summary_review']['path'])
    verify_file(run['summary']);verify_file(run['summary_review'])
    if signature(cards)!=signature(read(folder/'cohort_cards.json')):raise ValueError('Source evidence changed')
    contract=read(folder/'contract.json');trace=replay(contract,allowed)
    results=[];failures=[];calls=0
    for row in trace['beats']:
        b=row['beat'];beat_dir=folder/'beats'/b['id'];beat_dir.mkdir(parents=True,exist_ok=True)
        request=scene_request(contract,row);request_key=signature(request)
        accepted=beat_dir/'selected.json'
        if accepted.exists():
            saved=read(accepted)
            if saved.get('status')=='rejected_by_actual_review' and not (correction and b['id']==beat_id):
                failures.append({'beat_id':b['id'],'reason':'actual_rejection_requires_targeted_correction'});continue
            if correction and b['id']==beat_id:
                history=beat_dir/'selection_history';history.mkdir(exist_ok=True)
                archive=history/f'{signature(saved)}.json'
                if not archive.exists():save(archive,saved)
                save(accepted,dict(saved,status='rejected_by_actual_review',rejection=correction_binding))
            elif saved['request_sha256']==request_key:
                candidate=read(verify_file(saved['candidate']));validate_lines(candidate,contract,row,strict_timing=False);results.append(candidate);continue
        if beat_id and b['id']!=beat_id:
            failures.append({'beat_id':b['id'],'reason':'not_generated'});continue
        if not b['speakers']:
            candidate={'lines':[]};validate_lines(candidate,contract,row)
            silent=beat_dir/f'silent_{request_key[:16]}.json'
            if not silent.exists():save(silent,candidate)
            save(accepted,{'request_sha256':request_key,'candidate':identity(silent),'contract_review':identity(review_path),
                'status':'model_planned_action_only','model_calls':0})
            results.append(candidate);continue
        available=row['duration']-row['minimum_action_seconds']-b['pause']
        request['required_total_spoken_characters_excluding_punctuation']=[math.ceil(available*4.3),math.floor(available*5.7)]
        if correction:request['actual_scene_review_correction']=correction
        old=list(beat_dir.glob('attempt_*/run.json'))
        same=[p for p in old if read(p).get('scene_request_sha256')==request_key and read(p).get('correction')==correction_binding]
        remaining=max(0,2-len(same));feedback=None;success=False
        for retry in range(remaining):
            attempt=beat_dir/f'attempt_{len(old)+retry+1:03d}'
            attempt_request=dict(request)
            if feedback:attempt_request['correction']=feedback
            try:
                # Full state stays in the local cache key; the author receives only
                # facts already made visible, preventing later revelations leaking early.
                scoped=dialogue_projection(attempt_request,contract,row)
                lo,hi=request['required_total_spoken_characters_excluding_punctuation']
                prompt=DIALOGUE_PROMPT+f'\n本次所有text合计必须为{lo}至{hi}个实际发音汉字（不含标点和空格），不是每句这个长度。优先一句，最多两句。绝不能提前揭露后段证据或提前同意退款。只完成当前intent；已知事实也不必全部说出。写完自行逐字计数，超出即缩短，不要输出计数。'
                if correction:prompt+='\n实际审核修正优先于原规划中的旧措辞，但不改变已冻结动作和金额：'+correction
                candidate=model_attempt(attempt,prompt,scoped,'cohort_scene_dialogue',1200,run.get('model','MiniMax-M3'))
                if any(x in d.get('text','') for x in forbidden for d in candidate.get('lines',[])):
                    raise FlowError('repeated_actual_rejection','Dialogue repeats a phrase explicitly rejected by actual review','dialogue',b['id'])
                checked=validate_lines(candidate,contract,row,strict_timing=False)
                record_validation(attempt)
                save(accepted,{'request_sha256':request_key,'candidate':identity(attempt/'candidate.json'),'contract_review':identity(review_path),
                    'correction':correction_binding,'timing':checked,'status':'structurally_valid_pending_actual_review'})
                results.append(candidate);success=True;break
            except Exception as exc:
                if (attempt/'run.json').exists():record_validation(attempt,exc)
                feedback={'reason':str(exc),'scope':'只改本段对白，不重写其他段或事件链。'}
                if (attempt/'raw.txt').exists():feedback['previous_lines']=(attempt/'raw.txt').read_text(encoding='utf-8')
            finally:
                if (attempt/'run.json').exists():
                    ar=read(attempt/'run.json');ar.update(scene_request_sha256=request_key,correction=correction_binding);save(attempt/'run.json',ar);calls+=ar['model_calls']
            print(f'{b["id"]}: {"valid" if success else "needs revision"}',flush=True)
        if not success:failures.append({'beat_id':b['id'],'reason':feedback or 'bounded_attempts_exhausted','repair_stage':'dialogue'})
    run['model_calls']+=calls;run['contract_review']=identity(review_path);run['failures']=failures
    if failures:run['status']='dialogue_rejected'
    else:
        if run.get('direction_revision') and read(verify_file(run['direction_revision']))['dialogue_sha256']!=signature(results):
            run.setdefault('direction_history',[]).append(run.pop('direction_revision'))
        try:
            directed=apply_direction_revision(trace,read(verify_file(run['direction_revision'])),results) if run.get('direction_revision') else trace
            scheduled=fit_dialogue_timing(contract,directed,results)
        except FlowError as exc:
            run.update(status='dialogue_rejected',failures=[exc.report()],updated_at_bjt=now());save(folder/'run.json',run);return run
        body=render(contract,scheduled,results)
        prior=run.get('artifacts',{}).get('screenplay')
        if not prior or verify_file(prior).read_text(encoding='utf-8')!=body:
            assemblies=folder/'assemblies';assemblies.mkdir(exist_ok=True)
            assembly=assemblies/f'{len(list(assemblies.iterdir()))+1:03d}';assembly.mkdir(exist_ok=False)
            (assembly/'screenplay.md').write_text(body,encoding='utf-8');save(assembly/'dialogue.json',results);save(assembly/'scheduled_trace.json',scheduled)
            run['artifacts']={'screenplay':identity(assembly/'screenplay.md'),'dialogue':identity(assembly/'dialogue.json'),'scheduled_trace':identity(assembly/'scheduled_trace.json')}
            run['status']='dialogue_pending_actual_review';run.pop('screenplay_review',None)
        elif run['status']!='ready_for_user_review':run['status']='dialogue_pending_actual_review'
    run['updated_at_bjt']=now();save(folder/'run.json',run)
    return run

def accept_screenplay(workflow,review_path):
    folder=Path(workflow).resolve();run=read(folder/'run.json')
    if run['status']!='dialogue_pending_actual_review':raise ValueError('Complete dialogue candidate required')
    candidate=verify_file(run['artifacts']['screenplay']);dialogue=read(verify_file(run['artifacts']['dialogue']))
    _,allowed,cards,_=context(Path(run['trial_dir']),Path(run['summary']['path']).parent,run['summary_review']['path'])
    verify_file(run['summary']);verify_file(run['summary_review'])
    if signature(cards)!=signature(read(verify_file(run['cohort_cards']))):raise ValueError('Source evidence changed')
    contract=read(verify_file(run['contract']));trace=replay(contract,allowed)
    if signature(trace)!=signature(read(verify_file(run['trace']))):raise ValueError('Event trace changed; actual contract review must be renewed')
    if run.get('direction_revision'):trace=apply_direction_revision(trace,read(verify_file(run['direction_revision'])),dialogue)
    if check_direction_quotes(trace,dialogue):raise ValueError('Direction cues refer to dialogue not actually spoken')
    trace=fit_dialogue_timing(contract,trace,dialogue)
    if signature(trace)!=signature(read(verify_file(run['artifacts']['scheduled_trace']))):raise ValueError('Dialogue schedule changed; actual screenplay review required')
    if render(contract,trace,dialogue)!=candidate.read_text(encoding='utf-8'):raise ValueError('Assembled text differs from model lines and event trace')
    checks=('dialogue_action_alignment','source_fidelity','emotional_delivery','causal_ending','physical_feasibility','legal_bounds')
    review=require_actual_review(review_path,candidate,checks)
    rows=review.get('beat_reviews',[])
    if [r.get('beat_id') for r in rows]!=[b['beat']['id'] for b in trace['beats']]:raise ValueError('Every beat must be actually reviewed')
    for r,b,scene in zip(rows,trace['beats'],dialogue,strict=True):
        if (r.get('decision')!='passed' or r.get('dialogue_quotes')!=[x['text'] for x in scene['lines']]
                or r.get('operations')!=b['beat']['ops'] or not r.get('finding')):raise ValueError('Incomplete dialogue/action review')
    if review.get('terminal_state')!=trace['terminal']:raise ValueError('Ending review must match computed terminal state')
    run.update(status='ready_for_user_review',screenplay_review=identity(review_path),updated_at_bjt=now())
    save(folder/'run.json',run);return run


def revise_direction(workflow,feedback_file):
    folder=Path(workflow).resolve();run=read(folder/'run.json')
    scenes=read(verify_file(run['artifacts']['dialogue']));contract=read(verify_file(run['contract']))
    trace=replay(contract);feedback=read(feedback_file)
    existing=read(verify_file(run['direction_revision'])) if run.get('direction_revision') else None
    prior_overrides=existing['overrides'] if existing and existing['dialogue_sha256']==signature(scenes) else {}
    if feedback['candidate']!=run['artifacts']['dialogue']:raise ValueError('Direction review must bind exact compiled dialogue')
    attempts=folder/'direction_attempts';attempts.mkdir(exist_ok=True)
    prompt='你是项目现场导演，只修最终实际对白对应的导演提示。严格JSON {"overrides":{"镜头ID":{"指定字段":"修订后的提示"}}}。只输出审核指定字段。不得改对白、道具、站位、动作链、付款结果。trigger写实际已发生的触发，不编造引号台词；emotion写能拍出来的动作、语气和反应，不写审核指令或模型提示词。'
    last=None
    for i in range(2):
        attempt=attempts/f'attempt_{len(list(attempts.iterdir()))+1:03d}'
        response=model_attempt(attempt,prompt,{'contract':contract,'current_direction_overrides':prior_overrides,'actual_dialogue':scenes,'actual_review':feedback,'previous_problem':last},'cohort_direction_alignment',1800,run.get('model','MiniMax-M3'))
        run['model_calls']+=read(attempt/'run.json')['model_calls']
        try:
            if set(response)!={'overrides'}:raise ValueError('Only overrides required')
            actual={(b,k) for b,fields in response['overrides'].items() for k in fields}
            if actual!={tuple(x) for x in feedback['targets']}:raise ValueError('Direction fields differ from actual review targets')
            merged={k:dict(v) for k,v in prior_overrides.items()}
            for k,v in response['overrides'].items():merged.setdefault(k,{}).update(v)
            revision={'dialogue_sha256':signature(scenes),'overrides':merged}
            directed=apply_direction_revision(trace,revision,scenes)
            if check_direction_quotes(directed,scenes):raise ValueError('Unspoken dialogue remains in direction cues')
            save(attempt/'revision.json',revision);record_validation(attempt)
            run.update(direction_revision=identity(attempt/'revision.json'),updated_at_bjt=now());save(folder/'run.json',run);return run
        except Exception as exc:
            record_validation(attempt,exc);last=str(exc)
            run.update(updated_at_bjt=now());save(folder/'run.json',run)
    raise ValueError('Direction revision still requires actual correction: '+str(last))

def repair_plan(workflow,feedback_file,output_dir):
    parent=Path(workflow).resolve();old=read(parent/'run.json');feedback=read(feedback_file)
    original=read(verify_file(feedback['candidate']))
    candidate_path=Path(feedback['candidate']['path']).resolve()
    is_saved_contract=candidate_path==parent/'contract.json' and feedback['candidate']==old.get('contract')
    if not is_saved_contract and candidate_path.parent.parent!=parent:raise ValueError('Review must target this workflow contract or plan attempt')
    if original.get('schema')!='cohort_event_contract/v2':raise ValueError('Review target must be an event contract, not a patch response')
    out=new_output(output_dir);run={k:v for k,v in old.items() if k not in ('contract','trace','error','artifacts','model_calls','observations','cohort_cards')}
    run.update(status='repairing_contract',started_at_bjt=now(),model_calls=0,media_calls=0,parent=identity(parent/'run.json'),feedback=identity(feedback_file),artifacts={})
    save(out/'run.json',run)
    try:
        _,allowed,cards,bindings=context(Path(old['trial_dir']),Path(old['summary']['path']).parent,old['summary_review']['path'])
        if signature(cards)!=signature(read(verify_file(old['cohort_cards']))):raise ValueError('Parent cohort changed')
        save(out/'cohort_cards.json',cards);save(out/'allowed_evidence.json',allowed)
        run['cohort_cards']=identity(out/'cohort_cards.json');run['observations']=bindings
        prompt='你是项目事件编辑。只修实际审核指定字段，返回严格JSON：{"replacements":[{"path":"审核指定的JSON指针","value":"替换后的真实类型值"}]}。每个指定路径恰好一次，不改别处，不返回全文。数组/对象必须保留真实类型。先解决占手冲突和事实因果，不发明新道具、金额或字段。字段文本由你修订，操作状态必须与其他冻结字段一致。'
        targets=[]
        for pointer in feedback['allowed_paths']:
            value=original
            parts=pointer[1:].split('/')
            for part in parts:value=value[int(part)] if isinstance(value,list) else value[part]
            targets.append({'path':pointer,'beat_id':original['beats'][int(parts[1])]['id'] if parts[0]=='beats' else None,'original_value':value})
        request={'original_model_plan':original,'actual_review':feedback,'exact_replacement_targets':targets,
            'index_rule':'JSON数组从0开始：/beats/3是B04，/beats/7是B08，/beats/8是B09。必须原样复制targets的path；不按B编号另造路径。只返回这几个路径，所有其他字段冻结。'};last=None
        for i in range(1,3):
            attempt=out/f'plan_attempt_{i:02d}'
            payload=dict(request)
            if last:payload['last_patch_problem']=last
            try:
                patch=model_attempt(attempt,prompt,payload,'cohort_plan_field_repair',4000,old.get('model','MiniMax-M3'))
                candidate=apply_plan_replacements(original,patch,feedback['allowed_paths'])
                for pointer,expected in feedback.get('required_values',{}).items():
                    value=candidate
                    for part in pointer[1:].split('/'):value=value[int(part)] if isinstance(value,list) else value[part]
                    if value!=expected:raise FlowError('review_requirement',f'{pointer} must equal actual review requirement {expected!r}; unchanged or different value is rejected')
                trace=replay(candidate,allowed);save(out/'contract.json',candidate);save(out/'trace.json',trace)
                record_validation(attempt);run.update(status='contract_pending_actual_review',contract=identity(out/'contract.json'),trace=identity(out/'trace.json'),model_patch=identity(attempt/'candidate.json'))
                break
            except Exception as exc:
                if (attempt/'run.json').exists():record_validation(attempt,exc)
                last={'error':str(exc)}
                if (attempt/'raw.txt').exists():last['previous_patch']=(attempt/'raw.txt').read_text(encoding='utf-8')
                run.update(status='contract_rejected',error=str(exc))
            finally:
                if (attempt/'run.json').exists():run['model_calls']+=read(attempt/'run.json')['model_calls']
    finally:run['updated_at_bjt']=now();save(out/'run.json',run)
    return out

def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    p=argparse.ArgumentParser();p.add_argument('--stage',choices=('plan','repair-plan','write','direction','accept'),required=True)
    for key in ('trial-dir','summary-run','summary-review','output-dir','workflow','review','beat-id','feedback-file'):p.add_argument('--'+key)
    p.add_argument('--kind',choices=('short','long'),default='short');a=p.parse_args()
    if a.stage=='plan':print(create_plan(a.trial_dir,a.summary_run,a.summary_review,a.kind,a.output_dir,a.feedback_file))
    elif a.stage=='repair-plan':print(repair_plan(a.workflow,a.feedback_file,a.output_dir))
    elif a.stage=='write':print(json.dumps(write_scenes(a.workflow,a.review,a.beat_id,a.feedback_file),ensure_ascii=False))
    elif a.stage=='direction':print(json.dumps(revise_direction(a.workflow,a.feedback_file),ensure_ascii=False))
    else:print(json.dumps(accept_screenplay(a.workflow,a.review),ensure_ascii=False))

if __name__=='__main__':main()
