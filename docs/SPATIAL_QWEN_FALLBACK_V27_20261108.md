# Qwen-Image-Edit-2511 typed fallback — CPU preparation, 2026-11-08

This is a conditional replacement for Klein if root's final screen-order comparison still fails. It is not automatically scheduled, and preparing it does not reserve or consume image budget. No Comfy/model POST, new download, dependency update or service change was made by this agent for this fallback.

## Actual supported inputs

Live `8190/object_info` and the local Comfy source confirm `TextEncodeQwenImageEditPlus` accepts **image1, image2, image3**, not four independent images. The same source sends each image to the vision encoder at approximately384² pixel area and the reference VAE at approximately1024² area. `TextEncodeQwenImage21` has a separate16-image interface, but compatibility with this2511 checkpoint was not assumed or used.

Evidence: `data/qa/SPATIAL_QWEN_V27_CAPABILITY_20261108.json`, including live node schemas, local `nodes_qwen.py` SHA and the earlier successful native workflow/result/model gate.

The actual successful November5 two-person workflow was native ID `8fe173b7-9812-4bab-a793-c11848523064`, 512×688, four steps. That proves this local2511/Lightning stack ran, not that the new three-person task or736×1312 performance has passed. The previous roughly200-second low-resolution results are not a valid timing promise for this new larger, three-reference job.

## Three-slot packing

- Image1: exact r3 skin-corrected Blender stage, geometry/camera/pose/holder states bound by SHA.
- Image2: Su Mo's original independent canonical front.
- Image3: an **appearance-only** board of the two brothers, ordered by their projected screen-x positions. Left is Ye Xijue/beige T-shirt; right is Ye Nan/gray polo for the current canary stages.
- S04 end contains only the father, so it uses image1+image2 and no child board.

The board is not a composited movie frame or an approved guide. It is a deterministic unlabelled packing of existing canonical pixels. Each child source is768×1024; the actual crop is x128/y16/width512/height608, pasted without resizing at x0 or x512 into a1024×608 board. Per-source SHA, exact crop and target coordinates are recorded. The two original fronts and actual combined board were viewed: hair/head are retained; this is an upper-body crop and some lower arms/hands are cut at the bottom. Root must independently view and approve the board before any POST.

This packing gives the father a separate vision slot and larger child faces than a three-person full-body board. It is a reasonable test, not a guarantee of identity or spatial correctness. The prompt associates each named reference portrait with its original clothing-marker figure, preserves blocked positions/heights, and derives eyes/posture/bread holder from structured source state. It requests a single continuous scene from image1, not the portrait-board layout.

## Exact local model graph

- `qwen_image_edit_2511_int8_convrot.safetensors`
- `qwen_2.5_vl_7b_fp8_scaled.safetensors`, CLIP type `qwen_image`
- `qwen_image_vae.safetensors`
- `Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors`, strength1
- Prior successful order retained: UNET → AuraFlow shift3.1 → CFGNorm strength1 → Lightning LoRA → sampler.
- Four steps, CFG1, Euler/simple, denoise1; stage and target736×1312.
- Two candidate branches share model/CLIP/VAE loading but have separate conditioning, source latent, seed, sampler and save node. Positive and negative use the same image slots; negative prompt is empty, matching the earlier successful graph.

These model names were confirmed in the live node inventory and their existing D: files. The earlier model-gate SHA verification is preserved; this work did not download or replace weights, nor claim a new full30GB model rehash.

## Typed native execution and budget

Implementation: `src/content_factory/visual_spatial_qwen_v27.py`; CLI: `scripts/run_spatial_qwen_v27.py`. Klein's stable runtime is unchanged.

The typed graph rejects foreign classes, a fourth EditPlus input, changed model names, non-four-step sampler settings and incorrect output dimensions/scope. Actual sources are staged with the original native image staging helper and frozen bindings. The executor reuses native Config, lock, queue/path verification, SHA and receipt helpers without broadening the original Klein class whitelist.

