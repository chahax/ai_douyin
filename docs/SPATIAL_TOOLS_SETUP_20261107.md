# Spatial tools setup and real MoGe pilot — 2026-11-07

This work downloaded local tools and ran one authorized environment-geometry pilot. It does **not** claim a new H3 movie, full-room reconstruction, commercial/visual acceptance, or production deployment. Accounts, browsers, service configuration, original Python dependencies and old media holds were not changed.

## Tools actually available

- Blender **4.5.9 LTS**, portable official build, 399,051,129-byte archive. Actual `blender.exe --version` succeeded (build hash `8bf95cbd38d1`). Executable: `D:/IT/ai_douyin/data/tools/spatial_20261107/blender/blender-4.5.9-windows-x64/blender.exe`.
- Official SHA256 file fetched from `https://download.blender.org/release/Blender4.5/blender-4.5.9.sha256`; archive SHA **41da973b9bf95bb312cbeff4d1982feb13259b43c821686b9bafea4dfe5477cf** matched exactly.
- The official server's bulk transfers stalled. The known download worker was stopped through its own tool session; partial files remain. The archive was fetched from the Tsinghua Blender mirror with explicit ranged requests and validated against the original official SHA. No service or unrelated process was killed.
- Microsoft **MoGe-2-vits-normal**, 140,550,416 bytes, official HF SHA **79a16621928c2bf0ed04659218c55c01075e950507f40bb3332fb4c873d3e1dc** matched. Weight: `data/models/spatial_20261107/moge-2-vits-normal/model.pt`.
- Model source: `https://github.com/microsoft/MoGe`; official weight/declared MIT license: `https://huggingface.co/Ruicheng/moge-2-vits-normal`; official SHA visible at `https://huggingface.co/Ruicheng/moge-2-vits-normal/blob/main/model.pt`. Direct HF API timed out, so transport used `hf-mirror.com`; integrity was checked against the official HF page, not merely a mirror-provided digest.
- MoGe code is MIT; its bundled DINOv2 code is Apache-2.0. Source ZIP and license digests are recorded in `data/tools/spatial_20261107/SETUP_MANIFEST.json`.

## Runtime isolation

All new executables, sources, weights, caches and temporary files are on D: under `data/tools/spatial_20261107` or `data/models/spatial_20261107`.

The new `moge_env` is a Python 3.14 venv with read-only `.pth` references to the existing Comfy and project site-packages. It reuses their existing PyTorch 2.11.0+cu130 and utilities, rather than downloading/replacing a second multi-GB PyTorch installation. It is **an isolated overlay, not a fully independent dependency copy**. Nothing was installed into the original venvs. Direct CPU import of `moge.model.v2.MoGeModel` passed.

An initially attempted managed Python 3.13 download was stopped through its known session; partial data remains on D:. No system Python was replaced.

## Excluded candidates

**Apple SHARP is not suitable for this production/product-development task under the inspected license.** The official `LICENSE_MODEL` explicitly limits use to non-commercial scientific research and excludes product development or use in commercial products/services. Source was inspected and preserved; the weight download was stopped, with its partial file retained. There were **zero SHARP inference calls**. See `SHARP_PRODUCTION_HOLD.json` and the retained official license in `sharp_source/ml-sharp-main/LICENSE_MODEL`. This corrects any earlier implication that publicly released weights automatically permit commercial production.

**HY-World 2.0 full world generation** was researched, not downloaded. The official setup describes HY-Pano-2 around 80B parameters, WorldStereo-2 around 17B, extra native components and FlashAttention. The full pipeline was not selected for this 16GB Windows machine. This is a routing decision, not a claim that every submodel is categorically impossible to run.

## Actual MoGe GPU pilot

Root authorized exactly one source image and one MoGe GPU pilot. Input:

`data/serial_story_assets/1a437fadb696efa21c6e388d1d5ca81f_v4.png`

Source SHA **b97231a01cbaff83a000f12be5f22b140fe88e334ed63eb7184f2ba25157eee9**.

The wrapper held the existing `GPU.lock` and `VISUAL_GPU.lock`, checked the original old PAUSE digest and confirmed the 8190 queue was empty before inference. The lease was released immediately after copying inferred arrays to CPU; mesh export occurred afterward. Known worker session 23154 exited **0**. Two earlier wrapper import failures happened before CLAIM creation and before GPU inference; they did not consume additional model calls.

- Input was resized to **576×768** for this geometry pilot, resolution level 5, FP16 inference.
- Model load: **1.125s**; inference: **16.183s**; CPU mesh export: **7.870s**.
- Peak allocated GPU memory: **907,749,376 bytes**; reserved: **1,107,296,256 bytes**. These are this standalone MoGe process's PyTorch measurements, not total system/GPU usage.
- Saved NPZ maps, depth/normal visualization, validity mask, normalized camera intrinsics, GLB mesh and PLY point cloud in `data/video_generation/spatial_minute_experiments_20261107_v1/moge`.
- Estimated valid depth range was approximately **1.01–4.73m**. This scale is model-estimated; it is not measured room dimensions.

The independent CPU validator verified all original/result/model SHA bindings, map dimensions, finite positive observed depths, camera-matrix shape, and a nonempty finite GLB mesh. `CPU_VALIDATION.json` records success. A validity mask of 1.0 does **not** mean the unseen back of the room has been recovered or that its geometry is accurate. Outputs remain `production_approved=false` and `full_room_reconstruction=false`.

## Reusable commands

The inference wrapper refuses a pre-existing `CLAIM.json`; do not rerun it blindly against the same output folder.

```powershell
data/tools/spatial_20261107/moge_env/Scripts/python.exe -X utf8 -B scripts/spatial_tools_setup_v24_moge.py --source <approved-image> --output <new-output-folder>
data/tools/spatial_20261107/moge_env/Scripts/python.exe -B scripts/spatial_tools_setup_v24_validate.py data/video_generation/spatial_minute_experiments_20261107_v1/moge
```

Future GPU runs require root scheduling with other media jobs. The validator is CPU-only and does not infer, submit, update model inputs or change original results.

## Evidence and recovery

- `data/tools/spatial_20261107/BLENDER_READY.json`
- `data/tools/spatial_20261107/MOGE_MODEL_READY.json`
- `data/tools/spatial_20261107/SETUP_MANIFEST.json`
- `data/tools/spatial_20261107/SHARP_PRODUCTION_HOLD.json`
- `data/spatial_tools_setup_v24_parallel_mirror.log`
- `data/spatial_tools_setup_v24_moge_inference.log`
- `data/video_generation/spatial_minute_experiments_20261107_v1/moge/{CLAIM,INFERENCE_RESULT,CPU_VALIDATION,CAMERA}.json`

No Windows/Codex periodic task was added. Blender is ready for the scene agent's CPU-only renders; no further MoGe/SHARP GPU work was dispatched.
