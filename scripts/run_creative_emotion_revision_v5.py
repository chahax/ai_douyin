"""One source-bound content replacement after a known complete reviewed draft."""
from copy import deepcopy
from pathlib import Path
import json
import argparse
import sys
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from scripts import run_creative_emotion_revision_v4 as prior
from scripts import run_creative_emotion_revision_v1 as base
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_creative_resume_v4 as factory
from scripts import run_creative_resume_v10 as identity
from src.content_factory.creative_story_emotion import digest
from src.content_factory.creative_story_emotion_input_v3 import build_fresh_story_input
from src.content_factory.creative_emotion_review_v2 import validate_complete_review_v2
from scripts.prepare_creative_emotion_workflow import write_new

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT / "data/production_revisions/this_time_i_leave_emotion_revision_r5_20261007"
VERSION = "complete_emotion_content_replacement/v5"


def prepare():
    ROOT.mkdir(parents=True, exist_ok=True)
    if not (ROOT / "ANCHOR.json").exists():
        parent = prior.runtime()
        ledger = control.read(parent.ledger)
        parent.check(ledger)
        receipts = prior.records()
        draft = next(r for r in receipts if r["ordinal"] == 272)
        review = next(r for r in receipts if r["ordinal"] == 273)
        if draft["status"] != "contract_valid" or type(review["response_metadata"].get("total_tokens")) is not int:
            raise ValueError("known complete draft and known review outcome required")
        script = draft["document_output"]
        brief = control.read(base.QA / "inputs/EMOTIONAL_BRIEF.json")
        acceptance = validate_complete_review_v2(review["output"], script, brief)
        write_new(ROOT / "ORIGINAL_REVIEW_273_ACCEPTANCE_V2.json", acceptance)
        creative_brief = control.read(base.QA / "inputs/ORIGINAL_CREATIVE_BRIEF.json")
        direction = control.read(base.QA / "inputs/CONFIRMED_STORY_DIRECTION.json")
        feedback = {"scope": "fresh complete story from full original brief; known previous outcome; no interface retry",
            "original_user_feedback": control.read(base.QA / "inputs/ORIGINAL_HUMAN_FEEDBACK.json"),
            "confirmed_story_direction": direction,
            "previous_draft_ordinal": 272, "original_review_ordinal": 273,
            "original_review_sha256": digest(review["output"]),
            "verified_content_findings": [
                {"source": "script.beats.9.steps.0.text", "quote": script["beats"][9]["steps"][0]["text"],
                 "issue": "最后仍是他改单，丢失了她在门外赴约的情绪释放，不符合已确认结尾。"}],
            "stage_assignments": {
                "writer": "观众信息、人物互动、过去反复帮忙的事实、当场选择、责任转移和她赴约的收束。",
                "director": "观察对象、反应近景、切镜理由、合并生成段；不得将这些欠项要求编剧逐秒排手部操作。",
                "performance_and_compiler": "实际窗口、对白前中后留白、道具当前持有和动作前提。"},
            "unadopted_review_opinions": [
                "273的F01承认两次对白已兑现历史，却要求同时补可见旁证；原条件是对白或可见后果，不是两者同时必需。",
                "273的F02是后续导演构图窗口待办，不能作为故事正文已失败的理由。",
                "保持短暂劝留一级阻力，不新增一轮劝留、口头和解或第三人。"]}
        pack = control.read(base.QA / "inputs/FULL_R01_REFERENCE_PACK.json")
        character_path = base.PRIOR / "DELIVERABLE_s7_d1/STATIC_ASSET_DEFINITIONS.json"
        characters = control.read(character_path)["characters"]
        request_input = build_fresh_story_input(script, brief, pack, feedback,
            creative_brief=creative_brief, characters=characters)
        write_new(ROOT / "PRIOR_COMPLETE_SCRIPT_EVIDENCE.json", script)
        write_new(ROOT / "VERIFIED_CONTENT_FEEDBACK.json", feedback)
        write_new(ROOT / "COMPLETE_REVISION_INPUT.json", request_input)
        stats = prior.summary()
        inherited = {"calls_started": stats["effective_calls_started"], "reported_tokens": stats["effective_reported_tokens"],
                     "calls_with_known_usage": ledger["starting_spend"]["calls_with_known_usage"] + len(ledger["calls"]), "unknown_token_reservations": stats["unknown_token_reservations"],
                     "pending_ordinals": [70, 160], "parent_ledger_sha256": control.sha_file(parent.ledger)}
        files = [parent.ledger, prior.ROOT / "ANCHOR.json",
                 prior.ROOT / "call_272_complete_emotion_draft_r4.json",
                 prior.ROOT / "call_273_complete_emotion_full_review_r4.json"]
        files += list((base.QA / "inputs").glob("*.json"))
        files.append(character_path)
        write_new(ROOT / "ANCHOR.json", {"inherited": inherited, "models": ledger["model_configs"],
            "parent_files": {str(p): control.sha_file(p) for p in files},
            "scope": "one new complete content draft and one full review; preserve original rejected review and all old unknown calls"})
    return runtime().prepare()


