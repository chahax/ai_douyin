"""427 saved-response local intake plus same-source review only; never re-dispatch writer."""
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
import argparse,json,re,sys
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from scripts import run_legal_complete_revision_v11 as prior
from scripts import creative_resume_dispatch_v3 as control
from scripts.creative_call_evidence_v1 import CallEvidenceJournal
from scripts.creative_evidenced_role_clients_v1 import parse_saved_response
from jsonschema import Draft202012Validator

SOURCE_DIRECTORY='data/production_revisions/legal_spoken_dialogue_revision_20261010/round_12'
SOURCE_RECEIPT='call_427_complete_draft.json'
SOURCE_RECEIPT_SHA='16dbf2d6a1d78c876c8784c11cd55e2ab95fbbc1b678b734cd21c9b1d84676db'
SOURCE_REQUEST_SHA='0b2c5492ef6f6b46938b6d598f9f9df9f29d4bfed7b56c721eeba429c0ed922f'
SOURCE_OUTPUT_SHA='d4fa72bf5cab4e30dbfbd11a36e7d9da82beb8a02c5a144e4731fec27c8b2a60'
ORIGINAL_QUOTE='这是……“个人原因”？'
EQUIVALENT_QUOTE='这是……"个人原因"？'


def init(root):
    root=Path(root).resolve();source=PROJECT/SOURCE_DIRECTORY
    settings=deepcopy(control.read(source/'SETUP.json'))
    settings.update(parent_text_directory=SOURCE_DIRECTORY,saved_response_directory=SOURCE_DIRECTORY,
        saved_response_receipt=SOURCE_RECEIPT,saved_response_ordinal=427,
        saved_response_receipt_sha256=SOURCE_RECEIPT_SHA,saved_response_request_sha256=SOURCE_REQUEST_SHA,
        saved_response_output_sha256=SOURCE_OUTPUT_SHA,parent_ledger_sha256=control.sha_file(source/'CALL_LEDGER.json'),
        intake_version='saved_427_quote_equivalence_review_only/v12',draft_dispatch_allowed=False)
    control.write(root/'SETUP.json',settings,True)
    return {'setup':str(root/'SETUP.json'),'provider_called':False,'old_receipt_mutated':False}


def quote_equivalent_schema(schema):
    """Change only the B1 whole-beat const to two explicit whole-beat alternatives."""
    result=deepcopy(schema);rules=result['properties']['beats']['items']['allOf']
    if len(rules)!=4:raise ValueError('original fixed-beat and dialogue-count schema required')
    b1=[q for q in rules if q['if']['properties']['id']['const']=='B1']
    if len(b1)!=1:raise ValueError('one original B1 constraint required')
    expected=deepcopy(b1[0]['then']['const'])
    if expected['steps'][4]['text']!=ORIGINAL_QUOTE:raise ValueError('only verified B1.S05 quote is eligible')
    alternative=deepcopy(expected);alternative['steps'][4]['text']=EQUIVALENT_QUOTE
    b1[0]['then']={'enum':[expected,alternative]}
    Draft202012Validator.check_schema(result)
    return result


def validate_whole_output(raw,schema,direction):
    Draft202012Validator(schema).validate(raw)
    compiled=prior.compile_writer_script(raw,direction)
    creative=deepcopy(compiled);creative.pop('selected_candidate_id')
    if creative!=raw:raise ValueError('compiler changed creative content')
    for b in compiled['beats']:
        for q in b['steps']:
            if q['kind']=='action' and re.search(r'(?:说|道)[“\"]',q['text']):raise ValueError('dialogue hidden in action')
    findings=prior.check_current_scene_facts(compiled)
    if findings:raise ValueError('saved response has unresolved current facts: '+json.dumps(findings,ensure_ascii=False))
    return compiled,{**prior.validate_complete_story(compiled,direction),'script_sha256':control.digest(compiled),
        'raw_creative_sha256':control.digest(raw),'full_model_script':True,'creative_text_changed_locally':False,
        'local_current_fact_findings':findings,'creative_quality_passed':False}


