"""Explicit trend text stages on the existing evidenced, non-retrying ledger."""
from __future__ import annotations
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_creative_resume_v4 as factory
from scripts import run_creative_resume_v10 as identity
from scripts import run_creative_emotion_revision_v6 as parent
from scripts.run_creative_emotion_revision_v1 import review_schema
from scripts.prepare_creative_emotion_workflow import write_new
from src.content_factory.creative_story_emotion import digest
from src.content_factory.creative_emotion_review_v2 import validate_complete_review_v2
from src.content_factory.creative_trend_bridge import (
    validate_packet, build_direction_preview, build_writer_preview,
    validate_direction, validate_complete_story,
)
VERSION = "evidenced_trend_text_trial/v1"
DEFAULT_ROOT = PROJECT / "data/production_revisions/legal_trend_text_trial_20261007/round_01"


def build_wire(packet, legal_facts, stage, *, now, direction=None, confirmation=None, script=None):
    """Reject source/confirmation faults before constructing a dispatchable request."""
    current = validate_packet(packet, now=now)
    if current["blockers"]:
        raise ValueError("current packet blocked: " + ",".join(current["blockers"]))
    if packet["inputs"]["source"]["account_profile"]["domain_strategy_id"] != "legal_services":
        raise ValueError("this trial requires the bound legal account strategy")
    if (legal_facts.get("schema") != "verified_legal_story_context/v1"
            or not legal_facts.get("sources") or not legal_facts.get("facts")
            or not legal_facts.get("creative_boundaries")):
        raise ValueError("verified legal source context required")
    if stage == "direction":
        preview = build_direction_preview(packet, now=now)
        role, cap = "writer", 6000
    elif stage == "draft":
        preview = build_writer_preview(packet, direction, confirmation, now=now)
        role, cap = "writer", 10000
    elif stage == "review":
        writer = build_writer_preview(packet, direction, confirmation, now=now)
        validate_complete_story(script, direction)
        context = json.loads(writer["messages"][1]["content"])
        context.update(script=deepcopy(script), source_text_paths=[
            f"script.beats.{i}.steps.{j}.text"
            for i, beat in enumerate(script["beats"]) for j, _ in enumerate(beat["steps"])])
        preview = {"messages": [{"role": "system", "content": (
            "全文审查当前完整剧本，不代写。核对确认简报、标签兑现、事件因果、"
            "压力、选择、可见后果和结尾释放；核对法律内容与所给权威依据及适用条件。"
            "没有依据的法律结论应列问题，不能把源视频标题当法律事实。"
            "issues仅列当前正文违反现有要求的真实必修问题，完整引用source_text_paths中的原文。"
            "机位、秒数、手部操作是后续导演和表演职责，尚未生成不能断言实际声画失败。"
            "story_preserved与issues分别判断；四项情绪判断必须有正文证据，情绪必修项同步列入issues。"
            "creative_quality_passed必须false；模型审查不能替代用户内容认可。")},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)}],
            "tool_definition": {"function": {"parameters": review_schema(script, direction["emotional_brief"])}}}
        role, cap = "director", 6500
    else:
        raise ValueError("unknown text stage")
    messages = deepcopy(preview["messages"])
    context = json.loads(messages[1]["content"])
    context["verified_legal_context"] = deepcopy(legal_facts)
    context["evidence_roles"] = {
        "fresh_batch": "metadata for audience questions and topic selection; source videos not watched",
        "reference_fulltext": "existing R01 expression analysis; mechanisms only, not source-video analysis",
        "legal_context": "separately checked primary sources; no automatic individual-case conclusion",
        "format": "use one allowed account format; case analysis may show fictional events and reactions",
    }
    messages[1]["content"] = json.dumps(context, ensure_ascii=False)
    bindings = {"packet_sha256": digest(packet), "legal_context_sha256": digest(legal_facts),
        "stage": stage, "source_context_sha256": digest(context),
        "reference_fulltext_sha256": digest(context["reference_fulltext"])}
    if direction is not None:
        bindings["direction_sha256"] = digest(direction)
    if confirmation is not None:
        bindings["confirmation_sha256"] = digest(confirmation)
    if script is not None:
        bindings["script_sha256"] = digest(script)
    wire = factory.wire(role, messages, preview["tool_definition"]["function"]["parameters"], cap, bindings)
    wire["operator_version"] = VERSION
    return wire


