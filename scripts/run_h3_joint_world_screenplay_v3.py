"""Final remaining complete native body, then one separately gated full review."""
import argparse
import json
import os
from pathlib import Path
import sys
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from scripts import run_h3_world_source_repair_v2 as previous
from scripts import run_h3_screenplay_world_revision_v1 as old
from scripts import creative_scope_probe_execution_policy_v1 as policy
from scripts.creative_fresh_source_session_v1 import Session as NativeSession,Halt
from src.content_factory import creative_joint_world_screenplay_v3 as story
from src.content_factory import creative_screenplay_world_source_repair_v2 as render

ROOT=old.ROOT.parent/'text_final'
VERSION='h3_joint_world_screenplay/v3'
LIMITS={'goal_plan':0,'goal_audit':0,'complete_script':1,'full_review':1}
read,write,digest,sha,now=old.read,old.write,old.digest,old.sha,old.now


def parent_certificate():
    previous.guard();rt=previous.runtime();summary=rt.summary()
    if any(summary.get(k)!=v for k,v in {'effective_calls_started':639,'effective_reported_tokens':13497072,
        'effective_calls_with_known_usage':637,'unknown_token_reservations':93117,'new_unknown_token_reservations':0}.items()):
        raise ValueError('latest known639 consumption differs')
    if not (previous.ROOT/'STOP.json').is_file() or read(previous.ROOT/'WORLD_PRIMARY_DECISION.json').get('decision')!='rejected':
        raise ValueError('previous639 world must retain original STOP and actual content rejection')
    ledger=read(rt.ledger)
    if len(ledger['calls'])!=1 or ledger['calls'][0]['ordinal']!=639:raise ValueError('previous source run has unexpected downstream dispatch')
    NativeSession.known(rt.effective_receipt(ledger['calls'][0]),'settled639')
    names=['PREVIEW.json','PREPARED.json','USER_SCOPE.json','AUTHORIZATION.json','DISPATCH_POLICY.json','CALL_LEDGER.json',
        'GOAL_PLAN_RUN_CLAIM.json','STATE.json','WORLD_NATIVE.json','WORLD_PRIMARY_DECISION.json','STOP.json',
        'call_639_world_source_revision_02.json']
    names += ['call_evidence/call_639/'+n for n in ['IDENTITY.json','RESPONSE_BODY_MANIFEST.json','response_body.raw','REQUEST_BODY_MANIFEST.json','request_body.raw']]
    files={**read(previous.ROOT/'PREPARED.json')['parent_source_files'],
        **{str(previous.ROOT/n):sha(previous.ROOT/n) for n in names}}
    identity={'root':str(previous.ROOT),'terminal_state_sha256':sha(previous.ROOT/'STATE.json'),
        'native_ledger_sha256':sha(rt.ledger),'world_rejection_sha256':sha(previous.ROOT/'WORLD_PRIMARY_DECISION.json'),'end_ordinal':639}
    return {'schema':VERSION+'/settled639_anchor','root':str(previous.ROOT),'parent_identity':identity,
        'inherited':{'calls_started':639,'reported_tokens':13497072,'calls_with_known_usage':637,
            'pending_ordinals':[70,160],'unknown_token_reservations':93117},'original_source_files':files,
        'original_body_slots_used':2,'original_body_limit':3,'remaining_body_slots':1,'review_calls_this_run_limit':1,
        'world_components_before':2,'world_components_including_this':3,'old_director_capacity':old.DIRECTOR,
        'authorizes_dispatch':False,'old_budget_reset':False}


def history():
    return {'original_world637':read(old.ROOT/'WORLD_NATIVE.json'),'primary_rejection637':read(previous.REJECTION),
        'original_complete_screenplay638':read(old.ROOT/'recovery/call_638_NATIVE_SCRIPT.json'),
        'contract_diagnostics638':read(old.ROOT/'recovery/call_638.json')['effective_receipt']['validation'],
        'primary_body638_content_diagnosis':read(previous.EXTRA),
        'original_world639':read(previous.ROOT/'WORLD_NATIVE.json'),
        'primary_rejection639':read(previous.ROOT/'WORLD_PRIMARY_DECISION.json')}


