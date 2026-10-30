# Motion and realtime investigation — 2026-10-29

Latest user run: `demo-yoloe26m-640x480-long-20261029-214124-311256746`.
It recorded 2348 control calls, only4 executed right turns (3.73degrees total),
2343 control_rejected results, and no forward command or measured translation.
Map stayed at revision5/navigation frame6 while590primary+2350navigation raw
captures continued. Sensor sim time stayed at0.096s for the final2930frames.
Its19.85Hz wall-time invocation rate mostly describes the rejected loop.

A CPU reproduction using the production accepted-pause handler, navigation
submission and Habitat client pose validation yields exactly this pattern:
pause rejects new map/depth admission, the sensor advances its source cache,
and control asks for the superseded retained pose. The original command/ACK
mailbox was consumed, so the retained evidence cannot identify who requested
pause or the exact request. The user does not remember whether Pause was used.
No inference of model slowness causing the admission freeze is warranted.

Implemented repair: paused/closing control returns a non-actuating explicit
runtime_paused/runtime_stopped result before pose/policy/guard work. Existing
control lock ensures accepted Pause follows the last finite pulse. No automatic
resume, new synthetic command, proof reuse, stale-source motion or TTL relaxation.
UI command/ACK diagnostics now retain last64 records at clean finalization,
independently of consumed ACKs (128KiB bound, sanitization markers). Abrupt kills
before finalization can still lose these diagnostics; physical user identity is
not authenticated. Pause remains latched; restart to begin another live run.

Performance changes preserve algorithms and packets: JSON-lines receive scans
only new bytes for its delimiter (regression:524KiB fragmented reply previously
rescanned67.9MB); optional prewarmed bounded Numba frontier reductions preserve
minimum-distance, first-seen tie rank and exact final ordering, retaining the
original NumPy fallback for unsupported inputs. No model/data/dependency install.
RGB640x480, YOLOE26m imgsz640, depth TTL300ms, unknown/free distinction, footprint,
clearance, one-use source and native command/proof contracts are unchanged.

Reference caution: NewOH3DSG CTRL Hz counts completed simulator steps including
STOP; it differs from sensor, model, UI and translation rates. Retained near20Hz
runs include mostly STOP, while previously observed moving600s run was14.31Hz.
No normalized side-by-side current benchmark of both complete systems is claimed.
Neu's current long profile already has selective sensor reads, primary5Hz,
navigation20Hz requests and lossless npz_v2 recording. Older audit proposals to
implement these are historical, not remaining work.

Evidence and command/exit logs: `runs/realtime-motion-20261029/` (local, ignored),
with `diagnosis/`, `reference/`, `pause-audit/`, `frontier/`, before-metrics.json,
profile-stages.json, regression logs and pending native validation. Initial
no-UI-input30s baseline moved0.7535m lower bound,10.09Hz, p95149.06ms/p99169.71ms;
its resource sampling was incomplete, so it is not an accepted full runtime.
A UI-off diagnostic20s completed with9.47Hz and0.4198m lower bound; stage profiler
itself adds overhead. These baselines are retained and not substituted for final
production invocation statistics. Final candidate results will be appended.

## GPU follow-up — 2026-10-30

Explicit CUDA raycasting now uses existing Torch2.7.1/Triton3.3.1 in an isolated
worker; core imports neither framework. FP64/no-FMA traversal qualified bitwise
against CPU on measured41912-ray frames and boundary/no-return fixtures. Strict
bounded binary/JSON IPC binds geometry, request UUID and payload hashes. Worker
failure has no CPU fallback; startup/close/descriptor races have independent
regressions and scoped SolHigh ACCEPT. No install/download/source-repo edit.

Later profiles identified region CPU work and duplicate projection in addition
to ray traversal. Implemented: exact finite-coordinate bounded geometry caches,
100ms canonical map/region publication coalescing (new object revisions bypass),
final region/graph drain and post-quiescence canonical flush, uint8 mask-domain
validation without np.isin, call-local measured projection reuse preserving the
original world-axis transform. Source/pose/TTL/clearance/footprint/proof unchanged.
New GPU profile requests navigation30Hz with primary5Hz, without timer catchup;
existing CPU profile keeps20Hz. See gpu-mapping-design.md for contracts/limits.

Final whole-tree CPU command (frozen223 source/test/profile/script pins):
`OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMBA_NUM_THREADS=1
QT_QPA_PLATFORM=offscreen PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1
.venv/bin/python -m pytest tests -q -m 'not native'`
=>1859passed/2skipped/3deselected, exit0,97.50s. Earlier whole-tree attempt had
1837pass plus5 stale private _mapper mock-signature failures; mocks updated and
61profile tests passed before the final full rerun. Both logs retained.
Actual GPU worker final tests =>31passed exit0/2.06s, using detector26 Python and
existing system pytest read-only. Optional NumBa and native cases are not inferred
from portable skips: independent host acceleration/rejection/endpoint probes and
actualCUDA tests provide their separate evidence. Review reports: review-gpu/,
publication-review/, review-geometry-cache/, review-projection-reuse/.

Retained diagnostics are explicitly separate from final acceptance:
first integrated GPU20s12.321Hz/incompleteRSS; profiler15s11.52Hz; publication cap
probe20s12.36Hz; expensive cProfile whole-thread15s9.43Hz/incomplete graph cleanup
and no complete cProfile output; three-call region profile10s12.56Hz/completed;
puregeometrycache20s15.934Hz/incompleteRSS; navigation30 request20s17.086Hz/
completed,0.527m observed translation lower bound, strict export/proof and every
raw payload decoded. The cache harness additionally cached triangulation and is
not identical to the stricter production geometry cache. Navigation30 diagnostic
used an overridden validator before its production capability was implemented.
None of these is a final frozen20Hz demonstration. Logs and attempt-metrics.json
remain under runs/realtime-motion-20261030/.

The final frozen production60s run and offline audit are recorded separately;
no claim of20Hz, continuous50ms deadlines, full600s GPU validation, desktop timing,
quality improvement or P10 acceptance follows from unit tests or component speed.

Final production60s validation: `QT_QPA_PLATFORM=offscreen bash
tools/run_gpu_demo.sh 60 runs/realtime-motion-20261030/gpu-final60`
=>exit0/completed,17.698374Hz, p9598.201218ms/p99124.397844ms;
436/1060intervals>50ms(41.13%),49/1060>100ms(4.62%).1053nonzero executedproofs,
1.98496m observedtranslationlowerbound;42detector/23objectevidencecommits.
Raw1332/1332complete(1063depth180×240+269RGB-D480×640),485112599B; offline strict
export/proof/context inspector and fullReplayReader payloaddecode exit0.
RSS559/559valid sampledpeak3392073728B/GPU63/63valid702545920B, cleanworkers,
no runtimehealthfailure.223frozenpins unchanged afterCPU/native; postrun hostGPU
computeprocessinventory empty. The minimum10Hz mean target is met on this scoped
run;20Hz and50msdeadline consistency remain unachieved. Firstassignedmembership
absent; P10 remains unaccepted. Final audit/review paths are in the local report.

Independent finalnative review recomputed all timing/source/proof/rawbindings.
Eight expired_or_zero outcomes lack actuationproofs; aggregate actuation.complete
remainsfalse.1053retained proofs each join exact rawsource/calibration/pose/time
and commands; no proof is invented for unexecuted outcomes. Motion remains a
measured lowerbound, not certification of a complete physical trajectory. All19
final objects are unassigned; no assignedroommembership claim. Review-final-native/
records the scoped single60s acceptance and these limitations.
