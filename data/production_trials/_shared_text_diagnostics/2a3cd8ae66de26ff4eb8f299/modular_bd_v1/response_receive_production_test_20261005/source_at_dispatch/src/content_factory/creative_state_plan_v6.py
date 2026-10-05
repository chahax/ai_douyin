"""Opt-in whole-film state planning. Mechanical continuity is not semantic approval."""
from copy import deepcopy
import json
import math
from .creative_workflow_contract import CreativeContractError, _speech_units
from .creative_static_visual_manifest import style_from_manifest

VERSION = 'whole_film_state_plan_v1'
RULES = '''为已审核完整script生成全片可执行计划，只输出JSON。creative_brief是需求，script正文是事件/对白权威，static_visual_manifest是静态资产权威。不要从旧导演候选意见继承动作。
本版每个beat一个连续镜头，不能镜内硬切。先通读后续动作前提：后文坐下者此前须站立，后文放下者此前须持有；不新增多余起身拿取来修复错误起点。人物、道具ID引用manifest；初态是第一动作之前，不提前完成到达、拿取、抬眼。站坐持物位置视线由initial_state和events.changes一次定义，程序派生全部镜头首尾，禁止再写自由首尾或另造时间轴。
契约：{"schema":"whole_film_state_plan_v1","initial_state":{"C01":{"posture":"standing","position":"具体相对固定元素位置","gaze":"一个具体目标","affect":"可见表情或肩线状态"},"P01":{"holder":"C01或none","location":"具体放置/佩戴位置"}},"beats":[{"beat_id":"B1","purpose":"本拍新增信息/关系变化","composition":"固定取景范围，反应面部可读性","camera":"一个连续机位，给离开留深度","dialogue_mode":"画内对白","cut_reason":"本拍切走依据，不预测后拍","reaction_window":{"start":0,"end":2,"subject":"人物ID","meaning":"刺激与反应的情绪重点"},"events":[{"start":0,"end":2,"action":"谁的可见表演；必须忠实原文时序","changes":[{"entity":"C01","field":"position","from":"与当前值逐字一致","to":"变化后状态"}]}],"dialogue_windows":[{"start":2,"end":5}]}]}
initial_state必须覆盖manifest全部characters和props；固定场景不放状态。人物字段严格posture/position/gaze/affect，道具严格holder/location。posture枚举standing/sitting/kneeling/lying/other；holder引用人物ID或none，佩戴包holder可为佩戴者。所有字段为非空字符串。
beats逐个覆盖script.beats且顺序不变。时间是每拍局部秒数，0<=start<end<=该拍duration_seconds。events按时间排序不重叠，同时发生的动作放同一event，允许动作与对白重叠，但明确是何时听到刺激才反应；非关键表情也写action但changes可为空。每次changes先核对from当前状态，再赋to；不写from==to的伪变化。动作正文发生的站坐、位置、持物、视线改变必须同步changes；程序仅检查一致性，真实审核还会读动作语义。未变化的状态持续，不需要重复。
dialogue_windows与该拍dialogue逐句对应，只给start/end，不复制或修改文字/说话人。对白每秒不超过5计时单位，汉字每字1、拉丁词每词2；给重要刺激前中后足够表演时间，但不强制所有动作与对白串行。before→第一句对白→during→其余对白→after是剧本顺序依据。reaction_window标记真实可读的情绪反应，不能用表格代替表演。末拍不要堆砌无叙事意义动作。dialogue_mode枚举画内对白/画外对白/混合对白/无对白，根据构图中说话人是否可见选择，不得仅因角色说话就宣称同步口型。无对白时dialogue_windows=[]且dialogue_mode=无对白。
''' 

def build_state_plan_prompt(context=None):
    if (context or {}).get('state_plan_version') == 'whole_film_action_plan_v2':
        from .creative_action_plan_v2 import build_action_plan_prompt
        return build_action_plan_prompt(context)
    if (context or {}).get('state_plan_version') == 'whole_film_action_plan_v1':
        from .creative_action_plan_v1 import build_action_plan_prompt
        return build_action_plan_prompt(context)
    if (context or {}).get('state_plan_version') == 'whole_film_state_plan_v3':
        from .creative_state_plan_v3 import RULES as RULES_V3
        from .creative_state_plan_guidance import augment_prompt
        return augment_prompt(RULES_V3, context)
    if (context or {}).get('state_plan_version') == 'whole_film_state_plan_v2':
        from .creative_state_plan_v2 import RULES as RULES_V2
        return RULES_V2
    return RULES


