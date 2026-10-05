"""Runtime binding of the explicitly selected governance revision."""
from pathlib import Path
import json
from .creative_rule_registry import bind_registry, validate_registry_binding

PROTOCOL = 'governed_production_v1'
REGISTRY_DIRECTORY = 'data/creative_governance/20261002_v23_feedback_consistency'
ROOT = Path(__file__).resolve().parents[2]


def bind_new_task():
    return bind_registry(ROOT, REGISTRY_DIRECTORY)


def verify_rules(workflow, name=None):
    if workflow.state.get('production_protocol') != PROTOCOL:
        return None
    binding = workflow.state.get('rule_registry_binding')
    if not binding:
        raise RuntimeError('新版任务缺少规则版本绑定，不能自动补用当前规则')
    stage = ('plan_validation' if name and name.startswith('director_state_plan') else
             'plan_review' if name and name.startswith('writer_check') else
             'handoff' if name == 'handoff' else 'review')
    # Conservative activation: all in-scope features; no source-dependent rule is
    # silently skipped. Context-specific minimization remains explicit in registry.
    result = validate_registry_binding(binding, ROOT, stage=stage,
        features=['gaze','cut','seat','state','dialogue','timing','source','handoff'])
    if result['activation']['requires_split_or_merge']:
        raise RuntimeError('激活语义规则超出上限，需先合并或拆分责任')
    if name:
        path=Path(workflow.run_dir)/(name+'__rule_activation.json')
        if path.exists() and json.loads(path.read_text(encoding='utf-8')) != result:
            raise RuntimeError('阶段规则激活回执发生变化')
        path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


def record_plan_stop(workflow, name, error):
    receipt={'schema':'creative_plan_unavailable_receipt/v1','stage':name,
             'detail':error.detail,'automatic_retry':False,'automatic_approval':False}
    path=Path(workflow.run_dir)/(name+'__unavailable.json')
    if path.exists() and json.loads(path.read_text(encoding='utf-8')) != receipt:
        raise RuntimeError('表达不兼容停止回执发生变化')
    path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    workflow.state.update(status='needs_attention',unavailable_plan=receipt)
    workflow._save()



def focused_artifacts(workflow):
    """Recheck all accepted focused review receipts before handoff or resume."""
    if workflow.state.get('production_protocol') != PROTOCOL:
        return {}
    if workflow.state.get('pending_focused_review') or workflow.state.get('unavailable_plan'):
        raise RuntimeError('仍有待复核或表达不兼容，禁止媒体交接')
    from .creative_focused_review_stage import enabled, verify_expansion
    from .creative_review_gate import digest
    root=Path(workflow.run_dir);artifacts={}
    for key,binding in workflow.state.get('evidence_review_decisions',{}).items():
        packet_path=root/(key+'__review_packet.json')
        packet=json.loads(packet_path.read_text(encoding='utf-8'))
        context=packet.get('context',{})
        if not enabled(workflow,key,context):continue
        decision=json.loads((root/(key+'__assistant_decision.json')).read_text(encoding='utf-8'))
        if binding != {'packet_sha256':digest(packet),'decision_sha256':digest(decision)}:
            raise RuntimeError('已核实的聚焦审核回执绑定变化')
        verify_expansion(workflow,key,packet['review'],context)
        for suffix in ('.json','__focused_input.json','__disposition.json','__focused_review_expansion.json'):
            artifacts[key+suffix]='聚焦审核原始/派生回执及完整来源绑定'
        expansion=json.loads((root/(key+'__focused_review_expansion.json')).read_text(encoding='utf-8'))
        if expansion.get('resolution_sha256'):
            artifacts[key+'__focused_resolution.json']='真实助手复核unknown的绑定证据'
    if (root/'STATE_PLAN.json').exists():
        source=json.loads((root/'STATE_PLAN.json').read_text(encoding='utf-8'))['source_stage']
        if Path(source).name!=source or not source.startswith('director_state_plan__'):
            raise RuntimeError('交接源阶段路径无效')
        artifacts[source+'.json']='原始动作计划生产回执'
    return artifacts
