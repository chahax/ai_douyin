"""Source interpretation is generated before the reviewer sees the candidate."""
from typing import Literal,TypedDict
from pydantic import Field
from langgraph.graph import StateGraph,START,END
from .novel_evidence_graph_v1 import Strict,source_catalog
from .novel_evidence_protocol_v2 import inline_schema
from .novel_focus_review_v4 import context_for,Decision,validate_decision,PROMPT
class SourceFact(Strict):
    id:str
    statement:str=Field(min_length=1)
    certainty:Literal['established','uncertain','conditional','plan','original_novel_future']
    source_ids:list[str]=Field(min_length=1)
class SourceFacts(Strict):
    facts:list[SourceFact]=Field(min_length=1,max_length=20)
class State(TypedDict,total=False):
    cursor:int
    source_facts:dict
    findings:list[dict]
    status:str

def blind_payload(claim,catalog):
    data=context_for(claim,catalog)
    return {k:v for k,v in data.items() if k!='fixed_candidate'}

def build_graph(source,claims,caller,checkpointer=None):
    catalog=source_catalog(source);known={x['id'] for x in catalog}
    def read_source(state):
        claim=claims[state['cursor']]
        prompt='你尚未看到任何候选总结。只解读focused_context原文及完整相关章节，不猜要审核什么。记录焦点段明确写出的行为/状态及原文明说无法确定的状态，各项独立。没有确定的心理/信念不能推成肯定或否定；条件、计划、原书未来不当已发生。用原段ID给出处，不抄写原文，不做剧情补足。'
        raw=caller(f'SOURCE_{state["cursor"]+1:02}',prompt,blind_payload(claim,catalog),inline_schema(SourceFacts.model_json_schema()))
        value=SourceFacts.model_validate(raw).model_dump();ids=[]
        for f in value['facts']:
            ids.append(f['id'])
            if any(i not in known for i in f['source_ids']):raise ValueError('unknown_source')
        if len(ids)!=len(set(ids)):raise ValueError('duplicate_source_fact')
        return {'source_facts':value}
    def compare(state):
        claim=claims[state['cursor']];payload=context_for(claim,catalog)
        payload['independent_source_reading']=state['source_facts']
        prompt=PROMPT+' independent_source_reading在看到候选之前生成，可用于交叉核对，但原文始终优先。候选若把原文未确定状态变成确定状态，即使听起来合理也不能判supported。'
        schema=inline_schema(Decision.model_json_schema());schema['properties']['claim_id']['const']=claim['id']
        raw=caller(f'COMPARE_{state["cursor"]+1:02}',prompt,payload,schema)
        result=validate_decision(raw,claim,catalog)
        return {'cursor':state['cursor']+1,'findings':state['findings']+[result]}
    def finish(state):return {'status':'pending_independent_acceptance' if all(f['accepted'] for f in state['findings']) else 'needs_revision'}
    g=StateGraph(State);g.add_node('read_source',read_source);g.add_node('compare',compare);g.add_node('finish',finish)
    g.add_edge(START,'read_source');g.add_edge('read_source','compare')
    g.add_conditional_edges('compare',lambda s:'more' if s['cursor']<len(claims) else 'done',{'more':'read_source','done':'finish'});g.add_edge('finish',END)
    return g.compile(checkpointer=checkpointer)
