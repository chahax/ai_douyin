"""Three-chapter production trial with shared cards and bound final handoffs."""
import argparse
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.platform_adapter.fanqie_book_corpus import atomic
from src.content_factory.serial_story_runtime_v2 import run_lock
from src.content_factory.novel_adaptation import continuity_cards_v5 as cards, chapter_memory_v4 as memory
from src.content_factory.novel_adaptation import agent_transport_v2 as transport,script_specification as rules
from scripts import run_autonomous_revision_v3 as script

REQUEST='修改重新跑生产然后你再审核：共享人物事实、场景制作卡、上一场结束状态，前三章文本测试。'

def prepare(run,prior,resume_verification=None,finish_known_final=False,resume_handoff=False,resume_cards=False,resume_review=None):
    if sum(bool(x) for x in [resume_verification,finish_known_final,resume_handoff,resume_cards,resume_review])>1:raise ValueError('choose_one_resume')
    old=read(prior/'STATE.json')
    if not old['trial_ended'] or old['pending'] is not None:raise ValueError('prior_not_terminal')
    source=read(prior/'SOURCE.json');memory.packet(source,3)
    prior_plan=read(prior/'PLAN.json')
    plan={k:deepcopy(prior_plan[k]) for k in ['routes','capabilities','budgets','inference','endpoint_overrides']}
    plan.update(version='continuity_cards_v5',baseline_calls=old['calls_started'],baseline_tokens=old['reported_tokens'],
        max_calls=old['calls_started']+60,end_chapter=3,corpus_digest=digest(source),specification=rules.config())
    completed=[]
    if resume_cards:
        import json
        from src.content_factory.novel_adaptation.stream_evidence import audit_folder
        if resume_verification or finish_known_final or resume_handoff:raise ValueError('choose_one_resume')
        failed=Path(old['current_run']);fs=read(failed/'STATE.json');rec=fs['nodes']['cards']
        if prior_plan['version']!='continuity_cards_v5' or fs['pending'] is not None or not fs['trial_ended'] or rec['status']!='known_invalid_output':raise ValueError('not_known_cards_failure')
        if audit_folder(failed/f"native_{rec['call']:03}")['completion_evidence']!='known':raise ValueError('unknown_no_resume')
        raw=json.loads(read(failed/f"RESPONSE_{rec['call']:03}.json")['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
        if set(raw)!={'updates','reason'} or not isinstance(raw['reason'],str):raise ValueError('not_only_cards_metadata')
        payload=read(failed/'PAYLOAD.json');proposal={'updates':raw['updates']}
        if cards.c.schema_issues(proposal,cards.cards_schema(payload['source']),'cards'):raise ValueError('cards_invalid_after_metadata')
        chapter=max(x['chapter'] for x in payload['source']['chapters'] if x['role']=='target')
        completed=old['chapters']
        if [x['chapter'] for x in completed]!=list(range(1,chapter)) or not all(x['handoff_committed'] for x in completed):raise ValueError('incomplete_prior_handoffs')
        parent=read(prior/f'COMMIT_{chapter-1:03}.json')['commit_digest'] if chapter>1 else None
        bundle=dict(version='continuity_cards_v5',chapter=chapter,cards=payload['previous_cards'],previous_handoff=payload['previous_handoff'],parent_digest=parent)
        cards.validate_bundle(bundle)
        imported_cards=dict(proposal=proposal,payload=payload,origin=str(failed),metadata_preserved=raw['reason'],original_state_digest=digest(fs))
        plan.update(max_calls=prior_plan['max_calls'],specification=prior_plan['specification'],resumed_cards=dict(chapter=chapter,resume_cards=True),
            prior_roots=prior_plan.get('prior_roots',[])+[str(prior.resolve())],trial_baseline_calls=prior_plan.get('trial_baseline_calls',prior_plan['baseline_calls']),
            trial_baseline_tokens=prior_plan.get('trial_baseline_tokens',prior_plan['baseline_tokens']))
    if resume_handoff:
        from src.content_factory.novel_adaptation.stream_evidence import audit_folder
        if resume_verification or finish_known_final:raise ValueError('choose_one_resume')
        failed=Path(old['current_run']);fs=read(failed/'STATE.json')
        if prior_plan['version']!='continuity_cards_v5' or fs['pending'] is not None or not fs['trial_ended'] or read(failed/'ERROR.json')['message']!='handoff_quote_not_in_final_candidate':raise ValueError('not_known_handoff_address_failure')
        if audit_folder(failed/f"native_{fs['calls_started']:03}")['completion_evidence']!='known':raise ValueError('unknown_no_resume')
        payload=read(failed/'PAYLOAD.json');chapter=max(x['chapter'] for x in payload['source']['chapters'] if x['role']=='target')
        proposal=read(failed/'handoff_repair.json');review=read(failed/'handoff_audit_1.json');cards.checked_audit(review)
        if Path(payload['candidate_path']).read_text(encoding='utf-8')!=payload['final_candidate']:raise ValueError('handoff_candidate_changed')
        bundle=read(prior/f'CONTINUITY_{chapter:03}.json');cards.validate_bundle(bundle)
        completed=[x for x in old['chapters'] if x['chapter']<chapter]
        script_run=next(x['script_run'] for x in old['chapters'] if x['chapter']==chapter)
        imported_handoff=dict(proposal=proposal,audit=review,payload=payload,origin=str(failed),original_state_digest=digest(fs))
        plan.update(max_calls=prior_plan['max_calls'],specification=prior_plan['specification'],
            resumed_script=dict(run=script_run,chapter=chapter,finish_known_final=True,resume_handoff=True),
            prior_roots=prior_plan.get('prior_roots',[])+[str(prior.resolve())],
            trial_baseline_calls=prior_plan.get('trial_baseline_calls',prior_plan['baseline_calls']),
            trial_baseline_tokens=prior_plan.get('trial_baseline_tokens',prior_plan['baseline_tokens']))
    if resume_verification or finish_known_final or resume_review:
        from src.content_factory.novel_adaptation.stream_evidence import audit_folder
        failed=Path(old['current_run']);fs=read(failed/'STATE.json')
        node=resume_verification or f"cycle_{fs['patch_rounds']}_verify"
        rec=fs['nodes'][node]
        if prior_plan['version']!='continuity_cards_v5' or fs['pending'] is not None or not fs['trial_ended'] or rec['status']!='known_invalid_output':raise ValueError('not_known_verification_failure')
        if audit_folder(failed/f"native_{rec['call']:03}")['completion_evidence']!='known':raise ValueError('unknown_no_resume')
        if finish_known_final:
            import json
            if resume_verification:raise ValueError('choose_one_resume')
            if fs['patch_rounds']!=read(failed/'PLAN.json')['max_repair_rounds']:raise ValueError('not_final_bounded_candidate')
            review_node=f"cycle_{fs['patch_rounds']}_review";review_call=fs['nodes'][review_node]['call']
            if fs['nodes'][review_node]['status']!='complete' or audit_folder(failed/f'native_{review_call:03}')['completion_evidence']!='known':raise ValueError('final_review_not_known')
            raw=read(failed/f'RESPONSE_{rec["call"]:03}.json')['choices'][0]['message']['tool_calls'][0]['function']['arguments']
            normalized,receipt=script.n.repair_unique_misplaced_scopes(read(failed/f"cycle_{fs['patch_rounds']}_COMBINED_REVIEW.json"),json.loads(raw))
            if receipt['method']!='empty_scopes_for_keep_only':raise ValueError('unsupported_final_protocol_failure')
            text=(failed/'SCREENPLAY.md').read_text(encoding='utf-8')
            rp=json.loads(read(failed/f'CALL_{review_call:03}.json')['messages'][1]['content'])
            if rp['candidate']!=text or digest(text)!=read(failed/'CANDIDATE_BINDING.json')['candidate_digest']:raise ValueError('final_review_candidate_changed')
        bundle=read(failed/'CONTINUITY.json');cards.validate_bundle(bundle)
        completed=[x for x in old['chapters'] if x['chapter']<bundle['chapter']]
        plan.update(max_calls=prior_plan['max_calls'],specification=prior_plan['specification'],
            resumed_script=dict(run=str(failed),node=node,review=resume_review,chapter=bundle['chapter'],finish_known_final=finish_known_final),
            prior_roots=prior_plan.get('prior_roots',[])+[str(prior.resolve())],
            trial_baseline_calls=prior_plan.get('trial_baseline_calls',prior_plan['baseline_calls']),
            trial_baseline_tokens=prior_plan.get('trial_baseline_tokens',prior_plan['baseline_tokens']))
    paths=[Path(__file__),Path(cards.__file__),Path(memory.__file__),Path(transport.__file__),Path(script.__file__),
        Path(script.n.__file__),Path(script.base.__file__),Path(script.prose_patch.__file__),Path(rules.__file__),
        Path('src/content_factory/novel_adaptation/agent_capacity_v2.py'),Path('src/content_factory/serial_story_transport_v6.py'),Path('scripts/serial_native_worker_v6.py')]
    plan['implementation_pin']={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    run.mkdir(exist_ok=False)
    for p in paths:(run/('SNAPSHOT_'+p.name)).write_bytes(p.read_bytes())
    if resume_verification or finish_known_final or resume_handoff or resume_cards or resume_review:
        for row in completed:
            for prefix in ('CONTINUITY','COMMIT'):
                name=f"{prefix}_{row['chapter']:03}.json";freeze(run/name,read(prior/name))
        freeze(run/'RESUME_CONTINUITY.json',bundle)
        if resume_handoff:freeze(run/'IMPORTED_HANDOFF.json',imported_handoff)
        if resume_cards:freeze(run/'IMPORTED_CARDS.json',imported_cards)
        if finish_known_final:freeze(run/'KNOWN_FINAL_EVALUATION.json',dict(origin=str(failed),original_status=fs['status'],
            method='retain_known_failed_final_candidate_evaluate_only_boundary',normalized_verification=normalized,receipt=receipt,
            final_review_call=review_call,candidate_digest=digest(text),automatic_script_accepted=False,additional_script_calls=0))
    for key,value in [('PLAN',plan),('SOURCE',source),('AUTHORIZATION',dict(user=REQUEST,prior=str(prior),
        scope='仅已授权小说前三章、MiniMax生成与资料核验、DeepSeek独立整稿审；无媒体发布或默认迁移',max_calls=plan['max_calls'],
        max_script_patches_per_chapter=2,max_card_or_handoff_repairs=1))]:freeze(run/(key+'.json'),value)
    (run/'SPECIFICATION.md').write_text(plan['specification']['text'],encoding='utf-8')
    atomic(run/'STATE.json',dict(status='prepared',trial_ended=False,pending=None,calls_started=old['calls_started'],
        reported_tokens=old['reported_tokens'],retained_unknowns=old.get('retained_unknowns',[]),current_run=None,chapters=completed))

def auxiliary(run,plan,ledger,corpus,source,stage,payload,previous,imported=None):
    run.mkdir(exist_ok=False)
    active=deepcopy(plan);active.update(baseline_calls=ledger['calls_started'],baseline_tokens=ledger['reported_tokens'])
    state=dict(status='prepared',trial_ended=False,pending=None,nodes={},calls_started=ledger['calls_started'],
        reported_tokens=ledger['reported_tokens'],retained_unknowns=ledger.get('retained_unknowns',[]))
    for key,value in [('PLAN',active),('SOURCE',corpus),('INPUT',source),('PRODUCTION_CHOICES',[]),('PAYLOAD',payload)]:freeze(run/(key+'.json'),value)
    t=transport.Transport(run,active,state);t.save()
    prompt=cards.CARDS if stage=='cards' else cards.HANDOFF
    schema=cards.cards_schema(source) if stage=='cards' else cards.handoff_schema(source)
    try:
        proposal=imported['proposal'] if imported else t.call(stage,'writer',prompt,payload,schema)
        if imported:freeze(run/'IMPORT.json',imported)
        for attempt in ([1] if imported and 'audit' in imported else range(2)):
            audit=imported['audit'] if imported and 'audit' in imported else t.call(stage+'_audit_'+str(attempt),'writer',cards.AUDIT,
                {**payload,'stage':stage,'proposal':proposal},cards.AUDIT_SCHEMA)
            try:
                if stage=='cards':result=cards.merge_cards(previous,proposal,source,audit)
                else:
                    if audit['passed'] and any(q not in payload['final_candidate'] for q in proposal['candidate_quotes']):
                        addresses=t.call('handoff_addresses','writer',
                            '只定位证据，不修改state任何文字。按每个字段从candidate_lines选择确实支持该结束状态的行号；不能仅因含同一人物就选。若字段有实质内容无法由候选支持，supported=false。不要引用小说原文或另写引句。',
                            dict(state={k:v for k,v in proposal.items() if k not in ('candidate_quotes','source_ids')},candidate_lines=cards.candidate_lines(payload['final_candidate'])),cards.address_schema(payload['final_candidate']))
                        proposal,receipt=cards.apply_addresses(proposal,payload['final_candidate'],addresses)
                        freeze(run/'ADDRESS_RECOVERY.json',receipt);freeze(run/'ADDRESSED_HANDOFF.json',proposal)
                    result=cards.bind_handoff(proposal,source,payload['final_candidate'],payload['candidate_path'],audit)
                break
            except (ValueError,script.c.ContractError) as exc:
                freeze(run/f'REJECTED_{attempt}.json',dict(error=str(exc),proposal=proposal,audit=audit))
                if attempt or (run/'ADDRESS_RECOVERY.json').exists():raise
                proposal=t.call(stage+'_repair','writer',prompt+'\n只修明确问题，返回完整本次增量/结束状态。',
                    {**payload,'proposal':proposal,'review':audit,'contract_error':str(exc)},schema)
        freeze(run/'RESULT.json',result);state['status']='continuity_model_checked';return result
    except Exception as exc:
        if state['pending'] is None and state['status'] not in ('known_invalid_output','known_truncated','model_mismatch'):state['status']='continuity_failed'
        freeze(run/'ERROR.json',dict(type=type(exc).__name__,message=str(exc)[:2500]));raise
    finally:state['trial_ended']=True;t.save()

def execute(run):
    with run_lock(run):
        plan=read(run/'PLAN.json');state=read(run/'STATE.json');corpus=read(run/'SOURCE.json')
        if state['status']!='prepared' or state['trial_ended'] or state['pending'] is not None:raise ValueError('not_fresh')
        if digest(corpus)!=plan['corpus_digest']:raise ValueError('source_changed')
        for path,sha in plan['implementation_pin'].items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=sha:raise ValueError('implementation_changed')
        shared=[];handoff=None;parent=None;start_chapter=1
        resumed=plan.get('resumed_script') or plan.get('resumed_cards')
        if resumed:
            initial=read(run/'RESUME_CONTINUITY.json');cards.validate_bundle(initial)
            start_chapter=initial['chapter'];shared=initial['cards'];handoff=initial['previous_handoff'];parent=initial['parent_digest']
        def start(child):
            state.update(status='running',current_run=str(child));atomic(run/'STATE.json',state)
        def sync(child):
            s=read(child/'STATE.json')
            for key in ('calls_started','reported_tokens','pending'):state[key]=s[key]
            atomic(run/'STATE.json',state);return s
        try:
            for chapter in range(start_chapter,4):
                source=memory.packet(corpus,chapter)
                crun=run/f'chapter_{chapter:03}_cards';srun=run/f'chapter_{chapter:03}_script';hrun=run/f'chapter_{chapter:03}_handoff'
                if not (resumed and chapter==start_chapter) or resumed.get('resume_cards'):
                    start(crun)
                    imported_cards=read(run/'IMPORTED_CARDS.json') if resumed and chapter==start_chapter and resumed.get('resume_cards') else None
                    cp=dict(source=source,previous_cards=shared,previous_handoff=handoff)
                    if imported_cards and cp!=imported_cards['payload']:raise ValueError('imported_cards_input_changed')
                    try:shared=auxiliary(crun,plan,state,corpus,source,'cards',
                        cp,shared,**({'imported':imported_cards} if imported_cards else {}))
                    finally:sync(crun)
                bundle=dict(version='continuity_cards_v5',chapter=chapter,cards=shared,previous_handoff=handoff,parent_digest=parent)
                cards.validate_bundle(bundle);freeze(run/f'CONTINUITY_{chapter:03}.json',bundle)
                final_evaluation=resumed and chapter==start_chapter and resumed.get('finish_known_final')
                if final_evaluation:
                    srun=Path(resumed['run'])
                elif resumed and chapter==start_chapter and not resumed.get('resume_cards'):
                    script.prepare(srun,Path(resumed['run']),resume_verification=None if resumed.get('review') else resumed['node'],resume_review=resumed.get('review'),request_text=REQUEST)
                else:
                    script.prepare(srun,crun,mode='full',request_text=REQUEST,source_packet=source,
                        shared_max_calls=plan['max_calls'],continuity_bundle=bundle)
                start(srun)
                if not final_evaluation:script.execute(srun)
                if final_evaluation and resumed.get('resume_handoff'):s=read(srun/'STATE.json')
                else:s=sync(srun)
                state['chapters'].append(dict(chapter=chapter,script_run=str(srun),script_status=s['status'],handoff_committed=False))
                atomic(run/'STATE.json',state)
                if s['pending'] is not None:raise RuntimeError('unknown_no_next_chapter')
                if not final_evaluation and s['status'] not in ('text_contract_complete','auto_failed_revision_limit','auto_failed_cycle_limit'):
                    raise RuntimeError('script_contract_failed')
                # A model-checked boundary can be carried for evaluation even when
                # unrelated script notes remain. Never label the full script passed.
                candidate=(srun/'SCREENPLAY.md').read_text(encoding='utf-8')
                if read(srun/'CANDIDATE_BINDING.json')['candidate_digest']!=digest(candidate):raise ValueError('final_candidate_changed')
                start(hrun)
                hp=dict(source=source,previous_cards=shared,previous_handoff=handoff,final_candidate=candidate,candidate_path=str((srun/'SCREENPLAY.md').resolve()))
                imported=read(run/'IMPORTED_HANDOFF.json') if resumed and chapter==start_chapter and resumed.get('resume_handoff') else None
                if imported and hp!=imported['payload']:raise ValueError('imported_handoff_input_changed')
                try:handoff=auxiliary(hrun,plan,state,corpus,source,'handoff',hp,shared,**({'imported':imported} if imported else {}))
                finally:sync(hrun)
                parent=digest(dict(bundle=bundle,handoff=handoff))
                freeze(run/f'COMMIT_{chapter:03}.json',dict(bundle=bundle,handoff=handoff,commit_digest=parent,
                    script_status=s['status'],full_script_accepted=False))
                state['chapters'][-1].update(handoff_committed=True,commit_digest=parent)
                atomic(run/'STATE.json',state)
            state['status']='trial_complete'
        except Exception as exc:
            state['status']='outcome_unknown' if state['pending'] is not None else 'trial_failed'
            freeze(run/'ERROR.json',dict(type=type(exc).__name__,message=str(exc)[:2500]))
        finally:
            state.update(trial_ended=True,semantic_accepted=False,video_released=False);atomic(run/'STATE.json',state)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','execute']);p.add_argument('--run',type=Path,required=True);p.add_argument('--prior',type=Path);p.add_argument('--resume-verification');p.add_argument('--finish-known-final',action='store_true');p.add_argument('--resume-handoff',action='store_true');p.add_argument('--resume-cards',action='store_true');p.add_argument('--resume-review')
    a=p.parse_args()
    if a.command=='prepare':prepare(a.run,a.prior,a.resume_verification,a.finish_known_final,a.resume_handoff,a.resume_cards,a.resume_review)
    else:execute(a.run)