Before a fresh POST it requires a root approval binding the exact proposal PLAN, native job PLAN, selected IDs and both actual appearance-board paths/SHAs. `ROOT_EXECUTION_APPROVAL_TEMPLATE.json` deliberately has `allow_post=false`. Root must copy it to a new approval file, view the board, set true and schedule an empty GPU window. Preparation and prepare-batch make no budget claim and cannot POST.

POST admission holds the experiment BUDGET lock and original GPU/input locks, rechecks staged sources, old PAUSE SHA and actual Comfy queue. It combines existing Klein reservations/known attempts from all sibling namespaces with all prior same-authorization Qwen claims. A claim with unknown ID still consumes its branch allowance; an unknown keyframe claim also blocks a successor POST through a new namespace. The native CLAIM is persisted before network submission. Missing-ID/uncertain responses are not replayed; known IDs are polled and collected from exact original histories and save nodes.

`QWEN_IMAGE_BRANCH_BUDGET.json` distinguishes claimed Qwen branches, actual known IDs, saved branches and unresolved claims, alongside existing Klein reservations. The original Klein-only `IMAGE_BRANCH_BUDGET.json` is not relabeled as a combined counter. With six actual Klein images after v26, Qwen2 canary+2 keyframe ends would make ten images total if the Klein remaining batch is not dispatched. Existing prepared Klein reservations conservatively count until explicitly superseded; this work did not erase them.

## Actual prepared artifacts (0 production POST)

Run: `data/video_generation/spatial_minute_experiments_20261107_v1/qwen_fallback_v27`.

- PLAN SHA `f97761be2a8af0f25848978ab223b4155fc70fc5564110e26a960e6fd3b51428`.
- Native canary PLAN SHA `49145cd7735d16f4a3b849f99a776028761fb0e1d10375f14e843c8fc6ee2a33`.
- Canary items S01_start/S03_end were physically staged and remain prepared with native ID null at handoff.
- Four keyframe specifications exist: S01_start, S03_end, S02_end, S04_end. Only the two canary items have a prepared native job.
- Appearance board SHA `8198f5717f6be5d29702bd7b658e49849462591572912349621508ef3ff14667` (the canary stages share identical board pixels but retain individual file bindings).
- Exact prompts: `CANARY_PROMPTS_READING.md`.

Once root actually approves and schedules:

```powershell
.venv/Scripts/python.exe -B scripts/run_spatial_qwen_v27.py execute --run data/video_generation/spatial_minute_experiments_20261107_v1/qwen_fallback_v27 --batch canary --approval data/video_generation/spatial_minute_experiments_20261107_v1/qwen_fallback_v27/ROOT_EXECUTION_APPROVAL.json --max-seconds 3600
```

If root chooses to continue with Qwen, prepare the end batch using `prepare-batch --batch end --ids S02_end S04_end`, then separately review/bind its sheets and exact job in another root approval. Never copy canary approval to a different job unchanged. Do not execute this fallback if v26 already meets the experiment's needs.

## CPU verification

Final **16 unique tests passed**,37.93s, zero failures/skips: `data/qa/spatial_qwen_v27_20261108_release.xml`. These are not added to intermediate14/15 or Klein32. The first test run had one fixture-assumption failure (synthetic room cameras deduplicated more frames than the real scene); it was corrected without changing model settings or weakening the budget gate.

Coverage includes real files/crops/staging, exact three-slot/model/sampler assertions, an isolated fake-HTTP POST→ID→HISTORY→real PNG collect path, root-approval rejection, missing-ID preservation/no replay, cross-namespace unknown-claim protection, HTTP rejection, history/source tampering, duplicate batch assignment and combined budget rejection before POST. Fake HTTP is a loopback test server with CPU-fixture PNGs, never a Comfy or model call.

Stable runtime SHA `9c5a4bbf9163e915467a8e93251c5c70ed4d1ecafa557174fd573df7ddd6eca2`.

CLI SHA `434c3d1c1cfe657b7a034cc92d07e65ba0cbe352619ec4d00ea556318dac3a98`.

All saved outputs will remain `production_approved=false` until actual root visual review. This preparation does not certify future image fidelity, runtime, guide quality or any full-minute video.
