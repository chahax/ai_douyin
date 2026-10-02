"""Readable authoring contracts and deterministic checks for creative stages.

These checks prove format, provenance and selected invariants. They do not claim
to measure aesthetic quality or to replace the initial actual editorial review.
"""

from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from difflib import SequenceMatcher
from typing import Any

from .reusable_production import DESIGN_PROMPT


class CreativeContractError(ValueError):
    pass


def _object_schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


def _array_schema(items: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": items}


_STRING = {"type": "string"}
_INTEGER = {"type": "integer"}
WRITER_TOOL_SCHEMAS = {
    "writer_analysis": _object_schema({
        "summary": _STRING,
        "characters": _array_schema(_object_schema({
            "name": _STRING, "want": _STRING, "fear": _STRING, "source_quote": _STRING,
        })),
        "candidates": _array_schema(_object_schema({
            "id": _STRING, "title": _STRING, "setup": _STRING, "conflict": _STRING,
            "turn": _STRING, "peak": _STRING, "aftermath": _STRING,
            "start_quote": _STRING, "end_quote": _STRING,
            "duration_seconds": _INTEGER, "selection_reason": _STRING,
        })),
        "selected_candidate_id": _STRING,
        "selection_reason": _STRING,
        "reference_use": _array_schema(_object_schema({
            "reference_id": _STRING, "mechanism": _STRING, "not_used": _STRING,
        })),
    }),
    "writer_script": _object_schema({
        "title": _STRING, "premise": _STRING,
        "selected_candidate_id": _STRING, "duration_seconds": _INTEGER,
        "beats": _array_schema(_object_schema({
            "id": _STRING, "duration_seconds": _INTEGER, "event": _STRING,
            "trigger": _STRING, "before": _STRING, "during": _STRING,
            "after": _STRING,
            "dialogue": _array_schema(_object_schema({
                "speaker": _STRING, "text": _STRING,
            })),
        })),
    }),
}
WRITER_TOOL_SCHEMAS["writer_revise"] = _object_schema({
    "replace_beats": _array_schema(_object_schema({
        "beat_id": _STRING,
        "beat": WRITER_TOOL_SCHEMAS["writer_script"]["properties"]["beats"]["items"],
    })),
})
WRITER_TOOL_SCHEMAS["writer_character_motivation_revise"] = _object_schema({
    "character_updates": _array_schema(_object_schema({
        "name": _STRING, "want": _STRING, "fear": _STRING, "source_quote": _STRING,
    })),
})
WRITER_TOOL_SCHEMAS["writer_candidate_claims_revise"] = _object_schema({
    "candidate_update": _object_schema({
        "id": _STRING, "title": _STRING, "setup": _STRING, "conflict": _STRING,
        "turn": _STRING, "peak": _STRING, "aftermath": _STRING,
        "start_quote": _STRING, "end_quote": _STRING,
        "duration_seconds": _INTEGER, "selection_reason": _STRING,
    }),
})
WRITER_TOOL_SCHEMAS["writer_director_feedback"] = _object_schema({
    "candidate_update": WRITER_TOOL_SCHEMAS["writer_candidate_claims_revise"]
        ["properties"]["candidate_update"],
    "feedback_responses": _array_schema(_object_schema({
        "feedback_index": _INTEGER,
        "decision": {
            "type": "string",
            "enum": [
                "accepted_candidate_change",
                "accepted_in_script",
                "director_only",
                "declined",
            ],
        },
        "reason": _STRING,
    })),
})


COMMON_RULES = """你在制作有来源证据的可读剧本。返回一个合法 JSON 对象，不要代码围栏或隐藏推理文本。
用简短的可审阅理由解释创作选择。小说正文是人物、关系、事件和对白的唯一剧情来源；参考片只能提供表达方法，不能移植它的人物、对白或事件。
原著事实、非冲突制作选择、实质改编分开。默认对白逐字保真；没有依据的地下车库、夕阳、人物外貌等不得称为原著事实。
重要对白前、中、后安排刺激与可见反应；镜头的价值在于观众收到的信息，不强制镜数、焦段或构图层数。\n参考片用于建立质量标尺时，必须比较整片因果梯、情绪梯和视觉状态梯；不能只摘取画风名、若干表情词或单镜技巧。目标不是复制参考剧情，而是达到相近的信息推进密度、情绪可读性和视觉递进。\n"""


PROMPTS = {
    "reference_summary": """你只提炼参考片的镜头、表演、构图和节奏方法，不移植人物、事件、对白或道具。返回合法 JSON 对象：
{"expression_mechanisms":["..."],"excluded_story_elements":["..."],"limits":["..."]}。expression_mechanisms 必须覆盖整片的因果递进、情绪递进、空间或光线或景别递进、转折处节奏变化和结尾人物反应；每条写明触发条件、可迁移做法及成片中可观察的验收证据。若参考资料含分段、切点或阶段统计，要总结其变化趋势，不得只列平均值。limits 写明时长、题材、媒介差异及单场景情况下的替代办法。不输出隐藏推理。""",
    "source_summary": COMMON_RULES + """你是 MiniMax 编剧。只总结本段已获取来源，不推断未提供章节。
返回 {"summary":"...","characters":[{"name":"...","want":"...","evidence_quote":"原文短引文"}],
"events":[{"event":"...","cause":"...","consequence":"...","start_quote":"原文短引文","end_quote":"原文短引文"}],
"limits":["..."]}。引文必须在本次片段中出现。""",
    "writer_analysis": COMMON_RULES + """你是 MiniMax 编剧。先整体理解实际送来的材料，再比较 1-3 个真正不同的候选；只有一个完整事件时解释限制。
小说候选给出原文中唯一可定位、按顺序出现的起止引文；视频驱动与原创简报驱动创作原创故事，候选 start_quote/end_quote 以及原创人物 source_quote 均置空，新编台词和场景细节绝不能冒充参考片原文。起点必须包含关键动作的直接诱因、必要承诺或质问，不能从亲吻、逃跑、道歉等情绪峰值才开始，让观众看不到角色为何这样做。候选声称单一场景时，起止引文不能跨过其他场景；不得把前后章节的亲吻、转账等动作偷移到本场。
候选 setup、conflict、turn、peak、aftermath 若用引号逐字写出原文对白，所有引文必须严格服从原文出现顺序；不能为了概括高潮把后说的认错或解释提前到老师的质问、对方的刺激之前。候选叙述与 creative_focus 冲突时以原文先后为准。
人物只列与本次候选有关者；每条 source_quote 只能选正文中同一位置的一段连续短引文，不得把三处证据、两句对白或对白与叙述拼接成一个字符串，也不要自行添加外层引号。引文必须逐字取自正文，不能把标点或字词改写成近义说法。characters.want 与 fear 都必须能从这一条引文或同一处紧邻行动得到支持；依据不足的 fear 明确写“原文未证实”，不能把教师想纠错自行扩写成害怕学生失败。单次侧目、冷脸或沉默不能自行解释为宣示主权、报复或和解。依据不足时只写可观察的当前目标，并把更深心理解释标为制作推断。候选的起止引文同样逐字引用，尽量短到可唯一定位。
候选理由应精炼，逐条区分原文事实和制作设想；输入含 creative_focus 时优先研究该对照焦点，但若焦点中的情绪或行为没有原文依据，明确指出并改用有依据的情绪链；若仍决定保留它，标为实质改编，不能称作原著事实。end_quote 必须覆盖候选 aftermath 最后一个来源行动，不能停在前一句对白却把紧接着的反应写进收束；例如原文在 Matthew 鼓励之后紧接 `Anne smiled back at him.`，候选若以 Anne 回笑结束，end_quote 就必须取到这句回笑。
候选 start_quote 若从人物已经开口的直接对白开始，而到场、走近、坐下等动作位于锁定边界之前，setup 必须从人物已经在场的状态起拍；不得把边界外的进场动作重新写入本片。creative_focus 已锁定短选段时，起态只可使用用户明确给出的空间与对象；选段前才出现的仙石、芝兰、车辆、家具等场景物件不能作为主物、背景锚点或人物承载面重新带回。selected_source 锁定后，完整 materials 中位于终点以后的吃饭、离场、关系解释等信息也不能借“制作选择”、环境声、视线目标或表演动机重新带回当前成片。
原创视频候选若目标时长超过60秒，必须至少形成四次清楚可辨的因果推进：每次都改变人物掌握的信息、当下选择、代价或关系中的至少一项；不能把 setup、conflict、turn、peak、aftermath 写成同一对话的五种说法。参考片若展示了空间、光线、景别、社会密度或切镜密度的递进，reference_use 必须指明本故事在哪个阶段采用、观众会看到什么变化，以及哪些剧情元素明确不采用。单一场景只有在构图、光线、距离和人物支配关系至少出现三次有意义变化时才可入选；反复对视、低头、握拳不算三次变化。候选必须把使后果具有约束力的决定性动作明确写进 conflict 或 turn，例如签字、付款、交付或公开承诺；不能只在 premise 声称人物做过，实际候选却从犹豫直接跳到事后。
原创故事中会触发人物决定、改变关系或承担证据链的因果性关键道具，第一次出现时交代它原先的位置、由谁拿起和如何进入后续镜头；不能让下一拍突然出现一件物品，再把它当作角色改变决定的唯一证据。袖中纸甲、课桌内纸张等普通随身或桌内物品若不承担前置因果，可以在首次使用的同一连续动作中从明确储存位置取出，无须为了“预先建立”而让人物在情绪刺激之前提前玩弄或展示。小说候选若核心动机只存在于内心叙述，而选段里没有能支持该动机的可见动作、可听对白或他人刺激，应降低或放弃该候选，或调整到包含真实外部诱因的原文边界；不能为使动机可拍而新造扒衣袖、看价签、翻购物小票、偷看表格或手机界面等动作物证。候选的转折动作应符合人物日常做法；若为了表现忙碌而让人物把已盛好的食物倒回锅再重新装盒，要先判断是否有更直接、可信的一步动作。候选时长必须容纳完整物理动作、看到刺激后的停顿和结尾反应，不靠增加切镜冒充增加表演时间。
原文“告诉、叮嘱、表示、答应”等间接叙述不等于人物直接引语，不能把叙述中的内容原样或加称呼后塞进对白。若候选的关键刺激或结局只靠这类间接叙述成立，而 creative_focus 又禁止旁白、字幕和新增对白，应放弃该候选或选择另一个有可听对白、可辨行动的事件；不能把无法拍清的矛盾留给剧本阶段。
返回 {"summary":"...","characters":[{"name":"...","want":"...","fear":"...","source_quote":"..."}],
"candidates":[{"id":"C01","title":"...","setup":"...","conflict":"...","turn":"...","peak":"...","aftermath":"...",
"start_quote":"...","end_quote":"...","duration_seconds":90,"selection_reason":"..."}],
"selected_candidate_id":"C01","selection_reason":"...",
"reference_use":[{"reference_id":"R01","mechanism":"...","not_used":"..."}]}。reference_use 永远是数组：没有参考片时必须返回空数组 []，不得返回“无参考”对象、字符串或带 `$text` 的包装。不要只按数字分数选。""",
    "director_brief": COMMON_RULES + """你是 DeepSeek 导演。自己阅读来源和编剧候选，在剧本展开前参与一次。
比较至少两种不同画风，不把都市自动选为二维；说明镜头、空间与表演怎样支持情绪，以及已知执行限制。selected_style_id 对应的 medium 必须最终锁定一种可执行媒介，例如明确选择实拍、二维、三维或定格之一；不得写“实拍或高拟真三维”“二维/实拍”等把媒介二选一留给下游。
独立核对编剧所写的情绪因果与原始材料；用户对照焦点或编剧候选中的无依据心理变化，只能作为明确标注的改编建议，不能在导演稿中当原文事实沿用。检查 selected_source 起点是否漏掉紧邻的关键刺激，例如亲吻前的承诺对白；如需前移，给 source_scope.lead_in_start_quote（原文唯一可定位的短引文）和 reason。也检查候选起点是否过早，以至剧本焦点前已有整场未打算呈现的事件；如需收窄，给 source_scope.trim_start_quote（所选原文内、实际开场前因处唯一可定位的短引文）和 reason。若候选结尾声称的关键行动或反应位于当前 end_quote 后方，给 source_scope.extend_end_quote（后方原文中新的唯一终点短引文）和 reason，不能让编剧在锁定选段外补剧情；若候选结尾带入下一场或本片明确不拍的后续，给 source_scope.trim_end_quote（所选原文内、实际收束处唯一可定位的短引文）和 reason。起点前移与收窄最多选一个，终点延长与收窄最多选一个；一种起点调整可与一种终点调整同时使用，但调整后起点必须早于终点。不得在分镜阶段才改变故事边界。无需调整则 source_scope 写空对象 {}。
在 writer_feedback 中检查所选候选的因果性关键道具是否先出现后起作用、转折动作是否符合常识，以及标称总时长能否容纳每次拿取、移动、交接和必要反应。普通随身或桌内物品不承担前置因果时，允许在首次使用的连续动作里从袖口、书包或课桌等明确位置取出；不要强迫编剧在情绪刺激之前单独预演取物。发现上游故事问题时明确交给编剧，不能指望拆成更多镜头就自动解决。writer_feedback 只列必须由编剧实际处理的可执行问题；“无需修改、无需调整、维持当前、候选没有问题”属于检查通过，不得作为反馈项。全部检查通过时返回空数组 []，不要让编剧为通过项逐条回执。
还要检查关键告知、承诺或叮嘱在原文中究竟是引号内直接对白，还是“告诉他、叮嘱他”等间接叙述。不得建议把间接叙述逐字改成人物台词；若不使用原文连续旁白、字幕或有依据的可辨行动就无法让观众理解，应在本阶段要求更换候选或修改候选呈现约束，不能等分镜阶段再让编剧违规补对白。逐项核对 candidate aftermath 的最后行动是否真的位于 end_quote 之内；原文若在 end_quote 后紧接 `Anne smiled back at him.`，候选却承诺 Anne 回笑，必须前期要求延长终点，不能把边界外反应交给剧本。
若 creative_focus 指定一个关系动作，例如“同伴递稳、对方主动接走”，要核对候选与后续节拍保留交付者和接受者；若候选让两人互不触碰道具，须明确提示编剧这是改变了情绪高光。不要把精确手写文字或无声唇读设计成观众理解因果的唯一证据。
selected_source 之外的到场、吃饭、离开、关系说明或选段前才出现的仙石、芝兰、车辆、家具等场景物件，不能因为完整 materials 可见就进入分镜；不得把它们用作主物、背景锚点、人物承载面，也不得用画外环境声、视线看向某处或“制作选择”暗示这些边界外事实。若首句已经是直接对白，镜头从人物已在场的可见状态开始，不能补拍选段前的走入。原文和 creative_focus 没有身体吸引、打量或相关刺激时，不得把视线落到胸前、领口、衣扣、大腿或嘴唇来制造暧昧；人物反应应落在面部、手部或来源支持的关键物上。
对目标时长超过60秒的候选，visual_strategy 必须按建立、上升、转折、峰值、余波写出视觉状态递进，至少三次改变空间、光线、景别、人物距离或社会密度；每次变化要与信息或关系变化绑定。performance_strategy 写出各阶段人物情绪的外显差异和峰值对白后的独立反应窗口。spatial_strategy 说明为何换场或为何单场景仍能持续增加信息。参考片在转折处加密切镜或逼近人物时，可以迁移这种节奏函数，但不得照搬其人物、事件、对白或专属道具。若候选没有足够的情绪与视觉递进，必须在 writer_feedback 中退回，不能靠后期多切几个镜头假装丰富。
返回 {"style_options":[{"id":"S01","medium":"...","palette":"...","performance_fit":"...","source_basis":"...","tradeoff":"..."}],
"selected_style_id":"S01","visual_strategy":"...","spatial_strategy":"...","performance_strategy":"...",
"feasibility_notes":["..."],"writer_feedback":[{"issue":"...","scope":"...","proposal":"..."}],
"source_scope":{"lead_in_start_quote":"需前移时的原文短引文，或留空","trim_start_quote":"需收窄开头时的原文短引文，或留空","extend_end_quote":"需延长结尾时的新终点原文短引文，或留空","trim_end_quote":"需收窄结尾时的原文终点短引文，或留空","reason":"为何调整，均不调整时留空"}}。
不能替编剧改剧情。""",
    "writer_director_feedback": COMMON_RULES + """你是 MiniMax 编剧。DeepSeek 导演已经在完整剧本展开前独立阅读同一来源，并给出 writer_feedback；你现在必须逐条回应，再锁定候选的故事声明。这个阶段只协调候选，不写节拍、分镜或 screenplay_markdown。
candidate_lock 的 id、title、start_quote、end_quote、duration_seconds 已锁定，不得改变。setup、conflict、turn、peak、aftermath 与 selection_reason 可以修订，但每项必须能在 selected_source 内由逐字对白或可见动作成立。导演若指出候选把 selected_source 终点后的跟随、关门、回家、和解或心理结论写进本片，必须删去越界承诺并改成选段内实际发生的收束；不能只答应在后续剧本里处理，却保留错误 candidate_lock。
selected_source.text 是本阶段允许声称为原文的全部范围。不得引用“原文下一行”“紧接下文”或材料中未提供的后续来支持替代动作；完整 materials 中即使存在选段外文字，也不能借它绕过已锁定边界。creative_focus 允许“开始响应”时，只能添加一个不改变事件结果的最小非语言制作选择，并在 selection_reason 与反馈 reason 中明确写“非冲突制作选择、原文未写明”，不能伪称来源事实，也不能把迈步、入门、关门、应声对白等新事件塞进 aftermath。
candidate_update 中用引号逐字写出的原文对白必须继续按 selected_source 的出现顺序排列；不能因导演意见或原候选写错，就把后说的解释、认错提前到原文中更早的质问或刺激之前。
按 writer_feedback 原顺序返回一条 feedback_responses。decision 只能是：accepted_candidate_change（已修改候选声明）、accepted_in_script（候选本身正确，将在节拍中落实）、director_only（纯机位、画风或摄影执行事项，由导演负责）、declined（有明确来源证据所以不采纳）。每条 reason 都写具体处理或逐字来源依据，不能只写已优化、同意或不采纳。涉及候选、选段、原文边界、setup/conflict/turn/peak/aftermath 的意见不能标 director_only；若决定 accepted_candidate_change，candidate_update 必须实际改变对应声明。
只提交 {"candidate_update":{"id":"原 id","title":"原 title","setup":"...","conflict":"...","turn":"...","peak":"...","aftermath":"...","start_quote":"逐字复制原值","end_quote":"逐字复制原值","duration_seconds":90,"selection_reason":"..."},"feedback_responses":[{"feedback_index":0,"decision":"accepted_candidate_change","reason":"具体处理及依据"}]}。不要添加其他键。""",
    "writer_script": COMMON_RULES + """你是 MiniMax 编剧。本阶段先锁定故事节拍和对白，下一阶段才写可读剧本；不要在本阶段返回 screenplay_markdown。
根据已确定候选与导演前期意见，确定明确前因、冲突、峰值和收束；不要用镜头字段替代戏；不为凑时长重复动作。目标时长超过60秒时，把全片写成可累积的情绪阶梯：至少四个节拍必须带来新的事实、选择、代价或关系变化，且峰值前的每一步都使下一步更难撤回。连续15至20秒若没有上述任何增量，应压缩或重写；重复注视、沉默、走路和手部小动作本身不算新信息。结尾必须让观众看见角色如何承受或执行峰值后的结果，不能用空景、道具特写或一句主题字幕代替人物反应。决定性动作前的劝阻、犹豫和许可必须先发生，不能在签字、付款或离开之后才补上本应促成选择的表情。跨场景复用账本袋、证据袋、衣物等关系道具时，写清谁从上一空间带走、在新空间放到哪里；不能让只在旧场景建立的固定位置随切镜搬到新场景。涉及合同、收据、证据和登记材料时还要符合普通业务物理常识：双方副本应是预先准备并分别签章的完整文本，不能靠签后撕开一份合同制造甲乙方副本；资料袋用于随身保管时，办理窗口只取出并递交所需复印件或材料，人物继续保留袋子，除非剧情明确要求把容器本身作为证物移交。
先把 candidate_lock 的 setup、conflict、turn、peak、aftermath 分别拆成事件清单，并保证每项来源事件都进入实际 beat 的 before/during/after 或有依据的 dialogue。不得只检查高潮和结尾。候选写“坐下与他谈音乐会”时，不能因为原文是间接叙述就把整段谈话删除，再让对方无前因地直接评价音乐会；若 creative_focus 允许连续原文旁白，就用该段逐字旁白建立告知事件并配中性手势，仍不得杜撰安妮的具体台词。
把自己当作没有读过 creative_focus、candidate_lock 或简介的陌生观众，按最终会播出的对白与动作阅读前两拍：核心退让、拒绝、误会或决定的具体前因是否能被听见或看见？若“上次失败”“准备让位”等必要信息只写在焦点、premise、event 或 trigger 中，须把有依据的刺激放进实际的 before/during/after 或可说对白，再安排反应；不能靠一张必须读清的小字纸条、无声唇形或表演者自行脑补。小说改编不得因此新造原文没有的对白或事实；材料不足时要缩小候选的情绪主张，不把未建立的前因当作已演出。
程序把每一拍按固定顺序编成可读戏：before → 第一条 dialogue → during → 余下 dialogue → after。before 必须先完成第一句台词成立所需的可见刺激、递物或揭示；不能在第一句台词先说出物证/决定，而把举起物证、接住物品或作出决定写到 during 才发生。during 是第一句台词已经出口后的动作，不是可以倒放到台词前的说明；若要边做边说，把台词之前必须可见的起手动作写进 before，把台词中的推进写进 during。跨拍也按这个编译后的顺序检查，不能靠 event/trigger 标题声称动作已经演过。
原文若紧邻写成先轻笑、叹气或其他发声动作，再用冒号引出第一句对白，发声动作必须完整写在 before；单条 dialogue 的 during 已在整句对白之后，绝不能把先笑后说写进 during。比如“嘴里发出一声轻笑：对白”必须是 before 轻笑 → dialogue，不是 dialogue → during 轻笑。
同一人物的一条原文长对白若需要在前半与关键问句之间插入听者反应，必须在原文已有标点处分成同一 speaker 的两条相邻 dialogue；两条 text 按顺序拼接后必须逐字等于原句，不能删字、换字、补字或改标点。把轻微反应写在 during，把关键问句后的决定写在 after。不得在 during 中用“某人说到前段时”“说完某句后”或引号回抄对白来模拟台词内部时序，因为程序实际会在整条第一句结束后才播放 during。
输入的 candidate_lock 是已选故事版本。它的 aftermath 必须在最后一或最后两个节拍里以可见行动兑现；不能在 peak 后提前结束。输出前逐字阅读最后一拍的 event 与 after：若只到发现线索、人物停住或尚未说话，而 candidate_lock.aftermath 还有关系决定和共同动作，就必须继续补齐节拍；只在 premise 声称完成不算。若总时长有限，压缩前面重复的动作，不删除结局。最后一拍不能只有离场或空位，除非 candidate_lock.aftermath 本来就是这个结果。
实际节拍只能使用 selected_source 内的故事事实。选段前的走入、到场、坐下以及只在选段前出现的仙石、芝兰、车辆、家具等场景物件，和选段后的吃饭、离场、关系解释，即使能在完整 materials 里找到，也不能作为当前动作、主物、背景锚点、承载面、环境声、视线目标或人物动机带入；“制作选择”只能补不改变故事边界的摄影和中性表演，不能绕过选段锁。原文和 creative_focus 没有身体吸引、打量或相关刺激时，不能让人物视线落向胸前、领口、衣扣、大腿或嘴唇来替代真实因果；只使用面部、手部或来源支持的关键物作为凝视目标。
creative_focus 若锁定人物全程前行、不停止或脚步不停，任何节拍都不能把情绪停顿写成脚步微顿、停步、驻足或没有重新迈步；用眉眼、呼吸、手指和语气表现思考，同时明确脚步保持连续。
只输出一个 JSON 对象；每个键只出现一次，尤其整个对象只能有一个 beats 数组，不要在数组末尾另起 beats。JSON 字符串内部禁止使用英文双引号字符，引用文字改用无引号叙述；对白内容若必须有引号，使用 JSON 标准反斜杠转义。写完后检查首尾花括号、逗号和引号成对，确保可由标准 JSON 解析器读取。
节拍字段写短句，避免在 event、trigger、before、during、after 五处重复同一动作；before、during、after 也不得用简体转换、近义概述或“某人说出某句含义”的方式复述 dialogue，动作字段只写观众可见的表情、视线、站位和物理动作。“用朴素语气逐字说出那句肯定”仍是在 dialogue 之外重复表演台词，不能写入 during；对白前的对视放 before，对白后的听者反应放 during/after。先保证因果与人物动作准确，再由下一阶段扩写表演。
before、during、after 中也不得为了说明来源、制作边界或语气而把 dialogue 的单字、短句或长句放进中英文引号；来源说明留在 analysis、candidate_lock 和审核记录。程序会按固定顺序插入 dialogue，引号内再写一次会变成重复说话。
固定编译顺序只有 before → 第一条 dialogue → during → 其余 dialogue → after。before 不得写“听到本拍问话后”之类第一句尚未播放才会发生的反应；有两句以上对白时，during 也不得写后续说话人已经“答出、说完”，因为该对白此时尚未播放。after 已位于本拍全部 dialogue 之后，不能再写听者“等待这句回应”或后续说话人“准备开口”，否则回答会被重复或倒置。若两句对白是学生“可以抄一点。”、老师“拿来我看！”，老师的请求是第二句，伸手等待、学生递出、老师接住都必须写在 after；during 只能写第一句回答后的停顿或视线，不能提前完成第二句才触发的交付。若动作必须发生在第三句前而 during 已位于第一句后，应拆成相邻节拍，不能把动作偷放到请求之前。
逐拍跟踪因果性关键道具第一次出现、谁持有、何时放下和下一拍起始位置；同一拍的 before 与 after 若把同一人物写在不同位置，during 或相邻动作必须写出走位，不能从桌侧直接变到门边。相邻拍也必须把前拍 after 与后拍 before 逐人对齐；除非后拍明确开始新的时间或场景，人物不能在切点从桌侧瞬移到门边，修一拍结尾时要同步检查下一拍开头。若某件道具将触发人物决定，必须先在可见动作中建立它，不能只在后拍的 trigger 宣称它已经在手里。普通随身或桌内物品不承担前置因果时，可在首次使用的同一连续动作中从明确储存位置取出，不需要在情绪刺激前另设展示动作。来源明确的物品类型和材质不能凭翻译习惯改换；例如英文 slate 是写字石板，不能写成沿木纹裂开的木板，木质边框也不等于板面是木材。人物台词提到未来、别处或规则中的物体，不证明当前场景有该物体；例如研究室里说“以后照黑板上那样画”，不能在讲义下方凭空添加黑板范图。按实际表演顺序逐一计算取物、走位、装盒、关盖、离场等物理动作，不能把多步动作塞进短镜头后用“同时”或切镜掩盖。转折优先用人物会自然采取的直接动作；无理由把食物倒回锅再装盒等绕路操作，应在剧本阶段删简。
若原文给出连续空间动作，先列出每个位置变化再分拍，例如停在桥前 → 欠身上桥头 → 走到桥中 → 左右观看；每个承上启下动作必须在一个 before/during/after 中完整出现且只出现一次，不能从桥前直接跳到桥中，也不能前拍已完成过桥、后拍又从桥前重新起步。结尾含“动作/笑声 → 台词 → 他人反应”时严格保持三段先后；他人围拢、接物或离开不能与触发它的台词同时提前发生。
保持 creative_focus 中决定人物关系的动作和交接方向：如果原焦点是甲递稳、乙主动接住，不能在返修时悄悄改成乙独自从桌上拿起；确需改动时应先把改动作为候选层的明确选择，不可只在后段删掉交付者。不同节拍必须增加可见信息或决定，避免前半片长时间重复看同一纸条或道具，而把自主行动全部挤到结尾。手写文字和无声唇形可作辅助细节，不能承担观众必须逐字读懂的唯一叙事信息。
格式示例只示意字段，不是本稿时长模板：{"title":"...","premise":"...","selected_candidate_id":"C01","duration_seconds":37,
"beats":[{"id":"B01","duration_seconds":12,"event":"...","trigger":"...","before":"...","during":"...","after":"...","dialogue":[]},
{"id":"B02","duration_seconds":25,"event":"...","trigger":"...","before":"...","during":"...","after":"...","dialogue":[{"speaker":"角色名","text":"原文对白"}]}]}。
每个 beat 的 after 必须写清刺激和行动造成的可见结果或关系变化，不要只写泛泛的情绪形容词；下一 beat 的 trigger 应接上前段结果。若 after 明确写角色“跨不出、没有走、拒绝、未接住”等行动结果，下一拍不能无新刺激或新决定就写成“跨出、离开、接受、接住”；先安排可见的转变，或删去前拍过度绝对的结果。不需要单独的 consequence 字段。对白只放在 dialogue；before、during、after 不能再写出同一句台词，也不能把“边跑边喊”的对白放在动作发生之前。
如果故事靠误会反转，反转时给出能排除原误读的可见证据；“整理得整齐”“沉默”这类两种解释都成立的动作不能单独当作真相证明。角色听到对方表达痛苦或拒绝后，下一行动应有对方主动接受或允许的可见依据，不靠编剧替角色宣称被治愈。
剧本总时长由所有 beats.duration_seconds 算术相加，绝不能沿用候选的估计时长或上面示例数字；若节拍合计100秒，duration_seconds就写100。模型应在输出前核算一次。
先按每节拍实际对白长度估算说话时间，再为看见刺激、说话人表情和听者反应留时间。程序使用跨语言计时单位：中日韩文字每字 1 单位，拉丁字母等按词计且每词 2 单位；单拍硬上限为每秒 4.5 单位，整片对白总量不得超过总节拍秒数的 3.5 倍，否则没有足够表演留白。对白中的连续波浪号、连续省略号等拖长标记也表示慢速演唱、吟诵或犹豫，必须按慢速表演留出额外时间，不能只按文字数量估算。长篇诗歌或山歌只选原文连续的一小句，不要把整首歌和整段古文当作必说对白，也不能删去中间几句后把两端拼成一句。不要把候选总时长平均分配给每一拍：对白很长的节拍不能与无对白节拍同长；逐拍检查对白量、说话时间和反应时间，再计算总时长。时长不够就延长总片或在不扭曲原意的前提下删选整句原文，不能把多个长句压缩成新台词。
beats.dialogue 中的每一条必须恰有 speaker 和 text 两个键，text 必须是非空、实际会被说出的台词。不要使用 amount、content、line 等别名，也不要返回空 text；如果某节拍无人说话，dialogue 写空数组 []。原创视频驱动可以原创对白，小说驱动必须逐字保留已获取原文对白。
写涉及借、还、递、收、给、拿或亲属称谓的对白时，逐句核对说话人、提供者、接受者和物品；对白的通常语义必须与随后可见行动同向。若一句话会让观众以为出借者和借入者颠倒，原创故事要改写该句，小说改编则保留原文并用有依据的动作交代，不靠导演稿事后解释。角色不能只为迫使对方做出温情回应而无理由地淋雨、摔物、离场或承受其他代价。
对白必须按原文先后顺序列在 beats.dialogue。小说输入的 source_dialogue_inventory 是原文逐字引文及邻近上下文：把其中 Q 编号当作原文顺序，选用的 Q 项必须按编号递增映射到 beats.dialogue；candidate_lock 或简介里的概括不能覆盖这个顺序。只取实际说出的台词，石碣文字等题字不是对白；“告诉、叮嘱、表示、答应”等间接叙述也不是直接对白，不能把叙述内容加称呼后交给角色说。若允许用原文字幕或旁白呈现间接叙述，画面只配中性互动、视线和接收反应，不写“可读口型”，也不要求观众唇读不存在的台词。creative_focus 若明确要求观众知道一段包含姓名或具体内容的内心叙述，而面部动作无法传达该名字，就使用 selected_source 内逐字连续的原文旁白/画外心声，或退回候选取消这项承诺；不得让同伴或人群新说一句带该姓名的提示。原文只写“口头答应着”而没有答应的逐字内容时，也用这段原文叙述的旁白/字幕配合点头等中性反应；不得写成“嘴动但没有出声”，也不得杜撰“好”“我知道了”。说明紧邻一句对白是安慰、谎话或内心决定的原文叙述，可以放在该句之前、同时或紧接之后作为反思揭示；只要没有改变事件顺序和人物因果，不要机械强制它必须先于对白。可删去整句，或在不扭曲语义时选原文连续短句，不能把相邻两句合并成新对白。原文若是繁体，照抄繁体，不转简体、不改字词和标点。不要把非连续原文的内心叙述改成画外心声，优先让动作与表情承担；若确实使用画外心声，它也须是原文连续逐字引文并列入 beats.dialogue。小说原文未出现的对白不要新写。重复台词或动作若承担情绪反转，前段必须实际出现，后段才可作为重复刺激；结尾须由可见行动兑现人物变化。关键反应的时长应由内容决定。""",
    "writer_screenplay": COMMON_RULES + """你是 MiniMax 编剧。本阶段把已校验的 beat_lock 写成完整、可连续阅读的动作剧本；对白由程序从 beat_lock 逐字插入，你只负责相邻的动作和表演段落。
只返回合法 JSON：{"beat_scenes":[{"beat_id":"B01","action_segments":["对白前的连续动作文字","第一句对白后的连续动作文字"]}]}。
输入的 beat_scene_required_shape 已经逐节拍给出 action_segment_count，不要自己心算或把有对白的节拍也写成单段；按该清单逐项填满，再检查每项段数。每个 beat_scenes 元素严格只有 beat_id、action_segments 两个键；不要添加 dialogue 或额外键。
beat_scenes 必须与 beat_lock.beats 数量、ID、顺序完全相同，不能增添片尾节拍或结尾对白。每个 beat 的 action_segments 数量必须严格等于本 beat 对白句数加一：一段放在第一句对白前，每两句对白之间各一段，最后一段放在最后一句对白后；无对白 beat 只有一段。所有段落写成可阅读的戏剧动作，不要罗列字段或复制 beat 摘要；给出空间锚点、可见微表演和关键刺激前后的时间感。不要在动作段写任何实际说出的字词、引号里的发言、角色台词行或画外心声，也不要使用中英文引号，尤其不能在段外补一句收束对白。事件、人物关系、结果和时长以 beat_lock 为准；结尾行动必须兑现前面的关系变化，不新增未确认的原著事实。""",
    "director_shots": COMMON_RULES + """你是 DeepSeek 导演。保持编剧定稿事件、对白和顺序，不写新的剧情。先把参考片的表达机制转换成当前故事的镜头函数：建立阶段清楚交代关系，上升阶段逐步改变空间或构图权力，转折阶段提高信息密度并靠近关键反应，峰值给刺激与反应足够时间，余波回到人物承担结果。目标时长超过60秒时，原则上至少出现三次可感知的视觉状态变化；若故事必须单场景，则以光线、景别、人物距离、遮挡和支配位置的组合变化替代，并说明每次变化传达的新信息。不能把多镜头、运镜或特写数量本身当作丰富度。
若 creative_focus 或 style.character_lock 锁定人物全程前行、不停止或脚步不停，分镜的 composition、visible_performance、start_state、end_state 和 prompt 都必须保持脚步连续；情绪上的迟疑用眉眼、呼吸、手部或语气表现，不能擅自改成脚步微顿、停步、驻足或没有重新迈步。
每个镜头的 start_state 只描述该镜第一帧已经成立的静态状态，必须从上一镜 end_state 连续承接；不得把“走向、抵达、停下、抬手、接触”等本镜未来动作路径提前塞进 start_state，再在 visible_performance 重演。跨镜的新移动只写入 visible_performance，end_state 只写动作完成后的末帧。
creative_focus 若为某拍明确写出对白落音后的反应窗口，例如一到两秒，分镜不得把该拍对白后的独立无对白镜扩成更长时段；剩余拍长应分配给对白前刺激、说话过程或有信息增量的动作，不能靠长时间静止收束凑满。
在拆镜前先按 screenplay_markdown 的实际顺序阅读编剧稿：每拍 before → 第一条对白 → during → 后续对白 → after。对照 candidate_lock.aftermath、selected_source 与相邻节拍，检查关键刺激是否先于解释、行为结果是否无故翻转、候选结局是否由可见行动完成。若存在不改编剧稿就无法忠实拍摄的 blocking/major 剧情问题，本次只返回 {"story_issues":[{"owner":"writer","location":"B编号或选段位置","evidence":"引用当前剧本的具体矛盾","impact":"观众会看到的后果","proposal":"编剧应怎样修","severity":"blocking或major"}]}，不要同时返回 style/shots，不要擅自在镜头里补剧情。普通画风偏好、可由机位解决的镜头问题不算编剧问题；没有这类主要问题时直接返回下面的正常分镜对象，不输出空 story_issues。这个分流是导演原有分镜阶段的一部分，不是第三审核模型。
不仅核对 aftermath；还要把 candidate_lock 的 setup、conflict、turn、peak、aftermath 各自拆成来源事件，逐项定位到可读剧本。候选若写安妮先向马修谈音乐会，而剧本只让安妮沉默坐下、以嘴唇微动假装讲述、马修随后直接评价音乐会，属于缺少可听前因的 writer major；原文是间接叙述时只能建议使用获准的连续原文旁白与中性手势，不能补造具体对话。
若关键刺激只存在于“告诉、叮嘱、表示”等间接叙述，不能建议把叙述逐字改成人物台词，也不能新加“是”“好”等回应。若原文连续旁白、字幕和有依据动作均被 creative_focus 禁止，proposal 必须写“退回候选层”或“修改候选呈现约束”，让程序停在上游；不能用局部节拍返修反复生成无来源对白。
若间接叙述已由允许的原文字幕或旁白呈现，人物用转身、前倾、视线与听者反应建立交互即可；不得要求“可读口型”来补不存在的直接对白，也不能仅因没有听见具体词句就判定事件未发生。说明紧邻一句对白是安慰、谎话或内心决定的原文叙述，可作为该句之前、同时或紧接之后的反思揭示；只要因果未被改写，不要机械要求字幕一定先出现。
另以完全不知道焦点和候选简介的观众视角核对：剧本前段是否实际让人理解角色为何退让、犹豫或求助，以及同伴为何做出本片关键回应？若必需的前因只存在于 creative_focus、premise、event、trigger 或不可可靠辨认的小字/无声唇形中，属于编剧的上游主要问题；退回编剧建立可见或可听的刺激，不用镜头 purpose、特写和提示词替他补故事。
如果承担因果的决定性道具在剧本中没有首次拿取或放置动作，或必拍转折包含过多无法在规定节拍时间内完成的物理步骤，应作为上游 major 的 story_issues 退给编剧；增加机位与切镜不会延长节拍时间。普通随身或桌内物品若不触发前置决定，可在首次使用镜头中从明确位置连续取出，不要把“必须更早展示”误列为故事问题。来源写明的物品类型和材质必须保持；英文 slate 是写字石板，不得在 style、visible_performance 或 prompt 中改成旧木板、木纹板面或木材断裂。对白提到未来或别处的物体不等于当前空间已经存在，例如研究室里的“以后照黑板上那样画”只能靠台词与抬眼成立，不能在桌上或讲义下方增加黑板范图。镜头内每一次走位、拿取、开合、递接和回望都要分配可见时间，关键反应不能只写在 start_state 或 end_state 而没有镜内过程。
原文明写“递给、交给、接过”时，给予者伸出并由接收者抬手接住已经能完成交接；除非 creative_focus 明确要求犹豫、许可或拒绝，不得额外要求双方先对视、颔首或作出新的同意动作。
拆镜前把每拍动作写成有先后的物理步骤并估时：穿越障碍、落地稳定、确认环境、转头观察、重新起步都算独立信息。若 10 秒镜头堆入五到七个这类步骤，或既要长距离移动又要停顿反应，必须拆镜并重新分配节拍时长；若原 beat 总时长仍容不下，就退回编剧调整，不能用一句带多个分号的 visible_performance 假装可执行。原文中的桥前、桥头、桥中等空间节点必须逐步建立，不能跳过中间位置。
还要比较创作焦点、候选 setup/turn/peak 与剧本实际交接方向；若焦点的“他递稳、她接走”变成“她从桌上独自取走”，且这一交付动作承担关系变化，就应退回编剧，不能用机位补救。精确汉字道具特写和无声唇读不能成为观众理解核心因果的唯一途径。
按每个 beat 设计可执行的镜头，数量由戏剧需要决定；说明观众先看哪里，镜内动作顺序，重要表情在本机位是否可见。dialogue_lock 只能分配该 beat 的逐字对白，不额外加画外心声。逐镜按本镜实际对白量和速度估时；中日韩文字按字，英文等拉丁文本按词而不是按字母或字符计算，每个英文词约 2 个计时单位。若写“一字一顿”、停顿、听者抬手或说完后移动，就必须在该镜给足时间，不能把同一 beat 的无对白时长借给已说完的上一镜。
character_lock 必须写确定人数，不能写“四到六名”或“4-6 人”这类范围。对跨镜承担动作的前景人物逐个给稳定标识，至少锁定其园门远近或站位、发型/服装中的一个可见特征及所持道具；原文没写的外观明确作为制作选择，不能冒充来源事实。同一镜 composition 写两个孩子时，visible_performance 不能让未入画的第三个孩子承担关键动作。使用“最近那个”“最靠近园门的孩子”等相对称谓前，必须先建立并持续保持对应站位，不能在后镜把同一道具和动作悄悄换给另一个匿名人物。
逐条服从 creative_focus 中“不新增、不得、避免、不可、不猜”等否定约束；不能因为某个位置或回应便于构图就自行补上。原文和 creative_focus 没有身体吸引、打量或相关刺激时，分镜不得新增视线扫向胸前、领口、衣扣、大腿或嘴唇；只能沿用剧本中有来源依据的面部、手部或关键物反应。来源只写 sending up notes 时不能擅自断言人物在前排；确需确定生成用站位时，把它明确列为非冲突制作选择，并避开焦点已禁止的具体推断。
控制 JSON 体积：除逐字锁字段外，每个镜头的 purpose、composition、camera、visible_performance、start_state、end_state、cut_reason、prompt 各用一至两句具体短句；同一事件、构图和动作顺序不要在多个字段重复解释。精简文字不能省略人物位置、手部/道具状态、对白锁、秒数或连续性模式。
返回 {"style":{"style_option_id":"S01","visual_medium":"...","palette":"...","spatial_layout":"...","character_lock":"...","light_source":"..."},
"shots":[{"id":"SH01","beat_id":"B01","duration_seconds":8,"purpose":"...","composition":"...","camera":"...",
"visible_performance":"...","event_lock":"逐字复制对应beat的event","dialogue_lock":[{"speaker":"...","text":"本镜实际说出的原文对白"}],
"start_state":"...","end_state":"...","cut_reason":"...","dialogue_mode":"画内/画外/无对白",
"continuity_mode":"raw_tail_continuation 或 planned_cut_requires_adapter","prompt":"不新增剧情的画面提示词","production_choices":["..."]}],
"media_assumptions":["..."]}。每个 beat 至少对应一镜；新机位与换场标为 planned_cut_requires_adapter，不能假装原始尾帧自动完成切换。选择 raw_tail_continuation 时，本镜 start_state 必须逐字复制上一镜 end_state，不能只写语义相近的状态；若需要改变人物位置、机位或构图，就标记 planned_cut_requires_adapter。输出前检查全部相邻镜头。""",
    "writer_check": COMMON_RULES + """你是 MiniMax 编剧，核对 DeepSeek 导演稿是否保留已定的人物、事件、对白、刺激-反应时序及收束。你是现有编剧角色的交叉回核，不是独立第三审核模型。
先把 candidate_lock.aftermath 拆成必须让观众看见的决定、关系结果及行动，再逐项对照 script 最后一或最后两个节拍和对应收束镜。premise、候选简介、镜头 purpose 或结局道具特写里的声称不算兑现；若最后只写到线索、停顿或其中一人的反应，而候选还要求另一人的决定或共同行动，列为 writer 的 major，位置指向缺失的最终 beat。若剧本已有结局但分镜没有让观众看见，列为 director 的 major。“当面接受”只要求接受者在给予者面前作出可读接受，不自动要求给予者再颔首或新增确认动作；只有候选明确承诺双方确认、关系正式成立或共同决定时才要求另一人的新反应。不要靠新增原文没有的对白或心理动机补洞。校准阶段尤其要记录遗漏的具体结局动作，不能因事件名称相同就通过。
同样把 candidate_lock 的 setup、conflict、turn、peak 逐项拆成事件清单，定位到实际播放的动作或对白，不能只查 aftermath。原文写某人先向对方讲述某事、随后对方作出评价时，前一告知就是评价的直接前因；若剧本删掉告知，只剩沉默坐下后对方突然评价，列 writer major。间接叙述不是可以删除的事件：允许旁白时使用 selected_source 内连续逐字旁白配中性手势，不允许时应退回候选，不能补造具体对白。
实际阅读全文的编译顺序是每拍 before → 第一条 dialogue → during → 余下 dialogue → after。若人物先说“已经拓好了”等揭示台词，during 才举起能证明它的纸，不能因为 event 写了“举纸”就当观众已看见证据；这是编剧 major，须把必要刺激移到台词前，再重新检查镜头。有两句以上对白时，after 已在最后一句之后；若 after 仍写听者“等待这句回应”或最后说话人“准备开口”，列 writer major，不能把已经播放的回答审成尚未发生。动作字段把繁体原文转成简体、换成近义句，或写“某人说出某结论”再次概述已锁定 dialogue，同样属于编剧 major，不能把它当表演说明放过。跨拍若 after 已收手、软化，下一拍 before 不能无新刺激退回抬手质问。不要把上一镜 end_state 与下一镜 start_state 相同本身判作问题；连续镜头恰应从前镜终态起拍，问题在于后续动作是否重复、跳步或时长不足。前镜手指从红线起点移动到中段、后镜 start_state 逐字承接中段再移动到末端，是一次连续动作，不是重复起拍；只有后镜把手指重新放回起点或再次完成起点到中段才算重复。 start_state 只能是下一镜第一帧已经成立的状态；若它先写人物走向目标、抵达、停下并抬手接触，visible_performance 又从走向目标重新开始，列为 director major，不能把一整段动作路径当作起始状态。
原文若紧邻写明轻笑、叹气等发声动作之后才用冒号引出对白，检查该动作是否在 before；单条 dialogue 的 during 已经位于整句对白之后，把轻笑写入 during 会把“先笑后说”倒置，必须列 writer major。
逐句核对人物、称谓、物品交易方向和可见动作：谁提出、谁出借或交付、谁接受、谁归还；对白的通常理解与动作若相反或不清，列为 major 并退回编剧。检查角色每次退让、离开、淋雨、持物转移是否有自身动机，不能只是为了制造另一人的温情反应。检查同镜和相邻镜头的站位、间距、视线、手及道具状态；“肩并肩”与“隔半步”这类不能同时成立的描述要列问题。跨节拍也逐一核对：若前镜强调角色跨不出门槛、拒绝接物或无法离开，下一镜不能无新刺激或可见决定就直接跨出、接住或离开；不能仅把矛盾动作移到下一节拍当成修复。检查 analysis.characters.want 是否受其 source_quote 支持，不能把一次侧目当作“宣示主权”等确定动机。按本镜对白字数、说话方式和附带动作逐镜估时，特别核对“一字一顿”与实际镜头秒数；无对白反应镜的时间不能抵扣此前对白镜的说话时间。creative_focus 若明确某拍对白落音后只留一到两秒，逐镜相加该拍最后一句对白之后的独立无对白镜；超过上限就是 director major，不能把五秒静止镜审成一到两秒已满足。按整片时长核对每段是否增加新信息或关系变化；连续镜头只重复同一迟疑或接受状态而拖慢观感，也列为 major。同一 beat 的两句连续对白或同一回答的两部分可以分配到相邻镜头；只要 dialogue_lock 合并后的说话人、文字与顺序不变，中间没有提前发生本应在整段回答之后的决定或反应，就不能仅因切镜或自然停顿判为对白断裂，也不能强制合并成一镜。一个 after 可以同时容纳多个短促可见反应；不要仅因下一拍还有主角的后续行动，就要求把旁观者反应机械搬到下一拍。短促惊叫、三到五秒的教室过道移动和两到四秒的落手反应可以在八到十二秒内顺序成立；没有具体距离或步骤证据时，不得凭“收束要有重量”把十秒余波夸大成二十秒以上，也不得把 creative_focus 的“不要把大量动作堆到事后”反解为应让事后段占全片三分之一。即使事件和对白逐字保留，也须实际做这些语义检查。
检查 selected_style_id 对应的 medium 是否已经锁定一种可执行媒介；“实拍或高拟真三维”“二维/实拍”等仍把选择留给下游，列为 director major。shots.style 只需要用 style_option_id 引用该选择并以 visual_medium 写出单一媒介；不得因为 shots.style 没有契约外的 selected_style_id 字段而报问题，也不得建议新增该字段。检查 style.character_lock 是否给出确定人数和可跨镜识别的前景人物锚点。人数范围、只写“若干学生/服装统一”，或始终用“最近那个、另一个、最靠近门的那个”却没有固定站位、可见特征和道具归属，会让生成阶段换脸、换发色或把动作交给不同人物；列为 director major。同镜 composition 的人数与 visible_performance 的行动者数量不一致，也列为 director major。原文没写外貌时可以把稳定外观标为制作选择，不得把它说成原著事实。
把 creative_focus 中所有“不新增、不得、避免、不可、不猜”逐项列成检查清单，再对照剧本和分镜。若原文与焦点未建立身体吸引、打量或相关刺激，却新增视线落向胸前、领口、衣扣、大腿或嘴唇，列对应 owner 的 major；这种凝视会改写人物动机，不能作为普通微表情放过。即使新增内容看似日常或便于衔接，只要焦点明确禁止，仍列为对应 owner 的 major；例如焦点写“不猜成前排”，character_lock、composition 或 prompt 就不能把未知座位锁成前排。
若 creative_focus 锁定全程前行、不停止或脚步不停，要逐拍区分心理停顿与身体停步：思考一瞬、语气停顿可以成立，但脚步微顿、停步、驻足、没有重新迈步都列为对应 owner 的 major；不能用情绪合理性覆盖动作锁。
额外建立因果性关键道具清单，逐拍核对首次出现、取用者、手上位置、放下位置和下镜起始状态；触发人物转折的筷子、盒子等若此前未被建立，列为 writer major，不能因为后续镜头反复写“没动”就认为它已存在。普通随身或桌内物品若不承担前置因果，可在首次使用镜头里从明确储存位置连续取出；不要为此要求刺激发生前提前展示。还要逐项对照来源物品的类型和材质，不能把英文 slate 审成木板或让石板沿木纹裂开；边框材料不能替换板面材料。对白提到未来、别处或规则中的物体，不证明它在当前空间；“以后照黑板上那样画”不能被审成研究室桌上的黑板范图。判断道具是否瞬移时必须同时阅读 start_state、visible_performance 和 end_state；若 visible_performance 已写出从起点到终点的连续滑动、递接或拿取路线，不能只摘录首尾状态就声称路径缺失。对每个必拍动作按镜头秒数估算真实完成时间；若返修只是拆镜但仍在同样秒数里完成多步走位、装袋、拉链、回头和出门，继续列 major，不能为了完成两轮返修而清空问题单。
核对 creative_focus 与候选 setup/turn/peak 中承担情感关系的递接动作：若剧本或返修悄悄删除交付者，只留下接收者独自拿物，须判断是否改变“支持但不代替”的高光；改变了就列 writer major。按节拍计算观众获得新信息的间隔；若前半片大量秒数只是重复注视同一纸条、未见新的决定，却把主动行动全挤到结尾，应列节奏主要问题。不要用必须看清微小手写字或读懂无声唇形来代替可见行为因果。
用只听对白、只看可辨动作的陌生观众视角重新说出“他/她为何这样决定”；如果答案依赖模型输入中的背景说明或候选简介，而非成片里可听可见的前因，列 writer major 并指向缺失的开场节拍。不能用导演 purpose、画面提示词或无依据的小说新对白补足。
判断前因是否足够时先读当前台词本身：“以后不许再说”“还不道歉”“又忘了”“今日方知姓”“既然有姓”等回指性措辞已经向观众提供了前事类别或当前已成立状态，若本段冲突只需要知道这一级信息，不得为了复演完整前史而强行新增一句同义对白、道具牌或闪回。只有当前对白和可见动作都无法说明人物正在回应什么，才判定缺少直接诱因。
同理，“你们才说有本事进得来，出得去，不伤身体者，就拜他为王”已经同时说明先约、完成条件和当前索取承诺；若 creative_focus 本来从入洞后开始，不得再要求复演瀑布外立约或把两次进出都重演一遍。人物在逐字对白中回述已经完成的前段动作，当前冲突只需观众理解其主张时，不要求用闪回证明；只有故事明确质疑他是否说谎，才需要新的可见反证。
还要逐项查 selected_source 两端：若开头直接进入对白，剧本与分镜不得补入边界前的走入、到场或坐下；若结尾前已经收束，不能把边界后的吃饭、离场、关系解释变成环境声、视线目标或制作动机。把边界外事实标成 production choice 仍算越界。
小说改编的问题建议也受 selected_source 约束：proposal 不得新写原文没有的对白、照片、证件、手机界面、衣服价签、购物小票、回应声或其他剧情物证，不得建议取用选段边界之外的台词并谎称已在素材内。creative_focus 要求观众知道含姓名的内心叙述时，应建议使用 selected_source 中逐字连续的原文旁白/画外心声，或退回候选取消该承诺；绝不能建议 Jane、同学或人群新喊一句带该姓名的话。逐字内心旁白已经准确呈现态度时，可以同时配合抿唇、垂眼、视线停顿等与原文一致的轻微表情；只要表情没有抢在内心旁白前独立揭示具体事实、没有反转原意，就不能要求删光表情并让文字独占情绪。若唯一修法需要扩展选段或修改 candidate_lock，明确写“需上游选段/候选修订，不能由当前编剧或导演局部补写”，不要给出越界示例供下游照抄。
对白时长必须使用程序相同的跨语言单位：中日韩文字每字 1 单位，拉丁文本每词 2 单位；不得把英文句子的字母数、字符数或去空格长度当成中文“字数”，再据此要求无根据地扩拍。proposal 若声称英文对白超时，应写明词数、计时单位、镜头秒数和需要保留的具体动作。
原文中的间接叙述也不能由导演改判为人物直接对白。若关键刺激只有“告诉、叮嘱、表示”等叙述，没有引号内原话，story_issues 不得建议角色逐字说出该叙述或加一句“是”；若原文连续旁白、字幕和有依据动作均被 creative_focus 禁止，明确退回候选层，不要启动局部节拍返修。原文写“口头答应着”时，不能把“嘴动但没有出声”当成忠实表演；应使用该段原文叙述的旁白或字幕并配点头等中性反应，或者退回上游缩小叙事承诺，不能编造具体答应词。
若允许的原文字幕或旁白已经呈现“告诉、叮嘱、表示、答应”，配合人物朝向、距离变化和听者反应即可成立，不能要求可读口型或具体无声词句。说明紧邻对白是安慰、谎话或内心决定的原文叙述放在对白前、同时或紧接之后都可能是有效叙法；只有位置真的把前因改成后果或造成相反理解时才列 major。
不得把一个完整词语按单字分给不同人物或镜头来制造虚假的“多声递进”，也不得把原文只出现一次的称呼改成三次齐呼；群体 speaker、可见口型和同一声场已经可以证明齐声。叙述写“连呼三声、叫了几遍、再三催促”只锁定重复呼喊这一事件，不自动证明前一整句直接引语逐字重复了三遍；除非原文把重复内容逐次写出，后续呼喊可以用同一声场、呼声节奏和群体反应呈现，不能擅自复制长对白并挤坏时长。若结尾身份名称只存在于叙述，而 creative_focus 又禁止旁白、字幕和新增对白，应明确退回候选声明，收束到最后一个原文可见可听的关系结果；不得建议角色自说原文没有的称号，也不得用水墨字样、界面文字或道具偷渡该名称。
原文“住了身、定了神、仔细再看”等文学性动作概述，要按已经存在的可见状态变化判断：站稳或停止移动、呼吸与肩线恢复、目光有目的地扫视并定住，已经可以分别成立。不得为了逐字对应每个动词再强加跺脚、指桥、反复看两遍等原文没有的动作；只有剧本和分镜都缺少对应的可见变化时才列问题。
问题 owner 必须按实际修复层级填写：剧本缺事件、对白或动作先后，或剧本总时长超出 candidate_lock/creative_focus 的明确范围，需要改变 beat.duration_seconds，才归 writer；导演不能让镜头时长合计与对应 beat 不同来偷偷缩片。剧本已有完整动作且 beat 总时长足够，问题只需在同一拍内拆并镜、重新分配镜头秒数、编号、机位或画面可读性时归 director。proposal 若只写“拆 SH 镜头、合并 SH 镜头、延长或缩短 SH 秒数、重新编号”，不能标 writer；proposal 若要求全片或某拍增减总秒数，就必须标 writer 并指出要改的 beat。
按中文叙事惯例理解比喻与惯用语。“红脸白脸都由一人唱”“被玩弄于股掌之间”等首先描述角色在冲突中的立场切换和控制结果，不等于画面必须出现红色/白色脸、两种字面脸色、手掌特写或新增道具。只有原文或 candidate_lock 明确把字面视觉变化列为事件时，才要求对应的面部或道具证据。
对每个误会反转提出一个与表面证据同样成立的反向解释；如果剧本没有新证据排除它，标 major。对“我不敢看”“不要碰”等痛苦或拒绝之后的关怀动作，检查接收者是否有先犹豫后主动接住、点头或其他可见接受信号；没有就不能自行写成情感和解。检查收束镜是否真正显示人物关系变化，不能让关门、离场或道具特写代替人的最后反应。
但原文已经明确写出普通递交或接收时，不得为了“动机”再要求新增对视、颔首或许可；给予者伸出、接收者主动抬手并完成持物转移就是足够的连续行动。只有前拍明确拒绝、creative_focus 要求犹豫，或该接收本身代表新的关系决定时，才需要额外可见转变。
原文写一方握手、拥抱、扶住或按肩表达支持后，另一方随后必须起身、走开或完成别的动作时，自然松手只是物理连续性，不等于撤回支持、拒绝关系或削弱前一动作。不得要求接触一直保持到人物已走到另一位置，也不得为“保留余温”新增回握、再按一下或新的确认动作；只有原文明确写不肯松手、被挣脱或松手本身改变关系时，才把释放接触列为情绪问题。
逐字对照 selected_source 起止与剧本第一拍、最后一拍。source_scope_audit 若提示首句对白位置过晚，要实际阅读此前原文，判断是否跳过了完整事件或直接诱因；若确实遗漏，列为编剧 major，位置写 selected_source.start_quote，建议回到选段/节拍上游修订。不得把这项启发式提示本身当作定论；若前段已由可见动作充分交代，可在 calibration_focus 中说明依据。
视频原创候选中的手机文字、语音、当面告知等若只是在规定同一条信息的呈现渠道，剧本可在不改变说话人、事实、先后和人物决定的前提下改成更可听可见、且更符合 creative_focus 的渠道；不要把这种表达渠道优化误判为故事未保留。上一镜 end_state 与下一镜 start_state 完全相同是正常连续性；只有下一镜后续动作重复、跳步或没有信息增量才算问题。审核前逐字搜索被指控缺失的动作：若 visible_performance 已明确写工作人员接过身份证并开始登记，不得声称没有接过或没有登记。峰值镜若同时有对手走近、递文件、对白和主角反应，必须为主角在外部动作完成后保留至少一个独立可读反应阶段；不能把下颌收紧的一帧当成充分反应窗口。
最后按100分标尺复核并把分项与总分写入 calibration_focus：因果升级20、情绪递进20、视觉递进20、镜头信息密度15、峰值与反应可读性15、结尾后果10。总分低于80，或任一项低于该项满分的60%，必须产生对应 blocking/major issue，不能仅在 calibration_focus 里提醒后放行。评分必须引用 beat/shot 的实际证据；镜头多、运镜多、形容词多不能直接得分。若目标时长超过60秒，连续15至20秒没有新事实、选择、代价或关系变化，或全片没有至少三次有因果意义的视觉状态变化，视觉与信息密度不得判满。
本轮验收目标是参考片约八成的可用剧本，不是逐帧无瑕疵。blocking/major 只用于会使陌生观众误解因果、人物决定、情绪重心、道具归属，或使关键动作在物理上明显不可能、关键反应不可读的问题。单个手指在相邻镜的细小位置差、常规走廊步行秒数的一两秒估差、同一反应的自然眼神回落、在不改变人物和物权时普通手部起点未逐厘米交代，最多记 minor，不能阻止总分达到80。相同根因只能列一次：例如律师函递出后的独立反应不足，不得再分别以镜头交接、眼神预备、总时长核对重复列三项。先合并同源问题，再决定分数和是否返修。若总分已达80、各项达60%，且没有上述真正 blocking/major，story_preserved 必须为 true，issues 只可保留 minor 或为空，不得为了继续返修制造问题。
合同与证据场景额外按普通业务物理常识审核：签署后的甲乙方完整副本不能由撕开一份合同产生；随身资料袋若只是容器，窗口应接收从袋中取出的必要材料，人物仍保留袋子。此类错误改变物权或动作可信度，归 writer major；若剧本已经写对而只是分镜没拍清，才归 director。
只有实际发现的问题才写 issues，不要为通过而隐瞒，也不要把个人画风偏好当成剧情错误。
每条 issue 必须恰好包含 owner、location、evidence、impact、proposal、severity 六个键，每个键只出现一次；不得重复 impact 等字段，也不得增加其他键。location、evidence、impact、proposal 都必须填写非空具体文字；即使是 minor 也不能漏掉 impact。impact 写观众会看到或理解错什么，不能用空字符串或省略字段。JSON 字符串内部不要直接使用英文双引号；需要标示原文或字段词时改用中文引号，避免产生无法无歧义解析的响应。
返回 {"story_preserved":true,"issues":[{"owner":"writer 或 director","location":"beat/shot id","evidence":"具体依据",
"impact":"...","proposal":"...","severity":"blocking/major/minor"}],"calibration_focus":["..."]}。""",
    "writer_revise": COMMON_RULES + """你是 MiniMax 编剧。根据问题单修订已有完整剧本，不改变未受影响段落。
只返回 {"replace_beats":[{"beat_id":"B01","beat":本拍修订后的完整节拍对象}]}。replace_beats 的 beat_id、数量和顺序必须与 affected_beat_ids 完全相同；beat 内仍只含 id、duration_seconds、event、trigger、before、during、after、dialogue，且 beat.id 必须等于外层 beat_id。不要返回标题、premise、整份 beats、screenplay_markdown、writer_script、original、issues_resolved、来源证据或修改说明。程序会把局部节拍合并进 previous_script，重新计算总时长并按 before → 首句对白 → during → 其余对白 → after 编排可读剧本，再对完整稿重新校验。
问题若指出原结尾漏掉 selected_source 或 candidate_lock 已承诺的收束，而 affected_beat_ids 没有可新增的节拍编号，不得原样返回旧末拍，也不得声称新增 B08 等协议外节拍；把缺失的连续事件、逐字对白和反应折入最后一个 affected beat，并从其他受影响拍压缩非核心铺陈、重分时长。若问题位置写成 B01-B07 这类范围，affected_beat_ids 已展开为范围内每一拍，必须逐拍返回，不能只修两个端点。
任何返修都不得把“告诉、叮嘱、表示、答应”等间接叙述改造成角色直接对白，也不得为完成导演建议而添加原文没有的“是”“好”等回应。若问题的唯一解需要这样做，原样保留对白锁并明确问题属于候选层，不能用违规台词消耗下一轮。
逐拍按这个固定编译顺序检查实际观感：before 必定先于第一句 dialogue，during 必定在第一句 dialogue 之后，剩余 dialogue 再随后出现，最后才是 after。问题若要求人物先跳出再说“我進去”、先穿出瀑布再说“大造化”，对应跳出或穿出动作必须完整移到 before，并从 during 删除重复动作；问题若要求一句口令先触发众人行动，口令放第一句 dialogue，众人跟随动作才放 during。不能只改 event 标题或在 during 复述已经说过的台词来声称时序修复；把繁体台词转成简体、删几个字、换成近义概述，仍算复述，动作字段只保留可见表演。
原文若写成轻笑或叹气之后才引出对白，必须把该发声动作移入 before；不能让单条 dialogue 先播放，再在 during 补上本应先发生的笑声或叹气。
当请求或口令位于第二条 dialogue 时，during 仍在它之前，受请求触发的递出、接住、起身或离开只能放 after。典型例子是“可以抄一点。” → during 停顿 → “拿来我看！” → after 递出并接住讲义；不能连续两轮只改 during 的措辞却保持动作早于请求。
返修时逐字按编译顺序重读：before 不能预写听到本拍第一句之后的反应；during 不能写后续说话人已经答出、说完。before 与 after 若把同一人物放在不同位置，必须在 during 或相邻动作中写出走位；不能靠镜头切换把桌侧变成门边。修完受影响拍后还要把它的 after 与下一拍 before 逐人比较；没有明确时间/场景转场时必须完全承接，不能只修 B05 结束位置却把 B06 开头留在旧位置。
creative_focus 若锁定人物全程前行、不停止或脚步不停，返修不得把迟疑改成脚步微顿、停步、驻足或没有重新迈步；用眉眼、呼吸、手指和语气修情绪，同时让脚步保持连续。
一条原文长对白若需要中途插入听者反应，在原文已有标点处分成同一 speaker 的两条相邻 dialogue，按顺序拼接后逐字等于旧对白；during 位于第一条之后，after 位于其余对白之后。不得把“说到前段时”“说到某句时”“说完某句后”写进 during 代替结构拆分，也不得为拆分删字或改标点。
before、during、after 不能把任何 dialogue 单字、短句或长句放进中英文引号，即使目的是解释来源、停顿或制作边界；这些说明留在问题单和候选记录，动作字段只写可见表演。
修道具问题时先区分因果性关键道具与普通随身或桌内物品。前者必须在影响决定前建立；后者若不承担前置因果，可在首次使用时从明确储存位置连续取出，不得为了满足“预先建立”而把玩闹或展示提前到情绪刺激之前。
问题若涉及连续空间动作，按原文逐步修复桥前、桥头、桥中或门内、门槛、门外等节点，不得用“已到中间”替代首次跨入，也不得让相邻两拍重复同一次定位。结尾严格按触发顺序拆开：先完成笑声或起手动作，再说台词，台词结束后他人才围拢、接物或行动；不能把反应提前写进说话中的 during。
保留已确认来源、选段和画风约束；未受影响对白、人物关系和结局不动。问题单就是修订依据，无需另写修改说明。""",
    "writer_character_motivation_revise": COMMON_RULES + """你是 MiniMax 编剧，只修复已选人物的 want/fear 原著依据，不改人物姓名、source_quote、候选、选段、事件或对白。
输入含原文、旧分析、助手定位的问题与 target_characters。逐字阅读每个目标人物的 source_quote 和邻近正文；不要从一次侧目推断宣示主权、嫉妒或害怕竞争。无充分证据的心理动机降为可见行为与有限目标。只提交 {"character_updates":[{"name":"目标人物","want":"有来源支持的有限目标","fear":"有来源支持的担忧；原文未建立则明确写未证实","source_quote":"逐字复制旧引文"}]}，每个目标人物恰好一项，不添加其他人物，不修改引用文本。后续导演和剧本会在新分析的父版本上重审，不在本阶段改写。""",
    "writer_candidate_claims_revise": COMMON_RULES + """你是 MiniMax 编剧，只修复已选候选对本片事件的 setup/conflict/turn/peak/aftermath 描述及 selection_reason，不换故事、不改候选 id、title、start_quote、end_quote 或 duration_seconds。
输入含完整来源、旧分析、锁定候选、锁定 selected_source 和助手问题。候选每项承诺都必须能在锁定选段内由对白或可见动作实现；不能把 selected_source 结尾之后才发生的牵手、回宿舍或心理结论写进本片 peak/aftermath。删去越界承诺时，用选段内真实收束替代，不能让高潮只剩泛泛情绪。
只提交 {"candidate_update":{"id":"原 id","title":"原 title","setup":"...","conflict":"...","turn":"...","peak":"...","aftermath":"...","start_quote":"逐字复制原值","end_quote":"逐字复制原值","duration_seconds":90,"selection_reason":"更新后的选择理由"}}。后续导演方向、剧本、分镜和编剧回核会全部重审。""",
    "director_revise": COMMON_RULES + """你是 DeepSeek 导演。根据问题单局部修改分镜，剧本事件和对白保持不变。
只修输入 affected_beat_ids 中的节拍，不重复返回整份 style、未改镜头或 media_assumptions。返回 {"replace_beats":[{"beat_id":"B01","shots":[本拍修订后的完整镜头对象]}]}；replace_beats 的 beat_id、数量和顺序必须与 affected_beat_ids 完全相同，每拍 shots 须完整覆盖该拍。程序会把这些拍替换回 previous_shots，并对合并后的全片重新校验，未受影响镜头保持原版本。
script 是本轮有效编剧定稿：先逐镜按 beat_id 从 script.beats 重新逐字复制 event 到 event_lock，绝不能沿用旧事件文字；再按拍汇总替换镜头的 duration_seconds，须等于该 beat 的 duration_seconds；最后逐句核对替换镜头 dialogue_lock 合并后的说话人、文字与顺序，必须等于该 beat 的 dialogue。首个替换镜头的 start_state 与前一未改镜头终态、最后替换镜头的 end_state 与后一未改镜头起态也须连续；需要改变机位或构图时使用 planned_cut_requires_adapter。镜头若重新拆分，仍需完整覆盖并检查首尾状态。不能只把一个动作过密的镜头拆成两个，保持总秒数不变却声称节奏已经可演；应在本节拍内删去非必要动作，若编剧拍时长确实不足则不要伪造可演结果。不要输出修改说明或问题单。""",
}


def parse_json_object(text: str) -> dict[str, Any]:
    value = text.strip()
    if value.startswith("<think>"):
        end = value.find("</think>")
        if end < 0:
            raise CreativeContractError("模型思考段未闭合，正文不完整")
        value = value[end + len("</think>"):].strip()
    if value.startswith("```json"):
        value = value[7:]
    elif value.startswith("```"):
        value = value[3:]
    if value.endswith("```"):
        value = value[:-3]
    value = value.strip()
    try:
        result = json.loads(value)
    except json.JSONDecodeError as exc:
        raise CreativeContractError(
            f"模型未返回合法 JSON 对象: line={exc.lineno}, column={exc.colno}"
        ) from None
    if not isinstance(result, dict):
        raise CreativeContractError("模型必须返回 JSON 对象")
    return result


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CreativeContractError(f"{label} 必须为非空文字")
    return value.strip()


def _list(value: Any, label: str, *, minimum: int = 0) -> list[Any]:
    if not isinstance(value, list):
        raise CreativeContractError(f"{label} 必须为列表")
    if len(value) < minimum:
        raise CreativeContractError(f"{label} 至少需要 {minimum} 项")
    return value


def _duration(value: Any, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 600:
        raise CreativeContractError(f"{label} 必须为 0-600 秒正数")
    return float(value)


_DIALOGUE_DEPENDENT_BEFORE = re.compile(
    r"(?:听到|聽到|听见|聽見|听完|聽完).{0,8}"
    r"(?:问话|問話|询问|詢問|回答|要求|命令|这句话|這句話|那句话|那句話)|"
    r"(?:问话|問話|询问|詢問|回答|要求|命令|这句话|這句話|那句话|那句話)"
    r"(?:之后|之後|以后|以後|后|後)"
)
_COMPLETED_SPEECH = re.compile(
    r"(?:答出|回答了|回答完|说出|說出|说完|說完|喊出|喊完|念出|念完|问完|問完)"
)
_PENDING_PLAYED_SPEECH = re.compile(
    r"(?:等待|等着|等著).{0,10}(?:这句|這句|回答|回应|回應|答复|答覆)|"
    r"(?:准备|準備|将要|將要|即将|即將).{0,8}(?:开口|開口|回答|回应|回應|说话|說話)"
)
_UNLOCKED_SPEECH_ACTION = re.compile(
    r"(?:嘴唇|嘴巴|口型|开口|開口|张口|張口).{0,24}"
    r"(?:说出|說出|说起|說起|讲述|講述|谈起|談起|回答|回应|回應|念出|喊出)"
)
_STANDING_POSITION = re.compile(
    r"(?:^|[，。；;])\s*(?P<actor>[\u4e00-\u9fffA-Za-z·]{1,10}?)"
    r"(?:仍|还|還|已|正|安静地|安靜地)?站在(?:同一)?(?:研究室)?"
    r"(?P<place>门边一侧|門邊一側|桌面一侧|桌面一側|桌侧|桌側|桌边|桌邊|"
    r"桌前|桌后|桌後|门边|門邊|门口|門口|窗边|窗邊|墙边|牆邊|走廊)"
)
_POSITION_CHANGE = re.compile(
    r"(?:走到|走向|退到|移到|来到|來到|回到|转身|轉身|离开|離開|"
    r"靠近|绕到|繞到|站到|挪到|前移|后移|後移|迈步|邁步|走近|退回)"
)
_TIME_OR_SCENE_TRANSITION = re.compile(
    r"(?:转场|轉場|换场|換場|切到|来到另一|來到另一|同日稍后|同日稍後|"
    r"片刻后|片刻後|稍后|稍後|次日|翌日|第二天|隔天|"
    r"[一二三四五六七八九十两兩几幾数數\d]+(?:个|個)?(?:小时|小時|天|日|周|週|月|年)后|"
    r"[一二三四五六七八九十两兩几幾数數\d]+(?:个|個)?(?:小时|小時|天|日|周|週|月|年)後)"
)


def _speaker_aliases(speaker: str) -> set[str]:
    compact = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", speaker)
    aliases = {compact} if compact else set()
    for prefix in ("青年", "中年", "老年", "少年", "年轻", "年輕"):
        if compact.startswith(prefix) and len(compact) > len(prefix):
            aliases.add(compact[len(prefix):])
    if len(compact) >= 2:
        aliases.add(compact[-2:])
    return {item for item in aliases if item}


def is_narration_speaker(speaker: str) -> bool:
    """Recognize narration labels in the languages allowed by the authoring UI."""
    normalized = re.sub(r"[\s_-]+", "", str(speaker)).lower()
    return normalized in {"vo", "v.o.", "v.o"} or any(label in normalized for label in (
        "旁白", "叙述", "敘述", "解说", "解說", "画外", "畫外",
        "narrator", "narration", "voiceover",
    ))


def _standing_positions(text: str) -> dict[str, str]:
    return {
        match.group("actor"): (
            match.group("place")
            .replace("門", "门").replace("邊", "边").replace("側", "侧")
            .replace("後", "后")
        )
        for match in _STANDING_POSITION.finditer(text)
    }


def _unique_quote(source: str, quote: str, label: str) -> int:
    quote = _text(quote, label)
    if source.count(quote) != 1:
        raise CreativeContractError(f"{label} 在来源中必须唯一定位")
    return source.index(quote)


def _canonical_source_quote(source: str, quote: str, label: str) -> tuple[str, int]:
    """Recover exact source punctuation/line wrapping from a unique text anchor."""
    quote = _text(quote, label)
    if source.count(quote) == 1:
        return quote, source.index(quote)
    source_chars = [(index, char) for index, char in enumerate(source) if char.isalnum()]
    compact_source = "".join(char for _, char in source_chars)
    compact_quote = "".join(char for char in quote if char.isalnum())
    if len(compact_quote) < 8 or compact_source.count(compact_quote) != 1:
        raise CreativeContractError(f"{label} 在来源中必须唯一定位")
    compact_start = compact_source.index(compact_quote)
    start = source_chars[compact_start][0]
    end = source_chars[compact_start + len(compact_quote) - 1][0] + 1
    # Include only immediate trailing punctuation, not the next sentence's text.
    while end < len(source) and not source[end].isalnum() and not source[end].isspace():
        end += 1
    return source[start:end], start


def _dialogue_text(value: str) -> str:
    """Ignore edition line wrapping while preserving every non-space character."""
    return re.sub(r"\s+", "", value)


def _render_dialogue_text(value: str) -> str:
    """Remove source line wrapping without deleting meaningful Latin spaces."""
    value = value.strip()
    lines = [line.strip() for line in value.splitlines()]
    cjk_count = sum(
        0x3400 <= ord(character) <= 0x9FFF
        or 0xF900 <= ord(character) <= 0xFAFF
        or 0x3040 <= ord(character) <= 0x30FF
        or 0xAC00 <= ord(character) <= 0xD7AF
        for character in value
    )
    latin_count = sum(character.isascii() and character.isalpha() for character in value)
    return (" " if latin_count > cjk_count else "").join(lines)


def _validate_source_materials(source: str, production_text: str, label: str) -> None:
    """Reject a small set of explicit source-material contradictions."""
    if re.search(r"\bslates?\b", source, re.IGNORECASE) and any(
        marker in production_text for marker in ("木纹", "木板", "木质写字板")
    ):
        raise CreativeContractError(
            f"{label} 把原文 slate 改成木板或木纹断裂；"
            "写字石板可以有边框，但板面材质与裂开结果必须保持来源一致"
        )
    if "黑板上那样的画" in source and any(
        marker in production_text
        for marker in ("黑板范图", "讲义下方的黑板", "讲义下方黑板")
    ):
        raise CreativeContractError(
            f"{label} 把台词提到的未来黑板画变成研究室桌上的黑板范图；"
            "对白提及的物体不能在当前空间凭空出现"
        )
    if "口头答应着" in source and re.search(
        r"嘴.{0,8}(?:没有出声|无声|不出声)", production_text,
    ):
        raise CreativeContractError(
            f"{label} 把原文口头答应改成嘴动但没有出声；"
            "没有逐字直接引语时应用原文叙述旁白或字幕配中性反应"
        )


_SPEECH_REPORT_CUES = (
    "说出", "說出", "说道", "說道", "说着", "說著", "开口", "開口",
    "高叫", "喊出", "答道", "回答", "接话", "接話", "复述", "複述",
    "念出", "读出", "讀出", "朗声", "朗聲",
)


def _action_near_repeats_dialogue(action: str, spoken: str) -> bool:
    """Catch paraphrased speech in action prose, including common 繁/简 rewrites."""
    if not any(cue in action for cue in _SPEECH_REPORT_CUES):
        return False
    compact_action = "".join(char for char in action if char.isalnum())
    compact_spoken = "".join(
        char for char in _dialogue_text(spoken) if char.isalnum()
    )
    if len(compact_spoken) < 8 or len(compact_action) < 8:
        return False
    minimum = max(8, int(len(compact_spoken) * 0.7))
    maximum = min(len(compact_action), max(minimum, int(len(compact_spoken) * 1.2)))
    for width in range(minimum, maximum + 1):
        for start in range(0, len(compact_action) - width + 1):
            window = compact_action[start:start + width]
            if SequenceMatcher(None, compact_spoken, window).ratio() >= 0.6:
                return True
    return False


def _quoted_action_dialogue_matches(
    action: str, dialogue_lines: list[str],
) -> list[str]:
    """Return quoted action prose that repeats a dialogue line or its substring."""
    quoted: list[str] = []
    for pattern in (
        r'"([^"\r\n]+)"', r"'([^'\r\n]+)'", r"「([^」\r\n]+)」",
        r"『([^』\r\n]+)』", r"“([^”\r\n]+)”",
    ):
        quoted.extend(match.group(1) for match in re.finditer(pattern, action))
    spoken_values = [
        "".join(char for char in _dialogue_text(line) if char.isalnum())
        for line in dialogue_lines
    ]
    matches: list[str] = []
    for value in quoted:
        compact = "".join(char for char in _dialogue_text(value) if char.isalnum())
        if not compact:
            continue
        for spoken in spoken_values:
            if not spoken:
                continue
            if compact in spoken or spoken in compact:
                matches.append(value)
                break
            if len(compact) >= 4 and len(spoken) >= len(compact):
                # Short quoted paraphrases often differ in two simplified/traditional
                # glyphs (for example 进来/進來).  Requiring 0.75 would miss a
                # five-character quote with the same surrounding three characters.
                threshold = 0.6 if len(compact) <= 7 else 0.75
                if any(
                    SequenceMatcher(None, compact, spoken[start:start + len(compact)]).ratio()
                    >= threshold
                    for start in range(len(spoken) - len(compact) + 1)
                ):
                    matches.append(value)
                    break
    return matches


def _source_direct_quote_spans(source: str) -> list[tuple[int, int]]:
    """Return direct-speech ranges in the whitespace-normalized source."""
    normalized = _dialogue_text(source)
    spans = []
    for pattern in (r"「[^」]*」", r"『[^』]*』", r"“[^”]*”", r'"[^"\r\n]*"'):
        for match in re.finditer(pattern, normalized):
            prefix = normalized[max(0, match.start() - 48):match.start()].lower()
            if any(marker in prefix for marker in (
                "mottoonit", "verses", "poementitled", "title", "inscription",
                "cardwith", "labelled", "labeled", "signreading", "wroteonthe",
                "写着", "寫著", "题着", "題著", "题为", "題為", "字样", "字樣",
                "诗题", "詩題", "标题", "標題", "匾额", "匾額", "卡片上",
            )):
                continue
            spans.append((match.start() + 1, match.end() - 1))
    return sorted(spans)


def _find_direct_dialogue(
    source: str, spoken: str, cursor: int, direct_spans: list[tuple[int, int]],
) -> int:
    """Find the next matching occurrence that is actually inside direct speech."""
    position = source.find(spoken, cursor)
    while position >= 0:
        end = position + len(spoken)
        if any(position >= start and end <= stop for start, stop in direct_spans):
            return position
        position = source.find(spoken, position + 1)
    return -1


def _speech_units(value: str) -> int:
    """Estimate speech time across scripts without counting English by letter."""
    text = re.sub(r"\s+", " ", value).strip()

    def is_cjk(character: str) -> bool:
        codepoint = ord(character)
        return (
            0x3400 <= codepoint <= 0x4DBF
            or 0x4E00 <= codepoint <= 0x9FFF
            or 0xF900 <= codepoint <= 0xFAFF
            or 0x3040 <= codepoint <= 0x30FF
            or 0xAC00 <= codepoint <= 0xD7AF
        )

    cjk_units = sum(is_cjk(character) for character in text)
    non_cjk = "".join(" " if is_cjk(character) else character for character in text)
    word_units = 2 * len(re.findall(r"[^\W_]+(?:['’][^\W_]+)*", non_cjk, re.UNICODE))
    return cjk_units + word_units


def _claimed_spoken_character_counts(value: str) -> list[int]:
    """Read explicit Chinese claims such as ``只说出两个字`` from performance prose."""
    numeral_values = {
        "一": 1, "二": 2, "两": 2, "兩": 2, "三": 3, "四": 4,
        "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    }
    counts: list[int] = []
    patterns = (
        r"(?:仅|僅|只)?(?:发出|發出|说出|說出|吐出|喊出|说了|說了)"
        r".{0,8}?([一二两兩三四五六七八九十\d]+)个字",
        r"把.{0,4}?([一二两兩三四五六七八九十\d]+)个字"
        r".{0,12}?(?:挤出|擠出|说出|說出|吐出|喊出|发出|發出)",
    )
    for match in (
        match
        for pattern in patterns
        for match in re.finditer(pattern, value)
    ):
        numeral = match.group(1)
        if numeral.isdigit():
            counts.append(int(numeral))
        elif numeral in numeral_values:
            counts.append(numeral_values[numeral])
    return counts


def validate_candidate_embedded_dialogue_order(
    candidate: dict[str, Any], source: str,
) -> None:
    """Reject exact source dialogue quoted out of story order inside candidate claims."""
    normalized_source = _dialogue_text(source)
    direct_spans = _source_direct_quote_spans(source)
    evidence: list[tuple[int, str, str]] = []
    for field in ("setup", "conflict", "turn", "peak", "aftermath"):
        value = candidate.get(field)
        if not isinstance(value, str):
            continue
        quoted: list[tuple[int, str]] = []
        for pattern in (
            r'"([^"\r\n]+)"', r"'([^'\r\n]+)'", r"「([^」\r\n]+)」",
            r"『([^』\r\n]+)』", r"“([^”\r\n]+)”",
        ):
            quoted.extend(
                (match.start(), match.group(1)) for match in re.finditer(pattern, value)
            )
        for _, quote in sorted(quoted):
            normalized = _dialogue_text(quote)
            if not normalized or normalized_source.count(normalized) != 1:
                continue
            position = normalized_source.index(normalized)
            end = position + len(normalized)
            if any(position >= start and end <= stop for start, stop in direct_spans):
                evidence.append((position, field, quote))
    for previous, current in zip(evidence, evidence[1:]):
        if current[0] <= previous[0]:
            raise CreativeContractError(
                "候选故事声明中的逐字原文对白顺序倒置或重复: "
                f"{previous[1]}={previous[2][:32]} → {current[1]}={current[2][:32]}"
            )


def validate_candidate_duration(value: dict[str, Any], candidate: dict[str, Any]) -> None:
    """Keep the execution draft near the duration chosen during candidate selection."""
    expected = _duration(candidate.get("duration_seconds"), "candidate.duration_seconds")
    beats = _list(value.get("beats"), "beats", minimum=2)
    actual = sum(_duration(row.get("duration_seconds"), "beat.duration_seconds") for row in beats)
    tolerance = max(10.0, expected * 0.25)
    if abs(actual - expected) > tolerance:
        raise CreativeContractError(
            f"剧本节拍合计 {actual:g} 秒偏离候选 {expected:g} 秒，"
            f"允许误差 {tolerance:g} 秒；需保真删选对白或重新分配动作，不能静默扩成长片"
        )


def creative_focus_duration_range(creative_focus: str) -> tuple[float, float] | None:
    """Read an explicit duration range from the user-authored creative focus."""
    if not isinstance(creative_focus, str) or not creative_focus.strip():
        return None
    patterns = (
        r"(?:总时长|總時長|时长|時長|片长|片長)\s*"
        r"(\d+(?:\.\d+)?)\s*(?:到|至|[-–—~～])\s*(\d+(?:\.\d+)?)\s*秒",
        r"(?:total\s+)?duration\s*[:：]?\s*"
        r"(\d+(?:\.\d+)?)\s*(?:to|[-–—~])\s*(\d+(?:\.\d+)?)\s*"
        r"(?:seconds?|secs?|s)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, creative_focus, re.IGNORECASE)
        if not match:
            continue
        lower, upper = (float(match.group(1)), float(match.group(2)))
        if lower > upper:
            lower, upper = upper, lower
        if lower > 0 and upper <= 600:
            return lower, upper
    return None


def validate_creative_focus_duration(value: dict[str, Any], creative_focus: str) -> None:
    """Treat an explicit user duration range as a hard authoring boundary."""
    duration_range = creative_focus_duration_range(creative_focus)
    if duration_range is None:
        return
    lower, upper = duration_range
    beats = _list(value.get("beats"), "beats", minimum=2)
    actual = sum(_duration(row.get("duration_seconds"), "beat.duration_seconds") for row in beats)
    if actual < lower or actual > upper:
        raise CreativeContractError(
            f"剧本节拍合计 {actual:g} 秒超出 creative_focus 明确时长范围 "
            f"{lower:g}-{upper:g} 秒；这是编剧节拍层约束，不能只改分镜秒数"
        )


def _small_chinese_integer(text: str) -> int | None:
    """Parse the small integers commonly used in creative-focus beat ranges."""
    if text.isdigit():
        return int(text)
    digits = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if text == "十":
        return 10
    if "十" in text:
        left, right = text.split("十", 1)
        if left not in ("", *digits) or right not in ("", *digits):
            return None
        tens = 1 if not left else digits[left]
        ones = 0 if not right else digits[right]
        return tens * 10 + ones
    return digits.get(text)


def creative_focus_beat_range(creative_focus: str) -> tuple[int, int] | None:
    """Read an explicit beat-count range from the user-authored creative focus."""
    if not isinstance(creative_focus, str) or not creative_focus.strip():
        return None
    numeral = r"(?:\d+|[零一二两三四五六七八九十]+)"
    patterns = (
        rf"({numeral})\s*(?:到|至|[-–—~～])\s*({numeral})\s*(?:个|個)?\s*(?:节拍|節拍)",
        r"(\d+)\s*(?:to|[-–—~])\s*(\d+)\s*beats?\b",
    )
    for pattern in patterns:
        match = re.search(pattern, creative_focus, re.IGNORECASE)
        if not match:
            continue
        lower = _small_chinese_integer(match.group(1))
        upper = _small_chinese_integer(match.group(2))
        if lower is None or upper is None:
            continue
        if lower > upper:
            lower, upper = upper, lower
        if lower > 0 and upper <= 100:
            return lower, upper
    return None


def validate_creative_focus_beat_count(value: dict[str, Any], creative_focus: str) -> None:
    """Treat an explicit user beat-count range as a hard authoring boundary."""
    beat_range = creative_focus_beat_range(creative_focus)
    if beat_range is None:
        return
    lower, upper = beat_range
    actual = len(_list(value.get("beats"), "beats", minimum=2))
    if actual < lower or actual > upper:
        raise CreativeContractError(
            f"剧本共有 {actual} 个节拍，超出 creative_focus 明确节拍范围 "
            f"{lower}-{upper} 个；必须在编剧节拍层合并或拆分"
        )


_CONTINUOUS_MOVEMENT = re.compile(
    r"(?:始终|全程|一直).{0,12}(?:前行|行走|走动|走路|迈步)|"
    r"(?:不停步|不停下|不驻足)|"
    r"(?:脚步|步伐).{0,8}(?:不停|不止|保持)"
)
_MOVEMENT_WORD = re.compile(r"(?:前行|行走|走动|走路|迈步|脚步|步伐)")
_NO_STOP_WORD = re.compile(r"(?:不停止|不停步|不停下|不驻足|不要停|不能停)")
_PHYSICAL_STOP = re.compile(
    r"(?:脚步|步伐)[^，。；！？\n]{0,10}(?:停住|停下|停顿|微顿|顿住|一顿|仍然停)|"
    r"(?:停住|停下|顿住)[^，。；！？\n]{0,8}(?:脚步|步伐|身形|身体)|"
    r"(?:停在原地|驻足|没有[^，。；！？\n]{0,8}(?:重新)?迈步|"
    r"不再[^，。；！？\n]{0,8}(?:前行|迈步|行走))"
)


def _requires_continuous_movement(text: str) -> bool:
    """Recognize an explicit lock that a character must keep moving."""
    return bool(
        _CONTINUOUS_MOVEMENT.search(text)
        or (_MOVEMENT_WORD.search(text) and _NO_STOP_WORD.search(text))
    )


def validate_creative_focus_action_constraints(
    value: dict[str, Any], creative_focus: str,
) -> None:
    """Keep explicit continuous movement locks through every production action."""
    if not isinstance(creative_focus, str) or not _requires_continuous_movement(
        creative_focus
    ):
        return
    for row in _list(value.get("beats"), "beats", minimum=2):
        beat_id = _text(row.get("id"), "beat.id")
        action_text = " ".join(
            str(row.get(key, ""))
            for key in ("event", "trigger", "before", "during", "after")
        )
        conflict = _PHYSICAL_STOP.search(action_text)
        if conflict:
            raise CreativeContractError(
                f"{beat_id} 把 creative_focus 锁定的持续行走改成身体停步: "
                f"{conflict.group(0)}；情绪停顿只能用眼神、眉眼、呼吸或语气表现，"
                "脚步必须继续"
            )


def validate_summary(value: dict[str, Any], source_chunk: str) -> None:
    _text(value.get("summary"), "summary")
    for row in _list(value.get("events"), "events", minimum=1):
        for key in ("event", "cause", "consequence"):
            _text(row.get(key), key)
        start = _unique_quote(source_chunk, row.get("start_quote"), "start_quote")
        end = _unique_quote(source_chunk, row.get("end_quote"), "end_quote")
        if end < start:
            raise CreativeContractError("摘要事件起止顺序倒置")


def validate_reference_summary(value: dict[str, Any]) -> None:
    for key in ("expression_mechanisms", "excluded_story_elements", "limits"):
        for item in _list(value.get(key), key, minimum=1 if key == "expression_mechanisms" else 0):
            _text(item, key)


def validate_analysis(value: dict[str, Any], source: str, driver: str) -> dict[str, Any]:
    original = value
    value = deepcopy(value)
    _text(value.get("summary"), "summary")
    candidates = _list(value.get("candidates"), "candidates", minimum=1)
    reconciliations = list(value.get("format_reconciliations", []))
    if driver in {"reference_video", "original"}:
        misplaced_candidate_fields = (
            "setup", "conflict", "turn", "peak", "aftermath",
            "start_quote", "end_quote", "duration_seconds",
        )
        if (
            len(candidates) == 1
            and isinstance(candidates[0], dict)
            and set(candidates[0]) == {"id", "title"}
            and all(key in value for key in misplaced_candidate_fields)
            and isinstance(value.get("selection_reason"), str)
        ):
            # One candidate and no duplicate field values make this a pure
            # relocation of the model's existing content, not story repair.
            candidate = candidates[0]
            for key in misplaced_candidate_fields:
                candidate[key] = value.pop(key)
            candidate["selection_reason"] = value["selection_reason"]
            reconciliations.append({
                "candidate_id": candidate.get("id"),
                "repair": "lift_single_video_candidate_fields_from_top_level",
                "fields": [*misplaced_candidate_fields, "selection_reason"],
            })
        for row in candidates:
            nested = row.get("end_quote")
            if (isinstance(nested, dict)
                    and set(nested) == {"duration_seconds", "selection_reason"}
                    and "duration_seconds" not in row and "selection_reason" not in row
                    and row.get("start_quote") == ""):
                # The video-original contract requires empty source quotes. This
                # exact misplaced field pair can be lifted without changing text.
                row["duration_seconds"] = nested["duration_seconds"]
                row["selection_reason"] = nested["selection_reason"]
                row["end_quote"] = ""
                reconciliations.append({
                    "candidate_id": row.get("id"),
                    "repair": "lift_duration_and_reason_from_empty_video_end_quote",
                })
            misplaced = [
                key for key in ("start_quote", "end_quote")
                if isinstance(row.get(key), str) and row[key].strip()
            ]
            if misplaced:
                # An original video creates a new story. Preserve the raw model
                # response in the stage receipt, but never label its invented
                # opening/ending as a quote from the reference video.
                for key in misplaced:
                    row[key] = ""
                reconciliations.append({
                    "candidate_id": row.get("id"),
                    "repair": "clear_invented_original_video_source_quotes",
                    "fields": misplaced,
                })
    if len(candidates) > 3:
        raise CreativeContractError("候选数不能超过 3")
    selected = _text(value.get("selected_candidate_id"), "selected_candidate_id")
    ids: set[str] = set()
    valid_candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    candidate_source_spans: dict[str, tuple[int, int]] = {}
    for row in candidates:
        candidate_id = _text(row.get("id"), "candidate.id")
        if candidate_id in ids:
            raise CreativeContractError("候选 ID 重复")
        ids.add(candidate_id)
        try:
            for key in ("title", "setup", "conflict", "turn", "peak", "aftermath", "selection_reason"):
                _text(row.get(key), f"candidate.{key}")
            _duration(row.get("duration_seconds"), "candidate.duration_seconds")
            if driver == "novel":
                row["start_quote"], start = _canonical_source_quote(
                    source, row.get("start_quote"), "candidate.start_quote"
                )
                row["end_quote"], end = _canonical_source_quote(
                    source, row.get("end_quote"), "candidate.end_quote"
                )
                if end < start:
                    raise CreativeContractError("候选原文起止倒置")
                candidate_source_spans[candidate_id] = (
                    start, end + len(row["end_quote"]),
                )
                validate_candidate_embedded_dialogue_order(row, source)
            elif row.get("start_quote") or row.get("end_quote"):
                raise CreativeContractError("视频驱动原创候选不能冒充小说原文引文")
        except CreativeContractError as exc:
            if candidate_id == selected:
                raise
            rejected.append({"id": candidate_id, "candidate": row.copy(), "reason": str(exc)})
            continue
        valid_candidates.append(row)
    if selected not in {row["id"] for row in valid_candidates}:
        raise CreativeContractError("选中的候选不存在")
    if rejected and len(candidates) > 1 and len(valid_candidates) < 2:
        raise CreativeContractError("有效候选不足两个，不能声称完成候选比较")
    if rejected:
        value["rejected_candidates"] = rejected
        value["candidates"] = valid_candidates
    _text(value.get("selection_reason"), "selection_reason")
    _list(value.get("characters"), "characters")
    for index, row in enumerate(value["characters"]):
        _text(row.get("name"), "character.name")
        nested_want = row.get("want")
        if (
            driver in {"reference_video", "original"}
            and isinstance(nested_want, dict)
            and set(nested_want) == {"goal", "fear", "source_quote"}
            and all(isinstance(nested_want[key], str) for key in nested_want)
            and nested_want["goal"].strip()
            and "fear" not in row
            and "source_quote" not in row
        ):
            row["want"] = nested_want["goal"]
            row["fear"] = nested_want["fear"]
            row["source_quote"] = nested_want["source_quote"]
            reconciliations.append({
                "character_index": index,
                "repair": "lift_video_character_goal_fear_and_quote_from_nested_want",
            })
        _text(row.get("want"), "character.want")
        if driver in {"reference_video", "original"} and isinstance(row.get("source_quote"), str) and row["source_quote"].strip():
            row["source_quote"] = ""
            reconciliations.append({
                "character_index": index,
                "repair": "clear_invented_original_video_character_source_quote",
            })
        if driver == "novel" and row.get("source_quote"):
            label = f"characters[{index}].source_quote"
            try:
                row["source_quote"], _ = _canonical_source_quote(
                    source, row["source_quote"], label,
                )
            except CreativeContractError:
                selected_span = candidate_source_spans.get(selected)
                quote = row["source_quote"]
                occurrences = [
                    match.start() for match in re.finditer(re.escape(quote), source)
                ]
                scoped = [
                    position for position in occurrences
                    if selected_span is not None
                    and selected_span[0] <= position
                    and position + len(quote) <= selected_span[1]
                ]
                if len(scoped) != 1:
                    raise
            # Regression guard for a known source error: this description belongs
            # to 顾玉荣 in the obtained novel, not to 洛雪微.
            if (
                "女生身材高挑，穿着经典的衬衫短裙学妹装" in row["source_quote"]
                and row["name"] != "顾玉荣"
            ):
                raise CreativeContractError("已知原文人物外貌引文归属错误：该段描述顾玉荣")
    _list(value.get("reference_use"), "reference_use")
    if reconciliations:
        value["format_reconciliations"] = reconciliations
    original.clear()
    original.update(value)
    return next(row for row in original["candidates"] if row["id"] == selected)


def validate_director_brief(value: dict[str, Any]) -> None:
    options = _list(value.get("style_options"), "style_options", minimum=2)
    ids: set[str] = set()
    for row in options:
        style_id = _text(row.get("id"), "style.id")
        if style_id in ids:
            raise CreativeContractError("画风 ID 重复")
        ids.add(style_id)
        for key in ("medium", "palette", "performance_fit", "source_basis", "tradeoff"):
            _text(row.get(key), f"style.{key}")
    selected_style_id = _text(value.get("selected_style_id"), "selected_style_id")
    if selected_style_id not in ids:
        raise CreativeContractError("所选画风不在候选中")
    selected_medium = next(
        str(row["medium"]) for row in options if row["id"] == selected_style_id
    )
    live_action = bool(re.search(r"实拍|真人|live[ -]?action", selected_medium, re.I))
    animated = bool(re.search(r"二维|2d|三维|3d|动画|定格|stop[ -]?motion|cg", selected_medium, re.I))
    alternative_joiner = bool(re.search(r"(?:或|或者|/|／|\bor\b)", selected_medium, re.I))
    if live_action and animated and alternative_joiner:
        raise CreativeContractError(
            "所选画风 medium 必须锁定一种可执行媒介，不能保留实拍或动画/三维二选一"
        )
    for key in ("visual_strategy", "spatial_strategy", "performance_strategy"):
        _text(value.get(key), key)
    _list(value.get("feasibility_notes"), "feasibility_notes")
    writer_feedback = _list(value.get("writer_feedback"), "writer_feedback")
    for index, row in enumerate(writer_feedback):
        if not isinstance(row, dict) or set(row) != {"issue", "scope", "proposal"}:
            raise CreativeContractError(
                f"writer_feedback[{index}] 必须只包含 issue、scope、proposal"
            )
        issue = _text(row.get("issue"), f"writer_feedback[{index}].issue")
        _text(row.get("scope"), f"writer_feedback[{index}].scope")
        proposal = _text(row.get("proposal"), f"writer_feedback[{index}].proposal")
        if re.search(
            r"(?:无需|無需|不需)(?:修改|修改|调整|調整|延长|延長|前移|收窄|补充|補充|处理|處理|变更|變更|改动|改動)",
            f"{issue} {proposal}",
        ) or re.search(r"维持当前|維持當前|没有问题|沒有問題", proposal):
            raise CreativeContractError(
                f"writer_feedback[{index}] 是检查通过结论；无实际问题时必须省略该项"
            )
    scope = value.get("source_scope", {})
    if not isinstance(scope, dict):
        raise CreativeContractError("导演原文边界建议必须是对象")
    quote = scope.get("lead_in_start_quote", "")
    if not isinstance(quote, str):
        raise CreativeContractError("导演原文前移引文必须是字符串")
    trim_quote = scope.get("trim_start_quote", "")
    if not isinstance(trim_quote, str):
        raise CreativeContractError("导演收窄原文引文必须是字符串")
    extend_quote = scope.get("extend_end_quote", "")
    if not isinstance(extend_quote, str):
        raise CreativeContractError("导演延长原文终点引文必须是字符串")
    trim_end_quote = scope.get("trim_end_quote", "")
    if not isinstance(trim_end_quote, str):
        raise CreativeContractError("导演收窄原文终点引文必须是字符串")
    if quote and trim_quote:
        raise CreativeContractError("导演不能同时前移和收窄原文起点")
    if extend_quote and trim_end_quote:
        raise CreativeContractError("导演不能同时延长和收窄原文终点")
    if (quote or trim_quote or extend_quote or trim_end_quote) and (
        not isinstance(scope.get("reason"), str) or not scope["reason"].strip()
    ):
        raise CreativeContractError("导演调整原文边界必须说明因果理由")


_SLOW_PERFORMANCE_MARKERS = (
    "语速放稳", "语速放慢", "一字一顿", "缓慢说", "慢慢说",
    "短暂停顿", "明显停顿", "郑重", "哽咽", "抽泣",
)

# Conservative, visible outcomes that can be matched deterministically on both
# sides of omitted direct speech. This is intentionally narrower than general
# emotion vocabulary: a script may end before later source dialogue, but it may
# not skip that dialogue and then borrow the physical consequence after it.
_POST_DIALOGUE_OUTCOME_MARKERS = (
    "发抖", "發抖", "颤抖", "顫抖", "流泪", "流淚", "落泪", "落淚",
    "哭", "大笑", "笑出声", "笑出聲", "脸红", "臉紅", "脸色", "臉色",
    "低头", "低頭", "抬头", "抬頭", "点头", "點頭", "摇头", "搖頭",
    "转身", "轉身", "回头", "回頭", "离开", "離開", "跑开", "跑開",
    "逃走", "倒下", "跪下", "坐下", "站起", "停住", "沉默",
    "握住", "抱住", "拥抱", "擁抱", "接过", "接過", "放下",
    "开门", "開門", "关门", "關門",
)
_PHYSICAL_STEP_MARKERS = (
    "攀住", "跃下", "跳下", "落地", "屈膝", "撑地", "起身", "整衣",
    "上步", "站定", "拱手", "躬身", "抬眼", "转身", "侧身", "让开",
    "迈步", "抬足", "回头", "拿起", "放下", "递出", "接住", "打开",
    "关上", "穿过", "跨过", "走到", "握住", "取过", "抵进", "转动",
    "削出", "搁回", "拨齐", "叠成", "压平", "放回", "呼出",
)
_TRANSFER_REQUEST_MARKERS = (
    "拿来", "拿來", "给我", "給我", "交给我", "交給我", "递给我", "遞給我",
    "give me", "hand me", "pass me",
)
_TRANSFER_COMPLETION_MARKERS = (
    "递出", "遞出", "交出", "接住", "接过", "接過", "收下", "收到自己",
    "handed over", "hands over", "passed", "passes",
)

_UNSUPPORTED_BODY_GAZE = re.compile(
    r"(?:视线|目光|眼神)[^，。；！？\n]{0,12}"
    r"(?:落到|落在|移到|扫向|看向|盯着|盯住|钉在|釘在|钉住|釘住|"
    r"停在|掠过|投向|转向)"
    r"[^，。；！？\n]{0,6}(?<!上)(?:胸前|胸口|胸部|领口|衬衫扣|衣扣|乳房|乳沟|"
    r"大腿|双腿|嘴唇|唇瓣)",
)
_BODY_GAZE_TARGETS = (
    "胸前", "胸口", "胸部", "领口", "衬衫扣", "衣扣",
    "乳房", "乳沟", "大腿", "双腿", "嘴唇", "唇瓣",
)


def _validate_unsupported_body_gaze(text: str, source: str, label: str) -> None:
    unsupported_gaze = _UNSUPPORTED_BODY_GAZE.search(text)
    if unsupported_gaze and not any(marker in source for marker in _BODY_GAZE_TARGETS):
        raise CreativeContractError(
            f"{label} 新增了原文未支持的身体凝视目标: "
            f"{unsupported_gaze.group(0)[:40]}；视线应落在面部、手部或来源支持的关键物上"
        )


def _physical_step_count(text: str) -> int:
    return sum(text.count(marker) for marker in _PHYSICAL_STEP_MARKERS)


def _deliberate_slow_performance(text: str) -> bool:
    return any(marker in text for marker in _SLOW_PERFORMANCE_MARKERS)


def _dialogue_has_drawn_out_delivery(lines: list[str]) -> bool:
    """Treat explicit elongation marks as an instruction to slow delivery."""
    return any(
        re.search(r"(?:[~～]{2,}|…{2,}|\.{3,})", line)
        for line in lines
    )


def _unclosed_dialogue_quote(text: str) -> str | None:
    """Return an opening Chinese quote mark that the selected dialogue drops."""
    pairs = {"「": "」", "『": "』", "“": "”", "‘": "’"}
    closers = {closing: opening for opening, closing in pairs.items()}
    stack: list[str] = []
    for character in text:
        if character in pairs:
            stack.append(character)
        elif character in closers and stack and stack[-1] == closers[character]:
            stack.pop()
    return stack[-1] if stack else None


def validate_script(value: dict[str, Any], candidate_id: str, source: str, driver: str) -> None:
    _text(value.get("title"), "script.title")
    _text(value.get("premise"), "script.premise")
    if value.get("selected_candidate_id") != candidate_id:
        raise CreativeContractError("剧本换成了未经选择的候选")
    target = _duration(value.get("duration_seconds"), "script.duration_seconds")
    screenplay = _text(value.get("screenplay_markdown"), "screenplay_markdown")
    beats = _list(value.get("beats"), "beats", minimum=2)
    ids: set[str] = set()
    total = 0.0
    total_spoken_units = 0
    timing_issues: list[str] = []
    source_cursor = 0
    screenplay_cursor = 0
    source_dialogue = _dialogue_text(source)
    direct_source_spans = _source_direct_quote_spans(source)
    screenplay_dialogue = _dialogue_text(screenplay)
    expected_rendered_dialogue: list[str] = []
    selected_dialogue_text = ""
    used_direct_novel_dialogue = False
    production_text_parts = [screenplay]
    previous_beat_id = ""
    previous_after_positions: dict[str, str] = {}
    for row in beats:
        beat_id = _text(row.get("id"), "beat.id")
        if beat_id in ids:
            raise CreativeContractError("情绪节拍 ID 重复")
        ids.add(beat_id)
        beat_duration = _duration(row.get("duration_seconds"), f"{beat_id}.duration_seconds")
        total += beat_duration
        for key in ("event", "trigger", "before", "during", "after"):
            _text(row.get(key), f"{beat_id}.{key}")
            production_text_parts.append(str(row[key]))
        if driver == "novel":
            _validate_unsupported_body_gaze(
                " ".join(
                    str(row.get(key, ""))
                    for key in ("event", "trigger", "before", "during", "after")
                ),
                source,
                beat_id,
            )
        spoken_units = 0
        dialogue_rows = _list(row.get("dialogue"), f"{beat_id}.dialogue")
        dialogue_lines = [
            str(line.get("text", "")) for line in dialogue_rows if isinstance(line, dict)
        ]
        before_text = str(row.get("before", ""))
        if driver == "novel" and dialogue_lines:
            first_dialogue = dialogue_lines[0]
            dialogue_position = source.find(first_dialogue)
            if dialogue_position >= 0:
                source_prefix = source[max(0, dialogue_position - 48):dialogue_position]
                pre_speech_laugh = re.search(
                    r"(?:轻笑|輕笑|笑道|笑着说|笑著說|笑着问|笑著問)"
                    r"[^。！？\\n]{0,8}[：:，,]?[“「『\"]?$",
                    source_prefix,
                )
                if pre_speech_laugh and not re.search(
                    r"(?:轻笑|輕笑|笑出声|笑出聲|发出.{0,4}笑|發出.{0,4}笑)",
                    before_text,
                ):
                    raise CreativeContractError(
                        f"{beat_id}.before 遗漏原文紧邻对白之前的笑声动作；"
                        "固定编译顺序会先播放 dialogue，先轻笑再说话必须把轻笑写入 before，"
                        "不能放进 during 或 after"
                    )
        during_text = str(row.get("during", ""))
        after_text = str(row.get("after", ""))
        if not dialogue_rows and _UNLOCKED_SPEECH_ACTION.search(
            " ".join((before_text, during_text, after_text))
        ):
            raise CreativeContractError(
                f"{beat_id} 用嘴唇或开口动作表演未锁定的说话内容，但 dialogue 为空；"
                "直接对白必须进入 dialogue，间接叙述只能用来源内逐字旁白/字幕配中性动作"
            )
        if dialogue_lines and _DIALOGUE_DEPENDENT_BEFORE.search(before_text):
            raise CreativeContractError(
                f"{beat_id}.before 描写了听到本拍问话或要求后的反应，但固定编译时它会先于"
                "第一句对白出现；把刺激前状态留在 before，把听者反应移到对白后的动作窗口"
            )
        if len(dialogue_rows) >= 2 and _PENDING_PLAYED_SPEECH.search(after_text):
            raise CreativeContractError(
                f"{beat_id}.after 仍在等待或准备播放本拍已经结束的后续对白；"
                "after 位于全部 dialogue 之后，只能写回答落音后的可见结果"
            )
        if len(dialogue_rows) >= 2 and _COMPLETED_SPEECH.search(during_text):
            later_speakers = [
                str(line.get("speaker", "")) for line in dialogue_rows[1:]
                if isinstance(line, dict)
            ]
            if any(
                alias in during_text
                for speaker in later_speakers for alias in _speaker_aliases(speaker)
            ):
                raise CreativeContractError(
                    f"{beat_id}.during 写成后续说话人已经答出或说完，但固定编译时后续对白"
                    "尚未播放；during 只能放第一句之后、下一句之前的可见反应"
                )
        before_positions = _standing_positions(before_text)
        after_positions = _standing_positions(after_text)
        transition_text = " ".join(
            str(row.get(key, "")) for key in ("event", "trigger", "before")
        )
        if previous_after_positions and not _TIME_OR_SCENE_TRANSITION.search(transition_text):
            for actor in previous_after_positions.keys() & before_positions.keys():
                if (
                    previous_after_positions[actor] != before_positions[actor]
                    and not _POSITION_CHANGE.search(before_text)
                ):
                    raise CreativeContractError(
                        f"{previous_beat_id}→{beat_id} 中 {actor} 从 "
                        f"{previous_after_positions[actor]} 跳到 {before_positions[actor]}，"
                        "但新拍没有时间/场景转场或可见走位；相邻拍首尾位置必须相接"
                    )
        for actor in before_positions.keys() & after_positions.keys():
            if (
                before_positions[actor] != after_positions[actor]
                and not _POSITION_CHANGE.search(" ".join((before_text, during_text, after_text)))
            ):
                raise CreativeContractError(
                    f"{beat_id} 中 {actor} 从 {before_positions[actor]} 变到 "
                    f"{after_positions[actor]}，但动作字段没有走位过程；须补连续移动或保持原站位"
                )
        previous_beat_id = beat_id
        previous_after_positions = after_positions
        if (
            len(dialogue_lines) >= 2
            and any(marker in dialogue_lines[1].lower() for marker in _TRANSFER_REQUEST_MARKERS)
            and any(marker in str(row.get("during", "")).lower()
                    for marker in _TRANSFER_COMPLETION_MARKERS)
        ):
            raise CreativeContractError(
                f"{beat_id}.during 在第二句请求台词之前提前完成递交或接收；"
                "固定顺序是首句对白 → during → 第二句请求 → after，交付动作必须移到 after"
            )
        if (
            len(dialogue_lines) == 1
            and len(_dialogue_text(dialogue_lines[0])) >= 30
            and re.search(
                r"(?:说到|說到|念到|问到|問到|说完|說完|念完|问完|問完)",
                str(row.get("during", "")),
            )
        ):
            raise CreativeContractError(
                f"{beat_id}.during 用语言时间锚点模拟单条长对白内部动作；"
                "应在原文标点处分成同一说话人的相邻 dialogue，再把反应放在两句之间"
            )
        for key in ("before", "during", "after"):
            repeated_quotes = _quoted_action_dialogue_matches(row[key], dialogue_lines)
            speaker_labels = {
                "".join(
                    char for char in re.split(
                        r"[（(]", str(dialogue.get("speaker", "")), maxsplit=1,
                    )[0]
                    if char.isalnum()
                )
                for dialogue in dialogue_rows
                if isinstance(dialogue, dict)
            }
            repeated_quotes = [
                quote for quote in repeated_quotes
                if "".join(char for char in quote if char.isalnum()) not in speaker_labels
            ]
            if repeated_quotes:
                preview = "、".join(repeated_quotes[:3])
                raise CreativeContractError(
                    f"{beat_id}.{key} 用引号再次写入已锁定对白片段: {preview[:48]}；"
                    "来源说明应留在候选或审核记录，动作字段只写可见表演"
                )
            if dialogue_lines and re.search(
                r"(?:逐字|完整|原句).{0,10}(?:说出|說出|念出|讀出)|"
                r"(?:说出|說出|念出|讀出).{0,10}(?:那句|这句|這句|肯定|回答|对白|對白|台词|台詞)",
                str(row[key]),
            ):
                raise CreativeContractError(
                    f"{beat_id}.{key} 用泛称再次表演已锁定对白；"
                    "台词已由 dialogue 插入，动作字段只能写说话前后的可见表情与动作"
                )
        for line_index, line in enumerate(dialogue_rows):
            speaker = _text(line.get("speaker"), f"{beat_id}.speaker")
            spoken = _text(line.get("text"), f"{beat_id}.text")
            normalized_spoken = _dialogue_text(spoken)
            compact_spoken = "".join(char for char in normalized_spoken if char.isalnum())
            performance_text = " ".join(
                str(row.get(key, "")) for key in ("before", "during", "after")
            )
            claimed_counts = _claimed_spoken_character_counts(performance_text)
            if any(count != len(compact_spoken) for count in claimed_counts):
                claimed = "、".join(str(count) for count in claimed_counts)
                raise CreativeContractError(
                    f"{beat_id} 表演说明声称对白是 {claimed} 个字，实际锁定对白去除标点后"
                    f"为 {len(compact_spoken)} 个字；不能把感叹号数量当成说出的字或音节"
                )
            bare_vocative = (
                spoken.rstrip().endswith((",", "，", ":", "："))
                and bool(re.fullmatch(r"[\w\u3400-\u9fff]+[,，:：]", spoken.strip()))
                and line_index + 1 < len(dialogue_rows)
                and any(
                    isinstance(later, dict) and later.get("speaker") == speaker
                    for later in dialogue_rows[line_index + 1:]
                )
            )
            if len(compact_spoken) >= 4 and not bare_vocative:
                for key in ("before", "during", "after"):
                    compact_action = "".join(char for char in row[key] if char.isalnum())
                    if compact_spoken in compact_action or _action_near_repeats_dialogue(
                        row[key], spoken,
                    ):
                        raise CreativeContractError(
                            f"{beat_id}.{key} 直接或改写复述已锁定对白；台词只能放在 dialogue，"
                            "否则剧本会重复或打乱动作时序"
                        )
            spoken_units += _speech_units(spoken)
            expected_rendered_dialogue.append(normalized_spoken)
            selected_dialogue_text += normalized_spoken
            if driver == "novel":
                narration = is_narration_speaker(speaker)
                if not narration:
                    used_direct_novel_dialogue = True
                position = (
                    source_dialogue.find(normalized_spoken, source_cursor)
                    if narration else _find_direct_dialogue(
                        source_dialogue, normalized_spoken, source_cursor,
                        direct_source_spans,
                    )
                )
                if position < 0:
                    exists_in_earlier_direct_speech = (
                        not narration
                        and _find_direct_dialogue(
                            source_dialogue, normalized_spoken, 0,
                            direct_source_spans,
                        ) >= 0
                    )
                    reason = (
                        "不在所选原文顺序中"
                        if narration or exists_in_earlier_direct_speech
                        else "不是所选原文中的人物直接引语"
                    )
                    raise CreativeContractError(f"{beat_id} 角色对白{reason}: {spoken[:24]}")
                source_cursor = position + len(normalized_spoken)
            position = screenplay_dialogue.find(normalized_spoken, screenplay_cursor)
            if position < 0:
                raise CreativeContractError(f"{beat_id} 对白未按顺序进入可读剧本: {spoken[:24]}")
            screenplay_cursor = position + len(normalized_spoken)
        if spoken_units > beat_duration * 4.5:
            timing_issues.append(
                f"{beat_id} 对白约 {spoken_units} 个计时单位无法在 {beat_duration:g} 秒内自然说完；"
                "需延长节拍或保真删选整句，并保留动作反应时间"
            )
        action_text = " ".join(str(row.get(key, "")) for key in ("before", "during", "after"))
        slow_performance = _deliberate_slow_performance(action_text)
        drawn_out_delivery = _dialogue_has_drawn_out_delivery(dialogue_lines)
        if (
            spoken_units
            and (
                (slow_performance and spoken_units > max(0.0, beat_duration - 1.0) * 4.0)
                or (
                    drawn_out_delivery
                    and spoken_units > max(0.0, beat_duration - 2.0) * 3.5
                )
            )
        ):
            timing_issues.append(
                f"{beat_id} 明确要求放慢、停顿或郑重表演，却在 {beat_duration:g} 秒内安排约 "
                f"{spoken_units} 个计时单位；至少还须给动作和反应保留 1 秒"
            )
        physical_steps = _physical_step_count(action_text)
        action_seconds = beat_duration - (spoken_units / 4.5)
        if physical_steps >= 7 and action_seconds < physical_steps * 0.6:
            timing_issues.append(
                f"{beat_id} 约有 {physical_steps} 个连续物理步骤，但扣除对白后只剩约 "
                f"{max(0.0, action_seconds):.1f} 秒；需删减动作或延长节拍"
            )
        total_spoken_units += spoken_units
    unclosed_quote = (
        _unclosed_dialogue_quote(selected_dialogue_text)
        if driver == "novel" else None
    )
    if unclosed_quote:
        raise CreativeContractError(
            f"小说对白保留了嵌套引号 {unclosed_quote}，但漏掉对应结束符；"
            "逐字选句必须保留原文成对引号与标点"
        )
    if driver == "novel":
        if used_direct_novel_dialogue:
            omitted_later_spans = [
                (start, end)
                for start, end in direct_source_spans
                if start >= source_cursor
                and any(char.isalnum() for char in source_dialogue[start:end])
            ]
            source_aftermath = (
                source_dialogue[omitted_later_spans[-1][1]:]
                if omitted_later_spans else ""
            )
            production_text = "\n".join(production_text_parts)
            borrowed_outcomes = [
                marker for marker in _POST_DIALOGUE_OUTCOME_MARKERS
                if marker in source_aftermath and marker in production_text
            ]
            if borrowed_outcomes:
                omitted_later_dialogue = [
                    source_dialogue[start:end] for start, end in omitted_later_spans
                ]
                preview = "、".join(omitted_later_dialogue[:2])
                outcome_preview = "、".join(borrowed_outcomes[:3])
                raise CreativeContractError(
                    "所选原文在最后采用对白之后仍有未进入剧本的直接对白: "
                    f"{preview[:64]}；剧本又使用了其后的可见结果: {outcome_preview}。"
                    "若本片应提前收束，须删去后续结果或在候选阶段收窄 selected_source；"
                    "若使用这些对白之后的反应，必须保留中间对白，不能改写刺激与后果"
                )
        _validate_source_materials(source, "\n".join(production_text_parts), "剧本")
    if total_spoken_units > total * 3.5:
        timing_issues.append(
            f"全片对白约 {total_spoken_units} 个计时单位、节拍合计 {total:g} 秒，"
            "超过每秒 3.5 单位的整片密度上限；需删选整句或延长片长以保留表演"
        )
    if timing_issues:
        visible = timing_issues[:8]
        suffix = f"；另有 {len(timing_issues) - len(visible)} 处" if len(timing_issues) > len(visible) else ""
        raise CreativeContractError("；".join(visible) + suffix)
    rendered_dialogue = []
    for line in screenplay.splitlines():
        stripped = line.strip()
        if stripped.startswith("**") and "**" in stripped[2:] and "：" in stripped:
            label = stripped.split("**", 2)[1]
            if label.startswith("创作选择"):
                continue
            rendered_dialogue.append(_dialogue_text(stripped.split("：", 1)[1]))
    if rendered_dialogue != expected_rendered_dialogue:
        raise CreativeContractError("可读剧本的对白或画外心声与结构化节拍不一致")
    difference = abs(total - target)
    if difference > max(3.0, target * 0.05):
        if difference > 15.0 or difference > max(total, target) * 0.2:
            raise CreativeContractError("剧本节拍时长与总时长不符")
        value["declared_duration_seconds"] = target
        value["duration_seconds"] = total
        value["duration_reconciliation"] = "computed_from_beat_durations; first_draft_warning"


def validate_beat_plan(value: dict[str, Any], candidate_id: str, source: str, driver: str) -> None:
    """Check the locked story and source dialogue before prose is authored."""
    beats = _list(value.get("beats"), "beats", minimum=2)
    lines = [
        f"**{line.get('speaker', '')}**：{_render_dialogue_text(str(line.get('text', '')))}"
        for beat in beats for line in _list(beat.get("dialogue"), "beat.dialogue")
    ]
    check = deepcopy(value)
    check["screenplay_markdown"] = "\n".join(lines) or "无对白的动作剧本占位"
    validate_script(check, candidate_id, source, driver)
    for key in ("declared_duration_seconds", "duration_seconds", "duration_reconciliation"):
        if key in check:
            value[key] = check[key]


def compile_screenplay_template(value: dict[str, Any], beat_plan: dict[str, Any]) -> str:
    """Insert locked dialogue without trusting the model to retype a second copy."""
    if not isinstance(value, dict) or set(value) != {"beat_scenes"}:
        raise CreativeContractError("可读剧本阶段只允许返回 beat_scenes")
    scenes = _list(value["beat_scenes"], "beat_scenes", minimum=2)
    if len(scenes) != len(beat_plan["beats"]):
        raise CreativeContractError("可读剧本节拍数量与锁定节拍不一致")
    rendered = [f"# {beat_plan['title']}", ""]
    for scene, beat in zip(scenes, beat_plan["beats"], strict=True):
        if not isinstance(scene, dict) or set(scene) != {"beat_id", "action_segments"}:
            raise CreativeContractError("可读剧本节拍只允许 beat_id 和 action_segments")
        if scene["beat_id"] != beat["id"]:
            raise CreativeContractError("可读剧本节拍 ID 缺失、重复或错序")
        segments = _list(scene["action_segments"], "action_segments")
        if len(segments) != len(beat["dialogue"]) + 1:
            raise CreativeContractError(f"{beat['id']} 动作段数必须等于对白句数加一")
        rendered.extend([f"## {beat['id']} {beat['event']}", ""])
        for index, segment in enumerate(segments):
            prose = _text(segment, f"{beat['id']}.action_segments[{index}]")
            if any(mark in prose for mark in ('"', "「", "」", "“", "”", "『", "』", "[[DIALOGUE:")):
                raise CreativeContractError("可读剧本动作段含直接引语或对白占位符")
            if re.search(r"(?m)^\s*\*\*[^\n]+\*\*\s*[：:]", prose):
                raise CreativeContractError("可读剧本动作段私自写入台词行")
            rendered.extend([prose, ""])
            if index < len(beat["dialogue"]):
                line = beat["dialogue"][index]
                rendered.extend([
                    f"**{_text(line.get('speaker'), 'speaker')}**："
                    f"{_render_dialogue_text(_text(line.get('text'), 'text'))}", "",
                ])
    return "\n".join(rendered).strip()


def compile_beat_screenplay(beat_plan: dict[str, Any]) -> str:
    """Render the writer's locked beats and dialogue without a second model rewrite."""
    rendered = [f"# {_text(beat_plan.get('title'), 'title')}", ""]
    for beat in beat_plan["beats"]:
        beat_id = _text(beat.get("id"), "beat.id")
        rendered.extend([f"## {beat_id} {_text(beat.get('event'), 'beat.event')}", ""])
        rendered.extend([_text(beat.get("before"), f"{beat_id}.before"), ""])
        dialogue = beat["dialogue"]
        if dialogue:
            first = dialogue[0]
            rendered.extend([
                f"**{_text(first.get('speaker'), 'speaker')}**："
                f"{_render_dialogue_text(_text(first.get('text'), 'text'))}", "",
            ])
        rendered.extend([_text(beat.get("during"), f"{beat_id}.during"), ""])
        for line in dialogue[1:]:
            rendered.extend([
                f"**{_text(line.get('speaker'), 'speaker')}**："
                f"{_render_dialogue_text(_text(line.get('text'), 'text'))}", "",
            ])
        rendered.extend([_text(beat.get("after"), f"{beat_id}.after"), ""])
    return "\n".join(rendered).strip()


def validate_screenplay_output(
    value: dict[str, Any], beat_plan: dict[str, Any],
    candidate_id: str, source: str, driver: str,
) -> None:
    combined = {key: deepcopy(item) for key, item in beat_plan.items() if key != "screenplay_markdown"}
    combined["screenplay_markdown"] = compile_screenplay_template(value, beat_plan)
    validate_script(combined, candidate_id, source, driver)


def _creative_focus_post_dialogue_window(
    creative_focus: str, beat_id: str,
) -> tuple[int, int] | None:
    """Read an explicit post-dialogue hold window scoped to one beat."""
    if not isinstance(creative_focus, str) or not creative_focus.strip():
        return None
    start = creative_focus.find(beat_id)
    if start < 0:
        return None
    following = re.search(r"B\d{2}", creative_focus[start + len(beat_id):])
    end = (
        start + len(beat_id) + following.start()
        if following else min(len(creative_focus), start + 260)
    )
    segment = creative_focus[start:end]
    numeral = r"(?:\d+|[零一二两三四五六七八九十]+)"
    ranged = re.search(
        rf"落音后.{{0,12}}?({numeral})\s*(?:到|至|[-–—~～])\s*"
        rf"({numeral})\s*秒",
        segment,
    )
    if ranged:
        lower = _small_chinese_integer(ranged.group(1))
        upper = _small_chinese_integer(ranged.group(2))
        if lower is not None and upper is not None:
            return (min(lower, upper), max(lower, upper))
    single = re.search(rf"落音后.{{0,12}}?({numeral})\s*秒", segment)
    if single:
        seconds = _small_chinese_integer(single.group(1))
        if seconds is not None:
            return (seconds, seconds)
    return None


def validate_shots(
    value: dict[str, Any], brief: dict[str, Any], script: dict[str, Any],
    source: str = "", creative_focus: str = "",
) -> None:
    style = value.get("style")
    if not isinstance(style, dict) or style.get("style_option_id") != brief["selected_style_id"]:
        raise CreativeContractError("分镜未沿用选定的导演画风")
    for key in ("visual_medium", "palette", "spatial_layout", "character_lock", "light_source"):
        _text(style.get(key), f"style.{key}")
    character_lock = str(style["character_lock"])
    if re.search(
        r"(?:\d+|[一二三四五六七八九十两]+)\s*"
        r"(?:到|至|[-—~～])\s*"
        r"(?:\d+|[一二三四五六七八九十两]+)\s*(?:名|个|人)",
        character_lock,
    ):
        raise CreativeContractError(
            "character_lock 必须锁定确切人数，不能使用人数范围"
        )
    shots = _list(value.get("shots"), "shots", minimum=1)
    beats = {row["id"] for row in script["beats"]}
    beat_rows = {row["id"]: row for row in script["beats"]}
    seen_beats: set[str] = set()
    seen_shots: set[str] = set()
    beat_order = {row["id"]: index for index, row in enumerate(script["beats"])}
    beat_durations = {row["id"]: 0.0 for row in script["beats"]}
    beat_dialogue: dict[str, list[Any]] = {row["id"]: [] for row in script["beats"]}
    shots_by_beat: dict[str, list[dict[str, Any]]] = {
        row["id"]: [] for row in script["beats"]
    }
    last_beat_index = -1
    previous: dict[str, Any] | None = None
    continuity_errors = []
    production_text_parts = [
        str(style.get(key, ""))
        for key in ("visual_medium", "palette", "spatial_layout", "character_lock", "light_source")
    ]
    for row in shots:
        shot_id = _text(row.get("id"), "shot.id")
        if shot_id in seen_shots:
            raise CreativeContractError("镜头 ID 重复")
        seen_shots.add(shot_id)
        beat_id = _text(row.get("beat_id"), f"{shot_id}.beat_id")
        if beat_id not in beats:
            raise CreativeContractError(f"{shot_id} 指向不存在的情绪节拍")
        if row.get("event_lock") != beat_rows[beat_id]["event"]:
            raise CreativeContractError(f"{shot_id} 未绑定编剧定稿事件")
        shot_dialogue = _list(row.get("dialogue_lock"), f"{shot_id}.dialogue_lock")
        beat_dialogue[beat_id].extend(shot_dialogue)
        if beat_order[beat_id] < last_beat_index:
            raise CreativeContractError(f"{shot_id} 使剧情节拍倒序")
        last_beat_index = beat_order[beat_id]
        seen_beats.add(beat_id)
        shots_by_beat[beat_id].append(row)
        shot_duration = _duration(row.get("duration_seconds"), f"{shot_id}.duration_seconds")
        beat_durations[beat_id] += shot_duration
        spoken_units = sum(
            _speech_units(str(line.get("text", "")))
            for line in shot_dialogue if isinstance(line, dict)
        )
        if spoken_units > shot_duration * 5:
            raise CreativeContractError(
                f"{shot_id} 对白约 {spoken_units} 个计时单位无法在 {shot_duration:g} 秒内自然说完；"
                "不能用本节拍其他无对白镜头的时长抵扣"
            )
        performance_text = str(row.get("visible_performance") or "")
        if _requires_continuous_movement(character_lock):
            conflict = _PHYSICAL_STOP.search(
                " ".join(
                    str(row.get(key, ""))
                    for key in (
                        "purpose", "composition", "camera", "visible_performance",
                        "start_state", "end_state", "cut_reason", "prompt",
                    )
                )
            )
            if conflict:
                raise CreativeContractError(
                    f"{shot_id} 把 character_lock 锁定的持续行走改成身体停步: "
                    f"{conflict.group(0)}；镜头只能表现情绪停顿，不能让脚步停下"
                )
        shot_dialogue_lines = [
            str(line.get("text", ""))
            for line in shot_dialogue if isinstance(line, dict)
        ]
        slow_performance = _deliberate_slow_performance(performance_text)
        drawn_out_delivery = _dialogue_has_drawn_out_delivery(shot_dialogue_lines)
        if (
            spoken_units
            and (
                (slow_performance and spoken_units > max(0.0, shot_duration - 1.0) * 4.0)
                or (
                    drawn_out_delivery
                    and spoken_units > max(0.0, shot_duration - 2.0) * 3.5
                )
            )
        ):
            raise CreativeContractError(
                f"{shot_id} 明确要求放慢、停顿或郑重表演，但约 {spoken_units} 个计时单位对白"
                f"只分到 {shot_duration:g} 秒；本镜还须保留动作和反应时间"
            )
        physical_steps = _physical_step_count(performance_text)
        action_seconds = shot_duration - (spoken_units / 5.0)
        if physical_steps >= 6 and action_seconds < physical_steps * 0.55:
            raise CreativeContractError(
                f"{shot_id} 约有 {physical_steps} 个连续物理步骤，但扣除对白后只剩约 "
                f"{max(0.0, action_seconds):.1f} 秒；切镜不能代替动作时间"
            )
        for key in (
            "purpose", "composition", "camera", "visible_performance", "start_state",
            "end_state", "cut_reason", "dialogue_mode", "prompt",
        ):
            _text(row.get(key), f"{shot_id}.{key}")
            production_text_parts.append(str(row[key]))
        if row.get("continuity_mode") not in (
            "raw_tail_continuation", "planned_cut_requires_adapter",
        ):
            raise CreativeContractError(f"{shot_id} 连续模式无效")
        _list(row.get("production_choices"), f"{shot_id}.production_choices")
        production_text_parts.extend(str(item) for item in row["production_choices"])
        if previous and row["continuity_mode"] == "raw_tail_continuation":
            if previous["end_state"] != row["start_state"]:
                continuity_errors.append(shot_id)
        previous = row
    if source:
        production_text = "\n".join(production_text_parts)
        _validate_source_materials(source, production_text, "分镜")
        _validate_unsupported_body_gaze(production_text, source, "分镜")
    if continuity_errors:
        raise CreativeContractError(
            f"{','.join(continuity_errors)} 原始尾帧续段状态不连续；"
            "逐镜使 start_state 与前镜 end_state 完全一致，或改标需适配切镜"
        )
    if seen_beats != beats:
        raise CreativeContractError("导演稿遗漏了编剧情绪节拍")
    beat_contract_errors: list[str] = []
    for beat in script["beats"]:
        actual, expected = beat_durations[beat["id"]], beat["duration_seconds"]
        if abs(actual - expected) > max(1.5, expected * 0.1):
            beat_contract_errors.append(
                f"{beat['id']} 分镜时长与剧本节拍不符"
                f"（分镜合计 {actual:g} 秒，剧本 {expected:g} 秒）"
            )
        if not _director_dialogue_is_exact_partition(
            beat_dialogue[beat["id"]], beat["dialogue"],
        ):
            beat_contract_errors.append(
                f"{beat['id']} 分镜对白与剧本顺序或内容不符"
            )
        reaction_window = _creative_focus_post_dialogue_window(
            creative_focus, beat["id"]
        )
        beat_shots = shots_by_beat[beat["id"]]
        dialogue_indexes = [
            index for index, shot in enumerate(beat_shots)
            if isinstance(shot.get("dialogue_lock"), list)
            and shot["dialogue_lock"]
        ]
        if reaction_window is not None and dialogue_indexes:
            last_dialogue_index = max(dialogue_indexes)
            dedicated_post_seconds = sum(
                _duration(
                    shot.get("duration_seconds"),
                    f"{shot.get('id', beat['id'])}.duration_seconds",
                )
                for shot in beat_shots[last_dialogue_index + 1:]
                if isinstance(shot.get("dialogue_lock"), list)
                and not shot["dialogue_lock"]
            )
            if dedicated_post_seconds > reaction_window[1]:
                beat_contract_errors.append(
                    f"{beat['id']} 对白后独立反应镜合计 {dedicated_post_seconds:g} 秒，"
                    f"超过 creative_focus 明确落音后窗口 "
                    f"{reaction_window[0]}-{reaction_window[1]} 秒"
                )
    if beat_contract_errors:
        raise CreativeContractError("；".join(beat_contract_errors))
    _list(value.get("media_assumptions"), "media_assumptions")


def _director_dialogue_is_exact_partition(
    shot_dialogue: list[Any], script_dialogue: list[Any],
) -> bool:
    """Allow one locked writer line to be split across shots without rewriting it."""
    if not script_dialogue:
        return not shot_dialogue
    line_index = 0
    character_offset = 0
    for row in shot_dialogue:
        if (
            line_index >= len(script_dialogue)
            or not isinstance(row, dict)
            or set(row) != {"speaker", "text"}
            or not isinstance(row.get("speaker"), str)
            or not isinstance(row.get("text"), str)
            or not row["text"]
        ):
            return False
        expected = script_dialogue[line_index]
        if (
            not isinstance(expected, dict)
            or set(expected) != {"speaker", "text"}
            or row["speaker"] != expected["speaker"]
            or not expected["text"][character_offset:].startswith(row["text"])
        ):
            return False
        character_offset += len(row["text"])
        if character_offset == len(expected["text"]):
            line_index += 1
            character_offset = 0
    return line_index == len(script_dialogue) and character_offset == 0


def validate_director_shots_or_story_issues(
    value: dict[str, Any], brief: dict[str, Any], script: dict[str, Any],
    source: str = "", creative_focus: str = "",
) -> None:
    if "story_issues" not in value:
        validate_shots(value, brief, script, source, creative_focus)
        return
    if set(value) != {"story_issues"}:
        raise CreativeContractError("导演退回编剧时只能提交 story_issues，不得混入分镜")
    issues = _list(value["story_issues"], "story_issues", minimum=1)
    for row in issues:
        if not isinstance(row, dict) or row.get("owner") != "writer":
            raise CreativeContractError("导演前置问题必须退回编剧")
        if row.get("severity") not in ("blocking", "major"):
            raise CreativeContractError("导演前置问题只能是阻断或主要剧情问题")
        for key in ("location", "evidence", "impact", "proposal"):
            _text(row.get(key), f"story_issue.{key}")


def validate_writer_check(value: dict[str, Any]) -> list[dict[str, Any]]:
    if type(value.get("story_preserved")) is not bool:
        raise CreativeContractError("story_preserved 必须为布尔值")
    issues = _list(value.get("issues"), "issues")
    for row in issues:
        if row.get("owner") not in ("writer", "director"):
            raise CreativeContractError("问题单必须指定编剧或导演")
        if row.get("severity") not in ("blocking", "major", "minor"):
            raise CreativeContractError("问题严重度无效")
        for key in ("location", "evidence", "impact", "proposal"):
            _text(row.get(key), f"issue.{key}")
    if not value["story_preserved"] and not any(
        row["severity"] in ("blocking", "major") for row in issues
    ):
        raise CreativeContractError("故事未保留却没有阻断或主要问题")
    _list(value.get("calibration_focus"), "calibration_focus")
    return issues


def brief_for_user(value: dict[str, Any]) -> str:
    """A compact explanation; never pretend to expose private model reasoning."""
    return json.dumps(
        {
            "summary": value.get("summary"),
            "selection_reason": value.get("selection_reason"),
            "candidates": value.get("candidates"),
        },
        ensure_ascii=False,
        indent=2,
    )




PROMPTS["production_design"] = DESIGN_PROMPT
