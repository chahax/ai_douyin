"""Thin staged successor after settled637/638; no old frozen code changes."""
from copy import deepcopy
import argparse
import json
import os
from pathlib import Path
import sys
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from scripts import run_h3_screenplay_world_revision_v1 as old
from scripts import creative_resume_dispatch_v3 as io
from scripts import creative_scope_probe_execution_policy_v1 as policy
from scripts.creative_fresh_source_session_v1 import Session as NativeSession,Halt
from src.content_factory import creative_screenplay_world_source_repair_v2 as story
from src.content_factory import creative_screenplay_world_v1 as base

ROOT=old.ROOT.parent/'text_successor'
FACTS=old.ROOT.parent/'SELECTED_SCENE_VISIBLE_FACTS.json'
REJECTION=old.ROOT.parent/'WORLD637_PRIMARY_CONTENT_REJECTION.json'
EXTRA=ROOT/'PRIMARY_BODY638_CONTENT_DIAGNOSIS.json'
VERSION='h3_world_source_repair/v2'
LIMITS={'goal_plan':1,'goal_audit':0,'complete_script':1,'full_review':1}
read,write,digest,sha,now=io.read,io.write,io.digest,io.sha_file,io.now


def parent_certificate():
    old.guard();rt=old.runtime();summary=rt.summary()
    expected={'effective_calls_started':638,'effective_reported_tokens':13463603,'effective_calls_with_known_usage':636,
        'unknown_token_reservations':93117,'new_unknown_token_reservations':0}
    if any(summary.get(k)!=v for k,v in expected.items()):raise ValueError('settled actual638 consumption changed; no regrant')
    rows=read(rt.ledger)['calls']
    if [r['ordinal'] for r in rows]!=[637,638]:raise ValueError('unexpected original dispatch after638')
    receipts=[rt.effective_receipt(r) for r in rows]
    for receipt in receipts:NativeSession.known(receipt,'settled_parent',require_valid=False)
    if read(REJECTION).get('decision')!='rejected':raise ValueError('actual primary world637 source rejection required')
    files=[old.ROOT/n for n in ['PREVIEW.json','PREPARED.json','USER_SCOPE.json','RUN_CLAIM.json','AUTHORIZATION.json',
        'CALL_LEDGER.json','STATE.json','DISPATCH_POLICY.json','RECOVERY_INDEX.json','WORLD_NATIVE.json',
        'call_637_world_framework_01.json','call_638_complete_script_01.json','recovery/call_638.json',
        'recovery/call_638_NATIVE_SCRIPT.json','recovery/STOP638_COMPLETE.json','recovery/RECONCILED638_SPEND_CHECKPOINT.json']]
    for ordinal in (637,638):
        files += [old.ROOT/f'call_evidence/call_{ordinal}'/n for n in ['IDENTITY.json','RESPONSE_BODY_MANIFEST.json','response_body.raw','REQUEST_BODY_MANIFEST.json','request_body.raw']]
    identity={'root':str(old.ROOT),'terminal_state_sha256':sha(old.ROOT/'STATE.json'),
        'native_ledger_sha256':sha(rt.ledger),'recovery_index_sha256':sha(old.ROOT/'RECOVERY_INDEX.json'),'end_ordinal':638}
    inherited={'calls_started':638,'reported_tokens':13463603,'calls_with_known_usage':636,'pending_ordinals':[70,160],'unknown_token_reservations':93117}
    return {'schema':VERSION+'/known638_spend_anchor','root':str(old.ROOT),'inherited':inherited,'parent_identity':identity,
        'original_source_files':{str(p):sha(p) for p in files},'original_body_slots_used':2,'original_body_limit':3,
        'remaining_body_slots':1,'original_review_slots_used':1,'original_review_limit':6,
        'world_candidates_before':1,'new_world_source_revision_limit':1,'old_director_capacity':old.DIRECTOR,
        'world637_content_rejected':True,'body638_not_adopted':True,'old_budget_reset':False,'authorizes_dispatch':False}


def seed():
    result=old.seed();result['fixed_scene']=read(FACTS)
    result['primary_body638_additional_failures']=read(EXTRA)
    result['old_complete_native_screenplay638']=read(old.ROOT/'recovery/call_638_NATIVE_SCRIPT.json')
    return result


def preview():
    parent=parent_certificate();brief=read(old.BRIEF);native_seed=seed()
    facts=read(FACTS)
    if sha(facts['source_path'])!=facts['source_sha256']:raise ValueError('selected fixed scene hash changed')
    item=story.prepare_world(brief,native_seed,read(old.PROFILE),read(old.ROOT/'WORLD_NATIVE.json'),read(REJECTION),facts)
    sources=old.sources()+[Path(__file__),Path(story.__file__),FACTS,REJECTION,EXTRA,
        PROJECT/'docs/H3_SCREENPLAY_WORLD_SOURCE_REPAIR_20261015.md',Path(facts['source_path'])]
    sources={str(p.resolve()):sha(p) for p in set(sources)}
    successors=[str(p) for p in policy.successor_paths(PROJECT,parent,digest(parent))]
    return {'schema':VERSION+'/preview','root':str(ROOT),'parent':parent,'brief':brief,'seed':native_seed,
        'facts':facts,'first_request':item,'source_files':sources,'stage_limits':LIMITS,
        'total_new_calls_limit':3,'successor_claim_paths':successors,
        'successor_already_exists':[p for p in successors if Path(p).exists()],
        'world_content_gate_required':True,'automatic_next_phase':False,'other_round11_modified':False,
        'provider_calls':0,'media_authorized':False,'old_budget_reset':False}


