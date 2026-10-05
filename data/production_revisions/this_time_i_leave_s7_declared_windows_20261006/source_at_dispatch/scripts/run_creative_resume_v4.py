"""Resume the existing story through explicit new contracts; no media dispatch."""
from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path
import re
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import run_modular_bd_probe as legacy
from scripts import creative_linear_script_v3 as linear
from scripts import step_index_physical_adapter_v5 as physical
from scripts import creative_compact_review_transport_v8 as compact
from scripts import creative_resume_dispatch_v2 as control
from scripts.creative_script_review_sources_v7 import validate_review_v7
from scripts import run_creative_resume_v3 as previous_run
from scripts import creative_joint_source_binding_v10 as joint_binding
from scripts import creative_story_direction_contract_v1 as story_direction
from scripts import creative_review_wire_v10 as review_wire
from scripts import creative_component_registry_v1 as component_registry
from scripts import creative_json_document_transport_v1 as document_transport
from scripts.creative_deepseek_tool_client_v1 import CreativeDeepSeekToolClients
from src.content_factory.creative_review_v6 import build_review_prompt
from src.content_factory.creative_workflow_contract import CreativeContractError

PROJECT=Path(__file__).resolve().parents[1]
ROOT=legacy.ROOT/'resume_20261005_v4'
VERSION='story_first_modular_production_continuation/v4'
SOURCE_NAMES=['scripts/run_creative_resume_v4.py','scripts/creative_linear_script_v3.py',
    'scripts/creative_component_registry_v1.py','scripts/creative_surface_state_v1.py',
    'scripts/creative_surface_state_bridge_v1.py','scripts/creative_surface_action_core_v1.py',
    'scripts/creative_surface_action_v1.py','scripts/step_index_physical_adapter_v5.py',
    'scripts/creative_joint_source_binding_v10.py','scripts/creative_review_wire_v10.py']+previous_run.SOURCE_NAMES
ISSUES=[
 {'id':'VERIFIED_PEN_HOLDER','location':'B1/B8','evidence':'原48 B1把签字笔搁在表上，B8称为林屿手里的笔，中间没有恢复持有的实际步骤。','request':'提交完整新稿，明确笔的初态、每次变更和使用前提；不要由导演或局部表演补动作掩盖正文缺口。'},
 {'id':'VERIFIED_PAPER_ENDPOINT','location':'B1/B2/B14','evidence':'原48递到方澄手边未明确落点或接下，方澄之后回到另一工位，结尾又从她手边挪回同一叠纸。','request':'完整新稿明确实际纸堆的落点与持有变化，取回的因果和空间须由正文成立，不用额外无作用操作凑连续。'},
 {'id':'VERIFIED_CONCURRENCY','location':'B1','evidence':'原48先播放对白，之后action却写林屿说着，原steps先后与实际同时含义不一致。','request':'完整新稿中的原steps须如实先后；不要在action重演说话或把真正同时关系偷改成说后。对白中的嘴部呼吸情绪留导演对白表演，关键道具操作须正文明确可表达的先后。'},
 {'id':'NARRATIVE_GRANULARITY','location':'whole','evidence':'此前14拍中有多个单一摸包、桌面观察、放包等微操作；拍不是固定生成段。','request':'按完整事件与观众情绪推进组织自然叙事单元，必要观察对象可由导演多镜表达；时长浮动，不限定拍数，不删必要因果或为接口增加操作。'}]


def original():return legacy.read(legacy.ROOT/'ORIGINAL_CONTEXT.json')

