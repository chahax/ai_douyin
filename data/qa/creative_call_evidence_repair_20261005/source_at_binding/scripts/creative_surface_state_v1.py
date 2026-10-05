"""Independent surface-state contract; all old bound modules remain unchanged."""
from copy import deepcopy
import json
import re
from src.content_factory.creative_workflow_contract import CreativeContractError
from src.content_factory.creative_state_plan_v6 import _keys, _text, _window, _fail

VERSION = 'creative_surface_state_v1'
RULES = '''为已审核完整剧本生成全片计划，只输出目标JSON。script正文及creative_brief是权威；manifest只给身份、外观、固定场景和道具归属，不给当前姿态/当前手持。先通读全片：如果后拍坐下，初态通常应站着，不得无依据先坐又新增起身。道具归属owner绝不等于holder；桌上无接触的物品holder=none。初态必须在首动作发生前。
每拍单连续镜头。本版人物/道具初态同v1，但关键物理动作只写operations，程序推导所有首尾及变化；不再复述from，不写changes，不写另一个首尾状态。performance只补可见情绪、节奏、点头/呼吸等细节，不能藏operations没有表达的位移/站坐/拿放/视线变化。
目标结构：{"schema":"creative_surface_state_v1","initial_state":{"C01":{"posture":"standing","position":"具体位置","gaze":"一个目标","affect":"表情/肩部状态"},"P01":{"holder":"none","location":"桌面"}},"beats":[{"beat_id":"B1","purpose":"新信息或关系变化","composition":"取景和面部可读性","camera":"单机位连续拍摄","dialogue_mode":"画内对白","cut_reason":"本拍切点依据","reaction_window":{"start":0,"end":2,"subject":"C01","meaning":"刺激与反应重点"},"events":[{"start":0,"end":2,"phase":"before","performance":"可见表演补充，没有则写自然完成操作","operations":[{"kind":"move","actor":"C01","target":"","value":"新位置"}]}],"dialogue_windows":[{"start":2,"end":5}]}]}
initial_state精确覆盖manifest全部characters和props；人物字段posture/position/gaze/affect，道具holder/location。posture枚举standing/sitting/kneeling/lying/other。holder人物ID或none。position/location具体描述固定元素相对位置；affect仅表情/肩部紧松，绝不能写看向、持物、站坐。
operations每项严格kind/actor/target/value四字段：actor人物ID。
move: target=""，value新位置；gaze: target=""，value唯一目标；affect: target=""，value新的可见表情/肩部状态。
sit: target=manifest固定椅/可坐物ID，value=坐下后具体位置；程序要求原posture=standing，改sitting。stand: target=""，value起身后位置，要求原sitting/kneeling/lying，改standing。
take: target=道具ID，value=拿取后的具体手持/佩戴位置，要求原holder=none，holder改actor。place: target=道具ID，value=放置位置，要求原holder=actor，改none。pass: target=道具ID，value=接收者人物ID，要求原holder=actor，改接收者，位置由程序记为接收者持有。
无变化的move/gaze/affect允许维持，不视为新动作；禁止用take/place/sit假装已完成动作重新发生。其它细微动作只写performance；不要为修自己的初态错误新加剧情无关操作。
events按start排序。允许两个不同人物同时动作，不同字段可并行，但同一字段的重叠读写不允许；例如同一道具拿取尚未完成不能同时放下。每个event的operations在event结束时依次成立，开始时前置必须已成立。所有秒数为拍内时间，0<=start<end<=拍时长。
phase必须忠实原文before/对白/during/after：before事件在第一句对白前完成；during事件在第一句对白之后、第二句对白之前（若无第二句则本拍结束前）；after在本拍最后一句对白后开始。无对白时仍按正文选phase。不能把after离开提前到对白中。不要照抄原文标号却更改实际先后。原剧本明确同说同动而无法用以上顺序表达时，需如实指出给审核，不擅改台词。
dialogue_windows与script每拍dialogue一一对应，只给start/end，不复写对白或speaker。每秒最多5计时单位（汉字1，拉丁词2），重要对白留前中后的可见反应，不机械额外静止。dialogue_mode枚举画内对白/画外对白/混合对白/无对白，由构图中说话人可见性决定；无对白窗口[]且模式无对白。reaction_window标识真实表演，不额外创造剧情。
\nslide只移动一个已登记独立prop，target不允许集合ID；value严格为surface:<显式支持面ID>:<zone>。必须holder=none且动作前location也为同格式、同支持面。只更新该prop的location，不改变holder或其它成员。不能用slide跨桌面、暗中拿起、转写take/place/hold；实际原slide操作须保留，机械通过仍不证明正文语义。\n完整覆盖所有拍。真实审核还将核对operations是否覆盖正文关键动作以及情绪是否可读；程序通过不是语义通过。'''



