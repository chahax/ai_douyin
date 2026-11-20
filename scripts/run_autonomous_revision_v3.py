"""Bounded text-only autonomous closure; severity never skips confirmed repairs."""
import argparse
from copy import deepcopy
import difflib
import hashlib
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.serial_story_runtime_v2 import run_lock
from src.content_factory.novel_adaptation import autonomous_revision_v3 as n
from src.content_factory.novel_adaptation import agent_revision_v2 as base,agent_transport_v2 as transport,prose_patch,contracts as c
from src.content_factory.novel_adaptation import chapter_memory_v4 as memory_v4
from src.content_factory.novel_adaptation import script_specification as spec_rules
from src.content_factory.novel_adaptation import continuity_cards_v5 as continuity_v5


def prepare(run,prior,mode='repair',resume_review=None,resume_verification=None,request_text=None,
            source_packet=None,chapter_memory=None,shared_max_calls=None,resume_check=None,continuity_bundle=None):
    old=read(prior/'STATE.json');oldplan=read(prior/'PLAN.json')
    if old['pending'] is not None or not old['trial_ended']:raise ValueError('prior_not_terminal')
    candidate=(prior/'SCREENPLAY.md').read_text(encoding='utf-8') if (prior/'SCREENPLAY.md').exists() else None
    if candidate is None and mode!='full':raise ValueError('repair_requires_candidate')
    if candidate is not None and digest(candidate)!=read(prior/'CANDIDATE_BINDING.json')['candidate_digest']:raise ValueError('prior_candidate_changed')
    if sum(bool(x) for x in [resume_review,resume_verification,resume_check])>1:raise ValueError('choose_one_resume_stage')
    use_final=resume_review or resume_verification or resume_check or (mode=='full' and (prior/'FINAL_SOURCE.json').exists())
    packet=read(prior/('FINAL_SOURCE.json' if use_final else 'INPUT.json'));source=read(prior/'SOURCE.json')
    if source_packet is not None:
        if mode!='full' or resume_review or resume_verification:raise ValueError('source_override_requires_new_full_trial')
        targets=[x['chapter'] for x in source_packet['chapters'] if x['role']=='target']
        if len(targets)!=1 or source_packet!=memory_v4.packet(source,targets[0]):raise ValueError('invalid_chapter_source_prefix')
        packet=deepcopy(source_packet)
    if chapter_memory is not None:
        if source_packet is None:raise ValueError('memory_requires_source_prefix')
        if chapter_memory['current_chapter']!=targets[0]:raise ValueError('memory_target_mismatch')
    carry=[]
    previous_registry=[];imported_decisions=None;open_links={};imported_check=None
    if mode=='repair' and not resume_check and not resume_verification and not (resume_review and old.get('patch_rounds',0)):
        for row in read(prior/'ISSUE_REGISTRY.json'):
            if row['status'] in ('open','unresolved','pending_verification'):
                # Evidence must refer to the exact candidate being continued.
                if row['candidate_digest']!=digest(candidate):raise ValueError('stale_open_issue_needs_rebinding')
                carry.append({k:deepcopy(row[k]) for k in ('id','subject','kind','severity','claim','source_ids','reason','scopes')})
    if resume_verification:
        import json
        from src.content_factory.novel_adaptation.stream_evidence import audit_folder
        if mode!='repair':raise ValueError('verification_resume_requires_current_candidate')
        rec=old['nodes'][resume_verification];number=rec['call'];call=read(prior/f'CALL_{number:03}.json')
        address_resume=rec['status']=='complete' and resume_verification.endswith('_address_retry')
        if call['role']!='writer':raise ValueError('verification_not_writer')
        if address_resume:
            if read(prior/'ERROR.json')['message']!='address_retry_changed_decision':raise ValueError('only_known_address_failure')
        else:
            if rec['status']!='known_invalid_output':raise ValueError('verification_not_known_invalid')
            if read(prior/f'ERROR_{number:03}.json')['type']!='ContractError':raise ValueError('only_schema_displacement_recovery')
        if audit_folder(prior/f'native_{number:03}')['completion_evidence']!='known':raise ValueError('verification_unknown')
        payload=json.loads(call['messages'][1]['content'])
        if payload['candidate']!=candidate or digest(payload['source'])!=digest(packet):raise ValueError('verification_inputs_changed')
        report=payload['review']
        if digest(call['schema'])!=digest(n.verification_schema(report)):raise ValueError('verification_schema_changed')
        message=read(prior/f'RESPONSE_{number:03}.json')['choices'][0]['message']
        raw=json.loads(message['tool_calls'][0]['function']['arguments'])
        if address_resume:
            previous=payload['address_correction']['previous_decisions']
            invalid=payload['address_correction']['invalid']
            prior_node=resume_verification.removesuffix('_address_retry')
            if previous!=read(prior/(prior_node+'.json')):raise ValueError('address_previous_changed')
            corrections={f'a{i}':raw['decisions'][row['id']]['scopes'][row['scope_index']]['quote'] for i,row in enumerate(invalid)}
            repaired=apply_address_corrections(candidate,previous,invalid,corrections)
            receipt=dict(method='copy_only_corrected_quotes_from_known_response',ignored_non_address_fields=True,
                prior_node=prior_node,invalid=invalid)
        else:repaired,receipt=n.repair_unique_misplaced_scopes(report,raw)
        verification=n.decode_verification(report,repaired)
        # Validate every structural address before spending any further model call.
        n.adjudicate(packet,candidate,report,verification,allow_minor=bool(oldplan.get('specification')))
        imported_decisions=dict(report=report,verification=verification,repaired_native_value=repaired,
            receipt=receipt,call=number,source_digest=digest(packet),candidate_digest=digest(candidate))
        previous_registry=read(prior/'ISSUE_REGISTRY.json')
        for row in previous_registry:
            if row['status'] not in ('resolved','rejected','kept_style'):
                observations=[]
                for bound in prior.glob('cycle_*_CHECK_BINDING.json'):
                    binding=read(bound)
                    if binding['candidate_digest']!=digest(candidate):continue
                    check=read(prior/(bound.name.replace('_CHECK_BINDING.json','_check.json')))
                    if digest(check)!=binding['check_digest']:raise ValueError('check_evidence_changed')
                    observations.extend(x for x in check['regressions'] if x['id']==row['id'])
                matches=[x['id'] for x in report['issues'] if x['id'].endswith('_'+row['id']) and any(
                    {k:v for k,v in x.items() if k!='id'}=={k:v for k,v in o.items() if k!='id'} for o in observations)]
                if row.get('checked_candidate_digest')!=digest(candidate) or len(matches)!=1:raise ValueError('unresolved_history_not_bound')
                open_links.setdefault(matches[0],[]).append(row['record_id'])
    if resume_check:
        import json
        from src.content_factory.novel_adaptation.stream_evidence import audit_folder
        if mode!='repair' or not oldplan.get('specification') or read(prior/'ERROR.json')['message']!='check_coverage':raise ValueError('not_supported_check_recovery')
        rec=old['nodes'][resume_check];number=rec['call'];call=read(prior/f'CALL_{number:03}.json')
        if rec['status']!='complete' or audit_folder(prior/f'native_{number:03}')['completion_evidence']!='known':raise ValueError('check_not_known_complete')
        payload=json.loads(call['messages'][1]['content'])
        if payload['candidate']!=candidate or digest(payload['source'])!=digest(packet):raise ValueError('check_inputs_changed')
        prefix=resume_check.removesuffix('_check');a=read(prior/(prefix+'_ADJUDICATION.json'))
        if payload['confirmed_issues']!=a['accepted']:raise ValueError('check_issues_changed')
        check,receipt=spec_rules.normalize_check(read(prior/(resume_check+'.json')),a)
        previous_registry=read(prior/'ISSUE_REGISTRY.json')
        expected={x['id'] for x in a['accepted']}
        results={x['id']:x for x in check['results']}
        for row in previous_registry:
            if row['id'] in expected and row['record_id'].endswith(':'+prefix+':'+row['id']):
                outcome=results[row['id']];row.update(status=outcome['result'],check_reason=outcome['reason'],checked_candidate_digest=digest(candidate))
                if outcome['result']=='resolved':close_parents(previous_registry,row,'resolved',digest(candidate))
        base.validate_report(packet,candidate,dict(issues=check['regressions'],summary=check['summary']))
        carry=check['regressions']
        for row in previous_registry:
            if row['status'] not in ('resolved','kept_style','rejected'):
                if not any(x['id']==row['id'] for x in carry):raise ValueError('unresolved_check_evidence_missing')
                open_links.setdefault(row['id'],[]).append(row['record_id'])
        imported_check=dict(call=number,origin_run=str(prior),normalized=check,receipt=receipt,candidate_digest=digest(candidate))
    imported=None
    if resume_review:
        import json
        from src.content_factory.novel_adaptation.stream_evidence import audit_folder
        if mode!='repair':raise ValueError('review_resume_requires_current_candidate')
        origin=prior;origin_state=old;node=resume_review
        if resume_review=='imported':
            inherited=read(prior/'IMPORTED_REVIEW.json');number=inherited['call'];visited=set()
            while not (origin/f'CALL_{number:03}.json').exists():
                if origin.resolve() in visited:raise ValueError('review_origin_cycle')
                visited.add(origin.resolve());origin=Path(read(origin/'AUTHORIZATION.json')['prior'])
            origin_state=read(origin/'STATE.json');node=read(origin/f'CALL_{number:03}.json')['node']
            if read(origin/(node+'.json'))!=inherited['report']:raise ValueError('inherited_review_changed')
        rec=origin_state['nodes'][node];call=read(origin/f"CALL_{rec['call']:03}.json")
        if call['role']!='director' or rec['status'] not in ('complete','known_invalid_output'):raise ValueError('review_not_completed_director')
        if audit_folder(origin/f"native_{rec['call']:03}")['completion_evidence']!='known':raise ValueError('review_unknown')
        original=json.loads(call['messages'][1]['content'])
        if original['candidate']!=candidate:raise ValueError('review_candidate_changed')
        # Additional retrieved evidence may supplement but never change the old source.
        current={p['id']:p['text'] for ch in packet['chapters'] for p in ch['paragraphs']}
        if any(current.get(p['id'])!=p['text'] for ch in original['source']['chapters'] for p in ch['paragraphs']):raise ValueError('review_source_changed')
        if rec['status']=='known_invalid_output':
            if read(origin/f"ERROR_{rec['call']:03}.json")['type']!='ContractError':raise ValueError('not_known_envelope_error')
            value=json.loads(read(origin/f"RESPONSE_{rec['call']:03}.json")['choices'][0]['message']['content'])
            report,receipt=transport.normalize_response_envelope(value,call['schema'])
            if receipt is None:raise ValueError('no_safe_envelope_normalization')
        else:report=read(origin/(node+'.json'));receipt=None
        if old.get('patch_rounds',0):
            previous_registry=read(prior/'ISSUE_REGISTRY.json');carry=read(prior/'REMAINING_OBSERVATIONS.json')
            for row in previous_registry:
                if row['status'] in ('resolved','rejected','kept_style'):continue
                if row.get('checked_candidate_digest')!=digest(candidate):raise ValueError('stale_unresolved_history')
                matches=[x for x in carry if x['id']==row['id']]
                if len(matches)!=1:raise ValueError('unresolved_history_missing')
                open_links.setdefault(row['id'],[]).append(row['record_id'])
        else:carry=read(prior/'OPEN_ISSUES.json')
        imported=dict(report=report,normalization=receipt,source_digest=digest(original['source']),
                      call=rec['call'],original_request_digest=digest(call),origin_run=str(origin),origin_node=node)
    if imported_decisions:retrieval=dict(method='reuse_exact_verified_input',added_ids=[])
    else:packet,retrieval=n.retrieve(source,packet,carry)
    plan=deepcopy(oldplan)
    plan.update(version='autonomous_revision_v3',mode=mode,baseline_calls=old['calls_started'],baseline_tokens=old['reported_tokens'],
        source_digest=digest(packet),corpus_digest=digest(source),max_repair_rounds=2,max_cycles=6,
        history_digest=digest(carry),requires_human_confirmation=False)
    plan['imported_review_digest']=digest(imported) if imported else None
    plan['imported_decisions_digest']=digest(imported_decisions) if imported_decisions else None
    plan['previous_registry_digest']=digest(previous_registry);plan['open_links_digest']=digest(open_links)
    if mode=='full':
        # A user-requested new complete trial gets its own bounded window.
        # Recovery/continuation still inherits the previous window unchanged.
        if not request_text:raise ValueError('new_full_trial_requires_request_record')
        plan['max_calls']=shared_max_calls if shared_max_calls is not None else old['calls_started']+24
    elif shared_max_calls is not None:raise ValueError('shared_limit_requires_new_trial')
    plan['chapter_memory_digest']=digest(chapter_memory) if chapter_memory is not None else None
    if continuity_bundle is None and mode=='repair' and oldplan.get('continuity_digest'):
        continuity_bundle=read(prior/'CONTINUITY.json')
        if digest(continuity_bundle)!=oldplan['continuity_digest']:raise ValueError('continuity_changed')
    if continuity_bundle is not None:
        continuity_v5.validate_bundle(continuity_bundle)
        if [x['chapter'] for x in packet['chapters'] if x['role']=='target']!=[continuity_bundle['chapter']]:raise ValueError('continuity_target_mismatch')
    plan['continuity_digest']=digest(continuity_bundle) if continuity_bundle is not None else None
    if imported_decisions or imported_check or (resume_review and old.get('patch_rounds',0)):
        plan['max_repair_rounds']=oldplan['max_repair_rounds']-old['patch_rounds']
        # Zero permits settling the known final review, never another patch.
        if plan['max_repair_rounds']<0:raise ValueError('repair_round_budget_exhausted')
    # This continues the current experiment's remaining engineering bound.
    if plan['max_calls']<=old['calls_started']:raise ValueError('engineering_budget_exhausted')
    spec_rules.validate(plan.get('specification'))
    paths=[Path(__file__),Path(n.__file__),Path(base.__file__),Path(transport.__file__),Path(prose_patch.__file__),Path(memory_v4.__file__),Path(spec_rules.__file__),Path(continuity_v5.__file__),
        Path('src/content_factory/novel_adaptation/agent_capacity_v2.py'),Path('src/content_factory/serial_story_transport_v6.py'),Path('scripts/serial_native_worker_v6.py')]
    plan['implementation_pin']={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    run.mkdir(exist_ok=False)
    for p in paths:(run/('SNAPSHOT_'+p.name)).write_bytes(p.read_bytes())
    for key,value in [('PLAN',plan),('INPUT',packet),('SOURCE',source),('PRODUCTION_CHOICES',read(prior/'PRODUCTION_CHOICES.json')),
        ('INITIAL_RETRIEVAL',retrieval),('OPEN_ISSUES',carry),('AUTHORIZATION',dict(
        user=request_text or '模型把发现的问题都归为制作待确认，是不是需要修复下；整个流程目标是非人工参与',
        scope='完整生成、审核、自动返修的新一轮文本测试，无媒体或发布。' if mode=='full' else '自动决策、原文检索、中性表达、局部返修和无人文本完成门；延续本轮文本测试，无媒体或发布。',
        prior=str(prior),prior_state_sha256=hashlib.sha256((prior/'STATE.json').read_bytes()).hexdigest(),
        engineering_max_calls=plan['max_calls'],no_budget_reset=mode!='full',new_user_requested_full_trial=mode=='full'))]:freeze(run/(key+'.json'),value)
    if mode=='repair':(run/'ORIGINAL.md').write_text(candidate,encoding='utf-8')
    if chapter_memory is not None:freeze(run/'CHAPTER_MEMORY.json',chapter_memory)
    if continuity_bundle is not None:freeze(run/'CONTINUITY.json',continuity_bundle)
    if plan.get('specification'):(run/'SPECIFICATION.md').write_text(plan['specification']['text'],encoding='utf-8')
    if imported:freeze(run/'IMPORTED_REVIEW.json',imported)
    if imported_decisions:freeze(run/'IMPORTED_DECISIONS.json',imported_decisions)
    if imported_check:freeze(run/'IMPORTED_CHECK.json',imported_check)
    freeze(run/'PREVIOUS_REGISTRY.json',previous_registry);freeze(run/'OPEN_LINKS.json',open_links)
    state=dict(status='prepared',pending=None,calls_started=old['calls_started'],reported_tokens=old['reported_tokens'],
        trial_ended=False,nodes={},retained_unknowns=old.get('retained_unknowns',[]),semantic_accepted=False,
        video_released=False,requires_human_confirmation=False)
    transport.Transport(run,plan,state).save()


def close_parents(registry,record,status,candidate_digest):
    for key in record.get('parents',[]):
        parent=next(x for x in registry if x['record_id']==key)
        parent.update(status=status,closed_by=record['record_id'],checked_candidate_digest=candidate_digest)
        close_parents(registry,parent,status,candidate_digest)


def call_verification(t,node,payload,spec=None):
    schema=n.verification_schema(payload['review'])
    try:return t.call(node,'writer',spec_rules.prompt('verify',n.VERIFY_PROMPT,spec),payload,schema)
    except c.ContractError:
        # Only a fully received, known schema failure is eligible; never re-dispatch.
        import json
        state=t.state;number=state['calls_started']
        if state['pending'] is not None or state['status']!='known_invalid_output':raise
        message=read(t.run/f'RESPONSE_{number:03}.json')['choices'][0]['message']
        raw=json.loads(message['tool_calls'][0]['function']['arguments'])
        fixed,receipt=n.repair_unique_misplaced_scopes(payload['review'],raw)
        freeze(t.run/(node+'_PROTOCOL_RECOVERY.json'),dict(receipt=receipt,prior_state=deepcopy(state),value=fixed))
        state['nodes'][node].update(status='complete_protocol_recovered',result_digest=digest(fixed))
        state.update(trial_ended=False,status='node_complete');t.save()
        return fixed


def apply_address_corrections(candidate,raw,invalid,corrections):
    if set(corrections)!={f'a{i}' for i in range(len(invalid))}:raise ValueError('address_correction_coverage')
    fixed=deepcopy(raw)
    for i,row in enumerate(invalid):
        scope=fixed['decisions'][row['id']]['scopes'][row['scope_index']]
        if scope['quote']!=row['quote']:raise ValueError('address_original_changed')
        scope['quote']=n.resolve_typographic_span(candidate,corrections[f'a{i}'])
    return fixed


def verified_decisions(t,node,payload,spec=None):
    """One bounded address correction; never fuzzy-match or edit screenplay text."""
    raw=call_verification(t,node,payload,spec)
    verification=n.decode_verification(payload['review'],raw)
    try:
        n.adjudicate(payload['source'],payload['candidate'],payload['review'],verification,allow_minor=bool(spec))
    except ValueError as exc:
        if str(exc)!='repair_range_not_unique':raise
        invalid=[]
        for decision in verification['decisions']:
            if not decision['action'].startswith('repair_'):continue
            for index,scope in enumerate(decision['scopes']):
                try:n.resolve_typographic_span(payload['candidate'],scope['quote'])
                except ValueError:invalid.append(dict(id=decision['id'],scope_index=index,quote=scope['quote']))
        if not invalid:raise
        freeze(t.run/(node+'_ADDRESS_FAILURE.json'),dict(invalid=invalid,verification=verification,
            candidate_digest=digest(payload['candidate']),error=str(exc)))
        correction=dict(candidate=payload['candidate'],invalid_addresses={f'a{i}':row['quote'] for i,row in enumerate(invalid)})
        corrected=t.call(node+'_address_quotes','writer',
            '只纠正引用地址。按invalid_addresses的键，从candidate逐字复制对应完整连续原文，保留所有声道标签、标点和文字。不得改写、概括、删减原文；不要返回审核判断或修改候选。',
            correction,c.obj(**{f'a{i}':c.TEXT for i in range(len(invalid))}))
        fixed=apply_address_corrections(payload['candidate'],raw,invalid,corrected)
        verification=n.decode_verification(payload['review'],fixed)
        n.adjudicate(payload['source'],payload['candidate'],payload['review'],verification,allow_minor=bool(spec))
    return verification


def execute(run):
    with run_lock(run):
        state=read(run/'STATE.json');plan=read(run/'PLAN.json')
        spec=plan.get('specification');spec_rules.validate(spec)
        if state['status']!='prepared' or state['pending'] is not None or state['trial_ended']:raise ValueError('run_not_fresh')
        for path,sha in plan['implementation_pin'].items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=sha:raise ValueError('implementation_changed')
        source=read(run/'INPUT.json');corpus=read(run/'SOURCE.json');choices=read(run/'PRODUCTION_CHOICES.json')
        open_links=read(run/'OPEN_LINKS.json')
        carry=[(x,open_links.get(x['id'],[])) for x in read(run/'OPEN_ISSUES.json')]
        if digest(source)!=plan['source_digest'] or digest(corpus)!=plan['corpus_digest']:raise ValueError('source_changed')
        if digest([x for x,_ in carry])!=plan['history_digest']:raise ValueError('open_issues_changed')
        registry=read(run/'PREVIOUS_REGISTRY.json');open_links=read(run/'OPEN_LINKS.json')
        if digest(registry)!=plan['previous_registry_digest'] or digest(open_links)!=plan['open_links_digest']:raise ValueError('previous_history_changed')
        t=transport.Transport(run,plan,state);candidate=None;patch_count=0
        if plan.get('continuity_digest'):
            bundle=read(run/'CONTINUITY.json')
            if digest(bundle)!=plan['continuity_digest']:raise ValueError('continuity_changed')
            continuity_v5.validate_bundle(bundle)
            t=continuity_v5.BoundTransport(t,bundle)
        try:
            if plan['mode']=='repair':candidate=(run/'ORIGINAL.md').read_text(encoding='utf-8')
            else:
                author_payload=dict(source=source,production_choices=choices);author_prompt=spec_rules.prompt('write',n.WRITE,spec)
                if plan.get('chapter_memory_digest'):
                    memory=read(run/'CHAPTER_MEMORY.json')
                    if digest(memory)!=plan['chapter_memory_digest']:raise ValueError('chapter_memory_changed')
                    author_payload['chapter_memory']=memory;author_prompt+='\n'+memory_v4.AUTHOR_CONTEXT
                candidate=t.call('generate','writer',author_prompt,author_payload,c.obj(text=c.TEXT))['text']
                (run/'ORIGINAL.md').write_text(candidate,encoding='utf-8')
            (run/'SCREENPLAY.md').write_text(candidate,encoding='utf-8')
            for cycle in range(plan['max_cycles']):
                prefix=f'cycle_{cycle}'
                review_source_digest=digest(source)
                reused_decisions=None
                if cycle==0 and plan.get('imported_decisions_digest'):
                    reused_decisions=read(run/'IMPORTED_DECISIONS.json')
                    if digest(reused_decisions)!=plan['imported_decisions_digest']:raise ValueError('imported_decisions_changed')
                    review=reused_decisions['report'];review_source_digest=None
                elif cycle==0 and plan.get('imported_review_digest'):
                    imported=read(run/'IMPORTED_REVIEW.json')
                    if digest(imported)!=plan['imported_review_digest']:raise ValueError('imported_review_changed')
                    review=imported['report'];review_source_digest=imported['source_digest']
                else:
                    review=t.call(prefix+'_review','director',spec_rules.prompt('review',n.REVIEW,spec),dict(source=source,production_choices=choices,
                        candidate=candidate,contract_findings=n.contract_findings(candidate)),n.REPORT)
                base.validate_report(source,candidate,review)
                combined=deepcopy(review);parents=deepcopy(open_links) if reused_decisions else {}
                for i,(item,links) in enumerate(carry):
                    x=deepcopy(item);x['id']=f'C{cycle}_{i}_{x["id"]}'
                    combined['issues'].append(x);parents[x['id']]=links
                carry=[]
                if len({x['id'] for x in combined['issues']})!=len(combined['issues']):raise ValueError('combined_issue_id_collision')
                freeze(run/(prefix+'_COMBINED_REVIEW.json'),combined)
                if reused_decisions:retrieval=dict(method='reuse_exact_verified_input',added_ids=[])
                else:source,retrieval=n.retrieve(corpus,source,combined['issues'])
                freeze(run/(prefix+'_RETRIEVAL.json'),retrieval);freeze(run/(prefix+'_SOURCE.json'),source)
                if reused_decisions:verification=reused_decisions['verification']
                elif combined['issues']:
                    verification=verified_decisions(t,prefix+'_verify',dict(source=source,production_choices=choices,
                        candidate=candidate,review=combined,relevant_history=base.relevant_history(registry,combined['issues'])),spec)
                    freeze(run/(prefix+'_CANONICAL_VERIFY.json'),verification)
                else:verification=dict(decisions=[],summary='没有待处理意见')
                adjudication=n.adjudicate(source,candidate,combined,verification,allow_minor=bool(spec))
                freeze(run/(prefix+'_ADJUDICATION.json'),adjudication)
                records={}
                for row in adjudication['rows']:
                    record={**deepcopy(row),'record_id':run.name+':'+prefix+':'+row['id'],'parents':parents.get(row['id'],[]),
                        'status':('rejected' if row['decision']=='rejected' else 'kept_style') if row['action']=='keep' else 'open'}
                    records[row['id']]=record;registry.append(record)
                    if record['status']=='rejected':close_parents(registry,record,'rejected',digest(candidate))
                    if record['status']=='kept_style':close_parents(registry,record,'kept_style',digest(candidate))
                if adjudication['blocked']:
                    state['status']='auto_failed_unresolvable_evidence';break
                if not adjudication['accepted']:
                    # Any new evidence must be part of the final independent audit too.
                    if review_source_digest!=digest(source):continue
                    gate=n.completion_gate(candidate,registry,True)
                    freeze(run/(prefix+'_COMPLETION_GATE.json'),gate)
                    state['status']='text_contract_complete' if gate['passed'] else 'auto_failed_open_contract'
                    state['final_review_binding']=dict(candidate_digest=digest(candidate),source_digest=digest(source),
                        review_digest=digest(review),independent=True)
                    state['text_contract_complete']=gate['passed'];break
                if patch_count>=plan['max_repair_rounds']:
                    state['status']='auto_failed_revision_limit';break
                spans=n.patch_plan(candidate,adjudication);freeze(run/(prefix+'_SPANS.json'),spans)
                patch=t.call(prefix+'_patch','writer',spec_rules.prompt('repair',n.REPAIR_PROMPT,spec),dict(source=source,production_choices=choices,
                    candidate=candidate,confirmed_issues=adjudication['accepted'],slots=spans['slots'],
                    relevant_history=base.relevant_history(registry,adjudication['accepted'])),prose_patch.schema(spans))
                before=candidate;candidate=prose_patch.apply(candidate,spans,patch);patch_count+=1
                for name,value in [('BEFORE',before),('AFTER',candidate)]:
                    (run/(prefix+'_'+name+'.md')).write_text(value,encoding='utf-8')
                (run/(prefix+'_PATCH.diff')).write_text(''.join(difflib.unified_diff(before.splitlines(True),candidate.splitlines(True))),encoding='utf-8')
                (run/'SCREENPLAY.md').write_text(candidate,encoding='utf-8')
                check=t.call(prefix+'_check','writer',spec_rules.prompt('check',n.CHECK_PROMPT,spec),dict(source=source,production_choices=choices,
                    candidate=candidate,before=before,confirmed_issues=adjudication['accepted'],patches=patch,
                    relevant_history=base.relevant_history(registry,adjudication['accepted'])),
                    spec_rules.check_schema(adjudication['accepted'],n.CHECK) if spec else n.CHECK)
                if spec:
                    check,receipt=spec_rules.normalize_check(check,adjudication)
                    if receipt['ignored_kept_ids']:freeze(run/(prefix+'_CHECK_NORMALIZATION.json'),dict(value=check,receipt=receipt))
                expected={x['id'] for x in adjudication['accepted']}
                if len(check['results'])!=len(expected) or {x['id'] for x in check['results']}!=expected:raise ValueError('check_coverage')
                base.validate_report(source,candidate,dict(issues=check['regressions'],summary=check['summary']))
                unresolved=[]
                for row in check['results']:
                    record=records[row['id']];record.update(status=row['result'],check_reason=row['reason'],checked_candidate_digest=digest(candidate))
                    if row['result']=='resolved':close_parents(registry,record,'resolved',digest(candidate))
                    else:unresolved.append(row['id'])
                for item in check['regressions']:
                    links=[records[item['id']]['record_id']] if item['id'] in unresolved else []
                    carry.append((item,links))
                if not set(unresolved).issubset({x['id'] for x in check['regressions']}):
                    state['status']='auto_failed_missing_repair_evidence';break
                freeze(run/(prefix+'_CHECK_BINDING.json'),dict(candidate_digest=digest(candidate),source_digest=digest(source),
                    check_digest=digest(check),patch_digest=digest(patch),unselected_text_preserved=True))
            else:state['status']='auto_failed_cycle_limit'
        except Exception as exc:
            if state['pending'] is None and state['status'] not in ('known_truncated','known_invalid_output','model_mismatch'):
                state['status']='auto_failed_contract'
            freeze(run/'ERROR.json',dict(type=type(exc).__name__,message=str(exc)[:2500]))
        finally:
            if candidate is not None:
                freeze(run/'CANDIDATE_BINDING.json',dict(candidate_digest=digest(candidate),source_digest=digest(source)))
            freeze(run/'FINAL_SOURCE.json',source);freeze(run/'ISSUE_REGISTRY.json',registry)
            freeze(run/'REMAINING_OBSERVATIONS.json',[x for x,_ in carry])
            state.update(trial_ended=True,patch_rounds=patch_count,semantic_accepted=False,video_released=False,
                         requires_primary_acceptance=False,requires_human_confirmation=False)
            t.save()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','execute'])
    p.add_argument('--run',type=Path,required=True);p.add_argument('--prior',type=Path)
    p.add_argument('--mode',choices=['repair','full'],default='repair')
    p.add_argument('--resume-review');p.add_argument('--resume-verification');p.add_argument('--request-text');a=p.parse_args()
    if a.command=='prepare':prepare(a.run,a.prior,a.mode,a.resume_review,a.resume_verification,a.request_text)
    else:execute(a.run)
