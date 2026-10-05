"""Frozen expression references across creation, revision and text review."""
from copy import deepcopy
from .creative_workflow_contract import CreativeContractError
VERSION = "reference_expression_v1"
RULE = "reference_pack来自已获取的同类视频和教学表达分析。学习信息递进、刺激与反应、具体行动、观察主体及结尾余味；选与当前需求相关的机制，不照搬参考人物、对白、剧情、时长或画风。创作简报优先，不把参考偏好当硬禁令；未观察本次媒体不得宣称表演成功。"


def bind_reference_expression(reference_pack):
    return {"version": VERSION, "reference_pack": deepcopy(reference_pack), "rule": RULE}


def enrich_reference_context(binding, name, payload):
    if not binding or not name.startswith(("writer_", "director_", "script_review", "static_visual_manifest")):
        return payload
    if binding.get("version") != VERSION:
        raise CreativeContractError("不支持的参考表达绑定版本")
    result = deepcopy(payload)
    sent = result.get("reference_pack", result.get("materials", {}).get("reference_pack"))
    if sent is not None and sent != binding["reference_pack"]:
        raise CreativeContractError("当前阶段参考表达与任务绑定不一致")
    if sent is None:
        result["reference_pack"] = deepcopy(binding["reference_pack"])
    result["reference_expression_rule"] = binding["rule"]
    return result
