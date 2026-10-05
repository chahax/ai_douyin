"""Evidence-bound script reviews; semantic decisions remain with the assistant."""
from __future__ import annotations
import hashlib
import json
from .creative_workflow_contract import CreativeContractError, validate_writer_check

VERSION = 'evidence_review_v2'
REVIEW_RULES = '''
审核输出采用可定位问题契约。issues仅包含必须修复的blocking/major问题；个人偏好、可选润色或证据不足的猜测放suggestions，不得推动自动返修。
先逐条核对creative_brief.constraints中的硬条件，再审美与节奏。对于“只能、最后一次、最近一句、一次性、唯一持有者、先按后说”这类状态规则，按实际播放顺序逐事件追踪：触发动作发生前，最近一次发言/持有者/使用次数是什么，触发后结果是否符合规则。中间新增的短句也会改变“最后一句”，不能忽略口令、感叹或短回应。只写目标结果已发生，不足以证明前置条件成立。明确违反硬条件必须列issue，不得转为建议或因画面流畅而略过。
每个issue保留owner/location/evidence/impact/proposal/severity，并增加唯一id、rule（违反的具体要求）、contradiction（已知事实与规则冲突的简短说明）、evidence_refs数组。
evidence_refs每项为{"path":"script.beats.0.before","quote":"字段逐字原文"}；必须指向输入中的具体字符串或数字叶子。对白引用必须到dialogue.0.text，不得引用整个数组/对象。至少一条引用指向实际script/shots/production_design内容。location使用已有B或SH编号。proposal是修复目标，不代写正文。
suggestions每项为{"location":"B01","proposal":"可选改进","reason":"为什么只是建议"}，没有则[]。不把优点或无问题内容列入issues。
真实播放顺序为before→第一句dialogue→during→第二句dialogue→after；event/trigger是摘要不播放。前半片按累计秒数算，不按拍号猜。
记忆规则只约束明确指定的对象；一个人失忆不代表另一个人不能回忆或重新表达。把物品放入箱内后整理边角可以合理成立。普通跨拍走路省略不自动构成瞬移。
时长问题需引用明确台词长度、距离、必须顺序完成的动作或指定反应窗口；不能只数动作个数猜测超时。未看实际媒体，不能断言声音、口型或表演通过/失败。
'''
SCRIPT_REVIEW_PROMPT = '''你是DeepSeek独立剧本审查员，只审查当前简报和剧本，不代写。核对需求、人物关系、刺激反应顺序、道具归属、情绪重点与结尾行动者。
只返回JSON。以下是字段结构示意，不是已经通过的审查结论：
{"story_preserved":false,"issues":[{"id":"I01","owner":"writer","location":"B编号","severity":"major","rule":"实际违反的要求","evidence":"当前稿具体事实","evidence_refs":[{"path":"script.beats.0.before","quote":"逐字引用实际字段"}],"contradiction":"事实为何违反规则","impact":"具体影响","proposal":"修复目标"}],"suggestions":[{"location":"B编号","proposal":"可选建议","reason":"非必修的理由"}],"calibration_focus":["待关注事项"]}。
你必须独立判断是否有真实问题；有问题填写issues，无问题才置为[]并令story_preserved=true。没有可选建议则suggestions=[]。禁止照抄示例结论、占位符或原文中不存在的证据。''' + REVIEW_RULES


