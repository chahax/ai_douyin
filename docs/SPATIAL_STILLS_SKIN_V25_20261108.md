# Material-only spatial still correction — 2026-11-08

Root's actual review of the first Klein batch (`82fc29a2-c14e-4f78-85e1-aec3a7cc42a6`) found a teal plastic head/hands remaining on Ye Nan. Both original images, their native result and old `stills_r3` plans remain unchanged. This correction changes the upstream material contract and deterministic prompt in a **new namespace**, rather than manually editing generated people.

## New input contract

The source is still the exact final spatial r3 PLAN/HANDOFF; coordinates, camera matrices and actor/prop states are unchanged. The new renderer receipt is:

`data/video_generation/spatial_minute_experiments_20261107_v1/spatial_r3/blender_skin_proxy_v25/RESULT.json`

SHA256: `e69b6fb036326b0ef542aa4c495f608be8025c4d817b459e4993047e782435e6`.

Stills preparation explicitly requires `identity_color_clothes_only/v25`. It checks the full material contract in renderer REQUEST and actual metadata, and recomputes `validate_skin_metadata` from observed mesh material names and RGB values. The renderer result's skin-material verification must match that recomputation. Null, absent and wrong-colored heads are rejected; a legacy color-everywhere renderer cannot be relabeled as v25.

The deterministic prompt identifies a **figure with a teal/blue/orange clothing marker**, not a wholly colored person. It calls for natural human skin on visible heads/faces/hands using the named canonical photograph. The common architecture sentence now preserves **visible architecture and furniture** rather than demanding a doorway and two windows in every camera view. Hand grips and bread-holder semantics still come from structured state. Old legacy prompts remain in the legacy branch and all original frozen prompt files remain untouched.

The renderer remains coarse blocking, without a real face/hand rig. This is not a semantic quality certificate for either the placeholder or its future Klein output.

## Same-authorization global image ledger

Starting another still run does not reset the original 12-branch engineering allowance. Preparation and fresh submission inspect all sibling still batches bound to that exact authorization, validate native graph/save-node counts and retain failed/unknown claims in the reservation count.

`IMAGE_BRANCH_BUDGET.json` explicitly separates:

- `reserved_branches`: prepared plus already attempted branches;
- `known_native_branches`: branches with an actual known native ID;
- `saved_branches`: known technically saved branches;
- `unknown_claim_branches`: unresolved claimed submissions without an ID;
- `unsubmitted_reserved_branches`: prepared reservations without a claim or ID.

Each new batch also retains `BUDGET_ADMISSION.json`, including previous batch/result evidence and the post-admission reservation count. These are image-budget records only; H3 budgets, original native records and old holds are not modified.

At CPU handoff, the original failed canary accounted for **2 known/saved images**, and the new skin canary reserved **2 unsubmitted images**: **4/12 reserved, 2 actually generated, 0 unknown**. The old r2 whole-plan preparation had no batch/CLAIM/UUID and consumed no image reservation. Preparing the remaining five unique actor states later would make nine reserved branches, not nine already generated images.

## Actual CPU preparation

New run: `data/video_generation/spatial_minute_experiments_20261107_v1/stills_r3_skin_v1`.

- PLAN SHA: `ebcbd8a9984657ecd11947a1e59d1d1091ae2de61c3e417689375eff4e767c81`.
- Canary BATCH SHA: `8bf3541838ec92969040814aaeed019e18c9d614cb94b787d70df2faaafd0afe`.
- Canary items: S01_start, S03_end; shared Klein loading, independent sampler/seed/save nodes; four independent refs each; 736×1312; four steps.
- The actual `visual_image_jobs_v3.prepare_job` staged canonical and rendered images and verified the real Config/file boundaries. State was prepared and native ID null at this agent's handoff. This agent made **zero new image/video POSTs**.

Root owns scheduling of actual image execution after H3 releases the GPU. Command:

```powershell
.venv/Scripts/python.exe -B scripts/run_spatial_stills_v24.py execute --run data/video_generation/spatial_minute_experiments_20261107_v1/stills_r3_skin_v1 --batch canary --max-seconds 1800
```

If root accepts those actual images for further experimentation, the five remaining unique actor-state candidates can be prepared with `--batch remaining --ids S02_end S03_start S04_start S04_end S04_at_7`. S01_end and S02_start alias S01_start and are not regenerated. Terminal S04 uses the stage plus the father reference only, never forces departed children back into frame.

## Verification

Final **27 unique tests passed**, 23.94s, zero failures/skips, in `data/qa/spatial_stills_skin_v25_20261108_receipt.xml`. This includes the prior 19 tests; do not add 19+27. New coverage includes real skin-receipt/file staging, exact legacy prompt replay, null/colored-head rejection, cross-run budget exhaustion, unknown-claim retention, distinguishable actual/reserved counts and preservation of old renderer evidence. Native collector testing still uses actual fixture histories and independently saved PNGs through the original collector, without model or service calls.

Stable runtime SHA: `db218efb7354407b08a666e340cdbe8daad6eca47ba7cb4fdf8a5dfb0eeacb07`.

CLI SHA: `810abbb6f8543101296a7bc63ea8e8788ba7f3d2e652921eb927f2c17cfc616e`.

The CPU contract and actual preparation are complete. The new skin Klein images, motion, H3 results and full minute remain to be generated and reviewed by root; no production or publication approval is granted here.
