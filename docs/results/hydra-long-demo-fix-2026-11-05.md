# Hydra: kiểm tra và sửa đường chạy dài — 2026-11-05

Worktree thực thi: `.runtime/worktrees/Kiet_branch2`, branch `Kiet_branch2`.
Giữ nguyên source/environment của checkout `Kiet_branch`. Không commit/push.

## Phạm vi và invariants

Hydra sở hữu Scene Graph/object/room; NavMap, frontier planner, controller và
collision/clearance guard hiện tại tiếp tục sở hữu chuyển động. Không tăng TTL
300 ms, horizon 100 ms hoặc tốc độ; không dùng semantic GT/navmesh occupancy
làm đầu vào runtime. Map 5 cm, depth sampling stride 1, free-ray stride 1 và
4 raycast workers giữ nguyên. Một native/GPU/performance workload tại một thời điểm.

## Bằng chứng mới

Artifact chung: `.runtime/hydra-long-demo-fix-20261105/` trong worktree này.
Các số bên dưới là run mới; không thay thế outcome của artifact lịch sử.

| Run UI-on / 00805 | Outcome | Dịch chuyển LB | Hydra revision | Freshness misses | Proof executed thiếu |
| --- | --- | --- | --- | --- | --- |
| Baseline 30s, primary 5 Hz | completed | 0.217 m | 6 | 9/84 = 10.71% | 0 |
| Candidate 30s, primary 1 Hz | completed | 1.326 m | 7 | 6/185 = 3.24% | 0 |
| Candidate 60s, primary 1 Hz | incomplete: UI crash | 2.377 m | 14 | 9/341 = 2.64% | 0 |

`baseline-ui-30s`, `primary1-ui-30s`, `primary1-ui-60s` chứa recording,
measurements, control invocations, native graph/export manifest và UI metadata.
60s: 399/399 recording frames; native graph export verified; 322 executed;
6 source pending, 1 expired-before-step, 12 zero/expired stops. Không có bước
executed sau command deadline hoặc source TTL khi đối chiếu từng pre-step timestamp.
Control interval p95 328.337 ms; source age p95 281.265 ms; map update p95/max
192.4/416.0 ms. RSS 664/664 supported, zero missing/read errors, sampled peak
1,937,940,480 bytes. GPU memory provider vẫn unavailable; không chứng nhận
absolute memory boundedness.

So sánh 30s chỉ là một cặp, chưa chứng minh cải thiện dài hạn. Primary capture
5 Hz từng chiếm 85/86 vòng sensor-owner trong baseline dù Hydra chỉ nhận 6
update; 1 Hz giảm capture/IPC/decode cạnh tranh và cho 187 navigation/29 primary
captures trong candidate 30s. Không giảm fidelity NavMap hoặc thay movement policy.

60s vẫn không đạt gate freshness ≤1%; max consecutive misses 2. UI crash có
stack cụ thể: `spatial_scene.py:mouseMoveEvent` truy cập `row.label` trên Hydra
row `SimpleNamespace`. Không được coi native export thành công là toàn run pass.

## Đã triển khai và kiểm tra correctness

- Interpreter probe Hydra dùng configured startup timeout (10s), thay hardcoded
  3s. Chỉ startup; không đổi motion TTL. Probe cũng từ chối setup script trả nonzero.
- Tooltip đọc label canonical trong node dict cho cả Hydra/legacy; regression
  gửi QMouseEvent thật tái hiện lỗi trước sửa. Focused UI: 4 passed, exit 0.
- Snapshot session sao chép độc lập graph summary, transform và layer counts;
  reader không thể sửa graph canonical dưới cùng revision/input prefix.
- Rejected native step trả `last_source` của frame accepted gần nhất.
- `HydraGraphRuntime.scene_graph_query()` đọc đúng một accepted snapshot;
  `Pipeline.scene_graph_query()` chuyển giao reader ngoài pipeline control lock.
  Không đọc GUI, gọi child, chọn goal hoặc cấp ID mới.

