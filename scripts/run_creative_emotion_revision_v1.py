"""One complete MiniMax revision, then one full DeepSeek review; no auto retry."""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import argparse
import json
import sys
ROOT_PROJECT = Path(__file__).resolve().parents[1]
if str(ROOT_PROJECT) not in sys.path:
    sys.path.insert(0, str(ROOT_PROJECT))

from scripts import creative_resume_dispatch_v3 as control
from scripts import run_creative_resume_v4 as wire_factory
from scripts import run_creative_resume_v10 as identity
from src.content_factory.creative_story_emotion import digest, validate_emotion_review, CRITERIA
from scripts.prepare_creative_emotion_workflow import write_new

ROOT = ROOT_PROJECT / "data/production_revisions/this_time_i_leave_emotion_revision_20261007"
QA = ROOT_PROJECT / "data/qa/emotion_workflow_v1_20261007"
PRIOR = ROOT_PROJECT / "data/production_revisions/this_time_i_leave_s7_review_evidence_repair_20261006"
VERSION = "complete_emotion_revision/v1"


def obj(properties):
    return {"type": "object", "additionalProperties": False,
            "required": list(properties), "properties": properties}


def text():
    return {"type": "string", "minLength": 1}


def script_schema(previous):
    step = obj({"kind": {"enum": ["action", "dialogue"]},
                "speaker": {"type": "string"}, "text": text()})
    beat = obj({"id": text(), "event": text(), "trigger": text(),
                "steps": {"type": "array", "minItems": 1, "items": step}})
    return obj({"title": text(), "premise": text(),
                "selected_candidate_id": {"const": previous["selected_candidate_id"]},
                "beats": {"type": "array", "minItems": 1, "items": beat}})


def validate_script(value, previous):
    from jsonschema import Draft202012Validator
    Draft202012Validator(script_schema(previous)).validate(value)
    ids = [b["id"] for b in value["beats"]]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate beat identity")
    known = {s["speaker"] for b in previous["beats"] for s in b["steps"] if s["kind"] == "dialogue"}
    for b in value["beats"]:
        for s in b["steps"]:
            if (s["kind"] == "dialogue" and s["speaker"] not in known
                    or s["kind"] == "action" and s["speaker"]):
                raise ValueError("speaker identity differs from the two-person story")
    return {"complete_model_authored_revision": True, "manual_content_patch": False,
            "creative_quality_passed": False, "beat_count": len(ids)}


def exact_refs(refs, script):
    if not refs:
        raise ValueError("review needs exact current-source evidence")
    for r in refs:
        parts = r["path"].split(".")
        if (len(parts) != 6 or parts[0:2] != ["script", "beats"]
                or parts[3] != "steps" or parts[5] != "text"
                or not parts[2].isdigit() or not parts[4].isdigit()):
            raise ValueError("review evidence must point to played source text")
        target = script["beats"][int(parts[2])]["steps"][int(parts[4])]["text"]
        if r["quote"] != target:
            raise ValueError("review evidence quote changed")


def review_schema(script, brief):
    ref = obj({"path": text(), "quote": text()})
    issue = obj({"id": text(), "location": {"enum": [b["id"] for b in script["beats"]]},
                 "severity": {"enum": ["major", "blocking"]}, "rule": text(),
                 "evidence_refs": {"type": "array", "minItems": 1, "items": ref},
                 "impact": text(), "proposal": text()})
    criteria = obj({"criterion": {"enum": list(CRITERIA)},
                    "finding": {"enum": ["satisfied", "needs_revision", "uncertain"]},
                    "reason": text(), "evidence_refs": {"type": "array", "items": ref}})
    return obj({"full_text_review": obj({"story_preserved": {"type": "boolean"},
        "issues": {"type": "array", "items": issue},
        "suggestions": {"type": "array", "items": text()},
        "calibration_focus": {"type": "array", "items": text()}}),
        "emotion_review": obj({"schema": {"const": "story_emotion_checkpoint/v1"},
            "script_sha256": {"const": digest(script)}, "brief_sha256": {"const": digest(brief)},
            "creative_quality_passed": {"const": False},
            "criteria": {"type": "array", "minItems": 4, "maxItems": 4, "items": criteria}})})


