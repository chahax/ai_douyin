"""Reusable unattended text pipeline: scene plan -> whole script -> review -> bounded revisions.
No assistant decision files, no transport retries, no media calls or fake human approval.
"""
from pathlib import Path
from copy import deepcopy
import argparse,json,sys
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_creative_resume_v10 as identity
from src.content_factory import creative_autonomous_text_contract_v1 as contract

PLAN_RULE='你是MiniMax编剧。先规划这场戏的行动因果，不写完整对白。唯一剧情依据是brief；reference_fulltext仅借表达机制。明确每个人想改变谁的什么决定，阻力怎样让其改变策略，观众在哪个可见刺激后感受变化。结尾是本场尝试的可见结果，允许更大的争议未解决；不要求角色口头总结，不加未批准的后续承诺或新事实。beat数量由事件决定，禁止用固定四拍/固定对白句数作为审美标准。按照Schema提交简明完整计划，不写长篇分析。'
AUTHOR_RULE='你是MiniMax影视编剧。依据唯一brief、场景行动计划及参考机制完整创作title/premise/beats正文。全部对白与动作由你提交，不返回补丁或片段、不要求旧拍逐字不变。事实与人物身份稳定，话轮/拍数/动作可为表达重组。对白是对眼前听者采取行动：明确谁希望谁做什么，后一句回应上一刺激，阻力改变策略，不反复换句复述同一要求。口语先可直接听懂，不堆作者主题总结、概念对举或金句；正常职业口吻可用。表情随刺激与选择产生，允许说话和必要动作同时，不写逐秒肌肉清单。结尾让前面的选择在可见行动中兑现，不强制解释性收场台词或机械告别；保留更大问题未解，不能新增公司/他人承诺。reference_fulltext借行动目的、刺激反应、画面信息和余味机制，不抄其剧情。若提供完整前稿和revision_requirements，逐项解决但可重组整篇，仍完整提交新版。正文只写观众能看见/听见的事件；premise/event/trigger不能补未演出的事实。'
REVIEW_RULE='你是DeepSeek独立全文审查。完整读取正文每句、计划和brief，逐项评估六项功能标准并还原每条对白的施事/行为/对象与接话功能。关键句须直接听懂：核心请求若存在相反施事解读，clarity必须ambiguous/unknown，不能说语境可猜而只放建议。不要凭单词禁令判错，普通职业口吻不自动等于stilted，礼貌确认不自动等于冗余。判断具体上下文中有无实际新信息/策略/反应。结尾不要求口头宣布谈话结束或解释没签成，只检查目标受阻后人物的选择和可见结果是否接住交锋；动作可以完成结尾。不得把premise/event/trigger算作观众可见证据。六项标准与全部对白必须覆盖，证据仅evidence_catalog的正文steps。事实/道具/人物顺序全部核对，不新增法律事实作裁判。fail必须举当前证据和可执行修改目标，unknown如实保留，不能以issues为空或总体反馈已解决覆盖逐项问题。不代写替代正文，不强迫漂亮台词，不声称视频质量或人工批准。每项理由简短，避免重复长分析，按Schema完整提交。'


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
            receipts=[]
            for row in l['calls']:
                p=parent/row['receipt'];r=control.read(p)
                if control.sha_file(p)!=row['receipt_sha256'] or r['status']!='contract_valid' or type(r.get('response_metadata',{}).get('total_tokens')) is not int:raise RuntimeError('parent unresolved; reconcile original')
                receipts.append(r)
            inherited=deepcopy(l['starting_spend']);inherited.update(calls_started=inherited['calls_started']+len(receipts),reported_tokens=inherited['reported_tokens']+sum(r['response_metadata']['total_tokens'] for r in receipts),calls_with_known_usage=inherited['calls_with_known_usage']+len(receipts),parent_ledger_sha256=control.sha_file(parent/'CALL_LEDGER.json'))
            files={str(PROJECT/p):h for p,h in l['source_manifest'].items()}
            for p in [parent/'CALL_LEDGER.json',*[parent/q['receipt'] for q in l['calls']]]:files[str(p)]=control.sha_file(p)
            control.write(self.root/'ANCHOR.json',{'inherited':inherited,'models':l['model_configs'],'parent_files':files,'automatic_transport_retry':False,'automatic_content_revision_authorized':True,'authorization_source':'用户2026-10-11明确要求先修流程，再从新流程生成；目标后续脱离逐稿人工监管自动执行','media_authorized':False,'budget_reset':False},True)
        x=control.read(self.root/'INPUT.json')
        if type(self.settings.get('max_full_drafts')) is not int or not 1<=self.settings['max_full_drafts']<=5:raise ValueError('bounded full-draft versions required')
        if not x.get('reference_fulltext') or not x['brief'].get('selected_candidate_id'):raise ValueError('confirmed brief and actual reference required')
        self.runtime().prepare();return self.summary()
    def runtime(self):
        a=control.read(self.root/'ANCHOR.json')
        own=[Path(__file__).resolve(),Path(contract.__file__).resolve(),Path(control.__file__).resolve(),PROJECT/'scripts/creative_evidenced_role_clients_v1.py',PROJECT/'scripts/creative_call_evidence_v1.py',PROJECT/'src/content_factory/creative_response_contract.py',*[self.root/n for n in ['SETUP.json','INPUT.json','ANCHOR.json']]]
        kwargs={'inherited_guard':lambda:verify_files(a['parent_files']),'quota_state':None,'shared_lock':identity.SHARED_LOCK}
        if self.client_factory is not None:kwargs['client_factory']=self.client_factory
        return control.ContinuationRuntime(PROJECT,self.root,own+[Path(p) for p in a['parent_files']],a['inherited'],a['models'],**kwargs)
    def summary(self):
        s=self.runtime().summary();s['unknown_token_reservations']+=control.read(self.root/'ANCHOR.json')['inherited'].get('unknown_token_reservations',0);return s
    def state(self,status,**data):
        value={'schema':'autonomous_text_pipeline_state/v1','status':status,'updated_at':control.now(),'human_quality_approved':False,'video_calls':0,'no_manual_review_decision_needed':True,**data,'spend':self.summary()}
        control.write(self.root/'STATE.json',value);return value
    def request(self,stage,plan=None,script=None,previous=None,requirements=None):
        x=control.read(self.root/'INPUT.json');b=deepcopy(x['brief']);payload={'brief':b,'reference_fulltext':x['reference_fulltext'],'quality_criteria':contract.CRITERIA,'user_goal':x['user_goal']}
        if stage=='plan':role='writer';schema=contract.build_plan_schema(b);rule=PLAN_RULE;cap=3200
        elif stage=='draft':
            role='writer';schema=contract.build_script_schema(b);rule=AUTHOR_RULE;cap=5500;payload['scene_plan']=deepcopy(plan)
            if previous is not None:payload.update(previous_complete_script=deepcopy(previous),revision_requirements=deepcopy(requirements))
        elif stage=='review':
            role='director';schema=contract.build_review_schema(script,b);rule=REVIEW_RULE;cap=6500;payload.update(scene_plan=deepcopy(plan),full_current_script=deepcopy(script),evidence_catalog=contract.evidence_catalog(script))
        else:raise ValueError('explicit plan/draft/review only')
        models=control.read(self.root/'ANCHOR.json')['models']
        return {'role':role,'model':models[role]['model'],'messages':[{'role':'system','content':rule},{'role':'user','content':json.dumps(payload,ensure_ascii=False,separators=(',',':'))}],'structured_schema':schema,'parameters':{'max_completion_tokens':cap,'temperature':.4,'thinking':'disabled'},'input_provenance':{'operator_version':'autonomous_text_pipeline/v1','phase':stage,'brief_sha256':control.digest(b),'reference_fulltext_in_actual_messages':True,'reference_fulltext_sha256':control.digest(x['reference_fulltext']),'whole_script_sha256':control.digest(script) if script else None,'fixed_dialogue_counts':False,'locked_old_beats':False,'assistant_decision_required':False,'media_authorized':False,'human_quality_approved':False}}
    def call(self,label,request,validator):
        control.write(self.root/'request_previews'/f'{label}.json',request,True)
        return self.runtime().dispatch(label,request,validator)
    def ready(self,result,label):
        if result['status']!='contract_valid':
            self.state('halt_'+result['status'],failed_label=label,original_ordinal=result['ordinal'],failure=result.get('failure'));return False
        if type(result.get('response_metadata',{}).get('total_tokens')) is not int:
            self.state('halt_usage_unknown',failed_label=label,original_ordinal=result['ordinal']);return False
        return True
    def render(self,script):
        b=control.read(self.root/'INPUT.json')['brief'];names={q['id']:q.get('name',q['id']) for q in b['characters']}
        lines=['# '+script['title'],'','自动文本流程完整稿；机器文本验收完成，未宣称人工审美或视频通过。','',script['premise']]
        for beat in script['beats']:
            lines += ['','## '+beat['id']+' '+beat['event'],'','触发：'+beat['trigger']]
            for step in beat['steps']:lines += ['',(f"**{names[step['speaker']]}**：" if step['kind']=='dialogue' else '')+step['text']]
        return '\n'.join(lines)+'\n'
    def finish(self,script,plan,draft,review,decision,version):
        if decision['status']!='text_ready_for_director' or review['validation']['script_sha256']!=control.digest(script):raise ValueError('same-source text gate required')
        out=self.root/'DELIVERABLE'
        for n,v in [('FULL_SCRIPT.json',script),('RAW_MODEL_SCRIPT.json',draft['output']),('SCENE_PLAN.json',plan),('FULL_REVIEW.json',review['output']),('AUTOMATIC_DECISION.json',decision)]:control.write(out/n,v,True)
        p=out/'FULL_SCRIPT.md';p.parent.mkdir(parents=True,exist_ok=True);text=self.render(script)
        if p.exists() and p.read_text(encoding='utf-8')!=text:raise RuntimeError('immutable readable body differs')
        if not p.exists():p.write_text(text,encoding='utf-8')
        handoff={'schema':'autonomous_text_handoff/v1','status':'text_ready_for_director','script_sha256':control.digest(script),'raw_creative_sha256':control.digest(draft['output']),'draft_ordinal':draft['ordinal'],'review_ordinal':review['ordinal'],'full_draft_versions':version,'manual_assistant_gate_calls':0,'human_text_adoption_required_by_this_pipeline':False,'human_quality_approved':False,'creative_quality_proven':False,'new_director_and_performance_built':False,'prior_director_and_video_not_current':True,'media_calls':0,'reference_fulltext_in_actual_messages':True,'no_local_creative_patch':True,'spend':self.summary()}
        control.write(out/'HANDOFF.json',handoff,True);return self.state('text_ready_for_director',candidate_path=str(p),script_sha256=control.digest(script),full_draft_versions=version,handoff=str(out/'HANDOFF.json'))
    def run(self):
        self.prepare();x=control.read(self.root/'INPUT.json');brief=deepcopy(x['brief'])
        req=self.request('plan');result=self.call('scene_plan',req,lambda v:contract.validate_plan(v,brief))
        if not self.ready(result,'scene_plan'):return control.read(self.root/'STATE.json')
        plan=deepcopy(result['output']);control.write(self.root/'SCENE_PLAN.json',plan,True)
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
            decision=contract.decide_review(review['output'],script,brief);control.write(self.root/'versions'/f'{version:02}'/'AUTOMATIC_DECISION.json',decision,True)
            if decision['status']=='text_ready_for_director':return self.finish(script,plan,draft,review,decision,version)
            if decision['status']=='halt_review_uncertain':return self.state('halt_review_uncertain',full_draft_versions=version,decision=decision)
            if decision['status']!='needs_whole_revision':raise ValueError('unexpected transition')
            requirements=decision['revision_requirements'];fingerprint=tuple(sorted(q['code'] for q in requirements));fingerprints.append(fingerprint)
            if version==self.settings['max_full_drafts'] or (len(fingerprints)>=2 and fingerprints[-1]==fingerprints[-2]):return self.state('creative_stalled',full_draft_versions=version,decision=decision,reason='content revision limit or identical unresolved defects')
            self.state('automatic_whole_revision',full_draft_versions=version,decision=decision)
            previous=deepcopy(script)
        raise RuntimeError('unreachable')

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');ap=argparse.ArgumentParser();ap.add_argument('run_dir');ap.add_argument('stage',choices=['prepare','run','status']);a=ap.parse_args();op=Pipeline(a.run_dir)
    print(json.dumps(op.prepare() if a.stage=='prepare' else op.summary() if a.stage=='status' else op.run(),ensure_ascii=False),flush=True)