TDD logs: `probe-timeout-{red,green}.log`, `query-wiring-{red,green}.log`,
`coordinator-query-red.log`, `review-fixes-{red,green}.log`,
`rejected-source-red.log`, `focused-final.log`, `ui-hover/`, `objectnav-query/`.
Focused cuối cho query/probe/hover: 29 passed, exit 0; các session/runtime/
projection regression trước đó: 52 passed, exit 0. Không cộng số test các tập
chồng lấn thành tổng test riêng biệt.

## API phục vụ ObjectNav: phần đã có và giới hạn

```python
query = pipeline.scene_graph_query()
if query is not None:
    for candidate in query.objects("chair"):
        # semantic hypothesis; centroid chưa phải một free navigation goal
        print(candidate.node_id, candidate.position_xyz_m, candidate.room_id)
```

Query dùng numeric semantic ID trong labelspace/taxonomy đã pin; không đoán
class từ display name. Unknown/invalid/missing label bị loại. Có ID Hydra,
XYZ canonical Z-up, structural room ancestry, revision/input prefix, source,
calibration và vocabulary/labelspace provenance. Thiếu/cycle parent chain thì
membership unavailable. Stale/replay-required/failure/missing XYZ không được
đánh dấu usable_for_targeting. Một query là snapshot; consumer phải lấy snapshot
mới và kiểm tra revision khi quyết định hành động, không giữ nó làm authority
vĩnh viễn. `get(id, expected_revision=...)` từ chối ID/revision không khớp.

`usable_for_targeting` chỉ diễn tả graph hypothesis đủ dữ liệu, không chứng nhận
reachability. `navigability='unvalidated'`, `membership_kind='structural_not_navigation'`.
Confidence, verification, lifecycle và per-object evidence chưa có. Source
provenance hiện là toàn input prefix, không giả làm quan sát gần nhất của từng object.

Đã reload native `.sparkdsg` của 60s, kiểm tra SHA graph/journal khớp manifest,
và query được 8/8 layer-2 objects (bed, bench, kitchen island, mirror, desk,
wardrobe, storage box ×2), cả 8 có structural room assignment. Offline replay
được đánh stale và mọi candidate đều non-targetable. Artifact:
`primary1-ui-60s/native-query-{summary,evidence}.json`; lệnh và exit 0 nằm ở
`native-query-{reload,check}.log`. Đây không phải đánh giá semantic accuracy hoặc
thành công ObjectNav.

## Kiểm chứng toàn dự án và phần còn mở

Full CPU command:

```bash
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests QT_QPA_PLATFORM=offscreen \
  .venv/bin/python -m pytest -q
```

Lần đầu: **32 failed, 2471 passed, 10 skipped**, 216.23s, exit 1;
`full-suite.log`. Snapshot được thu thập trước các regression review bổ sung;
không suy suite hiện tại xanh từ focused tests. Đang phân loại root cause.

Gate giữ nguyên: smoke 30/60s sau fix → hai 120s completed/clean liên tiếp,
100% executed proof, không stale executed command, freshness miss ≤1%, không
≥3 misses liên tiếp, control interval p95 ≤415ms → 300s → 600s. Chưa đạt gate
này thì không báo demo dài đã sẵn sàng. Tối ưu log-odds phải qua exact parity,
warmup đầy đủ và replay timing trước khi đưa vào native campaign.

Để hoàn thiện ObjectNav sau ổn định runtime: (1) đánh giá object identity,
semantic class/XYZ/room và split/merge trên nhiều map; (2) thêm per-object
observation/evidence freshness và uncertainty; (3) tạo approach/view pose trên
measured free NavMap với clearance/path guard, không đi vào centroid object;
(4) target verification/reacquisition và bounded recovery khi mất target;
(5) đánh giá episode success/SPL/collision/latency bằng evaluator offline.
Giữ frontier hiện tại làm exploration fallback; các mục này chưa phải code đã triển khai.

## Checkpoint bổ sung: exact kernel và evaluator

