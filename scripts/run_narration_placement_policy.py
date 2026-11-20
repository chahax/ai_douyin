"""Bounded MiniMax narration decisions and an executable pre-video compile gate."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.content_factory import narration_placement_policy_v1 as policy

RUN=ROOT/'data/corpus_production_trials/20261113_narration_placement_v1'
MODEL='MiniMax-M3.1-Flash'


def demo_case():
    old=ROOT/'data/video_generation/h3_library_bound_next_minute_20261113_v1'
    selection=policy.read(old/'script_selection.json')
    manuscript=Path(selection['source']['path']).read_text(encoding='utf-8')
    segments={s['shot_id']:s for s in selection['segments']}
    n3=next(x['text'] for x in segments['S03']['ordered_source_items'] if x['kind']=='audio')
    n4=next(x['text'] for x in segments['S04']['ordered_source_items'] if x['kind']=='audio' and x['speaker']=='narrator')
    marker='**【旁白】** 现代写字楼'
    begin=manuscript.index(marker)+len('**【旁白】** ')
    opening=manuscript[begin:manuscript.index('\n',begin)]
    room='旧木凳上放着快见底的碘酒瓶'
    if room not in manuscript: raise ValueError('expected_original_environment_evidence_missing')
    quotes=[
        dict(id='N_OPEN',kind='narration',scene_id='SC_MEMORY',text=opening,fact_ids=['F_MEMORY']),
        dict(id='N_ROOM',kind='narration',scene_id='SC_CARE',text=room+'。',fact_ids=['F_ROOM']),
        dict(id='Q_PAIN',kind='dialogue',scene_id='SC_CARE',text='疼吗？',speaker_id='ye_yaner'),
        dict(id='Q_NOT_PAIN',kind='dialogue',scene_id='SC_CARE',text='不疼的，小六不疼。',speaker_id='ye_xijue'),
        dict(id='N_S03',kind='narration',scene_id='SC_CARE',text=n3,fact_ids=['F_INJURY']),
        dict(id='Q_NAN',kind='dialogue',scene_id='SC_CARE',text='大哥，上次你还没被他打够吗？',speaker_id='ye_nan'),
        dict(id='Q_GIRL',kind='dialogue',scene_id='SC_CARE',text='是啊，大哥，你打不过那个人渣的。',speaker_id='ye_yaner'),
        dict(id='N_S04',kind='narration',scene_id='SC_CARE',text=n4,fact_ids=['F_HUNGER'])]
    for quote in quotes:
        raw=room if quote['id']=='N_ROOM' else quote['text']
        start=manuscript.index(raw)
        quote['source_ref']=dict(document=selection['source'],start=start,end=start+len(raw),
            transform='append_chinese_period' if quote['id']=='N_ROOM' else 'identity')
    case=dict(schema=policy.CASE,source_refs_required=True,characters=dict(su_mo='苏墨',ye_yaner='叶嫣儿',ye_xijue='叶西决',ye_nan='叶南',ye_dong='叶东'),
        source_bindings=[selection['source'],policy.bind(old/'script_selection.json')],
        fixture_note='真实旧S03/S04旁白与原对白；为检验插叙打断，刻意将N_S03放在疼吗/不疼之间、N_S04放在两句劝阻之间。不是对旧片实际时间顺序的宣称。N_ROOM依据场景三原环境短句转述作动作间隙正例。',
        scenes=[dict(id='SC_MEMORY',context='回忆画面：苏墨升职后的现代写字楼与通勤人潮，尚未展示车祸。',items=['A_MEMORY','N_OPEN']),
            dict(id='SC_CARE',context='同一傍晚，孩子们共用的旧卧室；叶嫣儿给叶西决擦伤，叶东和叶南在场。',
                items=['A_BOTTLE','N_ROOM','Q_PAIN','N_S03','A_CARE','Q_NOT_PAIN','A_LEAVE','Q_NAN','N_S04','Q_GIRL','A_STOP'])],
        quotes=quotes,actions=[dict(id='A_MEMORY',scene_id='SC_MEMORY',text='写字楼外通勤人潮来往，镜头交代苏墨刚刚升职的背景。',duration_seconds=2),
            dict(id='A_BOTTLE',scene_id='SC_CARE',text='镜头从旧木凳上快见底的碘酒瓶移向正在擦伤的姐弟。',duration_seconds=2),
            dict(id='A_CARE',scene_id='SC_CARE',text='叶嫣儿动作极轻，用棉签点在青紫痕迹上。',duration_seconds=1),
            dict(id='A_LEAVE',scene_id='SC_CARE',text='叶东握拳，转身欲去找苏墨理论。',duration_seconds=1),
            dict(id='A_STOP',scene_id='SC_CARE',text='叶东的拳头停住，垂眼看自己和弟妹瘦弱的手腕。',duration_seconds=2)],
        facts=[dict(id='F_MEMORY',source_quote_ids=['N_OPEN'],known_by={'su_mo':['N_OPEN']},scene_open_allowed=True,temporal_scope='past_background'),
            dict(id='F_ROOM',source_quote_ids=['N_ROOM'],known_by={},scene_open_allowed=True,temporal_scope='present_environment'),
            dict(id='F_INJURY',source_quote_ids=['N_S03'],known_by={'ye_xijue':['N_S03']},scene_open_allowed=True,temporal_scope='past_personal_experience'),
            dict(id='F_HUNGER',source_quote_ids=['N_S04'],known_by={'ye_dong':['N_S04'],'ye_nan':['N_S04'],'ye_yaner':['N_S04'],'ye_xijue':['N_S04']},scene_open_allowed=True,temporal_scope='ongoing_shared_condition')],
        dialogue_groups=[dict(id='G_CARE',scene_id='SC_CARE',quote_ids=['Q_PAIN','Q_NOT_PAIN'],semantic_relation='姐姐问疼吗，弟弟忍痛回答；即使夹旁白和擦伤动作仍是一组问答。'),
            dict(id='G_WARN',scene_id='SC_CARE',quote_ids=['Q_NAN','Q_GIRL'],semantic_relation='叶南与叶嫣儿连续劝阻愤怒的叶东，旁白不应把两句劝阻拆开。')])
    policy.validate_case(case)
    return case


def prepare(run, case):
    policy.validate_case(case)
    policy.freeze(run/'CASE.json',case)
    policy.freeze(run/'PLAN.json',dict(schema=policy.VERSION,case=policy.bind(run/'CASE.json'),max_new_calls=4,
        model=MODEL,reasoning_effort='medium',thinking='adaptive',native_stream=True,include_usage=True,
        automatic_transport_retries=0,media_calls=0,publication=False,global_defaults_changed=False))
    return dict(status='prepared_no_call',case=policy.bind(run/'CASE.json'))


def native_call(run, case, phase, candidate=None, issues=None):
    from src.content_factory.creative_workflow_roles import role_config
    from src.content_factory.serial_story_transport_v6 import selected_endpoint
    calls=sorted(run.glob('calls/C*/START.json'))
    if len(calls)>=4: raise ValueError('narration_trial_four_call_bound_reached')
    for started in calls:
        if not (started.parent/'RESPONSE.json').exists(): raise ValueError('prior_native_call_unknown_do_not_replay')
    cfg=role_config('writer'); endpoint=selected_endpoint('writer',cfg,None)
    folder=run/'calls'/('C%03d'%(len(calls)+1)); folder.mkdir(parents=True,exist_ok=False)
    args=dict(model=MODEL,messages=policy.messages(case,phase=phase,candidate=candidate,issues=issues),
        max_completion_tokens=12000,reasoning_effort='medium',extra_body=dict(thinking=dict(type='adaptive'),reasoning_split=True),
        stream=True,stream_options=dict(include_usage=True))
    policy.freeze(folder/'REQUEST.json',dict(role='writer',base_url=endpoint,args=args,phase=phase))
    policy.freeze(folder/'START.json',dict(status='in_flight',new_call_index=len(calls)+1,unknown_replay=False))
    try:
        completed=subprocess.run([sys.executable,str(ROOT/'scripts/serial_native_worker_v6.py'),str(folder)],cwd=ROOT,
            capture_output=True,timeout=420)
    except subprocess.TimeoutExpired:
        policy.freeze(folder/'PARENT_OUTCOME.json',dict(status='outcome_unknown',reason='bounded_worker_timeout',replay=False))
        raise ValueError('native_outcome_unknown') from None
    if completed.returncode or not (folder/'RESPONSE.json').exists():
        policy.freeze(folder/'PARENT_OUTCOME.json',dict(status='outcome_unknown',exit_code=completed.returncode,replay=False))
        raise ValueError('native_outcome_unknown')
    response=policy.read(folder/'RESPONSE.json'); choices=response.get('choices',[]); usage=response.get('usage') or {}
    known=bool(len(choices)==1 and choices[0].get('finish_reason') in ('stop','length') and usage)
    reconciles=all(type(usage.get(k)) is int and usage[k]>=0 for k in ('prompt_tokens','completion_tokens','total_tokens')) and usage.get('total_tokens')==usage.get('prompt_tokens',0)+usage.get('completion_tokens',0)
    status='complete' if known and reconciles and response.get('model','').lower()==MODEL.lower() and choices[0]['finish_reason']=='stop' else 'response_rejected'
    policy.freeze(folder/'VALIDATION.json',dict(status=status,model=response.get('model'),finish_reason=choices[0].get('finish_reason') if choices else None,
        usage=usage,phase=phase,stream_chunks=policy.bind(folder/'CHUNKS.jsonl'),private_reasoning_not_interpreted=True))
    if status!='complete': raise ValueError('native_response_not_accepted_no_blind_replay')
    text=choices[0]['message'].get('content','')
    try: value=json.loads(text)
    except json.JSONDecodeError:
        return None,dict(code='invalid_JSON',raw_response=policy.bind(folder/'RESPONSE.json'))
    policy.freeze(folder/'PARSED.json',value)
    return value,None


def judge(run):
    plan=policy.read(run/'PLAN.json'); case=policy.read(policy.checked(plan['case']))
    if (run/'RECEIPT.json').exists(): return dict(status='already_accepted_no_call',receipt=policy.bind(run/'RECEIPT.json'))
    if list(run.glob('calls/C*/START.json')):
        raise ValueError('existing_trial_calls_preserved_use_new_explicit_resume_not_blind_restart')
    candidate=None; review=None; issues=None; phase='judge'
    for _ in range(4):
        value,error=native_call(run,case,phase,candidate,issues)
        if phase=='review':
            review=value
            issues=[error] if error else policy.validate_review(case,candidate,review)
            if not issues:
                receipt=dict(schema=policy.RECEIPT,status='accepted',case_sha256=policy.digest(case),candidate=candidate,semantic_review=review,
                    native_calls=[policy.bind(p) for p in sorted(run.glob('calls/C*/RESPONSE.json'))],global_defaults_changed=False,
                    semantic_verification='independent_minimax_review_not_video_or_acoustic_acceptance')
                policy.freeze(run/'RECEIPT.json',receipt)
                return dict(status='accepted',receipt=policy.bind(run/'RECEIPT.json'))
            phase='repair'
        else:
            candidate=value
            issues=[error] if error else policy.validate_decisions(case,candidate)
            phase='repair' if issues else 'review'
    policy.freeze(run/'UNRESOLVED.json',dict(status='needs_semantic_repair',candidate=candidate,issues=issues,
        remaining_calls=0,manual_confirmation_requested=False,media_dispatch_allowed=False))
    return dict(status='needs_semantic_repair',evidence=policy.bind(run/'UNRESOLVED.json'))


def compile_gate(run):
    plan=policy.read(run/'PLAN.json'); case=policy.read(policy.checked(plan['case']))
    receipt=policy.read(run/'RECEIPT.json'); compiled=policy.compile_before_video(case,receipt)
    policy.freeze(run/'VIDEO_COMPILATION.json',compiled)
    target=run/'VIDEO_PROMPT.txt'; text=compiled['compiled_prompt']
    if target.exists() and target.read_text(encoding='utf-8')!=text: raise ValueError('frozen_video_prompt_changed')
    if not target.exists(): target.write_text(text,encoding='utf-8')
    return dict(status='compiled_after_narration_gate',compilation=policy.bind(run/'VIDEO_COMPILATION.json'),prompt=policy.bind(target),
        audio_items=compiled['audio_items'],global_defaults_changed=False,media_dispatched=False)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['prepare-demo','prepare','judge','compile'])
    p.add_argument('--run',type=Path,default=RUN);p.add_argument('--case',type=Path)
    a=p.parse_args(argv)
    if a.action=='prepare-demo': value=prepare(a.run,demo_case())
    elif a.action=='prepare':
        if not a.case:p.error('prepare requires --case')
        value=prepare(a.run,policy.read(a.case))
    elif a.action=='judge':value=judge(a.run)
    else:value=compile_gate(a.run)
    print(json.dumps(value,ensure_ascii=False,indent=2))


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
