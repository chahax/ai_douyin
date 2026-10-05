"""Exactly one explicitly requested live receiving-layer probe; never retries call70."""
from pathlib import Path
from copy import deepcopy
from datetime import datetime,timezone
import hashlib,json
from scripts.creative_resume_dispatch_v3 import ContinuationRuntime,read,write,digest
from scripts.prepare_creative_call_evidence_repair_v1 import inspect_original
from scripts import creative_json_document_transport_v1 as transport

VERSION='creative_response_live_acceptance/v1'
LABEL='response_layer_live_acceptance'
INNER_SCHEMA={'type':'object','additionalProperties':False,'required':['probe_id','status','items'],
 'properties':{'probe_id':{'type':'string','const':'receive_layer_20261005_v1'},
 'status':{'type':'string','enum':['received']},'items':{'type':'array','minItems':1,'maxItems':1,
 'items':{'type':'object','additionalProperties':False,'required':['stimulus','reaction'],
 'properties':{'stimulus':{'type':'string','minLength':1,'maxLength':60},'reaction':{'type':'string','minLength':1,'maxLength':60}}}}}}

def build_wire():
    messages=[{'role':'system','content':'这是文本接口接收层验收，只提交一次工具调用；无长篇分析。'},
      {'role':'user','content':'probe_id填receive_layer_20261005_v1，status填received。items为只有一个对象的数组。stimulus填“方澄明确说今晚不行”，reaction填“林屿停住并收回笔”。这是接口测试，不是导演方案或最终剧本。'}]
    return {'role':'writer','model':'MiniMax-M3','messages':transport.build_messages(messages,INNER_SCHEMA),
      'parameters':{'max_completion_tokens':1024,'temperature':0.4,'thinking':'disabled'},
      'structured_schema':transport.build_envelope_schema(),'inner_document_schema':deepcopy(INNER_SCHEMA),
      'output_transport':transport.VERSION,'purpose':'one explicitly authorized independent response receiving test; not a resend or production continuation'}

def validate(value):
    if value['probe_id']!='receive_layer_20261005_v1' or value['status']!='received' or len(value['items'])!=1:
        raise ValueError('live probe contract rejected')
    if value['items'][0]!={'stimulus':'方澄明确说今晚不行','reaction':'林屿停住并收回笔'}:
        raise ValueError('live probe value changed')
    return {'probe_document_valid':True,'creative_quality_passed':False,'production_handoff_complete':False}