def prior_state():
    parent=previous_run.runtime();led=control.read(parent.ledger);parent.check(led)
    summary=parent.summary()
    if summary['unknown_token_reservations']:raise RuntimeError('parent usage unknown')
    for c in led['calls']:
        r=control.read(parent.root/c['receipt'])
        if r['status'] not in ('contract_valid','contract_rejected','interface_rejected'):raise RuntimeError('parent outcome unresolved')
        if r['status']=='interface_rejected' and r.get('failure',{}).get('response_received')is not True:raise RuntimeError('parent rejected outcome unknown')
    if summary['effective_calls_started']!=62 or summary['effective_reported_tokens']!=620826:raise RuntimeError('parent continuation changed; explicitly rebind')
    files=[parent.ledger,parent.root/'AUTHORIZATION.json',parent.root/'RESULT.json',parent.root/'STORY_PLAN_DECISION_call60.json',parent.root/'REQUEST_REFERENCE_AND_SEMANTIC_VERIFICATION_call60.json']+[parent.root/c['receipt'] for c in led['calls']]
    return {'calls_started':62,'reported_tokens':620826,'legacy_max_total_tokens':500000,
        'historical_legacy_calls':49,'historical_legacy_reported_tokens':490913,
        'original_parent_run':previous_run.prior_state()['original_parent_run'],
        'prior_evidence_sha256':{str(p.resolve()):control.sha_file(p) for p in files},
        'prior_aggregate_limit':None,'operator_extension':'script without model timing; separately declared preliminary budget; explicit original prop members plus same-surface slide; exact full joint binding',
        'last_rejection':{'ordinal':62,'code':'DIALOGUE_BUDGET_TOO_SHORT','known_usage':10722,'response_not_retried':True}}


def runtime():
    inherited=prior_state()
    def guard():
        parent=previous_run.runtime();parent.check(control.read(parent.ledger))
        for path,h in inherited['prior_evidence_sha256'].items():
            if control.sha_file(path)!=h:raise RuntimeError('prior frozen evidence changed')
    sources=[PROJECT/p for p in SOURCE_NAMES]+[PROJECT/p for p in legacy.source_manifest()]
    return control.ContinuationRuntime(PROJECT,ROOT,list(dict.fromkeys(sources)),inherited,legacy.model_configs(),
        inherited_guard=guard,client_factory=CreativeDeepSeekToolClients,quota_state=None,
        shared_lock=legacy.previous.definition.DIAGNOSTIC/'DISPATCH.lock')


def wire(role,messages,schema,cap,provenance):
    c=legacy.role_config(role)
    value={'role':role,'model':c.model,'messages':deepcopy(messages),'structured_schema':deepcopy(schema),
        'parameters':{'max_completion_tokens':cap,'temperature':.4,'thinking':'disabled'},
        'input_provenance':deepcopy(provenance),'operator_version':VERSION}
    if role=='writer':
        value.update(messages=document_transport.build_messages(messages,schema),
                     structured_schema=document_transport.build_envelope_schema(),
                     inner_document_schema=deepcopy(schema),output_transport=document_transport.VERSION)
    return value


def stage_record_view(receipt):
    # This is an in-memory view only. The on-disk output remains the exact tool envelope.
    value=deepcopy(receipt)
    if value['status']=='contract_valid' and value['request'].get('output_transport')==document_transport.VERSION:
        decoded=document_transport.extract_original_inner(value['response_text'],value['request']['inner_document_schema'])
        if decoded['document']!=value['document_output']:raise RuntimeError('derived document binding changed')
        value['wire_output']=deepcopy(value['output'])
        value['output']=deepcopy(decoded['document'])
    return value


def records():
    r=runtime();r.check(control.read(r.ledger))
    return previous_run.records()+[stage_record_view(control.read(ROOT/c['receipt'])) for c in control.read(r.ledger)['calls']]


def latest(prefix):
    matches=[r for r in records() if r['label'].startswith(prefix)]
    if not matches:raise RuntimeError('stage missing: '+prefix)
    r=max(matches,key=lambda r:r['ordinal'])
    if r['status']!='contract_valid':raise RuntimeError('latest stage rejected; no fallback: '+r['label'])
    return r


def ensure_latest_draft(n):
    nums=[int(m.group(1)) for r in records() if (m:=re.fullmatch(r'draft_s(\d+)',r['label']))]
    if not nums or max(nums)!=n:raise RuntimeError('draft superseded or missing')
    return latest(f'draft_s{n}')


def derive(raw):
    c=original();names=[x['name'] for x in c['static_visual_manifest']['characters']]
    # Source shape, identity and playback order only. Legacy validate_script
    # judges physical time against provisional placeholders and cannot run here.
    # Narrative semantics remain unapproved until the complete source review.
    return linear.accept_linear_script(c['script'],raw,character_names=names)