Exact fused log-odds kernel đã nối vào `_apply_log_odds`, warm trước capture;
layout chưa warm dùng NumPy fallback và không JIT trong frame. Ba cặp replay
luân phiên trên cùng 27 recorded sources khớp mọi vote/full-map/floor/clearance
hash. Mỗi candidate có 342/342 calls accelerated, zero fallback và signature
set không đổi. Focused 10 passed; main bổ sung spy xác nhận warmup hook thực sự
được gọi, 10 passed / 4.75s / exit 0. Independent Luna review không tìm thấy
blocker trên default mapper call path. Low-level helper giả định tile storage
và vote masks là allocations riêng, đúng với default collector; custom caller
không được cung cấp buffers chồng lấn.

Target-frame log-odds p50/p95 4.524/5.180 → 2.020/4.463 ms; toàn update không
cải thiện nhất quán. Không báo đây là fix live tail. Artifact replay và hashes:
`map-audit/hotframe-kernel-ab.json`, `map-audit/README.md`.

Native sau kernel: `kernel-primary1-ui-30s`, completed/exit 0; 170/170 frames,
0.788 m, 125 executed và zero missing proof/timing violation; UI shutdown sạch.
Freshness 5/140 = 3.57%, consecutive max 2; interval p95 405.355 ms; source age
p95 303.625 ms; trajectory extent 0.661 × 0.388 m, 3 distinct goals. **Không đạt
gate dài**. Local arithmetic optimization chưa giải quyết scheduling/latency
của hệ thống thực tế.

Đã sửa evaluator đọc schema producer hiện tại: RSS sample trace v1 được kiểm
tra closed fields/cap/accounting/timing/support provenance; control diagnostics,
versioned navigation diagnostics và stage events được kiểm tra chặt. Không
thay proof source, endpoint, deadline, TTL hoặc native-eligibility checks.
`moving_artifact()` fixture cũ thiếu các trường NavigationDecision khiến
producer từ chối record; đã dùng NavigationDecision đầy đủ thay vì nới validator.
Focused `tests/test_evaluation_measurements.py`: **65 passed**, 2.59s, exit 0.

Đã gọi `inspect_measurements` trên artifact 60s và kernel30s thật: cả hai pass;
evaluator offline tái tính translation LB 2.377345914 m / 323 attached proof
records và 0.788216648 m / 126 records. Support này gồm proof của command bị
expiry; không đồng nghĩa số executed commands (322 và125).

Các tests UI giả đã cập nhật để thực hiện ACK render và shutdown, thay worker
ngủ không đọc publication. Test cố ý timeout vẫn yêu cầu worker/threads được
reap, không ép final render thành công sau khi đã kill child. Shipped worker
pins trong ba YAML và live.example đồng bộ source. Regression liên quan:
**52 passed**, 5.22s, exit 0 (`ui-contract-green.log`). Full suite mới chưa chạy
lại sau tất cả các sửa này.

Thử nghiệm cadence tiếp theo (`candidate-lowload.json`): primary RGB-D 0.5 Hz,
UI publication1 Hz; navigation10 Hz, geometry/depth fidelity và control safety
không đổi. Hai cadence đổi cùng nhau nên không quy toàn bộ tác động cho một
thành phần. Chưa promote default; cần runtime gates.

Low-load smoke `lowload-ui-30s`: **completed, exit0**, 232/232 frames,
1.642139425m, 205 executed, zero missing proof/timing violation; freshness
1/214 =0.4673%, consecutive max1; control interval p95 236.228ms, source age
p95 213.217ms. Trajectory extent0.792×1.196m,4 distinct goal IDs. Hydra revision7
(4 objects,34 places,1 room,1 building), UI final revision7/point-cloud source
match/clean shutdown. Một pending event vẫn được tính; không bỏ event vì ở gần
deadline. Đây là smoke đạt gate, không chứng minh120/300/600s.

## Điều chỉnh cách đếm và checkpoint tiếp tục

Phát hiện khi profile: chỉ đếm `navigation_source_pending` và
`expired_before_step` bỏ sót zero-motion stops có command reason `depth_stale`.
Các số cũ phía trên là **subset pending/expiry**, không phải toàn bộ freshness
refusals. Assessment script đã mở rộng cách đếm, giữ nguyên denominator của
actual control invocations và tính mỗi event một lần: pending, expired-before-step,
deadline-expired hoặc command reason depth/nav stale. Không loại event cuối run.

