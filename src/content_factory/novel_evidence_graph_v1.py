"""LangGraph experimental evidence audit. No account or publishing integration."""
from typing import Literal,TypedDict,Callable
from pydantic import BaseModel,ConfigDict,Field
from langgraph.graph import StateGraph,START,END

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)

class Claim(Strict):
    id:str=Field(min_length=1)
    statement:str=Field(min_length=1)
    source_ids:list[str]

class Claims(Strict):
    claims:list[Claim]=Field(min_length=1,max_length=18)

class Atom(Strict):
    statement:str=Field(min_length=1)
    verdict:Literal['supported','contradicted','not_stated','uncertain']
    source_ids:list[str]
    reason:str=Field(min_length=1)

class Finding(Strict):
    claim_id:str
    atoms:list[Atom]=Field(min_length=1,max_length=12)

class Findings(Strict):
    findings:list[Finding]=Field(min_length=1,max_length=3)

class State(TypedDict,total=False):
    claims:list[dict]
    cursor:int
    findings:list[dict]
    accepted:list[dict]
    rejected:list[dict]
    status:str

def source_catalog(source):
    out=[]
    for ch in source['chapters']:
        for i,line in enumerate(ch['text'].splitlines(),1):
            if line.strip():out.append({'id':f"CH{ch['index']}-P{i:03}",'chapter':ch['index'],'text':line})
    return out

AUDIT_PROMPT='''你是证据核对员，只核查本批最多3条主张，不写背景或剧本。
候选是待核文字，不是事实。先将每条拆成最小可核命题，每个姓名、修饰、数量、时间、因果、否定和额外前提都须覆盖，不可只核对其中正确部分。
逐个命题判supported（原文支持）、contradicted（原文明确相反）、not_stated（材料未交代）、uncertain（多解且不能排除）。原文没说不能当成相反事实。
source_ids只能选原文目录ID，引用内容由程序读取，不重抄引文；支持和反驳都要给真正有关的原段。未交代可为空，但reason必须说明核查范围。
检查主张中当前发生/既往/原书未来/计划/条件及人物视角是否匹配。合理口语称谓可以自称，不能只看一个词。不要为凑确定性编理由。
对每个输入claim_id恰好给一个finding。只提交一次结果。'''
EXTRACT_PROMPT='''完整阅读原文，针对target_chapter提取10至18条关键人物、事件、背景命题，为后续编剧使用。
每条只表达一个可核查的主要事实，计划/条件/原书未来须在statement明确表达。不要把未交代内容补齐。人物称谓据上下文理解，无法确定留在措辞中。
每条id唯一，source_ids引用实际原文目录，至少一个来自目标章。参考章不等于目标章发生的事件。只提交一次结果。'''

def validate_claims(raw,catalog,target):
    value=Claims.model_validate(raw).model_dump();known={x['id']:x for x in catalog};seen=set()
    for c in value['claims']:
        if c['id'] in seen:raise ValueError('duplicate_claim_id')
        seen.add(c['id'])
        if not c['source_ids'] or any(i not in known for i in c['source_ids']):raise ValueError('invalid_source_id')
        if not any(known[i]['chapter']==target for i in c['source_ids']):raise ValueError('target_evidence_missing')
    return value

def validate_findings(raw,batch,catalog):
    value=Findings.model_validate(raw).model_dump();known={x['id'] for x in catalog}
    ids=[x['claim_id'] for x in value['findings']]
    if sorted(ids)!=sorted(x['id'] for x in batch):raise ValueError('findings_missing_or_duplicate')
    for f in value['findings']:
        for a in f['atoms']:
            if any(i not in known for i in a['source_ids']):raise ValueError('invalid_source_id')
            if a['verdict'] in ('supported','contradicted') and not a['source_ids']:raise ValueError('verdict_requires_evidence')
    return value

def build_graph(source,caller:Callable,checkpointer=None,target=1,seeded=False):
    catalog=source_catalog(source)
    def extract(state):
        raw=caller('EXTRACT',EXTRACT_PROMPT,{'target_chapter':target,'source_catalog':catalog},Claims.model_json_schema())
        return {'claims':validate_claims(raw,catalog,target)['claims'],'cursor':0,'findings':[]}
    def audit(state):
        start=state.get('cursor',0);batch=state['claims'][start:start+3]
        raw=caller(f'AUDIT_{start//3+1:02}',AUDIT_PROMPT,{'source_catalog':catalog,'claims':batch},Findings.model_json_schema())
        findings=validate_findings(raw,batch,catalog)['findings']
        return {'cursor':start+len(batch),'findings':state.get('findings',[])+findings}
    def finish(state):
        byid={x['claim_id']:x for x in state['findings']};accepted=[];rejected=[]
        for c in state['claims']:
            f=byid[c['id']]
            (accepted if all(a['verdict']=='supported' for a in f['atoms']) else rejected).append(c)
        return {'accepted':accepted,'rejected':rejected,'status':'evidence_checked' if not rejected else 'needs_revision'}
    g=StateGraph(State);g.add_node('extract',extract);g.add_node('audit',audit);g.add_node('finish',finish)
    g.add_edge(START,'audit' if seeded else 'extract');g.add_edge('extract','audit')
    g.add_conditional_edges('audit',lambda s:'more' if s['cursor']<len(s['claims']) else 'done',{'more':'audit','done':'finish'})
    g.add_edge('finish',END)
    return g.compile(checkpointer=checkpointer)