def previous_draft_for_revision(n):
    if type(n)is not int or n<1:raise RuntimeError('positive draft version required')
    drafts=[r for r in records() if re.fullmatch(r'draft_s(\d+)',r['label'])]
    nums=[int(r['label'].split('_s')[1]) for r in drafts]
    if nums and max(nums) not in (n-1,n):raise RuntimeError('draft version superseded or sequence skipped')
    if n==1:return deepcopy(legacy.get_call('linear_draft_v5')['output'])
    matches=[r for r in drafts if r['label']==f'draft_s{n-1}']
    if not matches:raise RuntimeError('previous draft receipt missing')
    r=max(matches,key=lambda x:x['ordinal'])
    if r['status'] not in ('contract_valid','contract_rejected','interface_rejected'):raise RuntimeError('previous draft outcome unknown')
    if r['status']=='interface_rejected' and r.get('failure',{}).get('response_received')is not True:raise RuntimeError('previous draft response unknown')
    if isinstance(r.get('output'),dict):return deepcopy(r['output'])
    return {'rejected_response_text':r.get('response_text'),'failure':deepcopy(r.get('failure',{})),
            'source_status':'unadopted failed response; generate a complete replacement'}


def story_plan(revision=1,feedback=None):
    ctx=original();diagnostic=control.read(legacy.ROOT/'resume_20261004_v1'/'SOURCE_DIAGNOSTIC_call51.json')
    feedback=feedback or {'verified_source_faults':diagnostic['verified_findings'],
        'instruction':'先整片目标、顾虑、选择、具体后果和关系改变。旧稿微操作多且状态不稳；可舍弃无叙事作用物件/操作，静态清单不表示全部必须出场。不要把失败动作链继续加补丁。'}
    messages=story_direction.build_messages(ctx,feedback)
    w=wire('writer',messages,story_direction.build_schema(ctx),4096,
        {'stage':'whole_story_direction_before_detailed_steps','reference_pack_sha256':control.digest(ctx['reference_pack']),
         'full_reference_pack_in_messages':True,'old_failed_full_script_used_as_template':False})
    def validate(raw):
        result=story_direction.validate(raw,ctx)
        return {'whole_story_direction_schema_valid':True,'semantic_approval':False,'detail_steps_generated':False,
                'local_validation':result}
    return runtime().dispatch(f'story_plan_r{revision}',w,validate)


def story_plan_decision(evidence):
    r=latest('story_plan_r');ctx=deepcopy(r['output'])
    evidence=verify_assistant_evidence(ctx,evidence)
    value={'schema':'story_direction_decision/v1','plan_sha256':control.digest(ctx),
           'approved_for_complete_script':True,'assistant_source_verification':evidence,'media_approval':False}
    control.write(ROOT/f"STORY_PLAN_DECISION_call{r['ordinal']}.json",value,True);return value


def adopted_story_plan():
    r=latest('story_plan_r')
    decision=ROOT/f"STORY_PLAN_DECISION_call{r['ordinal']}.json"
    if not decision.exists():
        if r['ordinal']!=60 or r['label']!='story_plan_r8':
            raise RuntimeError('only frozen parent call60 story_plan_r8 may be inherited')
        decision=previous_run.ROOT/'STORY_PLAN_DECISION_call60.json'
    d=control.read(decision)
    if not d['approved_for_complete_script'] or d['plan_sha256']!=control.digest(r['output']):raise RuntimeError('story direction not adopted or stale')
    return r


def draft(n,feedback=None):
    # Previous receipts are retained and sequence checked, but their failed
    # micro-operation chain is not sent as the creative template.
    previous_draft_for_revision(n)
    c=original();c.pop('script');plan=adopted_story_plan()
    c['adopted_story_direction']=deepcopy(plan['output'])
    issues={'feedback':feedback,'request':'按已确认整片方向生成完整新剧本，不拼接旧稿或补丁。每拍是事件与选择的自然叙事单元，不为拿放道具单独建拍；只写对信息、因果、情绪或画面观察有用的操作。时长与拍数随故事，不把资产清单每件都塞进来。'}
    messages=linear.build_linear_script_messages(c,{},issues)
    messages[0]['content']=messages[0]['content'].replace('参考全文与完整旧稿都在输入中，只学习表达机制。结合问题重新创作完整新稿，不把失效旧稿转换格式后当新交付。',
        '参考全文及已确认整片方向在输入，只借参考表达机制。旧失败微操作链没有作为模板，按方向独立提交完整新稿。')
    w=wire('writer',messages,linear.build_linear_script_schema(original()),6500,
        {'story_plan_sha256':control.digest(plan['output']),'story_plan_ordinal':plan['ordinal'],
         'reference_pack_sha256':control.digest(c['reference_pack']),'full_reference_pack_in_messages':True,
         'complete_new_script_required':True,'old_failed_full_script_used_as_template':False})
    def validate(raw):
        value=derive(raw)
        return {'complete_model_authored_new_script':True,'derived_sha256':control.digest(value),
                'beats':len(value['beats']),'total_seconds':value['duration_seconds'],'semantic_approval':False}
    return runtime().dispatch(f'draft_s{n}',w,validate)


