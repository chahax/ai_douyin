"""Render V6.2 LTX units in two stages to avoid per-shot model thrashing.

All expensive LTX motion clips are generated first while the model is warm.
Duration alignment and RIFE interpolation run only after every raw clip exists.
The resulting progress contract is identical to the regular LTX runner.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import uuid
from pathlib import Path

from run_task1_story_v62_ltx_batch import (
    DEFAULT_EVIDENCE,
    DEFAULT_OUTPUT,
    DEFAULT_P0_ROOT,
    DEFAULT_PLAN,
    _character_bindings,
    _probe,
    _sha256,
    _utc_now,
    _write_atomic,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--p0-root", type=Path, default=DEFAULT_P0_ROOT)
    parser.add_argument("--base-url", default="http://127.0.0.1:8190")
    parser.add_argument("--scene-id", action="append", default=[])
    args = parser.parse_args()

    p0_root = args.p0_root.resolve()
    sys.path.insert(0, str(p0_root))
    from src.novel_promotion.comfy_ltx_video_provider import (  # noqa: PLC0415
        DEFAULT_LTX_BASE_SHIFT,
        DEFAULT_LTX_CFG,
        DEFAULT_LTX_CKPT_NAME,
        DEFAULT_LTX_MAX_SHIFT,
        DEFAULT_LTX_SAMPLER,
        DEFAULT_LTX_SCHEDULER,
        DEFAULT_LTX_STEPS,
        DEFAULT_LTX_STRENGTH,
        DEFAULT_LTX_TEXT_ENCODER,
        DEFAULT_LTX_UNET,
        DEFAULT_LTX_VAE,
        ComfyLTXVideoSceneProvider,
        _build_ltx_i2v_workflow,
        _comfy_request_json,
        _comfy_wait_history,
        _duration_align,
        _select_ltx_frame_count,
    )
    from src.novel_promotion.scene_provider import ScenePlan  # noqa: PLC0415

    plan_path = args.plan.resolve()
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "fanqie_v62_microshot_workflow/v2":
        raise ValueError("unexpected V6.2 workflow schema")
    branch = payload["variants"]["original_recomposed"]
    if branch.get("publish_allowed") is not False or branch.get("reuse_sources"):
        raise ValueError("original branch publication/reuse guard failed")
    all_units = list(branch["new_framepack_units"])
    all_positions = {
        str(unit["scene_id"]): index
        for index, unit in enumerate(all_units, start=1)
    }
    units = all_units
    if args.scene_id:
        requested = set(args.scene_id)
        unknown = requested - set(all_positions)
        if unknown:
            raise ValueError(f"unknown scene ids: {', '.join(sorted(unknown))}")
        units = [unit for unit in all_units if unit["scene_id"] in requested]

    source_plan_path = Path(str(payload["source_story_plan"]))
    if _sha256(source_plan_path) != payload["source_story_plan_sha256"]:
        raise ValueError("source story plan changed")
    source_plan = json.loads(source_plan_path.read_text(encoding="utf-8"))
    bindings = _character_bindings(source_plan)

    output_dir = args.output_root.resolve() / "original_recomposed"
    raw_dir = output_dir / "raw_ltx"
    aligned_dir = output_dir / "aligned25"
    audit_dir = output_dir / "twostage_audit"
    for directory in (output_dir, raw_dir, aligned_dir, audit_dir):
        directory.mkdir(parents=True, exist_ok=True)
    pipeline_path = output_dir / "twostage_progress.json"
    final_progress_path = output_dir / "progress.json"
    plan_sha = _sha256(plan_path)

    pipeline: dict[str, object] = {
        "schema_version": "fanqie_v62_ltx_twostage_progress/v1",
        "variant": "original_recomposed",
        "plan_path": str(plan_path),
        "plan_sha256": plan_sha,
        "started_at": _utc_now(),
        "updated_at": _utc_now(),
        "stage_order": ["raw_ltx_all", "align_all", "rife_all"],
        "publish_allowed": False,
        "fanqie_backfill_allowed": False,
        "shots": [],
    }
    if pipeline_path.is_file():
        prior_pipeline = json.loads(pipeline_path.read_text(encoding="utf-8"))
        if (
            prior_pipeline.get("schema_version") == pipeline["schema_version"]
            and prior_pipeline.get("plan_sha256") == plan_sha
        ):
            pipeline = prior_pipeline
    states = {
        str(row["scene_id"]): row
        for row in pipeline.get("shots", [])
        if isinstance(row, dict) and row.get("scene_id")
    }

    existing_final: dict[str, dict[str, object]] = {}
    if final_progress_path.is_file():
        prior_final = json.loads(final_progress_path.read_text(encoding="utf-8"))
        if prior_final.get("plan_sha256") == plan_sha:
            existing_final = {
                str(row["scene_id"]): row
                for row in prior_final.get("shots", [])
                if isinstance(row, dict)
                and row.get("status") == "rendered"
                and Path(str(row.get("output_path", ""))).is_file()
                and row.get("output_sha256")
                == _sha256(Path(str(row["output_path"])))
            }

    provider = ComfyLTXVideoSceneProvider(
        base_url=args.base_url,
        comfy_input=r"D:\IT\AI_vido\ComfyUI\input",
        comfy_output=r"D:\IT\AI_vido\ComfyUI\output",
        evidence_root=str(args.evidence_root.resolve()),
        timeout_seconds=7200,
        musetalk_available=False,
    )
    plans = []
    for unit in units:
        scene_id = str(unit["scene_id"])
        identity = bindings.get(scene_id, {})
        plans.append(
            ScenePlan(
                scene_id=scene_id,
                visual_prompt=str(unit["prompt"]),
                estimated_duration_s=float(unit["target_duration_seconds"]),
                metadata={
                    **identity,
                    "seed": int(unit["seed"]),
                    "shot_anchor_image": str(Path(str(unit["anchor_path"])).resolve()),
                    "shot_anchor_sha256": str(unit["anchor_sha256"]),
                    "spoken_closeup": False,
                    "dialogue_audio_path": "",
                    "publish_allowed": False,
                },
            )
        )
    preflight = provider.preflight(plans, require_dialogue_audio=False)
    if not preflight.ok:
        raise RuntimeError(f"LTX preflight failed: {preflight.error}")

    comfy_input = Path(r"D:\IT\AI_vido\ComfyUI\input")
    comfy_output = Path(r"D:\IT\AI_vido\ComfyUI\output")
    raw_comfy_dir = comfy_output / "fanqie_v62_ltx_raw"

    # Stage 1: all LTX prompts while the large model remains warm.
    for unit, scene_plan in zip(units, plans):
        scene_id = scene_plan.scene_id
        position = all_positions[scene_id]
        if scene_id in existing_final:
            states[scene_id] = {
                "scene_id": scene_id,
                "position": position,
                "stage": "final",
                "output_path": existing_final[scene_id]["output_path"],
                "output_sha256": existing_final[scene_id]["output_sha256"],
            }
            continue
        raw_path = raw_dir / f"{scene_id}.mp4"
        state = states.get(scene_id, {})
        recovery_workflow = audit_dir / f"{scene_id}.ltx.api.json"
        if (
            not state.get("raw_sha256")
            and raw_path.is_file()
            and recovery_workflow.is_file()
            and raw_path.stat().st_mtime >= recovery_workflow.stat().st_mtime
        ):
            state = {
                "scene_id": scene_id,
                "position": position,
                "stage": "raw_ltx",
                "raw_path": str(raw_path),
                "raw_sha256": _sha256(raw_path),
                "raw_probe": _probe(raw_path),
                "recovered_after_progress_write_failure": True,
                "workflow_path": str(recovery_workflow),
                "workflow_sha256": _sha256(recovery_workflow),
            }
            states[scene_id] = state
            print(
                json.dumps({"event": "raw_recovered", "scene_id": scene_id}),
                flush=True,
            )
        if (
            state.get("raw_sha256")
            and raw_path.is_file()
            and state["raw_sha256"] == _sha256(raw_path)
        ):
            print(json.dumps({"event": "raw_cache_hit", "scene_id": scene_id}), flush=True)
            continue

        anchor = Path(str(unit["anchor_path"])).resolve()
        if not anchor.is_file() or _sha256(anchor) != unit["anchor_sha256"]:
            raise ValueError(f"anchor missing or changed: {scene_id}")
        staged_name = f"fanqie_v62_ltx_raw_input/{scene_id}.png"
        staged = comfy_input / staged_name
        staged.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(anchor, staged)
        frame_count = _select_ltx_frame_count(
            target_duration_s=scene_plan.estimated_duration_s,
            fps=25,
            minimum_frame_count=65,
        )
        workflow = _build_ltx_i2v_workflow(
            image_name=staged_name,
            motion_prompt=scene_plan.visual_prompt,
            seed=int(unit["seed"]),
            width=704,
            height=1248,
            frame_count=frame_count,
            unet_name=DEFAULT_LTX_UNET,
            vae_name=DEFAULT_LTX_VAE,
            text_encoder=DEFAULT_LTX_TEXT_ENCODER,
            ckpt_name=DEFAULT_LTX_CKPT_NAME,
            max_shift=DEFAULT_LTX_MAX_SHIFT,
            base_shift=DEFAULT_LTX_BASE_SHIFT,
            steps=DEFAULT_LTX_STEPS,
            cfg=DEFAULT_LTX_CFG,
            strength=DEFAULT_LTX_STRENGTH,
            sampler=DEFAULT_LTX_SAMPLER,
            scheduler=DEFAULT_LTX_SCHEDULER,
            fps=25,
            filename_prefix=f"fanqie_v62_ltx_raw/{scene_id}",
        )
        workflow_path = audit_dir / f"{scene_id}.ltx.api.json"
        workflow_path.write_text(
            json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        before = (
            {path.resolve() for path in raw_comfy_dir.glob(f"{scene_id}*.mp4")}
            if raw_comfy_dir.exists()
            else set()
        )
        print(
            json.dumps(
                {"event": "raw_started", "scene_id": scene_id, "position": position, "total": len(units)}
            ),
            flush=True,
        )
        response = _comfy_request_json(
            f"{args.base_url}/prompt",
            {"prompt": workflow, "client_id": str(uuid.uuid4())},
            timeout=30,
        )
        prompt_id = str(response.get("prompt_id") or "")
        if not prompt_id:
            raise RuntimeError(f"ComfyUI returned no prompt_id for {scene_id}")
        history = _comfy_wait_history(args.base_url, prompt_id, 7200)
        candidates = (
            [
                path
                for path in raw_comfy_dir.glob(f"{scene_id}*.mp4")
                if path.resolve() not in before
            ]
            if raw_comfy_dir.exists()
            else []
        )
        if not candidates:
            for output in history.get("outputs", {}).values():
                if not isinstance(output, dict):
                    continue
                for item in output.get("gifs", []) + output.get("videos", []):
                    filename = item.get("filename", "") if isinstance(item, dict) else str(item)
                    candidate = raw_comfy_dir / Path(filename).name
                    if candidate.is_file() and candidate.resolve() not in before:
                        candidates.append(candidate)
        if not candidates:
            raise RuntimeError(f"ComfyUI did not save a new raw clip for {scene_id}")
        generated = max(candidates, key=lambda path: path.stat().st_mtime)
        pending = raw_path.with_suffix(".pending.mp4")
        shutil.copy2(generated, pending)
        pending.replace(raw_path)
        states[scene_id] = {
            "scene_id": scene_id,
            "position": position,
            "stage": "raw_ltx",
            "prompt_id": prompt_id,
            "frame_count": frame_count,
            "raw_path": str(raw_path),
            "raw_sha256": _sha256(raw_path),
            "raw_probe": _probe(raw_path),
        }
        pipeline["shots"] = [
            states[key]
            for key in sorted(states, key=lambda item: all_positions.get(item, 999))
        ]
        pipeline["updated_at"] = _utc_now()
        _write_atomic(pipeline_path, pipeline)
        print(json.dumps({"event": "raw_finished", "scene_id": scene_id}), flush=True)

    # Stage 2: duration-align every raw clip before switching models to RIFE.
    for unit, scene_plan in zip(units, plans):
        scene_id = scene_plan.scene_id
        position = all_positions[scene_id]
        if scene_id in existing_final:
            continue
        raw_path = raw_dir / f"{scene_id}.mp4"
        state = states[scene_id]
        if not raw_path.is_file() or state.get("raw_sha256") != _sha256(raw_path):
            raise ValueError(f"raw clip missing or changed: {scene_id}")
        aligned = aligned_dir / f"{scene_id}.mp4"
        if not (
            state.get("aligned_sha256")
            and aligned.is_file()
            and state["aligned_sha256"] == _sha256(aligned)
        ):
            _duration_align(
                source=raw_path,
                target_duration_s=scene_plan.estimated_duration_s,
                output=aligned,
                width=704,
                height=1248,
                fps=25,
            )
            state.update(
                {
                    "stage": "aligned25",
                    "aligned_path": str(aligned),
                    "aligned_sha256": _sha256(aligned),
                    "aligned_probe": _probe(aligned),
                }
            )
            pipeline["shots"] = list(states.values())
            pipeline["updated_at"] = _utc_now()
            _write_atomic(pipeline_path, pipeline)

    # Stage 3: the lightweight RIFE model can now run for every aligned clip.
    final_rows = []
    for unit, scene_plan in zip(units, plans):
        scene_id = scene_plan.scene_id
        position = all_positions[scene_id]
        destination = output_dir / f"{scene_id}.mp4"
        if scene_id in existing_final:
            final_rows.append(existing_final[scene_id])
            continue
        aligned = aligned_dir / f"{scene_id}.mp4"
        state = states[scene_id]
        shot_dir = audit_dir / scene_id
        shot_dir.mkdir(parents=True, exist_ok=True)
        provider._run_rife(source_path=aligned, output_dir=shot_dir, shot_id=scene_id)
        rife = shot_dir / f"{scene_id}_rife50.mp4"
        pending = destination.with_suffix(".pending.mp4")
        shutil.copy2(rife, pending)
        pending.replace(destination)
        row = {
            "scene_id": scene_id,
            "position": position,
            "started_at": state.get("started_at", pipeline["started_at"]),
            "status": "rendered",
            "completed_at": _utc_now(),
            "output_path": str(destination),
            "output_sha256": _sha256(destination),
            "probe": _probe(destination),
            "provider_metadata": {
                "renderer": "local_comfyui_ltx_i2v_twostage",
                "shot_anchor_image": str(Path(str(unit["anchor_path"])).resolve()),
                "shot_anchor_sha256": str(unit["anchor_sha256"]).lower(),
                "seed": int(unit["seed"]),
                "spoken_closeup": False,
                "musetalk_used": False,
                "raw_ltx_sha256": state["raw_sha256"],
                "aligned_sha256": state["aligned_sha256"],
                "rife_sha256": _sha256(destination),
                "publish_allowed": False,
            },
        }
        final_rows.append(row)
        state.update({"stage": "final", "output_path": str(destination), "output_sha256": row["output_sha256"]})
        pipeline["shots"] = list(states.values())
        pipeline["updated_at"] = _utc_now()
        _write_atomic(pipeline_path, pipeline)
        final_progress = {
            "schema_version": "fanqie_v62_ltx_progress/v1",
            "variant": "original_recomposed",
            "role": branch.get("role"),
            "plan_path": str(plan_path),
            "plan_sha256": plan_sha,
            "started_at": pipeline["started_at"],
            "updated_at": _utc_now(),
            "base_url": args.base_url,
            "renderer": "local_comfyui_ltx_i2v_twostage",
            "lip_sync_applied": False,
            "remote_calls": 0,
            "network_downloads": 0,
            "publish_allowed": False,
            "fanqie_backfill_allowed": False,
            "shots": final_rows,
            "success": len(final_rows) == len(units),
        }
        _write_atomic(final_progress_path, final_progress)
        print(json.dumps({"event": "rife_finished", "scene_id": scene_id}), flush=True)

    pipeline["success"] = True
    pipeline["finished_at"] = _utc_now()
    pipeline["updated_at"] = pipeline["finished_at"]
    _write_atomic(pipeline_path, pipeline)
    print(json.dumps({"event": "batch_finished", "rendered": len(final_rows)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