def prepare(approved):
    value=preview()
    if digest(value)!=approved:raise ValueError('primary-reviewed successor preview changed')
    if value['successor_already_exists'] or (ROOT/'PREPARED.json').exists():raise FileExistsError('existing successor/prepared cannot regrant')
    ROOT.mkdir(parents=True,exist_ok=True)
    write(ROOT/'PREVIEW.json',value,True)
    scope={'schema':VERSION+'/scope','preview_sha256':approved,'inherited':value['parent']['inherited'],
        'stage_limits':LIMITS,'world_candidate_limit_including637':2,'remaining_original_body_slots':1,
        'world_actual_primary_content_gate':True,'automatic_retry':False,'automatic_next_phase':False,'media_authorized':False,
        'old_director_capacity':old.DIRECTOR,'old_budget_reset':False}
    write(ROOT/'USER_SCOPE.json',scope,True)
    binding={'schema':VERSION+'/successor_claim','root':str(ROOT),'parent_anchor_sha256':digest(value['parent']),
        'parent_identity':value['parent']['parent_identity'],'authorization_sha256':sha(ROOT/'USER_SCOPE.json'),'old_budget_reset':False}
    for p in value['successor_claim_paths']:policy.new_claim(p,binding)
    write(ROOT/'PREPARED.json',{'preview_sha256':approved,'binding':binding,'source_files':value['source_files'],
        'parent_source_files':value['parent']['original_source_files'],'successor_claim_paths':value['successor_claim_paths']},True)
    rt=runtime();rt.prepare();return state(rt,'prepared')


def guard():
    prepared=read(ROOT/'PREPARED.json');value=read(ROOT/'PREVIEW.json')
    if digest(value)!=prepared['preview_sha256']:raise ValueError('frozen successor preview changed')
    old.guard()
    for p in prepared['successor_claim_paths']:
        if read(p)!=prepared['binding']:raise ValueError('unique successor binding changed')
    if sha(ROOT/'USER_SCOPE.json')!=prepared['binding']['authorization_sha256']:raise ValueError('successor scope changed')
    for p,expected in {**prepared['parent_source_files'],**prepared['source_files']}.items():
        if sha(p)!=expected:raise ValueError('source/consumption identity changed: '+p)
    return True


def world_decision_template():
    value=read(ROOT/'PREVIEW.json');world=read(ROOT/'WORLD_NATIVE.json')
    return {'schema':VERSION+'/primary_world_decision','decision':'accepted_for_body','review_actor':'primary_assistant_actual_text_and_fixed_asset_review',
        'world_file_sha256':sha(ROOT/'WORLD_NATIVE.json'),'world_native_sha256':digest(world),
        'brief_sha256':digest(value['brief']),'selected_scene_facts_sha256':sha(FACTS),
        'selected_scene_image_sha256':value['facts']['source_sha256'],'fixed_casting_sha256':digest(value['seed']['fixed_casting']),
        'actual_content_findings':[],'human_video_approval':None}


def check_control(stage):
    if (ROOT/'STOP.json').exists():raise RuntimeError('explicit STOP present; no new phase dispatch')
    if stage in ('complete_script','full_review'):
        decision=read(ROOT/'WORLD_PRIMARY_DECISION.json');template=world_decision_template()
        if any(decision.get(k)!=v for k,v in template.items() if k!='actual_content_findings'):
            raise RuntimeError('actual source-bound primary world decision not accepted')
        if not isinstance(decision.get('actual_content_findings'),list) or not decision['actual_content_findings']:
            raise RuntimeError('actual primary world review findings required, not empty template')
        snapshot=ROOT/'WORLD_PRIMARY_DECISION_SNAPSHOT.json'
        if snapshot.exists() and read(snapshot)!=decision:raise RuntimeError('primary world decision changed after phase claim')
    return True


def runtime():
    value=read(ROOT/'PREVIEW.json')
    return old.ScreenplayRuntime(PROJECT,ROOT,[Path(p) for p in value['source_files']],value['parent']['inherited'],
        profile=read(old.PROFILE),stage_limits=LIMITS,inherited_guard=guard,quota_state=None,shared_lock=ROOT/'DISPATCH.lock',
        admission=lambda label,wire,ledger:check_control(wire['stage']),client_factory_builder=old.clients.make_client_factory)