- Primary1/60s:9/341 (2.64%), gồm2 depth-stale stops ngoài7 đã báo.
- Kernel-primary1/30s:8/140 (5.71%), gồm3 stale stops ngoài5 đã báo.
- Lowload/30s:1/214 (0.47%), không thay đổi.
- Lowload/60s:8/344 (2.33%), gồm2 stale stops ngoài6 đã báo.

Lowload60s completed/exit0,2.816607925m,324 executed,zero missing proof/timing
violation, trajectory extent1.099×1.614m,5 distinct goals; final UI revision12,
28,723 measured cloud points, graph/cloud source match, clean shutdown. Không
đạt gate dài. Map publication sauTTL và control/actuation expiry là hai đường
riêng; tối ưu map đơn lẻ chưa đủ. `allow_fresh_map_lag` còn tắt: map trước tại
một số miss đã hết TTL hoặc chỉ còn13.6–48ms, và dùng lag phải tính local votes
cho depth mới. Chưa bật để tránh tuyên bố lợi ích chưa đo.

Full CPU sau vòng sửa đầu: **3 failed,2523 passed,10 skipped**,221.64s,exit1
(`full-suite-after-fixes.log`). Đã sửa hai stale fixture: probe test kiểm tra
setup-dependent module thật; cadence test đối chiếu actual invocations cộng
explicit terminal deadline skip. Focused3passed/5.99s/exit0.
Lỗi còn lại là evaluator chưa nhận producer `run_deadline_skips`.

Đã sửa review RSS: complete v1 trace tái tính đúng aggregate peak/support/error/
time, dropped trace chỉ cấp retained lower bounds; xử lý sampled-at rollback và
không tính discarded-after-stop rows. Reader control invocations kiểm tra chặt
skip counters/source, vẫn nhận legacy artifact thiếu field. Focused evaluation
và CPU execution-proof integration: **85 passed**,5.12s,exit0, log
`rss-review-fix/focused.log`. Strict inspection/control reader trên lowload60s và
profilev2 native artifacts đều pass. Chưa có full-suite pass cuối.

Diagnostic wrapper riêng trong `live-profile/` đã chạy hai30s native probes,
exit0, không đổi command/geometry/TTL. Spans bounded10,000; v1 giữ6,785 records,
v2 giữ8,184, zero dropped. Đây không phải performance acceptance runs.
V2 active phase: raycast chunk wall/CPU p50≈30.5/29.6ms, p95≈51.3/47.9ms;
Hydra offer CPU≈96–110ms; frame serialization CPU≈35–41ms; journal CPU p95≈32ms;
UI encode CPU p95≈42ms. Wall-minus-thread-CPU không tự chứng minh GIL, và không
có child-process CPU attribution. Có bằng chứng encoder/journal lặp công việc
trên payload lớn; candidate tiếp theo là tái sử dụng JSON literal đã escape,
đòi byte-identical request/journal, input-prefix hash không đổi và retained
serialized buffers được tính đủ vào32MiB queue budget. Chưa promote candidate
hoặc tuyên bố nguyên nhân scheduling đã được giải quyết.

## Wire candidate: correctness và smoke

Tái sử dụng escaped JSON literal cho worker request và journal selected_frame;
byte output so với legacy oracle giữ nguyên, không đổi protocol/prefix/geometry.
Queue charge gồm raw serialized payload + literal, tối đa32MiB cho pending và
in-flight; frame object/transient assembled request vẫn ngoài scope này và RSS
chỉ là sampled peak. Buffer hoàn tất được thả trước condition wait. Native pipe
partial writes dùng memoryview thay vì copy toàn suffix bytes ở mỗi lần ghi.

- TDD wire RED → GREEN; Hydra-focused88passed/exit0.
- Microbench cùng máy, payload4,917,463B,5 repetitions và byte equality trước
  timing: median legacy39.80ms, reuse27.15ms (~1.47×); `wire-reuse/microbench.json`.
