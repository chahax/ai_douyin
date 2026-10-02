"""Build/check a frozen, explicitly incomplete governance pack. Never calls models."""
import argparse
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.content_factory.creative_rule_registry import REGISTRY_SCHEMA,digest,file_hash,resolve_fields,validate_registry,validate_ownership,select_rules,validate_runtime_sources
from src.content_factory.creative_evaluation import DEFAULT_CONFIG,normalize_call,summarize_cost,validate_dataset,score_review_runs,optimization_admission

SOURCE='data/production_trials/say_no_action_one_production_cycle_20260928/round_01'
PLAN_DOC='docs/VIDEO_PRODUCTION_ROOT_CAUSE_AND_CHANGE_PLAN_20260928.md'


def load(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def build(output):
    output=Path(output)
    if output.exists() and any(output.iterdir()):raise RuntimeError('Frozen output already exists; choose a new version directory')
    output.mkdir(parents=True,exist_ok=True);(output/'fixtures').mkdir()
    created=datetime.now(timezone.utc).isoformat();source_hash=file_hash(ROOT/PLAN_DOC)
    def envelope(schema,status='offline_implemented_not_production_validated',**fields):
        return {'schema_version':schema,'source_hash':source_hash,'created_at':created,'implementation_status':status,**fields}
    def write(name,value):
        path=output/name;path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    runtime_names=['creative_modular_contract','creative_direction_source_schema','creative_diagnostic_spend','creative_response_contract','creative_workflow_roles','creative_action_plan_v2','creative_state_plan_v6','creative_review_packet','creative_review_resolution','creative_focused_review_stage','creative_governed_runtime','creative_workflow','creative_plan_patch','creative_segmented_director','creative_state_plan_binding','creative_rule_registry','creative_evaluation']
    write('runtime_sources.json',envelope('creative_runtime_sources/v1',sources=[{'path':'src/content_factory/'+name+'.py','sha256':file_hash(ROOT/'src/content_factory'/(name+'.py'))} for name in runtime_names],rule_inventory_coverage_claim=False))
    source=ROOT/SOURCE
    review_record=load(source/'writer_check__state_plan_00.json')
    context=json.loads(review_record['request']['messages'][1]['content'])
    write('fixtures/frozen_context.json',envelope('creative_frozen_context/v1',source_file=SOURCE+'/writer_check__state_plan_00.json',source_file_sha256=file_hash(source/'writer_check__state_plan_00.json'),context=context))
    targets=load(source/'LOCAL_REVISION_TARGETS.json')['targets'];cases=[]
    def case(cid,category,kind,scenario,expected,*,family=None,group=None,evidence=None,issues=None,source_paths=None):
        return {'case_id':cid,'category':category,'case_kind':kind,'scenario':scenario,'expected_disposition':expected,
                'label_status':'candidate','adjudication':{'approved_by':None,'approved_at':None,'candidate_author':'Codex assistant; requires independent human adjudication'},
                'source_family':family or cid,'independence_group':group or cid,'split':'development','used_for_prompt_tuning':True,
                'expected_issues':issues or [],'evidence':evidence or [],'source_paths':source_paths or [],'production_validated':False}
    corrected=[
        'Lin Yao keeps her gaze on the folder while delivering the refusal; only breathing and mouth movement change. The upward gaze belongs to the next beat.',
        'One continuous fixed shot; retain the frame through the complete acceptance line and its ending reaction. Camera contains no separate cut instruction.',
        'Chen He is standing on the accessible front side of the chair facing the desk; from that position she sits onto its seat without moving through the chair back.'
    ]
    categories=['interaction','camera','space']
    for index,target in enumerate(targets):
        rid=f'R{index+1:02}';evidence=[]
        for path in target['paths']:
            values=resolve_fields(context,path)
            if not values:raise RuntimeError('Actual source path missing '+path)
            evidence.append({'path':path,'value':values[0]})
        negative=case(rid+'_BAD',categories[index],'error',target['evidence'],'failed',family='say_no_20260928',group='say_no_20260928',evidence=evidence,issues=[{'issue_id':rid,'severity':'major'}],source_paths=target['paths'])
        positive=case(rid+'_OK_CANDIDATE',categories[index],'correct',corrected[index],'passed',family='say_no_20260928',group='say_no_20260928',evidence=[{'local_revision_of':target['paths'][0],'replacement':corrected[index]}],source_paths=target['paths'])
        positive['scope']='Local conceptual counterexample only; not a complete repaired production plan'
        for item in (negative,positive):cases.append(item);write('fixtures/'+item['case_id']+'.json',envelope('creative_eval_case/v1','candidate_label_not_gold',case=item))
    deterministic=[('STATE_OK','standing -> sit on known seat','passed'),('STATE_BAD','sitting -> sit with no stand','failed'),
                   ('HOLD_OK','turn 0..1; hold 1..3; stimulus 3','passed'),('HOLD_BAD','turn 0..1; declared hold 0..2; stimulus 2','failed'),
                   ('SOURCE_OK','unchanged source and derived hashes','passed'),('SOURCE_BAD','derived storyboard changed without source plan revision','failed')]
    for cid,text,expected in deterministic:
        item=case(cid,'action' if cid.startswith(('STATE','HOLD')) else 'interface','correct' if expected=='passed' else 'error',text,expected,
                  family=cid.split('_')[0]+'_checker',group=cid.split('_')[0]+'_checker',issues=[] if expected=='passed' else [{'issue_id':cid,'severity':'major'}])
        item['scope']='Deterministic checker fixture; not an independent story or approved quality label'
        cases.append(item);write('fixtures/'+cid+'.json',envelope('creative_eval_case/v1','candidate_label_not_gold',case=item))
    boundaries=[('CONFLICT_1','同一镜要求固定10秒且必须连续拍满20秒','blocked'),('CONFLICT_2','只允许一名角色且必须同时呈现两名不同角色','blocked'),
      ('EXPRESSION_1','当前协议仅支持站走，但源剧情必须连续爬行穿过矮通道','expression_unsupported'),('EXPRESSION_2','源剧本必须在关键递物动作中说完整一句话，而当前串行协议不能表达','expression_unsupported'),
      ('SIMULTANEOUS_1','角色边走边问路，对方原地回答；现实可行，按协议能力通过或明确不兼容','passed_or_expression_unsupported'),('SIMULTANEOUS_2','甲讲述时乙喝水，不得把独立人物动作强制串行','passed_or_expression_unsupported'),
      ('AMBIGUOUS_1','只说她把它还给她，双方人名和物品均未明确','review_required'),('AMBIGUOUS_2','空间仅写椅子附近，不能判断人物是否在可坐侧','review_required'),
      ('CORRECT_1','固定摄影机保持原位，人物沿已留出的纵深通道离开','passed'),('CORRECT_2','第一帧站立，动作从0秒开始，不要求人为新增静止等待','passed')]
    for cid,text,expected in boundaries:
        item=case('BOUNDARY_'+cid,'space' if 'AMBIGUOUS' in cid else 'action','boundary',text,expected)
        item['required_error_code']='REQUIREMENT_CONFLICT' if cid.startswith('CONFLICT') else 'EXPRESSION_UNSUPPORTED' if cid.startswith('EXPRESSION') else None
        cases.append(item);write('fixtures/'+item['case_id']+'.json',envelope('creative_eval_case/v1','candidate_label_not_gold',case=item))
    from tests.test_creative_action_plan_v2 import sample as p1_sample
    from src.content_factory.creative_action_plan_v2 import compile_action_plan as p1_compile
    p1_plan,p1_script,p1_manifest=p1_sample()
    p1_context={'plan':p1_plan,'script':p1_script,'manifest':p1_manifest,'shots':p1_compile(p1_plan,p1_script,p1_manifest)}
    write('fixtures/p1_checker_context.json',envelope('creative_checker_context/v1',context=p1_context,source='tests/test_creative_action_plan_v2.py:sample',source_sha256=file_hash(ROOT/'tests/test_creative_action_plan_v2.py'),independent_gold=False))
    context={**context,'p1_checker':p1_context}
    for kind,category,positive,negative in [
      ('CUT','camera','test_last_action_anchor_after_dialogue_is_valid','test_cut_cannot_precede_remaining_locked_dialogue'),
      ('SEAT','space','test_separate_approach_and_face_then_sit_is_valid_and_compiled','test_seat_wrong_side_is_failure_and_does_not_guess_move'),
      ('BOUNDARY','action','test_version_dispatch_and_compiled_cut_facing_preserve_sources','test_compiled_boundary_tampering_is_not_a_valid_handoff_source')]:
        for suffix,symbol,expected in [('OK',positive,'passed'),('BAD',negative,'blocked')]:
            item=case('P1_'+kind+'_'+suffix,category,'correct' if suffix=='OK' else 'error','Executable existing checker test: '+symbol,expected,family='P1_SHARED_SAMPLE',group='P1_SHARED_SAMPLE',source_paths=['tests/test_creative_action_plan_v2.py:'+symbol])
            item['test_source_sha256']=file_hash(ROOT/'tests/test_creative_action_plan_v2.py')
            cases.append(item);write('fixtures/'+item['case_id']+'.json',envelope('creative_eval_case/v1','candidate_label_not_gold',case=item))
    def ref(path,anchor):return {'path':path,'sha256':file_hash(ROOT/path),'anchor':anchor}
    rules=[]
    def rule(rid,cat,rootcause,priority,stage,fields,checker,pos,neg,status='active',failure=None,authority=None):
        sourcefile=checker.split(':')[0] if checker and not checker.startswith('proposed:') else PLAN_DOC
        anchor=('def '+checker.split(':')[1]+'(') if sourcefile!=PLAN_DOC else rid.split('.')[0] if rid.split('.')[0] in (ROOT/PLAN_DOC).read_text(encoding='utf-8') else '统一事实来源'
        rules.append({'rule_id':rid,'category':cat,'root_cause':rootcause,'priority':priority,'severity':'blocking' if priority=='P0' else 'major','stage':stage,'trigger':{'any_features':[]},
                      'field_paths':fields,'authority_field':authority or (fields[0] if fields else None),'source_refs':[ref(sourcefile,anchor)],'checker':checker,'checker_kind':'semantic' if status=='proposed' else 'deterministic',
                      'failure_code':failure or rid.replace('.','_'),'positive_case_ids':[pos],'negative_case_ids':[neg],'version':'1','replaces':[],'replacement_rule_ids':[],'status':status,'repair_owner':'action_plan' if priority=='P1' else 'workflow',
                      'unknown_disposition':'review_required' if status=='proposed' else 'blocked','change_action':'propose' if status=='proposed' else 'retain'})
    rule('STATE.PRECONDITION.001','action','contract_precondition','P1',['plan_validation'],['state_plan.initial_state.*.posture','state_plan.beats[*].groups[*].operations'],'src/content_factory/creative_state_plan_v2.py:_apply_operation','STATE_OK','STATE_BAD')
    rule('TIME.HOLD.001','interaction','deterministic_timing','P1',['scheduling'],['state_plan.beats[*].groups[*].duration_seconds'],'src/content_factory/creative_action_plan_v1.py:schedule_action_plan','HOLD_OK','HOLD_BAD')
    rule('SOURCE.BIND.001','source','source_lineage','P0',['handoff'],['state_plan','script','shots'],'src/content_factory/creative_state_plan_binding.py:bind_reviewed_state_plan','SOURCE_OK','SOURCE_BAD')
    rule('EVIDENCE.BIND.001','interface','review_reference','P0',['review'],['shots.shots[*].start_state'],'src/content_factory/creative_review_evidence_ids.py:expand_review_ids','SOURCE_OK','SOURCE_BAD')
    rule('ACT.GAZE.001','interaction','semantic_double_authority','P1',['plan_review'],['state_plan.beats[*].groups[*].operations','state_plan.beats[*].dialogue_performance'],'proposed:check_gaze_text_consistency','R01_OK_CANDIDATE','R01_BAD','proposed','PLAN_GAZE_TEXT_CONFLICT')
    rule('CUT.COMPLETION.001','camera','cut_authority','P1',['plan_review'],['state_plan.beats[*].camera','state_plan.beats[*].cut_reason'],'proposed:check_camera_cut_consistency','R02_OK_CANDIDATE','R02_BAD','proposed','PLAN_CUT_TEXT_CONFLICT',authority='proposed:cut_after_event_id')
    rule('SPACE.SEAT.001','space','space_precondition','P1',['plan_review'],['state_plan.initial_state','state_plan.beats[*].groups[*].operations'],'proposed:check_sit_preconditions','R03_OK_CANDIDATE','R03_BAD','proposed','PLAN_SEAT_ACCESS_UNKNOWN')
    rule('CUT.EXECUTION.002','camera','typed_cut_completion','P1',['plan_validation','scheduling'],['p1_checker.plan.beats[*].cut_after_event_id','p1_checker.plan.beats[*].completion_condition'],'src/content_factory/creative_action_plan_v2.py:check_cut_completion','P1_CUT_OK','P1_CUT_BAD',failure='PLAN_CUT_BEFORE_REQUIRED_EVENT')
    rule('SPACE.SEAT_TYPED.002','space','typed_seat_precondition','P1',['plan_validation','scheduling'],['p1_checker.plan.spatial_contract.seats','p1_checker.plan.initial_state'],'src/content_factory/creative_action_plan_v2.py:check_sit_preconditions','P1_SEAT_OK','P1_SEAT_BAD',failure='PLAN_SEAT_ACCESS_INVALID')
    rule('STATE.BOUNDARY.002','action','compiled_state_continuity','P1',['handoff'],['p1_checker.shots.shots[*].start_state','p1_checker.shots.shots[*].end_state'],'src/content_factory/creative_action_plan_v2.py:check_adjacent_state_transition','P1_BOUNDARY_OK','P1_BOUNDARY_BAD',failure='PLAN_BOUNDARY_STATE_CONFLICT')
    exclusions=[{'scope':'Other prompts, legacy protocols, publishing/media/audio rules','reason':'Not exhaustively inventoried in this P0 pack; existing execution remains authoritative; requires separate inventory.'}]
    registry=envelope('creative_rule_registry/v1',inventory_scope={'coverage_denominator':len(rules)+1,'mapped':len(rules),'excluded':1,'unmapped':0,'repository_wide_complete':False,'exclusions':exclusions},rules=rules)
    write('rules.json',registry);write('rule_registry.schema.json',{**deepcopy(REGISTRY_SCHEMA),'x-artifact-metadata':envelope('creative_schema_artifact/v1')})
    write('rule_source_map.json',envelope('creative_rule_source_map/v1',items=[{'rule_id':r['rule_id'],'sources':r['source_refs'],'checker':r['checker'],'field_paths':r['field_paths'],'status':r['status']} for r in rules],exclusions=exclusions))
    ownership=[]
    for path,owner,authority in [('script.beats[*].dialogue','screenplay','locked script'),('static_visual_manifest.characters','static_manifest','static identity'),('state_plan.initial_state','action_plan','initial state'),('state_plan.beats[*].groups[*].operations','action_plan','typed state operations'),('state_plan.beats[*].groups[*].duration_seconds','action_plan','action and hold budgets'),('state_plan.beats[*].dialogue_performance','action_plan','performance-only prose; not state authority'),('shots.shots[*].start_state','compiler','derived; never independently writable'),('shots.shots[*].end_state','compiler','derived; never independently writable')]:ownership.append({'field_path':path,'owner':owner,'authority':authority,'status':'active'})
    ownership.append({'field_path':'proposed:cut_after_event_id','owner':'action_plan','authority':'single cut event; current camera/cut_reason conflict is unresolved','status':'proposed'})
    write('field_ownership.json',envelope('creative_field_ownership/v1',fields=ownership,coverage_scope='Only listed paths; not all execution fields.'))
    from src.content_factory.creative_action_plan_v2 import field_ownership as v2_ownership,checker_manifest as v2_checkers,build_action_plan_schema
    plan_schema=build_action_plan_schema({'script':context['script'],'static_visual_manifest':context['static_visual_manifest']})
    ownership_v2=v2_ownership();checker_v2=v2_checkers()
    seen_v2=set()
    for owner in ownership_v2['owners']:
        for field in owner['field_paths']:
            if field in seen_v2:raise RuntimeError('P1 duplicate field authority '+field)
            seen_v2.add(field);node=plan_schema
            for part in field.split('.'):
                if part=='*':node=node.get('items',node.get('additionalProperties',{}))
                else:node=node.get('properties',{}).get(part,{})
            if not node:raise RuntimeError('P1 ownership path missing from actual schema '+field)
    write('plan_schema.json',{**plan_schema,'x-artifact-metadata':envelope('creative_plan_schema_artifact/v1',source_module='src/content_factory/creative_action_plan_v2.py',source_module_sha256=file_hash(ROOT/'src/content_factory/creative_action_plan_v2.py'))})
    write('plan_v2_field_ownership.json',envelope('creative_p1_field_ownership/v1',ownership=ownership_v2,verified_schema_path_count=len(seen_v2),production_validated=False))
    write('checker_manifest.json',envelope('creative_p1_checker_manifest/v1',manifest=checker_v2,registry_mapping=[
        {'checker':row['checker'],'registry_rule_id':{'check_gaze_text_consistency':'ACT.GAZE.001','check_camera_cut_consistency':'CUT.COMPLETION.001','check_cut_completion':'CUT.EXECUTION.002','check_sit_preconditions':'SPACE.SEAT_TYPED.002','check_adjacent_state_transition':'STATE.BOUNDARY.002'}.get(row['checker']),
         'exclusion_reason':None} for row in checker_v2['checkers']],production_validated=False))

    write('fixtures/index.json',envelope('creative_fixture_index/v1',cases=[{'case_id':c['case_id'],'path':'fixtures/'+c['case_id']+'.json','sha256':file_hash(output/'fixtures'/ (c['case_id']+'.json')),'label_status':c['label_status']} for c in cases]))
    write('dataset_manifest.json',envelope('creative_dataset_manifest/v1','candidate_dataset_incomplete',cases=cases,independence_note='R01-R03 and their correct variants share one production source. Checker variants and boundary scenarios do not establish 80 independently approved stories.'))
    write('labels.json',envelope('creative_labels/v1','candidate_labels_require_adjudication',labels=[{k:c[k] for k in ('case_id','label_status','adjudication','expected_disposition','expected_issues')} for c in cases]))
    write('eval_config.json',envelope('creative_eval_configuration/v1',config=DEFAULT_CONFIG))
    calls=[]
    for path in sorted(source.glob('*.json')):
        obj=load(path)
        for record in [obj,*obj.get('prior_attempts',[])]:
            if record.get('response_metadata'):calls.append(normalize_call(record,SOURCE+'/'+path.name))
    human=[{'role':'assistant_and_user_review','active_minutes':None,'wait_minutes':None,'hourly_rate':None,'currency':None,'source':'not_measured; no retrospective guess'}]
    cost=summarize_cost(calls,human,0)
    write('baseline_metrics.json',envelope('creative_baseline_metrics/v1','historical_usage_partial',calls=calls,human_sessions=human,cost=cost,review_status='failed; zero qualified handoffs',raw_sources=[{'path':SOURCE+'/'+p.name,'sha256':file_hash(p)} for p in sorted(source.glob('*.json')) if load(p).get('response_metadata')]))
    results=score_review_runs(cases,[],DEFAULT_CONFIG)
    result=envelope('creative_eval_result/v1','not_executed_no_paid_authorization',result=results,optimization=optimization_admission([],False),automatic_paid_execution=False)
    (output/'eval_results.jsonl').write_text(json.dumps(result,ensure_ascii=False)+'\n',encoding='utf-8')
    write('activation_example.json',envelope('creative_rule_activation/v1',selection=select_rules(registry,'plan_review',[])))
    checks={'registry':validate_registry(registry,ROOT,context,{c['case_id'] for c in cases}),'ownership':validate_ownership(ownership,context),'dataset':validate_dataset(cases)}
    write('validation_receipt.json',envelope('creative_governance_validation/v1',checks=checks,command='python scripts/manage_creative_governance.py build --output '+str(output),exit_code=0,
          acceptance='Registry infrastructure passes; dataset/quality/cost acceptance blocked by missing approved labels, samples, runs and invoices.'))
    text=f'''---
schema_version: creative_quality_cost_report/v1
source_hash: {source_hash}
created_at: {created}
implementation_status: offline_infrastructure_only
---

# Quality and cost status\n\nImplemented: offline scoped registry validation, rule conflict/lifecycle helpers, candidate fixture freezing, evaluation gates, and missing-aware cost reporting. Production integration is not enabled by this pack.\n\nInventory: {len(rules)} individually mapped rules, one explicit coarse exclusion record. This is not a repository-wide rule census. Semantic rules remain proposed; active deterministic rules are not proof of semantic coverage.\n\nDataset: {len(cases)} candidate cases, 0 approved gold cases, 0 approved holdout cases. R01-R03 derive from one story; conceptual correct variants are not separately validated complete plans. Required 80 independent approved cases / 40 holdouts are unmet. No benchmark model calls were executed.\n\nBaseline: {cost['call_count']} actual historical requests. Provider token counts are recorded separately in baseline_metrics.json. Cache usage, invoice prices, currency and active human minutes are unavailable and remain null. No qualified handoff; cost per qualified handoff is undefined, not zero. No actual fee reduction claim is supported.\n\nQuality, cost and latency targets remain blocked/unverified. See eval_config.json and eval_results.jsonl for executable thresholds and integer denominators.\n'''
    (output/'quality_cost_report.md').write_text(text,encoding='utf-8')
    inventory=[{'path':str(p.relative_to(output)).replace('\\','/'),'sha256':file_hash(p)} for p in sorted(output.rglob('*')) if p.is_file()]
    write('artifact_manifest.json',envelope('creative_governance_artifacts/v1',artifacts=inventory,repository_root=str(ROOT),source_plan=PLAN_DOC))
    return checks


def verify(output):
    output=Path(output);manifest=load(output/'artifact_manifest.json')
    for row in manifest['artifacts']:
        path=(output/row['path']).resolve()
        if not path.is_relative_to(output.resolve()) or file_hash(path)!=row['sha256']:raise ValueError('FROZEN_ARTIFACT_CHANGED: '+row['path'])
    context=load(output/'fixtures/frozen_context.json')['context']
    if (output/'fixtures/p1_checker_context.json').exists():context={**context,'p1_checker':load(output/'fixtures/p1_checker_context.json')['context']}
    cases=load(output/'dataset_manifest.json')['cases']
    registry=validate_registry(load(output/'rules.json'),ROOT,context,{c['case_id'] for c in cases})
    return {'runtime_sources':validate_runtime_sources(output,ROOT),'artifact_hashes_valid':True,'registry':registry,'dataset':validate_dataset(cases),'automatic_paid_execution':False}


def main():
    parser=argparse.ArgumentParser(description='Offline only; cannot invoke model or video APIs')
    parser.add_argument('mode',choices=['build','verify']);parser.add_argument('--output',required=True)
    args=parser.parse_args();result=build(args.output) if args.mode=='build' else verify(args.output)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
