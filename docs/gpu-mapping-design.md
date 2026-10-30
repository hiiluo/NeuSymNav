# Optional CUDA raycasting — 2026-10-30

User explicitly requests GPU acceleration toward useful20Hz control. Existing
YOLOE26m already runs CUDA; this change moves measured-depth ray rasterization
into an isolated Torch2.7.1/Triton3.3.1 CUDAworker using existing localruntime.
No model/data/dependency download or installation. CPU remains the baseline;
select GPU explicitly using navigation.mapper.raycast_backend=triton_cuda and a
hash-pinned workers.raycast interpreter/script. No silent backend fallback.

Scope: per-ray traversal/vote masks only. CPU projection, immutable NavSnapshot,
log-odds map owner, frontier/controller and final safety guard retain their
contracts. Ray traversal uses FP64 parameters, IEEEdiv/sqrt and disabled fusion;
per-ray pending voxel and endpoint/floor classification preserve CPU semantics.
Atomic integer OR combines votes deterministically; occupied-wins is applied
before mapper integration. Current-frame source/pose/calibration/TTL300ms,
unknown/free, footprint/clearance and proof gates are unchanged. Keep original
navigation240x180 and primaryRGB640x480 with YOLOE26m imgsz640.

A fresh run-local private IPC directory holds one request and response, with
atomic ephemeral binary handoff (no replay durability claim). Closed framed
JSON metadata binds UUID/geometry/N and SHA256 binary payloads; host validates
response context, raster, byte counts and masks before using them. Host andworker
both bound rays, work, indices, cells and memory before nativeallocation.
The GPUworker qualifies its actualkernel at startup before new control captures.
GPUfailure/deadline errors stop publication through normal runtimehealth;
CPUfallback is not used to hide failures. Owned bounded cleanup reports pending
workers, including when graphstartup prevents the navigationthread starting.
IPC file descriptors reject symlinks/FIFOs/nonregular or multiplylinked files.

Limits:100k rays,1M gridcells,256heightbins,128MiB output,512MiB devicebuffer budget,
100k samples/ray and50M totalsamples. These are rejection limits, not allocation
promises or continuousGPUmemorycertification. Runquota separately reserves both
IPC files/temporaries; resource sampler includes GPUworker process descendants.

Validation: CPU protocol/wiring/lifecycle regressions first, independentSolHigh
review, actualCUDA bitwise five-mask parity on retained41912-ray frames and
boundary/no-return cases, one prewarmed kernelvariant, then integrated native
smoke and stable runtime timing. Standalone GPUcompute p50~4.6ms does not equal
systemlatency: measured end-to-end worker p50~10.7–11.2ms includes validation/IPC.
No sustained20Hz/P10 claim until actual source-ready control and movement, full
replay, resources and independent evidence support it. Evidence lives locally
under runs/realtime-motion-20261030/; older CPU/native attempts remain retained.

Measured follow-up: region owner used23.52ms thread CPU/update in the stage
probe, largely repeated simple-ring validation and polygon intersections.
Bounded64-entry pure geometry caches retain exact finite float64 coordinate
bytes (including signed zero), never source/revision/membership decisions.
Unsupported types/oversized rings retain the scalar path. Independent frozen
scalar differential evidence is under review-geometry-cache/. A uint8 vote mask
needs only an upper-bound comparison (>1); the equivalent boolean-domain check
avoids np.isin's dense integer temporaries. Retained565110-byte microbenchmark:
2.529ms vs0.0255ms median; this is not an end-to-end cadence measurement.

Canonical hierarchy/map composition coalesces map/region churn at100ms; new
object revisions publish promptly. Control still uses its independent freshest
measured map. During close, graph waits for navigation and region producers,
then publishes once after observing quiescence, preserving the atomic final
hierarchy/map pair. A blocked worker remains pending rather than being declared
clean. Independent scheduling/finalization race review: publication-review/.

The optional GPU profile requests navigation30Hz and primary5Hz, with no timer
catchup. This is a bounded capture ceiling, permitting control to recover time
spent on interleaved RGB capture; it does not certify30Hz or20Hz. Existing CPU
profiles remain20Hz. At600s the ideal30Hz count18000 fits the unchanged20000
control/proof record cap; raw/trace/resource limits are unchanged. One diagnostic
20s production-path attempt (before final projection optimization) completed:
17.086Hz, p9599.135ms/p99113.279ms,0.527m observed translation lower bound, all
raw decoded and strict export/proof inspection passed, RSS228/228valid. Its
navigation request validator was harness-overridden; final released profile
must be measured separately on a frozen snapshot. No final20Hz claim from it.
