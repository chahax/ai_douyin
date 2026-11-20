"""Reusable unattended text pipeline: scene plan -> whole script -> semantic review + literal audit -> bounded revisions.
No assistant decision files, no transport retries, no media calls or fake human approval.
"""
from pathlib import Path
from copy import deepcopy
import argparse,json,sys
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_creative_resume_v10 as identity
from src.content_factory import creative_autonomous_text_contract_v6 as contract

PLAN_RULE='你是MiniMax编剧。先从brief每项事实展开source_obligations、initial_conditions及必要source_order。来源标识用实体entity_type/entity_id和fact_id；原文由编译器从冻结输入解析，禁止生成source_quote字段，只提交Schema规定字段。event每项表示一个原子行动/单一言语功能，不把质问与拒绝合成任选功能列表；同一fact可拆多项。initial_conditions只声明来源明确的关系、参照与朝向，未明确用unspecified。source_order只连event，仅来源明确要求的先后，不给状态或同次请求两种描述加严格先后；必要重复拒绝须真实前后发生。同一句可完成多个目的，不能一概拆句。禁止来源没有的义务、承诺、固定拍数或台词数。再规划行动因果：人物希望听者改变什么决定，阻力如何改变策略，观众在哪个刺激后感受变化。结尾是本场尝试可见结果，允许争议未解，不强制解释性总结、承诺或金句。brief是唯一剧情来源，reference_fulltext只借表达机制。若有previous_complete_plan及plan_revision_requirement，由你提交全部完整新计划，不返回补丁、不复用旧字段拼接。按Schema简明完整提交，不写长篇分析。'
AUTHOR_RULE='你是MiniMax影视编剧。依据唯一brief、场景行动计划及参考机制完整创作title/premise/beats正文。全部对白与动作由你提交，不返回补丁或片段、不要求旧拍逐字不变。事实与人物身份稳定，话轮/拍数/动作可为表达重组。对白是对眼前听者采取行动：明确谁希望谁做什么，后一句回应上一刺激，阻力改变策略，不反复换句复述同一要求。口语先可直接听懂，不堆作者主题总结、概念对举或金句；正常职业口吻可用。表情随刺激与选择产生，允许说话和必要动作同时，不写逐秒肌肉清单。结尾让前面的选择在可见行动中兑现，不强制解释性收场台词或机械告别；保留更大问题未解，不能新增公司/他人承诺。reference_fulltext借行动目的、刺激反应、画面信息和余味机制，不抄其剧情。若提供完整前稿和revision_requirements，逐项解决但可重组整篇，仍完整提交新版。正文只写观众能看见/听见的事件；premise/event/trigger不能补未演出的事实。'
REVIEW_RULE='你是DeepSeek独立全文审查。逐条填写brief全部facts及initial_state人物、道具的实际正文证据；遇到未演出的拒绝或起态改动必须fail，不把event/premise替代正文。明确错别字、词义或语病进入language_integrity失败及language_error，不以建议放行。完整读取正文每句、计划和brief，逐项评估七项功能标准并还原每条对白的施事/行为/对象与接话功能。关键句须直接听懂：核心请求若存在相反施事解读，clarity必须ambiguous/unknown，不能说语境可猜而只放建议。不要凭单词禁令判错，普通职业口吻不自动等于stilted，礼貌确认不自动等于冗余。判断具体上下文中有无实际新信息/策略/反应。结尾不要求口头宣布谈话结束或解释没签成，只检查目标受阻后人物的选择和可见结果是否接住交锋；动作可以完成结尾。不得把premise/event/trigger算作观众可见证据。七项标准与全部对白必须覆盖，证据仅evidence_catalog的正文steps。事实/道具/人物顺序全部核对，不新增法律事实作裁判。fail必须举当前证据和可执行修改目标，unknown如实保留，不能以issues为空或总体反馈已解决覆盖逐项问题。不代写替代正文，不强迫漂亮台词，不声称视频质量或人工批准。每项理由简短，避免重复长分析，按Schema完整提交。'


