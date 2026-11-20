"""Story first, then explicit screen action; source facts stay upstream."""
from copy import deepcopy
import json
from jsonschema import validate as schema_validate
from .corpus_screenplay_v1 import digest

VERSION='story_first_contract/v5'
STAGES=('foundation','story','staging')
TEXT={'type':'string','minLength':1,'maxLength':240}
def obj(**fields):return {'type':'object','properties':fields,'required':list(fields),'additionalProperties':False}
def arr(item,n=0):return {'type':'array','items':item,'minItems':n}
def enum(values):return {'type':'string','enum':list(values)}
def refs(ids,n=1):return {**arr(enum(ids),n),'uniqueItems':True}
def paragraphs(source):
    return [{'id':f'CH{c["index"]}-P{i:03}', 'chapter':c['index'],'text':line}
            for c in source['chapters'] for i,line in enumerate(c['text'].splitlines(),1) if line.strip()]

def foundation_schema(source):
    evidence=refs([p['id'] for p in paragraphs(source)])
    return obj(world=TEXT,characters=arr(obj(id=TEXT,name=TEXT,source_ids=evidence),1),
        places=arr(obj(id=TEXT,name=TEXT,source_ids=evidence),1),
        relationships=arr(obj(subject=TEXT,object=TEXT,relation=TEXT,source_ids=evidence)),
        constraints=arr(obj(statement=TEXT,source_ids=evidence)),visual_style=TEXT,creative_additions=arr(TEXT))

def story_schema(source,foundation):
    ids=[p['id'] for p in paragraphs(source)];people=[c['id'] for c in foundation['characters']]
    return obj(title=TEXT,scenes=arr(obj(id=TEXT,story_time=TEXT,temporal_mode=enum(['actual','memory','plan']),
        timeline_id=TEXT,
        place_id=enum([p['id'] for p in foundation['places']]),seconds={'type':'integer','minimum':1,'maximum':15},
        information=TEXT,plot=TEXT,source_ids=refs(ids),
        dialogue=arr(obj(id=TEXT,speaker=enum(people),mode=enum(['onscreen','inner_voice','voiceover']),text=TEXT))),1))

def staging_schema(source,foundation,story):
    people=[c['id'] for c in foundation['characters']];places=[p['id'] for p in foundation['places']]
    evidence=refs([p['id'] for p in paragraphs(source)])
    position=obj(person=enum(people),place_id=enum(places),mark=TEXT)
    action=obj(id=TEXT,people=refs(people),description=TEXT,start={'type':'number','minimum':0},
               end={'type':'number','exclusiveMinimum':0},source_ids=evidence)
    change=obj(kind=enum(['prop','knowledge','location']),subject=enum(people),item=TEXT,before=TEXT,after=TEXT,action_id=TEXT,source_ids=evidence,state_id=TEXT)
    return obj(creative_additions=arr(TEXT),scenes=arr(obj(scene_id=enum([s['id'] for s in story['scenes']]),
        cast=refs(people),positions=arr(position,1),entries=arr(obj(person=enum(people),from_place=enum(places),to_place=enum(places),action_id=TEXT)),
        actions=arr(action,1),changes=arr(change),performance=TEXT,camera=TEXT,
        audio=arr(obj(dialogue_id=TEXT,start={'type':'number','minimum':0},end={'type':'number','exclusiveMinimum':0}))),1))

def unique(rows,key):
    values=[r[key] for r in rows]
    if len(values)!=len(set(values)):raise ValueError('duplicate_'+key)
    return set(values)

def validate_foundation(raw,source):
    schema_validate(raw,foundation_schema(source));people=unique(raw['characters'],'id');unique(raw['places'],'id')
    catalog={p['id']:p['text'] for p in paragraphs(source)}
    for row in raw['characters']+raw['places']:
        if not any(row['name'] in catalog[p] for p in row['source_ids']):raise ValueError('name_not_in_source:'+row['id'])
    for r in raw['relationships']:
        if r['subject'] not in people or r['object'] not in people:raise ValueError('relationship_unknown_person')
    return raw

def units(text):return sum(c.isalnum() for c in text)

