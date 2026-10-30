# Running NeuSymNav

## Current CUDA checkout: choose a map

The current CUDA checkout has checked local assets/profiles for **00770, 00802,
00861**. List prepared profiles and check the chosen one before launch:

```bash
bash tools/run_map_demo.sh --list
bash tools/run_map_demo.sh 00770 --preflight
bash tools/run_map_demo.sh 00770 300
bash tools/run_map_demo.sh 00802 300
bash tools/run_map_demo.sh 00861 300
```

These GPU profiles use the selected YOLOE11s640/.30 + CGvisual, radius.125m,
height1m and margin.05m. Each new output starts with an empty map/graph. The new
profiles retain existing scene-specific measuredfloor/initialpose provenance;
no simulator/navmesh occupancy seeds the runtime map.00337mesh is present but
has no prepared profile here. The00800–00809 Intel/machine-local profiles below
are available only where their local assets and generated configs exist.

The selector keeps existing `configs/demo-MAP.local.json` support on the Intel
setup; otherwise00770/00802/00861 select the currentGPUprofiles. MainGPU wrappers
also accept `NEUSYMNAV_DEMO_CONFIG` for an explicit profile.


## Local Intel/CPU demo on this machine (2026-10-30)

```sh
bash tools/run_local_demo.sh --preflight
bash tools/run_local_demo.sh 600
```

The default duration is **600 seconds (10 minutes)**. Run `bash tools/run_local_demo.sh`
without arguments for this duration; Stop can end the demo earlier.

The local wrapper reads the ignored `configs/demo.local.json`, with checksums
for this checkout, scene 00802, measured floor calibration, Intel/Mesa EGL
(`gpu_device_id=-1`), CPU raycasting and YOLOE-26m on Torch CPU. It opens the
Qt viewer; run from a desktop terminal with `DISPLAY` available. Startup and
model initialization add time beyond the requested capture duration. An optional
second argument selects a new output directory. Use Ctrl+C or the viewer's Stop
control to finish early.

Core/UI/Numba are installed in `.venv`; the detector is isolated in
`.runtime/detector26`. The sensor reuses the existing, read-only
`/home/kiettran05/miniconda3/envs/habitat` (Python 3.9, Habitat-Sim 0.3.3), whose
control-source hashes match the runtime contract. A newer local source build also
reports version 0.3.3 but fails the planar adapter hash check; it is not selected.
Model weights, the copied scene and the native worker are under `local-assets/`.
Calibration, dependency snapshots and setup logs are in
`.runtime/setup-20261030/`. No NVIDIA GPU is installed on this host; the historical
CUDA wrappers and their absolute-path configs below target another machine.
CPU demo readiness does not certify the historical GPU performance or P10 gates.

The local launcher uses 100% Qt scale for this 1920×1080 display and removes
inherited per-screen scale multipliers. To choose another zoom explicitly:
`NEUSYMNAV_UI_SCALE=1.1 bash tools/run_local_demo.sh 600`. Restart the demo
after changing scale; desktop-wide settings remain unchanged.

## Spatial scene viewer

The lower panel now defaults to **3D Scene**: historical measured RGB-D cloud,
blue geometry-region nodes and gold object nodes in world coordinates. Drag to
orbit, wheel to zoom, double-click to fit, and click an object for evidence.
Use **Focus view → SCENE GRAPH** to enlarge it. Only assigned graph relations
are connected; unassigned objects remain disconnected. **Graph layout** and
**Hierarchy** retain the structural views. See [spatial scene controls and data
limits](spatial-scene-ui.md). Restart the demo after updating UI code.

## Choose a local HM3D map

```sh
bash tools/run_map_demo.sh --list
bash tools/run_map_demo.sh 00800
bash tools/run_map_demo.sh 00809 120
bash tools/run_map_demo.sh 00803 --preflight
```

Choose one of `00800`, `00801`, `00802`, `00803`, `00804`, `00805`, `00806`,
`00807`, `00808`, `00809`. Each command opens one demo; default duration is
600 seconds, and the optional duration argument is in seconds. Stop ends early.
The original `bash tools/run_local_demo.sh` still uses its original 00802 start.
Map-specific configs use independently prepared, explicit starting poses.

Each ignored `configs/demo-MAP.local.json` pins the available local scene,
worker/model hashes and measured floor calibration. Preparation uses a seeded
navmesh sample only to select a saved initial pose offline; live occupancy still
starts empty and uses sensor depth. Preparation artifacts and RGB previews are
in `.runtime/map-selection-20261030/`. Rebuild configs after moving dependencies
or changing pinned worker scripts. To prepare one again with the sensor runtime:

