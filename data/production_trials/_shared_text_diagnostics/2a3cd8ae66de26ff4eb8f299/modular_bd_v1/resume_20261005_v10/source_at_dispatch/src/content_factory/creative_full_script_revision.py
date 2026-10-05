"""Complete model-authored script revisions; no old beat projection."""
from copy import deepcopy
from .creative_workflow_contract import CreativeContractError, compile_beat_screenplay

MODE='full_script'
VERSION='full_script_revision_v1'
PROMPT="""本次为完整剧本返修。将previous_script作为上一版，将issues作为修改需求，重新提交完整events剧本；不返回replace_beats或补丁，不要求未涉及的节拍逐字不变。保留创作简报中的主题、人物关系和核心要求；可调整整篇对白、动作、节拍数量、编号、顺序和时长，以保证情感、事件与画面表达衔接。审核问题的location仅为证据定位，不是只允许修改该拍的边界。premise必须准确概括新版实际演出。完整新版将直接全文审核，程序不会抽取某拍与旧稿拼接；不要增删剧情迁就字段数量。每拍至多两条dialogue，可合理拆拍并保留对白/动作因果。"""


def bind_full_script_revision():
    return {'version':VERSION,'mode':MODE,'prompt':PROMPT}


def accept_full_script(previous,value):
    if not isinstance(value,dict) or 'replace_beats' in value:
        raise CreativeContractError('整稿返修必须提交完整剧本，不接受局部补丁')
    required={'title','premise','selected_candidate_id','duration_seconds','beats'}
    if not required.issubset(value) or not isinstance(value.get('beats'),list) or not value['beats']:
        raise CreativeContractError('整稿返修缺少完整剧本正文')
    if value['selected_candidate_id']!=previous['selected_candidate_id']:
        raise CreativeContractError('整稿返修不能更换已选故事身份')
    result=deepcopy(value)
    result['screenplay_markdown']=compile_beat_screenplay(result)
    return result