def validate_story(raw,source,foundation,target=60):
    schema_validate(raw,story_schema(source,foundation));unique(raw['scenes'],'id');dialogue_ids=set()
    if sum(s['seconds'] for s in raw['scenes'])>target:raise ValueError('story_total_over_budget')
    for s in raw['scenes']:
        if (s['temporal_mode']=='actual')!=(s['timeline_id']=='CURRENT'):raise ValueError('timeline_mode_mismatch')
        # Give every interval an explicit information purpose; semantic pacing is reviewed separately.
        if s['seconds']>15:raise ValueError('scene_information_interval_over_15_seconds')
        for d in s['dialogue']:
            if d['id'] in dialogue_ids:raise ValueError('duplicate_dialogue_id')
            dialogue_ids.add(d['id'])
        if sum(units(d['text']) for d in s['dialogue'])>s['seconds']*4:raise ValueError('scene_dialogue_over_budget')
    return raw

def scene_schema(source,foundation,scene):
    schema=staging_schema(source,foundation,{'scenes':[scene]})
    schema['properties']['scenes']['maxItems']=1
    detail=schema['properties']['scenes']['items']['properties']
    for field,limit in [('actions',8),('changes',12),('entries',4),('audio',6)]:detail[field]['maxItems']=limit
    schema['properties']['creative_additions']['maxItems']=4
    state=obj(id=TEXT,kind=enum(['prop','knowledge','location']),subject=enum([p['id'] for p in foundation['characters']]),
              item=TEXT,value=TEXT,source_ids=refs([p['id'] for p in paragraphs(source)]))
    for field in ('state_before','state_after'):
        schema['properties'][field]={**arr(state,1),'maxItems':20}
        schema['required'].append(field)
    return schema

def validate_scene(raw,source,foundation,scene,previous=None):
    schema_validate(raw,scene_schema(source,foundation,scene))
    validate_staging({k:raw[k] for k in ('creative_additions','scenes')},source,foundation,{'scenes':[scene]})
    before={s['id']:s for s in raw['state_before']};after={s['id']:s for s in raw['state_after']}
    if len(before)!=len(raw['state_before']) or len(after)!=len(raw['state_after']) or set(before)!=set(after):raise ValueError('state_registry_changed')
    if previous is not None and raw['state_before']!=previous:raise ValueError('cross_scene_state_discontinuity')
    expected=deepcopy(before)
    detail=raw['scenes'][0];actions={a['id']:a for a in detail['actions']}
    ordered=sorted(detail['changes'],key=lambda x:(actions[x['action_id']]['end'],actions[x['action_id']]['start']))
    for change in ordered:
        key=change['state_id']
        if key not in expected:raise ValueError('unknown_state_id')
        current=expected[key]
        if any(change[k]!=current[k] for k in ('kind','subject','item')):raise ValueError('state_identity_changed')
        if change['before']!=current['value']:raise ValueError('transition_before_mismatch:'+key)
        if change['before']==change['after']:raise ValueError('state_hold_not_change')
        current['value']=change['after']
    for key,end in after.items():
        if any(end[k]!=expected[key][k] for k in ('kind','subject','item','value')):raise ValueError('state_end_without_action:'+key)
    for position in detail['positions']:
        location=[s for s in before.values() if s['kind']=='location' and s['subject']==position['person']]
        if not location:raise ValueError('location_state_missing')
        known={x['value'] for x in location}
        known.update(ch['after'] for ch in ordered if ch['kind']=='location' and ch['subject']==position['person'])
        if position['place_id'] not in known:raise ValueError('position_not_in_state_chain')
    for entry in detail['entries']:
        if not any(ch['kind']=='location' and ch['subject']==entry['person'] and ch['action_id']==entry['action_id']
                   and ch['before']==entry['from_place'] and ch['after']==entry['to_place'] for ch in ordered):
            raise ValueError('entry_state_transition_missing')
    return raw

def affected_scenes(issues,artifacts):
    catalog={r['id']:r for r in evidence_catalog(artifacts)}
    ids=set()
    for issue in issues:
        for eid in issue['evidence_ids']:
            row=catalog[eid];path=row['path']
            if row['stage']!='staging':continue
            if len(path)>1 and path[0] in ('scenes','continuity') and isinstance(path[1],int):
                ids.add(artifacts['story']['scenes'][path[1]]['id'])
            else:return {s['id'] for s in artifacts['story']['scenes']}
    return ids or {s['id'] for s in artifacts['story']['scenes']}