```sh
EGL_PLATFORM=surfaceless PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 \
  /home/kiettran05/miniconda3/envs/habitat/bin/python -B \
  tools/prepare_local_maps.py 00800
```

`apt_0`–`apt_5` assets exist, but their full ReplicaCAD scenes require six
articulated objects each. The current live sensor has physics disabled and omits
these objects. Their trial renders/configs are quarantined as incomplete; the
map launcher rejects them. They are not advertised as ready-to-run maps.

## Current demo: YOLOE-26m and 640×480 RGB-D

```sh
bash tools/run_realtime_demo.sh --preflight
bash tools/run_realtime_demo.sh 20
```

The wrapper now selects `configs/p10/demo-yoloe26m-640x480-00861.json`:
YOLOE-26m-seg + local MobileCLIP2, actual primary RGB/depth640×480, detector
imgsz640, confidence0.25, navigation depth240×180. The isolated detector26 runtime
uses Ultralytics8.4.24 matching checkpoint metadata and reuses existing Torch/CUDA.
The previous YOLOE-11s runtime/profile remains available for reproducibility.

The second command opens the Qt viewer and creates a fresh output directory.
Default duration is **20seconds**. A30second validation hit the unchanged1GiB raw
recording quota and is retained as incomplete;20seconds completed with292/292raw
frames and clean shutdown. Longer durations can stop at quota; no recording is
silently dropped to extend the demo. An optional second argument sets a new output
directory. Remove inherited `QT_QPA_PLATFORM=offscreen` for a visible desktop.

**This high-resolution profile does not meet the10Hz target.** The20second check
measured mean active control7.388Hz, intervalp95165.476ms/p99173.716ms,
142/142intervals>100ms; startup/shutdown excluded. The30second incomplete attempt
measured7.083Hz and remains in the report. These are invocation instrumentation
aggregates, not accepted-motion or semantic update rates. Confidence improvement
is not established; the initial fixed frame had zero detections forYOLOE-26m.

[New profile evidence and limits](../runs/yoloe26-640x480-20261029/report.md).
Earlier11.181/10.503Hz observations belong to the previous low-resolution
YOLOE-11s source/profile snapshot; they do not certify this demo. The wrapper's
filename is retained for compatibility and is not a realtime guarantee.

Run commands from the `NeuSymNav` project directory with the configured host
Python 3.12 environment. The source checkout can be used directly with
`PYTHONPATH=src`; an installed package also exposes the `neusymnav` command.
The CLI itself imports only the standard library. Runtime dependencies are
loaded after a command is selected, and UI, simulator, model, and native
worker paths must be declared by the selected configuration.

## Preflight and bounded runs

Preflight reads one explicit configuration and checks its declared local
resources without starting a simulator, model, native process, or UI:

```sh
PYTHONPATH=src .venv/bin/python -m neusymnav.cli preflight --config configs/baseline.yaml
```

The baseline profile is frontier-only with simulator pose and the declared
detector path. It requires explicit local worker and asset paths, including
SHA-256 values. Relative resource paths in a configuration resolve from the
configuration file's directory. A missing resource appears in the JSON
result's `issues` field; `ready: false` exits with status 1.

Start a bounded live run with a new, empty output directory:

```sh
PYTHONPATH=src .venv/bin/python -m neusymnav.cli run \
  --config configs/baseline.yaml --duration-s 120 --out runs/live-001
```

`--duration-s` must be finite, greater than zero, and no more than 300 seconds.
Input and output paths passed directly to the CLI are relative to the current
working directory. The command writes a JSON result to stdout and run exports
under the requested output directory. It exits 0 only for a completed run;
failed or incomplete outcomes exit 1. Invalid arguments emit a JSON error on
stderr and exit 2. A runtime error emits an actionable JSON error on stderr
and exits 1.

The `geometry-only` profile disables appearance and retains the declared
YOLOE detector for live runs. CPU correctness fixtures explicitly select
`mode: fixture_cpu_no_models` with matching recorded detector batches; they
do not substitute a fake detector for a live model. The separate `appearance` profile stays optional; enabling
it requires an explicit local worker and checkpoint and does not promote its
quality before P10 evaluation.

## Recorded replay and evaluation

Replay consumes a checksummed recording and a matching configuration. The
recording's original source frames remain historical and use a persisted replay
session clock; they are never promoted into live control observations.

```sh
PYTHONPATH=src .venv/bin/python -m neusymnav.cli replay \
  --input runs/live-001/keyframes/recording --config configs/geometry-only.yaml \
  --out runs/replay-001
```