def preview():
    parent=parent_certificate();brief=read(old.BRIEF);seed=previous.seed();facts=read(previous.FACTS);hist=history()
    item=story.prepare_joint(brief,seed,read(old.PROFILE),hist,facts)
    old.clients.expected_wire_request(item['request'])
    sources={**read(previous.ROOT/'PREVIEW.json')['source_files'],
        **{str(p):sha(p) for p in [Path(__file__),Path(story.__file__),PROJECT/'docs/H3_COMPLETE_WORLD_SCREENPLAY_FINAL_REVISION_20261015.md']}}
    successors=[str(p) for p in policy.successor_paths(PROJECT,parent,digest(parent))]
    return {'schema':VERSION+'/preview','root':str(ROOT),'parent':parent,'brief':brief,'seed':seed,'facts':facts,
        'history':hist,'first_request':item,'source_files':sources,'stage_limits':LIMITS,
        'successor_claim_paths':successors,'successor_already_exists':[p for p in successors if Path(p).exists()],
        'total_new_calls_limit':2,'new_separate_world_calls':0,'world_component_history_total':3,
        'other_round11_modified':False,'provider_calls':0,'media_authorized':False,'old_budget_reset':False}


def prepare(approved):
    value=preview()
    if digest(value)!=approved:raise ValueError('reviewed final joint preview changed')
    if value['successor_already_exists'] or (ROOT/'PREPARED.json').exists():raise FileExistsError('existing successor cannot regrant final body')
    ROOT.mkdir(parents=True,exist_ok=True);write(ROOT/'PREVIEW.json',value,True)
    scope={'schema':VERSION+'/scope','preview_sha256':approved,'inherited':value['parent']['inherited'],'stage_limits':LIMITS,
        'world_components_including_this':3,'remaining_original_body_slots':1,'automatic_retry':False,
        'automatic_next_phase':False,'media_authorized':False,'old_director_capacity':old.DIRECTOR,'old_budget_reset':False}
    write(ROOT/'USER_SCOPE.json',scope,True)
    binding={'schema':VERSION+'/successor_claim','root':str(ROOT),'parent_anchor_sha256':digest(value['parent']),
        'parent_identity':value['parent']['parent_identity'],'authorization_sha256':sha(ROOT/'USER_SCOPE.json'),'old_budget_reset':False}
    for p in value['successor_claim_paths']:policy.new_claim(p,binding)
    write(ROOT/'PREPARED.json',{'preview_sha256':approved,'source_files':value['source_files'],
        'parent_files':value['parent']['original_source_files'],'binding':binding,'successor_claim_paths':value['successor_claim_paths']},True)
    rt=runtime();rt.prepare();return state(rt,'prepared')


def guard():
    previous.guard();value=read(ROOT/'PREVIEW.json');prepared=read(ROOT/'PREPARED.json')
    if digest(value)!=prepared['preview_sha256'] or sha(ROOT/'USER_SCOPE.json')!=prepared['binding']['authorization_sha256']:
        raise ValueError('final joint reviewed source/scope changed')
    for p in prepared['successor_claim_paths']:
        if read(p)!=prepared['binding']:raise ValueError('unique final successor changed')
    for p,expected in {**prepared['source_files'],**prepared['parent_files']}.items():
        if sha(p)!=expected:raise ValueError('final source/inherited bytes changed: '+p)
    return True


def decision_template():
    value=read(ROOT/'PREVIEW.json');parent=read(ROOT/'NATIVE_JOINT_SCRIPT.json')
    return {'schema':VERSION+'/primary_joint_decision','decision':'accepted_for_full_review',
        'native_parent_file_sha256':sha(ROOT/'NATIVE_JOINT_SCRIPT.json'),'native_parent_canonical_sha256':digest(parent),
        'world_pointer':'/world','script_pointer':'/screenplay','brief_sha256':digest(value['brief']),
        'selected_scene_facts_sha256':sha(previous.FACTS),'fixed_casting_sha256':digest(value['seed']['fixed_casting']),
        'actual_content_findings':[],'human_video_approval':None}


def control(stage):
    if (ROOT/'STOP.json').exists():raise RuntimeError('final run STOP; no dispatch')
    if stage=='full_review':
        decision=read(ROOT/'PRIMARY_JOINT_DECISION.json');expected=decision_template()
        if any(decision.get(k)!=v for k,v in expected.items() if k!='actual_content_findings'):
            raise RuntimeError('actual full native parent primary review not accepted')
        if not isinstance(decision.get('actual_content_findings'),list) or not decision['actual_content_findings']:
            raise RuntimeError('actual complete primary review findings missing')
    return True


def runtime():
    value=read(ROOT/'PREVIEW.json')
    return old.ScreenplayRuntime(PROJECT,ROOT,[Path(p) for p in value['source_files']],value['parent']['inherited'],
        profile=read(old.PROFILE),stage_limits=LIMITS,inherited_guard=guard,quota_state=None,
        shared_lock=ROOT/'DISPATCH.lock',admission=lambda label,wire,ledger:control(wire['stage']),client_factory_builder=old.clients.make_client_factory)