def render_direction(value, packet):
    b, e = value["creative_brief"], value["emotional_brief"]
    lines = ["# " + b["title"] + "：故事方向", "", "状态：模型完整提案，等待用户确认；不是完整剧本。", ""]
    for key, label in (("theme", "主题"), ("audience", "观众"), ("relationships", "人物关系"),
                       ("audience_emotion", "观众感受"), ("visual_style", "画风"),
                       ("turn", "转折"), ("ending", "结尾")):
        lines += [f"**{label}**：{b[key]}", ""]
    lines += ["**呈现形式**：" + value["account_fit"]["proposed_format"], "",
              "**账号匹配**：" + value["account_fit"]["reason"], "", "## 人物", ""]
    lines += [f"- {c['name']}：{c['goal']}" for c in value["characters"]]
    lines += ["", "## 情绪与因果", ""]
    for k, label in (("pressure", "压力"), ("choice", "选择"), ("consequence", "后果"), ("release", "释放")):
        lines += [f"**{label}**：{e[k]}", ""]
    tags = {t["tag_id"]: t for t in packet["tag_catalog"]}
    lines += ["## 标签如何进入故事", ""]
    for row in value["tag_choices"]:
        t = tags[row["tag_id"]]
        lines += [f"- {t['label']}（{t['kind']}，{t['supporting_unique_videos']}个来源视频）：{row['story_relevance']}"]
    lines += ["", "## 创作边界", ""]
    lines += ["- " + x for x in b["constraints"] + b["avoid"]]
    lines += ["", "方向来源与热度范围保留；未观看本批原片，不能认为已完成其音画分析。",
              "确认方向后，MiniMax生成完整新稿，DeepSeek全文复审，再核对正文；未授权本轮媒体或发布。", ""]
    return "\n".join(lines)