def script_context(n):
    source=ensure_latest_draft(n);plan=adopted_story_plan()
    if source['request'].get('input_provenance',{}).get('story_plan_sha256')!=control.digest(plan['output']):raise RuntimeError('script not bound to current adopted story direction')
    ctx=original();ctx['adopted_story_direction']=deepcopy(plan['output']);ctx['script']=derive(source['output'])
    ctx['script'].pop('screenplay_markdown')
    ctx['script_revision_source']={'ordinal':source['ordinal'],'raw_sha256':control.digest(source['output']),
                                   'complete_model_authored':True,'operator':source['request']['operator_version'],'protocol':linear.VERSION}
    ctx['script_timing_status']='preliminary_budget_not_actual'
    ctx['script_preliminary_timing']=linear.preliminary_timing_estimates(source['output'])
    return ctx


def script_review(n,revision=1,feedback=None):
    ctx=script_context(n);messages=review_wire.script_messages(ctx)
    if feedback:messages.append({'role':'user','content':json.dumps({'previous_protocol_fault':feedback,
        'request':'重新提交完整全文审查，全部结论独立核对，不只修一行或沿用截断半稿。'},ensure_ascii=False)})
    w=wire('director',messages,review_wire.schema(ctx),20000,{'review_context_sha256':compact.context_digest(ctx),
        'script_sha256':control.digest(ensure_latest_draft(n)['output']),
        'reference_pack_sha256':control.digest(ctx['reference_pack']),'full_reference_pack_in_messages':True})
    def validate(raw):
        review=review_wire.validate_script_review(raw,ctx)
        return {'complete_review_evidence_valid':True,'story_preserved':review['story_preserved'],
                'issue_count':len(review['issues']),'semantic_approval':False,'review_context_sha256':compact.context_digest(ctx)}
    return runtime().dispatch(f'script_review_s{n}_r{revision}',w,validate)


def effective_script_review(n):
    ctx=script_context(n);r=latest(f'script_review_s{n}_r')
    return ctx,r,review_wire.validate_script_review(r['output'],ctx)


def verify_assistant_evidence(ctx,evidence):
    if not isinstance(evidence,list) or not evidence:raise RuntimeError('assistant explicit text evidence verification required')
    for ref in evidence:
        if not isinstance(ref,dict) or set(ref)!={'path','quote','finding'} or any(not isinstance(ref[k],str) or not ref[k].strip() for k in ref):
            raise RuntimeError('assistant evidence requires nonempty path, quote and finding')
        try:
            value=ctx
            for key in ref['path'].split('.'):
                value=value[int(key)] if isinstance(value,list) else value[key]
        except (KeyError,IndexError,TypeError,ValueError):raise RuntimeError('assistant evidence path absent')
        if isinstance(value,bool) or not isinstance(value,(str,int,float)) or ref['quote'] not in str(value):raise RuntimeError('assistant evidence must quote an actual leaf')
    return deepcopy(evidence)


def decision_path(n,review_receipt):return ROOT/f"SCRIPT_DECISION_s{n}_call{review_receipt['ordinal']}.json"


def script_decision(n,approved,evidence):
    ctx,r,review=effective_script_review(n)
    if type(approved)is not bool:raise RuntimeError('approved must be a boolean')
    evidence=verify_assistant_evidence(ctx,evidence)
    if approved and (review['issues'] or not review['story_preserved']):raise RuntimeError('unresolved required issues')
    value={'schema':'verified_script_decision/resume_v1','script_source_sha256':control.digest(ensure_latest_draft(n)['output']),
        'review_context_sha256':compact.context_digest(ctx),'review_receipt_sha256':control.sha_file(ROOT/next(c['receipt'] for c in control.read(ROOT/'CALL_LEDGER.json')['calls'] if c['ordinal']==r['ordinal'])),
        'approved_for_direction':bool(approved),'evidence':deepcopy(evidence),'media_approval':False}
    control.write(decision_path(n,r),value,True);return value


