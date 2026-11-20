"""Phase-specific requests and typed performance feedback for whole production.

Frozen v1/v2 and their native receipts are not modified. The range arithmetic
remains v2; estimates are never a guarantee of physical acting or media quality.
"""
from __future__ import annotations

from copy import deepcopy
import json

from scripts import creative_json_document_transport_v1 as transport
from . import creative_complete_production_pipeline_v1 as local
from . import creative_complete_production_pipeline_v2 as ranges
from . import creative_video_trial_contract_v1 as source

VERSION = "creative_complete_production_pipeline/v3"
DIRECTOR_RULE = (
    "你负责整片导演：依据完整正文的情绪与因果，安排每段新增信息、观察对象、情绪转折和切镜理由。"
    "只提交whole_observation、emotional_progression、visual_style及segments等本阶段Schema字段。"
    "本阶段不安排局部动作排时，不填写人物终态或状态变化。人物、场景、道具固定规格来自shared_manifest，不能改写。"
    "从candidate_graph的ranges选择range_id与budget_tier；range_columns说明每列，budget_columns说明预算列。"
    "索引按source_refs从0起，start包含、end不包含。首段从全文首来源开始，下一范围紧接前一范围，末段到全文末来源。"
    "所有来源原顺序一次覆盖；不能按叙事beat机械分成一个API段，不拆原句、不改对白、不加剧情或固定段数。"
    "目标秒数和反应余量由程序按选定档位派生，单段4至15秒、整片不超过180秒；不要自己填写或计算这些字段。"
    "minimum、natural、reaction、action是预算选项，不是表演质量等级；0.25秒动作只是数学下界。"
    "对白按3.3发音字/秒估计；复杂动作与明确说完之后的动作须留出空间，不能把邻接当作允许重叠的证据。"
    "观察对象可说明合适的观察距离与景别；不要猜人物画面左右、指定新人物、换座或修改固定空间。"
    "具体构图由实际素材模式约束；当前续段原尾帧模式不自动授权重建机位。"
    "若收到完整失败计划或局部排时诊断，重新提交完整原生整片计划；改变切点或预算需有叙事理由。"
    "不可为适配预算删对白、加快语速、缩短必要动作，程序不会手工补切点或拼接旧计划。"
)
PERFORMANCE_RULE = (
    "你只负责当前一个segment的连续表演、逐项动作时长、刺激接收与回应、计划终态及变化来源。"
    "当前导演安排、current_sources、已完成刺激和上一段计划终态是输入边界；不改整片切点或预算档位。"
    "完整shared_manifest固定人物性别、年龄、外貌、服装、场景与道具规格；不添加人物、不改变主体对应或声线。"
    "仅当前原对白由程序原样注入；不在演法中复抄台词、不新增对白或补未来动作。"
    "对白按正常3.3发音字/秒估计，双方边说边听；细微表情融入连续演法，不拆成机械停顿。"
    "当下动作只有与相邻当下对白且语义允许时才自然重叠；明确说完后才做的动作不能提前。"
    "动作duration_seconds按实际演法估计，0.25秒下限不是建议时长；保留末句接收和导演要求的反应窗口。"
    "即使估计超过当前target_seconds，也提交真实完整排时，程序将其分类并返回整片导演返修。"
    "不得为了验收加快语速、删句、压扁动作、改变切点或隐去超时。"
    "提交完整ending_state；不变字段原样承接，未知字段为null；所有变化在state_changes用本段source_ref及原文quote支持。"
    "位置、姿态、视线、情绪、知识及道具持有、承托、朝向分开；引用准确不证明变化语义合理，后续须全文审查。"
    "不凭姓名或未查看画面猜左右，不重新设机位；本阶段计划状态不是实际像素或人工批准。"
)
REVIEW_RULE = (
    "全文审查同源完整正文、整片导演、全部局部表演、确定性排时、完整状态链和所有计划视频提示词。"
    "逐项核对来源一次覆盖、原对白未改、因果与刺激反应、观察对象与切镜理由、动作和对白的语义重叠、必要反应窗口。"
    "程序时长下界不是演法可行证明；不得仅因数字通过就忽略复杂动作、说完后动作或异常快读。"
    "核对固定双人身份服装场景、道具当前持有与承托、状态变化的当前原文证据及实际首段请求投影。"
    "后段计划尚无实际批准尾帧不是正文失败；真实人物、声线、口型及表演观感属于人工媒体审查。"
    "内容明确fail列出具体必修改；证据不足用unknown，不把unknown当作已知内容失败自动返修。"
    "不得把机器文本通过、接口成功、创作选角同意写成人工审美或视频批准。"
)