def inspect_saved_source(settings):
    """Pure reads, protocol parsing with memory-only events, and no original status rewrite."""
    if settings.get('saved_response_directory')!=SOURCE_DIRECTORY or settings.get('saved_response_receipt')!=SOURCE_RECEIPT or settings.get('saved_response_ordinal')!=427:
        raise ValueError('this intake only accepts the exact original427 source')
    source=PROJECT/SOURCE_DIRECTORY;ledger_path=source/'CALL_LEDGER.json';ledger=control.read(ledger_path)
    if control.sha_file(ledger_path)!=settings['parent_ledger_sha256']:raise ValueError('parent ledger changed')
    prior.verify_files({str(PROJECT/p):h for p,h in ledger['source_manifest'].items()})
    prior.verify_files({str(source/'source_at_dispatch'/p):h for p,h in ledger['source_manifest'].items()})
    rows=ledger['calls']
    if len(rows)!=1 or rows[0]['ordinal']!=427 or rows[0]['label']!='complete_draft' or rows[0]['receipt']!=SOURCE_RECEIPT:
        raise ValueError('only the single known rejected427 call may be inherited')
    receipt_path=source/SOURCE_RECEIPT;r=control.read(receipt_path)
    if control.sha_file(receipt_path)!=SOURCE_RECEIPT_SHA or rows[0]['receipt_sha256']!=SOURCE_RECEIPT_SHA or settings['saved_response_receipt_sha256']!=SOURCE_RECEIPT_SHA:
        raise ValueError('original427 receipt changed')
    if r['ordinal']!=427 or r['label']!='complete_draft' or r['status']!='contract_rejected' or r.get('failure',{}).get('code')!='MODULE_SCHEMA_INVALID' or r.get('validation_error',{}).get('path')!=['beats',0]:
        raise ValueError('only the evidenced original quote contract rejection is eligible')
    if control.digest(r['request'])!=SOURCE_REQUEST_SHA or r['request_sha256']!=SOURCE_REQUEST_SHA or settings['saved_response_request_sha256']!=SOURCE_REQUEST_SHA:
        raise ValueError('original request binding changed')
    if r['source_binding_sha256']!=control.digest(ledger['source_manifest']):raise ValueError('original source binding changed')
    if r['request']!=control.read(source/'request_previews/draft.json'):raise ValueError('original request preview differs')
    identity={'ordinal':427,'label':'complete_draft','request_sha256':r['request_sha256'],
        'source_binding_sha256':r['source_binding_sha256'],'role':r['request']['role'],'model':r['request']['model']}
    journal=CallEvidenceJournal(source/'call_evidence/call_427',identity,create=False)
    if journal.identity_sha256!=r['call_evidence']['identity_sha256']:raise ValueError('original call evidence differs')
    body,manifest=journal.load_body();phases=[]
    parsed=parse_saved_response(body,manifest,'writer','MiniMax-M3',r['request']['parameters']['thinking'],r['request']['structured_schema'],SimpleNamespace(record=lambda p,d:phases.append({'phase':p,'details':deepcopy(d)})))
    if control.response_failure(parsed.metadata,parsed.text,require_tool=True):raise ValueError('saved reply did not complete its tool contract')
    if parsed.metadata!=r['response_metadata'] or parsed.text!=r['response_text'] or parsed.response_payload!=r['response_payload']:
        raise ValueError('saved protocol response differs from original receipt')
    if parsed.metadata.get('total_tokens')!=7120 or parsed.metadata.get('finish_reason')!='tool_calls' or parsed.metadata.get('response_body_complete') is not True:
        raise ValueError('complete known7120 tool response required; unknown cannot be inherited')
    raw=control.strict_json(parsed.text)
    if raw!=r['output'] or control.digest(raw)!=SOURCE_OUTPUT_SHA or settings['saved_response_output_sha256']!=SOURCE_OUTPUT_SHA:
        raise ValueError('whole original creative response changed')
    original_schema=r['request']['structured_schema'];errors=list(Draft202012Validator(original_schema).iter_errors(raw))
    if len(errors)!=1 or errors[0].validator!='const' or list(errors[0].absolute_path)!=['beats',0]:raise ValueError('rejection was not solely the verified fixed quote')
    schema=quote_equivalent_schema(original_schema)
    original_input=control.read(source/'INPUT.json')
    compiled,validation=validate_whole_output(raw,schema,original_input['source_direction'])
    assessment={'schema':'saved_response_local_contract_assessment/v12','status':'locally_contract_assessed_pending_full_review',
        'source_ordinal':427,'original_status':'contract_rejected','original_receipt_sha256':SOURCE_RECEIPT_SHA,
        'original_request_sha256':SOURCE_REQUEST_SHA,'original_source_binding_sha256':r['source_binding_sha256'],
        'original_response_body_sha256':control.sha_file(source/'call_evidence/call_427/response_body.raw'),
        'original_failure':deepcopy(r['failure']),'original_validation_error':deepcopy(r['validation_error']),
        'new_constraint':'Only B1.S05 allows either the exact Chinese-quote or ASCII-quote spelling; every other raw B1/B4 field and original schema remains fixed.',
        'original_schema_sha256':control.digest(original_schema),'intake_schema_sha256':control.digest(schema),
        'validation':validation,'provider_called_for_local_intake':False,'original_receipt_mutated':False,
        'whole_raw_normalized_or_spliced':False,'creative_quality_passed':False}
    return ledger,r,raw,compiled,schema,assessment


