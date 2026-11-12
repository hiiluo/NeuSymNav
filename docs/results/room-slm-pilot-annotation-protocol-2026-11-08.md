# Room SLM pilot annotation and evaluation protocol

Status: frozen protocol; no human annotation set has been completed. A partial
AI-agent visual draft is recorded at
`runs/room-slm-pilot/S1/annotations/image-reviewed-room-labels.json` (7 room
candidates, 3 scenes, 1 eligible sample). It is not human-reviewed and is not
evidence of room-label accuracy.

## Annotation unit and source evidence

- The independent sample is one **physical room instance in one scene**. Give it
  a stable `physical_room_id` that groups its native Hydra room IDs across graph
  revisions. A split or merge is annotated as a geometry event and reviewed
  separately; it does not create extra semantic samples.
- Review primary RGB-D imagery from the frozen run and, where needed, a
  reviewer-approved scene view. Record the evidence asset hashes and the
  annotation tool/reviewer/version. Never use the model proposal to decide the
  reference label.
- Assign one or more canonical labels from the pinned taxonomy, or `unknown` if
  the scene does not support a defensible label. Use multiple labels only for a
  real mixed-use physical room. Record `insufficient_visual_evidence` separately
  from an `unknown` room.
- Annotate geometry separately: `geometry_ok`, `merge`, `split`, `wrong_extent`,
  or `uncertain`, with regions or object IDs where review can support them.
  Geometry mistakes do not become semantic-label errors by implication.
- For each semantic object used as support, review whether its native ID maps to
  the visible object and mark `confirmed`, `uncertain`, or `not_reviewed`.
  Annotation labels never enter the model prompt or runtime graph.

## Frozen manifest fields

One record per physical room contains `physical_room_id`, `scene_id`,
`episode_id`, `source_run_id`, `native_room_ids`, `reference_labels`,
`reference_status`, `geometry_review`, `evidence_asset_sha256`,
`annotation_sha256`, `reviewer_id`, `annotation_version`, `split` (`dev` or
`heldout`), eligible support object IDs, and the selected exact prediction's
`context_hash`, `graph_revision`, `model_sha256`, `prompt_sha256`, and
`schema_sha256`. Store graph/input-prefix hashes and the run/room identity needed
to reproduce the snapshot. Freeze and hash the manifest before prompt tuning.

Require at least 12 physical rooms across at least 3 scenes for a minimally
informative pilot. Keep scenes wholly in dev or heldout. If fewer are available,
report a small pilot and do not claim the gate passed. Multiple revisions of a
room are history for flip/staleness analysis, not additional samples.

## Scoring and reporting

- Compare the versioned rule baseline and SLM using identical frozen contexts.
  Report both overall coverage and selective accuracy at comparable coverage.
- Report label-set-supported macro F1, the label confusion table, abstention
  reasons and denominator, invalid-output rate, hallucinated support IDs,
  distinct-context label flips, geometry unavailability, and results per scene.
- Report p50/p95/max inference latency and peak process RSS, plus host available
  memory and swap when measured. Mark missing measurements as unavailable.
- Score semantic quality only for eligible, visually reviewed samples with
  usable context. Report geometry-review outcomes alongside the semantic scores,
  never folded into the same accuracy figure.
- Evaluate heldout once after the prompt is frozen. Any subsequent prompt change
  turns heldout into development data and requires a new heldout split.

## Decision gate

For the reviewed eligible subset, propose the SLM for shadow integration only if
accuracy is at least 80% at coverage of at least 50%, it is no worse than the
rule baseline at matched coverage, invalid output is zero in the evaluated
sample, supporting IDs are valid, and resource goals are met. These are review
gates, not statistical guarantees. Insufficient sample count, annotation, model
assets, or comparable-coverage evidence means **inconclusive**, not pass.

The 00805 frozen graph snapshot currently has native semantic object IDs and
membership, but no reviewed visual object associations or room annotations. It
can exercise request construction and baseline behavior only; it cannot score
semantic room-label quality.
