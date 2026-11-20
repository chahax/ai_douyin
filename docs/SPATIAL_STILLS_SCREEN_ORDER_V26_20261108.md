# Last bounded reference-packing comparison — v26, 2026-11-08

The prior skin-proxy canary removed the teal head, but root still observed wrong clothing/bread ownership and possible swapped brother positions. Those original images, native ID `e527a547...`, plans and prompts are preserved. V26 tests one input-packing hypothesis; it is not a claim that screen ordering identifies faces or solves multi-person composition.

## Changed and unchanged inputs

The exact r3 spatial HANDOFF and v25 skin-render RESULT are reused. Source stage pixels, geometry, actor/prop states, cameras, canonical photographs and per-stage random seeds are unchanged. H3's three named character reference order is not modified.

Only Klein's character-reference slots are reordered to match the left-to-right order of the **projected design head centers** in stage image1. The stage remains image1. Actual Blender camera world/projection matrices from the renderer metadata project head centers derived from the original renderer's geometry formula. The transform checks finite values, 4×4 shape and a rigid camera matrix. Invisible characters are excluded, ties use the original named-ID order deterministically.

The resulting audit records each image number, unchanged actor ID, projected screen-x/y, camera depth, source world head center and corresponding canonical image. This is **source blocking association, not face recognition, a full-body visibility certificate or occlusion resolution**. Different-depth heads can be close in screen-x, and a figure can be partly occluded.

The prompt explicitly assigns leftmost/middle/rightmost stage figures and their original clothing-marker colors to the actual numbered reference photographs. It retains each figure's body position and relative height. Skin, visible-architecture, eyes and bread-holder rules from v25 remain. It does not add more negative instructions.

## Actual prepared comparison

New run: `data/video_generation/spatial_minute_experiments_20261107_v1/stills_r3_screenorder_v26`.

- PLAN SHA: `7c56fc8a3a1625229dc1936d8346136fed1cd0537b0e8197f38c482daf74f927`.
- Canary BATCH SHA: `c73932d56a3465d962fba943f9f520b6a0053db386f34c98ea80aa915325a2c7`.
- S01_start references: stage; Su Mo (u≈0.4594); Ye Xijue (u≈0.5881); Ye Nan (u≈0.9381).
- S03_end references: stage; Ye Xijue (u≈0.4595); Su Mo (u≈0.4925); Ye Nan (u≈0.8223). The first two projected heads are only about0.033 of frame width apart; sorting alone may not disambiguate them.
- Native prepare/staging completed against actual source/canonical images. At handoff the new batch was prepared, native ID null. This agent made zero model POSTs.
- Global ledger had four previously generated images and two newly reserved images, **6/12 reserved**. The remaining five unique actor states would bring this to11/12. A new namespace did not reset earlier consumption.

Full prompt text is in `CANARY_PROMPTS_READING.md`; exact slots and projection provenance are in `PLAN.json` and `PROMPT_AUDIT.json`.

## Run only in root's GPU window

```powershell
.venv/Scripts/python.exe -B scripts/run_spatial_stills_v24.py execute --run data/video_generation/spatial_minute_experiments_20261107_v1/stills_r3_screenorder_v26 --batch canary --max-seconds 1800
```

Existing native-ID/unknown guards, source SHA checks, shared loaders/independent seeds, global budget audit and candidate-only output status remain. No candidate is promoted to an H3 guide without root actually reviewing the generated image. Root designated this as the final reference-packing comparison, not an unlimited still-retry loop.

## CPU verification

Final **32 unique tests passed**, 32.49s, zero failures/skips: `data/qa/spatial_stills_screen_v26_20261108.xml`. These include the prior27, not27+32. Added tests independently compare matrix-derived projections with the design projector, verify actual reference-slot order through the original file-staging graph, preserve seeds/states/render pixels and legacy prompts, reject invalid camera matrices and require a verified skin renderer for v26.

Runtime SHA: `3898572cdfae0e090693e59b700c66e01a07cf96c676fe17518fca41706ea30f`.

CLI SHA: `df5fa59e0ff01ef7d1bde592082452446ce5471bf509bb6ce152af9b529e090a`.

Production/semantic approval remains false. No services, accounts, old holds or H3 reference contracts were changed.
