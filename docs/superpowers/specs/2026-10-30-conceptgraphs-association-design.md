# Association inspired by ConceptGraphs

Date: 2026-10-30. Status: user approved; implemented and correctness-verified.
Measured spatial-only pilot: unchanged quality; visual/native validation pending.
User selected integration into the existing canonical owner, retaining Hungarian.
This document authorizes no training, downloads, publication, or source-folder edits.

## Intent and baseline

Improve object identity across partial RGB-D views using the spatial/visual ideas
in ConceptGraphs, while retaining one canonical ID owner and durable alias handling.
Do not promise an improvement before a paired experiment. The existing pilot has
12 frames in one scene, detection recall15.91%, final IDF1 32.79%, HOTA33.81%,
AssA65.95%, and no eligible revisits. Association improvements cannot recover
objects that the detector never proposes.

The runtime already projects masks to world point clouds and fuses bounded3cm
voxel clouds (4096voxels/object). Association currently averages two directional
nearest-neighbor fractions over the first512points, plus centroid proximity and
AABB IoU. The measured demo has appearance disabled. The existing optional CLIP
worker and feature-space checks should be reused rather than replaced.

## Approaches and chosen boundary

1. Replace association with upstream greedy assignment: closer upstream behavior,
   but changes simultaneous-object handling and identity ownership assumptions.
2. Integrate ConceptGraphs-inspired spatial/visual scoring in the existing owner:
   chosen by the user. Retain Hungarian, ambiguity handling, cannot-link history,
   wall/floor/distance gates, episode isolation, ledger transactions and aliases.
3. Only enable the existing appearance mode: useful control experiment, but leaves
   the partial-view overlap issue and prefix sampling unchanged.

Main's implementation choices below are proposals, not user-specified thresholds.

## Reference and provenance

Local read-only reference:
`../3DSG/projects/Fusion_Concept_OccuSG/ref_ConceptGraph/concept-graphs/`
Git HEAD `8aca1172d2b9dab8e9db5c849268c060a39cfcd6`.
Pin the actual file bytes even if the checkout has local changes:

| File | SHA256 |
|---|---|
| conceptgraph/slam/mapping.py | 30be9f67f6237326240ffe8bd31c27a6ca431d6b35c5cf7d444c62fdb9d266ed |
| conceptgraph/slam/utils.py | 8015d5ac2ad539eb98bec057cc94d3c5b3d091850b4102a60faf58779845a712 |
| LICENSE | bbb50dd0e42f0180461db2088dc07e6374d3ad4fe6961167b07093000894a509 |

