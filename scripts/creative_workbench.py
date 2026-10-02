"""Shared media, delivery and quality commands; effects require explicit commands."""

from __future__ import annotations
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.content_factory.creative_stage_contracts import read, persist
from src.content_factory import creative_media_workbench as media
from src.content_factory import creative_quality_evidence as quality
from src.content_factory import creative_delivery as delivery


def parser():
    p = argparse.ArgumentParser()
    p.add_argument("run_dir", type=Path)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("inspect-media")
    c = sub.add_parser("register-candidate")
    c.add_argument("--receipt", required=True)
    c = sub.add_parser("review-media")
    for name in ("candidate-id", "decision", "statement", "video-sha256"):
        c.add_argument("--" + name, required=True)
    c.add_argument("--stage")
    c.add_argument("--stage-sha256")
    c.add_argument("--evidence", type=Path)
    c.add_argument("--time-range", nargs=2, type=float)
    c = sub.add_parser("assembly-chain")
    c.add_argument("--segments", nargs="+", required=True)
    c.add_argument("--reviews", nargs="+", required=True)
    c.add_argument("--output", required=True)
    c = sub.add_parser("prepare-segment")
    for name in ("compiled-plan", "segment-id", "output"):
        c.add_argument("--" + name, required=True)
    c.add_argument("--first-frame")
    c.add_argument("--first-frame-review")
    c.add_argument("--predecessor-review")
    c = sub.add_parser("assemble")
    c.add_argument("--chain", required=True)
    c.add_argument("--output-dir", required=True)
    c.add_argument("--execute", action="store_true", required=True)
    c = sub.add_parser("prepare-delivery")
    for name in ("review", "account-key", "account-uuid", "title"):
        c.add_argument("--" + name, required=True)
    c.add_argument("--description", default="")
    c.add_argument("--factual-story", action="store_true")
    c.add_argument("--assembly-chain", type=Path)
    for command in ("publish", "verify-publish", "collect-operations"):
        c = sub.add_parser(command)
        c.add_argument("--delivery", required=True)
        c.add_argument("--account-key", required=True)
        if command == "publish":
            c.add_argument("--execute", action="store_true", required=True)
    c = sub.add_parser("collect-quality-case")
    for name in ("stage", "category", "source-family", "independence-group"):
        c.add_argument("--" + name, required=True)
    c.add_argument("--split", choices=("development", "holdout"), default="development")
    c = sub.add_parser("annotate-quality")
    c.add_argument("--case", required=True)
    c.add_argument("--annotation", required=True)
    c = sub.add_parser("freeze-quality")
    c.add_argument("--cases", nargs="+", required=True)
    c.add_argument("--output", required=True)
    c = sub.add_parser("quality-report")
    c.add_argument("--dataset")
    c.add_argument("--runs")
    c.add_argument("--production")
    return p


def dispatch(a):
    if a.command == "inspect-media":
        result = media.inspect_media(a.run_dir)
    elif a.command == "register-candidate":
        result = media.register_candidate(a.run_dir, a.receipt)
    elif a.command == "review-media":
        result = media.media_feedback(
            a.run_dir,
            a.candidate_id,
            a.decision,
            a.statement,
            video_sha256=a.video_sha256,
            time_range=a.time_range,
            responsible_stage=a.stage,
            stage_output_sha256=a.stage_sha256,
            evidence=read(a.evidence) if a.evidence else None,
        )
    elif a.command == "assembly-chain":
        result = media.approved_chain(a.segments, a.reviews)
        persist(a.output, result, immutable=True)
    elif a.command == "prepare-segment":
        result = media.prepare_segment(
            a.run_dir,
            a.compiled_plan,
            a.segment_id,
            a.output,
            first_frame=a.first_frame,
            first_frame_review=a.first_frame_review,
            predecessor_review=a.predecessor_review,
        )
    elif a.command == "assemble":
        result = media.assemble_approved(a.chain, a.output_dir)
    elif a.command == "prepare-delivery":
        result = delivery.prepare_delivery(
            a.run_dir,
            a.review,
            account_key=a.account_key,
            account_uuid=a.account_uuid,
            title=a.title,
            description=a.description,
            fictional_story=not a.factual_story,
            assembly_chain=read(a.assembly_chain) if a.assembly_chain else None,
        )
    elif a.command in ("publish", "verify-publish", "collect-operations"):
        from src.platform_adapter.douyin_adapter import DouyinAdapter

        adapter = DouyinAdapter.for_account(a.account_key)
        try:
            operation = {
                "publish": delivery.publish_delivery,
                "verify-publish": delivery.verify_delivery,
                "collect-operations": delivery.collect_operations,
            }[a.command]
            result = operation(a.delivery, adapter)
        finally:
            adapter.session.stop()
    elif a.command == "collect-quality-case":
        result = quality.collect_case(
            a.run_dir,
            a.stage,
            category=a.category,
            source_family=a.source_family,
            independence_group=a.independence_group,
            split=a.split,
        )
    elif a.command == "annotate-quality":
        result = quality.annotate_case(a.case, read(a.annotation))
    elif a.command == "freeze-quality":
        result = quality.freeze_dataset(a.cases, a.output)
    else:
        result = quality.quality_report(
            a.run_dir,
            dataset_path=a.dataset,
            runs_path=a.runs,
            production_path=a.production,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main(argv=None):
    from datetime import datetime, timezone
    from uuid import uuid4

    a = parser().parse_args(argv)
    event = {
        "schema": "creative_workbench_command/v1",
        "command_id": uuid4().hex,
        "command": a.command,
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "arguments": {
            k: str(v) if isinstance(v, Path) else v for k, v in vars(a).items()
        },
    }
    path = a.run_dir / ".creative_debug/commands" / (event["command_id"] + ".json")
    persist(path, event)
    try:
        code = dispatch(a)
        event.update(status="completed", exit_code=code)
    except Exception as exc:
        event.update(
            status="failed", exit_code=2, error_type=type(exc).__name__, error=str(exc)
        )
        print(json.dumps(event, ensure_ascii=False, indent=2))
        code = 2
    persist(path, event)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