The live raw archive is written under `keyframes/recording`. Its reported
archive cap is `min(aggregate_raw_cap / 4, 256 MiB)`; the conservative shared
reservation also counts written archive bytes until drain. A recorder rejection
stops admission and produces an incomplete result. The aggregate budgets remain
2 GiB raw and 8 GiB per run.

The output summary records the outcome, profile, source-input checksum,
replay-session identity, accepted object IDs, evidence event IDs, runtime
health, and explicit runtime limitations. Reusing an output directory resumes
only when its persisted replay session matches the same input and configuration.
The bounded `events` list contains at most 4,096 rows; `events_total`,
`events_complete`, and `events_scope` identify that summary projection. The
canonical SQLite ledger retains the complete committed history. An incoherent
final hierarchy/map/object bundle is reported incomplete.

Offline evaluation consumes a frozen suite and checksummed runtime exports:

```sh
PYTHONPATH=src .venv/bin/python -m neusymnav.cli evaluate \
  --suite configs/evaluation/suite-v1.json --out runs/evaluation-001
```

This command evaluates supplied evidence; it does not launch a native campaign.
The shipped pilot pins one available scene and two seeds, with both attempts
explicitly missing. It writes `frozen-suite.json` and `report.json`, reports
completion 0/2 and exits 1 for the incomplete result. Missing, failed and timeout
attempts remain in the denominator; unmeasured metrics remain null with explicit
support. The evaluator fix passed independent scoped review; native software
readiness and execution gates remain incomplete. See the acceptance report.

## Source-only packaging check

The source-only check verifies package-local imports, dependencies, provenance
notices, and absence of source symlinks or legacy sibling imports. It then
copies the package and a recorder-generated RGB-D fixture to a temporary tree
and runs replay from an unrelated working directory with `PYTHONPATH` removed
and legacy source reads audited:

```sh
.venv/bin/python tools/verify_package.py --source-only
```

The JSON report is written to
`runs/p09-cli/source-only-report.json`. This check uses a deterministic CPU
fixture and reports model, simulator, and native execution as unavailable and
not runtime-validated. It establishes source import and fixture replay
isolation only.

## UI process

The PyQt viewer runs in a separate process. A live configuration may enable
the P09 UI transport; the launcher then starts the configured UI interpreter
and script and sends immutable display publications and acknowledged Pause or
Stop commands over that transport. The UI has no graph-write interface.
Live runs without an enabled UI configuration and all replays remain headless.

P08 verified the renderer with offscreen Qt tests and a synthetic screenshot.
The real display was unavailable during that check, so this does not establish
real-display operation or a nonempty live window. The P09 process transport
has its own source-only and bounded-process checks, but the actual display
still requires runtime validation on a host with a display.

## Runtime limits

Correctness tests and the source-only fixture do not prove Habitat capture,
detector or appearance inference, native DuDe execution, physical safety, or
scene-level quality. Model and scene assets stay external and must match the
declared checksums. The native worker candidate's presence does not establish
that it executes correctly or may be redistributed. Native portability is
claimed only for an OS and ABI where the worker has actually been exercised.

See [implementation status](implementation-status.md),
[source provenance](source-provenance.json), and
[third-party notices](../THIRD_PARTY_NOTICES.md) for the current evidence and
asset limitations.

## P10 measured profiles and evaluator v2

`configs/p10/baseline-seed-0.yaml` and `baseline-seed-1.yaml` are separate
measurement-enabled templates. Fill and verify existing interpreter/assets and
real scene floor/body/bootstrap calibration before preflight. Their null fields
are deliberate readiness blockers. The original three profiles and suite v1
remain historical; use the versioned templates for new measured attempts.
No environment installation or asset download is performed by evaluation.

```sh
PYTHONPATH=src .venv/bin/python -m neusymnav.cli evaluate \
  --suite configs/evaluation/suite-v2.json --out runs/p10-v2-evaluation
```

The supplied v2 pilot pins one scene and two seed configs, with both attempts
missing. Expected exit code is **1**, report outcome incomplete, attempted0 and
completed0. It does not start Habitat or inference. Record a real result v2 only
with checksum-pinned `measurements`, `summary`, execution `provenance`, and a
completed export manifest when applicable. Each suite attempt pins its own
`execution_config`. Failed measured phases retain supported performance only;
quality and completion require a compatible completed bundle. Software v2
integration is implemented but its independent review is still pending; see
implementation-status.md before treating it as a correctness gate.


## Robot overlays on the live map

