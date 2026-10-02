"""Explicit v2 entry; legacy novel/reference_video commands keep their old meaning."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.content_factory.creative_workflow import CreativeWorkflow, MODEL_PROFILES, CREATE_REVIEW_PROFILE  # noqa: E402
from src.content_factory.creative_workflow_inputs import load_materials  # noqa: E402
from src.content_factory.creative_original_prompt import VERSION as EVENT_WRITER_VERSION  # noqa: E402

TASK_REGISTRY = ROOT / "data" / "creative_workflows" / "_logical_tasks"
DEFAULT_BUDGET = json.loads((ROOT / "config" / "creative_workflow_budget_v5.json").read_text(encoding="utf-8"))


def _uninitialized_launch_failure(run_dir: Path) -> dict | None:
    path = Path(run_dir)
    if not path.is_dir() or (path / "state.json").exists():
        return None
    files = [item for item in path.iterdir() if item.is_file()]
    if len(files) != 1 or files[0].name != "LAUNCH_ERROR.json":
        return None
    try:
        receipt = json.loads(files[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (receipt.get("schema") != "creative_launch_error/v1"
            or receipt.get("automatic_media_submit") is not False):
        return None
    return receipt


def validate_run_dir_before_claim(run_dir: Path) -> None:
    """Reject dirty new directories before they can acquire a logical-task claim."""
    path = Path(run_dir)
    if path.exists() and any(path.iterdir()) and not (path / "state.json").exists():
        raise RuntimeError("运行目录已有其他文件，不能登记逻辑任务")


def claim_logical_task(
    bundle, focus: str, run_dir: Path, *, registry: Path = TASK_REGISTRY,
    max_calls: int = DEFAULT_BUDGET["max_calls"],
    max_total_tokens: int = DEFAULT_BUDGET["max_total_tokens"],
    max_revisions: int = DEFAULT_BUDGET["max_revisions"],
    max_contract_repairs: int = DEFAULT_BUDGET["max_contract_repairs"],
    budget_policy_version: str = DEFAULT_BUDGET["policy_version"],
) -> str:
    """Atomically bind one source and intent to one run directory across CLI invocations."""
    if budget_policy_version not in (
        "v1_20260922", "v2_20260922", "v3_20260922", "v4_20260923", "v5_20261001",
    ) or max_contract_repairs < 0:
        raise ValueError("创作预算版本或契约修复上限无效")
    identity = {
        "source_driver": bundle.source_driver,
        "story_source_sha256": hashlib.sha256(bundle.source_text.encode("utf-8")).hexdigest(),
        "story_video_sha256": bundle.manifest["files"].get("story_video", {}).get("sha256"),
        "metadata_sha256": bundle.manifest["files"].get("metadata", {}).get("sha256"),
        "reference_text_sha256": [
            hashlib.sha256(item["text"].encode("utf-8")).hexdigest()
            for item in bundle.references
        ],
        "creative_focus": focus.strip(),
    }
    if bundle.metadata.get("creative_brief"):
        identity["creative_brief"] = bundle.metadata["creative_brief"]
    task_id = hashlib.sha256(json.dumps(
        identity, ensure_ascii=False, sort_keys=True,
    ).encode("utf-8")).hexdigest()
    registry.mkdir(parents=True, exist_ok=True)
    path = registry / f"{task_id}.json"
    target = str(run_dir.resolve())
    budget = {"max_calls": max_calls, "max_total_tokens": max_total_tokens,
              "max_revisions": max_revisions}
    if budget_policy_version != "v1_20260922":
        budget.update(policy_version=budget_policy_version,
                      max_contract_repairs=max_contract_repairs)
    receipt = {
        "schema": "creative_logical_task_claim/v1",
        "task_id": task_id,
        "identity": identity,
        "run_dir": target,
        "budget": budget,
        "claimed_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(receipt, handle, ensure_ascii=False, indent=2)
    except FileExistsError:
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("identity") == identity and existing.get("run_dir") == target:
            if existing.get("budget") != receipt["budget"]:
                raise RuntimeError("恢复逻辑任务不能改变调用、用量或返修预算") from None
        elif (existing.get("identity") == identity
              and existing.get("budget") == receipt["budget"]
              and _uninitialized_launch_failure(Path(str(existing.get("run_dir", "")))) is not None):
            failed = _uninitialized_launch_failure(Path(existing["run_dir"]))
            receipt["prior_uninitialized_claims"] = [
                *existing.get("prior_uninitialized_claims", []),
                {"run_dir": existing["run_dir"], "claimed_at": existing.get("claimed_at"),
                 "launch_error": failed},
            ]
            receipt["reclaimed_after_uninitialized_launch"] = True
            temporary = path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)
        else:
            raise RuntimeError(
                f"相同来源与创作焦点已有逻辑任务：{existing.get('run_dir')}；"
                "请恢复该目录，独立新故事需明确改变创作焦点"
            ) from None
    return task_id


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="新版双角色剧本工作流；不会自动生成视频")
    value.add_argument("--source-driver", required=True, choices=("novel", "reference_video", "original"))
    value.add_argument("--model-profile", choices=MODEL_PROFILES, help="新任务默认MiniMax创作、DeepSeek审查；旧任务沿用绑定配置")
    value.add_argument("--writer-prompt-version", choices=("legacy", "original_events_v3"), help="新原创任务默认事件版编剧并强制助手复核；恢复时沿用原版本")
    value.add_argument("--production-protocol", choices=("legacy", "governed_production_v1"), help="显式启用新规则治理/动作v2/精简审核；需配合evidence_review_v6，旧任务保持绑定")
    value.add_argument("--review-policy-version", choices=("legacy", "evidence_review_v1", "evidence_review_v2", "evidence_review_v3", "evidence_review_v4", "evidence_review_v5", "evidence_review_v6"), help="新原创任务默认矛盾对照审核v5和逐节拍分镜；旧任务沿用原版本")
    value.add_argument("--title", required=True)
    value.add_argument("--run-dir", required=True, type=Path)
    value.add_argument("--novel", type=Path)
    value.add_argument("--metadata", type=Path)
    value.add_argument("--video", type=Path)
    value.add_argument("--analysis", type=Path)
    value.add_argument("--analysis-end-heading", default="",
                       help="视频分析范围终点标题；只取该标题之前内容，并记录排除范围")
    value.add_argument("--reference", type=Path, action="append", default=[])
    value.add_argument("--brief", type=Path, help="每次创作要求；原创模式必需")
    value.add_argument("--asset-library", type=Path, default=ROOT / "data/visual_asset_library/reusable_assets.json")
    value.add_argument("--focus", default="", help="本次对照焦点，例如第10章停车场争执")
    value.add_argument("--max-calls", type=int, default=DEFAULT_BUDGET["max_calls"])
    value.add_argument("--max-total-tokens", type=int, default=DEFAULT_BUDGET["max_total_tokens"])
    value.add_argument("--max-revisions", type=int, default=DEFAULT_BUDGET["max_revisions"])
    value.add_argument("--max-contract-repairs", type=int, default=DEFAULT_BUDGET["max_contract_repairs"])
    value.add_argument("--budget-policy-version", choices=(
        "v1_20260922", "v2_20260922", "v3_20260922", "v4_20260923", "v5_20261001",
    ),
                       default=DEFAULT_BUDGET["policy_version"])
    value.add_argument("--retry-unconfirmed-transport", action="store_true",
                       help="保留旧参数兼容；未知派发结果仍须对账，此开关不再允许重派")
    debug = value.add_mutually_exclusive_group()
    debug.add_argument(
        "--stop-after-stage",
        help="调试模式：指定阶段产物完成并保存不可变快照后暂停",
    )
    debug.add_argument(
        "--next-stage",
        action="store_true",
        help="调试模式：跳过已缓存阶段，只运行下一个尚未完成的阶段后暂停",
    )
    return value


def _resolve_reference_paths(args):
    """Explicit inputs win; resume the exact saved references; defaults only for new original tasks."""
    if args.reference:
        return args.reference
    manifest_path = args.run_dir / "materials.json"
    if (args.run_dir / "state.json").exists():
        if not manifest_path.exists():
            return []
        files = json.loads(manifest_path.read_text(encoding="utf-8")).get("files", {})
        return [Path(row["path"]) for key, row in sorted(files.items()) if key.startswith("reference_")]
    if args.source_driver != "original":
        return []
    defaults = json.loads((ROOT / "config/creative_reference_defaults.json").read_text(encoding="utf-8"))
    return [ROOT / path for path in defaults["original"]]


def _inherit_saved_budget(args, launch_args):
    # Existing tasks retain their saved budgets when flags were not explicitly supplied.
    saved_path = args.run_dir / "state.json"
    if saved_path.exists():
        saved = json.loads(saved_path.read_text(encoding="utf-8"))
        for key in ("max_calls", "max_total_tokens", "max_revisions", "max_contract_repairs", "budget_policy_version"):
            flag = "--" + key.replace("_", "-")
            if key in saved and saved[key] is not None and not any(x == flag or x.startswith(flag + "=") for x in launch_args):
                setattr(args, key, saved[key])


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    launch_args = list(sys.argv[1:] if argv is None else argv)
    args = parser().parse_args(launch_args)
    _inherit_saved_budget(args, launch_args)
    bundle = load_materials(
        source_driver=args.source_driver,
        title=args.title,
        novel_path=args.novel,
        metadata_path=args.metadata,
        video_path=args.video,
        analysis_path=args.analysis,
        analysis_end_heading=args.analysis_end_heading,
        reference_paths=_resolve_reference_paths(args),
        brief_path=args.brief,
        asset_library_path=args.asset_library,
    )
    if bundle.metadata.get("creative_brief"):
        from src.content_factory.creative_brief import brief_focus
        generated_focus = brief_focus(bundle.metadata["creative_brief"])
        if generated_focus not in args.focus:
            args.focus = (args.focus + "\n" + generated_focus).strip()
    try:
        validate_run_dir_before_claim(args.run_dir)
        logical_task_id = claim_logical_task(
            bundle, args.focus, args.run_dir,
            max_calls=args.max_calls, max_total_tokens=args.max_total_tokens,
            max_revisions=args.max_revisions,
            max_contract_repairs=args.max_contract_repairs,
            budget_policy_version=args.budget_policy_version,
        )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        # The web launcher detaches this process; leave a visible failure receipt
        # only in a new empty run directory, never overwrite an existing task.
        if not args.run_dir.exists() or not any(args.run_dir.iterdir()):
            args.run_dir.mkdir(parents=True, exist_ok=True)
            (args.run_dir / "LAUNCH_ERROR.json").write_text(json.dumps({
                "schema": "creative_launch_error/v1", "status": "needs_attention",
                "error": str(exc), "automatic_media_submit": False,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": "needs_attention", "error": str(exc),
                          "automatic_media_submit": False}, ensure_ascii=False, indent=2))
        return 2
    try:
        state = CreativeWorkflow(
            args.run_dir,
            writer_prompt_version=args.writer_prompt_version or (
                None if (args.run_dir / "state.json").exists() else
                EVENT_WRITER_VERSION if args.source_driver == "original"
                and args.model_profile in (None, CREATE_REVIEW_PROFILE) else "legacy"
            ),
            production_protocol=args.production_protocol,
            review_policy_version=args.review_policy_version or (
                None if (args.run_dir / "state.json").exists() else
                "evidence_review_v5" if args.source_driver == "original"
                and args.model_profile in (None, CREATE_REVIEW_PROFILE)
                and args.writer_prompt_version != "legacy" else None
            ),
            logical_task_id=logical_task_id,
            model_profile=args.model_profile or (None if (args.run_dir / "state.json").exists() else CREATE_REVIEW_PROFILE),
            max_calls=args.max_calls,
            max_total_tokens=args.max_total_tokens,
            max_revisions=args.max_revisions,
            max_contract_repairs=args.max_contract_repairs,
            budget_policy_version=args.budget_policy_version,
            creative_focus=args.focus,
            retry_unconfirmed_transport=args.retry_unconfirmed_transport,
            stop_after_stage=args.stop_after_stage,
            max_new_stages=1 if args.next_stage else None,
        ).run(bundle)
        if state["status"] == "media_handoff_pending_capability" and args.brief:
            from src.content_factory.reusable_production import prepare_next_work
            prepare_next_work(args.run_dir, args.asset_library)
    except Exception as exc:
        state_path = args.run_dir / "state.json"
        saved = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
        print(json.dumps({
            "run_dir": str(args.run_dir.resolve()),
            "status": saved.get("status", "needs_attention"),
            "calls_started": saved.get("calls_started", 0),
            "revision_rounds": saved.get("revision_rounds", 0),
            "contract_repairs_used": saved.get("contract_repairs_used", 0),
            "format_repairs_used": saved.get("format_repairs_used", 0),
            "budget_policy_version": saved.get("budget_policy_version", args.budget_policy_version),
            "error": str(exc),
            "automatic_media_submit": False,
        }, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({
        "run_dir": str(args.run_dir.resolve()),
        "status": state["status"],
        "review_policy_version": state.get("review_policy_version", "legacy"),
        "pending_evidence_review": state.get("pending_evidence_review"),
        "calls_started": state["calls_started"],
        "revision_rounds": state["revision_rounds"],
        "contract_repairs_used": state.get("contract_repairs_used", 0),
        "format_repairs_used": state.get("format_repairs_used", 0),
        "budget_policy_version": state.get("budget_policy_version", args.budget_policy_version),
        "automatic_media_submit": False,
    }, ensure_ascii=False, indent=2))
    return 0 if state["status"] in {
        "media_handoff_pending_capability", "debug_breakpoint",
    } else 2


if __name__ == "__main__":
    raise SystemExit(main())