# Freeze v1 strings: existing task receipts must keep their original prompt hashes.
REVIEW_RULES_V1 = REVIEW_RULES
SCRIPT_REVIEW_PROMPT_V1 = SCRIPT_REVIEW_PROMPT
CANDIDATE_VERSION = 'evidence_review_v2'
RULE_SCOPE_REVIEW = """
规则边界复核（覆盖前面任何可能被过度扩张的审核要求）：
每条必修问题都必须证明当前稿直接违反已给出的条件，不能把“可能影响观感”改写成新禁令。按四项核对：规则约束谁；在什么时刻触发；只改变哪件事或状态；是否明确约束此后的新行为。一次事件的生效条件，与生效后永久禁止同类事件，是不同要求。
例如撤销一笔订单，不自动禁止日后重新下单；关灯成功，不自动要求之后永远不能再开灯。只有简报明确写出后续禁令，后续行为才能按该禁令判断。也不能反向忽略显式禁令。
人物通过新话语获得新信息，不等于先前清除的记忆自行恢复。听者点头只证明回应眼前话语，不证明他记起更早被删除的具体内容。表达“差点做某事”不等于透露那件事的确切原话。若简报没有禁止再次表达，不能自行增加“此后不能提及、不能给线索、不能被推知”的永久保密要求。若简报明确禁止重新提起，则必须检查并指出实际违反。
报告前主动找一个由当前正文直接支持的正常解释：若这个解释满足原规则，且你只能靠额外假设才能声称矛盾，则删除该issue；不要求作者为了回应猜测新增说明。不要把已否定的假设移到calibration_focus里当作必须满足的新要求。
另一方面，触发动作之前新增的发言、拿取或第二次使用必须改变相应的最近事件、持有人或计数，不能把“有正常解释”当作忽略明确时序矛盾的理由。
输出issue.rule只写实际来源的约束；contradiction应指明谁在何时做了什么，与该约束直接冲突。若事实只支持可选审美改善，使用suggestions；若不需要改动则不列意见。不要重复列同一根因。
"""
REVIEW_RULES_V2 = REVIEW_RULES_V1 + RULE_SCOPE_REVIEW
SCRIPT_REVIEW_PROMPT_V2 = SCRIPT_REVIEW_PROMPT_V1 + RULE_SCOPE_REVIEW
SUPPORTED_VERSIONS = ('evidence_review_v1', CANDIDATE_VERSION, 'evidence_review_v3', 'evidence_review_v4', 'evidence_review_v5', 'evidence_review_v6')
# Publish the tested v2 prompt for new tasks; the registry retains exact v1 text.
REVIEW_RULES = REVIEW_RULES_V2
SCRIPT_REVIEW_PROMPT = SCRIPT_REVIEW_PROMPT_V2

def review_prompt(version):
    if version == 'evidence_review_v6':
        from .creative_review_v6 import build_review_prompt
        return build_review_prompt({})
    if version == 'evidence_review_v5':
        from .creative_review_v5 import build_review_prompt
        return build_review_prompt({})
    if version == 'evidence_review_v4':
        from .creative_review_v4 import build_review_prompt
        return build_review_prompt({})
    if version == 'evidence_review_v3':
        from .creative_review_v3 import build_review_prompt
        return build_review_prompt({})
    return {'evidence_review_v1': SCRIPT_REVIEW_PROMPT_V1,
            CANDIDATE_VERSION: SCRIPT_REVIEW_PROMPT_V2}[version]

def review_rules(version):
    if version == 'evidence_review_v6':
        return ''
    if version == 'evidence_review_v5':
        return ''
    if version == 'evidence_review_v4':
        return ''
    if version == 'evidence_review_v3':
        return ''  # v3 is a standalone prompt, never appended to legacy instructions.
    return {'evidence_review_v1': REVIEW_RULES_V1,
            CANDIDATE_VERSION: REVIEW_RULES_V2}[version]


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def _text(value,label):
    if not isinstance(value,str) or not value.strip():raise CreativeContractError(label+'必须为非空文本')