- UI size bound dùng worst-case ASCII/Unicode bound không tạo escaped copy lần
  hai; byte cap/stream fallback/wire unchanged. Focused5passed/exit0.
- Probe shell đồng nhất `set -eo pipefail` với native child: setup lỗi giữa file
  không được che bởi command thành công cuối. RED đúng lỗi;10passed/exit0.
- Full suite checkpoint trước memoryview: **2554passed,10skipped**,180.03s,
  exit0 (`full-suite-final.log`). Sau memoryview,38 session/wire/runtime/query
  regressions passed,6.08s,exit0. Cần full-suite cuối nếu còn thay source.

`wire-ui-30s`: completed/exit0,218/218 frames,1.365m;2/200 freshness refusals
=1.00% (tính cả stale stop), consecutive max1,source-age p95 233.342ms,
interval p95 267.409ms,zero executed proof/timing violations.

`wire-ui-60s`: completed/exit0,456/456 frames,3.077198510m;3/423=0.7092%,
consecutive max1,406executed,zero missing proof/timing violations. Source-age
p95 212.605ms,interval p95 239.045ms;extent1.261×1.614m,6 distinct goal IDs.

Các run wire và live-profile thuộc clock domain/boot mới
`host_monotonic:5d8eb483-b6f5-4c4c-9e21-3d047dc8da57`, khác nhóm baseline/lowload
cũ `host_monotonic:9d3027d1-c30b-48ca-850d-dda66aad4464`. Không quy chênh lệch
latency chéo boot cho patch. Microbench là so sánh cùng máy; native campaign
mới dùng gate tuyệt đối và các repeated runs, không suy causal A/B.

Candidate config vẫn riêng: `candidate-wire-reuse.json`; source closure ở
`wire-native-source-hashes.json`. Đã bắt đầu120s-a sau smoke60 đạt gate; chưa
coi300/600s sẵn sàng cho tới hai120s đạt liên tiếp.

## Stress120s và các candidate không promote

`wire-ui-120s-a` completed/exit0,686/686frames,4.392326255m,581executed,
zero missing proof/timing violations. Nhưng **30/625 freshness refusals=4.8%**,
consecutive max5,source-age p95 300.779ms,interval p95 342.805ms. Breakdown:
16pending,4expired-before-step,10depth-stale zero stops. Extent2.946×1.335m,
8 distinct goals. Gate fail; không chạy300/600s. Map median đầu→cuối82→114ms,
raycast45→61ms,prepare19→26ms; vote p95 theo30s windows19/21/64/46ms.
Đây là workload/latency scaling, không chỉ startup. Native Hydra accepted25
inputs/120s; journal service median mỗi30s khoảng4.2–5.0s, max6.68s.

Các probe sau chỉ là thử nghiệm, không promote default:

| Candidate | Outcome | Translation | Full freshness refusals | Quyết định |
| --- | --- | --- | --- | --- |
| Nav5Hz /60s | completed |1.961m|8/268=2.99%| Không đạt, còn chậm hơn; giữ riêng candidate-nav5.json |
| Fresh-map-lag /30s | completed |1.410m|38/246=15.45%| Không đạt; flag vẫn tắt trong candidate chính |
| Nice+10 cho Hydra child /60s | completed |2.241m|6/354=1.69%| Không đạt; wrapper chỉ là OS experiment |

Cả ba không thiếu executed proof/timing violation. Nice probe chỉ hạ priority
Hydra child của chính run, parentnice0/childnice10 được kiểm tra sau ready,
/usr/bin/nice và wrapper được hash ở `nice-probe/priority-manifest.json`.
Không đổi process của người dùng; không đưa priority knob vào product.

Fresh-map-lag đã được kiểm tra bổ sung với real NavMapper/MotionGuard: obstacle
mới chặn dù prior map free, pose hiện tại + cả hai TTL/horizon được giữ, stale
map chặn dù depth fresh, concurrent future-map update không đổi pinned map
hoặc current-frame coverage. **15passed/exit0**. Không có product safety bug
trong các cases này; runtime tệ hơn vì map deadline cũ quá gần và cần local
coverage. Không nới TTL để làm option này pass.