def support_surface_ids(manifest):
    """Explicit declared supporting surfaces, never guessed from element prose."""
    surfaces = manifest.get('surface_ids', [])
    if not isinstance(surfaces, list) or any(not isinstance(x,str) for x in surfaces):
        _fail('surface_ids必须为字符串组成的普通数组')
    if len(surfaces) != len(set(surfaces)):
        _fail('surface_ids必须为无重复的普通数组')
    elements = {x['id'] for x in manifest['scene']['elements']}
    for surface in surfaces:
        if not isinstance(surface, str) or not surface or ':' in surface or surface not in elements:
            _fail('surface_ids必须引用已登记固定支持面ID')
    return set(surfaces)


def surface_location_pattern(surface_ids):
    alternatives = '|'.join(re.escape(s) for s in sorted(surface_ids))
    # Zone is nonempty, contains no colon/newline and has no boundary whitespace.
    return r'^surface:(' + alternatives + r'):[^\s:][^:\r\n]*(?<!\s)$'


def parse_surface_location(value, surface_ids, path='location'):
    if not isinstance(surface_ids, (set, frozenset, list, tuple)) or not surface_ids:
        _fail(path+' slide缺少显式支持面声明')
    if not isinstance(value, str):
        _fail(path+' slide位置必须为surface:<支持面ID>:<zone>')
    match = re.fullmatch(r'surface:([^:\r\n]+):([^:\r\n]+)', value)
    if not match or not match.group(2).strip() or match.group(2) != match.group(2).strip():
        _fail(path+' slide位置必须为规范surface:<支持面ID>:<非空zone>')
    if match.group(1) not in surface_ids:
        _fail(path+' slide支持面未显式登记')
    return match.group(1), match.group(2)


def build_state_plan_schema(context):
    """JSON-schema for constrained output; semantic constraints stay in validator."""
    manifest=context['static_visual_manifest']; script=context['script']
    def obj(properties): return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
    def text(enum=None):
        result={'type':'string'}
        if enum is not None: result['enum']=enum
        return result
    number={'type':'number'}
    window=obj({'start':number,'end':number})
    characters=[c['id'] for c in manifest['characters']]
    states={c:obj({'posture':text(['standing','sitting','kneeling','lying','other']),'position':text(),'gaze':text(),'affect':text()}) for c in characters}
    states.update({p['id']:obj({'holder':text(characters+['none']),'location':text()}) for p in manifest['props']})
    operation=obj({'kind':text(['move','gaze','affect','sit','stand','take','place','pass','slide']),'actor':text(characters),'target':text(),'value':text()})
    surfaces = support_surface_ids(manifest)
    operation['allOf'] = [
        {'if': {'properties': {'kind': {'const': 'slide'}}, 'required': ['kind']},
         'then': {'properties': {
             'target': {'enum': [p['id'] for p in manifest['props']]},
             'value': {'type': 'string', 'pattern': surface_location_pattern(surfaces)}}
             } if surfaces else {'not': {}}}]
    event=obj({'start':number,'end':number,'phase':text(['before','during','after']),'performance':text(),'operations':{'type':'array','items':operation}})
    beat=obj({'beat_id':text([b['id'] for b in script['beats']]),'purpose':text(),'composition':text(),'camera':text(),
              'dialogue_mode':text(['画内对白','画外对白','混合对白','无对白']),'cut_reason':text(),
              'reaction_window':obj({'start':number,'end':number,'subject':text(characters),'meaning':text()}),
              'events':{'type':'array','items':event},'dialogue_windows':{'type':'array','items':window}})
    return obj({'schema':text([VERSION]),'initial_state':obj(states),'beats':{'type':'array','items':beat}})


