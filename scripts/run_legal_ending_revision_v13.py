"""Current human ending feedback: whole native revision, preserved B1-B3, full review."""
from pathlib import Path
from copy import deepcopy
import argparse,json,re,sys
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from scripts import run_legal_complete_revision_v11 as prior
control=prior.control
SOURCE='data/production_revisions/legal_spoken_dialogue_revision_20261010/round_12_quote_acceptance_v12'
SOURCE_RAW_SHA='d4fa72bf5cab4e30dbfbd11a36e7d9da82beb8a02c5a144e4731fec27c8b2a60'


def fixed_beat_schema(base,raw):
    result=deepcopy(base);items=result['properties']['beats']['items']
    items.pop('allOf',None)
    rules=[]
    for b in raw['beats'][:3]:
        variants=[deepcopy(b)]
        alternate=deepcopy(b)
        for step in alternate['steps']:
            if '\"个人原因\"' in step['text']:step['text']=step['text'].replace('\"个人原因\"','“个人原因”')
        alternate['trigger']=alternate['trigger'].replace('\"个人原因\"','“个人原因”')
        if alternate!=b:variants.append(alternate)
        rules.append({'if':{'properties':{'id':{'const':b['id']}},'required':['id']},'then':{'enum':variants}})
    items['allOf']=rules
    prior.Draft202012Validator.check_schema(result)
    return result


