"""Independent temporal/relationship and material-completeness graph gates."""
from typing import TypedDict,Literal
from pydantic import Field
from langgraph.graph import StateGraph,START,END
from .novel_evidence_graph_v1 import Strict,source_catalog
from .novel_evidence_protocol_v2 import inline_schema

class Gap(Strict):
    kind:Literal['timeline','causality','certainty','missing_event','missing_relationship']
    claim_ids:list[str]
    source_ids:list[str]=Field(min_length=1)
    explanation:str=Field(min_length=1)

class Gate(Strict):
    checked_claim_ids:list[str]
    issues:list[Gap]

class GuardState(TypedDict,total=False):
    temporal:dict
    completeness:dict
    status:str

def validate_gate(value,claims,catalog):
    r=Gate.model_validate(value).model_dump();ids={c['id'] for c in claims};known={p['id'] for p in catalog}
    if sorted(r['checked_claim_ids'])!=sorted(ids):raise ValueError('unchecked_or_duplicate_claims')
    for issue in r['issues']:
        if any(i not in ids for i in issue['claim_ids']) or any(i not in known for i in issue['source_ids']):raise ValueError('unknown_reference')
    return r

def build_guards(source,claims,caller,checkpointer=None):
    catalog=source_catalog(source)
    base='输入原文是唯一事实来源，候选可能不完整或存在错误。给出处ID，不抄引文。逐条登记checked_claim_ids，不使用旧审核意见。只报有依据的问题，不强行找错。'
    def temporal(state):
        prompt=base+'审核完整主张的关系而不只拆词：先后顺序、否定、条件、可能/确定、原书未来与当前是否保留。尤其检查主张孤立进入剧本后是否会让未来事件变成已发生。原文没有交代不能说已确定。issues中的kind只能timeline/causality/certainty。'
        raw=caller('RELATION_GUARD',prompt,{'source_catalog':catalog,'claims':claims},inline_schema(Gate.model_json_schema()))
        result=validate_gate(raw,claims,catalog)
        if any(i['kind'] not in ['timeline','causality','certainty'] for i in result['issues']):raise ValueError('guard_kind')
        return {'temporal':result}
    def completeness(state):
        prompt=base+'从完整原章重新阅读，检查影响剧情理解的重要事件、人物关系、冲突或结尾是否在候选材料中丢失；普通重复修饰不强求保留。不要把没有引用某段直接等同漏情节，要读候选实际内容。issues中的kind只能missing_event/missing_relationship；缺失无对应claim时claim_ids用空数组。'
        raw=caller('COMPLETENESS_GUARD',prompt,{'source_catalog':catalog,'claims':claims},inline_schema(Gate.model_json_schema()))
        result=validate_gate(raw,claims,catalog)
        if any(i['kind'] not in ['missing_event','missing_relationship'] for i in result['issues']):raise ValueError('guard_kind')
        return {'completeness':result}
    def finish(state):
        return {'status':'needs_revision' if state['temporal']['issues'] or state['completeness']['issues'] else 'pending_independent_acceptance'}
    g=StateGraph(GuardState);g.add_node('temporal',temporal);g.add_node('completeness',completeness);g.add_node('finish',finish)
    g.add_edge(START,'temporal');g.add_edge('temporal','completeness');g.add_edge('completeness','finish');g.add_edge('finish',END)
    return g.compile(checkpointer=checkpointer)
