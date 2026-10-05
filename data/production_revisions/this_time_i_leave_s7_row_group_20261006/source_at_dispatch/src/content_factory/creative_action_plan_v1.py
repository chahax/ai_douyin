"""Model supplies ordered actions; deterministic scheduling inserts locked dialogue."""
from copy import deepcopy
import json
import math
from .creative_workflow_contract import CreativeContractError, _speech_units
from .creative_state_plan_v3 import build_state_plan_schema as state_schema

VERSION='whole_film_action_plan_v1'
RULES='''为完整已审script生成动作计划。根层schema=whole_film_action_plan_v1、initial_state、beats。模型不生成任何start/end/dialogue_windows；程序插入原对白并排时，不改说话人或文字。
initial_state覆盖manifest人物和移动道具，人物posture/position/gaze/affect，道具holder/location。初态在首动作之前，归属不等于当前持有：后续take要求none，后续sit要求standing。不要先完成动作又重复执行。
每拍保留beat_id,purpose,composition,camera,dialogue_mode,cut_reason；新增groups数组、dialogue_performance字符串及reaction对象。每组严格id/script_slot/kind/duration_seconds/hold_subject/performance/operations。id全片唯一稳定。script_slot仅before/during/after，严格原文来源顺序；before组全部执行后插第一句对白，原during组在第一句之后其余对白之前，after组在所有对白之后；无对白按原文顺序。不要把“说话时的表演”误放during组，其由dialogue_performance统一描述。
kind=action或hold。action组给完整操作所需duration_seconds>0，hold_subject=""；同组可合并不同人物并行操作，关键状态按组结束生效。hold组必须operations=[]、hold_subject=人物ID，给原文明确要求稳定保持的完整时长，说明保持的状态。比如抬眼完成后至少2秒对视：抬眼action结束后另排2秒hold，再软化/放下，不能把抬眼过程充数。不为没有停顿要求的每个动作机械加hold。
operations沿用类型化kind/actor/target/value：move/gaze/affect的target=""；sit引用固定椅ID且当前standing；stand要求已坐/跪/卧；take引用道具且未持有；place要求当前actor持有；pass的value为另一人物ID。operations始终数组，单项也放数组。performance补可见表演，不藏关键状态变化。不新增无叙事作用的操作来凑时长。
reaction={anchor,subject,meaning}：anchor必须是本拍实际group.id或dialogue_0等实际对白索引，subject为人物ID，meaning说明实际刺激与反应，程序派生窗口。不另写反应时间。dialogue_performance仅嘴部、呼吸、情绪的表演，不藏移动或拿放动作。
程序优先每秒3.5计时单位并留0.3秒句间余量，必要时只缩对白至不超过5单位/秒，不压缩action/hold；仍放不进原拍时长会返回明确缺多少秒与每组预算。不要写无效多余动作把预算挤爆。完整覆盖全部beats，首尾顺序一致；根层不得散落item、groups的字段。返回唯一完整目标对象。'''


def build_action_plan_prompt(context=None):
    ids=[b['id'] for b in (context or {}).get('script',{}).get('beats',[])]
    return RULES+('\n本次beat顺序/数量：'+json.dumps(ids,ensure_ascii=False)+' / '+str(len(ids)) if ids else '')


def build_action_plan_schema(context):
    schema=state_schema(context)
    schema['properties']['schema']['enum']=[VERSION]
    beat=schema['properties']['beats']['items']
    props=beat['properties']
    event=props.pop('events')['items'];operation=event['properties']['operations']
    props.pop('dialogue_windows');props.pop('reaction_window')
    chars=[x['id'] for x in context['static_visual_manifest']['characters']]
    def obj(p): return {'type':'object','properties':p,'required':list(p),'additionalProperties':False}
    text={'type':'string'}
    props['groups']={'type':'array','items':obj({'id':text,'script_slot':{'type':'string','enum':['before','during','after']},
        'kind':{'type':'string','enum':['action','hold']},'duration_seconds':{'type':'number','exclusiveMinimum':0},
        'hold_subject':{'type':'string','enum':['']+chars},'performance':text,'operations':operation})}
    props['dialogue_performance']=text
    props['reaction']=obj({'anchor':text,'subject':{'type':'string','enum':chars},'meaning':text})
    beat['required']=list(props)
    return schema


def _structural_check(plan,context):
    from jsonschema import Draft202012Validator
    errors=[]
    for error in Draft202012Validator(build_action_plan_schema(context)).iter_errors(plan):
        errors.append({'path':'.'.join(map(str,error.absolute_path)) or '$','validator':error.validator,
                       'message':'expected '+str(error.validator_value)[:100]})
    if errors: raise CreativeContractError('action_plan结构错误: '+json.dumps(errors,ensure_ascii=False))