build_initial_state = ranges.build_initial_state
whole_direction_schema = ranges.whole_direction_schema
performance_schema = ranges.performance_schema
compile_direction = ranges.compile_direction
compile_complete = ranges.compile_complete
digest = source.digest


class PerformanceWindowExceeded(ValueError):
    code = "LOCAL_PERFORMANCE_WINDOW_EXCEEDED"

    def __init__(self, diagnostic):
        self.diagnostic = deepcopy(diagnostic)
        super().__init__(self.code + ": required=" + str(diagnostic["required_seconds"]) +
            ", target=" + str(diagnostic["target_seconds"]))


def compile_performance(raw, script, manifest, segment, initial, completed):
    """A typed arithmetic failure only after all preceding local gates succeed."""
    try:
        return local.compile_performance(raw, script, manifest, segment, initial, completed)
    except ValueError as exc:
        if str(exc) != "complete local performance exceeds its planned window at normal speech speed":
            raise
        current = local._range(script, completed, segment["source_refs"])
        schedule, elapsed, total = local._compile_schedule(raw, current)
        diagnostic = {"code": PerformanceWindowExceeded.code, "segment_id": segment["segment_id"],
            "source_refs": deepcopy(segment["source_refs"]), "script_sha256": digest(script),
            "global_manifest_sha256": digest(manifest), "planned_initial_state_sha256": digest(initial),
            "target_seconds": segment["target_seconds"], "provider_maximum_seconds": 15,
            "required_seconds": round(total, 6), "source_seconds": round(elapsed, 6),
            "excess_seconds": round(total - min(15, segment["target_seconds"]), 6),
            "normal_schedule": schedule, "post_reaction_seconds": raw["post_reaction_seconds"],
            "complete_native_performance": deepcopy(raw), "native_sha256": digest(raw),
            "result_is_not_adopted": True, "whole_direction_revision_required": True,
            "manual_source_or_timing_patch_allowed": False, "physical_acting_verified": False}
        raise PerformanceWindowExceeded(diagnostic) from exc


def build_director_input(script, manifest, initial, reference_fulltext, preferences, diagnostics=()):
    return {"full_current_script": deepcopy(script), "source_catalog": source.catalog(script),
        "shared_manifest": deepcopy(manifest), "planned_initial_state": deepcopy(initial),
        "reference_fulltext": reference_fulltext, "production_preferences": deepcopy(preferences),
        "candidate_graph": ranges.compact_request_graph(script, manifest),
        "known_complete_failure_diagnostics": deepcopy(list(diagnostics))}


def build_performance_input(script, manifest, segment, initial, completed, reference_fulltext, preferences):
    bank = source.catalog(script)
    return {"current_direction": deepcopy(segment),
        "current_sources": {ref: deepcopy(bank[ref]) for ref in segment["source_refs"]},
        "completed_stimulus_catalog": {ref: deepcopy(bank[ref]) for ref in completed},
        "shared_manifest": deepcopy(manifest), "planned_initial_state": deepcopy(initial),
        "completed_source_refs": deepcopy(completed), "reference_fulltext": reference_fulltext,
        "production_preferences": deepcopy(preferences), "actual_future_tail_not_created": True,
        "planned_state_is_not_pixel_approval": True}


def build_request(stage, inputs, schema, model):
    specs = {"whole_direction": ("writer", DIRECTOR_RULE, 10000),
        "local_performance": ("writer", PERFORMANCE_RULE, 7500),
        "whole_production_review": ("director", REVIEW_RULE, 6500)}
    role, rule, cap = specs[stage]
    messages = [{"role": "system", "content": rule},
        {"role": "user", "content": json.dumps(inputs, ensure_ascii=False, allow_nan=False)}]
    result = {"role": role, "model": model, "operator_version": VERSION, "stage": stage,
        "parameters": {"temperature": .4, "thinking": "disabled", "max_completion_tokens": cap},
        "messages": messages, "structured_schema": deepcopy(schema)}
    if role == "writer":
        result.update(output_transport=transport.VERSION, inner_document_schema=deepcopy(schema),
            structured_schema=transport.build_envelope_schema(), messages=transport.build_messages(messages, schema))
    return result


def render_prompt(performance, script, manifest, shared_context=None):
    """Current director intention reaches the request; whole-film future does not."""
    prompt = local.render_prompt(performance, script, manifest, shared_context)
    segment = performance["segment"]
    current = {key: segment[key] for key in ("information_change", "observation", "emotional_turn", "cut_reason")}
    source._no_dialogue_copy(current, script)
    local.shared.assert_creative_does_not_override(current)
    intent = "\n".join(["当前段导演意图（不朗读）：", "新增信息：" + current["information_change"],
        "观察对象：" + current["observation"], "情绪转折：" + current["emotional_turn"],
        "段落结束理由：" + current["cut_reason"]])
    return prompt + "\n" + intent