def delta_schema(source,foundation,scene):
    schema=scene_schema(source,foundation,scene)
    schema['properties']['introductions']=schema['properties'].pop('state_before')
    schema['properties']['introductions']['minItems']=0
    schema['properties'].pop('state_after')
    schema['required']=[k for k in schema['required'] if k not in ('state_before','state_after')]+['introductions']
    return schema

def validate_delta(raw,source,foundation,scene,previous=None):
    schema_validate(raw,delta_schema(source,foundation,scene))
    before=deepcopy(previous or [])
    ids={x['id'] for x in before};identities={(x['kind'],x['subject'],x['item']) for x in before}
    for intro in raw['introductions']:
        identity=(intro['kind'],intro['subject'],intro['item'])
        if intro['id'] in ids or identity in identities:raise ValueError('introduction_cannot_overwrite_state')
        before.append(deepcopy(intro));ids.add(intro['id']);identities.add(identity)
    computed={x['id']:deepcopy(x) for x in before};detail=raw['scenes'][0]
    actions={a['id']:a for a in detail['actions']}
    for change in detail['changes']:
        if change['action_id'] not in actions:raise ValueError('state_change_action_not_bound')
    for change in sorted(detail['changes'],key=lambda x:(actions[x['action_id']]['end'],actions[x['action_id']]['start'])):
        if change['state_id'] not in computed:raise ValueError('unknown_state_id')
        current=computed[change['state_id']]
        if any(current[k]!=change[k] for k in ('kind','subject','item')):raise ValueError('state_identity_changed')
        if current['value']!=change['before']:raise ValueError('transition_before_mismatch:'+change['state_id'])
        current['value']=change['after']
    derived={'creative_additions':deepcopy(raw['creative_additions']),'scenes':deepcopy(raw['scenes']),
             'state_before':before,'state_after':list(computed.values())}
    validate_scene(derived,source,foundation,scene)
    derived['_delta']=deepcopy(raw)
    return derived

def validate_cached(raw,source,foundation,scene,previous=None):
    if '_delta' not in raw:return validate_scene(raw,source,foundation,scene,previous)
    derived=validate_delta(raw['_delta'],source,foundation,scene,previous)
    if derived!=raw:raise ValueError('derived_cache_changed')
    return derived

def validate_staging(raw,source,foundation,story):
    schema_validate(raw,staging_schema(source,foundation,story))
    expected={s['id']:s for s in story['scenes']}
    if unique(raw['scenes'],'scene_id')!=set(expected):raise ValueError('staging_scene_coverage')
    for detail in raw['scenes']:
        s=expected[detail['scene_id']];cast=set(detail['cast']);duration=s['seconds'];actions={a['id']:a for a in detail['actions']}
        unique(detail['actions'],'id')
        if unique(detail['positions'],'person')!=cast:raise ValueError('cast_position_mismatch')
        for a in detail['actions']:
            if not set(a['people'])<=cast:raise ValueError('action_person_missing_cast')
            if not 0<=a['start']<a['end']<=duration:raise ValueError('action_outside_scene_budget')
        for e in detail['entries']:
            if e['person'] not in cast or e['action_id'] not in actions or e['person'] not in actions[e['action_id']]['people']:
                raise ValueError('entry_action_not_bound')
        for c in detail['changes']:
            if c['action_id'] not in actions or (c['kind']!='prop' and (c['subject'] not in cast or c['subject'] not in actions[c['action_id']]['people'])):
                raise ValueError('state_change_action_not_bound')
            if c['before']==c['after']:raise ValueError('state_change_no_change')
        dialogue={d['id']:d for d in s['dialogue']}
        if unique(detail['audio'],'dialogue_id')!=set(dialogue):raise ValueError('audio_dialogue_coverage')
        end=0
        for a in sorted(detail['audio'],key=lambda a:a['start']):
            d=dialogue[a['dialogue_id']]
            if not 0<=a['start']<a['end']<=duration or a['start']<end:raise ValueError('audio_overlap_or_outside_budget')
            end=a['end']
            if units(d['text'])>(a['end']-a['start'])*4:raise ValueError('audio_too_fast')
            if d['mode']=='onscreen' and d['speaker'] not in cast:raise ValueError('onscreen_speaker_not_in_cast')
    return raw

