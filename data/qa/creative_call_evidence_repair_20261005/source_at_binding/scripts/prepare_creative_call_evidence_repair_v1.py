"""Offline repair binding only. Never authorizes, creates, or dispatches a run."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from scripts.creative_call_evidence_v1 import atomic_create

VERSION='creative_call_evidence_repair_candidate/v1'
ADDED_SOURCES=(
    'scripts/creative_call_evidence_v1.py',
    'scripts/creative_evidenced_role_clients_v1.py',
    'scripts/creative_resume_dispatch_v3.py',
    'scripts/prepare_creative_call_evidence_repair_v1.py',
    'tests/test_creative_call_evidence_repair_v1.py',
)

def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def inspect_original(project, baseline_path, code_manifest_path):
    project=Path(project).resolve();baseline=read(baseline_path)
    root=Path(baseline['original_run']).resolve()
    original=baseline['immutable_original_file_hashes']
    code=read(code_manifest_path)['source_manifest']
    for rel,expected in original.items():
        if sha(root/rel)!=expected:raise RuntimeError('original production evidence changed: '+rel)
    for rel,expected in code.items():
        if sha(project/rel)!=expected:raise RuntimeError('original bound source changed: '+rel)
    ledger=read(root/'CALL_LEDGER.json');starting=deepcopy(ledger['starting_spend'])
    known=0;spent=0;reserved=0;pending=[];unknown_usage=[];ids=set()
    for row in ledger['calls']:
        path=root/row['receipt']
        if sha(path)!=row['receipt_sha256']:raise RuntimeError('original receipt binding changed')
        receipt=read(path);meta=receipt.get('response_metadata',{});amount=meta.get('total_tokens')
        if type(amount)is int and amount>=0:
            identity=meta.get('response_id')
            if identity and identity in ids:raise RuntimeError('duplicate original response identity')
            if identity:ids.add(identity)
            known+=1;spent+=amount
        else:unknown_usage.append(row['ordinal']);reserved+=row['token_reservation']
        if receipt['status'] in ('pending_response','outcome_unknown'):pending.append(row['ordinal'])
    return {'original_run':str(root),'verified_original_files':len(original),
        'verified_original_sources':len(code),'original_source_manifest':code,
        'model_configs':deepcopy(ledger['model_configs']),
        'original_starting_spend':starting,
        'spend':{'calls_started':starting['calls_started']+len(ledger['calls']),
          'calls_with_known_usage':starting['calls_started']+known,
          'reported_tokens':starting['reported_tokens']+spent,'unknown_token_reservation':reserved,
          'max_total_tokens':ledger['max_total_tokens'],'old_budget_reset':False},
        'pending_ordinals':pending,'unknown_usage_ordinals':unknown_usage,
        'production_dispatch_ready':not pending and not unknown_usage,
        'original_receipts_and_sources_modified':False}


def require_original_ready(observation):
    if not observation['production_dispatch_ready']:
        raise RuntimeError('original result/usage unresolved; no new task or dispatch')


def prepare_candidate(project, output, baseline_path, code_manifest_path):
    project=Path(project).resolve();output=Path(output).resolve()
    output.relative_to(project)  # Artifact stays in the project, never in the old run.
    observation=inspect_original(project,baseline_path,code_manifest_path)
    oldroot=Path(observation['original_run'])
    if output==oldroot or oldroot in output.parents:raise RuntimeError('cannot write into original run')
    output.mkdir(parents=True,exist_ok=True)
    sources=deepcopy(observation['original_source_manifest'])
    for rel in ADDED_SOURCES:sources[rel]=sha(project/rel)
    for rel,expected in sources.items():
        target=output/'source_at_binding'/rel
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():
            if sha(target)!=expected:raise RuntimeError('candidate source snapshot changed')
        else:atomic_create(target,(project/rel).read_bytes())
    candidate={'schema':VERSION,'created_at_utc':datetime.now(timezone.utc).isoformat(),
        'status':'offline_binding_prepared_production_blocked' if not observation['production_dispatch_ready'] else 'offline_binding_prepared_pending_explicit_adoption',
        'dispatch_enabled':False,'new_execution_task':False,'automatic_retry':False,
        'old_governance_migrated':False,'old_budget_reset':False,'provider_called':False,
        'code_source_count':len(sources),'source_manifest':sources,
        'parent_observation':observation,
        'acceptance_scope':'offline response capture/classification/recovery only',
        'production_adoption_required':True,'original_call70_recoverable_by_new_journal':False,
        'production_handoff_complete':False,'creative_quality_passed':False,
        'model_configs':observation['model_configs'],
        'http_change':'defer local SDK response parsing; server non-stream request preserved',
        'server_schema_guarantee':False}
    target=output/'CANDIDATE_BINDING.json'
    if target.exists():
        stored=read(target);candidate['created_at_utc']=stored['created_at_utc']
        if stored!=candidate:raise RuntimeError('immutable candidate binding changed')
    else:atomic_create(target,(json.dumps(candidate,ensure_ascii=False,indent=2)+'\n').encode())
    return candidate


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    records=args.project/'data/production_records/this_time_i_leave_s6_20261005'
    result=prepare_candidate(args.project,args.output,records/'BASELINE_RECORD.json',records/'CODE_BINDING_MANIFEST.json')
    print(json.dumps({k:result[k] for k in ('status','code_source_count','dispatch_enabled','provider_called')}))
