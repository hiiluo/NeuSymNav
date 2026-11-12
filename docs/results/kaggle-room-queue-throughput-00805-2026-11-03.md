# Kaggle room queue throughput evidence — map 00805 — 2026-11-03

## Scope and provenance

This note records the bounded Kaggle live run reported by the user. It is
evidence for the room-pipeline queue behavior on **map 00805** only; it is not
a result for other scenes or a general benchmark. The run's episode ID is
`local-intel-00805`. The pinned local profile previously identified map 00805
with HM3D scene `SUHsP6z2gcJ`.

- Run ID: `20261103T103038Z-53d2b0a0-180s`
- Requested live duration: 180 s
- CLI outcome / exit: `completed` / 0
- Reported cell wall time: 216.33 s (includes post-run detector diagnostic)
- Evidence source: user-pasted bounded-live output, preserved at
  `/home/kiettran05/.codex/attachments/5132bd4b-f84a-4989-a685-67a89296a41f/Pasted text.txt`
- Run artifact originally resides in Kaggle working storage at
  `/kaggle/working/rebuild-rgbd-00805-full/runs/20261103T103038Z-53d2b0a0-180s/`;
  that directory was not independently inspected from this local workspace.

## Queue counts

| Room-lane event | Count |
| --- | ---: |
| RGB-D room offers | 335 |
| Enqueued | 26 |
| Admitted to room session | 26 |
| Processed | 26 |
| Queue dropped/rejected | 309 |

Calculated from these counters:

- Room-lane drop fraction: `309 / 335 = 92.24%`.
- Room-lane processed fraction: `26 / 335 = 7.76%`.
- Sensor recording is a separate lane: `672 / 672` expected frames were
  durably written, with zero source gaps and zero recording rejections.
- Graph recorder/scheduler is also separate: `4 / 4` graph offers were
  durably accepted and processed, with zero rejects.

Thus “92% dropped” refers only to offers into the Rebuild room pipeline. It
does not mean 92% of all sensor frames or all project data were lost. The
recording certificate shows all 672 sensor frames were retained in this run.

The coordinator implementation offers each primary RGB-D observation to the
room lane, then rejects a new offer when either two room frames are already
queued or queued plus in-flight estimated payload exceeds 32 MiB. The room
worker consumes this queue serially. See
`src/neusymnav/runtime/coordinator.py`, `_offer_room_input_locked` and
`_room_pipeline_run` (current source lines around 566–645). The counters report
`queue_dropped=309` and `rejected=309`; based on the code path and the exact
counter equality, these drops were queue-capacity rejections, not room-worker
failures.

## Runtime context

- 180-second live run completed, `error=null`, `runtime_clean_shutdown=true`.
- Raw sensor recording certificate: complete; 672 expected, accepted, and
  written; 0 missing; 437,456,023 durable bytes of 536,870,912 allowed.
- Room revisions: accepted/latest M3 revision 26; M5 revision 22;
  `regions_stale=false`; `replay_required=false` at shutdown.
- Latest reported M1–M3 update timing: 4,134.17 ms total, including M2
  2,497.61 ms, M1 31.87 ms, M3 86.25 ms. M4/M5 together: 8.74 ms.
- These are the latest update's timings, not a latency distribution. They
  suggest M2 is the largest measured component in that update but do not
  establish the average or tail latency for all 26 updates.
- Detector diagnostic observed YOLOE inference on Tesla T4 (`cuda:0`), with
  1.071 s synchronized prediction and 1 detection. Triton raycast also
  reported Tesla T4. Those GPU results do not indicate that Rebuild M1–M5 ran
  on GPU; room timings are from the native room pipeline.

## What this does and does not establish

**Established for this run:** room-pipeline ingress could not keep up with the
offered updates under its bounded queue; 309/335 room offers were dropped.
The live run and raw recording completed cleanly, and M3/M5 were reported
non-stale at shutdown.

**Not established:** the strict acceptance checker result for this exact run;
M5 geometric validity/acceptance; room segmentation quality or scene coverage;
whether the 26 processed frames adequately represented the traversed area; or
whether other scenes behave similarly. Non-stale revisions alone do not prove
coverage or acceptance.

For later reports, describe this as **“map 00805 bounded Kaggle run, 180 s:
309 of 335 Rebuild room-lane offers dropped (92.24%); all 672 sensor frames
were recorded.”** Keep the acceptance/coverage caveat unless the matching
run's exported checker and coverage artifacts are retrieved.