def evidence_catalog(artifacts):
    """IDs bind exact immutable values including empty/null, never model-authored paths."""
    rows=[]
    def walk(stage,value,path):
        if isinstance(value,dict) and path and (len(path)>2 or (len(path)==2 and path[0] not in ('scenes','continuity'))):
            rows.append({'id':f'E{len(rows)+1:04}','stage':stage,'path':path,'value':deepcopy(value),'value_state':'present'})
        elif isinstance(value,dict):
            for k,v in value.items():walk(stage,v,path+[k])
        elif isinstance(value,list) and value:
            for i,v in enumerate(value):walk(stage,v,path+[i])
        else:
            rows.append({'id':f'E{len(rows)+1:04}','stage':stage,'path':path,'value':deepcopy(value),
                'value_state':'null' if value is None else 'empty' if value in ('',[]) else 'present'})
    for stage in STAGES:
        if stage in artifacts:walk(stage,artifacts[stage],[])
    return rows

def review_schema(source,catalog,sha):
    return obj(candidate_sha256={'const':sha},decision=enum(['pass','revise','uncertain']),
       checks=arr(obj(dimension=enum(['source','space_cast','props_knowledge','audio','timing','information_pacing']),verdict=enum(['pass','revise','uncertain']),reason=TEXT),6),
       issues=arr(obj(severity=enum(['hard_error','suggestion','uncertain']),responsible_stage=enum(STAGES),
            evidence_ids=refs([r['id'] for r in catalog]),source_ids=refs([p['id'] for p in paragraphs(source)],0),
            reason=TEXT,required_change=TEXT)))

def validate_review(raw,source,artifacts):
    catalog=evidence_catalog(artifacts);schema_validate(raw,review_schema(source,catalog,digest(artifacts)))
    dimensions=['source','space_cast','props_knowledge','audio','timing','information_pacing']
    if unique(raw['checks'],'dimension')!=set(dimensions):raise ValueError('review_dimensions_incomplete')
    rows={r['id']:r for r in catalog}
    for i in raw['issues']:
        if not any(rows[e]['stage']==i['responsible_stage'] for e in i['evidence_ids']):raise ValueError('responsibility_evidence_mismatch')
    hard=any(i['severity']=='hard_error' for i in raw['issues']);unknown=any(i['severity']=='uncertain' for i in raw['issues'])
    expected='revise' if hard else 'uncertain' if unknown else 'pass'
    if raw['decision']!=expected:raise ValueError('review_decision_mismatch')
    if raw['decision']=='pass' and any(c['verdict']!='pass' for c in raw['checks']):raise ValueError('review_checks_disagree')
    if raw['decision']=='revise' and not any(c['verdict']=='revise' for c in raw['checks']):raise ValueError('review_checks_disagree')
    return raw

def earliest_stage(reviews):
    stages=[i['responsible_stage'] for r in reviews for i in r['issues'] if i['severity']=='hard_error']
    return min(stages,key=STAGES.index) if stages else None

def adjudication_schema(artifacts,issues):
    return obj(candidate_sha256={'const':digest(artifacts)},issue_set_sha256={'const':digest(issues)},
        findings=arr(obj(index={'type':'integer','minimum':0,'maximum':len(issues)-1},
                        verdict=enum(['upheld','rejected','uncertain']),reason=TEXT),len(issues)))

def validate_adjudication(raw,artifacts,issues):
    schema_validate(raw,adjudication_schema(artifacts,issues))
    if unique(raw['findings'],'index')!=set(range(len(issues))):raise ValueError('adjudication_coverage')
    return raw

