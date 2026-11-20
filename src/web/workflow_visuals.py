"""Explain the configured capabilities without inventing a runnable DAG."""
from src.workflow.contracts import ActivationMode

STAGE_INTROS = {
    'trend_collection': '收集与账号方向有关的热门内容，为选题提供样本。',
    'media_acquisition': '取得样本视频或媒体信息，让后续分析有可追溯的输入。',
    'content_analysis': '提取样本内容、结构与特征，形成分析依据。',
    'opportunity_ranking': '结合相关性与分析结果，筛选值得继续研究的选题。',
    'llm': '理解需求、组织内容与生成文本，为内容策划提供支持。',
    'tts': '把确认后的文本转换为配音音频。',
    'background': '为画面准备背景素材。当前是否可用以所选实现状态为准。',
    'video_pipeline': '组织视频制作主流程。旧路线已停用，等待新流程验收。',
    'portrait_animation': '驱动人物表情、口型或头像动作。',
    'video_generation': '根据已准备的输入制作视频片段。',
    'frame_interpolation': '补充中间帧，改善视频片段的运动连续性。',
    'composition': '合并画面、音频和字幕，形成待审核成片。',
    'publishing': '将已审核成片交给指定平台账号发布。',
}


def build_workflow_graph(registry, profile, labels):
    positions = {'trend_collection': (0, 0), 'media_acquisition': (1, 0),
                 'content_analysis': (2, 0), 'opportunity_ranking': (3, 0),
                 'llm': (0, 1), 'tts': (1, 1), 'background': (1, 2),
                 'video_pipeline': (0, 3), 'portrait_animation': (1, 3),
                 'video_generation': (2, 2), 'frame_interpolation': (2, 3),
                 'composition': (3, 2), 'publishing': (3, 3)}
    modes = {ActivationMode.HOT_SWITCH: '已接线', ActivationMode.PROFILE_ONLY: '待适配',
             ActivationMode.EXTERNAL_CONFIG: '环境配置', ActivationMode.RESTART_REQUIRED: '需重启'}
    nodes = []
    for stage, implementation in profile.selections.items():
        spec = registry.get(stage, implementation)
        disabled = implementation == 'disabled_pending_redesign'
        status = '已停用' if disabled else modes[spec.activation_mode]
        column, row = positions.get(stage, (0, 4))
        ports = lambda values: '\n'.join(f'{p.description or p.name} · {p.artifact_type}' for p in values)
        nodes.append(dict(id=stage, label=labels.get(stage, stage), subtitle=status + ' · ' + spec.label,
                          column=column, row=row, status=status, disabled=disabled,
                          description=STAGE_INTROS.get(stage, spec.description),
                          facts=[['当前实现', spec.label], ['实现说明', spec.description],
                                 ['接收什么', ports(spec.inputs)], ['产出什么', ports(spec.outputs)],
                                 ['生效方式', status + '；配置状态不等于健康检查结果'],
                                 ['补充说明', '\n'.join(spec.notes) or '暂无补充说明']]))
    pairs = [('trend_collection', 'media_acquisition', '样本线索'),
             ('media_acquisition', 'content_analysis', '媒体内容'),
             ('content_analysis', 'opportunity_ranking', '分析结果'),
             ('opportunity_ranking', 'llm', '选题方向'), ('llm', 'tts', '配音文本'),
             ('llm', 'background', '场景描述'), ('background', 'video_generation', '画面素材'),
             ('video_pipeline', 'portrait_animation', '人物方案'),
             ('portrait_animation', 'frame_interpolation', '动作片段'),
             ('video_generation', 'composition', '视频片段'),
             ('tts', 'composition', '配音音轨'), ('frame_interpolation', 'composition', '连续画面'),
             ('composition', 'publishing', '审核后成片')]
    by_id = {n['id']: n for n in nodes}
    edges = []
    for source, target, payload in pairs:
        if source not in by_id or target not in by_id:
            continue
        pending = any(by_id[n]['status'] != '已接线' for n in (source, target))
        a = registry.get(source, profile.selections[source])
        b = registry.get(target, profile.selections[target])
        edges.append(dict(id=f'{source}:{target}', source=source, target=target,
                          label=f'{labels[source]} → {labels[target]}', short_label=payload,
                          status='职责衔接 · 待适配' if pending else '职责衔接', pending=pending,
                          description=f'「{labels[source]}」的{payload}，可作为「{labels[target]}」的准备依据。此线说明业务关系，实际接入还需完成接口适配与审核，不会因选中而执行。',
                          facts=[['上游输出契约', ', '.join(p.artifact_type for p in a.outputs)],
                                 ['下游输入契约', ', '.join(p.artifact_type for p in b.inputs)],
                                 ['当前边界', '注册表未定义可执行依赖图；这里不声明接口已直接连通。']]))
    return nodes, edges
