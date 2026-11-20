"""Source-first transcription: no model-written analysis, plan or biography."""
from .contracts import digest

TRANSCRIBE = '''你是原文视听转写员。把输入的完整目标章节依顺序转成能拍摄/配音的剧本。
原文是唯一剧情依据，context_only只辅助理解。保留目标章开头结尾及所有关键事件。
按自然地点和时间变化分场；同一环境连续行动可以合在一场。
输出简短世界背景、逐场时间地点在场人物、画面动作、对白/心声/必要旁白及原段号。
背景仅列当前剧情必需且原文明示的信息；人物用姓名，不补全排行年龄关系表。
原有对白保留主体与含义，叙述的行动转换成可见动作，心理转换为自然第一人称心声或旁白。
对白未署名时依明确上下文归属；仍不能确定的写【说话人待核】，保留原句并列段号，不猜人名。
未明示的动作主体同样标待核。推测、条件、未来打算保持原来的语气与时间层。
演出设计单列，只补表情、景别、光线及不改变剧情状态的微动作。人物位置、去向、重要道具归属以原文为准。
原文没有的回忆内容、人物经历、行动目标、承诺或结果不属于演出设计。
不要扩写对白来推动新的行动，不重新编故事，不制造悬念，不限制场数或时长。
每场末附原段号；全部目标原段得到表达或列出不影响剧情的合并说明。疑义单列待核，不用猜测填满。
只返回text字段内完整剧本。'''

REVIEW = '''对照程序给定的完整原文与完整候选，独立检查视听转写。
按原文顺序核对目标首尾、事件因果、人物关系/称谓/对白主体、人物去向和重要道具。
候选中的背景和人物名单也是待核内容，不能用它证明它自己。
每条错误列原文段号及引句、候选引句、改变的信息。未知不等于错误；有待核归属就标需决策，不能宣称可生产。
区分明确剧情矛盾、未决归属、声音画面表达问题和可选风格。普通灯光、微动作、合理省略转场不是错误。
不凭出场顺序推断排行，不把前夜忽略为仅次日，不把内心疑问变出声事实。
给出完整覆盖结论与未解决项，不直接改稿；本审核不授予自动放行。
只返回text字段内审核。'''

def packet(source, context, target):
    if set(context)&set(target) or not target:raise ValueError('invalid_scope')
    chapters={ch['index']:ch for ch in source['chapters']}
    result=[]
    for role,ids in [('context_only',context),('target',target)]:
        for index in ids:
            ch=chapters[index]
            result.append({'chapter':index,'role':role,'text_sha256':digest(ch['text']),
                'paragraphs':[{'id':f'CH{index}-P{n:03}','text':s}
                              for n,s in enumerate(ch['text'].split('\n\n'),1)]})
    return {'source_sha256':digest(source),'chapters':result}

def review_input(original, candidate):
    return {'original':original,'complete_candidate':candidate,'candidate_sha256':digest(candidate)}