def validate_full_review(value, script, brief):
    from jsonschema import Draft202012Validator
    Draft202012Validator(review_schema(script, brief)).validate(value)
    full = value["full_text_review"]
    if full["story_preserved"] != (not full["issues"]):
        raise ValueError("full review decision and issues disagree")
    ids = [i["id"] for i in full["issues"]]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate review issue")
    for issue in full["issues"]:
        exact_refs(issue["evidence_refs"], script)
    emotion = value["emotion_review"]
    for criterion in emotion["criteria"]:
        if criterion["evidence_refs"]:
            exact_refs(criterion["evidence_refs"], script)
    checkpoint = validate_emotion_review(emotion, script, brief)
    if checkpoint == "needs_complete_revision" and not full["issues"]:
        raise ValueError("emotion must-fix omitted from the full review")
    return {"full_review_complete": True, "needs_revision": bool(full["issues"]),
            "emotion_checkpoint": checkpoint, "creative_quality_passed": False}


def prepare():
    ROOT.mkdir(parents=True, exist_ok=True)
    if not (ROOT / "ANCHOR.json").exists():
        parent = control.read(PRIOR / "CALL_LEDGER.json")
        inherited = deepcopy(parent["starting_spend"])
        inherited["calls_started"] += len(parent["calls"])
        known = 0
        for c in parent["calls"]:
            receipt = control.read(PRIOR / c["receipt"])
            usage = receipt.get("response_metadata", {}).get("total_tokens")
            if receipt["status"] != "contract_valid" or type(usage) is not int:
                raise ValueError("latest parent outcome/usage unresolved")
            known += usage
        inherited["reported_tokens"] += known
        inherited["calls_with_known_usage"] += len(parent["calls"])
        inherited["parent_ledger_sha256"] = control.sha_file(PRIOR / "CALL_LEDGER.json")
        input_path = QA / "round_01/COMPLETE_REVISION_INPUT_NOT_SUBMITTED.json"
        input_value = control.read(input_path)
        files = [PRIOR / "CALL_LEDGER.json", input_path,
                 QA / "inputs/EMOTIONAL_BRIEF.json", QA / "inputs/FULL_R01_REFERENCE_PACK.json",
                 QA / "inputs/ORIGINAL_HUMAN_FEEDBACK.json"]
        files += list((PRIOR / "DELIVERABLE_s7_d1").glob("*.json"))
        anchor = {"inherited": inherited, "models": parent["model_configs"],
                  "parent_files": {str(p): control.sha_file(p) for p in files},
                  "revision_input_sha256": digest(input_value),
                  "scope": "one full MiniMax draft and one necessary complete DeepSeek review; no media/no automatic retries"}
        control.write(ROOT / "ANCHOR.json", anchor, True)
    return runtime().prepare()


def runtime():
    a = control.read(ROOT / "ANCHOR.json")
    def guard():
        for p, h in a["parent_files"].items():
            if control.sha_file(p) != h:
                raise RuntimeError("parent evidence or full input changed")
        for role, cfg in a["models"].items():
            live = wire_factory.legacy.role_config(role)
            if live.model != cfg["model"] or live.base_url != cfg["base_url"]:
                raise RuntimeError("unverified model switch")
    sources = [Path(__file__).resolve(), ROOT / "ANCHOR.json",
               ROOT_PROJECT / "src/content_factory/creative_story_emotion.py",
               ROOT_PROJECT / "scripts/prepare_creative_emotion_workflow.py",
               ROOT_PROJECT / "scripts/creative_resume_dispatch_v3.py",
               ROOT_PROJECT / "scripts/creative_json_document_transport_v1.py",
               ROOT_PROJECT / "scripts/run_creative_resume_v4.py"]
    return control.ContinuationRuntime(ROOT_PROJECT, ROOT, sources, a["inherited"], a["models"],
        inherited_guard=guard, quota_state=None, shared_lock=identity.SHARED_LOCK)


def summary():
    value = runtime().summary()
    inherited = control.read(ROOT / "ANCHOR.json")["inherited"]
    value["new_unknown_token_reservations"] = value["unknown_token_reservations"]
    value["inherited_unknown_token_reservations"] = inherited["unknown_token_reservations"]
    value["unknown_token_reservations"] += inherited["unknown_token_reservations"]
    value["unknown_outcome_ordinals"] = [70]
    value["unknown_usage_ordinals"] = [70, 160]
    return value


def records():
    rt = runtime()
    rt.check(control.read(rt.ledger))
    return [control.read(ROOT / c["receipt"]) for c in control.read(rt.ledger)["calls"]]


