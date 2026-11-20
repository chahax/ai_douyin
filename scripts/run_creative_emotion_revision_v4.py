"""One source-bound content replacement after a known complete reviewed draft."""
from copy import deepcopy
from pathlib import Path
import json
import argparse
import sys
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from scripts import run_creative_emotion_revision_v3 as prior
from scripts import run_creative_emotion_revision_v1 as base
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_creative_resume_v4 as factory
from scripts import run_creative_resume_v10 as identity
from src.content_factory.creative_story_emotion import digest
from src.content_factory.creative_story_emotion_input_v2 import build_complete_revision_input
from src.content_factory.creative_emotion_review_v2 import validate_complete_review_v2
from scripts.prepare_creative_emotion_workflow import write_new

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT / "data/production_revisions/this_time_i_leave_emotion_revision_r4_20261007"
VERSION = "complete_emotion_content_replacement/v4"


def prepare():
    ROOT.mkdir(parents=True, exist_ok=True)
    if not (ROOT / "ANCHOR.json").exists():
        parent = prior.runtime()
        ledger = control.read(parent.ledger)
        parent.check(ledger)
        receipts = prior.records()
        draft = next(r for r in receipts if r["ordinal"] == 270)
        review = next(r for r in receipts if r["ordinal"] == 271)
        if draft["status"] != "contract_valid" or type(review["response_metadata"].get("total_tokens")) is not int:
            raise ValueError("known complete draft and known review outcome required")
        script = draft["document_output"]
        brief = control.read(base.QA / "inputs/EMOTIONAL_BRIEF.json")
        acceptance = validate_complete_review_v2(review["output"], script, brief)
        write_new(ROOT / "ORIGINAL_REVIEW_271_ACCEPTANCE_V2.json", acceptance)
        creative_brief = control.read(base.QA / "inputs/ORIGINAL_CREATIVE_BRIEF.json")
        direction = control.read(base.QA / "inputs/CONFIRMED_STORY_DIRECTION.json")
        feedback = {"scope": "new complete content revision after known reviewed outcome; no interface retry",
            "original_user_feedback": control.read(base.QA / "inputs/ORIGINAL_HUMAN_FEEDBACK.json"),
            "confirmed_story_direction": direction,
            "previous_draft_ordinal": 270, "original_review_ordinal": 271,
            "original_review_sha256": digest(review["output"]),
            "verified_content_findings": [
                {"issue": "只有上个月报销单一个过去事例，林屿也说那次；未交代反复替他加班。",
                 "source": "script.beats.2.steps.0.text", "quote": script["beats"][2]["steps"][0]["text"]},
                {"issue": "拒绝后的反应主要是看包和单据、收笔、移便利贴；人的表情、视线及沉默没有承载默认被打破。",
                 "source": "script.beats.6.steps.0.text", "quote": script["beats"][6]["steps"][0]["text"]},
                {"issue": "她在走廊获得释放之后又切回林屿改单，当前情绪简报要求先兑现他接回工作，结尾落在她赴约。",
                 "source": "script.beats.10.steps.0.text", "quote": script["beats"][10]["steps"][0]["text"]}],
            "unadopted_review_opinions": [
                "271的F02要求第二次劝留；用户已确认短暂劝留这一级阻力，不增加一轮劝留或争吵。",
                "不把拿笔、揭便利贴、走两步当成独立故事事件；具体手部操作、坐标、时长留给后续表演与编译。"],
            "author_freedom": "依据完整原简报和用户确认重新创作整篇，不按旧稿十一拍逐项润色；保留两人、电影和生活化写实关系。"}
        pack = control.read(base.QA / "inputs/FULL_R01_REFERENCE_PACK.json")
        request_input = build_complete_revision_input(script, brief, pack, feedback, creative_brief=creative_brief)
        request_input["messages"][0]["content"] = (
            "你是本片编剧。依据完整creative_brief、用户确认和R01表达参考提交完整新稿，previous_script只是问题证据，不是拍数或动作模板。"
            "完整保留原简报的约束和关系：拒绝前让观众知道她曾反复替同事加班；她先说今晚已有电影安排，他短暂劝留，她明确坚持。"
            "坚持前后由人物面对彼此的反应承载变化；他的工作实质接回后，结尾落在她赴约。"
            "保持两人、克制写实，不额外劝留一轮、不争吵、不补偿、不突然完美理解。"
            "本阶段写故事，动作描述可见的反应和事件，不写手部操作序列、厘米、逐秒表演或镜头参数。"
            "允许调整拍数与时长，按观众信息和人物选择组织完整beats，所有对白及必要行动写在steps。不要返回修补片段。")
        write_new(ROOT / "VERIFIED_CONTENT_FEEDBACK.json", feedback)
        write_new(ROOT / "COMPLETE_REVISION_INPUT.json", request_input)
        stats = prior.summary()
        inherited = {"calls_started": stats["effective_calls_started"], "reported_tokens": stats["effective_reported_tokens"],
                     "calls_with_known_usage": ledger["starting_spend"]["calls_with_known_usage"] + len(ledger["calls"]), "unknown_token_reservations": stats["unknown_token_reservations"],
                     "pending_ordinals": [70, 160], "parent_ledger_sha256": control.sha_file(parent.ledger)}
        files = [parent.ledger, prior.ROOT / "ANCHOR.json",
                 prior.ROOT / "call_270_complete_emotion_draft_r3.json",
                 prior.ROOT / "call_271_complete_emotion_full_review_r3.json"]
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
               PROJECT / "scripts/run_creative_emotion_revision_v3.py",
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
    receipt = runtime().dispatch("complete_emotion_draft_r4", wire, lambda v: base.validate_script(v, previous))
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
    drafts = [r for r in records() if r["label"] == "complete_emotion_draft_r4"]
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
              "用户已确认仅短暂劝留一轮，不把必须再劝一次或口头和解作为问题；核对已确认方向及原简报，不引入新强度阈值。"
              "不靠添加更多操作解决弱冲突，不指定新台词正文。实际语速口型和表演未生成，不判断媒体通过。"
              "creative_quality_passed必须false；所有满足仍等待用户内容确认。")
    wire = factory.wire("director", [{"role": "system", "content": prompt},
        {"role": "user", "content": json.dumps(context, ensure_ascii=False)}],
        base.review_schema(script, brief), 6500, {"script_sha256": digest(script),
        "brief_sha256": digest(brief), "full_reference_pack_sha256": digest(inp["reference_pack"]),
        "source_draft_ordinal": drafts[0]["ordinal"]})
    wire["operator_version"] = VERSION
    control.write(ROOT / "request_previews/full_review.json", wire, True)
    receipt = runtime().dispatch("complete_emotion_full_review_r4", wire,
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