AUDIT_RULE='同一对白内严格先后通过occurrence_spans标注实际先后子句的完整原文quote，不要求拆成两次说话；没有span默认整步，重叠子句不能冒充先后。actual_initial_conditions必须还原最早正文动作发生前的物理状态，不能用该动作完成后的状态；从容器取出说明此前在容器内，翻正说明此前朝向未正。不知道就unknown，不能复制expected。obligation_evidence的occurrence_refs只列本义务真正发生的动作或对白，support_refs另放触发、上下文、结果，不能把所有支持证据冒充施事或行事功能。你是DeepSeek字面事实审计员，与审美全文审查独立。source_contract是源事实的可执行义务，逐项返回obligation_evidence实际正文引用与status，没有真正演出的义务不得配借另一时刻的引用；严格先后必须按实际steps发生。literal_events.speech_functions列出同一步实际演出的所有言语行动，primary speech_function必须属于数组；复合对白可同时告知和请求，但质问里没有明确拒绝要求就不能填refusal。actual_actor是实际执行行动者，dialogue实际说话者；不要把周姐说公司决定算公司当场说话。已确认的brief与初态不可改来迁就稿；需要修的是完整正文。只从full_current_script的beats.steps按发生顺序还原每一个实际动作、对白，不从title/premise/event/trigger、预期剧情或场景规划补齐没发生的事件。literal_events逐条对应evidence_catalog原始步骤、原始speaker/kind及顺序，actual_action简明记实际发生了什么，speech_function区分statement/question/request/refusal：质问、反问、表示事实不同，不等于明确拒绝对方要求；否定标记也不自动证明拒绝。道具props_origin/destination记录实际地点或持有人，未移动填空串。先照实重建，再逐条核对brief事实与初态。开始动作必须从brief初态发生，不得把编剧新增拿取、翻转解释为原有起态。每条fact_checks及initial_state_checks完整覆盖，expected文本照brief原文，observed如实说明实际发生及顺序。明确不满足填fail，未能判断填unknown，符合才pass。不得把摘要中的状态、以后可能发生或读者脑补算满足。禁止改写正文、代写替代台词或虚构人工批准；只返回Schema里的简明完整审计。'

SOURCE_AUDIT_RULE='回复只给Schema所列源标识及核对结果，不复写source_quote；程序会按源ID解析冻结原文，审查的status和explanation仍由你判定。同一对白内严格先后通过occurrence_spans标注实际先后子句的完整原文quote，不要求拆成两次说话；没有span默认整步，重叠子句不能冒充先后。actual_initial_conditions必须还原最早正文动作发生前的物理状态，不能用该动作完成后的状态；从容器取出说明此前在容器内，翻正说明此前朝向未正。不知道就unknown，不能复制expected。obligation_evidence的occurrence_refs只列本义务真正发生的动作或对白，support_refs另放触发、上下文、结果，不能把所有支持证据冒充施事或行事功能。你是DeepSeek来源合同审查员。只核对冻结brief与模型规划，不做文风评价。逐项核对source_obligations是否是源要求且覆盖其必要事件；initial_conditions每项物理条件和source_quote必须与来源初态一致，不把明确的朝向或位置遗漏为unspecified；source_order每条严格先后必须是来源要求，来源仅对同一个请求的不同描述不能强加成两次，允许同一句完成多个目的。源没有明确严格先后或plan多加义务必须fail，证据和必修目标来自原文；无法判断填unknown，不补齐来源。检查必须完整覆盖，不修改brief，不代写新计划，不声称创作或视频通过。'



def known_full_plan_rejection(receipt):
    metadata=receipt.get('response_metadata',{})
    failure=receipt.get('failure',{})
    known_contract_failure=(failure.get('category')=='validation' or (failure.get('category')=='state_contract' and failure.get('code')=='MODULE_SCHEMA_INVALID'))
    return (receipt.get('status')=='contract_rejected' and known_contract_failure and receipt.get('failure',{}).get('response_received') is True and isinstance(receipt.get('output'),dict) and receipt['output'].get('source_obligations') is not None and type(metadata.get('total_tokens')) is int and metadata['total_tokens']>=0 and metadata.get('response_body_complete') is True and metadata.get('finish_reason') in ('stop','tool_calls'))

def verify_files(files):
    for p,h in files.items():
        if control.sha_file(p)!=h:raise RuntimeError('source binding changed: '+str(p))

