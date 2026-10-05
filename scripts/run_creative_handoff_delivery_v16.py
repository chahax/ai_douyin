"""Read-only delivery saver after source-bound v15 review; no provider entry."""
from pathlib import Path
from copy import deepcopy
import json,sys
from scripts import run_creative_handoff_v15 as production
from scripts.run_creative_handoff_v15 import ROOT,control,wire_contract,compact,joint,source,summary
VERSION='s6_delivery_finalization/v16'

def latest_review():
    rt=production.runtime();ledger=control.read(rt.ledger);rt.check(ledger)
    records=[rt.effective_receipt(c) for c in ledger['calls'] if c['label'].startswith('full_review_s6_d6_view15_r')]
    if not records or records[-1]['status']!='contract_valid':raise RuntimeError('latest complete v15 review not valid')
    if records[-1]['output'].get('schema')!=wire_contract.VERSION:raise RuntimeError('wrong review transport')
    return records[-1]

def finalize(evidence):
    ctx=control.read(ROOT/'REVIEW_FULL_CONTEXT.json');compiled=control.read(ROOT/'ORIGINAL_COMPILED_PERFORMANCE.json')
    record=latest_review();decoded=wire_contract.expand(record['output'],ctx);review_doc=compact.expand_review(decoded,ctx);joint.validate_joint_review(review_doc,ctx)
    if review_doc['issues'] or not review_doc['story_preserved']:raise RuntimeError('unresolved full text issues')
    source.verify_assistant_evidence(ctx,evidence)
    out=ROOT/'DELIVERABLE_s6_d6';out.mkdir(parents=True,exist_ok=True)
    for name,value in [('FULL_SCRIPT.json',ctx['raw_linear_script']),('WHOLE_FILM_DIRECTION.json',ctx['whole_film_direction']),('COMPILED_PERFORMANCE.json',compiled),('REVIEWED_EXECUTION_VIEW.json',ctx['shots']),('FULL_TEXT_REVIEW.json',review_doc),('STATIC_ASSET_DEFINITIONS.json',ctx['static_visual_manifest'])]:control.write(out/name,value,True)
    for name,value in [('FULL_SCRIPT.md',source.linear.render_linear_screenplay(ctx['raw_linear_script'])+'\n'),('DIRECTOR_PERFORMANCE_PLAN.md',source.render_production_plan(ctx,{**compiled,'storyboard':ctx['shots']}))]:
        p=out/name
        if p.exists() and p.read_text(encoding='utf-8')!=value:raise RuntimeError('delivery changed')
        if not p.exists():p.write_text(value,encoding='utf-8')
    handoff={'schema':VERSION,'delivery_source_sha256':control.sha_file(Path(__file__).resolve()),'production_source_binding_unchanged':True,'adopted_review_ordinal':record['ordinal'],'status':'text_reviewed_awaiting_human_content_and_aesthetic_confirmation','script_sha256':control.digest(ctx['raw_linear_script']),'compiled_sha256':control.digest(compiled),'reviewed_view_sha256':control.digest(ctx['shots']),'review_sha256':control.digest(review_doc),'review_context_sha256':compact.context_digest(ctx),'assistant_verified_evidence':deepcopy(evidence),'narrative_beats':9,'shots':compiled['execution_shot_count'],'compiled_duration_seconds':compiled['total_duration_seconds'],'text_production_handoff_complete':True,'creative_quality_passed':False,'user_quality_confirmation':None,'actual_selected_images':[],'actual_images_returned_to_director':False,'component_registry':deepcopy(ctx['component_registry']),'asset_sample_selection_status':'awaiting_human_aesthetic_approval','media_calls':0,'video_human_review_required':True,'automatic_media_submit':False,'cost_ledger':summary(),'old_call70_still_unknown':True,'old_unknown_reservation_preserved':64010,'old_task_or_budget_reset':False,'legacy_compiled_prompt_not_media_instruction':True,'reviewed_execution_view_is_authoritative_text_projection':True,'next_steps':['human content and aesthetic review','few selected aesthetic images under media authorization','return actually selected images to director','validate long dialogue media duration','generate current segment then await human review','continue only with approved original service tail frame']}
    control.write(out/'PRODUCTION_HANDOFF.json',handoff,True);return handoff

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');print(json.dumps(finalize(control.read(sys.argv[1])),ensure_ascii=False,indent=2))
