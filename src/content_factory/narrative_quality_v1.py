"""Frozen narrative quality requirements shared by every new v8 stage.

These are creative/review requirements, not a word-count quality classifier.
No service call, environment credentials or media inspection is performed here.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

VERSION = "narrative_quality/v1"
REQUIREMENTS = {
    "story_information": "开场迅速使观众理解当下目标或冲突；每段行动、对白或反应产生可理解的信息、判断或关系变化。背景说明不能代替正片演出，不为凑秒数延长单句或无意义静候。",
    "interaction": "所有在场人物均有符合处境的动作、神情和回应；写明谁对谁说、刺激如何引出回应，允许自然打断、重叠及有动机的沉默。多人和镜外/电话角色的身份范围明确。",
    "gaze_orientation": "具体说明目光对象及转移、头部与身体朝向和空间关系；不能让对话双方无动机地一直直视前方。合理避视、看物和独处成立，不强制全程互看。",
    "camera_readability": "重要信息、双方神情和反应必须在指定构图、景别或机位中可见；近景/特写/越肩随表达需要安排，不机械频繁切镜。不能用远景背影承载不可见的关键细微表情。",
    "timing": "按完整互动和冻结简报的总时长规划，动作对白和听者反应自然并行，保持自然语速。有效停顿有具体表达功能；不按固定秒数、字数或动作数判定内容质量。",
    "compilation": "服务分段保留完整互动和因果，不只选第一条表演；全部最终视频请求由同一编译器产出并进入同源整包审核，保留每位在场者的动作神情视线、听者反应、摄影及首尾变化。内部场记证据JSON不进入视频表演提示词。",
    "review": "DeepSeek对照冻结来源、完整稿、全部导演段与所有最终实际视频请求判断内容；非空字段和合同通过不代替语义判断。正文错误回编剧，导演/分段错误回导演，编译丢失修通用编译器后重新审核。",
    "media": "文本合格不是实际视频通过。视频由用户人工审核，不主动抽帧、听看、ASR或音画模型审核；未通过视频的原尾帧不得续用。独立媒体授权、历史失败与用量不因质量版本重置。",
}


def canonical_sha256(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def quality_policy() -> dict:
    content = {"version": VERSION, "requirements": deepcopy(REQUIREMENTS),
               "semantic_judge": "deepseek", "writer": "minimax",
               "program_checks": ["identity", "references", "coverage", "capabilities", "time", "request_binding"],
               "media_review": "user_manual_only"}
    return {**content, "sha256": canonical_sha256(content)}


def validate_quality_policy(value) -> None:
    if value != quality_policy():
        raise ValueError("Narrative quality policy differs from the frozen v8 policy")


def source_kind(source=None, brief=None) -> str:
    kind = (brief or {}).get("source_kind", (source or {}).get("source_kind", "novel"))
    if kind not in {"novel", "original"}:
        raise ValueError("source_kind must be novel or original")
    return kind
