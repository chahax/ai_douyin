"""Preserve failed receipts and explicitly bind one budgeted full-plan rebuild."""
import json
from pathlib import Path
from datetime import datetime, timezone
from src.content_factory.creative_rule_registry import file_hash
from src.content_factory.creative_governed_runtime import bind_new_task


def prepare(run_dir):
    root = Path(run_dir).resolve()
    state = json.loads((root/'state.json').read_text(encoding='utf-8'))
    receipt_path = root/'PLAN_RECOVERY_AUTHORIZATION_V16.json'
    if receipt_path.exists():
        return json.loads(receipt_path.read_text(encoding='utf-8'))
    if state.get('status') != 'needs_attention' or 'PLAN_PATCH_VALUE_SCHEMA' not in state.get('last_error',''):
        raise RuntimeError('恢复仅适用于本次已确认的计划修复失败')
    if any((root/x).exists() for x in ['STATE_PLAN.json','STORYBOARD.json','MEDIA_HANDOFF.json']):
        raise RuntimeError('不能替换已审核或已交接计划')
    if state['calls_started']+5 > state['max_calls'] or state['revision_rounds'] >= state['max_revisions']:
        raise RuntimeError('重建、审查及后续必需调用的剩余预算不足')
    manifest = json.loads((root/'static_visual_manifest.json').read_text(encoding='utf-8'))['output']
    prior = json.loads((root/'director_state_plan__00__contract_repair_b79373e4fad5__action_patch_merge.json').read_text(encoding='utf-8'))['output']
    history = root/'history'/'failed_plan_v15_20261001'
    files = [p for p in root.glob('*.json') if p.name.startswith(('static_visual_manifest','director_state_plan__00')) or p.name.endswith('__rule_activation.json')]
    if history.exists():
        raise RuntimeError('恢复档案已存在但授权回执缺失，需核对中断状态')
    new_binding = bind_new_task()
    receipt = {'schema':'failed_plan_recovery/v1','created_at':datetime.now(timezone.utc).isoformat(),
        'authorization':'用户2026-10-01明确要求继续执行本流程；保留原14次调用及所有旧稿，用剩余额度重建未审核的导演工件。',
        'budget_before':{k:state[k] for k in ['calls_started','reported_tokens','revision_rounds','contract_repairs_used','max_calls','max_total_tokens','max_revisions','max_contract_repairs']},
        'previous_rule_binding':state['rule_registry_binding'],'new_rule_binding':new_binding,
        'archive':{p.name:file_hash(p) for p in files},'automatic_approval':False}
    manifest_rules = '保留原稿render、人物和P01到P07移动道具的身份及外观；椅子属于固定场景元素而非人物随身道具。将方澄椅P08改为固定元素E09，并为实际坐着工作的林屿明确固定椅E10；建立两桌、两椅、抽屉、门的稳定关系。P03三张便签位于方澄桌，P02当晚电影票信息可读。提交完整清单，不只返回补丁。不宣称任何现有画室图片已变成办公室。'
    plan_rules = '重新提交完整whole_film_action_plan_v2，使用当前新manifest身份，不沿用旧P08或把桌子E01当座椅。逐拍守住script实际动作对白顺序。根据每拍秒数给对白先留自然窗口，action/hold合计还要加对白才是总长，不机械添加长hold；数值必须number。完整保留必要动作和关键反应，不为排时删剧情；原稿不要求的停顿可以重新分配。检查所有拍而非只改B2。before在第一句前，during在第一句后、其余句前，after在全部对白后；performance不能藏take/place/move/stand/sit等物理操作。坐前位置、朝向、standing前提都要在前组成立；hold必须无物理动作。不编造操作kind，不伪造已完成状态。'
    state['stage_recovery_bindings'] = {
        'static_visual_manifest':{'version':'failed_plan_full_rebuild_v1','requirements':manifest_rules,'previous_invalid_output':manifest},
        'director_state_plan__00':{'version':'failed_plan_full_rebuild_v1','requirements':plan_rules,'previous_invalid_output':prior}}
    state['rule_registry_binding'] = new_binding
    state.setdefault('revision_committed',[]).append('failed_plan_full_rebuild_v16')
    state['revision_rounds'] += 1
    state['stages'] = [x for x in state['stages'] if x['name'] not in state['stage_recovery_bindings']]
    history.mkdir(parents=True)
    (history/'state_before.json').write_text((root/'state.json').read_text(encoding='utf-8'),encoding='utf-8')
    for path in files:
        target = history/path.name
        if not path.resolve().is_relative_to(root) or not target.resolve().is_relative_to(root):
            raise RuntimeError('档案路径超出当前任务')
        path.replace(target)
    receipt_path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    (root/'state.json').write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
    return receipt
