"""Freeze visual storytelling requirements in new briefs, without migrating runs.

The existing five-stage native-text workflow carries this complete brief into
each request and binds the final review to the exact compiled video requests.
This module does not classify stories or call a model/media service.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from . import performance_timing_reference_v2 as timing
from .narrative_quality_v1 import canonical_sha256

VERSION = "visual_storytelling/v1"
BRIEF_KEY = "visual_storytelling"

REQUIREMENTS = {
    "opening_information": {
        "requirement": "首个有效动作与对白尽早交代关键人物关系、地点和眼前目标或矛盾，让观众从演出理解；不靠仅供模型阅读的世界框架或大段说明。悬念可有意暂隐身份，但须说明暂隐的信息和当下可理解的目标，不按固定秒数硬判。",
        "review_dimensions": ["mainline_and_motivation", "completeness"],
    },
    "visible_emotion": {
        "requirement": "情绪落实为由具体刺激引发的可见动作、神情、视线或声音变化，注明人物的意图和观众能读出的信息。普通状态可以开镜已成立；不把每个情绪都演成犹豫、慢走或长时间沉默。",
        "review_dimensions": ["emotion_windows", "shootability"],
    },
    "parallel_action_dialogue": {
        "requirement": "普通移动、拿放与神情变化在合理依赖下同对白并行，最后必要信息完成即收段；避免动作演完才说话、重复反应和空尾。不能为了快而瞬移或催念，也不能为表现情绪强加进门、走近等过场。",
        "review_dimensions": ["timing", "space_gaze_action"],
    },
    "relationship_interaction": {
        "requirement": "称呼、距离、目光、日常习惯和说听反应符合人物关系；明确谁对谁说、哪句话触发对方哪种反应，避免各自独立念台词。合理避视、稳定机位、独处和电话镜外人物均可成立，不强求两人同框或不断走动。",
        "review_dimensions": ["character_identity", "dialogue_naturality", "causality"],
    },
    "source_grounded_environment": {
        "requirement": "明确场景用途、时代、生活或工作条件、少量有信息的陈设、人物与出入口空间关系，区分原文已知和合理补足。保留来源关键场景；地点改换须有冻结brief中的明确依据，并同步核对道具、动机、走位和结尾。来源未知如实标注，不擅自换书、换故事或默认把温情戏改成家中。",
        "review_dimensions": ["mainline_and_motivation", "space_gaze_action", "shootability"],
    },
    "motivated_light": {
        "requirement": "按具体时间、天气、实际光源、空间材质和剧情选择光线与色彩，说明主体可见性并保持相邻段一致；变化须有时间或事件依据。温情不等于统一暖黄、阳光或旧家具，不用滤镜代替人物情绪。",
        "review_dimensions": ["shootability", "space_gaze_action", "emotion_windows"],
    },
    "motivated_camera_continuity": {
        "requirement": "明确景别、机位、运动及切换所服务的新信息；稳定镜头可保留，有效互动不等于相机不断动。逐一核对段内及跨段的尺度、轴线、视线、人物位置、道具、动作阶段和光线；推进或切特写有可读动机，避免无理由突然放大、跳位或重复动作。必要省略与有意跳切说明前后关系，不能一律禁止切镜。",
        "review_dimensions": ["space_gaze_action", "shootability", "causality"],
    },
}

STAGE_REQUIREMENTS = {
    "writer_full": "在自然完整稿中落实七项要求，世界框架、表演和对白相互一致；不新增固定标题、工具或双份JSON。",
    "review_full": "对照完整来源与剧本逐项语义审查七项规则，将具体结论归入原九维checks/assessment，问题给出原文或稿件位置、依据、影响和建议；不能仅复述规则或以字段非空代替判断。",
    "natural_director": "承接已通过完整稿，把表演、环境、光影和镜头落实到各服务段；明确相邻段切换、起止状态和有意省略，不为镜头效果自改剧情。",
    "extract_review": "对照全部来源、剧本和自然导演逐项审核并忠实整理；每个实际prompt只表达本段需要的正向场景、光线、动作、互动和摄影安排。内部检查表、禁止项清单和后续剧情不直接堆入提示词。缺失或矛盾返回revise，不替导演补写。",
    "final_review": "逐项对照全部实际SDK请求与完整来源、剧本、自然导演，检查七项要求有无丢失或自创，特别检查相邻请求的构图、场景、光线和动作衔接；给具体结论，不能只核对单段。沿原九维输出合同审查，无须新增JSON字段。",
}


def profile():
    body = {
        "version": VERSION,
        "requirements": deepcopy(REQUIREMENTS),
        "stage_requirements": deepcopy(STAGE_REQUIREMENTS),
        "responsibility": {
            "writer": "来源、人物关系、主线与正文环境逻辑错误回编剧。",
            "director": "表演可见性、空间、摄影、光影和分段衔接错误回导演。",
            "extractor": "忠实整理中的遗漏、自创或改秒数回整理阶段复核，不代写原稿。",
            "compiler": "实际请求丢失或改变已审内容，修复通用编译并重新整包审核。",
        },
        "review_contract": "复用原生全文九维审核及已有pass/revise门。实质问题必须定位；合理沉默、静镜、冷光或非家庭场景不自动判失败。七项是语义要求，不是关键词、动作数量、字数或固定秒数分类器。",
        "source_integrity": "原小说与原创来源类型、正文和书籍标识沿冻结来源保持；不得因审核失败或额度耗尽自动替换测试故事。本规则本身不证明书籍推广授权。",
        "media_boundary": "文本审核不证明成片没有跳变或人物漂移；成片继续由用户人工验收。补帧不能替代构图与空间连续性修复。不新增模型、媒体、重试或发布授权。",
        "automatic_scene_rewrite": False,
        "semantic_classifier": False,
        "media_review": "user_manual_only",
    }
    return {**body, "sha256": canonical_sha256(body)}


def apply_brief(brief):
    result = timing.apply_brief(brief)
    expected = profile()
    if BRIEF_KEY in result and result[BRIEF_KEY] != expected:
        raise ValueError("已有visual_storytelling版本不同或被修改，不能覆盖冻结规范")
    result[BRIEF_KEY] = expected
    return result


def prepare_source(source_run_dir, *, brief=None, runtime=None, **kwargs):
    binding = Path(source_run_dir).resolve() / "BINDING.json"
    if binding.exists():
        frozen = timing.pacing._read_binding(binding).get("brief")
        if not isinstance(frozen, dict) or frozen.get(BRIEF_KEY) != profile():
            raise ValueError("已有运行未冻结本视觉叙事规范，请使用原恢复入口；不能补写旧稿")
        if brief is None:
            brief = frozen
        elif apply_brief(brief) != frozen:
            raise ValueError("已有运行brief不同，不能覆盖冻结创作要求")
    return timing.prepare_source(source_run_dir, brief=apply_brief(brief), runtime=runtime, **kwargs)
