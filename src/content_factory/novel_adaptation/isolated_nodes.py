"""Stage-local instructions and minimal handoffs; no prompt inheritance."""
from . import contracts as c, audio_first as a

AUDIO = '''你只负责声音整理。source是小说原文，target为本次正文，context_only为理解前情。
选取剧情必需的出声对白、心理/解释旁白、系统提示。原文用间接叙述交代的告知、提议等也须保留必要信息，避免只留下反应而漏掉原因；可选取原句作旁白，无需编新台词。
每项text取source_id中的连续原文片段。kind为dialogue、narration或system。先判断是否出声，再判断谁说；心理主体不明仍是narration，已出声但归属不明的dialogue才speaker为空。narration和system的speaker为空。
署名只依据原文上下文，evidence_ids给依据；未知保持空，不推测排行或把同一群体的所有话强归一人。
按目标原文顺序提交items，可一段多项；保留必要条件、否定和心理因果。普通可见动作不必重复配旁白。本节点输出只含声音项。'''

PICTURE = '''你的交付是把完整target小说正文整理成可供视频制作的连续场景剧本：让观众看懂谁在什么地方、发生什么、人物如何回应、下一件事为何发生。context_only只帮助理解前情；source是事实依据；audio_items是已有声音，只引用ID，保留原内容。
按原著事件顺序组织场景，先安排当前可见行动，再配已有声音承载对白、心理及解释。可见动作直接写入画面；必要信息通过画面或声音表达一次即可，不要求两种通道重复覆盖。完整保留目标正文的必要剧情与因果，连续行动可合场，无必要信息的过渡可省略。
地点联系按事件进展理解：区分人物已经离开、正在前往、已经抵达及只是计划去的地点。下一场承接最近实际发生的行动，不把较早地点沿用到已经转场后的内容。先确定原文支持的当前场所，再判断原文是否说明它与其他场所的方位关系；仅有行程先后不等于位于某处旁边、内部或外面。方位未明时，使用原文场所名及有依据的行程阶段即可。
逐场结合前后原文核对地点：前一场最后实际发生的行动和结束地点是什么，当前场从哪里开始，哪些动作发生在移动前、途中、抵达后，结束时人物又在哪里；下一场从这个已发生的结束状态承接。原文出现到站、出门、进店、回来等转折时，保留转折前后动作各自所属的位置。允许省略无信息的移动过程或合并场次，但合场文字必须明确各阶段的位置，不能把后一地点的动作放进前一地点。这里只要求清楚表达地点前后的内容，不要求额外生成状态表或逐步分析说明。
已由原文明示的主体、事件、关系、条件、当前/回忆/计划状态保持不变。不明确的内容保留开放，不猜地理归属、人物关系或未发生的结果。可设计普通景别、光线、微表情；不能借表现设计新增剧情事实。心理/过去见闻不替换成当前可见事件。
每场人物列本场实际出现的人；根据原文已发生的进出判断，不能把之前人物表直接沿用。场名、时间、地点与该场内容一致，不额外补详细地址。
连续行动可合并，过渡可省略；保留必要信息和因果。音画分组是合法剧本格式，暂不安排逐镜头时间。
text逐行使用：
场次：编号与名称
时间：原文支持的时段
地点：原文支持的层级，不明时不强调具体位置
人物：本场人物
画面[原文段号或同章连续范围]：可见表现
声音[音频ID]
原段：本场来源范围
段号取source.chapters.paragraphs.id；范围可用完整起止段号或末端P加数字，以-或~连接。声音ID取audio_items.audio_id，每项按顺序引用一次，程序会原样展开；可一行一个，也可同一行连续括号引用多个ID。地点信息放在地点行，不增加其他类型行。
未知声音不要通过画面指定发声人；旁白不安排人物张口说。每场包含场次、时间、地点、人物、原段。输出text和gaps。
gaps专指必需的声音缺口，按以下顺序判定：先检查信息是否已由已有声音或你写出的画面表达；能由原文支持的可见行动表达，就在text补足画面；只有必要对白、心理、解释或告知在已有声音中缺失、且仅靠可见行动无法准确传达其含义时，才报告gaps。普通可见动作缺少对应音频不构成声音缺口，不为凑配音而重复动作。
每个gap包含source_id及missing_content，后者说明遗漏的信息以及为何画面和现有声音无法表达它；没有这种缺口则返回空数组。gaps是待审建议，不自行增改声音。'''

REVIEW = '''你只负责审核，不生成或修改剧本。source是小说原文；candidate是待审内容，rendered=false时为未合成有效剧本的原始画面及声音；audio_index是声音出处与归属索引；gaps是上游报告的问题，不是审核结论。
对照原文核查必要信息和因果、人物关系、声音类型和归属、当前位置与进出、计划与回忆是否被当成事实。尤其检查是否只呈现反应却丢掉触发事件。
每个实质错误注明责任节点audio或picture、候选原句/音频ID、原文段号及为何冲突。原文未确定的保留未决，不替原著猜关系；不同说话人称同一人哥哥姐姐不自动矛盾。
普通微动作、光线、适当转场省略可接受；不要求每段都有镜头或配音。不因音画分组、缺逐镜头同步而判错。无动作不等于人物不在场。格式通过不代表语义正确。
地点按实际离开、前往、抵达的行程核查；先后出现的地名不证明方位邻接。逐条复核gaps：画面已表达或可通过原文可见行动表达的，不判为缺声音；区分真正缺失的必要声音、待补画面和已覆盖信息，不能把上游gaps直接当实质错误。
分别报告实质错误、未决和风格建议，仅返回text中的审查报告。'''

def audio_payload(packet):return {'source':packet}

def minimal_audio(bank):
    keys=('audio_id','source_id','kind','speaker','text','evidence_ids')
    return [{k:item[k] for k in keys} for item in bank['items']]

def picture_payload(packet,bank):return {'source':packet,'audio_items':minimal_audio(bank)}

def picture_schema(packet):
    ids=[p['id'] for ch in packet['chapters'] if ch['role']=='target' for p in ch['paragraphs']]
    gap=c.obj(source_id=c.choices(ids),missing_content={**c.TEXT,'description':'必要声音中遗漏的信息，以及为什么当前画面和已有声音无法表达；可见动作缺音频不算缺口。'})
    return c.obj(text=c.TEXT,gaps={**c.array(gap),'description':'只报告不可由画面及已有声音传达的必要声音缺口；无缺口返回空数组。'})

def review_payload(packet,bank,candidate,gaps,validation):
    return {'source':packet,'candidate':candidate,
            'audio_index':[{k:v for k,v in item.items() if k!='text'} for item in minimal_audio(bank)],
            'gaps':gaps,'format_issues':validation['issues']}

def validate_picture(raw,packet):
    issues=c.schema_issues(raw,picture_schema(packet),'picture')
    if issues:raise c.ContractError(issues)
    return raw
