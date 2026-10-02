"""Compile a creative run into Seedance templates without a remote request."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.content_factory.creative_seedance_segments import build_seedance_segment_plan  # noqa: E402


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def compile_run(run_dir: Path, *, revised: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    folder = run_dir.resolve()
    prefix = "ASSISTANT_REVISED_" if revised else ""
    handoff_path = folder / f"{prefix}MEDIA_HANDOFF.json"
    script_path = folder / f"{prefix}SCREENPLAY.json"
    shots_path = folder / f"{prefix}STORYBOARD.json"
    capability_path = folder / f"{prefix}MEDIA_CAPABILITY_AUDIT.json"
    state_path = folder / "state.json"
    for path in (handoff_path, script_path, shots_path, capability_path, state_path):
        if not path.is_file():
            raise ValueError(f"缺少创作运行产物: {path.name}")
    handoff, script, shots, capability, state = (
        _read(handoff_path), _read(script_path), _read(shots_path),
        _read(capability_path), _read(state_path),
    )
    for key, value in (
        ("script_sha256", script), ("shots_sha256", shots),
        ("capability_audit_sha256", capability),
    ):
        if handoff.get(key) != _hash(value):
            raise ValueError(f"媒体交接的 {key} 与当前产物不一致")
    if handoff.get("automatic_submit") is not False:
        raise ValueError("媒体交接缺少付费提交锁")
    plan = build_seedance_segment_plan(script, shots, capability)
    assistant_required = state.get("assistant_review_required") is True
    assistant_outcome = state.get(
        "assistant_revision_review_outcome" if revised else "assistant_review_outcome"
    )
    text_gate = (
        "assistant_review_major_issues"
        if assistant_outcome == "major_issues"
        else "assistant_review_pending"
        if assistant_required and assistant_outcome != "passed"
        else "text_review_gate_satisfied"
    )
    receipt = {
        "schema": "creative_seedance_segment_compile_receipt/v1",
        "source_run": str(folder),
        "variant": "assistant_revised" if revised else "initial",
        "workflow_status": state.get("status"),
        "text_gate_status": text_gate,
        "state_sha256": _hash(state),
        "handoff_sha256": _hash(handoff),
        "script_sha256": _hash(script),
        "shots_sha256": _hash(shots),
        "capability_audit_sha256": _hash(capability),
        "segment_plan_sha256": _hash(plan),
        "remote_request_sent": False,
        "automatic_submit": False,
    }
    return plan, receipt


def _write_new_or_same(path: Path, value: dict[str, Any]) -> None:
    raw = json.dumps(value, ensure_ascii=False, indent=2)
    if path.exists():
        if _read(path) != value:
            raise ValueError(f"输出已存在且绑定不同内容: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="离线编译创作分镜到 Seedance 请求模板；绝不提交远程任务")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--revised", action="store_true")
    args = parser.parse_args(argv)
    plan, receipt = compile_run(args.run_dir, revised=args.revised)
    output = args.output.resolve()
    receipt_path = output.with_name(output.stem + ".receipt.json")
    _write_new_or_same(output, plan)
    _write_new_or_same(receipt_path, receipt)
    from src.content_factory.creative_media_workbench import register_preview
    prefix = "ASSISTANT_REVISED_" if args.revised else ""
    register_preview(args.run_dir, output, source_paths={key: args.run_dir / (prefix + name)
        for key,name in (("script","SCREENPLAY.json"),("storyboard","STORYBOARD.json"),
                         ("capability","MEDIA_CAPABILITY_AUDIT.json"),("handoff","MEDIA_HANDOFF.json"))},
        text_gate=receipt["text_gate_status"])
    print(json.dumps({
        "segment_plan": str(output),
        "receipt": str(receipt_path),
        "mapping_status": plan["mapping_status"],
        "blocked_shots": plan["blocked_shots"],
        "text_gate_status": receipt["text_gate_status"],
        "automatic_submit": False,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