def schedule_action_plan(plan,script,manifest):
    """Return a v3 plan and a transparent timing report without altering raw input."""
    _structural_check(plan,{'script':script,'static_visual_manifest':manifest})
    if [b['beat_id'] for b in plan['beats']]!=[b['id'] for b in script['beats']]:
        raise CreativeContractError('action_plan beats覆盖/顺序不完整')
    result={'schema':'whole_film_state_plan_v3','initial_state':deepcopy(plan['initial_state']),'beats':[]}
    report={'schema':'action_plan_schedule_report/v1','policy':'preferred_3.5_units_per_second_plus_0.3; maximum_5; no_action_or_hold_compression','beats':[]}
    used_ids=set()
    for raw,beat in zip(plan['beats'],script['beats']):
        groups=raw['groups'];duration=beat['duration_seconds'];last_slot=-1
        for group in groups:
            gid=group['id'];slot=['before','during','after'].index(group['script_slot'])
            if not gid.strip() or gid in used_ids or gid.startswith('dialogue_'):
                raise CreativeContractError(f'action_plan {beat["id"]} group id必须全片唯一且不可使用dialogue_保留前缀: {gid}')
            used_ids.add(gid)
            if slot<last_slot: raise CreativeContractError(f'action_plan {beat["id"]} group原文来源倒序: {gid}')
            last_slot=slot
            if not math.isfinite(group['duration_seconds']): raise CreativeContractError('action_plan duration必须有限')
            if group['kind']=='hold' and (group['operations'] or not group['hold_subject']):
                raise CreativeContractError(f'action_plan hold {gid}须关联人物且operations=[]')
            if group['kind']=='action' and group['hold_subject']:
                raise CreativeContractError(f'action_plan action {gid} hold_subject须为空')
        action_total=sum(g['duration_seconds'] for g in groups)
        units=[_speech_units(x['text']) for x in beat['dialogue']]
        preferred=[max(1.0,u/3.5+0.3) for u in units]
        minimum=[max(1.0,u/5.0) for u in units]
        available=duration-action_total
        if available+1e-8<sum(minimum):
            details={'beat_id':beat['id'],'shot_seconds':duration,'action_and_hold_seconds':action_total,
                'minimum_dialogue_seconds':sum(minimum),'shortfall_seconds':round(action_total+sum(minimum)-duration,6),
                'groups':[{'id':g['id'],'kind':g['kind'],'duration_seconds':g['duration_seconds']} for g in groups]}
            raise CreativeContractError('action_plan无法排入且不能压缩动作/hold: '+json.dumps(details,ensure_ascii=False))
        compressed=sum(preferred)>available+1e-8
        if compressed:
            ratio=(available-sum(minimum))/(sum(preferred)-sum(minimum))
            actual=[minimum[i]+(preferred[i]-minimum[i])*ratio for i in range(len(units))]
        else: actual=preferred
        row={k:deepcopy(raw[k]) for k in ['beat_id','purpose','composition','camera','dialogue_mode','cut_reason']}
        row.update(events=[],dialogue_windows=[]);anchors={};cursor=0.0
        def add_group(group):
            nonlocal cursor
            end=cursor+group['duration_seconds'];slot=group['script_slot']
            if abs(end-duration)<1e-8: end=float(duration)
            phase='no_dialogue' if not units else 'before_first_line' if slot=='before' else 'between_lines' if slot=='during' and len(units)>1 else 'after_last_line'
            row['events'].append({'start':cursor,'end':end,'phase':phase,'script_slot':slot,'dialogue_index':-1,
                'performance':group['performance'],'operations':deepcopy(group['operations'])})
            anchors[group['id']]=(cursor,end);cursor=end
        def add_dialogue(index):
            nonlocal cursor
            end=cursor+actual[index]
            if abs(end-duration)<1e-8: end=float(duration)
            row['dialogue_windows'].append({'start':cursor,'end':end})
            row['events'].append({'start':cursor,'end':end,'phase':'first_line_delivery' if index==0 else 'later_line_delivery',
                'script_slot':'dialogue_performance','dialogue_index':index,'performance':raw['dialogue_performance'],'operations':[]})
            anchors['dialogue_'+str(index)]=(cursor,end);cursor=end
        for g in groups:
            if g['script_slot']=='before': add_group(g)
        if units: add_dialogue(0)
        for g in groups:
            if g['script_slot']=='during': add_group(g)
        for index in range(1,len(units)): add_dialogue(index)
        for g in groups:
            if g['script_slot']=='after': add_group(g)
        reaction=raw['reaction']
        if reaction['anchor'] not in anchors: raise CreativeContractError(f'action_plan {beat["id"]} reaction.anchor不存在: {reaction["anchor"]}')
        start,end=anchors[reaction['anchor']]
        row['reaction_window']={'start':start,'end':end,'subject':reaction['subject'],'meaning':reaction['meaning']}
        if cursor<duration-1e-8:
            row['events'].append({'start':cursor,'end':duration,'phase':'after_last_line' if units else 'no_dialogue',
                'script_slot':'after','dialogue_index':-1,'performance':'保持已成立末态，不新增动作；余量不能抵扣较早指定的保持时长','operations':[]})
        result['beats'].append(row)
        report['beats'].append({'beat_id':beat['id'],'action_and_hold_seconds':action_total,
            'preferred_dialogue_seconds':preferred,'actual_dialogue_seconds':actual,'dialogue_units':units,
            'reason':'仅缩短对白以适配原拍时长，未压缩动作或hold' if compressed else '使用优选语速与余量',
            'unused_tail_seconds':max(0,duration-cursor)})
    from .creative_state_plan_v3 import validate_state_plan
    validate_state_plan(result,script,manifest)
    return result,report


def validate_action_plan(plan,script,manifest):
    schedule_action_plan(plan,script,manifest)


def compile_action_plan(plan,script,manifest):
    from .creative_state_plan_v3 import compile_state_plan
    scheduled,_=schedule_action_plan(plan,script,manifest)
    return compile_state_plan(scheduled,script,manifest)
