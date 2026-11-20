"""Two explicitly authorized new text calls after preserved v1 trial C001–4."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.content_factory import narration_placement_policy_v2 as p

RUN=ROOT/'data/corpus_production_trials/20261113_narration_placement_v1'
MODEL='MiniMax-M3.1-Flash'


def case_v2():
    spec=importlib.util.spec_from_file_location('old_narration_cli',ROOT/'scripts/run_narration_placement_policy.py')
    old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    case=old.demo_case();case['placement_contract']=p.VERSION
    old_fact=next(f for f in case['facts'] if f['id']=='F_INJURY');case['facts'].remove(old_fact)
    case['facts'] += [dict(id='F_INJURY_PHYSICAL',claim='叶西决被踹后倒地、疼得半天起不来，路人扔给他面包，他拿回了面包。',
        epistemic_type='observed_event',source_quote_ids=['N_S03'],known_by={'ye_xijue':['N_S03']},scene_open_allowed=True),
        dict(id='F_STRANGER_MOTIVE',claim='路人是因为看他可怜而给面包；这属于他人的内心动机。',epistemic_type='other_mind',
            source_quote_ids=['N_S03'],known_by={},scene_open_allowed=True),
        dict(id='F_NARRATIVE_EVAL',claim='这块面包被叙述者评价为当天唯一上贡给苏墨的战利品。',epistemic_type='narrative_evaluation',
            source_quote_ids=['N_S03'],known_by={},scene_open_allowed=True)]
    for fact in case['facts']:
        if 'epistemic_type' not in fact:
            fact['epistemic_type']='shared_physical_condition' if fact['id']=='F_HUNGER' else 'background'
            fact['claim']=next(q['text'] for q in case['quotes'] if q['id']==fact['source_quote_ids'][0])
    for q in case['quotes']:
        if q['id']=='N_S03':q['fact_ids']=['F_INJURY_PHYSICAL','F_STRANGER_MOTIVE','F_NARRATIVE_EVAL'];q['allowed_slot_ids']=['GAP:A_LEAVE','GAP:A_STOP']
        if q['id']=='N_S04':q['allowed_slot_ids']=['GAP:A_STOP']
    p.validate_case(case);return case


def prepare(run):
    calls=sorted(run.glob('calls/C*/RESPONSE.json'))
    if len(calls)!=4 or any(not (q.parent/'VALIDATION.json').exists() for q in calls):raise ValueError('four_preserved_complete_prior_calls_required')
    case=case_v2();p.freeze(run/'CASE_V2.json',case)
    p.freeze(run/'SUPPLEMENT_AUTHORIZATION.json',dict(schema=p.VERSION,case=p.bind(run/'CASE_V2.json'),
        preserved_case=p.bind(run/'CASE.json'),preserved_unresolved=p.bind(run/'UNRESOLVED.json'),preserved_calls=[p.bind(c) for c in calls],
        authorization='Root explicitly authorized two more MiniMax text calls, total cap 4 to 6, after user unrestricted MiniMax authorization.',
        max_total_calls=6,max_new_calls=2,model=MODEL,reasoning_effort='medium',thinking='adaptive',media_calls=0,global_defaults_changed=False))
    return dict(status='supplement_prepared_no_call',case=p.bind(run/'CASE_V2.json'))


def call(run,case,phase,candidate=None):
    from src.content_factory.creative_workflow_roles import role_config
    from src.content_factory.serial_story_transport_v6 import selected_endpoint
    auth=p.read(run/'SUPPLEMENT_AUTHORIZATION.json')
    for b in auth['preserved_calls']:p.checked(b)
    starts=sorted(run.glob('calls/C*/START.json'))
    if len(starts) not in (4,5) or any(not (s.parent/'RESPONSE.json').exists() for s in starts):raise ValueError('total_six_cap_or_unknown_do_not_replay')
    cfg=role_config('writer');endpoint=selected_endpoint('writer',cfg,None)
    folder=run/'calls'/('C%03d'%(len(starts)+1));folder.mkdir(exist_ok=False)
    args=dict(model=MODEL,messages=p.messages(case,phase=phase,candidate=candidate),max_completion_tokens=12000,
        reasoning_effort='medium',extra_body=dict(thinking=dict(type='adaptive'),reasoning_split=True),stream=True,stream_options=dict(include_usage=True))
    p.freeze(folder/'REQUEST.json',dict(role='writer',base_url=endpoint,args=args,phase=phase,case=p.bind(run/'CASE_V2.json'),authorization=p.bind(run/'SUPPLEMENT_AUTHORIZATION.json')))
    p.freeze(folder/'START.json',dict(status='in_flight',new_call_index=len(starts)+1,unknown_replay=False))
    try:completed=subprocess.run([sys.executable,str(ROOT/'scripts/serial_native_worker_v6.py'),str(folder)],cwd=ROOT,capture_output=True,timeout=420)
    except subprocess.TimeoutExpired:
        p.freeze(folder/'PARENT_OUTCOME.json',dict(status='outcome_unknown',replay=False));raise ValueError('native_outcome_unknown') from None
    if completed.returncode or not (folder/'RESPONSE.json').exists():raise ValueError('native_outcome_unknown_preserve_no_retry')
    response=p.read(folder/'RESPONSE.json');choice=response.get('choices',[{}])[0];usage=response.get('usage') or {}
    valid=(choice.get('finish_reason')=='stop' and response.get('model','').lower()==MODEL.lower()
        and all(type(usage.get(k)) is int and usage[k]>=0 for k in ('prompt_tokens','completion_tokens','total_tokens'))
        and usage['total_tokens']==usage['prompt_tokens']+usage['completion_tokens'])
    p.freeze(folder/'VALIDATION.json',dict(status='complete' if valid else 'response_rejected',phase=phase,model=response.get('model'),
        usage=usage,finish_reason=choice.get('finish_reason'),stream_chunks=p.bind(folder/'CHUNKS.jsonl'),private_reasoning_not_interpreted=True))
    if not valid:raise ValueError('native_response_rejected_preserve_no_retry')
    try:value=json.loads(choice['message']['content'])
    except (KeyError,json.JSONDecodeError):raise ValueError('native_JSON_invalid_no_remaining_blind_retry') from None
    p.freeze(folder/'PARSED.json',value);return value


def judge(run):
    if (run/'RECEIPT_V2.json').exists():return dict(status='already_accepted',receipt=p.bind(run/'RECEIPT_V2.json'))
    if len(list(run.glob('calls/C*/START.json')))!=4:raise ValueError('supplement_must_start_after_exact_old_four_no_replay')
    auth=p.read(run/'SUPPLEMENT_AUTHORIZATION.json');case=p.read(p.checked(auth['case']))
    candidate=call(run,case,'judge');issues=p.validate_decisions(case,candidate)
    if issues:
        p.freeze(run/'UNRESOLVED_V2.json',dict(status='needs_semantic_repair',candidate=candidate,issues=issues,media_dispatch_allowed=False))
        return dict(status='needs_semantic_repair',issues=issues)
    review=call(run,case,'review',candidate);issues=p.validate_review(case,candidate,review)
    if issues:
        p.freeze(run/'UNRESOLVED_V2.json',dict(status='needs_semantic_repair',candidate=candidate,review=review,issues=issues,media_dispatch_allowed=False))
        return dict(status='needs_semantic_repair',issues=issues)
    receipt=dict(schema=p.base.RECEIPT,placement_contract=p.VERSION,status='accepted',case_sha256=p.digest(case),candidate=candidate,
        semantic_review=review,native_calls=[p.bind(run/'calls'/sid/'RESPONSE.json') for sid in ('C005','C006')],
        model_semantics_reviewed=True,independent_agent_semantic_review=None,media_dispatch_allowed=False,global_defaults_changed=False)
    p.freeze(run/'RECEIPT_V2.json',receipt)
    compilation=p.compile_before_video(case,receipt);p.freeze(run/'VIDEO_COMPILATION_V2.json',compilation)
    return dict(status='accepted_text_contract',receipt=p.bind(run/'RECEIPT_V2.json'),compilation=p.bind(run/'VIDEO_COMPILATION_V2.json'),
        decisions=[{k:r[k] for k in ('source_quote_id','classification','slot_id')} for r in candidate['decisions']],media_dispatched=False)


def normalize_review(run):
    if len(list(run.glob('calls/C*/START.json')))!=5:raise ValueError('explicit_normalization_only_after_known_C005_before_C006')
    case=p.read(p.checked(p.read(run/'SUPPLEMENT_AUTHORIZATION.json')['case']))
    raw=p.read(run/'calls/C005/PARSED.json');candidate,normalization=p.normalize_native_shape(case,raw)
    p.freeze(run/'NORMALIZED_C005.json',candidate)
    p.freeze(run/'NATIVE_NORMALIZATION.json',dict(normalization,raw=p.bind(run/'calls/C005/PARSED.json'),derived=p.bind(run/'NORMALIZED_C005.json'),
        authorization='Root explicitly approved only the finite enum aliases and exact oral-string wrapping before independent C006 review.'))
    review=call(run,case,'review',candidate);issues=p.validate_review(case,candidate,review)
    if issues:
        p.freeze(run/'NORMALIZED_REVIEW_UNRESOLVED.json',dict(status='needs_semantic_repair',issues=issues,media_dispatch_allowed=False))
        return dict(status='needs_semantic_repair',issues=issues)
    receipt=dict(schema=p.base.RECEIPT,placement_contract=p.VERSION,status='accepted',case_sha256=p.digest(case),candidate=candidate,semantic_review=review,
        normalization=p.bind(run/'NATIVE_NORMALIZATION.json'),native_calls=[p.bind(run/'calls'/sid/'RESPONSE.json') for sid in ('C005','C006')],
        model_semantics_reviewed=True,independent_agent_semantic_review=None,media_dispatch_allowed=False,global_defaults_changed=False)
    p.freeze(run/'RECEIPT_V2.json',receipt);compilation=p.compile_before_video(case,receipt);p.freeze(run/'VIDEO_COMPILATION_V2.json',compilation)
    return dict(status='accepted_normalized_text_contract',receipt=p.bind(run/'RECEIPT_V2.json'),compilation=p.bind(run/'VIDEO_COMPILATION_V2.json'),media_dispatched=False)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['prepare','judge','normalize-review']);parser.add_argument('--run',type=Path,default=RUN)
    a=parser.parse_args(argv)
    if a.run.resolve()!=RUN.resolve():parser.error('supplement is bound to this preserved six-call trial')
    value=prepare(a.run) if a.action=='prepare' else normalize_review(a.run) if a.action=='normalize-review' else judge(a.run)
    print(json.dumps(value,ensure_ascii=False,indent=2))


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
