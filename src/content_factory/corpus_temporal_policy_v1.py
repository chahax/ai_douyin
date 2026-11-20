"""Define the temporal subject of a lightweight material fact.

This is a semantic contract for generation and independent review. JSON/source
validation cannot prove it; no keyword rule rewrites or approves model content.
"""
from copy import deepcopy

VERSION = 'corpus_temporal_policy/v1'

RULES = """时间与语气的判定对象是 statement 所断言的主体行为/命题，不是证据段里最显眼的日期词。先确认 statement 在说哪件事，再给这件事的 modality 和 event_time。
每项事实的主体命题只能有一套相容的时间与语气。相互关联但分属现在/过去/未来、实际/计划的命题分别登记；不把整个章节拆断，仍完整阅读原章，只将必要的事实条目拆开。相同时间性质的动作因果可以合并。
表达层与内容层：某人在本章当下说、告知、承诺、回忆、想到或首次得知一件事，这个表达/认知行为发生在本章当下，通常是 actual/chapter_present；话、回忆或计划里面的事件可以属于另一时间与语气。标签不能取内层事件的时间，却让 statement 主体继续写外层“告诉、说、想到”。
例如“傍晚，医生说：后天复查。”可登记“医生在傍晚提出后天复查的安排”（表达行为，actual/chapter_present），必要时另记“拟在后天复查”（拟议行为，plan/later）；不能把前一条整体标成已经发生的未来复查，也不能用它证明已经复查。
例如“旅客今天向司机讲述上周丢伞的经历”：今天讲述是 actual/chapter_present；上周丢伞属于讲述的内容。只有人物这么说，不能单凭其话语把所述事件提升为客观已证实；如需单列，明确是被回忆/声称的材料，依据来源选择 memory、belief 或 uncertain 等已有语气，而不是凭对白猜 actual。叙述者或其他原文独立证实的过去事件可用 actual/earlier。
计划应明确判定对象：statement 若描述拟议行动（如“拟次日离村”），用 plan/later；若描述当下产生或表达计划的行为，按当下表达标注，并在文字中明确内层行动尚未发生。不要求每句都双倍提取；必要的表达行为、内层计划或过去事件不得相互吞并或丢失。
模糊时间使用 unspecified 或保留原文相对时间，不补造日期。source_refs 可以保留完整原句，但 statement 的时间不能因引文同时含多个时点而含混。保持原有分类材料阶段边界，不新增实体表、持物/知情状态数组或剧本调度。"""

REVIEW_RULES = RULES + """
独立审核时逐条对齐 statement 的主体行为、modality、event_time，并检查一个条目是否混有不同时间/语气的命题。将“当前告知”标成 earlier、将“当前表达及未来行动”整体混标、将人物声称当客观事实，须在 modality_and_event_time 或 source_fidelity 中 revise，给出对应 fact_ids、原文及明确原因。不能仅因日期词出现在原文、结构完整、引文准确就 pass。
责任在材料阶段时要求重新生成该完整章节材料；不是要求前置知情状态数组。后续框架、快照、剧本必须保持这一解释；当前表达事实不能证明话中未来行动已完成，过去事件也不代表别人当时已获知。"""


def extraction_prompt(base):
    return base + '\n\n【时间判定约定 ' + VERSION + '】\n' + RULES


def extraction_schema(base):
    schema = deepcopy(base)
    fields = schema['properties']['facts']['items']['properties']
    fields['statement']['description'] = '仅描述具有相容时间与语气的一项主体命题；表达行为和所述事件必须明确区分。'
    fields['event_time']['description'] = '相对于本章当下，标注 statement 主体命题发生的时间；不自动取引文/对白内层事件的时间。'
    fields['modality']['description'] = '标注 statement 主体命题的实际/回忆/计划等性质；实际说过不等于话中事件真实发生。'
    return schema


def review_prompt(base):
    return base + '\n\n【独立时间语义核对 ' + VERSION + '】\n' + REVIEW_RULES


def downstream_prompt(base):
    return base + '\n\n【材料时间解释 ' + VERSION + '】\n' + (
        '材料的 event_time/modality 只描述该条 statement 的主体命题。当前表达、回忆、承诺、获知的行为，'
        '与话里提到的过去/未来事件分别理解；某人实际说过不证明所述事件客观成立，未来计划不当已完成。'
        '取用材料时同时对照主体命题和原文，不按日期关键词机械排序；歧义应明确退回负责阶段。'
        '仍按当前阶段既有职责与 schema 输出：本集快照阶段需要完整状态和动作链，编剧阶段需要完整剧本，'
        '不能将材料阶段不生成状态数组的约定扩展为后续阶段也不生成。')
