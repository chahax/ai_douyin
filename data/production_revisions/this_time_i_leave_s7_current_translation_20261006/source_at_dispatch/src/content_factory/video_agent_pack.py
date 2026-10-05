"""Compile a video-control plan into isolated Hermes and Claude Code task files."""

from __future__ import annotations

import json
import re
from pathlib import Path


MANIFEST_TEMPLATE = "video_agent_pack/v1"
REPORT_TEMPLATE = "video_agent_pack_report/v1"
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")

TOOL_CONTRACTS: dict[str, dict[str, object]] = {
    "deterministic_2d_compositor": {
        "generation_manifest": "deterministic_motion/v1",
        "executor": r"scripts\deterministic_motion.py",
        "postprocess_manifest": None,
        "qa_output_flag": "--qa-dir",
    },
    "deterministic_camera": {
        "generation_manifest": "deterministic_camera/v1",
        "executor": r"scripts\deterministic_camera.py",
        "postprocess_manifest": "video_review_packet/v1",
        "qa_output_flag": "--qa-dir",
    },
    "liveportrait": {
        "generation_manifest": "ComfyUI LivePortrait workflow",
        "executor": "ComfyUI API",
        "postprocess_manifest": "video_audio_mux/v1",
    },
    "sadtalker": {
        "generation_manifest": "SadTalker command contract",
        "executor": r"D:\IT\SadTalker\inference.py",
        "postprocess_manifest": "video_review_packet/v1",
    },
    "sonic": {
        "generation_manifest": "ComfyUI Sonic workflow",
        "executor": "ComfyUI API",
        "postprocess_manifest": "video_review_packet/v1",
    },
    "framepack": {
        "generation_manifest": "FramePack run contract",
        "executor": r"D:\IT\FramePack\demo_gradio.py",
        "postprocess_manifest": "video_recipe/v1",
    },
    "ltx_i2v": {
        "generation_manifest": "ComfyUI LTX I2V workflow",
        "executor": "ComfyUI API",
        "postprocess_manifest": "video_recipe/v1",
    },
    "wan_animate_move": {
        "generation_manifest": "ComfyUI Wan Animate Move workflow",
        "executor": "ComfyUI API",
        "postprocess_manifest": "video_recipe/v1",
    },
    "wan_animate_replacement": {
        "generation_manifest": "ComfyUI Wan Animate Replacement workflow",
        "executor": "ComfyUI API",
        "postprocess_manifest": "video_recipe/v1",
    },
}