def render(artifacts):
    f,s,b=(artifacts[k] for k in STAGES);people={c['id']:c['name'] for c in f['characters']};places={p['id']:p['name'] for p in f['places']}
    detail={x['scene_id']:x for x in b['scenes']};out=[f'# {s["title"]}',f['world'],'画风：'+f['visual_style'],
        '人物关系：'+'；'.join(people[r['subject']]+r['relation']+people[r['object']] for r in f['relationships']),
        '创意补足：'+'；'.join(f['creative_additions']+b['creative_additions'])];cursor=0
    for scene in s['scenes']:
        d=detail[scene['id']];out += [f'## {cursor}—{cursor+scene["seconds"]}秒 · {scene["story_time"]} · {places[scene["place_id"]]}',
            '时态：'+scene['temporal_mode'],'人物：'+'、'.join(people[x] for x in d['cast']),
            '信息推进：'+scene['information'],'剧情：'+scene['plot'],
            '站位：'+'；'.join(people[p['person']]+'：'+places[p['place_id']]+'，'+p['mark'] for p in d['positions']),
            '动作：'+'；'.join(f'{a["start"]}—{a["end"]}秒 '+a['description'] for a in d['actions']),d['performance'],d['camera']]
        audio={a['dialogue_id']:a for a in d['audio']}
        out += [f'{audio[x["id"]]["start"]}—{audio[x["id"]]["end"]}秒 {people[x["speaker"]]} [{x["mode"]}]：“{x["text"]}”' for x in scene['dialogue']]
        out += ['状态变化：'+'；'.join(people[c['subject']]+' / '+c['item']+'：'+c['before']+' → '+c['after'] for c in d['changes'])]
        cursor+=scene['seconds']
    return '\n\n'.join(out)+'\n'

PROMPTS={
'foundation':'你是基础设定整理员。完整阅读所有提供章节，确定原文明示的人物名字、人物关系、地点和关键约束。人物与地点名字须在所引用原段出现。先不写逐场站位和持物表。不明信息保持未知，不能把空值理解为否定。世界与事实忠于原文，画风及布景美术补足单列creative_additions。关系用人物ID引用。',
'story':'你是剧情对白编剧。根据已固定基础设定写连续短剧初稿，最多目标秒数；可选主事件，不必演出所有原文。每场1—15秒，首场立即出现有效行动/信息，不用长空镜铺陈。此时只写剧情、信息目的和对白，暂不写站位与物品表。每句音轨明确onscreen开口、inner_voice内心、voiceover旁白。不要让原文未说出口的想法变成开口。人物进场和事件先后忠于原文，未来/回忆不可当现在。给后续动作留足时间。',
'staging':'你是表演调度师。在固定剧情对白之后补全各场站位、出入场、人物动作、道具和知情变化、神情镜头及音轨时间。不得改写story的场次、对白、时态、地点与秒数。cast包括画面里的所有人物，即使背景模糊身影；actions.people完整登记动作涉及的人物。院外不能改院中，地点用已有ID，具体站位mark是明确美术补足。每个变化和进场绑定该场action_id与证据。每场时间从0起，动作和音轨可以合理并行但必须真实可执行。所有对白有且仅有一条audio，对白间不重叠且每秒最多4字。创意动作/陈设另列creative_additions，人物关系不能另猜。',
'review':'你是独立交叉审查员。对照全部原文、基础设定、剧情及调度完整检查来源、空间人物、持物知情、音轨、动作时长、信息推进六方面。固定证据编号是唯一产物引用，不能编路径或复制空值。empty/null只是记录状态，不代表明确否定；只有明确断言冲突或明确任务违反才列hard_error，证据不足列uncertain，偏好列suggestion。不要因提供了表就默认完整，必须从动作文本核对遗漏人物；检查从院外到厨房的进场、内心音轨、动作密集结尾是否能完成。每个问题标真实责任阶段，只有该阶段修改才可解决。所有审查绑定candidate_sha256，不修正文。'
}

PROMPTS['foundation'] += ' 基础设定要简洁：关系只列家庭/社会关系，动作放入关键约束。未说明信内容不等于未说明钥匙用途。若使用居民群像，要将原文明示的居民登记为集体角色；不得凭空让主角参加群像。视觉风格服务信息紧凑的短剧，不要求慢节奏或长留白。'
PROMPTS['story'] += ' 本任务要求紧凑信息流：从主线钥匙交接或其紧邻行动开始，背景通过动作自然交代，不用祠堂取信群像独立开场。可省略不影响本集理解的去年回忆。每句对白必须推动主线，不加入车龄等无关事实。不要用旁白逐字解释观众已经看见的动作。'
PROMPTS['review'] += ' evidence_catalog为列定义加行数组，path可在artifacts对应stage内逐项取值得到原字段；完整值保留在artifacts，不因索引表不重复值而认定缺证据。'