def prepare(project,root):
    project=Path(project).resolve();root=Path(root).resolve();root.relative_to(project)
    records=project/'data/production_records/this_time_i_leave_s6_20261005'
    candidate=project/'data/qa/creative_call_evidence_repair_20261005/CANDIDATE_BINDING.json'
    observation=inspect_original(project,records/'BASELINE_RECORD.json',records/'CODE_BINDING_MANIFEST.json')
    if observation['spend']!={'calls_started':70,'calls_with_known_usage':69,'reported_tokens':709272,'unknown_token_reservation':64010,'max_total_tokens':None,'old_budget_reset':False} or observation['pending_ordinals']!=[70]:
        raise RuntimeError('parent changed; reconcile before a live test')
    binding=read(candidate)
    for rel,h in binding['source_manifest'].items():
        if hashlib.sha256((project/rel).read_bytes()).hexdigest()!=h:raise RuntimeError('repair candidate source changed')
    root.mkdir(parents=True,exist_ok=True);wire=build_wire()
    authority={'schema':VERSION,'user_request':'生产测试','scope':'one independent MiniMax-M3 text receiving-layer production test',
      'max_new_calls':1,'max_output_tokens':1024,'automatic_retry':False,
      'original_call70_result':'unknown','original_call70_reservation':64010,'original_call70_resend_authorized':False,
      'director_continuation_authorized_by_this_test':False,'media_calls_authorized':False,
      'explicit_test_exception_only':True,'parent_unknown_gate_for_regular_work_remains':True,
      'parent_observation_sha256':digest(observation),'candidate_binding_sha256':hashlib.sha256(candidate.read_bytes()).hexdigest(),
      'wire_sha256':digest(wire),'aggregate_text_limit':None,'old_budget_reset':False}
    write(root/'PRODUCTION_TEST_AUTHORIZATION.json',authority,True)
    write(root/'REQUEST_NOT_YET_SENT.json',wire,True)
    inherited={**deepcopy(observation['original_starting_spend']),'calls_started':70,'reported_tokens':709272,
      'calls_with_known_usage':69,'unknown_token_reservations':64010,'pending_ordinals':[70],
      'parent_run':observation['original_run'],'explicit_scoped_test_authorization_sha256':hashlib.sha256((root/'PRODUCTION_TEST_AUTHORIZATION.json').read_bytes()).hexdigest()}
    sources=[project/rel for rel in binding['source_manifest']]+[Path(__file__).resolve()]
    def guard():
        current=inspect_original(project,records/'BASELINE_RECORD.json',records/'CODE_BINDING_MANIFEST.json')
        if digest(current)!=authority['parent_observation_sha256']:raise RuntimeError('parent evidence changed')
        if read(root/'PRODUCTION_TEST_AUTHORIZATION.json')!=authority or read(root/'REQUEST_NOT_YET_SENT.json')!=wire:
            raise RuntimeError('test authority or request changed')
        ledger=root/'CALL_LEDGER.json'
        if ledger.exists():
            calls=read(ledger)['calls']
            if len(calls)>1 or any(c['label']!=LABEL for c in calls):raise RuntimeError('single test call limit exceeded')
    class ScopedAcceptanceRuntime(ContinuationRuntime):
        def dispatch(self,label,request,validator):
            if label!=LABEL or digest(request)!=authority['wire_sha256']:
                raise RuntimeError('only the single authorized probe is allowed')
            return super().dispatch(label,request,validator)
    runtime=ScopedAcceptanceRuntime(project,root,sources,inherited,observation['model_configs'],
       inherited_guard=guard,shared_lock=Path(observation['original_run'])/'DISPATCH.lock')
    runtime.prepare()
    return runtime,wire,observation


def execute(project,root):
    runtime,wire,parent=prepare(project,root)
    receipt=runtime.dispatch(LABEL,wire,validate)
    new=runtime.summary();metadata=receipt.get('response_metadata',{});usage=metadata.get('total_tokens')
    usage_known=type(usage)is int and usage>=0
    result={'schema':VERSION,'completed_at_utc':datetime.now(timezone.utc).isoformat(),
      'test_status':receipt['status'],'ordinal':receipt['ordinal'],'model':wire['model'],
      'response_metadata':metadata,'new_call_count':new['new_calls'],'new_reported_tokens':new['new_reported_tokens'],
      'effective_calls_started':new['effective_calls_started'],'calls_with_known_usage':69+(1 if usage_known else 0),
      'effective_reported_tokens':new['effective_reported_tokens'],
      'inherited_unknown_token_reservations':64010,'new_unknown_token_reservations':new['unknown_token_reservations'],
      'unknown_token_reservations':64010+new['unknown_token_reservations'],
      'original_unknown_ordinals':[70],'original_call70_recovered':False,'max_total_tokens':None,
      'old_budget_reset':False,'original_governance_migrated':False,'automatic_retry':False,'media_calls':0,
      'original_files_unchanged':25,'original_sources_unchanged':144,
      'interface_success':metadata.get('http_status_code')==200,
      'test_document_valid':receipt['status']=='contract_valid','production_continuation_ready':False,
      'creative_quality_passed':False,'production_handoff_complete':False,
      'actual_full_script_director_or_performance_test':False}
    write(runtime.root/'PRODUCTION_TEST_RESULT.json',result)
    return result

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-only',action='store_true')
    args=parser.parse_args();project=Path(__file__).resolve().parents[1]
    root=project/'data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/modular_bd_v1/response_receive_production_test_20261005'
    if args.prepare_only:
        runtime,wire,parent=prepare(project,root)
        print(json.dumps({'status':'prepared_not_dispatched','request_sha256':digest(wire),'calls_started':70,'unknown_reservation_preserved':64010}))
    else:print(json.dumps(execute(project,root),ensure_ascii=False),flush=True)
