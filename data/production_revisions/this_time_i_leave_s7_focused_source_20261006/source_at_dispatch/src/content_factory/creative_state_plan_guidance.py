"""Opt-in planning guidance; old v3 prompt bytes remain unchanged."""
import json
from .creative_workflow_contract import CreativeContractError

VERSION = 'completed_action_hold_v1'
STRUCTURE_VERSION = 'completed_action_hold_v2'
RULES = '''生成前先区分“完成变化”和“保持变化后的状态”。operations在event.end才生效；原文要求“动作完成后保持N秒/对视至少N秒/放下后停顿N秒”时，从相关动作event.end起算稳定保持时长，不能把抬眼、转身、拿放的运动过程算入保持。将该明确要求落实为后续独立event（operations可为空），说明保持什么状态；达到N秒之前不得开始原文要求在保持之后才发生的软化、拿放、开口或离开。reaction_window与purpose写了“至少N秒”不等于时间轴真的留足。
只履行原script/creative_brief明确要求的停顿，不给每个动作机械添加等待，不改变原剧情及对白。若当前节拍紧张，应在允许范围内缩短过渡动作并保留对白可读时长，不能把重要反应挪到刺激之前或用下一拍动作凑时长；不通过新增起身/拿放掩盖初态错误。
提交前核对完整结构：根层只能schema、initial_state、beats三个键；beats为数组，必须按输入顺序覆盖全部beat_id，数量、首拍、末拍均一致。每个event及dialogue_windows保留在所属beat内部，数组项不能写成根层item，也不能把末拍的script_slot/dialogue_index等字段散落在根层。先完成末拍并闭合所有数组，再提交一个完整对象；不要增加核对清单字段。'''


def augment_prompt(prompt, context):
    version=(context or {}).get('state_plan_guidance_version')
    if version is None: return prompt
    if version not in (VERSION, STRUCTURE_VERSION) or context.get('state_plan_version') != 'whole_film_state_plan_v3':
        raise CreativeContractError('不支持的state_plan_guidance_version或计划版本')
    result=prompt+'\n'+RULES
    if version == STRUCTURE_VERSION:
        result+='\n结构预检会一次列出全部错误路径，请在同一次完整修复中处理所有项；operations始终为数组，单项也须放在数组内。'
    beats=context.get('script',{}).get('beats')
    if isinstance(beats,list):
        ids=[beat['id'] for beat in beats]
        result+='\n本次完整beat_id顺序='+json.dumps(ids,ensure_ascii=False)+'；数量='+str(len(ids))
        if ids: result+='；首拍='+ids[0]+'；末拍='+ids[-1]
    return result


def validate_guided_structure(value, context):
    """Aggregate schema errors before semantics, only for a new explicit binding."""
    if context.get('state_plan_guidance_version') != STRUCTURE_VERSION:
        return
    from jsonschema import Draft202012Validator
    from .creative_state_plan_v6 import build_state_plan_schema
    schema=build_state_plan_schema(context)
    errors=[]
    for error in sorted(Draft202012Validator(schema).iter_errors(value), key=lambda e: '.'.join(map(str,e.absolute_path))):
        path='.'.join(map(str,error.absolute_path)) or '$'
        if error.validator == 'type':
            actual=('object' if isinstance(error.instance,dict) else 'array' if isinstance(error.instance,list) else type(error.instance).__name__)
            message='expected '+str(error.validator_value)+'; got '+actual
        elif error.validator == 'required':
            missing=[key for key in error.validator_value if key not in error.instance]
            message='missing keys: '+','.join(missing)
        elif error.validator == 'additionalProperties':
            extra=sorted(set(error.instance)-set(error.schema.get('properties',{})))
            message='unexpected keys: '+','.join(extra)
        else:
            message='constraint '+str(error.validator)+' expected '+json.dumps(error.validator_value,ensure_ascii=False)
        errors.append({'path':path,'validator':error.validator,'message':message[:180]})
    if errors:
        raise CreativeContractError('state_plan结构预检: '+json.dumps(errors,ensure_ascii=False))