def build_state_plan_repair(error, original_request, invalid_response):
    return ('修复完整全片计划，保留正确内容；只返回目标JSON，不输出patches或请求信封。\n'+build_state_plan_prompt(original_request),
            {'error':str(error),'original_request':original_request,'invalid_response':invalid_response})


def _fail(message):
    raise CreativeContractError('state_plan: '+message)


def _keys(value, keys, path):
    if not isinstance(value, dict) or set(value)!=set(keys.split()):
        _fail(path+' 字段必须为 '+keys)


def _text(value, path):
    if not isinstance(value,str) or not value.strip(): _fail(path+' 必须为非空字符串')


def _window(row, duration, path):
    for key in ('start','end'):
        if type(row.get(key)) not in (int,float) or not math.isfinite(row[key]): _fail(path+' 时间必须为有限数字')
    if not 0<=row['start']<row['end']<=duration: _fail(path+' 时间超界/倒序')


def _states(plan, script, manifest, *, allow_overlap=False):
    _keys(plan,'schema initial_state beats','root')
    if plan['schema']!=VERSION: _fail('schema错误')
    chars={x['id'] for x in manifest['characters']}; props={x['id'] for x in manifest['props']}
    state=deepcopy(plan['initial_state'])
    if not isinstance(state,dict) or set(state)!=chars|props: _fail('initial_state必须精确覆盖人物和移动道具ID')
    for entity,row in state.items():
        _keys(row,'posture position gaze affect' if entity in chars else 'holder location',entity)
        for field,value in row.items(): _text(value,entity+'.'+field)
    def check_values():
        for entity in chars:
            if state[entity]['posture'] not in {'standing','sitting','kneeling','lying','other'}: _fail(entity+' posture枚举错误')
        for entity in props:
            if state[entity]['holder'] not in chars|{'none'}: _fail(entity+' holder必须引用人物ID或none')
    check_values()
    if not isinstance(plan['beats'],list) or [x.get('beat_id') for x in plan['beats'] if isinstance(x,dict)]!=[x['id'] for x in script['beats']]: _fail('beats覆盖或顺序错误')
    result=[]
    for index,(row,beat) in enumerate(zip(plan['beats'],script['beats'])):
        path=f'beats.{index}'
        _keys(row,'beat_id purpose composition camera dialogue_mode cut_reason reaction_window events dialogue_windows',path)
        for key in ('purpose','composition','camera','cut_reason'): _text(row[key],path+'.'+key)
        if row['dialogue_mode'] not in {'画内对白','画外对白','混合对白','无对白'}: _fail(path+' dialogue_mode枚举错误')
        if bool(beat['dialogue']) == (row['dialogue_mode']=='无对白'): _fail(path+' dialogue_mode与有无对白不符')
        duration=beat['duration_seconds']; start=deepcopy(state)
        reaction=row['reaction_window']; _keys(reaction,'start end subject meaning',path+'.reaction_window'); _window(reaction,duration,path+'.reaction_window')
        if reaction['subject'] not in chars: _fail(path+' reaction subject未引用人物')
        _text(reaction['meaning'],path+'.reaction_window.meaning')
        if not isinstance(row['events'],list) or not row['events']: _fail(path+' events不能为空')
        last=0
        for ei,event in enumerate(row['events']):
            ep=f'{path}.events.{ei}'; _keys(event,'start end action changes',ep); _window(event,duration,ep); _text(event['action'],ep+'.action')
            if not allow_overlap and event['start']<last: _fail(ep+' events重叠，请把同时动作合并为一个event')
            last=event['end']
            if not isinstance(event['changes'],list): _fail(ep+' changes必须为数组')
            touched=set()
            for ci,change in enumerate(event['changes']):
                cp=f'{ep}.changes.{ci}'; _keys(change,'entity field from to',cp)
                entity,field=change['entity'],change['field']
                if not isinstance(entity,str) or not isinstance(field,str) or entity not in state or field not in state[entity]: _fail(cp+' 未知entity/field')
                if (entity,field) in touched: _fail(cp+' 同event重复修改字段')
                touched.add((entity,field)); _text(change['to'],cp+'.to')
                if change['from']!=state[entity][field]: _fail(cp+' from与当时状态不一致，期望 '+repr(state[entity][field]))
                if change['to']==change['from']: _fail(cp+' 无变化，删除伪变化')
                state[entity][field]=change['to']
            check_values()
        windows=row['dialogue_windows']
        if not isinstance(windows,list) or len(windows)!=len(beat['dialogue']): _fail(path+' dialogue_windows必须逐句对应锁定对白')
        last=0
        for wi,(window,line) in enumerate(zip(windows,beat['dialogue'])):
            wp=f'{path}.dialogue_windows.{wi}'; _keys(window,'start end',wp); _window(window,duration,wp)
            if window['start']<last: _fail(wp+' 对白窗口重叠或倒序')
            last=window['end']; units=_speech_units(line['text'])
            if units>(window['end']-window['start'])*5+1e-8: _fail(wp+f' 对白{units}单位需至少{units/5:g}秒')
        result.append((start,deepcopy(state)))
    return result