def require_script_decision(n):
    ctx,r,review=effective_script_review(n);d=control.read(decision_path(n,r))
    if not d['approved_for_direction'] or review['issues'] or not review['story_preserved']:raise RuntimeError('script not adopted')
    if d['review_context_sha256']!=compact.context_digest(ctx) or d['script_source_sha256']!=control.digest(ensure_latest_draft(n)['output']):raise RuntimeError('script decision stale')
    receipt=next(c['receipt'] for c in control.read(ROOT/'CALL_LEDGER.json')['calls'] if c['ordinal']==r['ordinal'])
    if d['review_receipt_sha256']!=control.sha_file(ROOT/receipt):raise RuntimeError('review decision stale')
    return d


def director_context(n):
    require_script_decision(n);c=original();c.pop('script')
    c['raw_linear_script']=deepcopy(ensure_latest_draft(n)['output'])
    c['adopted_story_direction']=deepcopy(adopted_story_plan()['output'])
    original_manifest=deepcopy(c['static_visual_manifest'])
    bundle=component_registry.build_p03_registry(original_manifest)
    c['static_visual_manifest']=component_registry.validate_component_bundle(bundle)
    c['component_registry']=deepcopy(bundle)
    c['linear_script_protocol']=linear.VERSION
    c['script_timing_status']='preliminary_budget_not_actual'
    c['script_preliminary_timing']=linear.preliminary_timing_estimates(c['raw_linear_script'])
    return c


def direction(n,revision=1,feedback=None):
    ctx=director_context(n);messages=physical.build_direction_messages(ctx)
    if feedback:messages.append({'role':'user','content':json.dumps({'previous_direction_fault':feedback,
        'request':'提交完整新整片方向、初态和分镜安排，不返回字段补丁，不改变原steps。'},ensure_ascii=False)})
    w=wire('writer',messages,physical.build_direction_schema(ctx),8000,
        {'script_decision_sha256':control.digest(require_script_decision(n)),
         'raw_script_sha256':control.digest(ctx['raw_linear_script']),'reference_pack_sha256':control.digest(ctx['reference_pack']),
         'full_reference_pack_in_messages':True,'actual_selected_images':[],'images_returned_to_director':False})
    def validate(raw):
        physical.validate_direction(raw,ctx)
        return {'direction_source_coverage_valid':True,'shots':len(physical._shots(raw)),
                'source_text_unchanged':True,'semantic_approval':False,'physical_state_verified':False}
    return runtime().dispatch(f'direction_s{n}_r{revision}',w,validate)


def direction_source(n,revision):
    r=latest(f'direction_s{n}_r')
    if r['label']!=f'direction_s{n}_r{revision}':raise RuntimeError('direction superseded')
    ctx=director_context(n);physical.validate_direction(r['output'],ctx)
    return ctx,r['output']


def local_sources(n,drevision,count):
    out=[]
    for i in range(1,count+1):out.append(latest(f'local_s{n}_d{drevision}_p{i:03}_r')['output'])
    return out


def local(n,drevision,index,revision=1,feedback=None):
    ctx,d=direction_source(n,drevision);previous=local_sources(n,drevision,index-1)
    inp=physical.build_local_input(ctx,d,previous);messages=physical.build_local_messages(inp)
    if feedback:messages.append({'role':'user','content':json.dumps({'previous_complete_local_fault':feedback,
        'request':'保持原脚本与方向，按真实首态提交当前镜完整新局部方案，不返回补丁、不凭空加动作。'},ensure_ascii=False)})
    w=wire('writer',messages,physical.build_local_schema(inp),4096,
        {'local_input_sha256':control.digest(inp),'current_shot':inp['shot_id'],
         'previous_locals_sha256':[control.digest(x) for x in previous],
         'raw_script_sha256':control.digest(ctx['raw_linear_script']),
         'reference_pack_sha256':control.digest(ctx['reference_pack']),'full_reference_pack_in_messages':True})
    def validate(raw):
        result=physical.compile_prefix(ctx,d,previous+[raw])
        control.write(ROOT/f'PREFIX_s{n}_d{drevision}_p{index:03}_{control.digest(result)[:12]}.json',result,True)
        return {'compiled_prefix_shots':len(previous)+1,'source_schedule_order_checked':True,
                'physical_state_checked':True,'declared_windows_checked':True,'component_registry_bound':True,'semantic_approval':False}
    return runtime().dispatch(f'local_s{n}_d{drevision}_p{index:03}_r{revision}',w,validate)