class Pipeline:
    def __init__(self,root,client_factory=None):
        self.root=Path(root).resolve();self.settings=control.read(self.root/'SETUP.json');self.client_factory=client_factory
    def prepare(self):
        if not (self.root/'ANCHOR.json').exists():
            parent=PROJECT/self.settings['parent_text_directory'];l=control.read(parent/'CALL_LEDGER.json')
            verify_files({str(PROJECT/p):h for p,h in l['source_manifest'].items()})
            if control.sha_file(parent/'AUTHORIZATION.json')!=l['authorization_sha256']:raise RuntimeError('parent authorization changed')
            snapshots={str(parent/'source_at_dispatch'/p):h for p,h in l['source_manifest'].items()};verify_files(snapshots)
            if {p.name for p in parent.glob('call_*.json') if p.name.casefold()!='call_ledger.json'}!={row['receipt'] for row in l['calls']}:raise RuntimeError('parent orphan or missing receipt')
            if len({row['receipt'] for row in l['calls']})!=len(l['calls']):raise RuntimeError('parent duplicate receipts')
            if [row['ordinal'] for row in l['calls']]!=list(range(l['starting_spend']['calls_started']+1,l['starting_spend']['calls_started']+len(l['calls'])+1)):raise RuntimeError('parent ordinal changed')
            receipts=[]
            for row in l['calls']:
                p=parent/row['receipt'];r=control.read(p)
                if control.sha_file(p)!=row['receipt_sha256'] or (r['status']!='contract_valid' and not known_full_plan_rejection(r)) or (type(r.get('response_metadata',{}).get('total_tokens')) is not int or r['response_metadata']['total_tokens']<0):raise RuntimeError('parent unresolved; reconcile original')
                receipts.append(r)
            inherited=deepcopy(l['starting_spend']);inherited.update(calls_started=inherited['calls_started']+len(receipts),reported_tokens=inherited['reported_tokens']+sum(r['response_metadata']['total_tokens'] for r in receipts),calls_with_known_usage=inherited['calls_with_known_usage']+len(receipts),parent_ledger_sha256=control.sha_file(parent/'CALL_LEDGER.json'))
            files={str(PROJECT/p):h for p,h in l['source_manifest'].items()}
            for p in [parent/'CALL_LEDGER.json',parent/'AUTHORIZATION.json',*[parent/q['receipt'] for q in l['calls']]]:files[str(p)]=control.sha_file(p)
            control.write(self.root/'ANCHOR.json',{'inherited':inherited,'models':l['model_configs'],'parent_files':files,'parent_snapshots':snapshots,'automatic_transport_retry':False,'automatic_content_revision_authorized':True,'authorization_source':'用户2026-10-11明确要求先修流程，再从新流程生成；目标后续脱离逐稿人工监管自动执行','media_authorized':False,'budget_reset':False},True)
        x=control.read(self.root/'INPUT.json')
        if self.settings.get('seed_rejected_plan_file'):
            seed=control.read(self.root/self.settings['seed_rejected_plan_file']);origin=control.read(seed['receipt_path'])
            bound=control.read(self.root/'ANCHOR.json')['parent_files'];origin_path=str(Path(seed['receipt_path']).resolve())
            if bound.get(origin_path)!=seed['receipt_sha256']:raise RuntimeError('plan seed must belong to the inherited frozen receipt lineage')
            if control.sha_file(seed['receipt_path'])!=seed['receipt_sha256'] or not known_full_plan_rejection(origin) or origin['output']!=seed['native_full_plan'] or origin['ordinal']!=seed['original_ordinal']:raise RuntimeError('original known failed plan seed changed or locally patched')
        if type(self.settings.get('max_full_drafts')) is not int or not 1<=self.settings['max_full_drafts']<=5:raise ValueError('bounded full-draft versions required')
        if not x.get('reference_fulltext') or not x['brief'].get('selected_candidate_id'):raise ValueError('confirmed brief and actual reference required')
        self.runtime().prepare();return self.summary()
    def runtime(self):
        a=control.read(self.root/'ANCHOR.json')
        own=[Path(__file__).resolve(),Path(contract.__file__).resolve(),Path(contract.prior.__file__).resolve(),Path(contract.prior.prior.__file__).resolve(),Path(contract.prior.prior.prior.__file__).resolve(),Path(contract.prior.prior.prior.prior.__file__).resolve(),Path(contract.base.__file__).resolve(),Path(control.__file__).resolve(),PROJECT/'scripts/creative_evidenced_role_clients_v1.py',PROJECT/'scripts/creative_call_evidence_v1.py',PROJECT/'src/content_factory/creative_response_contract.py',*[self.root/n for n in ['SETUP.json','INPUT.json','ANCHOR.json']]]
        if self.settings.get('regression_probe_file'):own.append(self.root/self.settings['regression_probe_file'])
        if self.settings.get('seed_rejected_plan_file'):own.append(self.root/self.settings['seed_rejected_plan_file'])
        kwargs={'inherited_guard':lambda:verify_files({**a['parent_files'],**a.get('parent_snapshots',{})}),'quota_state':None,'shared_lock':identity.SHARED_LOCK}
        if self.client_factory is not None:kwargs['client_factory']=self.client_factory
        return control.ContinuationRuntime(PROJECT,self.root,own+[Path(p) for p in a['parent_files']],a['inherited'],a['models'],**kwargs)
    def summary(self):
        s=self.runtime().summary();s['unknown_token_reservations']+=control.read(self.root/'ANCHOR.json')['inherited'].get('unknown_token_reservations',0);return s
    def state(self,status,**data):
        value={'schema':'autonomous_text_pipeline_state/v6','status':status,'updated_at':control.now(),'human_quality_approved':False,'video_calls':0,'no_manual_review_decision_needed':True,**data,'spend':self.summary()}
        control.write(self.root/'STATE.json',value);return value
    def request(self,stage,plan=None,script=None,previous=None,requirements=None,previous_plan=None,plan_failure=None):
        x=control.read(self.root/'INPUT.json');b=deepcopy(x['brief']);payload={'brief':b,'reference_fulltext':x['reference_fulltext'],'quality_criteria':contract.CRITERIA,'user_goal':x['user_goal']}
        if stage=='plan':
            role='writer';schema=contract.build_plan_schema(b);rule=PLAN_RULE;cap=6000
            if previous_plan is not None:payload.update(previous_complete_plan=deepcopy(previous_plan),plan_revision_requirement=deepcopy(plan_failure))
        elif stage=='source_audit':
            role='director';schema=contract.build_source_audit_schema(plan,b);rule=SOURCE_AUDIT_RULE;cap=4000;payload={'brief':b,'full_source_plan':deepcopy(plan)}
        elif stage=='draft':
            role='writer';schema=contract.build_script_schema(b);rule=AUTHOR_RULE;cap=5500;payload['scene_plan']=deepcopy(plan)
            if previous is not None:payload.update(previous_complete_script=deepcopy(previous),revision_requirements=deepcopy(requirements))
        elif stage=='review':
            role='director';schema=contract.build_review_schema(script,b);rule=REVIEW_RULE;cap=7500;payload.update(scene_plan=deepcopy(plan),full_current_script=deepcopy(script),evidence_catalog=contract.evidence_catalog(script))
        elif stage=='audit':
            role='director';schema=contract.build_audit_schema(script,b,plan);rule=AUDIT_RULE;cap=8000;payload={'brief':b,'full_current_script':deepcopy(script),'evidence_catalog':contract.evidence_catalog(script),'source_contract':{'source_obligations':deepcopy(plan['source_obligations']),'source_order':deepcopy(plan['source_order']),'initial_conditions':deepcopy(plan['initial_conditions'])}}
        else:raise ValueError('explicit plan/source_audit/draft/review/audit only')
        models=control.read(self.root/'ANCHOR.json')['models']
        return {'role':role,'model':models[role]['model'],'messages':[{'role':'system','content':rule},{'role':'user','content':json.dumps(payload,ensure_ascii=False,separators=(',',':'))}],'structured_schema':schema,'parameters':{'max_completion_tokens':cap,'temperature':.4,'thinking':'disabled'},'input_provenance':{'operator_version':'autonomous_text_pipeline/v6','phase':stage,'brief_sha256':control.digest(b),'reference_fulltext_in_actual_messages':stage not in ('audit','source_audit'),'reference_fulltext_sha256':control.digest(x['reference_fulltext']) if stage not in ('audit','source_audit') else None,'whole_script_sha256':control.digest(script) if script else None,'fixed_dialogue_counts':False,'locked_old_beats':False,'assistant_decision_required':False,'media_authorized':False,'human_quality_approved':False}}
    def call(self,label,request,validator):
        control.write(self.root/'request_previews'/f'{label}.json',request,True)
        return self.runtime().dispatch(label,request,validator)
    def ready(self,result,label):
        if result['status']!='contract_valid':
            self.state('halt_'+result['status'],failed_label=label,original_ordinal=result['ordinal'],failure=result.get('failure'));return False
        if type(result.get('response_metadata',{}).get('total_tokens')) is not int or result['response_metadata']['total_tokens']<0:
            self.state('halt_usage_unknown',failed_label=label,original_ordinal=result['ordinal']);return False
        return True
    def render(self,script):
        b=control.read(self.root/'INPUT.json')['brief'];names={q['id']:q.get('name',q['id']) for q in b['characters']}
        lines=['# '+script['title'],'','自动文本流程完整稿；机器文本验收完成，未宣称人工审美或视频通过。','',script['premise']]
        for beat in script['beats']:
            lines += ['','## '+beat['id']+' '+beat['event'],'','触发：'+beat['trigger']]
            for step in beat['steps']:lines += ['',(f"**{names[step['speaker']]}**：" if step['kind']=='dialogue' else '')+step['text']]
        return '\n'.join(lines)+'\n'
    def finish(self,script,plan,draft,review,audit,decision,version):
        if contract.decide_source_audit(control.read(self.root/'SOURCE_CONTRACT_AUDIT.json'),plan,control.read(self.root/'INPUT.json')['brief'])['status']!='source_contract_ready':raise ValueError('same-source plan support gate required')
        if decision['status']!='text_ready_for_director' or review['validation']['script_sha256']!=control.digest(script) or audit['validation']['script_sha256']!=control.digest(script):raise ValueError('same-source text gate required')
        if contract.combine_decisions(review['output'],audit['output'],script,control.read(self.root/'INPUT.json')['brief'],plan)!=decision:raise ValueError('decision must derive from these two complete current responses')
        out=self.root/'DELIVERABLE'
        for n,v in [('FULL_SCRIPT.json',script),('RAW_MODEL_SCRIPT.json',draft['output']),('SCENE_PLAN.json',plan),('RAW_MODEL_PLAN.json',control.read(self.root/'RAW_MODEL_PLAN.json')),('SOURCE_CONTRACT_AUDIT.json',control.read(self.root/'SOURCE_CONTRACT_AUDIT.json')),('COMPILED_SOURCE_CONTRACT_AUDIT.json',control.read(self.root/'COMPILED_SOURCE_CONTRACT_AUDIT.json')),('FULL_REVIEW.json',review['output']),('LITERAL_AUDIT.json',audit['output']),('AUTOMATIC_DECISION.json',decision)]:control.write(out/n,v,True)
        p=out/'FULL_SCRIPT.md';p.parent.mkdir(parents=True,exist_ok=True);text=self.render(script)
        if p.exists() and p.read_text(encoding='utf-8')!=text:raise RuntimeError('immutable readable body differs')
        if not p.exists():p.write_text(text,encoding='utf-8')
        handoff={'schema':'autonomous_text_handoff/v6','status':'text_ready_for_director','script_sha256':control.digest(script),'raw_creative_sha256':control.digest(draft['output']),'draft_ordinal':draft['ordinal'],'review_ordinal':review['ordinal'],'audit_ordinal':audit['ordinal'],'both_same_source_checks_required':True,'source_contract_checked_against_frozen_brief':True,'source_quotes_resolved_from_frozen_ids':True,'native_creative_plan_fields_unchanged':True,'full_draft_versions':version,'manual_assistant_gate_calls':0,'human_text_adoption_required_by_this_pipeline':False,'human_quality_approved':False,'creative_quality_proven':False,'new_director_and_performance_built':False,'prior_director_and_video_not_current':True,'media_calls':0,'reference_fulltext_in_actual_messages':True,'no_local_creative_patch':True,'spend':self.summary()}
        control.write(out/'HANDOFF.json',handoff,True);return self.state('text_ready_for_director',candidate_path=str(p),script_sha256=control.digest(script),full_draft_versions=version,handoff=str(out/'HANDOFF.json'))
    def regression_probe(self,plan):
        name=self.settings.get('regression_probe_file')
        if not name:return True
        fixture=control.read(self.root/name);brief=deepcopy(control.read(self.root/'INPUT.json')['brief']);script=deepcopy(fixture['full_script'])
        raw={key:deepcopy(value) for key,value in script.items() if key!='selected_candidate_id'}
        if contract.compile_script(raw,brief)!=script:raise ValueError('regression fixture source identity differs from current brief')
        request=self.request('audit',script=script,plan=plan)
        result=self.call('literal_gate_regression_probe',request,lambda v:contract.validate_audit(v,script,brief,plan))
        if not self.ready(result,'literal_gate_regression_probe'):return False
        decision=contract.decide_audit(result['output'],script,brief,plan)
        found={row['code'] for row in decision['revision_requirements']};expected=set(fixture['expected_fail_codes'])
        groups=fixture.get('expected_defect_groups',{})
        group_detected={name:any(code.startswith(prefix) for code in found for prefix in prefixes) for name,prefixes in groups.items()}
        detected=decision['status']=='needs_whole_revision' and expected.issubset(found) and all(group_detected.values())
        control.write(self.root/'REGRESSION_PROBE.json',{'schema':'autonomous_literal_gate_regression/v1','status':'detected_known_failures' if detected else 'gate_regression_failed','ordinal':result['ordinal'],'same_script_sha256':control.digest(script),'expected_fail_codes':sorted(expected),'actual_fail_codes':sorted(found),'expected_defect_groups':groups,'detected_groups':group_detected,'expectations_sent_to_model':False,'primary_old_review_sent_to_model':False,'source_identity':fixture['source_identity'],'decision':decision,'semantic_quality_approved':False},True)
        if not detected:self.state('halt_gate_regression_failed',decision=decision,failed_label='literal_gate_regression_probe')
        return detected
    def run(self):
        self.prepare();x=control.read(self.root/'INPUT.json');brief=deepcopy(x['brief'])
        previous_plan=None;plan_failure=None
        if self.settings.get('seed_rejected_plan_file'):
            seed=control.read(self.root/self.settings['seed_rejected_plan_file']);previous_plan=deepcopy(seed['native_full_plan']);plan_failure=deepcopy(seed['revision_requirement'])
        plan_cap=2 if self.settings.get('seed_rejected_plan_file') else 3
        max_plans=self.settings.get('max_full_plans',plan_cap)
        if type(max_plans) is not int or not 1<=max_plans<=plan_cap:raise ValueError('bounded plan versions required')
        for plan_version in range(1,max_plans+1):
            label=f'scene_plan_{plan_version:02}';req=self.request('plan',previous_plan=previous_plan,plan_failure=plan_failure)
            result=self.call(label,req,lambda v:contract.validate_plan(v,brief))
            if result['status']=='contract_valid':
                if not self.ready(result,label):return control.read(self.root/'STATE.json')
                candidate_plan=contract.compile_plan(result['output'],brief)
                control.write(self.root/'plan_versions'/f'{plan_version:02}'/'RAW_MODEL_PLAN.json',result['output'],True)
                control.write(self.root/'plan_versions'/f'{plan_version:02}'/'COMPILED_PLAN.json',candidate_plan,True)
                audit_label=f'source_contract_audit_{plan_version:02}'
                source_audit=self.call(audit_label,self.request('source_audit',plan=candidate_plan),lambda v:contract.validate_source_audit(v,candidate_plan,brief))
                if not self.ready(source_audit,audit_label):return control.read(self.root/'STATE.json')
                compiled_source_audit=contract.compile_source_audit(source_audit['output'],candidate_plan,brief)
                control.write(self.root/'plan_versions'/f'{plan_version:02}'/'RAW_SOURCE_AUDIT.json',source_audit['output'],True)
                control.write(self.root/'plan_versions'/f'{plan_version:02}'/'COMPILED_SOURCE_AUDIT.json',compiled_source_audit,True)
                source_decision=contract.decide_source_audit(source_audit['output'],candidate_plan,brief)
                control.write(self.root/'plan_versions'/f'{plan_version:02}'/'SOURCE_DECISION.json',source_decision,True)
                if source_decision['status']=='source_contract_ready':
                    plan=candidate_plan;control.write(self.root/'RAW_MODEL_PLAN.json',result['output'],True);control.write(self.root/'SCENE_PLAN.json',plan,True);control.write(self.root/'SOURCE_CONTRACT_AUDIT.json',source_audit['output'],True);control.write(self.root/'COMPILED_SOURCE_CONTRACT_AUDIT.json',compiled_source_audit,True);break
                if source_decision['status']=='halt_source_uncertain':return self.state('halt_source_uncertain',full_plan_versions=plan_version,decision=source_decision)
                if source_decision['status']!='needs_whole_plan_revision':raise ValueError('source decision transition unknown')
                previous_plan=deepcopy(result['output']);plan_failure=source_decision
                if plan_version==max_plans:return self.state('plan_stalled',full_plan_versions=plan_version,original_ordinal=result['ordinal'],decision=source_decision)
                self.state('automatic_full_plan_revision',full_plan_versions=plan_version,original_ordinal=result['ordinal'],decision=source_decision)
                continue
            if not known_full_plan_rejection(result):
                self.ready(result,label);return control.read(self.root/'STATE.json')
            if plan_version==max_plans:return self.state('plan_stalled',full_plan_versions=plan_version,original_ordinal=result['ordinal'],failure=result['failure'])
            self.state('automatic_full_plan_revision',full_plan_versions=plan_version,original_ordinal=result['ordinal'],failure=result['failure'])
            previous_plan=deepcopy(result['output']);plan_failure={'problem':result['failure']['code'],'required_revision':'只修本次完整计划的合同及源解析，保持brief与初态冻结，提交全部字段；不得本地补丁、固定旧计划拍数或重发相同请求。'}
        else:raise RuntimeError('plan limit unreachable')
        if not self.regression_probe(plan):return control.read(self.root/'STATE.json')
        previous=None;requirements=None;fingerprints=[]
        for version in range(1,self.settings['max_full_drafts']+1):
            label=f'whole_draft_{version:02}';req=self.request('draft',plan=plan,previous=previous,requirements=requirements)
            def validate_draft(value):
                s=contract.compile_script(value,brief);return {'complete_native_script':True,'script_sha256':control.digest(s),'creative_text_changed_locally':False,'human_quality_approved':False}
            draft=self.call(label,req,validate_draft)
            if not self.ready(draft,label):return control.read(self.root/'STATE.json')
            script=contract.compile_script(draft['output'],brief);control.write(self.root/'versions'/f'{version:02}'/'FULL_SCRIPT.json',script,True)
            review_label=f'whole_review_{version:02}';req=self.request('review',plan=plan,script=script)
            captured_script=deepcopy(script);captured_brief=deepcopy(brief)
            review=self.call(review_label,req,lambda v:contract.validate_review(v,captured_script,captured_brief))
            if not self.ready(review,review_label):return control.read(self.root/'STATE.json')
            primary=contract.decide_review(review['output'],script,brief)
            if primary['status']=='halt_review_uncertain':return self.state('halt_review_uncertain',full_draft_versions=version,decision=primary)
            audit_label=f'literal_audit_{version:02}';req=self.request('audit',script=script,plan=plan)
            audit=self.call(audit_label,req,lambda v:contract.validate_audit(v,captured_script,captured_brief,plan))
            if not self.ready(audit,audit_label):return control.read(self.root/'STATE.json')
            decision=contract.combine_decisions(review['output'],audit['output'],script,brief,plan);control.write(self.root/'versions'/f'{version:02}'/'AUTOMATIC_DECISION.json',decision,True)
            if decision['status']=='text_ready_for_director':return self.finish(script,plan,draft,review,audit,decision,version)
            if decision['status']=='halt_review_uncertain':return self.state('halt_review_uncertain',full_draft_versions=version,decision=decision)
            if decision['status']!='needs_whole_revision':raise ValueError('unexpected transition')
            requirements=decision['revision_requirements'];fingerprint=tuple(sorted((q['code'],q['problem'],q['required_revision']) for q in requirements));fingerprints.append(fingerprint)
            if version==self.settings['max_full_drafts'] or (len(fingerprints)>=2 and fingerprints[-1]==fingerprints[-2]):return self.state('creative_stalled',full_draft_versions=version,decision=decision,reason='content revision limit or identical unresolved defects')
            self.state('automatic_whole_revision',full_draft_versions=version,decision=decision)
            previous=deepcopy(script)
        raise RuntimeError('unreachable')

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');ap=argparse.ArgumentParser();ap.add_argument('run_dir');ap.add_argument('stage',choices=['prepare','run','status']);a=ap.parse_args();op=Pipeline(a.run_dir)
    print(json.dumps(op.prepare() if a.stage=='prepare' else op.summary() if a.stage=='status' else op.run(),ensure_ascii=False),flush=True)