Candidate hiện đang thử: `candidate-hydra01.json`, chỉ thêm
`workers.hydra.fps_limit_hz=0.1` vào wire profile (nav10Hz,primary0.5Hz,UI1Hz).
Lý do: service Hydra4–6s/input làm worker gần như bận liên tục; giảm camera xuống
0.5Hz vẫn cao hơn throughput native, không tạo idle. Rate0.1Hz tạo CPU budget
nhưng làm graph live thưa hơn; mỗi selected frame vẫn đầy đủ pixels, calibration,
semantic labels và source provenance. Raw recording không cắt frame vì cap này.
Chưa có kết quả để promote; cần báo selected/fps-limited counts và chưa coi
ObjectNav semantic/room accuracy đã đạt.


## Diagnostic 300s được người dùng cho phép — kết quả cuối

Người dùng chọn chạy300s chẩn đoán dù có thể fail gate1%; giữ nguyên mọi guard.
Đây là ngoại lệ về thứ tự thử nghiệm, không phải thay đổi tiêu chí acceptance.
Artifact: `.runtime/hydra-long-demo-fix-20261105/diagnostic-ui-300s/`;
profile bền vững: `configs/demo-00805.hydra-diagnostic.local.json`.
Không chạy600s.

| Chỉ số | Kết quả thực đo |
| --- | --- |
| CLI / outcome | exit1 / incomplete |
| Recording |1353/1353 frames, complete |
| Translation lower bound từ proof |6.723785844m |
| Executed commands |942; thiếu proof0; timing violation0 |
| Freshness/deadline refusals |247/1207=20.46396%; liên tiếp tối đa11 |
| Control interval p95 |423.811ms |
| Source age p95 |319.558ms |
| Trajectory extent XY |4.458×1.983m |
| Accumulated measured map |18.0825m² known;10.785m² free; không phải GT coverage |
| Native Hydra |revision40;15objects;76places;1room;1building;247edges |
| UI |final publication295 rendered, graph/cloud source khớp |

Refusals gồm162 navigation_source_pending,10 expired_before_step,
67 depth_stale và8 deadline_expired.18 zero-motion khác không tính là freshness
miss. NavMap update median theo100s tăng103.7→131.4→141.8ms; p95 tương ứng
223.0→300.7→408.3ms. Điều này chứng minh pipeline hiện tại chưa duy trì cadence
khi chạy dài; chưa chứng minh một nguyên nhân đơn lẻ như GIL hoặc Hydra là thủ phạm.
Giảm nav FPS, bật fresh-map-lag, hạ nice Hydra hay cap Hydra0.1Hz đều không đạt
trong các run thử; không promote các candidate đó. Codec byte-identical đã giảm
chi phí serialization trong microbench nhưng codec30s vẫn3/172=1.74% refusals.

Recording, native export, UI và worker shutdown hoàn tất sạch. Tuy nhiên RSS chỉ
1759/1760 samples supported: một ScopeDeadlineError ở initial_census:thread_children,
khoảng1.39s sau control cuối, làm resource certificate incomplete và CLI exit1.
Sampled RSS peak2,207,571,968B; không có absolute peak/boundedness proof và GPU
memory provider chưa khả dụng. Không đổi historical outcome thành pass.

Graph export SHA256:
`462e740ef6cec825cefdc7f1d4219f76ed5b0bf8e5e51c4833930cdeda70cf10`.
Native reload + host query kiểm chứng15/15 object có numeric category, position,
room ancestry và graph/source/calibration provenance, exit0. Replay được đánh dấu
stale nên không usable_for_targeting. Đây không phải kiểm chứng semantic accuracy,
room accuracy hoặc ObjectNav end-to-end. Một native room không đủ để kết luận
segmentation sai nếu chưa có evaluator/GT offline.
Observer UI độc lập chỉ quan sát khoảng115s cuối; max graph update gap15.079s
chỉ thuộc đoạn đó. UI point cloud là measured RGB-D cloud (~72,359 điểm ở mẫu
cuối), không phải mesh TSDF native Hydra.

