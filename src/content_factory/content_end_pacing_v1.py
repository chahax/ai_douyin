"""Freeze content-driven endings for new source briefs; never migrate old runs.

This preparation adapter has no model/media calls and changes no runtime budget,
authorization, native evidence or existing dispatch behavior.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

VERSION = "content_end_pacing/v1"
REQUIREMENTS = {
    "content_end": "每个服务段在最后必要对白、动作及关键反应完成时立即收段；不要在内容已结束后继续等待、发呆、凝视或补无新作用的动作。普通尾部补时为0秒，不另留固定尾窗。",
    "ordinary_expression": "普通或平淡神情开镜直接成立；普通抬眼、转头、拿取、推物、收纳、起身不必逐项慢慢展开。动作、视线、对白和听者即时反应自然并行，不让同一信息分别占几个长镜。",
    "necessary_reaction": "重要信息或情绪转折可以保留观众读得懂的关键反应，但须说明该反应改变了什么理解、判断或关系；时长服务于具体作用，不把所有反应统一压成0秒，也不例行追加沉默。",
    "reference_total": "未明确指定duration_policy时，新任务采用content_driven：依据有效内容决定时长，单独的target_duration_seconds仅作参考估算，不为接近参考总长增加动作、对白或停顿。",
    "hard_constraints": "完整保留用户显式最短、最长和硬目标范围；min_duration_seconds、max_duration_seconds及显式target_duration_seconds与duration_tolerance_seconds组合仍是原硬约束。参考总长不能扩大或取消这些边界。有冲突时交回编剧或导演删合、改写、重新分段，审核员和SDK编译器不能私自改秒数。",
    "natural_delivery": "保持可理解的自然对白语速、真实空间距离和必要交接；压缩应来自删合重复内容、普通动作并行或清楚切镜省略过程，不能催念台词、让人瞬移、重复动作或把全稿按比例缩秒。",
    "service_duration": "Seedance Mini服务段为4至15秒整数，选择能完整容纳必要内容的最短可行档。若内容不足最低4秒，优先并入相邻段或重新组织分段，不能用空等或补动作填到最低档；如超过15秒，删合或重新分段，不牺牲自然语速。",
    "actual_prompt": "实际发送Seedance Mini的提示词按动作、对白和反应的自然发生顺序表达，明确哪些并行、哪些先后；不要强迫模型卡小数秒时间点。内部时间分析表可记录估算时点，但不得机械照搬为实际视频提示词。",
    "same_source_review": "MiniMax完整创作与自然导演、DeepSeek同稿全文审核、忠实整理及最终全部SDK请求复审均读取同一冻结brief和本规则；审核应指出内容已经结束却仍占时等具体问题。整理和编译保持创作者原定内容和秒数，不能靠暗改duration冒充修复通过。",
    "preservation": "本设置只用于显式新任务；旧运行恢复不补写brief、不修改原生稿、冻结文件、回执、预算、失败或计数。文本审核通过不代表视频质量通过；视频仍由用户人工审核，本规则不新增媒体、重试、续段或发布权限。",
}


def _sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def policy():
    """Return an independent complete policy copy with a canonical content hash."""
    content = dict(version=VERSION, requirements=deepcopy(REQUIREMENTS),
        ordinary_tail_padding_seconds=0, default_duration_policy="content_driven",
        service_duration_seconds=dict(min=4, max=15, integer_only=True),
        actual_prompt_timing="ordered_actions", automatic_duration_rewrite=False)
    return {**content, "sha256": _sha(content)}


def apply_brief(brief):
    """Add the new policy to a deep copy without relaxing explicit constraints."""
    if brief is not None and not isinstance(brief, dict):
        raise ValueError("创作要求必须为对象或None")
    result = deepcopy(brief or {})
    expected = policy()
    if "content_end_pacing" in result and result["content_end_pacing"] != expected:
        raise ValueError("已有content_end_pacing与本独立版本不同，不能覆盖或迁移")
    result["content_end_pacing"] = expected
    if result.get("duration_policy") is None:
        result["duration_policy"] = "content_driven"
    return result


def _runtime():
    from . import natural_director_pipeline_v10
    return natural_director_pipeline_v10


def _read_binding(path):
    def unique(rows):
        value = {}
        for key, item in rows:
            if key in value:
                raise ValueError("旧运行绑定含重复字段，不能自动迁移")
            value[key] = item
        return value
    value = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError("旧运行绑定包含非法数值")))
    if not isinstance(value, dict):
        raise ValueError("旧运行绑定不是完整对象")
    return value


def prepare_source(source_run_dir, *, brief=None, runtime=None, **kwargs):
    """Prepare only a new source, or the exact already-frozen new-policy route.

    All authorization and original prepare arguments go unchanged to v10. An
    existing run without this exact policy must use its original recovery entry.
    """
    run = Path(source_run_dir).resolve()
    binding_path = run / "BINDING.json"
    if binding_path.exists():
        binding = _read_binding(binding_path)
        frozen_brief = binding.get("brief")
        if (not isinstance(frozen_brief, dict) or frozen_brief.get("content_end_pacing") != policy()):
            raise ValueError("已有运行未冻结本content_end_pacing版本，请使用原恢复入口；不能补写旧稿")
        if brief is None:
            brief = frozen_brief
    prepared_brief = apply_brief(brief)
    return (runtime if runtime is not None else _runtime()).prepare_source(
        source_run_dir, brief=prepared_brief, **kwargs)
