# Room SLM pilot — 2026-11-08

## Decision

**The offline pilot is implemented and real inference was exercised, but it has
not passed the quality or resource gates. Do not add the asynchronous worker or
connect UI/live yet.** The available data yields seven image-reviewed room
candidates across three scenes, below the required twelve. Only one candidate is
eligible for semantic scoring, and that request timed out. The five real model
calls produced three timeouts and two invalid outputs; none produced an accepted
room label.

## Image and annotation evidence

- `runs/room-slm-pilot/S1/annotations/image-reviewed-room-labels.json` contains
  seven visual room candidates in 00805, 00806, and 00807. Each binds to run,
  graph revision, native room ID, frozen request/context where available, RGB-D
  frame hash, object association audit, overlay hash, and an annotation hash.
- This is an **AI-agent visual draft**, not human-reviewed ground truth. Six of
  seven rows are excluded from semantic scoring: 00805/00806 native `R(0)`
  combines visually different spaces; the 00807 bathroom is from a run whose
  outer run certificate is incomplete; and one 00805 object category is visibly
  wrong. Only the complete 00807 living-room row is eligible. Its SLM call
  timed out.
- Geometry projection was checked against captured depth and RGB overlays. It
  is only candidate support evidence: it does not establish detector category
  correctness or physical room membership. Manual review found `O(0)` in 00805
  labeled `bed` projects onto a sofa; `O(21)` labeled `wardrobe` projects onto a
  door. The reviewed bathroom anchors (`sink`, `bathtub`, `mirror`) and selected
  00806/00807 anchors visually align. Full per-object status is recorded in the
  annotation manifest and `S1/dataset/*/association-audit.json`.
- Distinct graph revisions are not counted as additional rooms. Repeated
  contexts for merged regions are excluded. The current annotation target is
  unmet: 7 candidates, 3 scenes, 4 distinct context hashes, 1 eligible sample.

## Model and runtime

- Downloaded the official Apache-2.0 `Qwen/Qwen3-1.7B` safetensors at revision
  `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`, converted locally to F16 GGUF,
  then quantized to Q4_K_M. The output is 1,282,439,168 bytes,
  SHA-256 `9954a72ab369f967d40520ea5fd161485bf82593f9050ae8a93528e90aa4163f`.
- Built official llama.cpp tag `b12189`, commit
  `80d2c0c2c56e4a1bbf74be98f64b99927bf230bc`, CPU-only, Release, native
  optimizations and OpenMP. `llama-server` SHA-256 is
  `39810101b9c23983133c660f6ec1ca96188d989b1e87cba66026f813645939cb`.
- Model shards, tokenizer, chat template, license, converter dependencies,
  quantizer/server/CLI binaries and asset hashes are pinned in
  `runs/room-slm-pilot/S2/model-runtime-lock.json`. The repeatable enabled
  config is run-scoped at `runs/room-slm-pilot/S2/qwen3-1.7b-q4km-cpu.json`.
  The shared experimental config remains disabled.

## Same-context baseline comparison and resources

Five immutable requests across three scenes were each passed unchanged to the
rules baseline and local SLM. The paired output is in
`runs/room-slm-pilot/S3/real-inference-summary.json`; individual predictions sit
beside their requests.

| Measure | Result |
|---|---:|
| Rule baseline | 1 available, 2 unknown, 2 insufficient evidence |
| SLM | 3 timeout, 2 invalid output, 0 accepted labels |
| End-to-end latency | p50 60.95 s, p95/max 62.25 s |
| Sampled child-process RSS | 2.55–2.57 GB |
| Resource samples per call | 265–446 at ~100 ms intervals |
| Process launch / clean shutdown | 5/5 / 5/5 |

Two short one-object contexts returned invalid JSON semantics in 37–39 s. A
captured raw response repeats `office` in both `label` and `alternatives` and
claims a mirror proves an office; the strict adapter correctly rejected it.
Three larger contexts hit the 60 s job deadline and finished cleanup at
60.95–62.25 s. Host available memory stayed around 9.58–9.86 GB; swap was
already in use (about 3.35–3.49 GB). These measurements are for cold, per-request
CPU server launch, not a persistent worker. No semantic accuracy, macro F1,
coverage gate, or matched-coverage quality claim is supported by this sample.

## Verification

- `PYTHONPATH=.:src .venv/bin/pytest -q tests/test_room_slm_backend.py tests/test_room_label_evaluation.py tests/test_room_label_snapshot.py tests/test_room_label_requests.py tests/test_room_label_contract.py tests/test_room_context.py tests/test_hydra_scene_graph_query.py tests/test_room_label_prompt.py tests/test_room_label_adapter.py tests/test_room_slm_cli.py tests/test_room_object_visual_association.py` — **66 passed**, exit 0. This includes the regression proving timeout/error telemetry retains `launched=true` and clean shutdown.
- `tools/audit_room_object_visual_association.py` ran on complete detector-backed exports for 00805, 00806, 00807 and, separately, the explicitly marked incomplete 00807 artifact. Geometry-projection outputs are not treated as semantic confirmation.
- Real inference was run with the pinned run-scoped config, one CPU thread, no GPU layers, local loopback only, and clean process shutdown. The eligible 00807 request timed out; no output was used to choose annotation labels.
- The first focused-test invocation omitted repository root from `PYTHONPATH`; the corrected command above passed. The shared CLI config was restored to disabled after moving enabled settings into the run artifact.

## Gates and next step

1. **S1 data gate remains open:** obtain image/RGB-D evidence for at least eleven more eligible independent physical rooms with detector-backed objects, at least twelve total across three scenes; review category-to-image association and room membership. Current merged `R(0)` contexts cannot count as separate prediction samples.
2. **S3 quality/resource gate remains open:** after freezing those annotations, improve or reject the current prompt/model path, then rerun paired inference on the same eligible contexts. The present results show invalid outputs and deadline misses, so they are not a pass.
3. **S4 async worker and S5 UI/live remain unimplemented and gated.** No Hydra geometry, native IDs, membership, exploration, movement, freshness guard, command horizon, default profile, or external source repository was changed.
