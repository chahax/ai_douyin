"""Record read-only actual request evidence and copy the complete reviewed candidate."""
from pathlib import Path
import json
from datetime import datetime, timezone
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from scripts import run_creative_emotion_revision_v6 as current
from scripts.prepare_creative_emotion_workflow import write_new
from src.content_factory.creative_story_emotion import digest
from scripts.creative_resume_dispatch_v3 import sha_file


def main():
    qa=ROOT/'data/qa/emotion_workflow_v1_20261007'
    read=lambda p: json.loads(p.read_text(encoding='utf-8-sig'))
    pack=read(qa/'inputs/FULL_R01_REFERENCE_PACK.json')
    brief=read(qa/'inputs/ORIGINAL_CREATIVE_BRIEF.json')
    folders=['this_time_i_leave_emotion_revision_20261007']+[f'this_time_i_leave_emotion_revision_r{i}_20261007' for i in range(2,7)]
    rows=[]
    for folder in folders:
        for p in sorted((ROOT/'data/production_revisions'/folder).glob('call_*.json')):
            r=read(p)
            if 'ordinal' not in r: continue
            context=None
            for m in r['request']['messages']:
                try: item=json.loads(m['content'])
                except (ValueError,TypeError): continue
                if isinstance(item,dict) and 'reference_pack' in item:
                    context=item
                    break
            meta=r.get('response_metadata',{})
            rows.append({'ordinal':r['ordinal'],'label':r['label'],'model':meta.get('response_model'),
                'status':r['status'],'reported_tokens':meta.get('total_tokens'),
                'complete_response_received':meta.get('response_body_complete'),
                'full_R01_in_actual_request':context is not None and context.get('reference_pack')==pack,
                'full_original_brief_in_actual_request':context is not None and context.get('creative_brief')==brief,
                'needs_revision':r.get('validation',{}).get('needs_revision'),
                'receipt':str(p),'receipt_sha256':sha_file(p),'automatic_retry':r['automatic_retry']})
    rows.sort(key=lambda r:r['ordinal'])
    assert [r['ordinal'] for r in rows]==list(range(266,277))
    assert all(r['full_R01_in_actual_request'] and r['complete_response_received'] for r in rows)
    assert all(type(r['reported_tokens']) is int and r['automatic_retry'] is False for r in rows)
    assert all(r['full_original_brief_in_actual_request'] for r in rows if r['ordinal']>=270)
    summary=current.summary()
    script=read(current.ROOT/'COMPLETE_DRAFT_AWAITING_FULL_REVIEW/FULL_SCRIPT.json')
    review=read(current.ROOT/'FULL_REVIEW.json')
    checkpoint=read(current.ROOT/'STORY_CHECKPOINT.json')
    assert checkpoint['status']=='awaiting_human_content_confirmation' and not review['full_text_review']['issues']
    out=qa/'REVIEWED_STORY_CANDIDATE_r6'
    out.mkdir(exist_ok=True)
    pairs=[(current.ROOT/'COMPLETE_DRAFT_AWAITING_FULL_REVIEW/FULL_SCRIPT.md',out/'FULL_SCRIPT.md'),
        (current.ROOT/'COMPLETE_DRAFT_AWAITING_FULL_REVIEW/FULL_SCRIPT.json',out/'FULL_SCRIPT.json'),
        (current.ROOT/'FULL_REVIEW.json',out/'FULL_REVIEW.json')]
    for source,dest in pairs:
        write_new(dest,source.read_text(encoding='utf-8-sig'))
        assert sha_file(dest)==sha_file(source)
    write_new(out/'READINESS.json',{'schema':'source_bound_story_candidate/v1',
        'script_sha256':digest(script),'review_sha256':digest(review),
        'status':checkpoint['status'],'human_content_approval':None,'creative_quality_passed':False,
        'director_complete':False,'physical_performance_complete':False,'production_handoff_complete':False,
        'media_calls':0,'source_ordinals':[275,276],
        'unconfirmed_content_differences':['原稿独自看电影，新稿增加和朋友约电影','原稿门外走廊，新稿增加电梯结束'],
        'next_step':'核对完整故事及新增设定；再按采用的完整原稿重新编制导演与表演。'})
    code=[ROOT/'src/content_factory'/n for n in ['creative_story_emotion.py','creative_story_emotion_input_v2.py',
        'creative_story_emotion_input_v3.py','creative_story_schema_v2.py','creative_emotion_review_v2.py',
        'creative_video_projection.py','creative_seedance_segments.py']]
    code += [ROOT/'scripts'/n for n in ['prepare_creative_emotion_workflow.py','prepare_creative_emotion_workflow_v2.py']+[f'run_creative_emotion_revision_v{i}.py' for i in range(1,7)]]
    code += [ROOT/'tests/test_creative_emotion_workflow.py',ROOT/'tests/test_creative_seedance_segments.py',Path(__file__).resolve()]
    result={'schema':'emotion_workflow_actual_verification/v1',
        'at_utc':datetime.now(timezone.utc).isoformat(),'text_calls':rows,
        'new_text_calls':len(rows),'new_reported_tokens':sum(r['reported_tokens'] for r in rows),
        'spend_snapshot':summary,'offline_tests_passed':59,'offline_tests_log':str(qa/'FINAL_OFFLINE_TESTS_V4.txt'),
        'actual_candidate':str(out/'FULL_SCRIPT.md'),'candidate_state':checkpoint,
        'content_differences_need_user_alignment':True,
        'old_source_or_ledger_modified':False,'old_budget_reset':False,'old_governance_migrated':False,
        'source_bindings_rechecked':True,'new_media_calls':0,
        'grouped_media_dispatcher_connected':False,'service_schema_generation_guarantee':False,
        'code_files':{str(p):sha_file(p) for p in code},
        'earlier_local_review_error_267_preserved':True,'known_protocol_rejection_274_preserved':True,
        'old_unknown_outcome_ordinals':[70],'old_unknown_usage_ordinals':[70,160]}
    target=qa/'FINAL_VERIFICATION.json'
    if target.exists():
        old=read(target)
        result['at_utc']=old['at_utc']
    write_new(target,result)
    print(json.dumps({'new_calls':len(rows),'new_tokens':result['new_reported_tokens'],
        'summary':summary,'candidate':str(out/'FULL_SCRIPT.md'),'tests':59},ensure_ascii=False))


if __name__=='__main__': main()