def runtime():
    a = control.read(ROOT / "ANCHOR.json")
    def guard():
        prior.runtime().check(control.read(prior.runtime().ledger))
        for p, h in a["parent_files"].items():
            if control.sha_file(p) != h:
                raise ValueError("parent evidence changed")
        for role, cfg in a["models"].items():
            live = factory.legacy.role_config(role)
            if live.model != cfg["model"] or live.base_url != cfg["base_url"]:
                raise ValueError("model switch not authorized")
    sources = [Path(__file__).resolve(), ROOT / "ANCHOR.json", ROOT / "COMPLETE_REVISION_INPUT.json",
               ROOT / "VERIFIED_CONTENT_FEEDBACK.json",
               PROJECT / "src/content_factory/creative_emotion_review_v2.py",
               PROJECT / "scripts/run_creative_emotion_revision_v1.py",
               PROJECT / "src/content_factory/creative_story_emotion.py",
               PROJECT / "src/content_factory/creative_story_emotion_input_v2.py",
               PROJECT / "src/content_factory/creative_story_emotion_input_v3.py",
               ROOT / "PRIOR_COMPLETE_SCRIPT_EVIDENCE.json",
               PROJECT / "scripts/run_creative_emotion_revision_v2.py",
               PROJECT / "scripts/run_creative_emotion_revision_v3.py",
               PROJECT / "scripts/run_creative_emotion_revision_v4.py",
               PROJECT / "scripts/creative_resume_dispatch_v3.py",
               PROJECT / "scripts/creative_json_document_transport_v1.py",
               PROJECT / "scripts/run_creative_resume_v4.py"]
    return control.ContinuationRuntime(PROJECT, ROOT, sources, a["inherited"], a["models"],
        inherited_guard=guard, quota_state=None, shared_lock=identity.SHARED_LOCK)


def summary():
    value = runtime().summary()
    value["new_unknown_token_reservations"] = value["unknown_token_reservations"]
    inherited = control.read(ROOT / "ANCHOR.json")["inherited"]["unknown_token_reservations"]
    value["inherited_unknown_token_reservations"] = inherited
    value["unknown_token_reservations"] += inherited
    value["unknown_outcome_ordinals"] = [70]
    value["unknown_usage_ordinals"] = [70, 160]
    return value


def records():
    rt = runtime()
    rt.check(control.read(rt.ledger))
    return [control.read(ROOT / r["receipt"]) for r in control.read(rt.ledger)["calls"]]


def draft():
    prepare()
    inp = control.read(ROOT / "COMPLETE_REVISION_INPUT.json")
    previous = control.read(ROOT / "PRIOR_COMPLETE_SCRIPT_EVIDENCE.json")
    wire = factory.wire("writer", inp["messages"], base.script_schema(previous), 10000, inp["bindings"])
    wire["operator_version"] = VERSION
    control.write(ROOT / "request_previews/draft.json", wire, True)
    receipt = runtime().dispatch("complete_emotion_draft_r5", wire, lambda v: base.validate_script(v, previous))
    if receipt["status"] == "contract_valid":
        doc = receipt["document_output"]
        folder = ROOT / "COMPLETE_DRAFT_AWAITING_FULL_REVIEW"
        folder.mkdir(exist_ok=True)
        write_new(folder / "FULL_SCRIPT.json", doc)
        lines = ["# " + doc["title"], "", doc["premise"], ""]
        for b in doc["beats"]:
            lines += ["## " + b["id"] + " " + b["event"], ""]
            for s in b["steps"]:
                lines += [("**" + s["speaker"] + "**：" if s["kind"] == "dialogue" else "") + s["text"], ""]
        write_new(folder / "FULL_SCRIPT.md", "\n".join(lines) + "\n")
    return receipt


