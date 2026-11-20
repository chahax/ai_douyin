"""Evidence-based ending refinement; validation uses captured immutable request, no re-entry."""
from pathlib import Path
from copy import deepcopy
import argparse,json,re,sys
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from scripts import run_legal_ending_revision_v13 as base
control=base.control;prior=base.prior
PARENT='data/production_revisions/legal_ending_withdrawal_revision_20261011/round_01'

class Revision(base.Revision):
    def prepare(self):
        if not (self.root/'ANCHOR.json').exists():
            parent=PROJECT/PARENT;l=control.read(parent/'CALL_LEDGER.json');prior.verify_files({str(PROJECT/p):h for p,h in l['source_manifest'].items()})
            if [q['ordinal'] for q in l['calls']]!=[429,430]:raise ValueError('exact known429/430 parent required')
            receipts=[]
            for row in l['calls']:
                p=parent/row['receipt'];r=control.read(p)
                if control.sha_file(p)!=row['receipt_sha256'] or type(r['response_metadata']['total_tokens']) is not int or r['response_metadata']['response_body_complete'] is not True:raise ValueError('parent changed or unknown')
                receipts.append(r)
            if receipts[0]['status']!='contract_valid' or receipts[1]['status']!='contract_rejected' or receipts[1]['failure']['code']!='receipt changed; reconcile':raise ValueError('only verified local430 validation failure eligible')
            assessment=control.read(parent/'LOCAL_REVIEW430_ASSESSMENT.json')
            if assessment['receipt_sha256']!=control.sha_file(parent/'call_430_full_review.json') or assessment['schema_and_actual_same_source_locally_verified'] is not True:raise ValueError('saved430 proof missing')
            gate=control.read(parent/'INDEPENDENT_EDITORIAL_GATE.json');s=control.read(parent/'FULL_MODEL_SCRIPT.json')
            if gate['script_sha256']!=control.digest(s) or gate['text_candidate_qualified'] is not False:raise ValueError('actual evidenced rejected candidate required')
            findings=prior.editorial_requirements(gate)
            x=deepcopy(control.read(parent/'INPUT.json'));x['draft_to_replace_not_facts']=s
            x['independent_editorial_revision']=gate;x['previous_full_review']=receipts[1]['output']
            x['spoken_language_revision_criteria'].append({'id':'one_resolved_closure','criterion':'当前429已用第一条回应说明本次签不下来；后面追加泛化收尾是本轮未解决问题。B4只保留一次对拒绝的实际回应，在取回前或同时说，之后以收未签材料、周姐独自离开、小林留坐门关后呼气完成事件，不再补第二句结束语。此处是本轮消除重复的选择，非所有剧本通用句数。'})
            schema=deepcopy(control.read(parent/'WRITER_SCHEMA.json'));schema['properties']['beats']['items']['allOf'].append({'if':{'properties':{'id':{'const':'B4'}},'required':['id']},'then':{'properties':{'steps':{'contains':{'type':'object','properties':{'kind':{'const':'dialogue'}},'required':['kind']},'minContains':1,'maxContains':1}}}})
            for n,v in [('CURRENT_BRIEF.json',control.read(parent/'CURRENT_BRIEF.json')),('INPUT_PROJECTION.json',control.read(parent/'INPUT_PROJECTION.json')),('INPUT.json',x),('USER_FEEDBACK.json',x['feedback']),('WRITER_SCHEMA.json',schema),('PRESERVED_SINGLE_SOURCE.json',control.read(parent/'PRESERVED_SINGLE_SOURCE.json'))]:control.write(self.root/n,v,True)
            inherited=deepcopy(l['starting_spend']);inherited.update(calls_started=inherited['calls_started']+2,reported_tokens=inherited['reported_tokens']+sum(r['response_metadata']['total_tokens'] for r in receipts),calls_with_known_usage=inherited['calls_with_known_usage']+2,parent_ledger_sha256=control.sha_file(parent/'CALL_LEDGER.json'))
            files={str(PROJECT/p):h for p,h in l['source_manifest'].items()}
            for p in [parent/'CALL_LEDGER.json',parent/'call_429_complete_draft.json',parent/'call_430_full_review.json',parent/'LOCAL_REVIEW430_ASSESSMENT.json',parent/'FULL_MODEL_SCRIPT.json',parent/'INDEPENDENT_EDITORIAL_GATE.json',Path(base.__file__).resolve()]:files[str(p)]=control.sha_file(p)
            control.write(self.root/'ANCHOR.json',{'inherited':inherited,'models':l['model_configs'],'parent_files':files,'automatic_retry':False,'media_authorized':False,'budget_reset':False,'old_governance_migrated':False,'preserved_beat_ids':['B1','B2','B3'],'rewrite_beat_ids':['B4']},True)
        self.runtime().prepare();return self.summary()
    def runtime(self):
        a=control.read(self.root/'ANCHOR.json');own=[Path(__file__).resolve(),Path(base.__file__).resolve(),Path(prior.__file__).resolve(),Path(prior.baseline.__file__).resolve(),PROJECT/'scripts/finish_legal_ending_candidate_v1.py',PROJECT/'scripts/creative_resume_dispatch_v3.py',PROJECT/'src/content_factory/creative_legal_current_facts_gate_v4.py',PROJECT/'src/content_factory/creative_trend_bridge.py',PROJECT/'src/content_factory/creative_current_brief_projection_v1.py',PROJECT/'scripts/run_confirmed_legal_script_trial_v4.py',*[self.root/n for n in ['SETUP.json','INPUT.json','USER_FEEDBACK.json','CURRENT_BRIEF.json','INPUT_PROJECTION.json','WRITER_SCHEMA.json','PRESERVED_SINGLE_SOURCE.json','ANCHOR.json']],*sorted((PROJECT/'src/content_factory').glob('creative_legal_dialogue_craft_v*.py'))]
        return control.ContinuationRuntime(PROJECT,self.root,own+[Path(p) for p in a['parent_files']],a['inherited'],a['models'],inherited_guard=lambda:prior.verify_files(a['parent_files']),quota_state=None,shared_lock=prior.identity.SHARED_LOCK)
    @staticmethod
    def validate_captured(stage,v,req,direction,script):
        prior.Draft202012Validator(req['structured_schema']).validate(v)
        if stage=='draft':
            s=prior.compile_writer_script(v,direction);raw=deepcopy(s);raw.pop('selected_candidate_id')
            if raw!=v:raise ValueError('compiler changed creative content')
            for b in s['beats']:
                for q in b['steps']:
                    if q['kind']=='action' and re.search(r'(?:说|道)[“\"]',q['text']):raise ValueError('dialogue hidden in action')
            return {**prior.validate_complete_story(s,direction),'script_sha256':control.digest(s),'full_model_script':True,'creative_text_changed_locally':False,'local_current_fact_findings':prior.check_current_scene_facts(s),'creative_quality_passed':False}
        return {'full_review_complete':True,'script_sha256':control.digest(script),'needs_revision':bool(v['issues']) or not v['story_invariants_preserved'] or not v['human_spoken_language_feedback_addressed'],'creative_quality_passed':False}
    def dispatch(self,stage):
        self.prepare();req,label=self.request(stage);direction=deepcopy(control.read(self.root/'INPUT.json')['source_direction']);script=deepcopy(self.script()) if stage=='review' else None
        control.write(self.root/'request_previews'/f'{stage}.json',req,True)
        r=self.runtime().dispatch(label,req,lambda v:self.validate_captured(stage,v,req,direction,script))
        if stage=='draft' and r['status']=='contract_valid':
            control.write(self.root/'FULL_MODEL_SCRIPT.json',self.script(),True)
            prior.baseline.write_readable(self.root/'FULL_SCRIPT_DRAFT.md',prior.render_script(self.script(),'完整MiniMax结尾返修新稿；待全文复审及用户核对，新视频0。'))
        return {'ordinal':r['ordinal'],'status':r['status'],'validation':r.get('validation'),'failure':r.get('failure'),'spend':self.summary()}

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');ap=argparse.ArgumentParser();ap.add_argument('run_dir');ap.add_argument('stage',choices=['prepare','draft','review','status']);a=ap.parse_args();op=Revision(a.run_dir)
    print(json.dumps(op.prepare() if a.stage=='prepare' else op.summary() if a.stage=='status' else op.dispatch(a.stage),ensure_ascii=False),flush=True)
