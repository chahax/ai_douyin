"""Story first, then explicit screen action; source facts stay upstream."""
from copy import deepcopy
import json
from jsonschema import validate as schema_validate
from .corpus_screenplay_v1 import digest

VERSION='story_first_contract/v2'
STAGES=('foundation','story','staging')
TEXT={'type':'string','minLength':1}
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
        place_id=enum([p['id'] for p in foundation['places']]),seconds={'type':'integer','minimum':1,'maximum':60},
        information=TEXT,plot=TEXT,source_ids=refs(ids),
        dialogue=arr(obj(id=TEXT,speaker=enum(people),mode=enum(['onscreen','inner_voice','voiceover']),text=TEXT))),1))

def staging_schema(source,foundation,story):
    people=[c['id'] for c in foundation['characters']];places=[p['id'] for p in foundation['places']]
    evidence=refs([p['id'] for p in paragraphs(source)])
    position=obj(person=enum(people),place_id=enum(places),mark=TEXT)
    action=obj(id=TEXT,people=refs(people),description=TEXT,start={'type':'number','minimum':0},
               end={'type':'number','exclusiveMinimum':0},source_ids=evidence)
    change=obj(kind=enum(['prop','knowledge']),subject=enum(people),item=TEXT,before=TEXT,after=TEXT,action_id=TEXT,source_ids=evidence)
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
        # Give every interval an explicit information purpose; semantic pacing is reviewed separately.
        if s['seconds']>15:raise ValueError('scene_information_interval_over_15_seconds')
        for d in s['dialogue']:
            if d['id'] in dialogue_ids:raise ValueError('duplicate_dialogue_id')
            dialogue_ids.add(d['id'])
        if sum(units(d['text']) for d in s['dialogue'])>s['seconds']*4:raise ValueError('scene_dialogue_over_budget')
    return raw

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
            if c['subject'] not in cast or c['action_id'] not in actions or c['subject'] not in actions[c['action_id']]['people']:
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
        if isinstance(value,dict):
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
