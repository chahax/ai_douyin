"""Current B4 four-step output contract: one reply and three event actions, whole script."""
from pathlib import Path
from copy import deepcopy
import argparse,json,sys
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from scripts import run_legal_ending_revision_v14 as base
control=base.control;prior=base.prior
PARENT='data/production_revisions/legal_ending_withdrawal_revision_20261011/round_02'

def four_step_schema(schema):
    schema=deepcopy(schema);items=schema['properties']['beats']['items'];items['allOf']=[q for q in items['allOf'] if q['if']['properties']['id']['const']!='B4']
    step=deepcopy(items['properties']['steps']['items'])
    slots=[]
    for kind,speaker in [('dialogue','周姐（虚构人事主管）'),('action',''),('action',''),('action','')]:
        slot=deepcopy(step);slot['properties']['kind']={'const':kind};slot['properties']['speaker']={'const':speaker};slots.append(slot)
    items['allOf'].append({'if':{'properties':{'id':{'const':'B4'}},'required':['id']},'then':{'properties':{'steps':{'type':'array','minItems':4,'maxItems':4,'prefixItems':slots,'items':False}}}})
    prior.Draft202012Validator.check_schema(schema);return schema

class Revision(base.Revision):
    def prepare(self):
        if not (self.root/'ANCHOR.json').exists():
            parent=PROJECT/PARENT;l=control.read(parent/'CALL_LEDGER.json');prior.verify_files({str(PROJECT/p):h for p,h in l['source_manifest'].items()})
            if len(l['calls'])!=1 or l['calls'][0]['ordinal']!=431:raise ValueError('exact known431 parent required')
            row=l['calls'][0];r=control.read(parent/row['receipt'])
            if control.sha_file(parent/row['receipt'])!=row['receipt_sha256'] or r['status']!='contract_rejected' or r['failure']['code']!='MODULE_SCHEMA_INVALID' or r['validation_error']['path']!=['beats',3,'steps'] or type(r['response_metadata']['total_tokens']) is not int or r['response_metadata']['response_body_complete'] is not True:raise ValueError('only evidenced complete431 output count failure eligible')
            x=deepcopy(control.read(parent/'INPUT.json'));s=prior.compile_writer_script(r['output'],x['source_direction']);gate=control.read(parent/'INDEPENDENT_REJECTED_DRAFT_GATE.json')
            if gate['script_sha256']!=control.digest(s) or gate['text_candidate_qualified'] is not False:raise ValueError('exact rejected431 evidence required')
            prior.editorial_requirements(gate);x['draft_to_replace_not_facts']=s;x['independent_editorial_revision']=gate;x.pop('previous_full_review',None)
            x['spoken_language_revision_criteria'].append({'id':'four_event_steps','criterion':'本轮B4只四项steps：第1周姐对拒签的一条具体应答，说明当前签名取不到/申请拿回去；第2动作从小林近桌沿收纸笔入夹；第3动作周姐带夹独自出门、门关；第4动作小林留坐短呼气。第2至4只动作、无新增对白。语义目的仍是交涉失败后撤回当前申请，不机械逐秒表演。'})
            for n,v in [('CURRENT_BRIEF.json',control.read(parent/'CURRENT_BRIEF.json')),('INPUT_PROJECTION.json',control.read(parent/'INPUT_PROJECTION.json')),('INPUT.json',x),('USER_FEEDBACK.json',x['feedback']),('WRITER_SCHEMA.json',four_step_schema(control.read(parent/'WRITER_SCHEMA.json'))),('PRESERVED_SINGLE_SOURCE.json',control.read(parent/'PRESERVED_SINGLE_SOURCE.json'))]:control.write(self.root/n,v,True)
            inherited=deepcopy(l['starting_spend']);inherited.update(calls_started=inherited['calls_started']+1,reported_tokens=inherited['reported_tokens']+r['response_metadata']['total_tokens'],calls_with_known_usage=inherited['calls_with_known_usage']+1,parent_ledger_sha256=control.sha_file(parent/'CALL_LEDGER.json'))
            files={str(PROJECT/p):h for p,h in l['source_manifest'].items()}
            for p in [Path(__file__).resolve(),PROJECT/'scripts/finish_legal_ending_candidate_v2.py',parent/'CALL_LEDGER.json',parent/row['receipt'],parent/'INDEPENDENT_REJECTED_DRAFT_GATE.json']:files[str(p)]=control.sha_file(p)
            control.write(self.root/'ANCHOR.json',{'inherited':inherited,'models':l['model_configs'],'parent_files':files,'automatic_retry':False,'media_authorized':False,'budget_reset':False,'old_governance_migrated':False,'preserved_beat_ids':['B1','B2','B3'],'rewrite_beat_ids':['B4']},True)
        self.runtime().prepare();return self.summary()
    def request(self,stage):
        req,label=super().request(stage)
        if stage=='draft':req['messages'][0]['content']+=' 本轮B4.steps严格四项：周姐一条对拒绝的具体回应、收未签纸笔入夹的action、周姐独自出门关门的action、小林留坐呼气的action。第一句说完后不再有对白。不要再添今天先到这/回头再说，事件由动作完成。'
        req['input_provenance']['operator_version']='four_step_ending_revision/v15';return req,label

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');ap=argparse.ArgumentParser();ap.add_argument('run_dir');ap.add_argument('stage',choices=['prepare','draft','review','status']);a=ap.parse_args();op=Revision(a.run_dir)
    print(json.dumps(op.prepare() if a.stage=='prepare' else op.summary() if a.stage=='status' else op.dispatch(a.stage),ensure_ascii=False),flush=True)
