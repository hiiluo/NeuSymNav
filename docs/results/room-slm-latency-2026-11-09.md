# Room SLM latency path — 2026-11-09

Status: **implemented + CPU tests pass in a container; not yet measured with the real
model on the robot host and not yet run live.** Labels remain hypotheses for the
debug UI; they never feed geometry, navigation or control.

## Why it was slow (measured before this change)

| Source | Prompt | Prefill | Output | Decode | Total |
|---|---|---|---|---|---|
| live 00807-120s R(3), 2 objects | 480 tok, cache 0 | 29.6 s (16 tok/s) | 71 tok | 12.8 s (5.5 tok/s) | 48.2 s |
| live 00807-120s R(0), 5 objects | 661 tok | — | — | — | timeout 60 s |
| KV bench, 9 objects, cache OFF | 955 tok | 57.3 s | 136 tok | 31.6 s | 89 s |

Causes: server pinned to 1 CPU thread; ~340 static prompt tokens (instructions +
a JSON schema the grammar already enforces) plus ~70 tokens/object of constant
fields (`association=not_recorded`, `evidence_count=0`, `membership=assigned`) and
place-parent relations; a model-written `reason` of up to 256 chars dominating
decode; timeouts killing the warm server; and request identity bound to the
whole-graph snapshot hash so every Hydra revision re-queued every room.

## What changed

1. **Threads / priority** — `RoomSlmBackendConfig.threads` accepts 1..32 (clamped to
   the CPUs available), new `nice` (0..19) and optional `cpu_affinity`. Both
   backends pass `--threads` and `--threads-batch`; priority/affinity are applied to
   the server right after spawn (`metrics.scheduling` records the outcome).
2. **`prompt_policy: compact-v2`** (`rooms/compact_policy.py`). Prompt = one static,
   room-independent prefix (cached by llama.cpp) + `"<index> <category>"` lines.
   No native IDs, schema, constant fields or relations reach the model. Generic
   common-sense cues (toilet → bathroom, …) are part of the static prefix; no
   scene annotation is used.
3. **Compact answer** `label|alt1,alt2|1,3` (or `unknown`), constrained by a
   request-bound GBNF (sorted unique support indices ≤8, alternatives ≠ label).
   The host maps indices to this request's own native IDs, writes a factual reason
   (`supported by bed O(0), …`), builds the canonical JSON and passes it through the
   unchanged strict `adapt_model_reply` + `validate_room_label`. Output budget 64.
   `json-v1` stays the default for offline reproducibility.
4. **Semantic reuse** in `RoomLabelDebugService`: a model answer is remembered by
   `(episode, run, world_epoch, room_id, geometry_status, truncated, [(native_id,
   category, membership)])`. A newer revision with identical room rows gets that
   answer bound to its own exact key (`backend_metrics.semantic_cache = hit`,
   `reused_from_revision`), without a model call; changed rows trigger a new call.
   Timeouts/unavailable/invalid answers are never reused. Reuse records replace
   each other in history. `history.json` writes are throttled to ≤1/s.
5. **Warm-up**: the service starts `PersistentRoomLabelBackend.warm()` in the
   background, which launches the server and prefills the static prefix once.
6. **Scene-graph display**: `rooms/label_overlay.current_room_labels` selects only
   records bound to the exact current revision; the 3D Scene and Scene Graph tabs
   show them on Hydra room nodes (`SLM bathroom · R(0)`). Display only.

Configs: `configs/room-label-slm.async-debug.local.json` now sets `threads: 4`,
`nice: 10`, `prompt_policy: compact-v2`, `max_output_tokens: 64`; its SHA-256 pin in
`configs/demo-00807.hydra-room-slm-debug.experimental.local.json` was updated.
`room_label_ui_entry.py` is unchanged (its pin still matches).

On the two frozen requests in `runs/`, the compact prompt is 1088 / 1180 chars versus
2738 / 4604 for json-v1, and 1020 of those chars are the cached static prefix.

## Verification done

Container (Python 3.13, no PyQt5/llama.cpp): 145 room tests pass (+22 new),
23 native-marked skipped; Qt integration tests and `coordinator` imports were not
runnable there. GBNF language checked by inlining the grammar to a regex; it uses
only constructs the previous native-validated grammar used, but **has not been
parsed by the pinned llama.cpp yet**.

## Still to prove on the robot host

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q -m 'not native' -k 'room or hydra'
.venv/bin/python tools/bench_room_slm_latency.py \
  --config configs/room-label-slm.async-debug.local.json \
  --request-json runs/room-slm-async-debug-20261108/persistent-request-normalized.json \
  --request-json runs/room-slm-diagnosis-20261108/corrected-00805/request-000.json \
  --baseline --out runs/room-slm-latency-bench-20261109/bench.json
```

Then the live demo with the debug profile. Open limits: label accuracy is still
unmeasured (no human reference set of ≥12 rooms/3 scenes); temperature-0 output
was observed to differ with KV cache on/off; room segmentation errors are not
fixed by labels.