def complete(n,drevision):
    ctx,d=direction_source(n,drevision);locals_=local_sources(n,drevision,len(physical._shots(d)))
    result=physical.compile_complete(ctx,d,locals_)
    control.write(ROOT/f'COMPLETE_s{n}_d{drevision}_{control.digest(result)[:12]}.json',result,True)
    return ctx,d,locals_,result


def final_context(n,drevision):
    ctx,d,locals_,compiled=complete(n,drevision)
    ctx['script']=derive(ctx['raw_linear_script']);ctx['script'].pop('screenplay_markdown')
    ctx.update(shots=deepcopy(compiled['storyboard']),state_plan=deepcopy(compiled['derived_action_plan']),
        whole_film_direction=deepcopy(d),execution_script=deepcopy(compiled['derived_execution_script']),
        execution_bindings=[{k:deepcopy(t[k]) for k in ('shot_id','source_ref','anchor','kind','start','end')} for t in compiled['source_trace']],
        declared_performance_window_checks=deepcopy(compiled['performance_checks']))
    return ctx,compiled


def joint_review_messages(ctx):
    scope=ctx.get('review_scope')
    if scope=='storyboard_segment' or (isinstance(scope,dict) and scope.get('current_beat_only')) or ctx.get('scope')=='single_beat':raise RuntimeError('full joint review requires whole-film scope')
    rows=compact._rows(ctx);p=build_review_prompt(ctx);lines=[];seen=set()
    for line in p.splitlines():
        if line.startswith('唯一输出JSON顶层字段'):
            line='唯一输出JSON顶层字段恰为schema、context_sha256、story_preserved(bool)、issues(array)、suggestions(array)、calibration_focus(array)、coverage(array)。有必修问题story_preserved=false，否则true。';seen.add('top')
        elif line.startswith('evidence_refs每项为'):
            line='evidence_refs每项严格为[path,quote]二元数组；点分路径到输入真实字符串或数字叶子，quote逐字片段，不引对象数组。每条issue有真实当前script/shots正文证据。';seen.add('refs')
        elif line.startswith('coverage逐行覆盖编号'):
            line='coverage完整覆盖各编号一次：'+json.dumps(rows,ensure_ascii=False)+'。每行固定[id,requirements,timing,continuity,dialogue_timing,first_frame,assets]；每检查固定[status,reason,evidence_refs,issue_ids]。status仅pass/fail/not_applicable；保留具体核对理由与所有证据，fail关联已列issues，其他issue_ids=[]。pass/fail引用本镜实际正文，各要求与上一镜来源按下文，不允许漏行或默认通过。';seen.add('coverage')
        lines.append(line)
    if seen!={'top','refs','coverage'}:raise RuntimeError('joint review prompt protocol changed')
    lines += ['schema填写'+json.dumps(compact.VERSION)+'；context_sha256填写'+json.dumps(compact.context_digest(ctx))+'。',
        '本次同时审完整原steps、整片情绪与因果、全片方向、实际镜头、typed operations和执行绑定。script是原故事正文；execution_script与分镜对白窗口是实际排时，不拿上游估时替代实调。核对每原action的文字是否由操作及表演完整兑现，没有来源的新动作、被删动作、隐藏在文字中的物理变化都应报告；机械通过不能代替语义审查。actual_selected_images为空，图片审美尚待人选后回传导演，不假定已选或复用成功。']
    return [{'role':'system','content':'\n'.join(lines)},{'role':'user','content':json.dumps(ctx,ensure_ascii=False,separators=(',',':'))}]