class Revision(prior.Revision):
    def prepare(self):
        if not (self.root/'ANCHOR.json').exists():
            parent=PROJECT/SOURCE;ledger=control.read(parent/'CALL_LEDGER.json')
            prior.verify_files({str(PROJECT/p):h for p,h in ledger['source_manifest'].items()})
            if len(ledger['calls'])!=1 or ledger['calls'][0]['ordinal']!=428:raise ValueError('exact428 parent required')
            row=ledger['calls'][0];receipt=control.read(parent/row['receipt'])
            if control.sha_file(parent/row['receipt'])!=row['receipt_sha256'] or receipt['status']!='contract_valid':raise ValueError('parent unknown or changed')
            compiled=control.read(parent/'REVIEWED_CANDIDATE/FULL_SCRIPT.json');raw=control.read(parent/'REVIEWED_CANDIDATE/RAW_MODEL_SCRIPT.json')
            if control.digest(raw)!=SOURCE_RAW_SHA or receipt['validation']['script_sha256']!=control.digest(compiled) or receipt['validation']['needs_revision']:raise ValueError('exact whole source and full review required')
            brief=prior.baseline.current_brief(compiled);brief['source_identity']['source_id']='current427_script_and_explicit_human_B4_feedback'
            projection=prior.project_current_brief(brief,{'schema':'current_ending_revision/v13'})
            direction={'schema':'current_revision_direction/v1','current_brief_identity':projection['identity'],'characters':[{'name':q['name']} for q in brief['characters']]}
            feedback={'schema':'human_ending_feedback/v13','user_statement':self.settings['user_statement'],'source_script_sha256':control.digest(compiled),'source_raw_sha256':control.digest(raw),'source_ordinal':427,'reported_issue':'结尾只告知离场，未兑现本场索签失败的结果','source':'human_current_script_feedback','assistant_viewed_or_listened':False,'formal_binary_media_rejection_invented':False,'new_video_authorized':False}
            old=control.read(parent/'INPUT.json')
            finding={'code':'HUMAN_EMPTY_ENDING','evidence_refs':['B3.S01','B3.S02','B4.S01','B4.S02'],'evidence_text':'周姐：小林，就当帮我一个忙，表你签了，我拿去交差。 | 小林：你为难我懂，可这字一签，离职就是我说的，这事我不能帮你。 | 周姐收纸笔站起后仅说：那先走了。','problem':'第二次求签失败后只告知离开，没有明确停止索签/撤回当前未签申请的言语行动，离场缺少当面交涉的结果。','required_revision':'只重写B4，使第二次拒签明确导致周姐放弃本次索签并取回当前未签申请。台词对小林刚才的拒绝作真实应答，表达当面材料撤回/当前申请办不成，放在取回前或同时；动作收一次纸笔入夹、周姐独自走、小林留坐门关后呼气。不加第三轮劝签、未来承诺或法律结论。完整提交四拍，不本地回填。'}
            criteria=[{'id':'ending_causal_withdrawal','criterion':finding['required_revision']},{'id':'spoken_action','criterion':'结尾用自然的当面言语行动回应对方，不使用那先走了/那先这样/今天先到这等空泛结束语。不要求金句，不复述前面道理，不用象征空镜代替事件结果。'},{'id':'preserved_scope','criterion':'同一427原生完整稿的B1/B2/B3保持；仅个人原因的中文/ASCII引号等价可选。B4在本次人类反馈后开放重写，旧版固定B4选择被本次要求取代，旧记录保留。标题不签的字。'}]
            x={'source_direction':direction,'current_projection':projection,'reference_fulltext':old['reference_fulltext'],'feedback':feedback,'draft_to_replace_not_facts':compiled,'spoken_language_revision_criteria':criteria,'legal_expression_boundaries':old['legal_expression_boundaries'],'independent_editorial_revision':{'schema':'current_human_revision_findings/v13','text_candidate_qualified':False,'unresolved_mandatory_findings':[finding],'previous428_review_unchanged':True},'source_provenance':{'raw427_original_status':'contract_rejected','local427_quote_intake':'whole native output unchanged, local quote-equivalent intake plus428 full review','single_whole_raw_sha256':SOURCE_RAW_SHA}}
            schema=fixed_beat_schema(control.read(parent/'WRITER_SCHEMA.json'),raw)
            for n,v in [('CURRENT_BRIEF.json',brief),('INPUT_PROJECTION.json',projection),('INPUT.json',x),('USER_FEEDBACK.json',feedback),('WRITER_SCHEMA.json',schema),('PRESERVED_SINGLE_SOURCE.json',raw)]:control.write(self.root/n,v,True)
            inherited=deepcopy(ledger['starting_spend']);tokens=receipt['response_metadata']['total_tokens']
            if type(tokens) is not int:raise ValueError('unknown parent usage')
            inherited.update(calls_started=inherited['calls_started']+1,reported_tokens=inherited['reported_tokens']+tokens,calls_with_known_usage=inherited['calls_with_known_usage']+1,parent_ledger_sha256=control.sha_file(parent/'CALL_LEDGER.json'))
            files={str(PROJECT/p):h for p,h in ledger['source_manifest'].items()}
            for p in [parent/'CALL_LEDGER.json',parent/row['receipt'],parent/'INPUT.json',parent/'WRITER_SCHEMA.json',parent/'LOCAL_VALIDATION.json',*[parent/'REVIEWED_CANDIDATE'/n for n in ['RAW_MODEL_SCRIPT.json','FULL_SCRIPT.json','HANDOFF.json','INDEPENDENT_EDITORIAL_GATE.json']]]:files[str(p)]=control.sha_file(p)
            control.write(self.root/'ANCHOR.json',{'inherited':inherited,'models':ledger['model_configs'],'parent_files':files,'automatic_retry':False,'media_authorized':False,'budget_reset':False,'old_governance_migrated':False,'preserved_beat_ids':['B1','B2','B3'],'rewrite_beat_ids':['B4']},True)
        self.runtime().prepare();return self.summary()
    def runtime(self):
        a=control.read(self.root/'ANCHOR.json')
        own=[Path(__file__).resolve(),Path(prior.__file__).resolve(),Path(prior.baseline.__file__).resolve(),PROJECT/'scripts/creative_resume_dispatch_v3.py',PROJECT/'src/content_factory/creative_legal_current_facts_gate_v4.py',PROJECT/'src/content_factory/creative_trend_bridge.py',PROJECT/'src/content_factory/creative_current_brief_projection_v1.py',PROJECT/'scripts/run_confirmed_legal_script_trial_v4.py',*[self.root/n for n in ['SETUP.json','INPUT.json','USER_FEEDBACK.json','CURRENT_BRIEF.json','INPUT_PROJECTION.json','WRITER_SCHEMA.json','PRESERVED_SINGLE_SOURCE.json','ANCHOR.json']],*sorted((PROJECT/'src/content_factory').glob('creative_legal_dialogue_craft_v*.py'))]
        return control.ContinuationRuntime(PROJECT,self.root,own+[Path(p) for p in a['parent_files']],a['inherited'],a['models'],inherited_guard=lambda:prior.verify_files(a['parent_files']),quota_state=None,shared_lock=prior.identity.SHARED_LOCK)
    def request(self,stage):
        x=control.read(self.root/'INPUT.json');m=control.read(self.root/'ANCHOR.json')['models']
        payload={k:deepcopy(x[k]) for k in ['reference_fulltext','feedback','spoken_language_revision_criteria','legal_expression_boundaries','source_provenance']}
        payload['authoring']=deepcopy(x['current_projection']['writer_context']);prior.verify_writer_request(payload['authoring'],x['current_projection'])
        if stage=='draft':
            payload['evidenced_revision_findings']=prior.editorial_requirements(x['independent_editorial_revision'])
            payload['unchanged_beats_from_single_full_model_source']={'source_ordinal':427,'source_raw_sha256':SOURCE_RAW_SHA,'beats':control.read(self.root/'PRESERVED_SINGLE_SOURCE.json')['beats'][:3],'use':'由模型原样保留前三拍并完整提交四拍；只重写B4，不本地拼接。引号等价拼写见schema。'}
            schema=control.read(self.root/'WRITER_SCHEMA.json');role='writer';label='complete_draft';cap=4500
            rule='你是影视编剧。按照当前简报及真实用户结尾反馈，提交完整四拍新稿。标题不签的字，B1/B2/B3来自所给单一427原生完整稿，由你原样保留在此次完整输出中，只重写B4的event/trigger/steps并同步premise。旧版固定B4要求已被当前反馈取代。B3周姐求帮忙签字交差，小林再次拒绝；B4要让周姐实际承认本次拿不到签名，停止索签，撤回眼前这份未签申请。用自然当面口语表达当前谈话的结果，话与取回纸笔同一行动，不只是那先走了/今天先到这空告离场，不复述前面理由、不追问第三次。台词在取回前或同时发生。然后一次从小林近桌沿取回纸和笔放进文件夹，周姐拿文件夹独自出门，小林留坐，门关后短呼气，争议未解决。不新增第三人、场景、道具、公司后续承诺、截止时间、劳动争议事实或法律结论。不把撤回这张申请写成撤销公司让小林走的决定，不给大团圆。R01全文只借刺激反应、行动目的和余味机制，不照搬剧情。不写逐秒面部肌肉指令、不朗诵金句。按schema一次输出完整title/premise/beats，四拍顺序B1至B4，每句dialogue独立、action不藏发言；不输出分析。'
        elif stage=='review':
            s=self.script();payload.update(full_current_script=s,source_catalog=prior.baseline.evidence(s),independent_editorial_revision=x['independent_editorial_revision'])
            schema=prior.baseline.review_schema(s);schema['properties']['human_spoken_language_feedback_addressed']={'type':'boolean'};schema['required'].append('human_spoken_language_feedback_addressed')
            role='director';label='full_review';cap=5500
            rule='DeepSeek同源全文复审：完整读取每拍每句、当前事实、真实B4反馈与R01。前三拍已保留，不能以改写不在本轮范围的前三拍来代替结尾修复。重点核对B3第二次拒绝是否明确导致B4停止索签并撤回当前未签申请；台词是当前交涉结果，且在开始取回前或同时说，不是已收完才空报离开。不把动作概要或premise当实际对白的因果证据。不能新增未来公司承诺、第三轮劝签/拒绝、法律结论、撤销公司让员工离开的决定或手续最终解决。紙笔只能一次从小林近桌沿取回入夹，周姐独自走、小林留坐门关后呼气。全文仍核对预填个人原因、先公司口径后私人求帮、两次拒签；对自然口语依据当前语境评判，不硬禁词、不强加金句。不手改正文，提交完整review，问题具体举当前证据；审美和未验证实际表演放suggestions，不声称用户或视频质量通过。'
        else:raise ValueError('explicit draft/review only')
        req={'role':role,'model':m[role]['model'],'messages':[{'role':'system','content':rule},{'role':'user','content':json.dumps(payload,ensure_ascii=False,separators=(',',':'))}],'structured_schema':schema,'parameters':{'max_completion_tokens':cap,'temperature':.4,'thinking':'disabled'},'input_provenance':{'operator_version':'current_human_ending_revision/v13','reference_fulltext_in_actual_messages':True,'reference_fulltext_sha256':control.digest(x['reference_fulltext']),'human_feedback_in_actual_messages':True,'preserved_single_native_source_ordinal':427,'preserved_beat_ids':['B1','B2','B3'],'rewrite_beat_ids':['B4'],'full_new_script_in_review':stage=='review','creative_text_changed_locally':False,'new_media_authorized':False,'budget_reset':False}}
        return req,label
    def validate_output(self,stage,v):
        req,_=self.request(stage);x=control.read(self.root/'INPUT.json');prior.Draft202012Validator(req['structured_schema']).validate(v)
        if stage=='draft':
            s=prior.compile_writer_script(v,x['source_direction']);creative=deepcopy(s);creative.pop('selected_candidate_id')
            if creative!=v:raise ValueError('compiler changed creative body')
            for b in s['beats']:
                for q in b['steps']:
                    if q['kind']=='action' and re.search(r'(?:说|道)[“\"]',q['text']):raise ValueError('dialogue hidden in action')
            return {**prior.validate_complete_story(s,x['source_direction']),'script_sha256':control.digest(s),'full_model_script':True,'creative_text_changed_locally':False,'local_current_fact_findings':prior.check_current_scene_facts(s),'creative_quality_passed':False}
        return {'full_review_complete':True,'script_sha256':control.digest(self.script()),'needs_revision':bool(v['issues']) or not v['story_invariants_preserved'] or not v['human_spoken_language_feedback_addressed'],'creative_quality_passed':False}
    def dispatch(self,stage):
        self.prepare();req,label=self.request(stage);control.write(self.root/'request_previews'/f'{stage}.json',req,True)
        r=self.runtime().dispatch(label,req,lambda v:self.validate_output(stage,v))
        if stage=='draft' and r['status']=='contract_valid':
            control.write(self.root/'FULL_MODEL_SCRIPT.json',self.script(),True)
            prior.baseline.write_readable(self.root/'FULL_SCRIPT_DRAFT.md',prior.render_script(self.script(),'完整MiniMax结尾返修新稿；待全文复审及用户核对，新视频0。'))
        return {'ordinal':r['ordinal'],'status':r['status'],'validation':r.get('validation'),'failure':r.get('failure'),'validation_error':r.get('validation_error'),'spend':self.summary()}

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');ap=argparse.ArgumentParser();ap.add_argument('run_dir');ap.add_argument('stage',choices=['prepare','draft','review','finish','status']);a=ap.parse_args();op=Revision(a.run_dir)
    print(json.dumps(op.prepare() if a.stage=='prepare' else op.summary() if a.stage=='status' else op.finish() if a.stage=='finish' else op.dispatch(a.stage),ensure_ascii=False),flush=True)
