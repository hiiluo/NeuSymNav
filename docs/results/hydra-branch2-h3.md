# Hydra branch2 H3 — semantic raster, objects and rooms

Date: 2026-11-04. Worktree: `Kiet_branch2`. Native source: Hydra
`2e58a35baea629eee8838409771876acff015daf`, Spark-DSG
`3c40997e4ae739c56ed3cdd6ef5e882d403d8b64`.

## Implemented

- `HydraLabelRasterizer` consumes the already-produced `DetectionBatch`; it never
  starts inference. It validates source frame, geometry hash, image dimensions and
  vocabulary before rasterizing.
- Pixels use deterministic score-descending, detection-ID-ascending precedence.
  Unknown masks claim pixels as semantic label `0`; unmasked measured background
  remains `0`; invalid depth overrides all masks to label `1`. Taxonomy categories
  use IDs `2..60`, so unknown and invalid labels cannot enter `object_labels`.
- The generated Hydra labelspace follows the pinned native schema, carries the
  taxonomy provenance and a canonical SHA256, and is checked against the committed
  config. Each `HydraFrame` now carries the labelspace ID/hash as source provenance.
- The selected pipeline config uses the custom labelspace and existing Habitat
  reconstruction/GVD/room stages. No GT room labels or semantic floor labels enter
  runtime data.

Pinned labelspace SHA256: `910722d17a2f3a5999658dff44e4ce2a5d3b6b1a15332b5e9527ea2b3f84e537`.
Taxonomy source is `configs/taxonomy-v1.json` (`neusymnav:taxonomy:v1`).

## Verification

- RED then GREEN: label raster tests cover order-independent overlap ties, unknown
  class precedence, invalid-depth override, empty detections, pinned config parity,
  and wrong-frame rejection.
- CPU command: `.venv/bin/python -m pytest tests/test_hydra_labels.py
  tests/test_hydra_contracts.py tests/test_hydra_input.py tests/test_contracts.py -q`
  — **125 passed**, exit 0. `git diff --check` — exit 0.
- Native unknown-background geometry probe: four accepted empty-detection frames;
  label 0 remains measured geometry and yields a reloadable 718-vertex / 1,000-face
  mesh. A stable 20×20 invalid-depth patch is NaN at the binding and has zero mesh
  vertices projected into its one-pixel-interior region. Labelspace ID/hash are
  recorded in the result.
- Native same-class object gate: two disjoint predicted chair masks (1,320 pixels
  each), box centers 1.0 m apart, Habitat `min_cluster_size=40` and
  `cluster_tolerance=0.25 m`. Hydra creates `O(0)` and `O(1)`; eight repeated frames
  retain exactly two object nodes. The graph reload contains both nodes. The selected
  RGB-D/mask/label/pose/timestamp prefix is saved beside the graph.
- Native open-space room gate: 28 views of an 8×6×2.5 m space produce 77 place nodes,
  one room and one building; graph reload preserves all layers.
- Native narrow-connection gate: 28 views of two 4×6×2.5 m spaces joined by a 0.7 m
  opening produce 83 place nodes, two rooms and one building; graph reload preserves
  all layers. Both room fixtures use the same unmodified Habitat thresholds.

Effective frozen Habitat settings: voxel `0.1 m`, TSDF truncation `0.3 m`, full
update separation `1.0 s`; mesh resolution `0.005 m`; GVD `min_distance=0.2 m`,
`max_distance=4.5 m`, `min_diff=0.1 m`; room finder dilation `[0.5, 1.2] m`,
`min_component_size=10`, `min_room_size=10`, `PLATEAU`, `plateau_ratio=0.25`.
Room layer is Spark-DSG layer 4; place layer 3; building layer 5.

## Artifacts and evidence levels

Native inputs, logs, JSON summaries, and `.sparkdsg` graphs are in the ignored
`.runtime/hydra_ws/artifacts/h3-*` directories. Native commands were run with the
branch2 child environment and `PYTHONPATH="$PWD/src:$PYTHONPATH"`; each probe exited
0. The object test prefix is `artifacts/h3-same-class-objects/input-prefix.npz`.
The result JSONs and source probes include the exact view poses, masks, thresholds,
per-step accepted state, node counts, and graph reload counts.

| Artifact | SHA-256 |
| --- | --- |
| CPU test log | `7d6dc77a5707bbf56eab19bb409f9a73fdd54c6c21acd379841e2b2db295df0f` |
| Native unknown geometry graph | `e483c51e3aeb38af5efc0a863c6b9d4a60783e046b96571cff0ff21c8b7d992d` |
| Same-class objects input prefix | `f49b2fe9ce20e6e319859c546fbd180d1d7566ad00bd677e3fb27f405868af4a` |
| Same-class objects native graph | `b0545f3f3598899c54b2886d430f810dd691462e1c1c5c14ab9d183e852ee33c` |
| Open-room native graph | `54d668c7aa9376b5fdc95a9b5b42153787433a4a66f8aa21c8beecc9fbd53974` |
| Two-room native graph | `ff7c45bd497d61230f1ad947857f90debb705a5af044fb58a9fcb99aff5e8fb8` |
| Generated labelspace config | `ff1eb56f2bd402839c835ac5e53fc7bbd09ff2d3fe142c618e3f596e668b0075` |

**Implemented:** deterministic rasterizer, native labelspace config, labelspace
provenance fields, and test fixtures.

**Correctness-verified:** 125 focused CPU tests and all four native gates above
(unknown background/invalid patch, same-class objects, one open room, two connected
rooms).

**Runtime-validated:** these are native Hydra binding/pipeline fixture runs only.
NeuSymNav worker lifecycle/admission, real YOLOE inference reuse in the running
coordinator, UI/export integration, live navigation, and A/B remain unverified and
belong to H4–H7.