def final_review(n,drevision,revision=1,feedback=None):
    ctx,compiled=final_context(n,drevision);joint_binding.preflight(ctx);messages=review_wire.joint_messages(ctx,joint_review_messages(ctx),joint_binding.build_messages_addendum(ctx))
    if feedback:messages.append({'role':'user','content':json.dumps({'previous_full_review_protocol_fault':feedback,
        'request':'完整重新复审，不能拼接截断或局部结果。'},ensure_ascii=False)})
    w=wire('director',messages,review_wire.schema(ctx),24000,{'compiled_sha256':control.digest(compiled),
        'review_context_sha256':compact.context_digest(ctx),'reference_pack_sha256':control.digest(ctx['reference_pack']),
        'full_reference_pack_in_messages':True})
    def validate(raw):
        review=compact.expand_review(raw,ctx);joint_binding.validate_joint_review(review,ctx)
        return {'complete_joint_review_evidence_valid':True,'story_preserved':review['story_preserved'],
                'issue_count':len(review['issues']),'requires_assistant_source_verification':True,'semantic_approval':False}
    return runtime().dispatch(f'final_review_s{n}_d{drevision}_r{revision}',w,validate)


def get_effective_final_review(n,drevision):
    ctx,compiled=final_context(n,drevision);r=latest(f'final_review_s{n}_d{drevision}_r')
    review=compact.expand_review(r['output'],ctx);joint_binding.validate_joint_review(review,ctx)
    return ctx,compiled,r,review


def render_production_plan(ctx,compiled):
    raw=ctx['raw_linear_script'];direction=ctx['whole_film_direction']
    parts=[f"# {raw['title']}：整片导演与表演安排",'',
           f"实际编译时长：{compiled['total_duration_seconds']:.2f}秒；{compiled['execution_shot_count']}镜。",'',
           '本文件是文本制作安排；实际样板与资产尚待人工选定并回传导演，视频须逐段人工审查。','',
           '## 整片方向','',str(direction['emotional_arc']),'',str(direction['ending_intent']),'',
           '因果链：'+json.dumps(direction['causal_chain'],ensure_ascii=False),'']
    byid={x['shot_id']:x for x in physical._shots(direction)}
    source={x['source_step_ref']:x['source_step'] for x in compiled['source_map']}
    elapsed=0
    for shot in compiled['storyboard']['shots']:
        d=byid[shot['beat_id']];end=elapsed+shot['duration_seconds']
        parts += [f"## {shot['id']}（{elapsed:.2f}–{end:.2f}秒）",'',
            '新增信息：'+d['new_information'],'', '观察对象：'+d['observation_object'],'',
            '画面与机位：'+d['composition']+'；'+d['camera'],'', '切镜理由：'+d['cut_reason'],'',
            '刺激与反应要求：'+json.dumps(d['performance_requirements'],ensure_ascii=False),'',
            '首态：'+shot['start_state'],'', '| 全片时间 | 原文与表演 | 实际操作 |','| --- | --- | --- |']
        seen_steps=set()
        for e in (x for x in compiled['source_trace'] if x['shot_id']==shot['beat_id']):
            original_step=source[e['source_ref']]
            text=original_step['text'] if e['source_ref'] not in seen_steps else '同一原步骤续行（不重演动作）'
            seen_steps.add(e['source_ref'])
            if original_step['kind']=='dialogue':text=original_step['speaker']+'：'+text
            text=e['source_ref']+' / '+e['anchor']+' / '+e['kind']+' / '+text
            performance=e['actual_scheduled_payload']['performance']
            content=(text+' / '+performance).replace('|',r'\|').replace('\n','<br>')
            ops=json.dumps(e['physical_operations'],ensure_ascii=False).replace('|',r'\|')
            parts.append(f"| {e['start']:.2f}–{e['end']:.2f}秒 | {content} | {ops} |")
        scheduled=next(b for b in compiled['scheduled_execution']['beats'] if b['beat_id']==shot['beat_id'])
        report=next(b for b in compiled['schedule_report']['beats'] if b['beat_id']==shot['beat_id'])
        if report['unused_tail_seconds']>1e-8:
            tail=scheduled['events'][-1]
            parts.append(f"| {elapsed+tail['start']:.2f}–{elapsed+tail['end']:.2f}秒 | 程序尾保持：{tail['performance']}（不计作声明反应窗口） | [] |")
        parts += ['', '尾态：'+shot['end_state'],'']
        elapsed=end
    parts += ['## 制作交接与待办','',
        '1. 在媒体授权范围内先出少量审美样板，由用户确认人物、场景与画风。',
        '2. 生成或复用资产，把实际选定图片及文件标识回传给导演，重核本安排。',
        '3. 逐段生成视频；接口成功且文件完整保存后记录 awaiting_human_review。',
        '4. 用户明确通过当前段后，使用服务返回的原始尾帧续段。','']
    return '\n'.join(parts)


