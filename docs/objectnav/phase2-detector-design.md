# ObjectNav phase 2 — detector measurement on goal categories (design, 11/11/2026)

Branch `objectnav`. No locked file changes: the detector (`perception/*`, taxonomy, YOLOE-26m OpenVINO model) stays exactly as in `baseline-3dsg-v11`. Phase 2 only measures it.

## Question to answer

For each ObjectNav goal category, at the distances and viewing angles the robot will actually have:

1. How often is a visible goal object detected (recall), and how does that fall with distance?
2. How often does the detector report the category where there is no goal object (false positives per frame), and on what does it fire? This bounds false STOPs.
3. Which confidence threshold and confirmation rule should B0 use?
4. What SR ceiling does the detector alone impose per category?

## Ground truth: the episode's own goal objects

Positives are the object instances listed as goals in the episode files (`goals_by_category[...].object_id` = HM3D semantic instance id), not a name match on `semantic.txt`. This is the definition the scorer uses, so label ambiguity (armchair vs chair, tv vs monitor) cannot bias the result. Every other instance is a negative for that category; its `semantic.txt` name is kept only to explain false positives.

Category mapping (detector label → goal category), fixed before looking at results:

| Goal category (HM3D, 6) | Detector labels counted | Note |
|---|---|---|
| chair | chair, armchair | reported jointly and separately |
| bed | bed | |
| plant | plant | |
| toilet | toilet | |
| tv_monitor | television | `computer monitor` reported apart as a near-miss |
| sofa | sofa | |

MP3D's 21 categories get a draft mapping table in the same file but are measured in phase 6.

## Pipeline: three steps, three interpreters, files in between

| Step | Interpreter | Tool | Output |
|---|---|---|---|
| 1. Sample views | Habitat | `tools/objectnav/detector_eval/sample_views.py` | `frames/<id>.npz` (RGB, depth, semantic ids, pose, K) + `views.jsonl` |
| 2. Run detector | detector env (`.runtime/detector26`) | `tools/objectnav/detector_eval/run_detector.py` | `predictions.jsonl` (label, score, mask RLE) at confidence floor 0.01, max 100 detections |
| 3. Score | project venv | `tools/objectnav/detector_eval/score_detector.py` | `report.json`, `report.md`, PR curves |

Step 1 uses the annotated scene config and is evaluator-only. Step 2 sees RGB only and uses the runtime `YoloeDetector` class with the same pinned assets and backend (OpenVINO GPU, imgsz 640), so numbers describe the detector the robot runs. Step 3 reuses `evaluation/detection_quality.py` for IoU matching and AP.

## View sampling (dev scenes only)

Scenes: the 6 dev scenes of the frozen split. Test scenes are never sampled.

Camera: the runner's primary sensor (640×480, hfov 90°, 1.2 m above the body origin), body on the robot navmesh (r 0.20 m, h 1.5 m).

Two view sets per scene:

- **Path views** (what the robot sees while searching): for each dev episode, poses every 0.5 m along the navmesh shortest path from start to goal, heading along the path, plus headings ±45°. About 20–40 poses per episode.
- **Scan views** (what a 360° look-around sees): at 40 random navigable points per scene, 12 headings at 30° steps.

Budget: about 2,500–4,000 frames in total; deduplicated by pose. A goal instance counts as visible in a frame when it covers at least 100 pixels (the existing `MIN_VISIBLE_PIXELS`); smaller ones are ignored, neither hit nor miss.

Sanity check before trusting GT: for 20 frames per scene, depth rendered with the annotated config must match depth rendered with the runtime basis config (existing `ALIGNMENT_POLICY`).

## Metrics

Per goal category, at confidence thresholds 0.05–0.60:

- **Frame recall** by distance bin (0–1.5, 1.5–3, 3–5, > 5 m) and by visible-pixel bin; mask IoU ≥ 0.5, and also a looser "any overlap ≥ 0.1" hit, because B0 only needs to localise the object, not segment it.
- **Instance recall**: fraction of goal instances detected in at least 1 and at least 3 of the frames where they are visible within 3 m.
- **False positives per 100 frames** on frames with no goal instance of that category, and the list of what they fire on (semantic name of the dominant instance under the predicted mask).
- **Persistence of false positives**: fraction of false detections that repeat on the same instance from ≥ 3 different views. This is what a multi-view confirmation rule cannot remove.
- Precision–recall curve and AP (COCO-style subset already implemented).

Derived outputs:

- Recommended confidence threshold per category (highest recall with persistent false positives per scene ≤ 1), and whether one global threshold is good enough.
- Recommended confirmation rule for B0 (N detections from views at least X degrees apart).
- Detector-only SR ceiling per category: share of dev episodes whose goal instances are detected from at least one path view within 3 m.

## Deliverables and done criteria

- `docs/objectnav/phase2-detector-results.md`: the tables above, PR plots, the chosen threshold and confirmation rule.
- `configs/objectnav/goal-categories-v1.json`: the frozen mapping.
- Tests: mapping loader, visibility rule, scorer on synthetic frames (known recall and false-positive counts), RLE round trip.
- Done when the three steps run from one script on the user's machine, the alignment check passes, and the report exists for all 6 categories.

## Open points

1. Only `yoloe-26m-seg.pt` is on the machine; the earlier 11s comparison (F1 36.6 % vs 24.4 %) used a model that is no longer in `local-assets/models`. Comparing models needs a download approved by the user; default is to measure 26m only.
2. A threshold below the runtime's 0.25 would need a runner config change (not a locked file) and costs detector time; decided from the PR curves.
3. Stairs and other floors: path views stay on the episode's start floor, matching B0's first scope.