The current `configs/p10/demo-ui-00861.json` enables the Qt viewer with measured robot position/heading, a thin sampled trail and calibrated camera FOV edges. Restart the demo process after updating code. Existing recorded UI publications may lack body poses; those display `Robot pose unavailable` until a new paired capture is published. Bright red cells denote occupied geometry; unknown stays distinct from free. The camera fan is a1m schematic, not a safe/visible region. See [overlay source and limits](ui-map-overlays.md).

## Larger NewOH3DSG-style viewer

The 2026-10-29 UI prefers 2160×1350 (50% larger per dimension), caps the window
at the current screen's available size and maximizes on smaller displays. Use
**Focus view → RGB FRAME / OCCUPANCY MAP / SCENE GRAPH** to inspect one panel;
**All panels** restores the split workspace. Splitter handles resize the panels.

**Detector observation** displays bounding boxes, labels/confidence and colored
segmentation masks from a committed detector batch on its own original RGB
frame. **Live RGB** displays the separate newest camera frame. The observation
caption reports frame/source age and historical status; detector commits are
asynchronous, so this tab can lag live RGB. Box and mask checkboxes change only
the display. Before a matched detector result is available, the UI shows live
RGB with detector observation explicitly unavailable. The RGB input retains its
actual sensor resolution when enlarged.

Restart the demo to load the updated viewer:

```sh
bash tools/run_realtime_demo.sh 20
```

See [design/source binding](ui-reference-refresh.md) and the
[historical real-evidence preview](../runs/ui-new-reference-20261029/preview-2160x1350.png).

## Opt-in 10-minute demo (fixed640 / YOLOE-26m)

```sh
bash tools/run_long_demo.sh --preflight
bash tools/run_long_demo.sh 600
```

The long wrapper uses the existing `.runtime/host` interpreter (including Numba),
fixed primary RGB/depth640×480, detector imgsz640, and unchanged navigationdepth
240×180. Primary capture targets5Hz; fresh navigation/control targets20Hz. These
are requested maximum rates; actual invocations, deadline misses and source-bound
motion must be measured. A single Habitat owner serializes capture/action calls.
Semantic inference never refreshes old sources or grants motion authority.

All generated primary and navigation observations enter checksummed NPZ v2
lossless replay. Legacy JSON recordings remain readable. The explicit per-run
budgets are12GiB archive,24GiB aggregate raw,32GiB total; startup requires at least
33GiB available disk. They are limits, not preallocated files. The recorder
releases pending estimates into actual durable byte accounting; quota exhaustion
still stops admission and marks incomplete. Source TTL300ms, footprint, clearance,
unknown/free distinction and actuation proofs remain unchanged.

`control-invocations.json` retains up to20000 actual invocation starts (including
STOP/pending) with SHA binding in the export. Its intervals can be recomputed for
p95/p99 and50/100ms misses. A complete file does not prove accepted-motion rate.
Long measurements explicitly budget20000 proof/pose records and512MiB conservative
trace charges; export is bounded64MiB. Overflow remains incomplete. The original
`run_realtime_demo.sh 20` keeps its legacy profile/defaults. See the latest status
and long-demo report for actual validation; command availability alone is not
10Hz/20Hz or P10 acceptance.

The long profile additionally limits expensive UI publication preparation to2Hz;
it coalesces graph publications before reading crops/segmentation and encoding
RGB. Captures still target5Hz and navigation20Hz. Pause/stop ACK processing is
independent. `coalesced_publications` is reported separately from failed/dropped
publications. The display therefore updates less often; original source ages and
historical detector status remain visible. RSS sampling uses an explicit1s
bounded operation deadline and0.2s retry wait (maximum3 trials), with every final
missing/truncated sample still counted as unsupported. See the retained first
600s attempt as well as the final profile's evidence; earlier incomplete runs
are not erased or relabelled complete.

Optional CUDA raycasting demo (existing local GPU environment required):

```sh
bash tools/run_gpu_demo.sh --preflight
bash tools/run_gpu_demo.sh 60
```

This explicit profile keeps YOLOE-26m/640×480 and navigation depth240×180, uses
an isolated Triton/CUDA raycasting worker, and requests primary5/navigation30Hz.
The CPU demo remains available with run_long_demo.sh. Request rates are ceilings;
actual source-ready control/motion and p95/p99 must come from each run's artifacts.
GPU failures stop the dependent lane; no implicit CPU fallback. See
[gpu mapping design](gpu-mapping-design.md) for bounds and current validation.

### Giữ cố định goal khám phá