def state(rt,status,**details):
    value={'schema':VERSION+'/state','at':now(),'status':status,'spend':rt.summary(),
        'text_ready_for_director':False,'local_screenplay_review_accepted':status=='local_text_review_accepted',
        'human_quality_approved':False,'creative_quality_passed':False,'media_authorized':False,
        'old_director_capacity':old.DIRECTOR,'old_budget_reset':False,'other_round11_modified':False,**details}
    write(ROOT/'STATE.json',value);return value


def invoke(stage,label,item,validator):
    guard();control(stage)
    policy.new_claim(ROOT/f'{stage.upper()}_RUN_CLAIM.json',{'schema':VERSION+'/phase_claim','pid':os.getpid(),
        'started_at':now(),'request_sha256':item['request_sha256'],'automatic_restart':False})
    write(ROOT/'requests'/f'{label}.json',item,True)
    return runtime().dispatch(label,item['request'],validator)


def phase(action):
    rt=runtime();value=read(ROOT/'PREVIEW.json');brief=value['brief'];seed=value['seed']
    try:
        if action=='body':
            receipt=invoke('complete_script','complete_joint_screenplay_final_03',value['first_request'],lambda d:story.validate_joint(d,brief,seed['fixed_casting']))
            parent=NativeSession.known(receipt,'complete_joint_native',require_valid=False)
            path=ROOT/'NATIVE_JOINT_SCRIPT.json';write(path,parent,True)
            write(ROOT/'BODY_NECESSARY_DECISION.json',receipt.get('validation'),True)
            if receipt['status']!='contract_valid':return state(rt,'halt_final_joint_necessary_contract_rejected',receipt_ordinal=receipt['ordinal'])
            mapping={**story.identity_mapping(parent),'native_parent_file_path':str(path),'native_parent_file_sha256':sha(path)}
            write(ROOT/'NATIVE_IDENTITY_MAP.json',mapping,True)
            write(ROOT/'DERIVED_VALIDATION_VIEW.json',{'schema':VERSION+'/derived_validation_view','native':False,
                'derivation':mapping,'screenplay_with_mechanical_identity':story.validation_view(parent)},True)
            (ROOT/'WORLD_FRAMEWORK.md').write_text(render.render_world(parent['world']),encoding='utf8')
            (ROOT/'FULL_SCRIPT.md').write_text(render.render_script(parent['screenplay'],parent['world']),encoding='utf8')
            return state(rt,'awaiting_primary_joint_content_review',body_ordinal=receipt['ordinal'])
        if read(ROOT/'STATE.json')['status']!='awaiting_primary_joint_content_review':raise RuntimeError('necessary valid native parent required')
        parent=read(ROOT/'NATIVE_JOINT_SCRIPT.json')
        hist={k:v for k,v in value['history'].items() if 'original_' not in k}
        item=story.prepare_review(brief,parent,seed,read(old.PROFILE),hist,value['facts'])
        receipt=invoke('full_review','joint_full_review_final_03',item,lambda d:story.validate_review(d,brief,parent))
        document=NativeSession.known(receipt,'joint_same_source_full_review')
        write(ROOT/'NATIVE_FULL_REVIEW.json',document,True);write(ROOT/'REVIEW_DECISION.json',receipt['validation'],True)
        return state(rt,'local_text_review_accepted' if receipt['validation']['accepted'] else 'halt_final_full_review_rejected',review_ordinal=receipt['ordinal'])
    except Halt as error:return state(rt,error.status,**error.details)
    except Exception as error:
        write(ROOT/'LAST_STOP.json',{'at':now(),'action':action,'error_type':type(error).__name__,'error':str(error),'automatic_retry':False})
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['preview','prepare','body','review','decision-template','status'])
    parser.add_argument('--approve-preview-sha');parser.add_argument('--output');args=parser.parse_args()
    if args.action=='preview':result=preview()
    elif args.action=='prepare':result=prepare(args.approve_preview_sha)
    elif args.action=='decision-template':result=decision_template()
    elif args.action=='status':result=read(ROOT/'STATE.json')
    else:result=phase(args.action)
    if args.output:write(args.output,result);print(json.dumps({'saved':args.output,'sha256':digest(result),'provider_calls':result.get('provider_calls'),'status':result.get('status')},ensure_ascii=False))
    else:print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