def compile_video_agent_pack(manifest_path: str | Path) -> dict[str, object]:
    path = Path(manifest_path).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("template") != MANIFEST_TEMPLATE:
        raise ValueError(f"template must be {MANIFEST_TEMPLATE}")

    pack_id = _safe_id(data, "id")
    namespace = _safe_id(data, "namespace")
    plan_path = _required_path(path, data, "plan_report")
    comfyui_root = _required_path(path, data, "comfyui_root")
    orchestrator_root = _required_path(path, data, "orchestrator_root")
    output_dir = _required_path(path, data, "output_dir")
    _require_within(output_dir, orchestrator_root, "output_dir", "orchestrator_root")

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("template") != "video_control_plan_report/v1":
        raise ValueError("plan_report must be video_control_plan_report/v1")
    routes = plan.get("routes")
    if not isinstance(routes, list) or not routes:
        raise ValueError("plan_report routes must be a non-empty array")

    output_dir.mkdir(parents=True, exist_ok=True)
    task_reports: list[dict[str, object]] = []
    for raw_route in routes:
        if not isinstance(raw_route, dict):
            raise ValueError("each plan route must be an object")
        shot_id = _safe_id(raw_route, "id")
        shot_dir = output_dir / shot_id
        shot_dir.mkdir(parents=True, exist_ok=True)
        contract = _shot_contract(
            raw_route,
            namespace=namespace,
            comfyui_root=comfyui_root,
            orchestrator_root=orchestrator_root,
        )
        contract_path = shot_dir / "contract.json"
        hermes_path = shot_dir / "hermes_task.md"
        claude_path = shot_dir / "claude_code_task.md"
        contract_path.write_text(
            json.dumps(contract, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        hermes_path.write_text(_hermes_task(contract), encoding="utf-8")
        claude_path.write_text(_claude_task(contract), encoding="utf-8")
        task_reports.append(
            {
                "shot_id": shot_id,
                "status": (
                    "ready" if contract["generation_allowed"] else "blocked"
                ),
                "contract": str(contract_path),
                "hermes_task": str(hermes_path),
                "claude_code_task": str(claude_path),
                "asset_input_dir": contract["paths"]["asset_input_dir"],
                "raw_output_dir": contract["paths"]["raw_output_dir"],
                "qa_output_dir": contract["paths"]["qa_output_dir"],
            }
        )

    blocked = [
        item["shot_id"]
        for item in task_reports
        if item["status"] == "blocked"
    ]
    report = {
        "template": REPORT_TEMPLATE,
        "id": pack_id,
        "namespace": namespace,
        "plan_report": str(plan_path),
        "output_dir": str(output_dir),
        "roots": {
            "comfyui": str(comfyui_root),
            "orchestrator": str(orchestrator_root),
        },
        "summary": {
            "shot_count": len(task_reports),
            "ready_count": len(task_reports) - len(blocked),
            "blocked_count": len(blocked),
            "blocked_shots": blocked,
        },
        "tasks": task_reports,
    }
    report_path = output_dir / "pack.report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_index(output_dir / "README.md", report)
    report["report_path"] = str(report_path)
    return report


def _shot_contract(
    route: dict[str, object],
    *,
    namespace: str,
    comfyui_root: Path,
    orchestrator_root: Path,
) -> dict[str, object]:
    shot_id = _safe_id(route, "id")
    resolved_tool = route.get("resolved_tool")
    primary_tool = route.get("primary_tool")
    selected_tool = resolved_tool or primary_tool
    if selected_tool is not None and not isinstance(selected_tool, str):
        raise ValueError(f"route {shot_id} tool must be a string or null")
    tool_contract = TOOL_CONTRACTS.get(str(selected_tool), {})
    asset_input = comfyui_root / "input" / namespace / shot_id
    raw_output = comfyui_root / "output" / namespace / shot_id
    qa_output = orchestrator_root / "data" / "qa" / namespace / shot_id
    _require_within(asset_input, comfyui_root, "asset_input_dir", "comfyui_root")
    _require_within(raw_output, comfyui_root, "raw_output_dir", "comfyui_root")
    _require_within(
        qa_output,
        orchestrator_root,
        "qa_output_dir",
        "orchestrator_root",
    )
    return {
        "template": "video_agent_shot_contract/v1",
        "shot_id": shot_id,
        "generation_allowed": route.get("generation_allowed") is True,
        "route_status": route.get("route_status"),
        "control_mode": route.get("control_mode"),
        "primary_tool": primary_tool,
        "resolved_tool": resolved_tool,
        "risk": route.get("risk"),
        "intent": route.get("intent"),
        "required_assets": route.get("required_assets", []),
        "postprocess": route.get("postprocess", []),
        "warnings": route.get("warnings", []),
        "acceptance_checks": route.get("acceptance_checks", []),
        "readiness": route.get("readiness", {}),
        "execution": {
            "generation_manifest": tool_contract.get("generation_manifest"),
            "executor": tool_contract.get("executor"),
            "postprocess_manifest": tool_contract.get("postprocess_manifest"),
            "qa_output_flag": tool_contract.get("qa_output_flag"),
            "control_manifest": "video_control/v1",
            "review_manifest": "video_review_packet/v1",
            "recovery_manifest": "video_recovery/v1",
        },
        "paths": {
            "asset_input_dir": str(asset_input),
            "raw_output_dir": str(raw_output),
            "qa_output_dir": str(qa_output),
        },
        "roots": {
            "comfyui": str(comfyui_root),
            "orchestrator": str(orchestrator_root),
        },
        "owners": {
            "assets": "Hermes",
            "execution": "Claude Code",
            "approval": "Codex/manual reviewer",
        },
        "continuation_rule": (
            "Only composition_eligible=true may continue to story assembly."
        ),
    }


def _hermes_task(contract: dict[str, object]) -> str:
    paths = contract["paths"]
    roots = contract["roots"]
    assert isinstance(paths, dict)
    assert isinstance(roots, dict)
    required = contract.get("required_assets", [])
    warnings = contract.get("warnings", [])
    allowed = contract.get("generation_allowed") is True
    state = "READY" if allowed else "STOP / BLOCKED"
    return "\n".join(
        [
            f"# Hermes 素材任务：{contract['shot_id']}",
            "",
            f"状态：**{state}**",
            "",
            "## 唯一职责",
            "",
            f"- 只准备这些素材：`{json.dumps(required, ensure_ascii=False)}`。",
            f"- 所有素材只写入：`{paths['asset_input_dir']}`。",
            "- 不运行 LTX、Wan、FramePack、LivePortrait、SadTalker 或 Sonic。",
            f"- 不修改 `{roots['orchestrator']}` 中的源码、报告或清单。",
            "- 不得自行宣称镜头通过，只返回绝对路径、模型、seed 和实际提示词。",
            "",
            "## 警告",
            "",
            *(
                [f"- {warning}" for warning in warnings]
                if isinstance(warnings, list) and warnings
                else ["- 无额外警告。"]
            ),
            "",
            "若状态为 STOP / BLOCKED，停止生成并只返回缺失项。",
            "",
        ]
    )


def _claude_task(contract: dict[str, object]) -> str:
    paths = contract["paths"]
    roots = contract["roots"]
    execution = contract["execution"]
    assert isinstance(paths, dict)
    assert isinstance(roots, dict)
    assert isinstance(execution, dict)
    allowed = contract.get("generation_allowed") is True
    state = "READY" if allowed else "STOP / BLOCKED"
    readiness = contract.get("readiness", {})
    missing = readiness.get("missing", []) if isinstance(readiness, dict) else []
    return "\n".join(
        [
            f"# Claude Code 执行任务：{contract['shot_id']}",
            "",
            f"状态：**{state}**",
            "",
            "## 固定路线",
            "",
            f"- 工具：`{contract.get('resolved_tool') or contract.get('primary_tool')}`",
            f"- 控制模式：`{contract.get('control_mode')}`",
            f"- 生成清单：`{execution.get('generation_manifest')}`",
            f"- 执行入口：`{execution.get('executor')}`",
            *(
                [
                    f"- QA 参数：`{execution.get('qa_output_flag')} "
                    f"{paths['qa_output_dir']}`"
                ]
                if execution.get("qa_output_flag")
                else []
            ),
            f"- 素材目录：`{paths['asset_input_dir']}`",
            f"- 原始视频和工作流只写入：`{paths['raw_output_dir']}`",
            f"- 门禁、抽帧和恢复报告只写入：`{paths['qa_output_dir']}`",
            "",
            "## 强制顺序",
            "",
            "1. 检查素材和本机库存，不允许静默换模型。",
            "2. 只生成一个候选。",
            "3. 生成 `video_control/v1` 并运行机器门禁。",
            "4. 生成 `video_review_packet/v1`，等待视觉验收。",
            "5. 失败时生成 `video_recovery/v1`，下一轮只执行 `single_change`。",
            "6. 只有 `composition_eligible=true` 才能交给故事合成。",
            "",
            "## 禁止事项",
            "",
            f"- 不修改 `{roots['orchestrator']}` 源码。",
            f"- 不把 ComfyUI 原始输出写入 `{roots['orchestrator']}`。",
            f"- 不把 QA、门禁或任务清单写入 `{roots['comfyui']}`。",
            "- 不同时修改 seed、提示词、CFG、采样器和工作流参数。",
            f"- 缺失项：`{json.dumps(missing, ensure_ascii=False)}`。",
            "",
            "若状态为 STOP / BLOCKED，停止 ComfyUI 队列，不生成候选。",
            "",
        ]
    )


def _write_index(path: Path, report: dict[str, object]) -> None:
    summary = report["summary"]
    assert isinstance(summary, dict)
    lines = [
        f"# 视频代理任务包：{report['id']}",
        "",
        f"- namespace：`{report['namespace']}`",
        f"- ready：`{summary['ready_count']}`",
        f"- blocked：`{summary['blocked_count']}`",
        "",
        "| 镜头 | 状态 | Hermes | Claude Code |",
        "|---|---|---|---|",
    ]
    tasks = report["tasks"]
    assert isinstance(tasks, list)
    for task in tasks:
        assert isinstance(task, dict)
        shot_id = task["shot_id"]
        lines.append(
            f"| `{shot_id}` | `{task['status']}` | "
            f"`{shot_id}/hermes_task.md` | `{shot_id}/claude_code_task.md` |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _safe_id(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise ValueError(f"{key} must use letters, numbers, underscores, or hyphens")
    return value


def _required_path(
    manifest_path: Path,
    data: dict[str, object],
    key: str,
) -> Path:
    raw = data.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{key} must be a non-empty string")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = manifest_path.parent / candidate
    return candidate.resolve()


def _require_within(
    path: Path,
    root: Path,
    path_name: str,
    root_name: str,
) -> None:
    if not path.is_relative_to(root):
        raise ValueError(f"{path_name} must stay within {root_name}")
