"""Pure contracts for the independent novel adaptation text route.

Only source anchors, structural coverage and conservative timing are checked
here. Faithfulness, acting quality and dramatic effectiveness require the bound
whole-text review; a successful validator is not a human creative approval.
Source anchors are short exact quotations. The program locates their character
spans; the model never calculates offsets or echoes source identities.
"""
from __future__ import annotations

import math
import re

from jsonschema import Draft202012Validator

VERSION = "novel_adaptation_contracts/v1"
STAGES = ("analysis", "adaptation_plan", "screenplay")
REVIEW_DIMENSIONS = (
    "mainline_and_motivation", "causality", "character_identity",
    "space_gaze_action", "emotion_windows", "dialogue_naturality",
    "shootability", "completeness", "timing",
)


def _obj(properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


def _array(items, minimum=0):
    return {"type": "array", "items": items, "minItems": minimum}


TEXT = {"type": "string", "minLength": 1, "pattern": r"\S"}
OCCURRENCE = {"type": "integer", "minimum": 0}
RANGE = _obj({"start_quote": TEXT, "end_quote": TEXT,
              "start_occurrence": OCCURRENCE, "end_occurrence": OCCURRENCE})
RANGE["required"] = ["start_quote", "end_quote"]
SOURCE_REF = _obj({"quote": TEXT, "occurrence": OCCURRENCE})
SOURCE_REF["required"] = ["quote"]
REFS = _array(SOURCE_REF, 1)
IDS = _array(TEXT, 1)
WORLD = _obj({"era": TEXT, "daily_context": TEXT, "space_and_prior_events": TEXT,
              "unknowns": _array(TEXT)})
CHARACTER = _obj({"id": TEXT, "name": TEXT, "identity": TEXT, "personality": TEXT,
                  "situation": TEXT, "goal": TEXT, "relationships": TEXT, "source_refs": REFS})
STATE = _obj({"character_id": TEXT, "action": TEXT, "expression": TEXT, "gaze": TEXT})
SECONDS = {"type": "number", "exclusiveMinimum": 0, "maximum": 3600}
EVENT = _obj({
    "id": TEXT, "kind": {"enum": ["action", "dialogue", "reaction", "voiceover"]},
    "actor_id": TEXT, "text": TEXT, "duration_seconds": SECONDS,
    "character_states": _array(STATE, 1), "stimulus_event_id": {"type": "string"},
    "emotional_focus": {"type": "boolean"},
})
SCENE = _obj({"id": TEXT, "timeline": TEXT, "time": TEXT, "location": TEXT,
              "present_character_ids": IDS, "start_state": TEXT, "end_state": TEXT,
              "events": _array(EVENT, 1)})

SCHEMAS = {
    "analysis": _obj({
        "world": WORLD, "characters": _array(CHARACTER, 1),
        "storyline": _array(_obj({"id": TEXT, "cause": TEXT, "event": TEXT,
                                 "consequence": TEXT, "source_refs": REFS}), 1),
        "highlights": _array(_obj({
            "id": TEXT, "kind": {"enum": ["conflict", "suspense", "reversal", "emotional_peak"]},
            "description": TEXT, "reason": TEXT, "storyline_ids": IDS,
            "character_ids": IDS, "source_refs": REFS,
        }), 1),
    }),
    "adaptation_plan": _obj({
        "title": TEXT, "selected_character_ids": IDS, "selected_highlight_ids": IDS,
        "source_ref": RANGE, "start_state": TEXT, "end_state": TEXT,
        "causal_beats": _array(_obj({
            "id": TEXT, "phase": {"enum": ["setup", "stimulus", "reaction", "escalation", "closure", "cliffhanger"]},
            "description": TEXT, "character_ids": IDS, "source_refs": REFS,
        }), 5),
        "preserved_facts": _array(_obj({"id": TEXT, "description": TEXT, "source_refs": REFS}), 1),
        "changes": _array(_obj({"description": TEXT, "reason": TEXT, "mainline_impact": TEXT})),
        "target_duration_seconds": SECONDS,
    }),
    "screenplay": _obj({
        "title": TEXT, "world": WORLD, "characters": _array(CHARACTER, 1),
        "duration_seconds": SECONDS, "scenes": _array(SCENE, 1),
        "ending": _obj({"type": {"enum": ["closure", "cliffhanger"]}, "description": TEXT}),
        "adaptation_notes": _array(TEXT),
    }),
}
REVIEW_SCHEMA = _obj({
    "whole_text_reviewed": {"const": True}, "summary": TEXT,
    "dimensions": _array(_obj({"dimension": {"enum": list(REVIEW_DIMENSIONS)}, "assessment": TEXT}), len(REVIEW_DIMENSIONS)),
    "issues": _array(_obj({
        "severity": {"enum": ["blocking", "major", "minor"]}, "location": TEXT,
        "evidence": TEXT, "impact": TEXT, "proposal": TEXT,
        "responsible_stage": {"enum": list(STAGES)},
    })),
})

_BASE = """你是小说改编编剧，使用submit_creative_json提交本阶段完整JSON。只分析source.text实际取得的正文，source.scope之外不可声称已读。未知背景明确写原文未交代。不要输出来源SHA、binding_id、字符下标或其他程序身份，也不要另写一份重复Markdown。角色ID不得使用保留值narrator，该值只供voiceover旁白使用。source_refs.quote是原文中可定位的连续短引文，选择足够长的独特引文；若重复可用可选occurrence指定从0开始第几次出现。程序定位范围，不让你计字符。引用只证明依据位置，不要求对白逐字照抄。人物动机、主线关键因果和走向应有原文依据；允许重写对白、合并场景、压缩支线与调整叙述顺序，但须交代改编理由和影响。previous_value与issues如存在是完整修订依据，返回完整新版本，不返回补丁，不改来源迎合正文。"""
PROMPTS = {
    "analysis": _BASE + """
分析世界框架：时代、日常环境、空间及前情，未知写入unknowns。列出有稳定ID的角色卡，写身份、性格、处境、目标、关系与短引证。按因果分析已取得正文的主线与关键转折，列出多个可供选择的冲突、悬念、反转或情绪高潮候选，说明理由并引用角色/主线ID。不因要求多个而捏造，正文只有一个候选可如实只交一个。""",
    "adaptation_plan": _BASE + """
基于完整analysis选择本稿角色和高潮ID，source_ref以start_quote和end_quote给出选段起止短锚文，不重复全文、不计算字符位置；重复时可指定start_occurrence/end_occurrence。范围从起锚开头到止锚结尾。明确起止状态、必须保留的动机和主线事实，按setup→stimulus→reaction→escalation→closure或cliffhanger编排causal_beats。每个重要高潮保留铺垫和刺激后的可见反应，不将反应挪到不相关段落。记录每项改编变更及理由/主线影响；无变更可空数组。目标时长按实际内容设置，不能为短时长删除必要因果。角色与引用ID必须来自analysis。""",
    "screenplay": _BASE + """
依据已接受analysis与adaptation_plan生成一份完整可拍剧本。先完整世界与本稿角色卡，再逐场写timeline/time/location、所有在场角色ID、首尾状态。events按真实播放次序写action/dialogue/reaction/voiceover，actor_id为角色ID；只有voiceover可用narrator。每事件character_states必须逐一列出本场所有在场人的动作、神情和视线，包括不说话者，动作对白自然推进，不靠堆动作或长时间静候凑时长。事件时长之和必须等于整稿duration_seconds；对白/旁白预留保守阅读时间（中文最多每秒6字、英文最多每秒3词），重要emotional_focus事件及对应可见reaction各至少1秒。reaction的stimulus_event_id引用此前本场刺激事件，其他无刺激填空串。重要情绪刺激之后必须实际演出reaction，不以总结代替表演。结束以ending明确收束或可理解的悬念。不要只给开头、提纲、占位或省略剩余场次。对白允许符合主线的自然改写，不需逐句原文引证。""",
}
REVIEW_PROMPT = """你是DeepSeek独立全文审查员。阅读同次请求中的完整source、analysis、adaptation_plan与screenplay，不代写，不猜测SHA。whole_text_reviewed必须真实，按schema完成所有dimension的具体评估，全部问题一次汇总。核对只分析已取得范围；背景/角色动机/主线走向与关键因果有原文依据；允许合理重写对白、合并场景、压缩支线和调整叙述顺序，不因不逐字引用而拒绝。逐场检查真实说话人、人物关系身份、空间移动、视线/动作衔接、铺垫→刺激→反应→升级→收束/悬念、重要情绪反应窗口、对白自然程度、可拍性、全稿完整和时间可行性。程序校验只是结构与保守估算，不代表表演成立。每个issue给出可定位的本稿证据、影响、修复建议和responsible_stage：来源分析错误归analysis、选段/因果规划错误归adaptation_plan、执行写作错误归screenplay。发现多层问题可分别列出，不改来源迁就正文，不只审开头。无major/blocking仅表示机器文本可交导演，不代表用户采用、普遍创作品质或视频通过。"""


def _issue(code, path, message, stage):
    return {"code": code, "path": path, "message": message,
            "severity": "major", "responsible_stage": stage}


def _deduplicated(issues):
    seen = set()
    result = []
    for issue in issues:
        key = (issue["code"], issue["path"], issue["message"], issue["responsible_stage"])
        if key not in seen:
            seen.add(key)
            result.append(issue)
    return result


def _finite(value, path, stage, issues):
    if isinstance(value, float) and not math.isfinite(value):
        issues.append(_issue("NON_FINITE_NUMBER", path, "数值必须有限", stage))
    elif isinstance(value, dict):
        for key, item in value.items():
            _finite(item, f"{path}.{key}", stage, issues)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _finite(item, f"{path}[{index}]", stage, issues)


def _schema_errors(schema, value, stage):
    issues = []
    for error in Draft202012Validator(schema).iter_errors(value):
        path = "$" + "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in error.absolute_path)
        issues.append(_issue("SCHEMA", path, error.message, stage))
    _finite(value, "$", stage, issues)
    return issues


def _items(value, key):
    items = value.get(key, []) if isinstance(value, dict) else []
    return items if isinstance(items, list) else []


def _id_set(items, path, stage, issues, key="id"):
    seen = set()
    for index, item in enumerate(items):
        identity = item.get(key) if isinstance(item, dict) else None
        if not isinstance(identity, str):
            continue
        if identity in seen:
            issues.append(_issue("DUPLICATE_ID", f"{path}[{index}].{key}", f"重复ID：{identity}", stage))
        seen.add(identity)
    return seen


def _check_ids(values, allowed, path, stage, issues):
    if not isinstance(values, list):
        return
    seen = set()
    for index, identity in enumerate(values):
        if not isinstance(identity, str):
            continue
        if identity in seen:
            issues.append(_issue("DUPLICATE_REFERENCE", f"{path}[{index}]", f"重复引用：{identity}", stage))
        if identity not in allowed:
            issues.append(_issue("UNKNOWN_REFERENCE", f"{path}[{index}]", f"未知引用：{identity}", stage))
        seen.add(identity)


def resolve_source_ref(text, ref):
    """Locate one exact short quote without changing the native model payload.

    Optional occurrence is zero-based (overlapping matches are counted).
    Ambiguous/missing anchors raise ValueError; callers must not guess a span.
    """
    if not isinstance(text, str) or not isinstance(ref, dict):
        raise ValueError("SOURCE_QUOTE: invalid text or reference")
    quote = ref.get("quote")
    if not isinstance(quote, str) or not quote.strip():
        raise ValueError("SOURCE_QUOTE: quote must be nonempty")
    positions = []
    start = text.find(quote)
    while start >= 0:
        positions.append(start)
        start = text.find(quote, start + 1)
    if not positions:
        raise ValueError("SOURCE_QUOTE: quote not found in frozen source")
    occurrence = ref.get("occurrence")
    if "occurrence" not in ref:
        if len(positions) != 1:
            raise ValueError("SOURCE_AMBIGUOUS: repeated quote needs occurrence or a longer unique quote")
        occurrence = 0
    if type(occurrence) is not int or not 0 <= occurrence < len(positions):
        raise ValueError("SOURCE_OCCURRENCE: occurrence is outside exact quote matches")
    start = positions[occurrence]
    return start, start + len(quote)


def resolve_selection_range(text, ref):
    """Locate inclusive boundary quotes as a half-open source range."""
    if not isinstance(ref, dict):
        raise ValueError("SOURCE_RANGE: invalid selection")
    start_ref = {"quote": ref.get("start_quote")}
    end_ref = {"quote": ref.get("end_quote")}
    if "start_occurrence" in ref:
        start_ref["occurrence"] = ref["start_occurrence"]
    if "end_occurrence" in ref:
        end_ref["occurrence"] = ref["end_occurrence"]
    start, start_end = resolve_source_ref(text, start_ref)
    end_start, end = resolve_source_ref(text, end_ref)
    if start > end_start or start_end > end:
        raise ValueError("SOURCE_RANGE: selection boundary quotes are reversed")
    return start, end


def _check_refs(value, text, stage, issues, path="$", selected=None):
    if isinstance(value, dict):
        if "quote" in value or "start_quote" in value:
            try:
                start, end = resolve_selection_range(text, value) if "start_quote" in value else resolve_source_ref(text, value)
                if selected is not None and not (selected[0] <= start < end <= selected[1]):
                    issues.append(_issue("OUTSIDE_SELECTED_RANGE", path, "关键依据超出本稿选段范围", stage))
            except ValueError as exc:
                issues.append(_issue(str(exc).split(":", 1)[0], path, str(exc), stage))
        for key, item in value.items():
            _check_refs(item, text, stage, issues, f"{path}.{key}", selected)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _check_refs(item, text, stage, issues, f"{path}[{index}]", selected)


def _seconds(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _reading_minimum(text):
    """Public conservative estimate: CJK/6 + Latin words/3, no audio claim."""
    if not isinstance(text, str):
        return 0.0
    cjk = len(re.findall(r"[\u3400-\u9fff\uf900-\ufaff]", text))
    words = len(re.findall(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*", text))
    return cjk / 6.0 + words / 3.0


def validate_stage(stage, value, context):
    """Aggregate structural/source/timing diagnostics; never semantic approval."""
    if stage not in STAGES:
        raise ValueError(f"unknown adaptation stage: {stage}")
    issues = _schema_errors(SCHEMAS[stage], value, stage)
    if not isinstance(context, dict):
        issues.append(_issue("STAGE_CONTEXT", "$", "阶段上下文必须为冻结对象", stage))
        context = {}
    if not isinstance(value, dict):
        return issues
    source = context.get("source", {})
    text = source.get("text") if isinstance(source, dict) else None
    if not isinstance(text, str) or not text:
        issues.append(_issue("SOURCE_CONTEXT", "$", "缺少完整冻结source.text", stage))
        text = ""
    _check_refs(value, text, stage, issues)
    if stage in ("analysis", "screenplay"):
        for index, character in enumerate(_items(value, "characters")):
            if isinstance(character, dict) and character.get("id") == "narrator":
                issues.append(_issue("RESERVED_CHARACTER_ID", f"$.characters[{index}].id", "narrator保留给voiceover旁白，不能作为角色ID", stage))
    if stage == "analysis":
        characters = _id_set(_items(value, "characters"), "$.characters", stage, issues)
        storyline = _id_set(_items(value, "storyline"), "$.storyline", stage, issues)
        _id_set(_items(value, "highlights"), "$.highlights", stage, issues)
        for index, highlight in enumerate(_items(value, "highlights")):
            if isinstance(highlight, dict):
                _check_ids(highlight.get("character_ids"), characters, f"$.highlights[{index}].character_ids", stage, issues)
                _check_ids(highlight.get("storyline_ids"), storyline, f"$.highlights[{index}].storyline_ids", stage, issues)
    elif stage == "adaptation_plan":
        analysis = context.get("analysis", {})
        characters = {item["id"] for item in _items(analysis, "characters") if isinstance(item, dict) and isinstance(item.get("id"), str)}
        highlights = {item["id"] for item in _items(analysis, "highlights") if isinstance(item, dict) and isinstance(item.get("id"), str)}
        _check_ids(value.get("selected_character_ids"), characters, "$.selected_character_ids", stage, issues)
        _check_ids(value.get("selected_highlight_ids"), highlights, "$.selected_highlight_ids", stage, issues)
        beats = _items(value, "causal_beats")
        _id_set(beats, "$.causal_beats", stage, issues)
        _id_set(_items(value, "preserved_facts"), "$.preserved_facts", stage, issues)
        selected = value.get("selected_character_ids", [])
        selected = set(x for x in selected if isinstance(x, str)) if isinstance(selected, list) else set()
        phases = [item.get("phase") for item in beats if isinstance(item, dict)]
        for phase in ("setup", "stimulus", "reaction", "escalation"):
            if phase not in phases:
                issues.append(_issue("MISSING_CAUSAL_PHASE", "$.causal_beats", f"缺少{phase}阶段", stage))
        if not any(phase in phases for phase in ("closure", "cliffhanger")):
            issues.append(_issue("MISSING_ENDING", "$.causal_beats", "缺少收束或悬念终态", stage))
        elif not phases or phases[-1] not in ("closure", "cliffhanger"):
            issues.append(_issue("CAUSAL_ENDING_ORDER", "$.causal_beats", "最后一个因果拍须明确收束或悬念终态", stage))
        for index, beat in enumerate(beats):
            if isinstance(beat, dict):
                _check_ids(beat.get("character_ids"), selected, f"$.causal_beats[{index}].character_ids", stage, issues)
        if all(phase in phases for phase in ("setup", "stimulus", "reaction", "escalation")):
            if not (phases.index("setup") < phases.index("stimulus") < phases.index("reaction") < phases.index("escalation")):
                issues.append(_issue("CAUSAL_PHASE_ORDER", "$.causal_beats", "首个铺垫、刺激、反应和升级顺序不正确", stage))
        ref = value.get("source_ref", {})
        try:
            selected_range = resolve_selection_range(text, ref)
        except ValueError:
            selected_range = None  # the aggregate source walk already reported it
        if selected_range is not None:
            for key in ("causal_beats", "preserved_facts"):
                _check_refs(value.get(key, []), text, stage, issues, f"$.{key}", selected_range)
            selected_highlights = value.get("selected_highlight_ids", [])
            selected_highlights = {identity for identity in selected_highlights if isinstance(identity, str)} if isinstance(selected_highlights, list) else set()
            for index, highlight in enumerate(_items(analysis, "highlights")):
                if isinstance(highlight, dict) and isinstance(highlight.get("id"), str) and highlight["id"] in selected_highlights:
                    _check_refs(highlight.get("source_refs", []), text, stage, issues, f"$.selected_highlight_ids[{index}].source_refs", selected_range)
    else:
        _validate_screenplay(value, context, issues)
    return _deduplicated(issues)


def _validate_screenplay(value, context, issues):
    stage = "screenplay"
    characters = _id_set(_items(value, "characters"), "$.characters", stage, issues)
    plan = context.get("adaptation_plan", {})
    selected = plan.get("selected_character_ids", []) if isinstance(plan, dict) else []
    selected = {item for item in selected if isinstance(item, str)} if isinstance(selected, list) else set()
    if characters != selected:
        issues.append(_issue("CAST_PLAN_MISMATCH", "$.characters", "本稿角色卡须完整匹配改编计划选角", stage))
    analysis_names = {item["id"]: item.get("name") for item in _items(context.get("analysis", {}), "characters") if isinstance(item, dict) and isinstance(item.get("id"), str)}
    for index, character in enumerate(_items(value, "characters")):
        if isinstance(character, dict) and isinstance(character.get("id"), str) and character["id"] in analysis_names and character.get("name") != analysis_names[character["id"]]:
            issues.append(_issue("CHARACTER_IDENTITY", f"$.characters[{index}].name", "角色ID对应姓名与来源分析不同", stage))
    scenes = _items(value, "scenes")
    _id_set(scenes, "$.scenes", stage, issues)
    all_events = set()
    used_characters = set()
    emotional_focus_count = 0
    total = 0.0
    duration_valid = True
    for si, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        path = f"$.scenes[{si}]"
        present = scene.get("present_character_ids", [])
        _check_ids(present, characters, f"{path}.present_character_ids", stage, issues)
        present = {item for item in present if isinstance(item, str)} if isinstance(present, list) else set()
        used_characters.update(present)
        events = _items(scene, "events")
        prior = set()
        visible_reactions = set()
        focus_events = set()
        for ei, event in enumerate(events):
            if not isinstance(event, dict):
                continue
            ep = f"{path}.events[{ei}]"
            identity = event.get("id")
            if isinstance(identity, str):
                if identity in all_events:
                    issues.append(_issue("DUPLICATE_EVENT_ID", f"{ep}.id", f"事件ID全稿重复：{identity}", stage))
                all_events.add(identity)
            kind, actor = event.get("kind"), event.get("actor_id")
            if not isinstance(actor, str) or (actor not in present and not (kind == "voiceover" and actor == "narrator")):
                issues.append(_issue("ACTOR_NOT_PRESENT", f"{ep}.actor_id", "事件主体须为在场人物；旁白可用narrator", stage))
            states = _items(event, "character_states")
            state_ids = _id_set(states, f"{ep}.character_states", stage, issues, "character_id")
            if state_ids != present:
                issues.append(_issue("PRESENT_STATE_COVERAGE", f"{ep}.character_states", "每事件须明确本场全部且仅在场人物状态", stage))
            duration = event.get("duration_seconds")
            if _seconds(duration):
                total += duration
                if kind in ("dialogue", "voiceover"):
                    minimum = _reading_minimum(event.get("text"))
                    if duration + 1e-9 < minimum:
                        issues.append(_issue("SPEECH_TIME_LOWER_BOUND", f"{ep}.duration_seconds", f"保守阅读估算至少{minimum:.2f}秒（中文6字/秒、英文3词/秒）", stage))
                if (kind == "reaction" or event.get("emotional_focus") is True) and duration < 1:
                    issues.append(_issue("EMOTION_WINDOW", f"{ep}.duration_seconds", "重要情绪/可见反应至少保留1秒结构窗口，实际表演由全文审查判断", stage))
            else:
                duration_valid = False
            stimulus = event.get("stimulus_event_id")
            if stimulus and (not isinstance(stimulus, str) or stimulus not in prior):
                issues.append(_issue("STIMULUS_ORDER", f"{ep}.stimulus_event_id", "刺激须引用本场此前事件", stage))
            if kind == "reaction":
                if not stimulus:
                    issues.append(_issue("REACTION_WITHOUT_STIMULUS", f"{ep}.stimulus_event_id", "反应必须绑定本场此前刺激", stage))
                elif isinstance(stimulus, str) and stimulus in prior:
                    visible_reactions.add(stimulus)
            if event.get("emotional_focus") is True and kind != "reaction" and isinstance(identity, str):
                focus_events.add(identity)
                emotional_focus_count += 1
            if isinstance(identity, str):
                prior.add(identity)
        for identity in sorted(focus_events - visible_reactions):
            issues.append(_issue("MISSING_VISIBLE_REACTION", f"{path}.events", f"重要刺激{identity}缺少随后绑定的可见reaction事件", stage))
    if characters - used_characters:
        issues.append(_issue("UNUSED_SELECTED_CHARACTER", "$.characters", "计划角色未在任何场次出现", stage))
    if not emotional_focus_count:
        issues.append(_issue("MISSING_EMOTIONAL_FOCUS", "$.scenes", "改编高潮须明确至少一个情绪刺激重心及后续可见反应", stage))
    if duration_valid and _seconds(value.get("duration_seconds")) and abs(value["duration_seconds"] - total) > 0.01:
        issues.append(_issue("DURATION_SUM", "$.duration_seconds", f"整稿时长须等于顺序事件合计{total:.2f}秒；事件内动作对白可重叠", stage))


def validate_review(value, context):
    """Validate review coverage only; runtime binds this to the exact request."""
    issues = _schema_errors(REVIEW_SCHEMA, value, "screenplay")
    if not isinstance(context, dict):
        context = {}
    if not isinstance(value, dict):
        return issues
    dimensions = _id_set(_items(value, "dimensions"), "$.dimensions", "screenplay", issues, "dimension")
    if dimensions != set(REVIEW_DIMENSIONS):
        issues.append(_issue("REVIEW_COVERAGE", "$.dimensions", "全文审查须逐一覆盖全部规定维度", "screenplay"))
    for stage in STAGES:
        if not isinstance(context.get(stage), dict):
            issues.append(_issue("REVIEW_CONTEXT", "$", f"全文审查缺少完整{stage}", "screenplay"))
    source = context.get("source", {})
    if not isinstance(source, dict) or not isinstance(source.get("text"), str) or not source["text"]:
        issues.append(_issue("REVIEW_CONTEXT", "$", "全文审查缺少冻结正文", "screenplay"))
    return issues


def render_screenplay(value):
    """Deterministically project the one canonical screenplay, without invention."""
    lines = [f"# {value['title']}", "", f"预计时长：{value['duration_seconds']}秒", "", "## 世界与前情", ""]
    world = value["world"]
    for key, label in (("era", "时代"), ("daily_context", "日常环境"), ("space_and_prior_events", "空间与前情")):
        lines.extend([f"{label}：{world[key]}", ""])
    if world["unknowns"]:
        lines.extend(["原文未交代：" + "；".join(world["unknowns"]), ""])
    lines.extend(["## 角色", ""])
    names = {item["id"]: item["name"] for item in value["characters"]}
    for character in value["characters"]:
        lines.extend([f"### {character['id']} · {character['name']}", ""])
        for key, label in (("identity", "身份"), ("personality", "性格"), ("situation", "处境"), ("goal", "目标"), ("relationships", "关系")):
            lines.extend([f"{label}：{character[key]}", ""])
        for ref in character["source_refs"]:
            occurrence = f"（第{ref['occurrence'] + 1}次出现）" if "occurrence" in ref else ""
            lines.extend([f"原文依据{occurrence}：{ref['quote']}", ""])
    for scene in value["scenes"]:
        lines.extend([f"## {scene['id']} · {scene['location']}", "", f"时间线：{scene['timeline']}；时间：{scene['time']}", "",
                      "在场：" + "、".join(f"{identity} {names[identity]}" for identity in scene["present_character_ids"]), "",
                      f"段首状态：{scene['start_state']}", ""])
        for event in scene["events"]:
            actor = "旁白" if event["actor_id"] == "narrator" else names[event["actor_id"]]
            labels = {"action": "动作", "dialogue": "对白", "reaction": "反应", "voiceover": "旁白"}
            lines.extend([f"### {event['id']} · {labels[event['kind']]} · {event['duration_seconds']}秒", "",
                          f"{actor}：{event['text']}", ""])
            if event["emotional_focus"]:
                lines.extend(["情绪重心：是", ""])
            if event["stimulus_event_id"]:
                lines.extend([f"承接刺激：{event['stimulus_event_id']}", ""])
            for state in event["character_states"]:
                lines.extend([f"{names[state['character_id']]}：动作—{state['action']}；神情—{state['expression']}；视线—{state['gaze']}", ""])
        lines.extend([f"段尾状态：{scene['end_state']}", ""])
    lines.extend(["## 结尾", "", f"{value['ending']['type']}：{value['ending']['description']}", ""])
    if value["adaptation_notes"]:
        lines.extend(["## 改编说明", ""])
        for note in value["adaptation_notes"]:
            lines.extend([note, ""])
    return "\n".join(lines).rstrip() + "\n"