def draft():
    prepare()
    request_input = control.read(QA / "round_01/COMPLETE_REVISION_INPUT_NOT_SUBMITTED.json")
    actual = json.loads(request_input["messages"][1]["content"])
    previous = actual["previous_script"]
    request = wire_factory.wire("writer", request_input["messages"], script_schema(previous),
                                10000, request_input["bindings"])
    request["operator_version"] = VERSION
    control.write(ROOT / "request_previews/draft.json", request, True)
    result = runtime().dispatch("complete_emotion_draft_r1", request,
                               lambda value: validate_script(value, previous))
    if result["status"] == "contract_valid":
        value = result["document_output"]
        folder = ROOT / "COMPLETE_DRAFT_AWAITING_FULL_REVIEW"
        folder.mkdir(exist_ok=True)
        write_new(folder / "FULL_SCRIPT.json", value)
        lines = ["# " + value["title"], "", value["premise"], ""]
        for beat in value["beats"]:
            lines.extend(["## " + beat["id"] + " " + beat["event"], ""])
            for step in beat["steps"]:
                lines.extend([("**" + step["speaker"] + "**：" if step["kind"] == "dialogue" else "") + step["text"], ""])
        write_new(folder / "FULL_SCRIPT.md", "\n".join(lines) + "\n")
    return result


def review():
    prepare()
    drafts = [r for r in records() if r["label"] == "complete_emotion_draft_r1"]
    if len(drafts) != 1 or drafts[0]["status"] != "contract_valid":
        raise RuntimeError("complete accepted source draft required; never resend an unknown call")
    script = drafts[0]["document_output"]
    brief = control.read(QA / "inputs/EMOTIONAL_BRIEF.json")
    pack = control.read(QA / "inputs/FULL_R01_REFERENCE_PACK.json")
    original_feedback = control.read(QA / "inputs/ORIGINAL_HUMAN_FEEDBACK.json")
    context = {"script": script, "emotional_brief": brief, "reference_pack": pack,
               "original_user_feedback": original_feedback}
    prompt = ("审查当前完整新剧本全文，不代写正文。检查人物关系、事件因果、道具当前持有、"
              "刺激与反应、观众压力、角色选择、选择后果和结尾释放。不能只看字段完整。"
              "按pressure、choice、consequence、release顺序填写四项情绪证据。"
              "证据逐字引用script.beats.N.steps.N.text实际播放正文，不能引用事件摘要或背景设定。"
              "必修问题进入full_text_review.issues，可选建议进入suggestions；不要捏造硬规则。"
              "需要返修的情绪缺项也列入全文issues。所有满足仍等待用户内容确认，creative_quality_passed必须false。"
              "未经实际视频，不判断声音、口型、真实表演通过。只提交工具文档。")
    request = wire_factory.wire("director", [{"role": "system", "content": prompt},
        {"role": "user", "content": json.dumps(context, ensure_ascii=False)}],
        review_schema(script, brief), 6500, {"script_sha256": digest(script),
        "brief_sha256": digest(brief), "full_reference_pack_sha256": digest(pack),
        "source_draft_ordinal": drafts[0]["ordinal"]})
    request["operator_version"] = VERSION
    control.write(ROOT / "request_previews/full_review.json", request, True)
    result = runtime().dispatch("complete_emotion_full_review_r1", request,
                               lambda value: validate_full_review(value, script, brief))
    if result["status"] == "contract_valid":
        write_new(ROOT / "FULL_REVIEW.json", result["output"])
        write_new(ROOT / "STORY_CHECKPOINT.json", {"schema": "reviewed_complete_emotion_story/v1",
            "script_sha256": digest(script), "review_sha256": digest(result["output"]),
            "status": "needs_complete_revision" if result["output"]["full_text_review"]["issues"] else "awaiting_human_content_confirmation",
            "creative_quality_passed": False, "human_approval": None,
            "director_plan_complete": False, "media_calls": 0})
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("operation", choices=["prepare", "draft", "review", "status"])
    a = p.parse_args()
    result = prepare() if a.operation == "prepare" else draft() if a.operation == "draft" else review() if a.operation == "review" else summary()
    print(json.dumps({k: result[k] for k in ("status", "ordinal", "validation", "failure") if k in result}
                     if a.operation in {"draft", "review"} else result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