class Trial:
    def __init__(self, root=DEFAULT_ROOT):
        self.root = Path(root).resolve()
        self.root.relative_to(PROJECT)

    def prepare(self, packet_path=None, legal_path=None, authorization_path=None):
        self.root.mkdir(parents=True, exist_ok=True)
        anchor = self.root / "ANCHOR.json"
        if not anchor.exists():
            if any(p is None for p in (packet_path, legal_path, authorization_path)):
                raise ValueError("exact packet, legal context and actual authorization required")
            packet, facts, authority = [control.read(p) for p in (packet_path, legal_path, authorization_path)]
            if (authority.get("schema") != "legal_new_batch_text_trial_authorization/v1"
                    or authority.get("account_key") != packet["inputs"]["source"]["account_profile"]["account_key"]
                    or "test_trend_to_complete_story_text_flow" not in authority.get("scope", [])
                    or authority.get("automatic_model_retry") is not False
                    or authority.get("media_generation") is not False
                    or authority.get("publishing") is not False):
                raise ValueError("actual bound text-only task authorization required")
            build_wire(packet, facts, "direction", now=control.now())
            rt = parent.runtime()
            ledger = control.read(rt.ledger)
            rt.check(ledger)
            stats = parent.summary()
            if stats["new_unknown_token_reservations"]:
                raise ValueError("parent new-call usage unresolved")
            inherited = {"calls_started": stats["effective_calls_started"],
                "reported_tokens": stats["effective_reported_tokens"],
                "calls_with_known_usage": ledger["starting_spend"]["calls_with_known_usage"] + len(ledger["calls"]),
                "unknown_token_reservations": stats["unknown_token_reservations"],
                "pending_ordinals": [70, 160], "parent_ledger_sha256": control.sha_file(rt.ledger)}
            files = [Path(p).resolve() for p in (packet_path, legal_path, authorization_path)] + [rt.ledger]
            control.write(self.root / "SOURCE_PACKET.json", packet, True)
            control.write(self.root / "LEGAL_CONTEXT.json", facts, True)
            control.write(self.root / "CURRENT_TASK_AUTHORIZATION.json", authority, True)
            control.write(anchor, {"schema": VERSION, "inherited": inherited, "models": ledger["model_configs"],
                "parent_files": {str(p): control.sha_file(p) for p in files},
                "stages": ["direction", "draft_after_real_confirmation", "complete_review"],
                "automatic_retry": False, "media_calls_authorized": False}, True)
        return self.runtime().prepare()

    def runtime(self):
        a = control.read(self.root / "ANCHOR.json")
        def guard():
            parent.runtime().check(control.read(parent.runtime().ledger))
            for path, sha in a["parent_files"].items():
                if control.sha_file(path) != sha:
                    raise ValueError("frozen parent/input changed")
            for role, cfg in a["models"].items():
                live = factory.legacy.role_config(role)
                if live.model != cfg["model"] or live.base_url != cfg["base_url"]:
                    raise ValueError("unverified model switch")
        own = [Path(__file__).resolve(), self.root / "ANCHOR.json", self.root / "SOURCE_PACKET.json",
               self.root / "LEGAL_CONTEXT.json", self.root / "CURRENT_TASK_AUTHORIZATION.json"]
        own += [PROJECT / p for p in (
            "src/content_factory/creative_trend_bridge.py", "src/content_factory/creative_brief.py",
            "src/content_factory/creative_emotion_review_v2.py", "src/trend_intelligence/sample_gate.py",
            "scripts/creative_evidenced_role_clients_v1.py", "scripts/creative_call_evidence_v1.py")]
        sources = list(dict.fromkeys(own + parent.runtime().sources))
        return control.ContinuationRuntime(PROJECT, self.root, sources, a["inherited"], a["models"],
            inherited_guard=guard, quota_state=None, shared_lock=identity.SHARED_LOCK)

    def summary(self):
        value = self.runtime().summary()
        inherited = control.read(self.root / "ANCHOR.json")["inherited"]
        value["new_unknown_token_reservations"] = value["unknown_token_reservations"]
        value["unknown_token_reservations"] += inherited["unknown_token_reservations"]
        value.update(unknown_outcome_ordinals=[70], unknown_usage_ordinals=[70, 160],
                     creative_quality_passed=False)
        return value

    def accepted(self, stage):
        rt = self.runtime()
        ledger = control.read(rt.ledger)
        rt.check(ledger)
        rows = [r for r in ledger["calls"] if r["label"] == "trend_" + stage + "_r1"]
        if len(rows) != 1:
            raise ValueError("one source stage required: " + stage)
        receipt = rt.effective_receipt(rows[0])
        if receipt["status"] != "contract_valid":
            raise ValueError("latest stage rejected or unresolved: " + stage)
        return receipt.get("document_output", receipt.get("output"))

    def dispatch(self, stage, confirmation_path=None):
        self.prepare()
        packet, facts = [control.read(self.root / n) for n in ("SOURCE_PACKET.json", "LEGAL_CONTEXT.json")]
        direction = None if stage == "direction" else self.accepted("direction")
        confirmation = None if stage == "direction" else control.read(confirmation_path) if confirmation_path else None
        script = self.accepted("draft") if stage == "review" else None
        wire = build_wire(packet, facts, stage, now=control.now(), direction=direction,
                          confirmation=confirmation, script=script)
        control.write(self.root / "request_previews" / (stage + ".json"), wire, True)
        if stage != "direction":
            control.write(self.root / "HUMAN_DIRECTION_CONFIRMATION.json", confirmation, True)
        def validate(value):
            if stage == "direction":
                validate_direction(value, packet)
                return {"complete_direction_valid": True, "human_confirmation_pending": True,
                        "creative_quality_passed": False}
            if stage == "draft":
                return validate_complete_story(value, direction)
            return validate_complete_review_v2(value, script, direction["emotional_brief"])
        receipt = self.runtime().dispatch("trend_" + stage + "_r1", wire, validate)
        if receipt["status"] == "contract_valid":
            value = receipt.get("document_output", receipt.get("output"))
            control.write(self.root / (stage.upper() + ".json"), value, True)
            if stage == "direction":
                write_new(self.root / "STORY_DIRECTION_FOR_REVIEW.md", render_direction(value, packet))
            elif stage == "draft":
                lines = ["# " + value["title"], "", "完整模型正文，等待全文复审及用户内容确认。", "", value["premise"], ""]
                for beat in value["beats"]:
                    lines += ["## " + beat["id"] + " " + beat["event"], "", "触发：" + beat["trigger"], ""]
                    for step in beat["steps"]:
                        lines += [("**" + step["speaker"] + "**：" if step["kind"] == "dialogue" else "") + step["text"], ""]
                write_new(self.root / "FULL_SCRIPT.md", "\n".join(lines))
        control.write(self.root / "STATUS.json", {"latest_stage": stage, "receipt_status": receipt["status"],
            "ordinal": receipt["ordinal"], "spend": self.summary(), "creative_quality_passed": False,
            "director_complete": False, "performance_complete": False, "media_calls": 0})
        return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "direction", "draft", "review", "status"))
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--packet", type=Path)
    parser.add_argument("--legal-facts", type=Path)
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--confirmation", type=Path)
    args = parser.parse_args()
    trial = Trial(args.root)
    if args.stage == "prepare":
        result = trial.prepare(args.packet, args.legal_facts, args.authorization)
    elif args.stage == "status":
        result = trial.summary()
    else:
        r = trial.dispatch(args.stage, args.confirmation)
        result = {"ordinal": r["ordinal"], "status": r["status"], "failure": r.get("failure"),
                  "spend": trial.summary()}
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
