"""Program-bound candidate text; one claim and its full source chapters per review."""
from typing import Literal,TypedDict
from pydantic import Field
from langgraph.graph import StateGraph,START,END
from .novel_evidence_graph_v1 import Strict,source_catalog
from .novel_literal_review_v3 import Scope
from .novel_evidence_protocol_v2 import inline_schema
class Decision(Strict):
    claim_id:str
    decision:Literal['supported','contradicted','not_stated','uncertain']
    source_time_scope:Scope
    source_ids:list[str]=Field(min_length=1)
    reason:str=Field(min_length=1)
    temporal_reason:str=Field(min_length=1)

PROMPT='''核查这一条固定原句。不要抄写或改写候选再审，不要信任任何旧审核。
先阅读focused_context，然后阅读完整相关章节，尤其关注引用段前后描述的状态。判断的是主张所有限定是否成立，而不是它的大致主题。
反事实/原书未来不可当已经发生。没有交代是否相信与明确不相信不同。说话人可以用身份自称。不能把某人的意识恢复等同另一个身体动作。
先后关系必须以原文实际行动顺序为准，不按候选的顺序复述。证据只支持一部分时不能判整条supported。
给出原文该命题的source_time_scope和temporal_reason；decision评估候选事实、先后、确定性与时间层。未交代用not_stated，多解用uncertain。只提交一次。'''
def context_for(claim,catalog):
    index={p['id']:i for i,p in enumerate(catalog)}
    anchors=claim['source_ids']
    if not anchors or any(i not in index for i in anchors):raise ValueError('anchors_required')
    chapters={catalog[index[i]]['chapter'] for i in anchors};focus=set()
    for id in anchors:
        n=index[id]
        for j in range(max(0,n-8),min(len(catalog),n+9)):
            if catalog[j]['chapter']==catalog[n]['chapter']:focus.add(j)
    return {'fixed_candidate':claim,'focused_context':[catalog[j] for j in sorted(focus)],'complete_related_chapters':[p for p in catalog if p['chapter'] in chapters]}

def validate_decision(raw,claim,catalog):
    v=Decision.model_validate(raw).model_dump();known={p['id'] for p in catalog}
    if v['claim_id']!=claim['id'] or any(i not in known for i in v['source_ids']):raise ValueError('binding_mismatch')
    scope_ok=claim['time_scope']!='unknown' and v['source_time_scope']==claim['time_scope']
    return {**v,'program_scope_match':scope_ok,'accepted':v['decision']=='supported' and scope_ok}

class State(TypedDict,total=False):
    cursor:int
    findings:list[dict]
    status:str

def build_graph(source,claims,caller,checkpointer=None):
    catalog=source_catalog(source)
    def review(state):
        n=state['cursor'];claim=claims[n];payload=context_for(claim,catalog)
        schema=inline_schema(Decision.model_json_schema());schema['properties']['claim_id']['const']=claim['id']
        raw=caller(f'FOCUS_{n+1:02}',PROMPT,payload,schema)
        return {'cursor':n+1,'findings':state['findings']+[validate_decision(raw,claim,catalog)]}
    def finish(state):return {'status':'pending_independent_acceptance' if all(f['accepted'] for f in state['findings']) else 'needs_revision'}
    g=StateGraph(State);g.add_node('review',review);g.add_node('finish',finish);g.add_edge(START,'review')
    g.add_conditional_edges('review',lambda s:'more' if s['cursor']<len(claims) else 'done',{'more':'review','done':'finish'});g.add_edge('finish',END)
    return g.compile(checkpointer=checkpointer)
