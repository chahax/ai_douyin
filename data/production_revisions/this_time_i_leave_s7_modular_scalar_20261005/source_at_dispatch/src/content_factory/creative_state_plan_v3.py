"""Explicit screenplay source slots and dialogue performance, opt-in v3 only."""
from copy import deepcopy
from .creative_state_plan_v2 import RULES as OLD_RULES, build_state_plan_schema as old_schema, project_to_v1 as physical_projection
from .creative_state_plan_v6 import _keys, _window, _fail

VERSION='whole_film_state_plan_v3'
PHASES=['before_first_line','first_line_delivery','later_line_delivery','between_lines','after_last_line','no_dialogue']
SLOTS=['before','during','after','dialogue_performance']
PHASE_RULES='''phase不再使用before/during/after旧缩写。每个event额外写script_slot和dialogue_index：script_slot为before/during/after/dialogue_performance；dialogue_index仅对白表演填实际句索引，其余填-1。
script_slot指原script来源，不是时间口语：原before动作phase=before_first_line且第一句开始前完成；原during动作在第一句结束后，若有第二句phase=between_lines且第二句前完成，只有一句则phase=after_last_line；原after动作phase=after_last_line且最后一句结束后开始。
说话时的呼吸、嘴部表演、可见情绪单独用script_slot=dialogue_performance；第一句phase=first_line_delivery/dialogue_index=0，其余phase=later_line_delivery/dialogue_index=实际句索引，区间必须落在对应对白窗口内。该类operations只能affect，不能用此类提前执行原文离开/拿放/坐下/视线移动。关键动作仍引用原before/during/after来源。无对白统一phase=no_dialogue且dialogue_index=-1，仍保持原来源顺序。
例：对白2–5秒时，2–5秒嘴部表演是first_line_delivery，不是原script.during；原script.after的离开必须5秒之后。原script.during不是英语“说话期间”的意思。'''
_old_phase=OLD_RULES[OLD_RULES.index('phase必须忠实'):OLD_RULES.index('dialogue_windows与script')]
RULES=OLD_RULES.replace('whole_film_state_plan_v2',VERSION).replace(_old_phase,PHASE_RULES+'\n').replace('"phase":"before",','"phase":"before_first_line","script_slot":"before","dialogue_index":-1,')


def build_state_plan_schema(context):
    schema=old_schema(context)
    schema['properties']['schema']['enum']=[VERSION]
    event=schema['properties']['beats']['items']['properties']['events']['items']
    event['properties']['phase']['enum']=PHASES
    event['properties']['script_slot']={'type':'string','enum':SLOTS}
    event['properties']['dialogue_index']={'type':'integer'}
    event['required']+=['script_slot','dialogue_index']
    return schema


def project_to_v1(plan,script,manifest):
    _keys(plan,'schema initial_state beats','root')
    if plan['schema']!=VERSION: _fail('v3 schema错误')
    adapted=deepcopy(plan); adapted['schema']='whole_film_state_plan_v2'
    physical_script=deepcopy(script)
    if len(plan['beats'])!=len(script['beats']): _fail('v3 beats覆盖错误')
    for bi,(row,beat) in enumerate(zip(plan['beats'],script['beats'])):
        windows=row['dialogue_windows']
        if len(windows)!=len(beat['dialogue']): _fail('v3对白窗口覆盖错误')
        for w in windows: _window(w,beat['duration_seconds'],f'beats.{bi}.dialogue_windows')
        last_slot=-1
        for ei,event in enumerate(row['events']):
            path=f'beats.{bi}.events.{ei}'
            _keys(event,'start end phase script_slot dialogue_index performance operations',path)
            _window(event,beat['duration_seconds'],path)
            phase,slot,index=event['phase'],event['script_slot'],event['dialogue_index']
            if phase not in PHASES or slot not in SLOTS or type(index) is not int: _fail(path+' v3 phase/source/index错误')
            if not windows:
                if phase!='no_dialogue' or index!=-1 or slot=='dialogue_performance': _fail(path+' 无对白不能安排对白表演')
                order=SLOTS.index(slot)
                if order<last_slot: _fail(path+' 无对白原文来源倒序')
                last_slot=order
            elif slot=='dialogue_performance':
                if not 0<=index<len(windows): _fail(path+' 对白索引越界')
                expected='first_line_delivery' if index==0 else 'later_line_delivery'
                if phase!=expected or event['start']<windows[index]['start'] or event['end']>windows[index]['end']: _fail(path+' 对白表演必须落在对应对白窗口')
                if any(op.get('kind')!='affect' for op in event['operations']): _fail(path+' 对白表演不能提前执行位移或道具等关键动作')
            else:
                if index!=-1: _fail(path+' 非对白表演index须-1')
                if slot=='before':
                    if phase!='before_first_line' or event['end']>windows[0]['start']: _fail(path+' 原before须第一句前完成')
                elif slot=='during' and len(windows)>1:
                    if phase!='between_lines' or event['start']<windows[0]['end'] or event['end']>windows[1]['start']: _fail(path+' 原during须第一句后第二句前')
                else:
                    if phase!='after_last_line' or event['start']<windows[-1]['end']: _fail(path+' 原during/after不能提前到对白中')
            dest=adapted['beats'][bi]['events'][ei]
            dest.pop('script_slot'); dest.pop('dialogue_index'); dest['phase']='before'
        adapted['beats'][bi]['dialogue_windows']=[]
        physical_script['beats'][bi]['dialogue']=[]
    # Reuse only v2 physical transition validation, not its ambiguous phase vocabulary.
    result=physical_projection(adapted,physical_script,manifest)
    for row,original in zip(result['beats'],plan['beats']): row['dialogue_windows']=deepcopy(original['dialogue_windows'])
    return result


def validate_state_plan(plan,script,manifest):
    from .creative_state_plan_v6 import _states
    _states(project_to_v1(plan,script,manifest),script,manifest,allow_overlap=True)


def compile_state_plan(plan,script,manifest):
    from .creative_state_plan_v6 import compile_state_plan as compile_v1
    return compile_v1(project_to_v1(plan,script,manifest),script,manifest,allow_overlap=True)