def validate_state_plan(plan, script, manifest):
    if plan.get('schema') == 'whole_film_action_plan_v2':
        from .creative_action_plan_v2 import validate_action_plan
        return validate_action_plan(plan,script,manifest)
    if plan.get('schema') == 'whole_film_action_plan_v1':
        from .creative_action_plan_v1 import validate_action_plan
        return validate_action_plan(plan,script,manifest)
    if plan.get('schema') == 'whole_film_state_plan_v3':
        from .creative_state_plan_v3 import validate_state_plan as validate_v3
        return validate_v3(plan,script,manifest)
    if plan.get('schema') == 'whole_film_state_plan_v2':
        from .creative_state_plan_v2 import validate_state_plan as validate_v2
        return validate_v2(plan,script,manifest)
    _states(plan,script,manifest)


def compile_state_plan(plan, script, manifest, *, allow_overlap=False):
    """Derived execution is still subject to real model and assistant review."""
    if plan.get('schema') == 'whole_film_state_plan_v2':
        from .creative_state_plan_v2 import compile_state_plan as compile_v2
        return compile_v2(plan,script,manifest)
    if plan.get('schema') == 'whole_film_state_plan_v3':
        from .creative_state_plan_v3 import compile_state_plan as compile_v3
        return compile_v3(plan,script,manifest)
    if plan.get('schema') == 'whole_film_action_plan_v2':
        from .creative_action_plan_v2 import compile_action_plan
        return compile_action_plan(plan,script,manifest)
    if plan.get('schema') == 'whole_film_action_plan_v1':
        from .creative_action_plan_v1 import compile_action_plan
        return compile_action_plan(plan,script,manifest)
    states=_states(plan,script,manifest,allow_overlap=allow_overlap)
    names={x['id']:x['name'] for x in manifest['characters']+manifest['props']}
    def render(state):
        return json.dumps({f'{key}({names[key]})':value for key,value in state.items()},ensure_ascii=False,sort_keys=True)
    shots=[]
    for i,(row,beat,(start,end)) in enumerate(zip(plan['beats'],script['beats'],states)):
        events=[]
        for event in row['events']:
            changes=json.dumps(event['changes'],ensure_ascii=False)
            events.append(f"{event['start']:g}–{event['end']:g}秒：{event['action']}；该段结束状态变化：{changes}")
        for window,line in zip(row['dialogue_windows'],beat['dialogue']):
            events.append(f"对白{window['start']:g}–{window['end']:g}秒：{line['speaker']}：{line['text']}")
        reaction=row['reaction_window']
        events.append(f"情绪反应窗口{reaction['start']:g}–{reaction['end']:g}秒，{names[reaction['subject']]}：{reaction['meaning']}")
        shots.append({'id':f'SH{i+1:02}','beat_id':beat['id'],'duration_seconds':beat['duration_seconds'],
                      'purpose':row['purpose'],'composition':row['composition'],'camera':row['camera'],
                      'cut_reason':row['cut_reason'],'visible_performance':'\n'.join(events),
                      'start_state':render(start),'end_state':render(end),'event_lock':beat['event'],
                      'dialogue_lock':deepcopy(beat['dialogue']),'dialogue_mode':row['dialogue_mode'],
                      'continuity_mode':'planned_cut_requires_adapter','production_choices':[],
                      'prompt':'由执行时间轴自动编译'})
    from .creative_segmented_director import compile_execution_storyboard, validate_execution_contract
    result=compile_execution_storyboard({'style':style_from_manifest(manifest),'shots':shots,'media_assumptions':[]},static_manifest=manifest)
    validate_execution_contract(result)
    return result


def build_state_plan_schema(context):
    if context.get('state_plan_version') == 'whole_film_action_plan_v2':
        from .creative_action_plan_v2 import build_model_response_schema
        return build_model_response_schema(context)
    if context.get('state_plan_version') == 'whole_film_action_plan_v1':
        from .creative_action_plan_v1 import build_action_plan_schema
        return build_action_plan_schema(context)
    if context.get('state_plan_version') == 'whole_film_state_plan_v3':
        from .creative_state_plan_v3 import build_state_plan_schema as schema_v3
        return schema_v3(context)
    from .creative_state_plan_v2 import build_state_plan_schema as schema_v2
    return schema_v2(context)
