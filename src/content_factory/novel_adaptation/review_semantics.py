"""Shared field meanings for independent review, not exceptions to factual checks."""
RULES={
    'visible_people':'画面人物只列当前镜头可见的人，不是房间全体在场清单。未列出不等于离场；仍须核对实际进出、动作和对白。',
    'source_ids':'来源ID表示该段有内容依据此原段，不宣称覆盖原段的全部信息。遗漏核心因果可单独提出，不能只因未逐字复述整段就指责引用错误。',
    'audio_visual_overlap':'内心和旁白可与动作同时发生。只有稿中明确先后约束时，才从动作窗口扣除音轨时间；不能默认所有动作都等到音轨结束。',
    'design':'区分小说硬事实与明确影视补足。不同字段对同一设计对象互相冲突仍应报告；普通布景无需每次逐件演示摆放。',
    'scope':'拍摄场景列表不是整个故事世界可存在空间的穷举。画外提及地点不自动等于新增拍摄场景。',
    'severity':'偏好的剪辑节奏作为建议；事实矛盾、确定的动作因果缺口、身份或时间混淆才按证据判必须修复。模型verdict不是最终验收。',
}


def prompt():
    return '\n字段合同（与生成和状态解释保持一致）：\n'+'\n'.join(RULES.values())
