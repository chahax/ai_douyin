"""Apply evidence-bound string edits; reject stale parents and out-of-scope paths."""
from copy import deepcopy
from .creative_workflow_contract import CreativeContractError
PATCH_SCHEMA={'type':'object','required':['patches'],'additionalProperties':False,'properties':{'patches':{'type':'array','minItems':1,'items':{'type':'object','required':['path','before','after'],'additionalProperties':False,'properties':{k:{'type':'string'} for k in ('path','before','after')}}}}}
PATCH_PROMPT='''你是MiniMax编剧返修员。只修review_issues指定问题，不重写完整稿。返回patches数组，每条path必须在allowed_paths中，before必须逐字复制当前字段，after是修好后的字符串。不要添加人物、道具、能力或新的对白。没有必要修改的字段不返回。事件按数组顺序播放，event/trigger仅摘要；若正文变化导致摘要矛盾，同步修允许范围的摘要。不能让错误从一个字段移到另一个字段。返回submit_creative_json工具参数。'''

def apply_script_patches(parent,patches,allowed_paths):
    if not isinstance(patches,dict) or set(patches)!={'patches'} or not isinstance(patches['patches'],list) or not patches['patches']:raise CreativeContractError('字段修补格式无效')
    result=deepcopy(parent);seen=set()
    for patch in patches['patches']:
        if not isinstance(patch,dict) or set(patch)!={'path','before','after'} or any(not isinstance(patch[k],str) for k in patch):raise CreativeContractError('字段修补项无效')
        path=patch['path']
        if path not in allowed_paths or path in seen:raise CreativeContractError('字段修补越界或重复')
        seen.add(path);parts=path.split('.');value=result
        try:
            for part in parts[:-1]:value=value[int(part)] if isinstance(value,list) else value[part]
            key=int(parts[-1]) if isinstance(value,list) else parts[-1]
            if not isinstance(value[key],str) or value[key]!=patch['before']:raise CreativeContractError('字段修补父文本不匹配')
            value[key]=patch['after']
        except (KeyError,IndexError,ValueError,TypeError) as exc:raise CreativeContractError('字段修补路径不存在') from exc
    return result
