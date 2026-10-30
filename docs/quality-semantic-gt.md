# Offline semantic GT for retained object observations

`src/neusymnav/evaluation/quality_semantic_gt.py` is evaluator-only. The `prepare`
command runs on the host CPU, reads SHA-bound committed Observation assets, and
writes portable source NPZ files. `render` runs directly under the existing
Habitat interpreter with `PYTHONPATH=src` and owns a separate, serial simulator.
Both stages use the current repository contract registry, included in the main
source freeze; the native stage lazily imports it before any Habitat import. No runtime module
imports it; semantic IDs/labels never enter the online graph or control path.

The primary scope is **visible semantic instances supported by the already frozen
taxonomy**, including its existing aliases. Doors and windows remain eligible.
There are no inherited structural exclusions or scene-specific aliases. A mask
needs at least 100 pixels, declared before rendering. Visibility uses the entire
semantic raster, without depth-masking it into an easier target. HM3D instance IDs
are preserved as `hm3d:<id>` across frames. The primary denominator excludes
background (-1/0/uint32-max), IDs absent from the descriptor, unsupported labels,
and masks below 100 pixels. Every excluded ID, original label, visible count and
reason is retained per frame in `alignment-exclusions.json`. Predictions are all
retained; predictions outside the GT scope can count as false positives. These
are scoped HM3D annotation metrics, not manually adjudicated whole-scene accuracy.

The recording manifest must bind the exact frozen capture config SHA for recorded
inputs. Config, scene geometry, scene dataset descriptor, semantic mesh, semantic
descriptor, taxonomy, exported prediction JSON and original source assets are
SHA-verified. Source episode, sensor, frame index, capture time, geometry hash,
image shape and coordinate/depth convention must match exported frame metadata.
The requested frame count is 1–12, preserving the export's fixed order.
Native preflight decodes each SHA-bound original source as a typed Observation;
the prepared NPZ RGB/depth/valid/K/pose must match its dtype, shape and exact C-order
bytes, including NaN payload bits. Merely hashing the original and the NPZ
individually is insufficient: reordered or rehashed arrays must be rejected.
Prepared frame metadata must equal the corresponding ordered prediction frame,
source descriptor SHA must equal that frame's source SHA, and primary camera
settings/HFOV/assets must match the verified frozen capture config.

Canonical optical poses convert using
`inverse(W_yup_to_zup) @ T_world_camera @ diag(1,-1,-1,1)`. The native renderer
uses zero local sensor offsets, the configured HFOV/near/far and exact source
width/height. All RGB/depth/semantic sensor poses must match the requested pose
within 1e-5 in the homogeneous matrix. Projection-derived K for **each actual
sensor** must match source K within 1e-8, including pixel-centre principal points.
The preliminary HFOV representability check allows focal anisotropy up to 1e-4
pixels because actual float32 GL projection gives fx319.99996185 and
fy319.99998093 for the native 640×480/90-degree camera. This does not relax the
actual rendered K comparison; rendering uses the frozen configured HFOV.

GT is accepted only after RGB and axial metre depth alignment. The prospectively
fixed policy requires at least 100 valid recorded depth pixels, finite positive
source depth, finite rendered depth, and at least 99.9% of those pixels within
`0.001 m + 0.0001 * source_depth`. RGB mean absolute byte error must be <=0.5,
and the 99th percentile absolute byte error <=3. Failure aborts publication of
the whole GT document. There is no auto-relaxation, quarantine-as-empty, or GT
annotation for a failed source. All per-frame alignment values are retained.

Output publication stages all frames and masks before creating the result
folder. Existing output folders are rejected. `ground-truth.json` follows the
existing quality dataset schema; masks are SHA-bound bool NPY. The sidecar and
manifest retain alignment, exclusions, input assets and implementation hashes.
Full-scene geometry, semantic surface completeness, all-semantic recall, online
association history, and detector AP from a low-score replay remain unproven.

Verification: new pure analytic tests exercise world/camera basis conversion,
malformed poses/calibration, RGB/depth mismatch and nonvacuous support, persistent
semantic IDs, complete excluded-pixel accounting, taxonomy aliases, door
inclusion, malformed annotation IDs, config provenance substitution and source
asset corruption. TDD logs and bounded native preparation are under
`runs/quality-evaluation-20261029/semantic/`. The main coordinator owns GPU launch,
full CPU integration, independent review and the shared implementation status.

Independent review found that the first implementation verified NPZ and original
source hashes separately, allowing valid arrays to be exchanged between frames.
The repair adds seven RED→GREEN cases for swapped arrays, changed primary,
reordered frames, changed frame metadata/source descriptor/HFOV and rehashed pose.
CPU verification under the actual sensor interpreter accepts the original
12-frame request and rejects both reviewer reproductions before Habitat imports.
This repair does not change the prospective RGB-D alignment or visibility policy.