class Revision(prior.Revision):
    def prepare(self):
        ledger,r,raw,compiled,schema,assessment=inspect_saved_source(self.settings)
        source=PROJECT/SOURCE_DIRECTORY
        if not (self.root/'ANCHOR.json').exists():
            inherited=deepcopy(ledger['starting_spend'])
            inherited.update(calls_started=inherited['calls_started']+1,reported_tokens=inherited['reported_tokens']+7120,
                calls_with_known_usage=inherited['calls_with_known_usage']+1,parent_ledger_sha256=control.sha_file(source/'CALL_LEDGER.json'))
            if inherited['calls_started']!=427 or inherited['reported_tokens']!=6750566 or inherited['unknown_token_reservations']!=93117:
                raise ValueError('original cumulative spend is not exact427 lineage')
            for name in ['INPUT.json','CURRENT_BRIEF.json','INPUT_PROJECTION.json','USER_FEEDBACK.json','WRITER_SCHEMA.json']:
                value=control.read(source/name)
                if name=='INPUT.json':
                    value['saved_response_intake_source']={'source_ordinal':427,'original_receipt_status':'contract_rejected',
                        'original_receipt_sha256':SOURCE_RECEIPT_SHA,'raw_creative_sha256':SOURCE_OUTPUT_SHA,
                        'local_status':assessment['status'],'local_assessment_schema':assessment['schema'],
                        'acceptance_difference':'Only B1.S05 Chinese/ASCII quote equivalence; original whole raw unchanged.',
                        'original_interface_contract_passed':False,'new_writer_call':False,'raw_normalized_or_spliced':False}
                control.write(self.root/name,value,True)
            for name,value in [('RAW_MODEL_SCRIPT.json',raw),('FULL_MODEL_SCRIPT.json',compiled),('INTAKE_SCHEMA.json',schema),('LOCAL_VALIDATION.json',assessment)]:
                control.write(self.root/name,value,True)
            files={str(PROJECT/p):h for p,h in ledger['source_manifest'].items()}
            for p in [source/'CALL_LEDGER.json',source/SOURCE_RECEIPT,source/'AUTHORIZATION.json',source/'request_previews/draft.json',*sorted((source/'call_evidence/call_427').glob('*'))]:
                if p.is_file():files[str(p)]=control.sha_file(p)
            control.write(self.root/'ANCHOR.json',{'inherited':inherited,'models':ledger['model_configs'],'parent_files':files,
                'automatic_retry':False,'media_authorized':False,'budget_reset':False,'old_governance_migrated':False,
                'intake_source_status':'contract_rejected','local_intake_calls':0,'writer_dispatch_allowed':False},True)
        if control.read(self.root/'LOCAL_VALIDATION.json')!=assessment or control.read(self.root/'RAW_MODEL_SCRIPT.json')!=raw or control.read(self.root/'FULL_MODEL_SCRIPT.json')!=compiled:
            raise ValueError('local saved-response assessment or whole script changed')
        self.runtime().prepare();return self.summary()

    def runtime(self):
        a=control.read(self.root/'ANCHOR.json')
        own=[Path(__file__).resolve(),Path(prior.__file__).resolve(),PROJECT/'src/content_factory/creative_legal_current_facts_gate_v4.py',
            PROJECT/'scripts/creative_resume_dispatch_v3.py',PROJECT/'scripts/creative_evidenced_role_clients_v1.py',PROJECT/'scripts/creative_call_evidence_v1.py',
            PROJECT/'src/content_factory/creative_trend_bridge.py',PROJECT/'src/content_factory/creative_current_brief_projection_v1.py',
            *[self.root/n for n in ['SETUP.json','INPUT.json','CURRENT_BRIEF.json','INPUT_PROJECTION.json','USER_FEEDBACK.json','WRITER_SCHEMA.json',
                'RAW_MODEL_SCRIPT.json','FULL_MODEL_SCRIPT.json','INTAKE_SCHEMA.json','LOCAL_VALIDATION.json','ANCHOR.json']]]
        def guard():
            prior.verify_files(a['parent_files']);inspect_saved_source(self.settings)
        return control.ContinuationRuntime(PROJECT,self.root,own+[Path(p) for p in a['parent_files']],a['inherited'],a['models'],
            inherited_guard=guard,quota_state=None,shared_lock=prior.identity.SHARED_LOCK)

    def accepted(self,label):
        if label=='complete_draft':
            _,r,raw,compiled,schema,assessment=inspect_saved_source(self.settings)
            if control.read(self.root/'LOCAL_VALIDATION.json')!=assessment or control.read(self.root/'RAW_MODEL_SCRIPT.json')!=raw or control.read(self.root/'FULL_MODEL_SCRIPT.json')!=compiled:
                raise ValueError('saved whole script or local assessment changed')
            return {'ordinal':427,'status':'locally_contract_assessed_pending_full_review','original_status':'contract_rejected',
                'original_receipt_sha256':SOURCE_RECEIPT_SHA,'output':deepcopy(raw),'validation':deepcopy(assessment['validation'])}
        return super().accepted(label)

    def dispatch(self,stage):
        if stage!='review':raise ValueError('v12 only reviews the original saved427 whole response; writer dispatch prohibited')
        return super().dispatch(stage)

    def finish(self):
        s=self.script();d=self.accepted('complete_draft');r=self.accepted('full_review');gate=control.read(self.root/'INDEPENDENT_EDITORIAL_GATE.json')
        if d['validation']['local_current_fact_findings'] or r['validation']['script_sha256']!=control.digest(s) or r['validation']['needs_revision'] or gate['script_sha256']!=control.digest(s) or not gate['text_candidate_qualified'] or gate['unresolved_mandatory_findings']:
            raise ValueError('complete same-source review/editorial gate unresolved')
        out=self.root/'REVIEWED_CANDIDATE'
        for name,value in [('FULL_SCRIPT.json',s),('RAW_MODEL_SCRIPT.json',d['output']),('FULL_TEXT_REVIEW.json',r['output']),
            ('USER_FEEDBACK.json',control.read(self.root/'USER_FEEDBACK.json')),('CURRENT_BRIEF.json',control.read(self.root/'CURRENT_BRIEF.json')),
            ('INDEPENDENT_EDITORIAL_GATE.json',gate),('SAVED_RESPONSE_LOCAL_ASSESSMENT.json',control.read(self.root/'LOCAL_VALIDATION.json'))]:
            control.write(out/name,value,True)
        prior.baseline.write_readable(out/'FULL_SCRIPT.md',prior.render_script(s,'原427完整回复仅离线引号等价验收并完成同源全文复审；待用户核对，新视频0。'))
        control.write(out/'HANDOFF.json',{'status':'complete_reviewed_text_awaiting_human_content_confirmation','draft_ordinal':427,
            'review_ordinal':r['ordinal'],'script_sha256':control.digest(s),'raw_creative_sha256':control.digest(d['output']),
            'original_draft_receipt_status':'contract_rejected','original_draft_receipt_sha256':SOURCE_RECEIPT_SHA,
            'local_intake_status':d['status'],'creative_text_changed_locally':False,'whole_raw_normalized_or_spliced':False,
            'old_director_performance_and_video_invalidated_for_new_script':True,'new_director_and_performance_built':False,
            'human_quality_approved':False,'video_calls':0,'spend':self.summary()},True)
        return {'candidate':str(out/'FULL_SCRIPT.md'),'draft_ordinal':427,'review_ordinal':r['ordinal'],'spend':self.summary()}


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');ap=argparse.ArgumentParser();ap.add_argument('run_dir');ap.add_argument('stage',choices=['init','prepare','review','finish','status']);args=ap.parse_args()
    if args.stage=='init':result=init(args.run_dir)
    else:
        op=Revision(args.run_dir);result=op.prepare() if args.stage=='prepare' else op.summary() if args.stage=='status' else op.finish() if args.stage=='finish' else op.dispatch('review')
    print(json.dumps(result,ensure_ascii=False),flush=True)
