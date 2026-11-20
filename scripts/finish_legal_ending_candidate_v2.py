"""Strict same-source, typed finalization for an ending-revision candidate; no API calls."""
from pathlib import Path
import argparse,json,sys
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from scripts.run_legal_ending_revision_v13 import Revision,control

def validate_finalization(script,draft,review,gate):
    sha=control.digest(script)
    for receipt,label in [(draft,'complete_draft'),(review,'full_review')]:
        if receipt.get('status')!='contract_valid' or receipt.get('label')!=label:raise ValueError('known valid original receipt required')
        if type(receipt.get('validation')) is not dict or receipt['validation'].get('script_sha256')!=sha:raise ValueError('receipt reviewed another complete script')
        if type(receipt.get('response_metadata',{}).get('total_tokens')) is not int:raise ValueError('known usage required')
    if draft['validation'].get('local_current_fact_findings')!=[] or type(draft['validation'].get('local_current_fact_findings')) is not list:raise ValueError('local current facts unresolved or invalid')
    if review['validation'].get('needs_revision') is not False:raise ValueError('review unresolved or invalid')
    output=review['output']
    if type(output.get('issues')) is not list or output['issues']!=[] or output.get('story_invariants_preserved') is not True or output.get('human_spoken_language_feedback_addressed') is not True:raise ValueError('full review feedback unresolved or invalid')
    if gate.get('script_sha256')!=sha or gate.get('draft_ordinal')!=draft['ordinal'] or gate.get('review_ordinal')!=review['ordinal']:raise ValueError('independent gate source mismatch')
    if gate.get('text_candidate_qualified') is not True or type(gate.get('unresolved_mandatory_findings')) is not list or gate['unresolved_mandatory_findings']!=[]:raise ValueError('independent findings unresolved or invalid')
    if type(gate.get('checks')) is not dict or not gate['checks'] or any(v is not True for v in gate['checks'].values()):raise ValueError('independent source checks incomplete')
    return {'script_sha256':sha,'same_complete_script_reviewed':True,'typed_review_and_gate_checked':True,'human_quality_approved':False,'new_media_authorized':False}

def finish(root):
    setup=control.read(Path(root)/'SETUP.json')
    cls=Revision
    if setup.get('operator_version')=='captured_ending_revision/v14':
        from scripts.run_legal_ending_revision_v14 import Revision as cls
    if setup.get('operator_version')=='four_step_ending_revision/v15':
        from scripts.run_legal_ending_revision_v15 import Revision as cls
    op=cls(root);op.prepare();s=op.script();d=op.accepted('complete_draft');r=op.accepted('full_review');gate=control.read(op.root/'INDEPENDENT_EDITORIAL_GATE.json')
    result=validate_finalization(s,d,r,gate)
    writer_payload=json.loads(d['request']['messages'][1]['content']);review_payload=json.loads(r['request']['messages'][1]['content'])
    if review_payload['full_current_script']!=s or review_payload['feedback']!=control.read(op.root/'USER_FEEDBACK.json') or review_payload['reference_fulltext']!=writer_payload['reference_fulltext']:raise ValueError('actual review payload source mismatch')
    if gate.get('writer_request_sha256')!=d['request_sha256'] or gate.get('review_request_sha256')!=r['request_sha256']:raise ValueError('independent request mismatch')
    control.write(op.root/'STRICT_FINALIZATION.json',{**result,'validator_sha256':control.sha_file(Path(__file__)),'draft_ordinal':d['ordinal'],'review_ordinal':r['ordinal']},True)
    return op.finish()

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');a=argparse.ArgumentParser();a.add_argument('run_dir');args=a.parse_args();print(json.dumps(finish(args.run_dir),ensure_ascii=False),flush=True)