def state(rt,status,**details):
    value={'schema':VERSION+'/state','at':now(),'status':status,'spend':rt.summary(),
        'text_ready_for_director':False,'local_screenplay_review_accepted':status=='local_text_review_accepted',
        'human_quality_approved':False,'creative_quality_passed':False,'media_authorized':False,
        'old_director_capacity':old.DIRECTOR,'old_budget_reset':False,'other_round11_modified':False,**details}
    write(ROOT/'STATE.json',value);return value


def invoke(stage,label,item,validator):
    guard();check_control(stage)
    policy.new_claim(ROOT/f'{stage.upper()}_RUN_CLAIM.json',{'schema':VERSION+'/phase_claim','stage':stage,'pid':os.getpid(),
        'started_at':now(),'request_sha256':item['request_sha256'],'automatic_restart':False})
    if stage in ('complete_script','full_review'):
        snapshot=ROOT/'WORLD_PRIMARY_DECISION_SNAPSHOT.json';decision=read(ROOT/'WORLD_PRIMARY_DECISION.json')
        if snapshot.exists():
            if read(snapshot)!=decision:raise RuntimeError('primary world decision snapshot changed')
        else:write(snapshot,decision,True)
    write(ROOT/'requests'/f'{label}.json',item,True)
    return runtime().dispatch(label,item['request'],validator)


def phase(action):
    rt=runtime();value=read(ROOT/'PREVIEW.json');brief=value['brief'];native_seed=value['seed'];profile=read(old.PROFILE)
    try:
        if action=='world':
            item=value['first_request'];receipt=invoke('goal_plan','world_source_revision_02',item,lambda d:story.validate_world(d,brief,native_seed['fixed_casting']))
            document=NativeSession.known(receipt,'world_source_revision',require_valid=False)
            write(ROOT/'WORLD_NATIVE.json',document,True)
            if receipt['status']!='contract_valid':return state(rt,'halt_world_necessary_contract_rejected',receipt_ordinal=receipt['ordinal'])
            (ROOT/'WORLD_FRAMEWORK.md').write_text(story.render_world(document),encoding='utf8')
            return state(rt,'awaiting_primary_world_content_review',world_ordinal=receipt['ordinal'])
        world=read(ROOT/'WORLD_NATIVE.json')
        if action=='body':
            oldbody=read(old.ROOT/'recovery/call_638_NATIVE_SCRIPT.json')
            diag={'exact_contract_diagnostics':read(old.ROOT/'recovery/call_638.json')['effective_receipt']['validation'],
                'primary_content_diagnostics':read(EXTRA),'source_world637_rejection':read(REJECTION)}
            item=story.prepare_script(brief,world,native_seed,profile,oldbody,diag,value['facts'])
            receipt=invoke('complete_script','complete_script_final_02',item,lambda d:story.validate_script(d,brief,world))
            body=NativeSession.known(receipt,'final_complete_script',require_valid=False)
            write(ROOT/'NATIVE_SCRIPT.json',body,True)
            if receipt['status']!='contract_valid':return state(rt,'halt_final_body_contract_rejected',receipt_ordinal=receipt['ordinal'])
            (ROOT/'FULL_SCRIPT.md').write_text(story.render_script(body,world),encoding='utf8')
            return state(rt,'awaiting_same_source_full_review',script_ordinal=receipt['ordinal'])
        body=read(ROOT/'NATIVE_SCRIPT.json')
        latest=read(ROOT/'STATE.json')
        if latest['status']!='awaiting_same_source_full_review':raise RuntimeError('original valid final body state required')
        item=base.prepare_review(brief,world,body,native_seed,profile)
        receipt=invoke('full_review','full_review_final_02',item,lambda d:base.validate_review(d,brief,world,body))
        document=NativeSession.known(receipt,'same_source_full_review')
        write(ROOT/'NATIVE_FULL_REVIEW.json',document,True);decision=receipt['validation']
        return state(rt,'local_text_review_accepted' if decision['accepted'] else 'halt_full_review_not_accepted',review_ordinal=receipt['ordinal'],decision=decision)
    except Halt as error:return state(rt,error.status,**error.details)
    except Exception as error:
        write(ROOT/'LAST_STOP.json',{'at':now(),'action':action,'error_type':type(error).__name__,'error':str(error),'automatic_retry':False})
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['preview','prepare','world','world-decision-template','body','review','status'])
    parser.add_argument('--approve-preview-sha');parser.add_argument('--output');args=parser.parse_args()
    if args.action=='preview':result=preview()
    elif args.action=='prepare':result=prepare(args.approve_preview_sha)
    elif args.action=='world-decision-template':result=world_decision_template()
    elif args.action=='status':result=read(ROOT/'STATE.json')
    else:result=phase(args.action)
    if args.output:
        write(args.output,result);print(json.dumps({'saved':args.output,'sha256':digest(result),'status':result.get('status'),'provider_calls':result.get('provider_calls')},ensure_ascii=False))
    else:print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
