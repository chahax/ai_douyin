"""Literal predicate/qualifier checking and explicitly scoped chapter materials."""
from typing import Literal,TypedDict
from pydantic import Field
from langgraph.graph import StateGraph,START,END
from .novel_evidence_graph_v1 import Strict,source_catalog
from .novel_evidence_protocol_v2 import inline_schema

Scope=Literal['current','past','original_novel_future','conditional','plan','unknown']
class Fact(Strict):
    id:str=Field(min_length=1)
    statement:str=Field(min_length=1)
    time_scope:Scope
    source_ids:list[str]=Field(min_length=1)
class Material(Strict):
    claims:list[Fact]=Field(min_length=1,max_length=80)
class Judgment(Strict):
    claim_id:str
    verdict:Literal['supported','contradicted','not_stated','uncertain']
    claim_fragment:str=Field(min_length=1)
    claim_reading:str=Field(min_length=1)
    source_reading:str=Field(min_length=1)
    source_ids:list[str]=Field(min_length=1)
    reason:str=Field(min_length=1)
class Review(Strict):
    findings:list[Judgment]=Field(min_length=1,max_length=3)
class Omission(Strict):
    source_ids:list[str]=Field(min_length=1)
    missing_content:str=Field(min_length=1)
    why_important:str=Field(min_length=1)
class Coverage(Strict):
    omissions:list[Omission]

EXTRACT='''完整阅读目标章，不限精选条数，不要为凑数量省略章末、关系、转交、否定、条件、保护动作与冲突。
按原文顺序提取完整关键材料，每条一个主要命题，独立time_scope。不得将原书后续、当前回忆行为、实际过去混合一条。
当前(actual current)、当前之前past、原书未来original_novel_future、条件conditional、计划plan、无法确定unknown。
source_ids从固定原段目录选择；只给ID，不重抄引文。ID唯一。80是输出技术保护上界，不是精选数量目标。
未交代的事不补齐。疑似笔误保留不确定，不擅自新增人物。不要写小说简介或剧本。'''
REVIEW='''你只判断本批最多3条材料是否忠实原文，不重写它们。
第一步：原样截取claim_fragment，它必须是候选statement的连续子串，包含你准备检查的关键谓词及限定词。
第二步：分别解释候选实际表达(claim_reading)与原文表达(source_reading)，保留先后、否定、条件、因果、时间层和不确定性。
第三步：supported=同一含义被原文直接或完整上下文支持；contradicted=原文明确相反；not_stated=原文未交代；uncertain=多解或缺必要时间层。
不要替换候选谓词后再反驳替换出来的含义；不要把主张没说的话加进去，不以单词缺少完全相同表面形式否定合理上下文。
逐字关注前/后、已/未、如果、可能、全部、只有等限定，不得拆掉关系后只核对两端事件。没有说是否相信，不等于已经不相信。
time_scope是候选的一部分，必须检查；unknown不等于事实成立。原书未来必须与当前区分。
reason解释你判断是否存在真正矛盾；依据不足不能编造相反事实。每个claim_id恰好一个finding。引用ID需真实存在。
只提交一次结果，JSON数组用[]。'''
COMPLETE='''完整重读原章并核对所有候选材料，找影响理解的重要遗漏（人物关系、转交/拒绝、冲突、入场、因果、章末承接）。
没有引用某段不等于遗漏，必须读候选语义。普通重复修饰不用补。只列真正未保留且有原文的内容，不能发明必须存在的情节。'''

def validate_material(raw,catalog):
    value=Material.model_validate(raw).model_dump();known={x['id'] for x in catalog};ids=[]
    for f in value['claims']:
        ids.append(f['id'])
        if any(i not in known for i in f['source_ids']):raise ValueError('unknown_source')
    if len(ids)!=len(set(ids)):raise ValueError('duplicate_id')
    return value

def validate_review(raw,batch,catalog):
    value=Review.model_validate(raw).model_dump();claims={x['id']:x for x in batch};known={x['id'] for x in catalog}
    if sorted(x['claim_id'] for x in value['findings'])!=sorted(claims):raise ValueError('missing_or_duplicate_review')
    for f in value['findings']:
        if f['claim_fragment'] not in claims[f['claim_id']]['statement']:raise ValueError('rewritten_claim_fragment')
        if any(i not in known for i in f['source_ids']):raise ValueError('unknown_source')
    return value

class State(TypedDict,total=False):
    claims:list[dict]
    cursor:int
    findings:list[dict]
    omissions:list[dict]
    status:str

def build_graph(source,caller,checkpointer=None,seeded=False):
    catalog=source_catalog(source)
    def extract(state):
        raw=caller('EXTRACT',EXTRACT,{'source_catalog':catalog},inline_schema(Material.model_json_schema()))
        return {'claims':validate_material(raw,catalog)['claims'],'cursor':0,'findings':[]}
    def review(state):
        i=state['cursor'];batch=state['claims'][i:i+3]
        raw=caller(f'REVIEW_{i//3+1:02}',REVIEW,{'source_catalog':catalog,'claims':batch},inline_schema(Review.model_json_schema()))
        return {'cursor':i+len(batch),'findings':state['findings']+validate_review(raw,batch,catalog)['findings']}
    def complete(state):
        raw=caller('COMPLETENESS',COMPLETE,{'source_catalog':catalog,'claims':state['claims']},inline_schema(Coverage.model_json_schema()))
        value=Coverage.model_validate(raw).model_dump();known={x['id'] for x in catalog}
        if any(i not in known for o in value['omissions'] for i in o['source_ids']):raise ValueError('unknown_source')
        return value
    def finish(state):
        good=not state.get('omissions') and all(f['verdict']=='supported' for f in state['findings'])
        return {'status':'pending_independent_acceptance' if good else 'needs_revision'}
    graph=StateGraph(State)
    for name,fn in [('extract',extract),('review',review),('complete',complete),('finish',finish)]:graph.add_node(name,fn)
    graph.add_edge(START,'review' if seeded else 'extract');graph.add_edge('extract','review')
    graph.add_conditional_edges('review',lambda s:'more' if s['cursor']<len(s['claims']) else 'done',{'more':'review','done':'finish' if seeded else 'complete'})
    graph.add_edge('complete','finish');graph.add_edge('finish',END)
    return graph.compile(checkpointer=checkpointer)