Runtime `Navigator` mặc định giữ nguyên ID và tọa độ world XY của goal đã chọn.
Frontier đổi hình dạng/ID, đích khác gần hơn hoặc hết thời gian hysteresis không
làm đổi goal. Đường đi được lập lại trên NavMap mới tới cùng tọa độ. Khi robot
cách tọa độ đã chốt không quá **0.05 m (5 cm)**, một tick dừng ghi nhận đạt đích;
tick kế tiếp mới chọn goal mới. Reset episode xóa commitment của episode cũ.

Nếu goal/đường đi thiếu free-space, floor support hoặc clearance, robot dừng và
chờ đường tới cùng goal hợp lệ trở lại. Guard veto giữ goal và áp dụng cooldown
map revisions hiện có trước khi thử lại. Ngoại lệ được người dùng cho phép:
**>=8 giây bị chặn bởi lý do hình học, >=20 map revisions mới và không tiến gần
goal thêm 3 cm** => đánh dấu thất bại, giữ failed-ID/spatial cooldown, xóa goal
thất bại; tick sau mới chọn goal khác. Đây là xác nhận không tiến triển kéo dài,
không phải bằng chứng toán học rằng mọi đường trên toàn scene đều bất khả thi.
Tiến gần thêm 3 cm đặt lại cửa sổ theo dõi; lặp cùng map revision không tăng bộ
đếm. Stale depth/nav, lỗi clock, Pause hoặc các lý do không hình học không kích
hoạt cơ chế này. Không ghi nhận goal thất bại là đã tới/đã khám phá.

UI giữ marker **HELD GOAL** khi đang bị chặn, bỏ route không thể thực thi và ghi
lý do upstream cụ thể thay vì nhãn actuator tổng quát `expired_or_zero`. Trạng
thái Pause/Stop vẫn ẩn goal. `summary.json` -> `runtime.metrics.navigation` lưu
reason counts, goal ID/XY, route availability, frontier count và lần thất bại
cuối để chẩn đoán lượt sau. Counts tối đa65nhãn, bão hòa số đếm; không giữ lịch sử
map/goal vô hạn. TTL 300 ms, RGB-D/pose binding, footprint và kiểm tra đường đi
vẫn áp dụng. Cần khởi động lại demo đang chạy để nạp thay đổi code.
Nếu control bỏ qua vì Pause/chờ source/exception, hoặc hai quan sát hình học cách
nhau hơn 1 giây, cửa sổ xác nhận thất bại được đặt lại; thời gian thiếu evidence
không được tính thành thời gian goal bị chặn.

### Khoảng kiểm tra depth phía trước: 10 cm

Theo yêu cầu người dùng, `MotionGuard` mặc định kiểm tra trước **0.10 m**, thay cho
0.30 m. Khi quãng đường lệnh `v × command_horizon` lớn hơn 10 cm, kiểm tra đủ quãng
đường đó (`max(0.10, v × horizon)`). Khi chỉ quay, kiểm tra footprint tại chỗ.
Bán kính robot, margin, swept margin, TTL, unknown rejection và kiểm tra đường đi
không thay đổi. Profile demo hiện tại dùng bán kính0.20m+margin0.05m và horizon
100ms. Đây là thay đổi hành vi được cho phép, không claim parity30cm cũ.

### Best view của object đang chọn

UI vẫn nhận tối đa3ảnh preview để giữ publication gọn. Khi chọn object khác,
Qtprocess đọc crop đã commit của chính object đó từ kho assets ở chế độ read-only;
không phụ thuộc object có nằm trong3preview hay đã verified hay chưa. Gallery
được xếp theo chất lượng như trước;ảnh chất lượng thấp vẫn được hiển thị nếu đó
là evidence đang có. Nếu ảnh đứng đầu bị lỗi/mất,thử evidence tiếp theo. Trường
hợp không còn crop hợp lệ sẽ báo unavailable,không lấy ảnh object khác thay thế.

Chỉ cache1crop,bounded8MB;kiểm tra hash,source/episode/clock,canonicalalias và
revision với publication đang pin. Crop đọc trên UIprocess,không chạy inference
hoặc chặn control. Restart demo để Qtchild nhận đường dẫn assets và code mới.

### Demo zoom 150%

Qtchild được phóng thêm1.5× so với scale hệ thống hiện có (`QT_SCALE_FACTOR` chỉ
được nhân trong môi trường child). Chữ,nút,ảnh và nội dung vẽ cùng được scale;
không chỉ tăng kích thước cửa sổ ưu tiên. Qt vẫn giới hạn cửa sổ theo diện tích
màn hình khả dụng. Restartdemo để nhận zoom mới;host/control không đổi scale.