Official source inspected:
[mapping.py](https://github.com/concept-graphs/concept-graphs/blob/main/conceptgraph/slam/mapping.py),
[utils.py](https://github.com/concept-graphs/concept-graphs/blob/main/conceptgraph/slam/utils.py).
Upstream code combines directional cloud overlap with raw cosine similarity,
using a physical bias. Its paper's remapped visual score differs from this code.
Upstream also has bounding-box prefilters, denoising and greedy fusion. Our
implementation will explicitly document differences and will not claim exact
ConceptGraphs reproduction. Preserve MIT attribution for adapted code.

## Scoring and geometry

Introduce an explicit opt-in `conceptgraphs` association recipe. Legacy modes
retain their current results and remain the default until quality is measured.
Use the existing world-Z-up metric cloud; no additional sensor or new GT input.

Spatial score is the fraction of sampled new-observation points whose nearest
map-cloud neighbor is strictly closer than a metric tolerance. Use an exact
SciPy cKDTree over the complete bounded map cloud, with deterministic voxel
sampling of each observation rather than an arbitrary point prefix. Sampling
is canonical-order independent, at3cm, capped4096points; any cap is declared.
Initially use a3cm distance tolerance, consistent with the existing fusion grid;
expose it as a validated recipe parameter. This is an adaptation, not an upstream
default (the reference base voxel size is2.5cm).

When compatible visual features exist, use
`raw = (1 + physical_bias) * spatial + (1 - physical_bias) * cosine`.
Start with physical_bias0 and normalized assignment utility `raw / 2`.
Thresholds use this explicitly documented scale: initial utility threshold .55
(raw1.10) and ambiguity margin .08. These are untuned candidates. Reject spatial
score below .10 in visual mode so appearance alone cannot join disjoint objects.
All existing floor/wall/centroid-radius/AABB-distance gates remain before scoring.
This retains the current1.5m maximum candidate radius and its known limitation
for large objects viewed from opposite ends.

For mixed feature availability, select one scoring policy per observation row
before Hungarian/ambiguity comparison: if the observation or any geometrically
eligible candidate lacks an embedding, score every eligible candidate in that
row with directional overlap alone, using threshold .55. Otherwise score every
candidate with raw/2. Never mix an unhalved spatial-only value with spatial-plus-
visual utilities in the same row: missing appearance must not double a candidate's
weight. Count row fallback and its reason; do not manufacture a cosine value.
This conservative policy can discard useful visual information when one local
candidate lacks features, an explicit limitation to measure in the ablation.
If embeddings exist but have incompatible
dimensions or feature spaces, reject through existing validation. Feature-space
identity remains pinned at the owner boundary. This fallback means a run with
appearance disabled is not a test of the full spatial-plus-visual method.
The graph coordinator currently attaches encoder results before owner.commit;
reuse that ordering. Late appearance attachments update future scoring only:
they do not retroactively revise an assignment or bypass canonical merge rules.

Continue existing bounded voxel fusion and count-weighted normalized visual
fusion. No unbounded cloud concatenation, ICP pose corrections, automatic
background removal, DBSCAN or post-hoc cross-ID merge in this first change.
Those are separate ablations because they can remove thin/disconnected objects
or increase false merges. Geometry preparation and scoring stay on the graph
lane; motion must not wait for them.

## Configuration, durability and observability

Wire the recipe from validated runtime configuration through ObjectOwner into
AssociationEngine; fork and recovery retain it. Persist a versioned recipe with
all scoring parameters in ledger metadata. Legacy ledgers opened in legacy mode
continue to work; changing recipes on a populated ledger fails explicitly and
requires a new episode/output directory. No silent rescoring of historical IDs.
Provide a runnable opt-in profile using existing local assets if available;
missing CLIP assets produce an explicit preflight limitation, not a download.

Persist bounded per-batch diagnostics: recipe ID, number of candidates, matches,
new IDs, ambiguous observations, visual/spatial-only scored pairs and cloud
sampling/cap counts. Include these in the measured experiment report. Do not
change the event digest or checkpoint representation without migration tests.
Record online assignment endpoints before alias rewriting in the experiment
artifact so online/final metrics can be distinguished; do not relabel existing
final-only history as online.

## Verification and experiment

Tests must cover partial containment, shuffled cloud order, thin/planar clouds,
strict distance boundaries, orthogonal/negative/missing visual features, nearby
same-class objects, ambiguity, one-to-one assignment, cannot-link/floor/wall gates,
fork rollback, restart and recipe mismatch. Use independent small-cloud distance
oracles. Existing legacy-mode parity tests must remain unchanged and pass.
Include mixed-availability regression: candidateA overlap .8/cosine .5 and
candidateB overlap .75/absent embedding must be compared spatially (.8 vs .75),
not by mismatched .65 vs .75 utilities.

Replay the same retained source-ordered observation clouds/detections through
legacy geometry, existing geometry+appearance and the new recipe. Visual modes
use identical features; if no verified cached/local encoder is usable, report
the appearance comparison unavailable and still verify the geometry ablation.
No native navigation rerun is needed to compare identity on fixed inputs.
GT belongs only to a separate offline evaluator and never to the matcher.

Report exact frame/detection denominators, projection losses, online and final
IDF1/HOTA/AssA, duplicates, false merges/splits, ambiguity and runtime/memory.
Keep all frames and GT when detections fail. The original21-output detector
baseline remains distinct from17identity-bearing memory observations.
Do not tune on this pilot and then call it a held-out improvement. Additional
scenes, occlusion/revisit sequences and a held-out split are required before
promoting the recipe to default. No eligible revisit means unavailable.

Completion states: implemented; correctness-verified after fresh relevant/full
CPU checks and independent Sol High review; runtime-validated only for actually
executed profiles. No P10, broad quality gain or realtime claim from unit tests.

## Other quality improvements to recommend, not implement in this task

1. Audit taxonomy and source masks, particularly table/dining-table, missing doors
   and windows. Any aliases get a new vocabulary version and both old/new scores.
   Door/window are already present in taxonomy-v1; adding their existing names
   again is not a fix. Inspect model outputs and confidence/class confusion.
2. Fixed-image detector replay with a declared low confidence floor and adequate
   detection cap; compare PR curves and bbox/mask AP before selecting production
   thresholds. Increasing recall can increase false positives.
3. Compare existing local detector checkpoints/resolutions on the same images;
   report throughput/VRAM as well as per-class AP. New models require separate
   downloads authorization. Higher resolution is an experiment, not a guarantee.
4. For low localization quality, audit mask resizing and boundaries; test higher
   resolution/refinement before fusion, with retained unrefined controls.
   The current adapter already sets `retina_masks=True`, so enabling that flag
   again is not an improvement. It also only permits imgsz480/512/544/640 and
   max30detections; larger-image/cap experiments require an explicit offline
   recipe change rather than editing a production guard unnoticed. Supported
   prediction controls are documented by
   [Ultralytics](https://docs.ultralytics.com/modes/predict/).
5. For3D errors, inspect depth-edge contamination and sampling/caps, then ablate
   depth-consistent filtering and robust outlier rejection. Current shared-depth
   GT proxy cannot certify sensor/pose accuracy or full unseen object geometry.
   Projector already has a median depth-component and MAD filter. Audit what it
   drops, especially the four unassigned detections, before adding another filter
   that could lower recall or remove valid parts of elongated objects.
6. Expand evaluation across scenes and deliberate revisits with fixed splits;
   only after evidence identifies residual class/domain gaps consider fine-tuning.
