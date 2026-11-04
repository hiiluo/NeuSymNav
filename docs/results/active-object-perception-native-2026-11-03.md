# Active object perception native smoke, 2026-11-03

This engineering smoke used Habitat 00861, the existing seed 0 and fixed start
policy, the pinned YOLOE-11s/CLIP recipe, 640×480 primary RGB-D, the existing
Triton CUDA map worker and the fixed-height planar actuator. The four profiles
each requested 45 s of live runtime. Only UI enablement and the experimental
mode/strategy differ from the corresponding development profiles. The initial
shadow run preceded active motion. Runs were sequential on the RTX 3060.

The artifacts are under
`.runtime/active-object-perception/native-smoke-20261103/`. They include the
effective profile JSONs, preflight outputs, source/config hashes, stdout/stderr,
exit codes and full run exports. Reproduce each attempt with a fresh output
directory, in a session with access to the simulator and CUDA:

```sh
d=.runtime/active-object-perception/native-smoke-20261103
mode=memory # shadow first, then off, reobserve, scheduled in separate attempts
PYTHONPATH=src .venv/bin/python -m neusymnav.cli preflight --config "$d/$mode.json"
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  .venv/bin/python -m neusymnav.cli run --config "$d/$mode.json" \
  --duration-s 45 --out "$d/new-$mode"
python3 "$d/summarize.py"
```

The summary script reads the retained `run-*` artifacts. Its p95/p99 use
nearest-rank quantiles of consecutive control invocation start intervals.
Those intervals include sensor and map waits. They measure cadence, while
command execution latency is a separate population. Misses count intervals
strictly over 100 ms (10 Hz period) or 50 ms (20 Hz period).

## Native evidence

| Mode | CLI exit | Mean Hz | p95 / p99 interval (ms) | >100 ms | >50 ms | Detector calls / commits |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| B / off | 1, incomplete | 18.73 | 90.38 / 116.90 | 20/841 | 310/841 | 16 / 16 |
| M / shadow | 0 | 16.42 | 106.55 / 130.05 | 54/737 | 363/737 | 15 / 15 |
| R / reobserve | 0 | 18.59 | 96.23 / 127.08 | 33/835 | 294/835 | 19 / 19 |
| C / scheduled | 0 | 18.63 | 96.98 / 132.20 | 34/837 | 290/837 | 19 / 19 |

All four preflights exited 0. All four runs have complete raw recording
certificates, full control-start exports, and clean runtime shutdown. R/C
reported zero runtime health failures and zero publication mismatches. The B
run remains incomplete because one RSS sample failed when the CUDA worker's
leader was a zombie and a thread was still alive. The other three resource
exports were complete. Across all runs, sampled peaks were 4,694–4,832 MiB RSS
and 490–492 MiB process-attributed VRAM. These are sampled peaks.

Shadow retained 18 views and reported two feasible viewpoints with no
reobserve actuation. Both active modes emitted source-bound reobserve action
proofs and then returned to frontier actions. R had 126 reobserve proof rows,
0.187 m observed translation, 7.24 s of active time and 149 later frontier
proof rows. C had 138 rows, 0.141 m observed translation, 7.58 s of active time
and 120 later frontier proof rows. Neither mode satisfied a request with new
independent evidence. R ended 14 requests blocked and eight expired. C ended
12 blocked, eight expired and two cancelled. The recorded reasons include
unknown space, outside-map viewpoints, unreachable paths, time budget and
object movement.

Each attempt lacked three command proofs. Distances computed from present
proofs are observed endpoint lower bounds. The existing frontier distance
aggregate counts any nonempty goal ID for these runtime profiles, which
includes reobserve IDs. The smoke summary separates reobserve actions by
their exported goal ID and excludes the mixed aggregate from frontier
comparisons. R and C used 19 detector calls each, with different observed
travel. This pair does not establish a matched realized motion budget.

## Acceptance decision

The smoke confirms native shadow planning, guarded active motion and return
to frontier. End-to-end fresh-view completion remains unverified. Average
control rate exceeded 10 Hz in each attempt. All four had periods over
100 ms and averaged under 20 Hz. The incomplete B run and one attempt per
mode prevent a paired performance conclusion. No safety thresholds were
changed. Full actuation coverage and P10 certification remain open.

Q5 development quality pilot and Q6 confirmation remain gated. The smoke
has one seed and shorter horizons than the frozen protocol. Existing 00861
annotation covers only a sparse scoped development subset, with no suitable
independent held-out scene set. There is no promotion decision from these
attempts. Keep the default `off`.

Focused correctness rerun after the GPU attempts: 40 passed, exit 0, using
`PYTHONPATH=src QT_QPA_PLATFORM=offscreen OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -m pytest tests/{test_active_perception_runtime,test_active_perception_evaluation,test_active_viewpoints,test_reobserve_requests,test_view_memory}.py -q`.
See `focused-cpu.log` and `focused-cpu.exit` alongside the native artifacts.