PROMPTS['foundation'] += ' 每个文本字段最多240字符。仅保留本集关键基础信息，不列长篇镜头建议。地点名使用原文明示的词，不把院外概括成院中。'
PROMPTS['story'] = '根据完整原文和基础设定写紧凑短剧：每场1—15秒，总长不超过target_seconds；建议4—6场，优先从关键冲突或交接动作进入，省略不影响本集的回忆支线。每场对白最多6条，每字段最多240字符。对白明确onscreen/inner_voice/voiceover，不把未说出口的想法改开口。actual场timeline_id固定CURRENT；回忆或计划使用各自独立timeline_id，同一timeline内部必须按事件先后排列。人物身份、时间与物品用途忠于原文。无需给每场增加旁白解释。'
PROMPTS['staging'] = '只生成current_scene这一场调度，固定全部剧情对白，不生成完整多场调度。读取完整原文、全局基础设定、整集story、前一同时间线状态previous_state和后续承接。每场最多8动作/12变化/4进场/6音轨，每文本最多240字符，performance/camera各用短句，不重复剧情。state_before在有previous_state时必须原样复制；首次建立本时间线所有将用到的位置、道具、知情槽位（未明确可写未知），state_after保持同一组id/kind/subject/item。位置槽value必须地点ID。changes的state_id绑定槽，每个变化绑定真实动作，before逐项承接前值；状态保持不写changes。最终state_after只能由这些变化得到。人物进场须同时有entries与location变化；空间ID与mark文字一致。state_before/after登记的是场景开始/结束状态，positions可描述明确进场后的站位。cast涵盖动作涉及人物（画外可明确标注），不可偷加剧情。道具开锁后不自动回口袋：留锁中或明确补动作并列creative_additions。音轨与动作可并行但必须合理，每秒最多4字。不要用画外人物的台词填时长。'
PROMPTS['review'] += ' 不要把继母被称妈自动判错；空值不是否定。台词和动作可并行，递给你可以先于递出。整句音轨开始早于开柜不能证明后半句提前获知，硬伤须落实关键短语时间，否则只列建议。重点核对continuity各场状态及原文，状态保持不算变化。每字段最多240字符，意见最多聚焦6个主要问题，不重复所有原文。'
PROMPTS['adjudicate'] = '独立核验已有硬伤是否成立，不改稿。逐项绑定输入候选SHA与问题集SHA。只有具体字段与原文/明确合同冲突才upheld；推断不足uncertain；合理称呼如继母被叫妈、对白和动作合理并行、只凭整句起点推断后半句提前获知、空值当否定，均不能据此确认硬伤。不得因为前审说错就赞同，不得引入新问题。每项reason至多240字符。'

PROMPTS['staging'] += ' prop槽的subject是关联人物（如收件人），不要求该人物在场；动作实际由actions.people指定，不能为满足道具关联人而凭空加入演员。变化描述须保留真正持有人与位置。knowledge/location槽主体则必须参与相关动作。'
PROMPTS['review'] += ' 证据索引可能指向完整动作/状态记录；字段值在artifacts内完整保留。必须读完整产物，不因索引改为记录级就忽略内部字段。道具槽subject是关联人物，并不必然是持有人或动作执行人。'

PROMPTS['staging'] += ' 输出接口更新：不输出state_before/state_after，previous_state由程序原样保存，不要抄写或改写。只输出introductions和本场调度：introductions仅登记尚未出现的槽位（原文支持的本场首次出现人物/道具/知情初态），不得重命名或覆盖已有id或同kind/subject/item；不需要第一场预先建立全剧槽位。对已有槽位只能用changes绑定动作改变值，before必须与previous_state或前一变化after精确一致；状态保持不写changes。程序根据这些变化计算场尾及后场前态，返回结果不要包含计算后的状态表。'