def review():
    prepare()
    drafts = [r for r in records() if r["label"] == "complete_emotion_draft_r5"]
    if len(drafts) != 1 or drafts[0]["status"] != "contract_valid":
        raise ValueError("complete source draft required")
    script = drafts[0]["document_output"]
    inp = json.loads(control.read(ROOT / "COMPLETE_REVISION_INPUT.json")["messages"][1]["content"])
    brief = inp["emotional_brief"]
    context = {"script": script, "creative_brief": inp["creative_brief"], "emotional_brief": brief, "reference_pack": inp["reference_pack"],
               "verified_feedback": inp["feedback"], "characters": inp["characters"],
               "source_text_paths": [f"script.beats.{i}.steps.{j}.text" for i, b in enumerate(script["beats"]) for j, _ in enumerate(b["steps"])]}
    prompt = (
        "全文审查当前完整故事，不代写。核对完整原creative_brief、用户确认和实际正文的因果、压力、选择、后果、释放。"
        "本阶段是故事验收：实际发生的矛盾、历史、选择、反应与结尾是编剧职责；机位、近景、秒数和手部操作是后续导演及表演职责，列入suggestions或calibration_focus。"
        "issues仅列当前正文对已存在要求的真实违反；不能把已满足条件的额外美化或下游待办判成major。"
        "历史条件是自然对白或可见后果，不能强行要求两者同时具备。用户已确认短暂劝留一级阻力，不强制第二轮劝留、口头和解或第三人。"
        "从source_text_paths逐字引用实际步骤，不因演出尚未生成就断言实际口型语速失败。"
        "story_preserved表示主题关系是否保留，issues独立决定是否返修。四项情绪判断必须有正文证据，必修问题同步进入issues。"
        "creative_quality_passed必须false；文本满足也须等待用户内容确认。")
    wire = factory.wire("director", [{"role": "system", "content": prompt},
        {"role": "user", "content": json.dumps(context, ensure_ascii=False)}],
        base.review_schema(script, brief), 6500, {"script_sha256": digest(script),
        "brief_sha256": digest(brief), "full_reference_pack_sha256": digest(inp["reference_pack"]),
        "source_draft_ordinal": drafts[0]["ordinal"]})
    wire["operator_version"] = VERSION
    control.write(ROOT / "request_previews/full_review.json", wire, True)
    receipt = runtime().dispatch("complete_emotion_full_review_r5", wire,
                                lambda value: validate_complete_review_v2(value, script, brief))
    if receipt["status"] == "contract_valid":
        write_new(ROOT / "FULL_REVIEW.json", receipt["output"])
        write_new(ROOT / "STORY_CHECKPOINT.json", {"schema": "reviewed_complete_emotion_story/v2",
            "script_sha256": digest(script), "review_sha256": digest(receipt["output"]),
            "status": "needs_complete_revision" if receipt["validation"]["needs_revision"] else "awaiting_human_content_confirmation",
            "creative_quality_passed": False, "human_approval": None,
            "director_plan_complete": False, "media_calls": 0})
    return receipt


def main():
    p = argparse.ArgumentParser()
    p.add_argument("operation", choices=["prepare", "draft", "review", "status"])
    a = p.parse_args()
    r = prepare() if a.operation == "prepare" else draft() if a.operation == "draft" else review() if a.operation == "review" else summary()
    print(json.dumps({k: r[k] for k in ("status", "ordinal", "validation", "failure") if k in r}
        if a.operation in {"draft", "review"} else r, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

