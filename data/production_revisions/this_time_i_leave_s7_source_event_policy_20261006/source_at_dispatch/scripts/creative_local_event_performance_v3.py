"""Model-authored atomic event plan, then complete performance; strict projection."""
from copy import deepcopy
import json
from jsonschema import Draft202012Validator
from scripts import creative_synchronous_prop_contract_v3 as compact
from scripts import step_index_physical_adapter_v5 as physical
VERSION="local_event_then_performance/v3_note_bundle"


def obj(p):return {'type':'object','properties':p,'required':list(p),'additionalProperties':False}


def focus(inp):
    shot=next(s for s in physical._shots(inp['direction']) if s['shot_id']==inp['shot_id'])
    sources=physical._raw_sources(inp['context'])
    return {'current_shot':shot,'ordered_complete_current_steps':[{'source_step_ref':ref,**sources[ref]} for ref in shot['source_step_refs']], 'actual_start_state':deepcopy(inp['start_state'])}


def plan_schema(inp):
    """Encode established physical field and reaction relations before projection."""
    base=compact.build_schema(inp)
    event_base=base['properties']['actions']['items']['properties']['groups']['items']
    chars=[c['id'] for c in inp['context']['static_visual_manifest']['characters']]
    props=[p['id'] for p in inp['context']['static_visual_manifest']['props']]
    def operation(kinds,target):
        return obj({'kind':{'enum':kinds},'actor':{'enum':chars},'target':target,'value':{'type':'string','minLength':1}})
    operation_schema={'anyOf':[{'type':'null'},
        operation(['move','gaze','affect','stand','face'],{'const':''}),
        operation(['take','place','pass','slide'],{'enum':props}),
        operation(['sit'],{'type':'string','minLength':1}), compact.batch_schema(inp)]}
    shot=focus(inp)['current_shot'];sources=physical._raw_sources(inp['context'])
    ordered=[ref for ref in shot['source_step_refs'] if sources[ref]['kind']=='action']
    definitions=[]
    for ref in ordered:
        requirements=[q for q in shot['performance_requirements'] if q['relation']!='during' and q['reaction_ref']==ref]
        ids=[q['id'] for q in requirements]
        satisfies={'type':'array','uniqueItems':True,'maxItems':len(ids),'items':{'enum':ids} if ids else {'type':'string'}}
        event=obj({'intent':{'type':'string','minLength':1},'subject':event_base['properties']['subject'],
                   'operation':deepcopy(operation_schema),'satisfies':satisfies})
        if requirements:
            event['allOf']=[{'if':{'properties':{'satisfies':{'contains':{'const':q['id']}}}},
                             'then':{'properties':{'operation':{'type':'null'},'subject':{'const':q['subject']}}}}
                            for q in requirements]
        definitions.append(obj({'source_step_ref':{'const':ref},'events':{'type':'array','minItems':1,'items':event}}))
    actions={'type':'array','minItems':len(ordered),'maxItems':len(ordered)}
    if definitions:actions.update(prefixItems=definitions,items=False)
    return obj({'actions':actions})


def slots(plan):
    return [{'slot':f'A{ai}E{ei}','source_step_ref':a['source_step_ref'],**deepcopy(e)} for ai,a in enumerate(plan['actions']) for ei,e in enumerate(a['events'])]


def plan_as_compact(plan,inp):
    Draft202012Validator(plan_schema(inp)).validate(plan)
    shot=focus(inp)['current_shot'];minimums={q['id']:q['minimum_seconds'] for q in shot['performance_requirements']}
    return {'dialogue_performance':'仅状态事件计划预检，不是实际表演交付。','actions':[{'source_step_ref':a['source_step_ref'],'groups':[{'seconds':max([1.,*[minimums[r] for r in e['satisfies']]]),'subject':e['subject'],'performance':e['intent'],'operation':deepcopy(e['operation']),'satisfies':deepcopy(e['satisfies'])} for e in a['events']]} for a in plan['actions']]}


def plan_messages(inp,feedback=None):
    rule='先只提交当前镜全部原action的完整状态事件计划，不写秒数或表演长文。每action source_step_ref/events；每event恰intent/subject/operation/satisfies。operation是null、恰kind/actor/target/value对象，或同叠三色便利贴恰三项的同步数组。普通事件最多一个变化；同叠三张take同事件，place在后续另一事件；全部操作读取事件开始态。intent简短说明原步骤中的可见事件，不能一句藏多个道具转移；三色便利贴成员P03_Y/P03_P/P03_B齐全、同actor同kind，整叠同步取，再整体展开同步放；不用三次揭压。取时同持有位置，放时同支持面可不同位置。face/gaze值在value,target空；take/place/slide目标是道具ID，value非空真实持有位置或surface:支持面ID:区域。move为人物整体移动，不是手移动。只记录真实原动作，不做未来镜，对白由后续程序插原句，不能在事件中说话。反应保持事件operation=null且正确人物，仅绑定当前要求ID。'
    return [{'role':'system','content':rule},{'role':'user','content':json.dumps({'read_only_complete_context_and_direction':inp,'current_only':focus(inp),'verified_faults':feedback or {},'task':'提交上述当前镜完整新事件计划，所有原动作完整、有明确真实状态；禁止拼接旧失败稿。'},ensure_ascii=False,separators=(',',':'))}]


def performance_schema(plan):
    ids=[s['slot'] for s in slots(plan)]
    return obj({'dialogue_performance':{'type':'string','minLength':1},'performances':{'type':'array','minItems':len(ids),'maxItems':len(ids),'items':obj({'slot':{'enum':ids},'seconds':{'type':'number','exclusiveMinimum':0},'performance':{'type':'string','minLength':1}})}})


def performance_messages(inp,plan,feedback=None):
    rule='为已核对的当前镜全部事件写完整自然表演和各自实际秒数。根对象只有dialogue_performance/performances；每行slot/seconds/performance，所有slots按序恰好一次。事件操作来自同一生成模型的完整状态计划，不能更改、合并、省略或在表演里藏新状态。原对白由程序插完整原句，dialogue_performance仅该句自然语气/面部/呼吸，不藏身体动作或改台词；无对白写非空本镜无对白。反应保持须给足当前要求最低时间且可读，不机械空等。所有当前事件完整重交，不拼接旧表演。'
    return [{'role':'system','content':rule},{'role':'user','content':json.dumps({'read_only_complete_context_and_direction':inp,'current_only':focus(inp),'model_authored_complete_event_plan':plan,'fixed_events_to_perform':slots(plan),'verified_faults':feedback or {},'task':'逐事件写可制作完整表演与真实秒数，重要说话/反应不能压缩。'},ensure_ascii=False,separators=(',',':'))}]


def performance_as_compact(doc,plan,inp):
    Draft202012Validator(performance_schema(plan)).validate(doc)
    expected=slots(plan)
    if [r['slot'] for r in doc['performances']]!=[s['slot'] for s in expected]:raise ValueError('performance slots must be complete, unique and ordered')
    rows=iter(doc['performances']);actions=[]
    for action in plan['actions']:
        groups=[]
        for event in action['events']:
            perf=next(rows)
            groups.append({'seconds':perf['seconds'],'subject':event['subject'],'performance':perf['performance'],'operation':deepcopy(event['operation']),'satisfies':deepcopy(event['satisfies'])})
        actions.append({'source_step_ref':action['source_step_ref'],'groups':groups})
    result={'dialogue_performance':doc['dialogue_performance'],'actions':actions}
    compact.derive_local(result,inp)
    return result
