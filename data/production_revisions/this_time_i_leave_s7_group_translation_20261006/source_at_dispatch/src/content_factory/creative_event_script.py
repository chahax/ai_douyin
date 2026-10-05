"""Lossless chronological-event authoring adapter for original scripts only."""
from copy import deepcopy
from .creative_workflow_contract import WRITER_TOOL_SCHEMAS,CreativeContractError

EVENT_SCHEMA=deepcopy(WRITER_TOOL_SCHEMAS['writer_script'])
beat=EVENT_SCHEMA['properties']['beats']['items']
for key in ('before','during','after','dialogue'):del beat['properties'][key]
beat['properties']['events']={'type':'array','minItems':3,'maxItems':5,'items':{'type':'object','additionalProperties':False,'required':['kind','speaker','text'],'properties':{'kind':{'type':'string','enum':['action','dialogue']},'speaker':{'type':'string'},'text':{'type':'string'}}}}
beat['required']=list(beat['properties'])
PATTERNS={('action','action','action'):(0,1,2,()),('action','dialogue','action','action'):(0,2,3,(1,)),('action','dialogue','action','dialogue','action'):(0,2,4,(1,3))}

def compile_event_script(raw):
    """Preserve every event in order; empty legacy slots use an explicit no-action marker."""
    if not isinstance(raw,dict) or set(raw)!=set(EVENT_SCHEMA['properties']):raise CreativeContractError('事件稿顶层字段不完整')
    if not isinstance(raw.get('beats'),list) or not raw['beats']:raise CreativeContractError('事件稿缺beats')
    output={k:deepcopy(v) for k,v in raw.items() if k!='beats'};output['beats']=[]
    for b in raw['beats']:
        if not isinstance(b,dict) or set(b)!=set(beat['properties']):raise CreativeContractError('事件节拍字段不完整')
        events=b['events']
        if not isinstance(events,list) or any(not isinstance(e,dict) or set(e)!={'kind','speaker','text'} for e in events):raise CreativeContractError('事件字段无效')
        kinds=tuple(e['kind'] for e in events)
        if any(k not in ('action','dialogue') for k in kinds) or kinds.count('dialogue')>2 or not events:
            raise CreativeContractError(f"{b['id']}事件类型/对白数量不能无损转换")
        for e in events:
            if not isinstance(e['text'],str) or not e['text'].strip():raise CreativeContractError('事件正文为空')
            if not isinstance(e['speaker'],str) or (e['kind']=='action' and e['speaker']!='') or (e['kind']=='dialogue' and not e['speaker'].strip()):raise CreativeContractError('事件说话人不符合kind')
        lines=[i for i,e in enumerate(events) if e['kind']=='dialogue']
        def action_text(group):
            return "\n".join(e['text'] for e in group) or '（无新增动作）'
        if len(lines)==2:
            first,second=lines
            segments=(events[:first],events[first+1:second],events[second+1:])
        elif len(lines)==1:
            first=lines[0];tail=events[first+1:]
            segments=(events[:first],tail[:1],tail[1:])
        else:
            segments=(events[:1],events[1:-1] if len(events)>1 else [],events[-1:] if len(events)>1 else [])
        out={k:deepcopy(v) for k,v in b.items() if k!='events'}
        out.update(**dict(zip(('before','during','after'),map(action_text,segments))),dialogue=[{'speaker':events[i]['speaker'],'text':events[i]['text']} for i in lines])
        output['beats'].append(out)
    return output