def _apply_operation(operation,state,characters,props,elements,path,*,surface_ids=None):
    _keys(operation,'kind actor target value',path)
    kind,actor,target,value=(operation[k] for k in ('kind','actor','target','value'))
    if actor not in characters: _fail(path+' actor必须引用人物ID')
    _text(value,path+'.value')
    changes=[]; reads=set()
    def put(entity,field,new):
        old=state[entity][field]; reads.add((entity,field))
        if old!=new:
            changes.append({'entity':entity,'field':field,'from':old,'to':new})
            state[entity][field]=new
    if kind in ('move','gaze','affect'):
        if target!='': _fail(path+' move/gaze/affect target应为空字符串')
        field={'move':'position','gaze':'gaze','affect':'affect'}[kind]
        put(actor,field,value)
        description=f'{actor} '+({'move':'移动至','gaze':'视线转向','affect':'可见情绪变为'}[kind])+value if changes else f'{actor}维持{field}={value}'
    elif kind in ('sit','stand'):
        reads.add((actor,'posture'))
        if kind=='sit':
            if target not in elements: _fail(path+' sit target须引用固定可坐物ID')
            if state[actor]['posture']!='standing': _fail(path+' sit要求当前standing，不能从已坐初态重复坐下')
            put(actor,'posture','sitting'); description=f'{actor}在{target}坐下至{value}'
        else:
            if target!='': _fail(path+' stand target应为空字符串')
            if state[actor]['posture'] not in ('sitting','kneeling','lying'): _fail(path+' stand要求当前坐/跪/卧')
            put(actor,'posture','standing'); description=f'{actor}起身站至{value}'
        put(actor,'position',value)
    elif kind == 'slide':
        if target not in props: _fail(path+' slide target必须引用已登记独立prop')
        if state[target]['holder'] != 'none': _fail(path+' slide要求当前holder=none，不暗中拿起')
        before_surface, before_zone = parse_surface_location(state[target]['location'], surface_ids, path+'.from')
        after_surface, after_zone = parse_surface_location(value, surface_ids, path+'.value')
        if before_surface != after_surface: _fail(path+' slide不能跨支持面，需真实拿放操作')
        if before_zone == after_zone: _fail(path+' slide必须改变zone，不能伪写移动')
        reads.add((target,'holder')); reads.add((target,'location'))
        put(target,'location',value)
        description=f'{actor}执行slide：在支持面{after_surface}将独立道具{target}从{before_zone}滑移至{after_zone}；holder维持none'
    elif kind in ('take','place','pass'):
        if target not in props: _fail(path+' 道具操作target必须引用prop')
        reads.add((target,'holder'))
        if kind=='take':
            if state[target]['holder']!='none': _fail(path+' take要求当前holder=none（归属不等于持有）')
            put(target,'holder',actor); put(target,'location',value); description=f'{actor}拿起{target}至{value}'
        elif kind=='place':
            if state[target]['holder']!=actor: _fail(path+' place要求道具当前由actor持有')
            put(target,'holder','none'); put(target,'location',value); description=f'{actor}将{target}放在{value}'
        else:
            if state[target]['holder']!=actor or value not in characters or value==actor: _fail(path+' pass要求当前持有人交给另一有效人物')
            put(target,'holder',value); put(target,'location',value+'持有'); description=f'{actor}将{target}交给{value}'
    else: _fail(path+' kind不支持')
    return changes,reads,description


