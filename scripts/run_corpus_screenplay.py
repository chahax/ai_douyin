"""Explicit corpus screenplay prepare/execute; never publishes or generates media."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import prepare,prepare_rework,execute,resume_known_analysis,resume_review_validation,resume_fact_validation,continue_writing,recover_known_writer_truncation,finish_revision_pair

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['prepare','prepare-rework','execute','retry-analysis-groups','resume-analysis','resume-review-validation','resume-fact-validation','continue-writing','recover-truncated-writer','finish-revision-pair']);p.add_argument('--run',required=True)
    p.add_argument('--manifest');p.add_argument('--previous-status');p.add_argument('--user-statement');p.add_argument('--previous-run')
    p.add_argument('--reuse-remaining-budget',action='store_true')
    p.add_argument('--analysis-workers',type=int,default=2)
    p.add_argument('--analysis-group-chars',type=int,default=12000)
    p.add_argument('--analysis-context-chars',type=int,default=2000)
    p.add_argument('--analysis-only',action='store_true')
    p.add_argument('--analysis-local-model')
    p.add_argument('--analysis-local-endpoint',default='http://127.0.0.1:11435')
    p.add_argument('--analysis-context-tokens',type=int,default=32768)
    p.add_argument('--analysis-max-output-tokens',type=int,default=8192)
    p.add_argument('--group-ids',nargs='+')
    a=p.parse_args()
    if a.action=='prepare':
        if not all((a.manifest,a.previous_status,a.user_statement)):p.error('prepare requires manifest, previous-status and user-statement')
        route=({'provider':'ollama','model':a.analysis_local_model,'endpoint':a.analysis_local_endpoint,
                'context':a.analysis_context_tokens,'max_tokens':a.analysis_max_output_tokens}
               if a.analysis_local_model else None)
        result=prepare(a.manifest,a.run,user_statement=a.user_statement,previous_status=a.previous_status,
            analysis_workers=a.analysis_workers,analysis_group_chars=a.analysis_group_chars,
            analysis_context_chars=a.analysis_context_chars,analysis_only=a.analysis_only,analysis_route=route)
    elif a.action=='retry-analysis-groups':
        if not a.group_ids or not a.user_statement:p.error('retry-analysis-groups requires group-ids and user-statement')
        result=execute(a.run,retry_groups=a.group_ids,retry_reason=a.user_statement)
    elif a.action=='prepare-rework':
        if not all((a.previous_run,a.previous_status,a.user_statement)):p.error('prepare-rework requires previous-run, previous-status and user-statement')
        result=prepare_rework(a.previous_run,a.run,user_statement=a.user_statement,previous_status=a.previous_status,reuse_remaining_budget=a.reuse_remaining_budget)
    elif a.action=='resume-analysis':result=resume_known_analysis(a.run)
    elif a.action=='resume-review-validation':
        if not a.user_statement:p.error('resume-review-validation requires user-statement')
        result=resume_review_validation(a.run,user_statement=a.user_statement)
    elif a.action=='resume-fact-validation':
        if not a.user_statement:p.error('resume-fact-validation requires user-statement')
        result=resume_fact_validation(a.run,user_statement=a.user_statement)
    elif a.action=='continue-writing':
        if not a.user_statement:p.error('continue-writing requires reason in user-statement')
        result=continue_writing(a.run,a.user_statement)
    elif a.action=='recover-truncated-writer':result=recover_known_writer_truncation(a.run)
    elif a.action=='finish-revision-pair':result=finish_revision_pair(a.run)
    else:result=execute(a.run)
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