def validate_review(value,context):
    if not isinstance(value,dict):raise CreativeContractError('审核必须为对象')
    if not isinstance(value.get('issues'),list) or any(not isinstance(i,dict) for i in value['issues']):raise CreativeContractError('issues必须为对象数组')
    issues=validate_writer_check(value)
    if not isinstance(value.get('suggestions'),list):raise CreativeContractError('suggestions必须为数组')
    for row in value['suggestions']:
        if not isinstance(row,dict):raise CreativeContractError('suggestion必须为对象')
        for key in ('location','proposal','reason'):_text(row.get(key),'suggestion.'+key)
    ids=set()
    locations={b['id'] for b in context.get('script',{}).get('beats',[])}|{s['id'] for s in context.get('shots',{}).get('shots',[])}
    for issue in issues:
        for key in ('id','rule','contradiction'):_text(issue.get(key),'issue.'+key)
        if issue['id'] in ids:raise CreativeContractError('重复issue.id')
        ids.add(issue['id'])
        if issue['severity'] not in ('blocking','major'):raise CreativeContractError('可选或minor意见必须进入suggestions')
        if issue['location'] not in locations:raise CreativeContractError('issue.location必须是已有B/SH编号')
        refs=issue.get('evidence_refs')
        if not isinstance(refs,list) or not refs:raise CreativeContractError('缺少evidence_refs')
        actual=False
        for ref in refs:
            try:
                if not isinstance(ref,dict):raise ValueError()
                _text(ref.get('path'),'evidence.path');_text(ref.get('quote'),'evidence.quote')
                parts=ref['path'].split('.');target=context
                for part in parts:
                    if isinstance(target,list):
                        if not part.isdecimal():raise ValueError()
                        target=target[int(part)]
                    elif isinstance(target,dict):target=target[part]
                    else:raise ValueError()
                if isinstance(target,str):valid=ref['quote'] in target
                elif type(target) in (int,float):valid=ref['quote']==json.dumps(target)
                else:valid=False
                if not valid:raise ValueError()
                actual |= parts[0] in ('script','shots','production_design')
            except (KeyError,IndexError,TypeError,ValueError):
                raise CreativeContractError('审核引用路径或逐字证据无效: '+str(ref)) from None
        if not actual:raise CreativeContractError('问题缺少当前创作正文证据')
    return issues

def make_packet(key,review,context):
    validate_review(review,context)
    return {'schema':'creative_evidence_review_packet/v1','key':key,'review':review,'context':context,
            'context_sha256':digest(context),'review_sha256':digest(review),'automatic_media_submit':False}

def template(packet):
    return {'schema':'creative_evidence_review_decision/v1','packet_sha256':digest(packet),
            'reviewed_by':'assistant','reviewed_full_text':False,'summary':'',
            'decisions':[{'id':i['id'],'decision':None,'reason':''} for i in packet['review']['issues']],
            'additional_issues':[]}

def confirmed_issues(packet,decision):
    validate_review(packet['review'],packet['context'])
    if not isinstance(decision,dict) or decision.get('schema')!='creative_evidence_review_decision/v1':raise CreativeContractError('核实回执格式无效')
    if decision.get('packet_sha256')!=digest(packet):raise CreativeContractError('核实回执对应旧稿或旧审核')
    if decision.get('reviewed_by')!='assistant' or decision.get('reviewed_full_text') is not True:raise CreativeContractError('必须由助手实际阅读全文核实')
    _text(decision.get('summary'),'核实summary')
    rows=decision.get('decisions');known={i['id']:i for i in packet['review']['issues']}
    if not isinstance(rows,list) or any(not isinstance(r,dict) or not isinstance(r.get('id'),str) for r in rows):raise CreativeContractError('核实decisions无效')
    if len(rows)!=len(known) or {r['id'] for r in rows}!=set(known):raise CreativeContractError('必须逐项核实，不允许遗漏或重复')
    result=[]
    for row in rows:
        if row.get('decision') not in ('confirm','dismiss'):raise CreativeContractError('必须确认或驳回每个问题')
        _text(row.get('reason'),'核实reason')
        if row['decision']=='confirm':result.append(known[row['id']])
    added=decision.get('additional_issues')
    if not isinstance(added,list):raise CreativeContractError('additional_issues必须为数组')
    validate_review({'story_preserved':True,'issues':[*packet['review']['issues'],*added],
                     'suggestions':[],'calibration_focus':[]},packet['context'])
    return result+added