## Giảm rủi ro ở export sau diagnostic

`_selected_accepted_inputs` trước đây read_text/splitlines toàn journal rồi giữ
payload của nhiều event; journal300s đạt196,800,658B. Parser mới đọc binary từng
physical line (cap32MiB), tiêu thụ event ngay, giữ source metadata/hash/byte count
và accepted manifest entries. Malformed/oversize fail closed; không truncate.
Oracle kiểm chứng selection/order/UTF-8/hash tương đương; TDD4failed/3passed trước
sửa,7passed sau; related33passed/exit0. Probe20MiB: peak tracemalloc giảm từ
41,989,372B xuống3,163,856B. Evidence: `export-stream/verification.json`.
Đây là correctness-verified và giảm rủi ro memory/GIL khi shutdown; chưa runtime-
validated trên run300s và chưa chứng minh là nguyên nhân của RSS timeout trên.

## Hướng tiếp theo đề xuất, chưa triển khai

Ưu tiên thiết kế tách local safety khỏi full world-map update. Hiện control phải
chờ full NavMap của đúng source rồi còn planner/guard; phần thời gian còn lại của
TTL300ms quá ít khi map lớn. Một local-clearance lane từ depth+pose mới có thể
chứng nhận chuyển động ngắn; world map/planner cập nhật bất đồng bộ làm ngữ cảnh
chọn frontier. Cả hai cần source/revision/TTL riêng; world map cũ không được trở
thành chứng nhận motor mới. Giữ unknown khác free, floor/footprint/clearance,
collision filtering, deadline/horizon và proof. Không chỉ tăngTTL để che latency.
Đây là thay đổi contract cần thiết kế/review và tests obstacle mới, stale source,
pose mismatch, concurrent map update, shutdown trước khi demo; chưa được thực hiện
trong diagnostic này. Đo capture→local clearance→guard→actuation riêng, map scaling
và CPU contention để chốt implementation thay vì tiếp tục chỉnh FPS đơn thuần.

Để thành module ObjectNav hoàn chỉnh còn cần: evidence/confidence/lifecycle theo
object, canonical alias/merge policy, free approach pose, target verification,
semantic/room accuracy evaluator offline và nhiều scene. Query API hiện tại chỉ là
nền tảng có provenance, không tự chứng nhận navigability hay target success.
Không có600s readiness, multi-map quality hoặc long-run acceptance pass.


### Verification tiếp tục ngày2026-11-06

Lượt full-suite `full-suite-post-diagnostic.log` bị gián đoạn trước summary khi
phiên công cụ kết thúc; không tính là pass. Đã chạy lại toàn bộ suite trong
`full-suite-resumed-20261106.log`, exit code ghi riêng cùng tên `.exit`.
Window assessment300s được sửa để tính cả diagnostics.failure_detail=
`deadline_expired`; source-capture windows0–100/100–200/200–300s lần lượt
37/477,74/378,136/352 refusals, tổng247/1207. Stage statistics dùng cùng mốc
source capture đầu tiên. Không thay raw trace hoặc historical run outcome.
ResourceSampler.snapshot chỉ shallow-copy aggregate và provider diagnostics chỉ
thu lúc cleanup; chưa thấy bằng chứng growing deep-copy trace trong control loop.


Full verification ngày2026-11-06:
`env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ./.venv/bin/python -m pytest -q`
→ **2580passed,10skipped,201.15s,exit0**. Log:
`.runtime/hydra-long-demo-fix-20261105/full-suite-resumed-20261106.log`.

Offline parser mới trên journal thật196,800,658B →40/40 selected_inputs exact
match với historical export manifest; elapsed1.681s, tracemalloc peak15,547,969B,
exit0. Artifact `export-stream/real-300s-journal.json`. Không nạp lại native Hydra,
không chạy lại300s; không chứng minh RSS runtime timeout đã hết.
`git diff --check` exit0. Những phần chưa chứng minh: long-run performance gate,
native resource completeness sau export fix, semantic/room accuracy và ObjectNav
end-to-end. Các thay đổi và evidence chỉ nằm trong worktreeKiet_branch2.
