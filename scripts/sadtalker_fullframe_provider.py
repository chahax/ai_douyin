"""Auditable hybrid provider for V6.1 live-action story shots.

Spoken shots use a reviewed full-frame plate with SadTalker driving only the
face crop; the crop is pasted back into the exact plate and then interpolated
through the existing RIFE delivery stage.  Silent action shots remain delegated
to the production ComfyUI LTX provider.  The two paths use distinct fingerprints,
schemas and provenance fields.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from src.novel_promotion.comfy_ltx_video_provider import (
    DELIVERY_FPS,
    REQUIRED_RIFE_NODE_CLASSES,
    VHS_LOAD_VIDEO_AUDIO_OUTPUT_INDEX,
    ComfyLTXVideoSceneProvider,
    _comfy_health_check,
    _comfy_object_info,
    _ffprobe_duration,
    _ffprobe_fps,
    _ffprobe_has_audio,
    _validate_base_url,
)
from src.novel_promotion.scene_provider import (
    MissingCapability,
    PreflightResult,
    SceneAsset,
    SceneAssetResult,
    ScenePlan,
)


logger = logging.getLogger(__name__)

PROVIDER_NAME = "hybrid_live_action_v61"
PROVIDER_VERSION = "1.2.0"
SPOKEN_RENDERER = "sadtalker_fullframe"
SPOKEN_CACHE_SCHEMA = "fanqie_sadtalker_fullframe/cache/v2"
WRAPPER_AUDIT_SCHEMA = "fanqie_sadtalker_fullframe/v1"
RIFE_BINDING_SCHEMA = "fanqie_sadtalker_fullframe/rife_binding/v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        shutil.copy2(str(source), str(temporary))
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_json_new(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
    except FileExistsError as exc:
        raise RuntimeError(f"refusing to overwrite immutable evidence: {path}") from exc


class HybridLiveActionV61Provider:
    """Route spoken and silent V6.1 beats through distinct reviewed engines."""

    test_only = False
    requires_structured_scene_plan = True

    def __init__(
        self,
        *,
        base_url: str,
        comfy_input: str,
        comfy_output: str,
        evidence_root: str,
        timeout_seconds: int,
        sadtalker_python: str,
        sadtalker_root: str,
        sadtalker_checkpoint_dir: str,
        sadtalker_wrapper: str,
        expression_scale: float = 0.58,
        width: int = 704,
        height: int = 1248,
        fps: int = 25,
        delivery_fps: int = DELIVERY_FPS,
        ltx_provider: ComfyLTXVideoSceneProvider | None = None,
    ) -> None:
        self._base_url = _validate_base_url(base_url)
        self._comfy_input = Path(comfy_input)
        self._comfy_output = Path(comfy_output)
        self._evidence_root = Path(evidence_root)
        self._timeout = int(timeout_seconds)
        self._sadtalker_python = Path(sadtalker_python)
        self._sadtalker_root = Path(sadtalker_root)
        self._checkpoint_dir = Path(sadtalker_checkpoint_dir)
        self._wrapper = Path(sadtalker_wrapper)
        self._expression_scale = float(expression_scale)
        self._width = int(width)
        self._height = int(height)
        self._fps = int(fps)
        self._delivery_fps = int(delivery_fps)
        self._runtime_manifest_cache: dict[str, str] | None = None
        if not (0.1 <= self._expression_scale <= 1.5):
            raise ValueError("expression_scale outside reviewed range 0.1..1.5")
        if self._delivery_fps != self._fps * 2:
            raise ValueError("reviewed RIFE contract requires a 2x delivery fps")
        self._ltx = ltx_provider or ComfyLTXVideoSceneProvider(
            base_url=self._base_url,
            comfy_input=str(self._comfy_input),
            comfy_output=str(self._comfy_output),
            evidence_root=str(self._evidence_root),
            timeout_seconds=self._timeout,
            width=self._width,
            height=self._height,
            fps=self._fps,
            delivery_fps=self._delivery_fps,
            musetalk_available=False,
        )

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    @property
    def provider_version(self) -> str:
        return PROVIDER_VERSION

    def preflight(
        self, plans: list[ScenePlan], *, require_dialogue_audio: bool = True
    ) -> PreflightResult:
        spoken = [plan for plan in plans if bool(plan.metadata.get("spoken_closeup"))]
        silent = [plan for plan in plans if not bool(plan.metadata.get("spoken_closeup"))]
        errors = self._spoken_preflight_errors(
            spoken, require_dialogue_audio=require_dialogue_audio
        )
        silent_result = self._ltx.preflight(silent) if silent else None
        if silent_result is not None and not silent_result.ok:
            errors.append(f"silent LTX preflight: {silent_result.error}")
        return PreflightResult(
            ok=not errors,
            provider_name=self.name,
            planned_scene_count=len(plans),
            status="ok" if not errors else "capability_check_failed",
            error="; ".join(errors),
            details={
                "spoken_renderer": SPOKEN_RENDERER,
                "spoken_count": len(spoken),
                "silent_ltx_count": len(silent),
                "base_url": self._base_url,
                "delivery_fps": self._delivery_fps,
                "silent_ltx_preflight": vars(silent_result) if silent_result else None,
            },
        )

    def _spoken_preflight_errors(
        self, plans: list[ScenePlan], *, require_dialogue_audio: bool
    ) -> list[str]:
        if not plans:
            return []
        errors: list[str] = []
        required_files = (
            (self._sadtalker_python, "SadTalker Python"),
            (self._wrapper, "SadTalker full-frame wrapper"),
            (self._sadtalker_root / "inference.py", "SadTalker inference.py"),
        )
        for path, label in required_files:
            if not path.is_file():
                errors.append(f"{label} missing: {path}")
        if not self._checkpoint_dir.is_dir():
            errors.append(f"SadTalker checkpoint directory missing: {self._checkpoint_dir}")
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            errors.append("ffmpeg and ffprobe are required")
        if not self._comfy_input.is_dir() or not self._comfy_output.is_dir():
            errors.append("ComfyUI input/output directories are missing")
        if not _comfy_health_check(self._base_url):
            errors.append(f"ComfyUI not reachable at {self._base_url}")
        else:
            try:
                obj_info = _comfy_object_info(self._base_url)
                missing = sorted(REQUIRED_RIFE_NODE_CLASSES - set(obj_info))
                if missing:
                    errors.append("Missing RIFE node classes: " + ", ".join(missing))
                load_video = obj_info.get("VHS_LoadVideo", {})
                output_types = list(load_video.get("output", []))
                if (
                    len(output_types) <= VHS_LOAD_VIDEO_AUDIO_OUTPUT_INDEX
                    or output_types[VHS_LOAD_VIDEO_AUDIO_OUTPUT_INDEX] != "AUDIO"
                ):
                    errors.append("VHS_LoadVideo AUDIO output contract mismatch")
            except Exception as exc:
                errors.append(f"ComfyUI RIFE capability check failed: {exc}")
        for plan in plans:
            shot_id = plan.scene_id
            anchor = Path(str(plan.metadata.get("shot_anchor_image") or ""))
            audio = Path(str(plan.metadata.get("dialogue_audio_path") or ""))
            if not anchor.is_file():
                errors.append(f"{shot_id}: reviewed shot anchor missing")
            if not audio.is_file():
                if require_dialogue_audio:
                    errors.append(f"{shot_id}: 16kHz dialogue audio missing")
                continue
            try:
                duration = _ffprobe_duration(str(audio))
                if abs(duration - float(plan.estimated_duration_s)) > 0.12:
                    errors.append(f"{shot_id}: dialogue audio duration mismatch")
                sample_rate = subprocess.run(
                    ["ffprobe", "-v", "error", "-select_streams", "a:0",
                     "-show_entries", "stream=sample_rate",
                     "-of", "default=noprint_wrappers=1:nokey=1", str(audio)],
                    check=False, capture_output=True, text=True, timeout=30, shell=False,
                )
                if sample_rate.returncode != 0 or sample_rate.stdout.strip() != "16000":
                    errors.append(f"{shot_id}: dialogue audio must be 16kHz")
            except Exception as exc:
                errors.append(f"{shot_id}: dialogue audio probe failed: {exc}")
        return errors

    def provide_scenes(
        self, plans: list[ScenePlan], output_dir: str | Path
    ) -> SceneAssetResult:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        assets: list[SceneAsset] = []
        missing: list[MissingCapability] = []
        for plan in plans:
            if bool(plan.metadata.get("spoken_closeup")):
                try:
                    assets.append(self._generate_spoken(plan, output))
                except Exception as exc:
                    logger.exception("SadTalker full-frame shot failed: %s", plan.scene_id)
                    missing.append(MissingCapability(
                        scene_id=plan.scene_id,
                        reason=f"SadTalker full-frame generation failed: {exc}",
                        provider_name=self.name,
                        required_capability=SPOKEN_RENDERER,
                    ))
            else:
                result = self._ltx.provide_scenes([plan], output)
                assets.extend(result.assets)
                missing.extend(result.missing)
        return SceneAssetResult(assets=assets, missing=missing)

    def _config_token(self) -> str:
        runtime_manifest = self._runtime_manifest()
        wrapper_sha = _sha256(self._wrapper) if self._wrapper.is_file() else "missing"
        inference = self._sadtalker_root / "inference.py"
        inference_sha = _sha256(inference) if inference.is_file() else "missing"
        rife_model = getattr(self._ltx, "_rife_model", None)
        rife_multiplier = getattr(self._ltx, "_rife_multiplier", None)
        if not isinstance(rife_model, str) or not rife_model.strip():
            raise RuntimeError("RIFE model binding unavailable; refusing cache fingerprint")
        if not isinstance(rife_multiplier, int) or rife_multiplier <= 0:
            raise RuntimeError("RIFE multiplier binding unavailable; refusing cache fingerprint")
        return "|".join([
            PROVIDER_VERSION,
            str(self._sadtalker_python.resolve()),
            str(self._sadtalker_root.resolve()),
            str(self._checkpoint_dir.resolve()),
            str(self._wrapper.resolve()),
            f"wrapper_sha256:{wrapper_sha}",
            f"inference_sha256:{inference_sha}",
            "runtime_manifest:"
            + hashlib.sha256(
                json.dumps(runtime_manifest, sort_keys=True).encode("utf-8")
            ).hexdigest().upper(),
            f"rife_model:{rife_model}",
            f"rife_multiplier:{rife_multiplier}",
            f"expression_scale:{self._expression_scale:.6f}",
            f"size:{self._width}x{self._height}",
            f"fps:{self._fps}->{self._delivery_fps}",
        ])

    def _runtime_manifest(self) -> dict[str, str]:
        """Hash the exact local SadTalker code/models once per provider run."""
        if self._runtime_manifest_cache is not None:
            return dict(self._runtime_manifest_cache)
        files: list[Path] = []
        if self._checkpoint_dir.is_dir():
            files.extend(sorted(
                path for path in self._checkpoint_dir.rglob("*")
                if path.is_file() and ".git" not in path.parts
            ))
        if self._sadtalker_root.is_dir():
            files.extend(sorted(
                path for path in self._sadtalker_root.rglob("*")
                if path.is_file()
                and path.suffix.lower() in {".py", ".yaml", ".yml"}
                and ".git" not in path.parts
                and "__pycache__" not in path.parts
            ))
        if self._sadtalker_python.is_file():
            files.append(self._sadtalker_python)
        files.append(self._wrapper)
        manifest: dict[str, str] = {}
        for path in files:
            resolved = path.resolve()
            key = str(resolved).replace("\\", "/")
            if key in manifest:
                continue
            manifest[key] = _sha256(resolved) if resolved.is_file() else "missing"
        self._runtime_manifest_cache = manifest
        return dict(manifest)

    def _fingerprint(
        self, *, plan: ScenePlan, anchor_sha: str, audio_sha: str
    ) -> str:
        payload = "|".join([
            SPOKEN_CACHE_SCHEMA, self._config_token(), plan.scene_id,
            anchor_sha, audio_sha, f"{float(plan.estimated_duration_s):.6f}",
        ])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest().upper()

    def _cache_dir(self, fingerprint: str) -> Path:
        return (
            self._evidence_root / "sadtalker_fullframe" /
            fingerprint[:2].lower() / fingerprint.lower()
        )

    def _valid_cache(
        self, *, cache_dir: Path, fingerprint: str, anchor_sha: str,
        audio_sha: str, target_duration: float,
    ) -> dict[str, Any] | None:
        meta_path = cache_dir / "audit_meta.json"
        clip = cache_dir / "rife_clip.mp4"
        spoken = cache_dir / "sadtalker_fullframe_clip.mp4"
        wrapper_audit = cache_dir / "sadtalker_fullframe.audit.json"
        rife_binding_path = cache_dir / "rife_binding.json"
        if not all(path.is_file() for path in (
            meta_path, clip, spoken, wrapper_audit, rife_binding_path,
        )):
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            audit = json.loads(wrapper_audit.read_text(encoding="utf-8"))
            rife_binding = json.loads(rife_binding_path.read_text(encoding="utf-8"))
            if (
                meta.get("schema") != SPOKEN_CACHE_SCHEMA
                or meta.get("fingerprint") != fingerprint
                or meta.get("shot_anchor_sha256") != anchor_sha
                or meta.get("dialogue_audio_sha256") != audio_sha
                or meta.get("spoken_renderer") != SPOKEN_RENDERER
                or audit.get("schema") != WRAPPER_AUDIT_SCHEMA
                or audit.get("source_image_sha256") != anchor_sha
                or audit.get("dialogue_audio_sha256") != audio_sha
                or audit.get("output_sha256") != meta.get("spoken_renderer_sha256")
                or not isinstance(audit.get("plate_preservation"), dict)
                or audit["plate_preservation"].get("passed") is not True
                or rife_binding.get("schema") != RIFE_BINDING_SCHEMA
                or rife_binding.get("source_sha256") != meta.get("spoken_renderer_sha256")
                or rife_binding.get("output_sha256") != meta.get("final_sha256")
                or rife_binding.get("rife_model") != getattr(self._ltx, "_rife_model", None)
                or rife_binding.get("rife_multiplier") != getattr(self._ltx, "_rife_multiplier", None)
                or meta.get("runtime_manifest") != self._runtime_manifest()
                or _sha256(clip) != meta.get("final_sha256")
                or _sha256(spoken) != meta.get("spoken_renderer_sha256")
                or _sha256(wrapper_audit) != meta.get("spoken_renderer_audit_sha256")
                or _sha256(rife_binding_path) != meta.get("rife_binding_sha256")
                or abs(_ffprobe_duration(str(clip)) - target_duration) > 0.12
                or abs(_ffprobe_fps(str(clip)) - self._delivery_fps) > 0.5
                or not _ffprobe_has_audio(str(clip))
            ):
                return None
            return meta
        except (OSError, ValueError, TypeError, json.JSONDecodeError, RuntimeError):
            return None

    def _asset_from_cache(
        self, *, plan: ScenePlan, cache_dir: Path, meta: dict[str, Any],
        output_dir: Path, cached: bool,
    ) -> SceneAsset:
        destination = output_dir / f"{plan.scene_id}.mp4"
        _atomic_copy(cache_dir / "rife_clip.mp4", destination)
        if _sha256(destination) != meta["final_sha256"]:
            destination.unlink(missing_ok=True)
            raise RuntimeError("cached final clip changed during copy")
        metadata = {
            **plan.metadata,
            "fingerprint": meta["fingerprint"],
            "provider_version": PROVIDER_VERSION,
            "cached": cached,
            "has_presenter": False,
            "shot_anchor_sha256": meta["shot_anchor_sha256"],
            "dialogue_audio_path": meta["dialogue_audio_path"],
            "dialogue_audio_sha256": meta["dialogue_audio_sha256"],
            "spoken_renderer": SPOKEN_RENDERER,
            "spoken_renderer_used": True,
            "spoken_renderer_artifact_path": str(
                (cache_dir / "sadtalker_fullframe_clip.mp4").resolve()
            ),
            "spoken_renderer_sha256": meta["spoken_renderer_sha256"],
            "spoken_renderer_audit_path": str(
                (cache_dir / "sadtalker_fullframe.audit.json").resolve()
            ),
            "spoken_renderer_audit_sha256": meta["spoken_renderer_audit_sha256"],
            "sadtalker_fullframe_used": True,
            "musetalk_used": False,
            "rife_fps": meta["rife_fps"],
            "rife_binding_path": str((cache_dir / "rife_binding.json").resolve()),
            "rife_binding_sha256": meta["rife_binding_sha256"],
            "final_sha256": meta["final_sha256"],
            "per_stage_sha256": meta["per_stage_sha256"],
        }
        return SceneAsset(
            scene_id=plan.scene_id,
            video_path=str(destination.resolve()),
            duration_s=float(plan.estimated_duration_s),
            provider_name=self.name,
            metadata=metadata,
        )

    def _generate_spoken(self, plan: ScenePlan, output_dir: Path) -> SceneAsset:
        shot_id = plan.scene_id
        anchor = Path(str(plan.metadata.get("shot_anchor_image") or "")).resolve()
        audio = Path(str(plan.metadata.get("dialogue_audio_path") or "")).resolve()
        if not anchor.is_file() or not audio.is_file():
            raise RuntimeError("reviewed anchor and dialogue audio are required")
        expected_anchor_sha = str(plan.metadata.get("shot_anchor_sha256") or "").upper()
        anchor_sha = _sha256(anchor)
        if not expected_anchor_sha or anchor_sha != expected_anchor_sha:
            raise RuntimeError("reviewed shot anchor SHA mismatch")
        audio_sha = _sha256(audio)
        target_duration = float(plan.estimated_duration_s)
        if abs(_ffprobe_duration(str(audio)) - target_duration) > 0.12:
            raise RuntimeError("dialogue audio duration mismatch")
        sample_rate = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=sample_rate",
             "-of", "default=noprint_wrappers=1:nokey=1", str(audio)],
            check=False, capture_output=True, text=True, timeout=30, shell=False,
        )
        if sample_rate.returncode != 0 or sample_rate.stdout.strip() != "16000":
            raise RuntimeError("dialogue audio must be 16kHz")
        fingerprint = self._fingerprint(plan=plan, anchor_sha=anchor_sha, audio_sha=audio_sha)
        cache_dir = self._cache_dir(fingerprint)
        cached_meta = self._valid_cache(
            cache_dir=cache_dir, fingerprint=fingerprint, anchor_sha=anchor_sha,
            audio_sha=audio_sha, target_duration=target_duration,
        )
        if cached_meta:
            return self._asset_from_cache(
                plan=plan, cache_dir=cache_dir, meta=cached_meta,
                output_dir=output_dir, cached=True,
            )

        shot_dir = output_dir / "audit" / shot_id
        shot_dir.mkdir(parents=True, exist_ok=True)
        invocation = shot_dir / "sadtalker_runs" / uuid.uuid4().hex
        spoken_path = invocation / f"{shot_id}_sadtalker_fullframe.mp4"
        wrapper_audit = invocation / f"{shot_id}_sadtalker_fullframe.audit.json"
        wrapper_work = invocation / "wrapper_work"
        command = [
            str(self._sadtalker_python), str(self._wrapper),
            "--source-image", str(anchor), "--audio", str(audio),
            "--output", str(spoken_path), "--audit", str(wrapper_audit),
            "--work-dir", str(wrapper_work),
            "--sadtalker-root", str(self._sadtalker_root),
            "--checkpoint-dir", str(self._checkpoint_dir),
            "--width", str(self._width), "--height", str(self._height),
            "--fps", str(self._fps),
            "--expression-scale", f"{self._expression_scale:.6f}",
            "--timeout-seconds", str(self._timeout),
        ]
        result = subprocess.run(
            command, check=False, capture_output=True, text=True,
            timeout=self._timeout, shell=False, cwd=str(self._sadtalker_root),
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"SadTalker wrapper exited {result.returncode}: "
                f"{(result.stderr or result.stdout)[-3000:]}"
            )
        if not spoken_path.is_file() or not wrapper_audit.is_file():
            raise RuntimeError("SadTalker wrapper did not produce clip and audit")
        audit = json.loads(wrapper_audit.read_text(encoding="utf-8"))
        spoken_sha = _sha256(spoken_path)
        if (
            audit.get("schema") != WRAPPER_AUDIT_SCHEMA
            or audit.get("source_image_sha256") != anchor_sha
            or audit.get("dialogue_audio_sha256") != audio_sha
            or audit.get("output_sha256") != spoken_sha
            or not isinstance(audit.get("plate_preservation"), dict)
            or audit["plate_preservation"].get("passed") is not True
            or Path(str(audit.get("output_path") or "")).resolve() != spoken_path.resolve()
            or abs(_ffprobe_duration(str(spoken_path)) - target_duration) > 0.12
            or abs(_ffprobe_fps(str(spoken_path)) - self._fps) > 0.01
            or not _ffprobe_has_audio(str(spoken_path))
        ):
            raise RuntimeError("SadTalker wrapper audit/output contract failed")

        rife_output_dir = invocation / "rife"
        rife_job_id = f"{shot_id}_{invocation.name}"
        rife_path = rife_output_dir / f"{rife_job_id}_rife50.mp4"
        if rife_path.exists():
            raise RuntimeError("fresh RIFE invocation unexpectedly contains output")
        self._ltx._run_rife(  # reviewed shared delivery primitive
            source_path=spoken_path, output_dir=rife_output_dir, shot_id=rife_job_id
        )
        if (
            not rife_path.is_file()
            or abs(_ffprobe_duration(str(rife_path)) - target_duration) > 0.12
            or abs(_ffprobe_fps(str(rife_path)) - self._delivery_fps) > 0.5
            or not _ffprobe_has_audio(str(rife_path))
        ):
            raise RuntimeError("RIFE delivery output contract failed")
        final_sha = _sha256(rife_path)
        wrapper_audit_sha = _sha256(wrapper_audit)
        rife_model = getattr(self._ltx, "_rife_model", None)
        rife_multiplier = getattr(self._ltx, "_rife_multiplier", None)
        if not isinstance(rife_model, str) or not rife_model.strip():
            raise RuntimeError("RIFE output model binding unavailable")
        if not isinstance(rife_multiplier, int) or rife_multiplier <= 0:
            raise RuntimeError("RIFE output multiplier binding unavailable")
        rife_binding_path = invocation / "rife_binding.json"
        rife_binding = {
            "schema": RIFE_BINDING_SCHEMA,
            "rife_job_id": rife_job_id,
            "source_path": str(spoken_path.resolve()),
            "source_sha256": spoken_sha,
            "output_path": str(rife_path.resolve()),
            "output_sha256": final_sha,
            "rife_model": rife_model,
            "rife_multiplier": rife_multiplier,
            "delivery_fps": self._delivery_fps,
        }
        _write_json_new(rife_binding_path, rife_binding)
        per_stage = {
            "dialogue_audio_sha256": audio_sha,
            "spoken_renderer_sha256": spoken_sha,
            "spoken_renderer_audit_sha256": wrapper_audit_sha,
            "rife_binding_sha256": _sha256(rife_binding_path),
            "rife_sha256": final_sha,
        }
        meta = {
            "schema": SPOKEN_CACHE_SCHEMA,
            "fingerprint": fingerprint,
            "provider_name": self.name,
            "provider_version": PROVIDER_VERSION,
            "runtime_manifest": self._runtime_manifest(),
            "shot_id": shot_id,
            "shot_anchor_path": str(anchor),
            "shot_anchor_sha256": anchor_sha,
            "dialogue_audio_path": str(audio),
            "dialogue_audio_sha256": audio_sha,
            "spoken_renderer": SPOKEN_RENDERER,
            "spoken_renderer_sha256": spoken_sha,
            "spoken_renderer_audit_sha256": wrapper_audit_sha,
            "rife_binding_sha256": _sha256(rife_binding_path),
            "target_duration_s": target_duration,
            "source_fps": self._fps,
            "rife_fps": self._delivery_fps,
            "final_sha256": final_sha,
            "per_stage_sha256": per_stage,
        }
        cache_dir.parent.mkdir(parents=True, exist_ok=True)
        staging = cache_dir.parent / f".{cache_dir.name}.{uuid.uuid4().hex}.staging"
        staging.mkdir(exist_ok=False)
        try:
            _atomic_copy(spoken_path, staging / "sadtalker_fullframe_clip.mp4")
            _atomic_copy(wrapper_audit, staging / "sadtalker_fullframe.audit.json")
            _atomic_copy(rife_path, staging / "rife_clip.mp4")
            _atomic_copy(rife_binding_path, staging / "rife_binding.json")
            _write_json_atomic(staging / "audit_meta.json", meta)
            try:
                staging.rename(cache_dir)
            except FileExistsError:
                # An identical concurrent run won the immutable namespace. Its
                # bytes still have to pass the complete cache contract below.
                shutil.rmtree(staging)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        validated = self._valid_cache(
            cache_dir=cache_dir, fingerprint=fingerprint, anchor_sha=anchor_sha,
            audio_sha=audio_sha, target_duration=target_duration,
        )
        if validated is None:
            raise RuntimeError("new SadTalker evidence cache failed validation")
        return self._asset_from_cache(
            plan=plan, cache_dir=cache_dir, meta=validated,
            output_dir=output_dir, cached=False,
        )
