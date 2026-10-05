"""Immutable per-run original storyboard instructions; legacy/novel runs opt out."""
import json

VERSION = "original_director_v1"

SHOT_SHAPE = {
    "style": {
        "style_option_id": "director_brief.selected_style_id",
        "visual_medium": "画面媒介", "palette": "统一色彩", "spatial_layout": "明确空间和朝向",
        "character_lock": "确定人数、人物名和稳定外观", "light_source": "光源位置和方向",
    },
    "shots": [{
        "id": "SH01", "beat_id": "原剧本节拍ID", "duration_seconds": 8,
        "purpose": "本镜新增信息和观众关注点", "composition": "景别、入画人物、视线及布局",
        "camera": "机位与必要运镜", "visible_performance": "按时间顺序写可见动作、台词刺激及反应窗口",
        "event_lock": "逐字复制对应beat.event",
        "dialogue_lock": [{"speaker": "原说话人", "text": "逐字分配原对白"}],
        "start_state": "第一帧已成立的静态状态", "end_state": "动作完成后的末帧状态",
        "cut_reason": "本镜在此切走的叙事原因", "dialogue_mode": "画内",
        "continuity_mode": "raw_tail_continuation 或 planned_cut_requires_adapter",
        "prompt": "包含构图、动作、人物和道具状态的生成提示词", "production_choices": [],
    }],
    "media_assumptions": [],
}

PROMPT = """你是原创短片导演，为已审核的剧本设计可执行分镜，只返回合法JSON。
创作依据：creative_brief 的显式要求约束所有制作选择；script 是当前已审核演出锁。candidate_lock 是历史候选，不得把其中已被剧本删除或替换的动作、道具、结尾实现恢复。不要重新创作对白和剧情，也不把候选摘要当来源事实。director_brief 只提供已选画风和导演目标。
播放顺序：每拍 before → 第一条dialogue → during → 后续dialogue → after。严格保持节拍和动作顺序、因果、对白文字和说话人。event/trigger/premise 是摘要，不额外演出；screenplay_markdown 只是同稿可读版本。逐拍至少一镜，beat_id 使用输入原ID，镜头ID唯一；逐拍所有镜头时长之和必须等于该拍duration_seconds。
镜头设计：每镜明确新增的信息、看谁的反应和为何切走；机位服务于剧情，不以运镜数量代替叙事。省略进店、点单、普通走路等无因果必要的过程是合法省略，不得强加步骤。已有对白可以说明当前成立的状态，无需复演每一段前史。
情绪时序：为刺激、反应、关键对白前中后表演及收束分配明确秒数，面部须在情绪重心时可读；反应不得抢在刺激之前。可在原动作对白顺序内安排的窗口由导演排时，不退回编剧。不能仅按动作数量断言超时。中文每字计1单位、拉丁文本每词计2单位，每镜对白最多每秒5单位，动作、停顿和反应另留时间；不能借其他无对白镜的秒数抵扣。
声音归属：dialogue_lock 逐字分配本拍原对白，合并后与本拍dialogue的说话人和文字顺序完全一致，不新增、重复、删减或转移给别人。dialogue_mode 仅为“画内”“画外”“画内/画外”“无对白”；说话人的入画情况、构图、表演和prompt必须一致。
连续性：start_state 只写首帧已经成立的状态，本镜才发生的拿取、移动、接触等写入visible_performance，不得首帧先完成再重演。end_state 明确末帧结果。选择raw_tail_continuation时本镜start_state必须逐字等于上镜end_state；新机位、构图变化用planned_cut_requires_adapter，不能宣称原尾帧自然换机位。
人物与资产：人数确定，人物名、外观、服装、站位、视线和道具归属保持一致；画风采用director_brief.selected_style_id。可复用资产仅依据输入目录和已证实特征，不编造可用素材；目录缺失时记录待制作/待核实，不把复用写成已完成。
道具与构型：建立唯一数量、持有人、所在位置、开合状态、部件和可操作方式；同一对象的构型必须在style、composition、visible_performance、首尾状态、prompt和production_choices间一致。动作若需要取下部件、打开容器或重新握持，必须有合规时序；不能一处有盖另一处无盖，也不能把抓握部位或材质悄悄换掉。未被剧本确定的非叙事外观可以作为明确制作选择，但不能增加操作链、改变因果或突破简报。未来首帧与资产设计必须继承这些状态，不提前完成镜内动作。
执行边界：服从executor_constraints中的能力和每镜时长范围。必要时拆镜并合理分配时长，保持每拍总长；不能省掉必要反应或加速台词凑时。未看到实际素材时，构图和首帧只是计划，不能声称声音、口型、表演或媒体审核已通过。
输出分流：正常情况提交下列完整style/shots/media_assumptions对象，不输出空story_issues。只有无法通过构图、排时或已有演出顺序解决的具体blocking/major剧情矛盾，才返回非空story_issues；保留原稿并引用实际正文证据，遵循附加审核字段合同。已被助手驳回的问题不换措辞重提，不以个人审美建议冒充必须返修。缺少分镜不是故事问题。
字段合同：每镜包含示例的全部字段；无对白dialogue_lock=[]，production_choices与media_assumptions均为数组。每个文本字段具体且简洁，状态与动作不得相互矛盾。\n""" + json.dumps(SHOT_SHAPE, ensure_ascii=False)


def bind_original_director():
    return {"version": VERSION, "prompt": PROMPT}

REVISION_VERSION = "original_director_revision_v1"


def bind_original_director_revision(base_prompt):
    return {"version": REVISION_VERSION, "prompt": base_prompt + """
本次为已核实问题的局部导演返修，以下输出合同替代前面的首稿输出分流：只返回 {"replace_beats":[{"beat_id":"实际ID","shots":[该拍完整新镜头对象]}]}。
replace_beats 的数量、ID、顺序严格等于 affected_beat_ids；每拍交回全部镜头，不仅错误镜头。不得返回 story_issues、style、media_assumptions 或新剧本。以issues中的真实问题为修复目标，已驳回问题不重提。
script 是当前定稿；previous_shots 只用于未受影响镜头与相邻边界。受影响拍重新从当前script逐字复制event_lock和对白，候选或旧镜头中的已删除道具不得复活。合并后每拍时长、台词顺序、表演先后仍与script一致。
先逐秒安排刺激、说话、听者反应、动作及收束，不把有先后因果的动作改成同时发生；尤其不让收回、放松等结果抢在触发它的台词之前。首帧只描述首态；生成动作prompt不能当作首帧提示。
与前后未改镜头边界保持相容，变化机位采用planned_cut_requires_adapter，不能伪称原尾帧衔接。镜头标识唯一。涉及构图中的人物、服装、包型、道具部件和站位，必须在每个相关字段写一致；已入画角色必须由后续资产清单覆盖。资产和首帧问题在镜头中提供清晰静态依据，后续production_design单独重建并复核，不宣称已完成媒体审核。
"""}
