"""One source-bound content replacement after a known complete reviewed draft."""
from copy import deepcopy
from pathlib import Path
import json
import argparse
import sys
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from scripts import run_creative_emotion_revision_v2 as prior
from scripts import run_creative_emotion_revision_v1 as base
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_creative_resume_v4 as factory
from scripts import run_creative_resume_v10 as identity
from src.content_factory.creative_story_emotion import digest
from src.content_factory.creative_story_emotion_input_v2 import build_complete_revision_input
from src.content_factory.creative_emotion_review_v2 import validate_complete_review_v2
from scripts.prepare_creative_emotion_workflow import write_new

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT / "data/production_revisions/this_time_i_leave_emotion_revision_r3_20261007"
VERSION = "complete_emotion_content_replacement/v3"


def prepare():
    ROOT.mkdir(parents=True, exist_ok=True)
    if not (ROOT / "ANCHOR.json").exists():
        parent = prior.runtime()
        ledger = control.read(parent.ledger)
        parent.check(ledger)
        receipts = prior.records()
        draft = next(r for r in receipts if r["ordinal"] == 268)
        review = next(r for r in receipts if r["ordinal"] == 269)
        if draft["status"] != "contract_valid" or type(review["response_metadata"].get("total_tokens")) is not int:
            raise ValueError("known complete draft and known review outcome required")
        script = draft["document_output"]
        brief = control.read(base.QA / "inputs/EMOTIONAL_BRIEF.json")
        acceptance = validate_complete_review_v2(review["output"], script, brief)
        write_new(ROOT / "ORIGINAL_REVIEW_269_ACCEPTANCE_V2.json", acceptance)
        creative_brief = control.read(base.QA / "inputs/ORIGINAL_CREATIVE_BRIEF.json")
        direction = control.read(base.QA / "inputs/CONFIRMED_STORY_DIRECTION.json")
        feedback = {"scope": "complete new content revision, not interface retry",
            "original_user_feedback": control.read(base.QA / "inputs/ORIGINAL_HUMAN_FEEDBACK.json"),
            "confirmed_story_direction": direction,
            "previous_draft_ordinal": 268, "original_review_ordinal": 269,
            "verified_goals": [
                "必须保留原creative_brief的全部条件，特别是拒绝前让观众知道她过去不止一次替同事加班，不能只写背景或摸包。",
                "落实最新用户确认：她先说明已有安排，同事短暂劝留，她再坚持；保留两人克制关系，不争吵、不反派。",
                "对白和互动承载压力与选择，不用挪包、蹭票角、收手等小操作代替心理冲突。",
                "允许重写整篇、调整拍数、顺序和时长，不照旧十拍模板；把同事接回工作的后果先交清楚，结尾落在她赴约，不再回来重复对账。"],
            "original_review_sha256": digest(review["output"]),
            "unadopted_opinions": ["不要求强行口头和解或重复摸票；审查建议不是指定的新动作。"]}
        pack = control.read(base.QA / "inputs/FULL_R01_REFERENCE_PACK.json")
        request_input = build_complete_revision_input(script, brief, pack, feedback, creative_brief=creative_brief)
        request_input["messages"][0]["content"] += "当前不是微润色；不要把旧稿的十拍当模板，完整重构观众经历的压力、选择和释放。"
        write_new(ROOT / "VERIFIED_CONTENT_FEEDBACK.json", feedback)
        write_new(ROOT / "COMPLETE_REVISION_INPUT.json", request_input)
        stats = prior.summary()
        inherited = {"calls_started": stats["effective_calls_started"], "reported_tokens": stats["effective_reported_tokens"],
                     "calls_with_known_usage": ledger["starting_spend"]["calls_with_known_usage"] + len(ledger["calls"]), "unknown_token_reservations": stats["unknown_token_reservations"],
                     "pending_ordinals": [70, 160], "parent_ledger_sha256": control.sha_file(parent.ledger)}
        files = [parent.ledger, prior.ROOT / "ANCHOR.json",
                 prior.ROOT / "call_268_complete_emotion_draft_r2.json",
                 prior.ROOT / "call_269_complete_emotion_full_review_r2.json"]
        files += list((base.QA / "inputs").glob("*.json"))
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
               PROJECT / "scripts/run_creative_emotion_revision_v2.py",
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
    previous = json.loads(inp["messages"][1]["content"])["previous_script"]
    wire = factory.wire("writer", inp["messages"], base.script_schema(previous), 10000, inp["bindings"])
    wire["operator_version"] = VERSION
    control.write(ROOT / "request_previews/draft.json", wire, True)
    receipt = runtime().dispatch("complete_emotion_draft_r3", wire, lambda v: base.validate_script(v, previous))
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
    drafts = [r for r in records() if r["label"] == "complete_emotion_draft_r3"]
    if len(drafts) != 1 or drafts[0]["status"] != "contract_valid":
        raise ValueError("complete source draft required")
    script = drafts[0]["document_output"]
    inp = json.loads(control.read(ROOT / "COMPLETE_REVISION_INPUT.json")["messages"][1]["content"])
    brief = inp["emotional_brief"]
    context = {"script": script, "creative_brief": inp["creative_brief"], "emotional_brief": brief, "reference_pack": inp["reference_pack"],
               "verified_feedback": inp["feedback"],
               "source_text_paths": [f"script.beats.{i}.steps.{j}.text" for i, b in enumerate(script["beats"]) for j, _ in enumerate(b["steps"])]}
    prompt = ("全文审查当前完整新稿，不代写。检查人物、因果、道具当前持有、刺激反应及压力、选择、后果、释放。"
              "必须全文核对原creative_brief.constraints和avoid，情绪补充不能覆盖原条件；story_preserved只表示主题关系是否保留，issues单独决定是否需要返修。不要把审美偏好自动变成硬禁令。"
              "证据从source_text_paths逐字引用实际步骤，数组用数字索引；不能靠想象声称动作没发生。"
              "按pressure、choice、consequence、release填写四项判断，必修情绪问题也进入全文issues。"
              "不靠添加更多操作解决弱冲突，不指定新台词正文。实际语速口型和表演未生成，不判断媒体通过。"
              "creative_quality_passed必须false；所有满足仍等待用户内容确认。")
    wire = factory.wire("director", [{"role": "system", "content": prompt},
        {"role": "user", "content": json.dumps(context, ensure_ascii=False)}],
        base.review_schema(script, brief), 6500, {"script_sha256": digest(script),
        "brief_sha256": digest(brief), "full_reference_pack_sha256": digest(inp["reference_pack"]),
        "source_draft_ordinal": drafts[0]["ordinal"]})
    wire["operator_version"] = VERSION
    control.write(ROOT / "request_previews/full_review.json", wire, True)
    receipt = runtime().dispatch("complete_emotion_full_review_r3", wire,
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

