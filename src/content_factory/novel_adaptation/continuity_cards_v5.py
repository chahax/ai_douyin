"""Versioned source facts, production choices and final-candidate handoffs."""
from copy import deepcopy
from pathlib import Path
from . import contracts as c
from .chapter_memory_v4 import source_ids

POLICY = '''continuity是独立的跨章交接，不是新剧情。facts只保存有原文依据的人物身份/关系/年龄等稳定事实；designs是制作选择而非小说事实。二者不得混用。
沿用已有卡的语义键和值，不换名字另建同一人物或同一房间来绕过继承。只补本章必需的新增信息；变更既有卡须有当前原文证据，不能因为喜好重新设计。
年龄只在原文明示时确定，外观估计保留“约/看起来”的性质；未明示年龄写儿童/少年等宽泛形象，不自行指定数字或青春期外观。后文尚未读取不意味着全书无据。
previous_handoff是上一章最终修订候选的实际结束状态，当前开场先核对source是否紧接；紧接则继承时间、地点、在场人、持物与未完成行动，后续按原文变化。
已有房型、门窗和主要家具关系保持一致；原文明确冲突优先原文，报告需要更正的卡，不悄悄改造。旧失败分析不是事实。小措辞和普通微动作只记备注。
'''
CARDS = POLICY + '''从source提取本章必要的共享资料增量。previous_cards为已有版本，返回updates即可，未变化的卡不要重复。
每卡key用稳定简短语义键。kind=fact须有原文source_ids；kind=design只选择本段确实需要的普通造型或空间，不用设计补人物年龄/关系/经历/绝对年月时刻。
初次出现的居住空间建立一份足够简单、兼容当前原文的布局，此后同屋复用；不要为了完整性猜全屋结构。衣服允许普通制作选定并持续复用。
不收集本章剧情流水账，不保存人物猜测为事实。reason说明新增或更正依据。'''
HANDOFF = POLICY + '''只从final_candidate抽取结尾实际状态，不改剧本、不总结整章。输出time/place/people/held_props/unfinished_action，用简短文字；不知道写未明确。
candidate_quotes逐字摘取能证明结尾状态的连续片段，source_ids引用相应原文。不得把中间场景或计划当结尾，不把人物栏过时名单当实际在场。
提取结果仅用于衔接，不等于批准整章剧本。'''
AUDIT = POLICY + '''独立核对proposal。stage=cards时检查增量是否有据、是否把年龄推测/猜测写为事实、是否重新发明已有布局、是否混入剧情状态；合理普通布景不必原文逐件出现。
stage=handoff时检查结尾状态是否准确来自最终候选并与source兼容。只报告会误导后续生成的实质问题；无需摘全句对白或罗列每个微动作。
passed与issues为空一致。不要要求人工确认；问题具体写清需改哪里和原因。'''

def cards_schema(source):
    return c.obj(updates=c.array(c.obj(key=c.TEXT,kind=c.choices(['fact','design']),value=c.TEXT,
        source_ids=c.refs(source_ids(source),0),reason=c.TEXT)))

def handoff_schema(source):
    return c.obj(time=c.TEXT,place=c.TEXT,people=c.TEXT,held_props=c.TEXT,unfinished_action=c.TEXT,
        candidate_quotes=c.array(c.TEXT,1),source_ids=c.refs(source_ids(source)))

AUDIT_SCHEMA=c.obj(passed={'type':'boolean'},issues=c.array(c.TEXT))

def checked_audit(audit):
    if c.schema_issues(audit,AUDIT_SCHEMA,'audit') or audit['passed'] != (not audit['issues']):
        raise ValueError('continuity_audit_contract')
    if not audit['passed']:raise ValueError('continuity_not_approved')

def merge_cards(previous,proposal,source,audit):
    checked_audit(audit)
    faults=c.schema_issues(proposal,cards_schema(source),'cards')
    if faults:raise c.ContractError(faults)
    result=deepcopy(previous);by={x['key']:i for i,x in enumerate(result)};seen=set()
    for row in proposal['updates']:
        key=row['key']
        if key in seen:raise ValueError('duplicate_card_key')
        seen.add(key)
        if row['kind']=='fact' and not row['source_ids']:raise ValueError('fact_without_source')
        if key in by:
            old=result[by[key]]
            if row==old:continue
            if not row['source_ids']:raise ValueError('card_change_requires_source')
            if row['kind']!=old['kind']:raise ValueError('card_kind_cannot_be_promoted')
            result[by[key]]=deepcopy(row)
        else:by[key]=len(result);result.append(deepcopy(row))
    return result

def bind_handoff(proposal,source,candidate,candidate_path,audit):
    checked_audit(audit)
    faults=c.schema_issues(proposal,handoff_schema(source),'handoff')
    if faults:raise c.ContractError(faults)
    if any(q not in candidate for q in proposal['candidate_quotes']):raise ValueError('handoff_quote_not_in_final_candidate')
    return dict(state=deepcopy(proposal),candidate_digest=c.digest(candidate),
        candidate_path=str(Path(candidate_path).resolve()),source_digest=c.digest(source),semantic_guarantee=False)

def candidate_lines(candidate):
    return {f'L{i:04}':line for i,line in enumerate(candidate.splitlines(),1) if line.strip()}

def address_schema(candidate):
    ids=list(candidate_lines(candidate))
    return c.obj(**{key:c.obj(supported={'type':'boolean'},line_ids=c.refs(ids,0))
        for key in ('time','place','people','held_props','unfinished_action')})

def apply_addresses(proposal,candidate,addresses):
    faults=c.schema_issues(addresses,address_schema(candidate),'handoff_addresses')
    if faults:raise c.ContractError(faults)
    if any(not x['supported'] or not x['line_ids'] for x in addresses.values()):raise ValueError('handoff_state_not_supported_by_candidate')
    lines=candidate_lines(candidate);ids=list(dict.fromkeys(i for x in addresses.values() for i in x['line_ids']))
    result=deepcopy(proposal);result['candidate_quotes']=[lines[i] for i in ids]
    return result,dict(method='select_exact_candidate_line_ids_only',addresses=addresses,
        candidate_digest=c.digest(candidate),original_proposal_digest=c.digest(proposal),state_fields_unchanged=True)

def validate_bundle(bundle):
    if set(bundle)!={'version','chapter','cards','previous_handoff','parent_digest'} or bundle['version']!='continuity_cards_v5':raise ValueError('invalid_continuity_bundle')
    keys=[x['key'] for x in bundle['cards']]
    if len(keys)!=len(set(keys)):raise ValueError('duplicate_card_key')
    if any(x['kind']=='fact' and not x['source_ids'] for x in bundle['cards']):raise ValueError('fact_without_source')
    h=bundle['previous_handoff']
    if (bundle['chapter']==1)!=(h is None):raise ValueError('previous_handoff_required')
    if h:
        candidate=Path(h['candidate_path']).read_text(encoding='utf-8')
        if c.digest(candidate)!=h['candidate_digest']:raise ValueError('stale_handoff_candidate_changed')
        if any(q not in candidate for q in h['state']['candidate_quotes']):raise ValueError('stale_handoff_quotes')

class BoundTransport:
    """Same context for author, independent reviewer and repairs; opt-in only."""
    def __init__(self,transport,bundle):self.transport,self.bundle=transport,deepcopy(bundle)
    def __getattr__(self,name):return getattr(self.transport,name)
    def call(self,node,role,prompt,payload,schema,**kwargs):
        validate_bundle(self.bundle)
        return self.transport.call(node,role,prompt+'\n'+POLICY,
            {**payload,'continuity':self.bundle},schema,**kwargs)
