# ConceptGraphs-inspired association

This opt-in recipe uses directional world-cloud overlap and optional visual
cosine similarity inside NeuSymNav's existing object owner. It retains Hungarian
assignment, ambiguity handling, cannot-link history, canonical aliases and
transactional commits. It is an adaptation, not an exact ConceptGraphs replica.

## Enable the recipe

Add an explicit top-level mapping to a runtime configuration:

```yaml
association:
  mode: conceptgraphs
  nn_distance_m: 0.03
  voxel_m: 0.03
  max_points: 4096
  physical_bias: 0.0
  match_threshold: 0.55
  ambiguity_margin: 0.08
  min_spatial: 0.10
```

All parameters are included in a versioned durable recipe. Omitted association
means legacy behavior. A populated ledger cannot be opened under a different
recipe; start a new episode/output directory for a comparison. Existing legacy
ledgers without this metadata remain readable in legacy mode.

The local-asset profile
`configs/p10/demo-yoloe26m-conceptgraphs-gpu-00861.json` selects this recipe with
appearance off, making it a spatial-only ablation. Run from the repository root:

```bash
PYTHONPATH=src .venv/bin/python -m neusymnav.cli preflight \
  --config configs/p10/demo-yoloe26m-conceptgraphs-gpu-00861.json
PYTHONPATH=src .venv/bin/python -m neusymnav.cli run \
  --config configs/p10/demo-yoloe26m-conceptgraphs-gpu-00861.json \
  --duration-s 30 --out runs/conceptgraphs-new-episode
```

The profile does not change the existing demo launcher's default. Preflight
success checks assets and interpreter readiness, not native quality or speed.

## Geometry and visual behavior

Projection already provides metric Z-up world clouds from exact-source RGB-D.
The scorer voxel-samples observations deterministically and queries the complete
bounded object cloud, using the fraction strictly closer than `nn_distance_m`.
It does not average the reverse fraction: a small partial view need not cover
the whole accumulated object. Legacy scoring retains its own original behavior.

With compatible features, raw score is
`(1 + physical_bias) * overlap + (1 - physical_bias) * cosine`.
Assignment utility is raw/2, so threshold .55 means raw1.10 at the default bias.
Visual rows require overlap at least .10. If an observation or any candidate
passing geometry gates lacks a feature, the whole observation row falls back to
spatial-only utility=overlap. Missing features never compete on an incompatible
scale within a row. This can discard useful visual evidence, and cross-row
utility calibration remains empirical. No threshold has been tuned on the pilot.

Floor/wall/centroid-radius/AABB-distance gates still apply. The1.5m maximum
candidate radius remains a limitation for large objects seen from opposite ends.
Geometry is fused with the existing bounded voxel means. There is no new ICP,
automatic cross-ID merge, unbounded concatenation or DBSCAN step.

Visual features use the source/feature-space-checked appearance lane. The complete
local-asset path now uses `appearance_mode: openai_clip`, explicit
`checkpoint_format: openai_jit`, ViT-B-32 and the versioned
`openai-clip-vit-b-32-eval-224-maskbboxpad20-v1` preprocessing recipe. The worker
checks the local checkpoint hash/architecture, loads TorchScript on CPU without a
pickle fallback or download, and records the installed CLIP implementation and
transform hashes. It extracts normalized512D vectors from padded source RGB/mask
crops. Existing OpenCLIP safetensors recipes remain separate feature spaces.
Late feature attachments affect future comparisons only; earlier IDs are unchanged.

Run the complete visual profile from the repository root:

```bash
bash tools/run_conceptgraphs_demo.sh --preflight
bash tools/run_conceptgraphs_demo.sh 300
```

This selects `configs/p10/demo-yoloe11s-conceptgraphs-visual-gpu-00861.json`
(YOLOE-11s640/confidence.30, selected by the subsequent detection experiment).
It uses the existing read-only sibling ViT-B-32 checkpoint and installed `clip`
package in `.runtime/detector26`; no package/model download was required. The
installed package is an Ultralytics fork, and its actual source hashes are pinned;
it is not represented as an unchanged upstream OpenAI implementation. The earlier
missing OpenCLIP/safetensors asset does not block this explicitly distinct backend.
The user explicitly selected CG + Visual as the main demo association; both
`tools/run_gpu_demo.sh` and this wrapper select it. The earlier spatial profile
is an ablation. Legacy remains available as an explicit algorithm baseline.

## Audit and evaluation

New-mode batch records persist recipe, bounded scalar association diagnostics,
ordered detection IDs and original online object IDs in the same transaction as
the commit. Later merges retarget canonical evidence endpoints but leave this
batch history intact. A failed transaction publishes neither state nor diagnostic
records. Existing event digests and checkpoint shape are unchanged.

Use fixed-input replay and the separate offline evaluator to compare algorithms.
The matcher must not see semantic GT. Keep detector outputs distinct from the
projected-memory scope and retain all frames/GT for the chosen scope. Measure
IDF1, HOTA, AssA, ambiguity, false merges/splits and cost; add deliberate revisits
and held-out scenes before considering this recipe as a default.

Design/provenance: [approved design](superpowers/specs/2026-10-30-conceptgraphs-association-design.md).
Implementation evidence and measured results:
[fixed-input experiment](results/conceptgraphs-association-2026-10-30.md).
The earlier12frame spatial-only pilot was unchanged. The completed real visual
comparison on all79frames now improves AssA29.45→42.43% and HOTA22.28→25.51%
relative to CGspatial, but unresolved observations increase29→36. See the
[visual completion report](results/conceptgraphs-visual-completion-2026-10-30.md)
for four-mode metrics, denominators, native proof and limitations. The recipe
remains opt-in.

Detector selection and measured tradeoffs: [detection improvement](results/detection-improvement-2026-10-30.md).
