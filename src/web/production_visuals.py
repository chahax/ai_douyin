"""Artifact-backed production graph, including non-linear supporting views."""
def build_production_graph(items):
    descriptions = {
        '灵感来源': '查看选题来源、样本记录和本批次使用的灵感依据。',
        '分析依据': '了解来源时间、样本占比和研究方向，判断制作依据是否充分。',
        '剧本内容': '阅读完整剧本，确认故事结构、对白和画面描述。',
        '分镜与采集': '逐镜头查看提交提示词、生成回执、参考素材与已下载视频。',
        '合并成片': '预览按镜头顺序合并的成片，并检查声音和媒体参数。',
        '一致性审核': '阅读审核报告与角色对比，判断成片是否满足质量要求。',
        '本地文件': '集中查看本批次产物与下载入口。',
        '页面风格': '查看已有页面视觉基线与对比资料，属于辅助工具。',
    }
    nodes = [dict(id=name,label=name,subtitle=status,status=status,column=i%3,row=i//3,
                  description=descriptions[name],facts=[['记录状态',status],['操作说明','选中节点后，下方切换至该阶段的完整内容。']])
             for i,(name,status) in enumerate(items)]
    edges = []
    for source,target,payload in [('灵感来源','分析依据','来源证据'),('分析依据','剧本内容','分析方向'),
                                  ('剧本内容','分镜与采集','分镜描述'),('分镜与采集','合并成片','本地片段'),
                                  ('合并成片','一致性审核','待审核成片')]:
        status = dict(items)
        edges.append(dict(id=source+':'+target,source=source,target=target,label=source+' → '+target,short_label=payload,
                          status='制作衔接',description=f'从「{source}」提供{payload}，再进入「{target}」。这条线表示检查顺序，不代表任务已经执行或审核已经通过。',
                          facts=[['上游记录',status[source]],['下游记录',status[target]],['传递内容',payload]]))
    return nodes,edges
