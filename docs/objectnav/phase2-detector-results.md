# ObjectNav phase 2 — detector results (11/11/2026)

Detector = the runtime one, unchanged: YOLOE-26m-seg, OpenVINO on Intel UHD (iGPU), imgsz 640, taxonomy-v1 (59 prompts), max 30 detections, confidence floor lowered to 0.01 for the offline curve. Mapping `configs/objectnav/goal-categories-v1.json` (frozen before results). Design: `phase2-detector-design.md`.

Data: 6 DEV scenes of the frozen split, 4,170 frames (1,763 path views along the shortest path of the 60 dev episodes, 2,407 360° scan views), robot camera (640×480, hfov 90°, 1.2 m). Alignment annotated vs runtime render: 20/20 in every scene. Goal object ids match their semantic names (chair goals are named chair / armchair / dining chair / sofa chair; plant goals include flower vase / flowerpot / flower).

## Main result: the detector is a large SR bottleneck, and mostly through naming, not seeing

Frame recall (IoU ≥ 0.1 with a visible goal object) at the runtime threshold 0.25:

| Category | Frame recall | Precision (IoU ≥ 0.5) | False positives / 100 frames | What it says instead on missed goal views (score ≥ 0.25) |
|---|---|---|---|---|
| bed | 0.76 | 0.56 | 7.7 | bench, desk, storage box |
| toilet | 0.58 | 0.74 | 0.4 | stool, bathtub |
| sofa | 0.55 | 0.48 | 12.1 | bench, bed, pillow |
| tv_monitor | 0.43 | 0.47 | 3.4 | mirror, painting, oven |
| chair | 0.41 | 0.75 | 5.1 | sofa 327, bench 255, pillow 168, stool 135 |
| plant | 0.02 | 0.81 | 0.02 | vase 184, coffee table, desk, bowl |

Wrong objects detected as the goal at 0.25: chair ← window (138); sofa ← armchair (296), chair (149); bed ← cabinet (61), couch (60), chair, armchair; tv_monitor ← picture, plus "led tv" objects that the episodes do not list as goals (likely unlisted TVs: counted as false positives here, so tv_monitor false positives are overstated).

## Instance-level confirmation rule chosen for B0 (`configs/objectnav/b0-detection-v1.json`)

Recall = goal instances confirmed / goal instances seen within 3 m; wrong = non-goal objects confirmed per scene (each is a place where B0 could STOP wrongly).

| Category | Threshold | Min views | Vote | Recall | Wrong / scene | Goal instances (dev) |
|---|---|---|---|---|---|---|
| bed | 0.50 | 3 | yes | 0.94 | 1.33 | 16 |
| chair | 0.50 | 2 | no | 0.68 | 1.00 | 85 |
| plant | 0.25 | 1 | no | 0.16 | 0.17 | 45 |
| sofa | 0.50 | 3 | yes | 0.76 | 2.83 | 17 |
| toilet | 0.35 | 2 | no | 0.69 | 0.00 | 13 |
| tv_monitor | 0.50 | 2 | no | 0.62 | 1.00 | 8 |

A single global threshold does not work: toilet is clean at 0.35, while bed and sofa still confirm 1–3 wrong objects per scene at 0.50. The vote (category must win among goal labels on that object) only pays for bed and sofa; for chair it costs recall because many real chairs are also called sofa.

Rough detector-only SR ceiling on the TEST category mix (bed 39, chair 36, sofa 33, plant 32, tv 22, toilet 18 episodes): Σ recall × share ≈ **0.65**, before exploration, approach and wrong stops. Plant alone costs about 15 SR points.

## Levers for later (phase 5, decided from B0's failure table)

1. **Plant vocabulary** (largest): HM3D "plant" includes flower vases and flowerpots; prompt only "plant". Options: map `vase` → plant (cheap, a v2 mapping, must be re-validated on dev then test), or add prompts such as "potted plant", "flower vase", "houseplant".
2. **Seating confusion** (sofa ↔ armchair ↔ chair ↔ bench): goal-specific prompt sets or a verification step when close.
3. Prompt changes need a new OpenVINO export (class names are baked into the IR) or the Torch CPU backend, and a new baseline lock (perception group).

## Caveats

- Views are sampled offline (path + scan), not the frames B0 will see; instance counts are small for tv_monitor (8) and toilet (13).
- 2,627 frames hit the 30-detection cap at the 0.01 floor; curves below about 0.15 may be slightly low. Thresholds ≥ 0.25 are unaffected in practice.
- "Unlisted" same-category objects are recognised only by exact semantic name (68 chair detections); synonyms such as "led tv" are not, so some false positives are real objects of the category that the dataset omitted. Stopping at them still fails the episode.
- Thresholds were chosen on dev; the test split has not been touched.
