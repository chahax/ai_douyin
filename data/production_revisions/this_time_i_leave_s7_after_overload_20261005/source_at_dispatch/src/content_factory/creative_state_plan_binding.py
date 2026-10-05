"""Verify the reviewed state plan remains the source of downstream execution."""
import hashlib
import json
from pathlib import Path
from .creative_state_plan_v6 import compile_state_plan
from .creative_review_gate import confirmed_issues, digest


def bind_reviewed_state_plan(workflow, script, shots):
    """Return source context only for opt-in v6; legacy runs read no new files."""
    if (workflow.state.get('segmented_director_binding') or {}).get('version')!='reviewed_beat_storyboard_v6':
        return {},None
    from .creative_governed_runtime import verify_rules
    verify_rules(workflow, 'handoff')
    root=Path(workflow.run_dir)
    def read(name): return json.loads((root/name).read_text(encoding='utf-8'))
    record=read('STATE_PLAN.json')
    if record.get('schema')!='creative_reviewed_state_plan/v1': raise RuntimeError('STATE_PLAN包版本错误')
    source=record.get('source_stage','');review=record.get('review_stage','')
    for key,prefix in ((source,'director_state_plan__'),(review,'writer_check__state_plan_')):
        if not isinstance(key,str) or not key.startswith(prefix) or Path(key).name!=key:
            raise RuntimeError('STATE_PLAN来源阶段/审核阶段无效')
    plan=record['plan']
    if read(source+'.json').get('output')!=plan: raise RuntimeError('STATE_PLAN与模型产物不一致')
    packet=read(review+'__review_packet.json');decision=read(review+'__assistant_decision.json')
    binding={'packet_sha256':digest(packet),'decision_sha256':digest(decision)}
    if workflow.state.get('evidence_review_decisions',{}).get(review)!=binding:
        raise RuntimeError('STATE_PLAN未绑定实际助手审核回执')
    if confirmed_issues(packet,decision): raise RuntimeError('STATE_PLAN仍有已确认审核问题')
    context=packet.get('context',{})
    from .creative_focused_review_stage import enabled as focused_enabled, verify_expansion
    if focused_enabled(workflow, review, context):
        source_record = read(source+'.json')
        if source_record.get('status') != 'validated' or source_record.get('output_sha256') != digest(plan):
            raise RuntimeError('新版STATE_PLAN来源未验证或产物hash不符')
        if workflow.state.get('pending_focused_review'):
            raise RuntimeError('仍有聚焦审核待复核，禁止复用已审计划交接')
        verify_expansion(workflow, review, packet['review'], context)
    if context.get('state_plan')!=plan or context.get('script')!=script or context.get('shots')!=shots:
        raise RuntimeError('STATE_PLAN审核上下文与当前剧本/分镜不同')
    manifest=read('static_visual_manifest.json')['output']
    if context.get('static_visual_manifest')!=manifest or compile_state_plan(plan,script,manifest)!=shots:
        raise RuntimeError('STATE_PLAN不能重现当前执行分镜或静态资产已改变')
    extra={}
    if plan.get('schema') in ('whole_film_action_plan_v1', 'whole_film_action_plan_v2'):
        if plan.get("schema") == "whole_film_action_plan_v2":
            from .creative_action_plan_v2 import schedule_action_plan
        else:
            from .creative_action_plan_v1 import schedule_action_plan
        scheduled,report=schedule_action_plan(plan,script,manifest)
        if context.get('scheduled_state_plan')!=scheduled or context.get('scheduling_report')!=report:
            raise RuntimeError('动作计划派生时间轴与已审上下文不同')
        if read('SCHEDULED_STATE_PLAN.json')!=scheduled or read('SCHEDULING_REPORT.json')!=report:
            raise RuntimeError('已审派生时间轴或排时报告被改变')
        extra={'scheduled_state_plan':scheduled,'scheduling_report':report}
    record_hash=digest(record)
    if workflow.state.get('accepted_state_plan_sha256',record_hash)!=record_hash:
        raise RuntimeError('已绑定STATE_PLAN发生改变')
    workflow.state['accepted_state_plan_sha256']=record_hash
    workflow._save()
    return {'state_plan':plan,'static_visual_manifest':manifest,**extra},record_hash