def project_to_v1(plan,script,manifest):
    """Lossless derived action prose, never edit the raw v2 model receipt."""
    _keys(plan,'schema initial_state beats','root')
    if plan['schema']!=VERSION: _fail('v2 schema错误')
    characters={c['id'] for c in manifest['characters']};props={p['id'] for p in manifest['props']};elements={x['id'] for x in manifest['scene']['elements']}
    if not isinstance(plan['initial_state'],dict) or set(plan['initial_state'])!=characters|props: _fail('initial_state覆盖错误')
    # Validate initial shape via a zero-beat old validator, keeping its old behavior unchanged.
    from src.content_factory.creative_state_plan_v6 import _states
    _states({'schema':'whole_film_state_plan_v1','initial_state':plan['initial_state'],'beats':[]},{'beats':[]},manifest)
    if not isinstance(plan['beats'],list) or [r.get('beat_id') for r in plan['beats']]!=[b['id'] for b in script['beats']]: _fail('beats覆盖/顺序错误')
    state=deepcopy(plan['initial_state']);result=deepcopy(plan);result['schema']='whole_film_state_plan_v1'
    for bi,(row,beat) in enumerate(zip(plan['beats'],script['beats'])):
        path=f'beats.{bi}';_keys(row,'beat_id purpose composition camera dialogue_mode cut_reason reaction_window events dialogue_windows',path)
        if not isinstance(row['events'],list) or not row['events']: _fail(path+' events不能为空')
        windows=row['dialogue_windows']
        if not isinstance(windows,list) or len(windows)!=len(beat['dialogue']): _fail(path+' 对白窗口覆盖错误')
        for wi,w in enumerate(windows): _window(w,beat['duration_seconds'],f'{path}.dialogue_windows.{wi}')
        projected=[]; active=[];last_start=-1
        for ei,event in enumerate(row['events']):
            ep=f'{path}.events.{ei}';_keys(event,'start end phase performance operations',ep);_window(event,beat['duration_seconds'],ep)
            _text(event['performance'],ep+'.performance')
            if event['start']<last_start: _fail(ep+' events须按start排序')
            last_start=event['start']
            if event['phase'] not in ('before','during','after'): _fail(ep+' phase枚举错误')
            if windows:
                if event['phase']=='before' and event['end']>windows[0]['start']: _fail(ep+' before动作须在第一句对白前完成')
                if event['phase']=='during' and (event['start']<windows[0]['end'] or (len(windows)>1 and event['end']>windows[1]['start'])): _fail(ep+' during动作须在第一句后及第二句前')
                if event['phase']=='after' and event['start']<windows[-1]['end']: _fail(ep+' after动作不能提前到对白中')
            if not isinstance(event['operations'],list): _fail(ep+' operations必须为列表')
            # Commit finished events. Independent simultaneous actors remain legal.
            finished=[a for a in active if a['end']<=event['start']]
            for a in sorted(finished,key=lambda a:a['end']):
                for change in a['changes']: state[change['entity']][change['field']]=change['to']
            active=[a for a in active if a['end']>event['start']]
            local=deepcopy(state);changes=[];reads=set();descriptions=[]
            for oi,operation in enumerate(event['operations']):
                delta,access,description=_apply_operation(operation,local,characters,props,elements,f'{ep}.operations.{oi}',surface_ids=support_surface_ids(manifest))
                changes.extend(delta);reads|=access;descriptions.append(description)
            # One event may sequentially take/hand over or move/sit; retain the final state once.
            physical_writes={(change['entity'],change['field']) for change in changes}
            net={}
            for change in changes:
                key=(change['entity'],change['field'])
                if key in net:
                    net[key]['to']=change['to']
                else:
                    net[key]=deepcopy(change)
            changes=[change for change in net.values() if change['from']!=change['to']]
            writes=physical_writes
            for a in active:
                if (reads&a['writes']) or (writes&a['reads']): _fail(ep+' 与重叠事件存在同字段读写依赖，请顺序执行')
            entry={'start':event['start'],'end':event['end'],'changes':changes,'reads':reads,'writes':writes,
                   'action':'；'.join(descriptions)+('；表演补充：'+event['performance'])}
            active.append(entry);projected.append(entry)
        for a in sorted(active,key=lambda a:a['end']):
            for change in a['changes']: state[change['entity']][change['field']]=change['to']
        result['beats'][bi]['events']=[{k:a[k] for k in ('start','end','action','changes')} for a in sorted(projected,key=lambda a:a['end'])]
    return result


def validate_state_plan(plan,script,manifest):
    from src.content_factory.creative_state_plan_v6 import _states
    projected=project_to_v1(plan,script,manifest)
    _states(projected,script,manifest,allow_overlap=True)


def legacy_visual_manifest(manifest):
    """Old visual compiler view only; full physical/context manifest is retained."""
    support_surface_ids(manifest)
    result = deepcopy(manifest)
    result.pop('surface_ids', None)
    return result


def compile_projected_state_plan(projected,script,manifest):
    """Only the old renderer's static-shape check receives the visual projection."""
    from src.content_factory.creative_state_plan_v6 import compile_state_plan as compile_v1
    return compile_v1(projected,script,legacy_visual_manifest(manifest),allow_overlap=True)


def compile_state_plan(plan,script,manifest):
    projected=project_to_v1(plan,script,manifest)
    return compile_projected_state_plan(projected,script,manifest)