def finalize(n,drevision,evidence):
    ctx,compiled,r,review=get_effective_final_review(n,drevision)
    if review['issues'] or not review['story_preserved']:raise RuntimeError('full production text has unresolved issues')
    evidence=verify_assistant_evidence(ctx,evidence)
    source=ensure_latest_draft(n);out=ROOT/f'DELIVERABLE_s{n}_d{drevision}';out.mkdir(exist_ok=True)
    raw=source['output'];control.write(out/'FULL_SCRIPT.json',raw,True)
    text=linear.render_linear_screenplay(raw)+'\n'
    target=out/'FULL_SCRIPT.md'
    if target.exists() and target.read_text(encoding='utf-8')!=text:raise RuntimeError('delivery script changed')
    target.write_text(text,encoding='utf-8')
    plan_text=render_production_plan(ctx,compiled)
    plan_path=out/'DIRECTOR_PERFORMANCE_PLAN.md'
    if plan_path.exists() and plan_path.read_text(encoding='utf-8')!=plan_text:raise RuntimeError('delivery plan changed')
    plan_path.write_text(plan_text,encoding='utf-8')
    control.write(out/'WHOLE_FILM_DIRECTION.json',ctx['whole_film_direction'],True)
    control.write(out/'COMPILED_PERFORMANCE.json',compiled,True)
    control.write(out/'FULL_TEXT_REVIEW.json',review,True)
    control.write(out/'STATIC_ASSET_DEFINITIONS.json',ctx['static_visual_manifest'],True)
    handoff={'schema':'creative_text_handoff/resume_v1','status':'text_reviewed_awaiting_aesthetic_samples',
        'script_sha256':control.digest(raw),'compiled_sha256':control.digest(compiled),'review_sha256':control.digest(review),
        'assistant_verified_evidence':deepcopy(evidence),'narrative_beats':len(raw['beats']),
        'shots':compiled['execution_shot_count'],'compiled_duration_seconds':compiled['total_duration_seconds'],
        'text_production_handoff_complete':True,'actual_selected_images':[],'actual_images_returned_to_director':False,
        'component_registry':deepcopy(ctx['component_registry']),'original_asset_manifest_preserved':True,
        'preliminary_script_budget_was_not_actual':True,
        'asset_sample_selection_status':'awaiting_human_aesthetic_approval','media_calls':0,
        'video_content_status':None,'video_human_review_required':True,'automatic_media_submit':False,
        'next_steps':['generate few aesthetic samples under media authorization','human aesthetic selection',
            'generate or reuse assets and return actually selected images to director','revalidate direction/performance against real assets',
            'generate one segment; save awaiting_human_review','continue only after explicit human approval using original service tail frame'],
        'cost_ledger':runtime().summary(),'old_task_or_budget_reset':False}
    control.write(out/'PRODUCTION_HANDOFF.json',handoff,True)
    return handoff


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');command=sys.argv[1]
    feedback=control.read(sys.argv[-1]) if sys.argv[-1].endswith('.json') else None
    args=[int(v) for v in sys.argv[2:] if not v.endswith('.json')]
    if command=='prepare':value=runtime().prepare()
    elif command=='story-plan':value=story_plan(*args,feedback=feedback)
    elif command=='draft':value=draft(*args,feedback=feedback)
    elif command=='script-review':value=script_review(*args,feedback=feedback)
    elif command=='direction':value=direction(*args,feedback=feedback)
    elif command=='local':value=local(*args,feedback=feedback)
    elif command=='final-review':value=final_review(*args,feedback=feedback)
    elif command=='report':value=runtime().summary()
    else:raise SystemExit('prepare | story-plan REV | draft N | script-review N REV | direction N REV | local N D INDEX REV | final-review N D REV | report [feedback.json]')
    if 'status' in value:print(json.dumps({k:value.get(k) for k in ('ordinal','label','status','validation','failure','validation_error','response_metadata')},ensure_ascii=False,indent=2))
    else:print(json.dumps(value,ensure_ascii=False,indent=2))
