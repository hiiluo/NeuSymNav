# Offline object quality evaluation — 2026-10-29

User authorized implementation of the preceding three-level metric proposal.
This additive evaluator does not change runtime contracts, thresholds, control,
or the in-progress motion work. GT remains offline. No installation, training,
asset download, publication or new GPU campaign is implied.

## Approach and scope

Extend the existing pure offline helpers with versioned, source-bound prediction
and annotation JSON, CPU detection/geometry/identity metrics, JSON/Markdown reports,
and a read-only committed-ledger exporter. Prefer this to adding GT to Habitat
runtime or inferring accuracy from final object counts. Reuse stored evidence;
full model AP requires a separate prospectively fixed low-score detector replay.

Detection: confidence operating-point P/R/F1 and class-wise bbox/mask 101-point
AP at IoU .50:.05:.95. This is the ordinary non-crowd/non-ignore subset, not the
complete official COCO evaluator; supply prediction score floor and caps.
Geometry: label-independent one-to-one matching; volume and footprint IoU,
precision/observed recall, duplicates, AABB-center error, optional observed-surface
point-cloud P/R at a declared metre tolerance. Never equate partial observations
to full unobserved object surfaces.
Identity: observation-level IDF1, conditional pair precision/recall, merge/split
pairs, switches, visible fragmentation, absent-frame revisit recovery. Report
online and final aliases separately. Ledger IDs are rewritten on merge, hence
ledger export supports final memory only; online identity cannot be reconstructed.
HOTA/AssA are provided by a separate independently implemented, reference-pinned
TrackEval sequence algorithm: class-agnostic bbox IoU, 19 alpha thresholds,
global soft alignment then frame Hungarian before alpha filtering. Colliding
final IDs within a frame are unavailable rather than silently deduplicated.

## Input and provenance

Two JSON files, schema_version=1, same binding: scene_id, episode_id,
recording_sha256, taxonomy_sha256, coordinate_convention=canonical_z_up_m_v1.
Both list the same ordered frame_id/source_sha256/geometry_hash/frame_index/
capture_monotonic_ns/width/height. GT frames declare annotated=true and objects;
empty annotated frames mean true negatives. Unannotated frames fail evaluation,
never masquerade as empty GT. Prediction frames declare status=complete|partial|
failed|missing; absent predictions count as empty and the report retains status.
objects: id, label, bbox (pixel half-open xyxy); predicted objects also score and
optional identity. Optional masks are boolean rasters or SHA-bound npy references.
Optional geometry lists bounds/points under geometry_objects, and scope_gt_ids on
GT declares object-count scene coverage. Thresholds are evaluator arguments.

Top-level provenance includes kind=synthetic|recorded, description; predictions
declare identity_semantics=online|final_canonical_only|none, score_floor and
max_detections (null means unknown). final_aliases optional. No GT label/identity
is inferred from predictions. Missing genuine GT yields preparation artifacts
and an explicit blocker, never a synthetic score presented as measured quality.

## Verification

TDD independent perfect/missed/duplicate/wrong-label/split/merge/alias/occlusion
oracles; reject source mismatch, unannotated GT, malformed/nonfinite data, cycles.
Fresh independent Sol High review on frozen new files. CPU integration plus
synthetic CLI report, native ledger extraction if safe. Existing runtime dirty
files remain owned by their current writers; no full-head certificate while
unrelated edits are active.
