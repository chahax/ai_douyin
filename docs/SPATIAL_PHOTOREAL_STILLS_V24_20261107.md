# Spatial blocking to photoreal still candidates — v24, 2026-11-07

This additive layer consumes the final spatial HANDOFF, original CPU Blender RESULT and three named canonical cast fronts. It prepares local Klein image jobs; it does not treat blockout placeholders or technically saved outputs as approved H3 guides. There is no service restart, cloud call, dependency upgrade or old-batch migration.

Implementation: `src/content_factory/visual_spatial_stills_v24.py`; CLI: `scripts/run_spatial_stills_v24.py`.

## Input and prompt contract

- Verify HANDOFF, linked spatial PLAN, actual Blender REQUEST/RESULT, renderer metadata, all individual stage image SHAs, canonical image identities and explicit root authorization.
- Renderer must be CPU/Cycles, actual images 736×1312, correct plan digest and actual visible actor IDs/bread holder.
- The first reference is the exact stage image. Additional references are only the canonical fronts of people actually visible in that stage. Three-person stages use four independent inputs; S04 end uses the stage plus the father only. Empty-room images use one reference.
- Map blue to adult Su Mo/dark jacket+gray button shirt, teal to older Ye Nan/gray polo+dark long trousers, orange to younger Ye Xijue/beige T-shirt+gray shorts. Placeholder colors are identity markers, not wardrobe.
- Compile posture, eye state, actual named bread holder and empty hands for nonholders from structured state. Natural hand grips/arms must realize the holder state rather than copying the coarse mannequin's default arms or floating prop cube literally.
- Preserve source-stage perspective and camera composition. There is no global fixed-camera video wrapper and no dialogue rewrite or text-model call.
- Current frozen prompt also names the room's doorway and two windows. Root identified that this may induce architecture outside the visible camera view. This remains an explicit pilot risk; it was not silently edited after PLAN freeze. If actual stills show that failure, use a new namespace/prompt revision.

## Job and recovery contract

`prepare` and `prepare-batch` are CPU/file-only. The H3 config superset is distilled to the actual `visual_image_jobs_v3.Config` fields; `gpu_lock_root`, dimensions and H3 workflow fields are never passed to that constructor.

`prepare-batch` calls the real original `build_graph` and `prepare_job`: shared Klein4B BF16/FP4-encoder/VAE loaders, 4 steps, each image with its own seed/sampler/save node. Sources are physically staged and verified before a job is called prepared. Batch inputs, parent plan and native graph are frozen. Duplicate stage reservation in two batches is rejected. Exact repeated state+camera combinations are aliases and cannot be separately selected for generation.

`tick`/`execute` use original submit/poll/collect and known-ID receipts. A fresh submit takes the shared GPU.lock and original input-root VISUAL_GPU.lock; a busy Comfy queue waits. Unknown claim without ID, failed, interrupted and rejected states are not replayed. Native complete is collected without another service poll. Because original `collect` returns a RESULT rather than a STATE, this adapter re-reads status after collection.

Every observed ID is appended once to `job_ids.txt` and `LOG.md`. A saved native result produces `CANDIDATES.json` bound to its actual save nodes, files, SHAs, dimensions and original ID. `production_approved=false` remains; root must actually review the candidate before using it as a video guide.

The local plan caps selected unique branches at the root authorization's image allowance (at most12); the main experiment owner still controls the overall budget across separate experimental namespaces.

## Actual preparation (0 model POST by this agent)

The earlier `stills/PLAN.json` used r2 during CPU integration and remains preserved, never submitted. Root selected final spatial r3; production-pilot preparation is exclusively in:

`data/video_generation/spatial_minute_experiments_20261107_v1/stills_r3`

- Final r3 HANDOFF SHA: `f776e7094c0735a35ecc1212896dcc467131991279be3cdc1504ebe5cb03b94e`.
- Actual r3 Blender RESULT SHA: `6ddd88d5ef1316f5802028e03849b3fd10894b7fab0de62d7f0f8953fe74dfe1`.
- Stills PLAN SHA: `6084d52ea3369a0e6b253fb459247eae333fbb00da41b204da8deffc9fceb80c`.
- Canary BATCH SHA: `1c742f4ca458b0ac0b8beb17d608899a766ec28ba852795bdbaa61d2a68aa860`.
- Canary items: **S01_start** (three people, adult lying) and **S03_end** (three people, adult standing with bread).
- Native image `prepare_job` completed with actual canonical and stage file staging, not a mocked prepare. State was prepared, native ID null at handoff.
- S01_end and S02_start alias S01_start. The remaining five unique actor states are S02_end, S03_start, S04_start, S04_end, S04_at_7. Three optional empty-room candidates are prepared as specifications but not assigned to a batch.

Root owns actual GPU execution after the concurrent H3 canary has left the queue. This document does not claim those image requests have already been submitted or visually passed.

## Commands

```powershell
.venv/Scripts/python.exe -B scripts/run_spatial_stills_v24.py status --run data/video_generation/spatial_minute_experiments_20261107_v1/stills_r3
.venv/Scripts/python.exe -B scripts/run_spatial_stills_v24.py execute --run data/video_generation/spatial_minute_experiments_20261107_v1/stills_r3 --batch canary --max-seconds 1800
.venv/Scripts/python.exe -B scripts/run_spatial_stills_v24.py prepare-batch --run data/video_generation/spatial_minute_experiments_20261107_v1/stills_r3 --batch remaining --ids S02_end S03_start S04_start S04_end S04_at_7
```

Do not execute the remaining batch until root has reviewed canary outputs and selected whether this frozen prompt remains suitable.

## Tests

Final **19 unique tests passed**, 11.41 seconds, zero failures/skips: `data/qa/spatial_stills_v24_20261107_final.xml`. This is not 18+19 tests. The first test command failed before tests ran because the existing C: pytest temp folder was inaccessible; preserved XML `spatial_stills_v24_20261107.xml`. Subsequent runs used explicit D: temporary directories.

Tests create real file fixtures, physically stage inputs through the original image job layer, verify native Config's actual field boundary, preserve ID/unknown protections, reject source/cast/camera evidence tampering, prevent duplicate reservation, and run the real native collector against a clearly marked completed CPU-fixture history with real independently saved PNGs. The fixture is not a model output and never contacts Comfy. Actual r3 file-boundary prepare was also performed independently of those fixtures.

Stable runtime SHA at handoff: `83769515e294859b4e3971801caff2f065f60ce286a027506d5b1a2a3a9ef5f9`; CLI SHA `2042b4badd161b4e80fe770b103d29975075bfba35c9b84e42c51b19dc0f68f7`. No core edits are scheduled while root runs the still canary.
