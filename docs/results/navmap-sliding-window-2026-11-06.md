# Rolling NavMap — triển khai, đo và cấu hình đề xuất / 2026-11-06

**Kết luận:** chọn thử nghiệm bán kính2m, lưu10s kể từ lần đo cuối của từng
component. Đã implemented, correctness-verified và native runtime-validated;
**chưa đạt gate freshness≤1%**. Chỉ thay đổi trong worktreeKiet_branch2.

Profile: `configs/demo-00805.hydra-rolling.local.json`, SHA256
`04b34a630483cb6e625589585097959c38f762d83a4605c6b58b551d161d4d54`; byte-identical với profile2m/10s được đo.
Không âm thầm thay profile default/long-demo cũ. Artifacts:
`.runtime/navmap-window-20261106/`.

## Hành vi đã triển khai

- Optional `navigation.mapper.local_retention_s`; absent giữ legacy. Window
  vuông cùng tâm navigation camera như NavSnapshot hiện tại; radius2m tạo
  raster81×81 ở5cm/cell, khoảng4.05×4.05m.
- Crop vote integration vào window; ngoài window bị clear/evict, không archive
  rồi load lại làm FREE. Full measured ray collection, stride1, thresholds,
  floor datum/calibration, Hydra và frontier/controller không đổi.
- Planar occupancy, floor và từng height voxel có last-observed timestamps riêng.
  Sau10s không được đo lại, component trở thành NaN/unsupported→UNKNOWN;
  một phần được đo mới không gia hạn phần khác. Không decay odds về FREE.
  Đây là expiry lần đo gần nhất, không cam kết mọi log-odds contribution trẻ
  hơn10s. Cập nhật liên tiếp tạo progressive forgetting, không reset toàn map.
- Fresh depth bootstrap, sourceTTL300ms, command horizon100ms, cylinder/clearance,
  collision filtering và proof vẫn bắt buộc. Map-memory age không phải controlTTL.
- Rolling frame dedup dùng per-sensor watermarks thay full frame-history set.
  Timestamp0 hợp lệ; equal capture stamps với distinct increasing FrameKeys hợp
  lệ; rollback/clock mismatch/episode mismatch bị reject trước mutation.
- UI `Accumulated map` vẫn là lịch sử riêng và có thể giữ ô cũ; nó không phải map
  mà MotionGuard đang dùng. Hydra graph/point cloud dài hạn không bị xóa theo ROI.

## Ma trận và cách đo

Screen9 tổ hợp radius1/2/3m × age3/10/30s, cùng legacy2m/no expiry ở đầu và cuối.
Mỗi trial152/1211 sources (every8), span318.52s. Sampling giữ timestamp intervals,
có thể làm TTL thiếu ngữ cảnh hơn full rate; không suy freshness live từ replay.
Baseline p50/p95 đầu52.45/61.21ms, cuối45.17/56.40ms cho thấy host variability.

Full replay3 shortlist,1211/1211 raw navigation inputs, source span319.012s,
candidate/reference xen kẽ mỗi source. Raw recording của active300s có1 startup
capture không submit vào live NavMap; vì vậy đây là matched raw-source experiment,
không exact replay live control. Chênh1 footprint frame không đủ để chọn retention.

Source boot cũ có thể numerically future trên boot mới: harness dùng private
`replay:` clock domain, giữ nguyên numeric capture stamps/intervals và lưu riêng
original domain/hash. Không republish thành live source. Probe thất bại ban đầu
và probe sau fix2frames/exit0 được giữ trong artifacts.

| Full replay | Candidate p50/p95 | Paired legacy p50/p95 | Footprint-supported | Max tile-array bytes incl timestamps |
| --- | --- | --- | --- | --- |
|1m/10s|51.85/72.45ms|55.90/76.41ms|1209/1211|6,242,304|
|2m/10s|62.11/93.08ms|62.24/95.44ms|1209/1211|9,363,456|
|2m/30s|51.67/62.13ms|51.17/63.39ms|1210/1211|9,363,456|

Không so93ms với62ms giữa hai trial khác nhau để khẳng định30s nhanh hơn:
paired baselines cũng khác. Lợi ích latency offline nhỏ;1m giảm planner context.
State agreement là độ giống legacy trên common cells, không phải accuracy/GT.

Screening cho thấy NumPy retention/crop tốn4–7ms/frame. Đã thêm kernel fused
exact với independent scalar oracle; warm trước capture, C-layout entrypoint đã
compile, NumPy fallback cho unwarmed/strided/không cóNumba. Không per-frameJIT.
Full replay maintenance p50 khoảng1.3–1.7ms; không coi so sánh sparse/full này là
causal A/B speedup. Kernel không đổi vote/safety semantics.

## Native UI-on, cùng scene00805 và profile model/camera/cadence

| Run | Quãng đường tích lũy LB | Freshness/deadline refusals | Source age p95 | Control interval p95 |
| --- | --- | --- | --- | --- |
|baseline-60s|3.242m|0/437 = 0.00%|200.55ms|234.85ms|
|r1-t10-30s|1.349m|0/198 = 0.00%|205.08ms|262.16ms|
|r2-t30-30s|1.855m|0/231 = 0.00%|184.18ms|207.33ms|
|r2-t30-120s|5.072m|24/671 = 3.58%|287.62ms|316.11ms|
|r2-t30-300s|11.013m|128/1466 = 8.73%|306.10ms|363.08ms|
|r2-t10-120s|5.655m|18/718 = 2.51%|258.89ms|312.17ms|
|r2-t10-300s|10.719m|101/1584 = 6.38%|303.51ms|343.83ms|

Cả7CLI exit0/outcome completed; recording/export/UI/shutdown sạch. Không thiếu
executed proof, không executed pre-step sau command deadline/sourceTTL. Strict
measurement/control readers accepted7, full control trace khớp invocation totals,
trace dropped0; final rendered cloud source khớp graph. Schema inspection cố ý
không cấp native acceptance certificate.

**Chọn2m/10s trong các cấu hình đã đo**: giữ bán kính planner hiện tại; smoke2m
đi xa hơn1m trong lượt30s; đối chứng cùng2m ở120/300s có refusal fraction thấp hơn
30s trong các trial này. Cả hai300s vượt useful-progress8m gate.10s300s10.72m gần
30s300s11.01m, nhưng không dùng quãng đường làm bằng chứng coverage. Đây là lựa
chọn vận hành ban đầu, không phải statistical/universal optimum; mỗi livecandidate
chỉ1 trial ở một scene/seed, thứ tự/load có thể ảnh hưởng.

Selected300s: 1731 rawframes/recording complete,
1429executed proofs; trace411,156,480/536,870,912B,
dropped0. Hydra revision59:15objects/77places/1room/1building. Final publication300
rendered/source match. RSS2049/2049supported, sampled peak2,181,828,608B; không
absolute peak hoặc GPU-memory boundedness certificate.

Policy hoạt động thực: cuối300s4tiles,6,242,304B resident tile arrays gồm
4,194,304B timestamps;4tiles spatially evicted;138,771 spatial components bị
quên;1,203planar/137,561height/1,029floor components hết hạn. Spatial bound9tiles
cho profile này tương ứng≤14,045,184B arrays, không gồm Python overhead, scratch
votes, overview hoặc Hydra. Không claim RSS thấp hơn legacy: quỹ đạo ngắn này
legacy chỉ4.608MB arrays và không cần timestamps.

## Freshness chưa giải quyết hết

Selected300s theo source-capture windows (exclude raw startup khỏi origin):

| Đoạn | Refusals/control | NavMap p50/p95 | Retention p50/p95 | Raycast p95 |
| --- | --- | --- | --- | --- |
|0–100s|9/634|81.39/157.62ms|1.93/7.51ms|79.80ms|
|100–200s|42/478|105.58/246.99ms|1.92/9.98ms|158.94ms|
|200–300s|50/472|104.56/264.94ms|2.12/12.11ms|144.54ms|

Map đã bounded nhưng tail vẫn tăng; tích lũy tile không phải nguyên nhân duy
nhất. Full ray projection/raycast, sensor/IPC và scheduling vẫn nằm trên đường
control. Stage wall times có cả descheduling; chưa đủ bằng chứng quy toàn bộ cho
GIL hoặc một worker. Selected300s6.38% và max3 misses liên tiếp vẫn FAIL gate≤1%
và không≥3 liên tiếp;120s2.51% cũng FAIL. Không nớiTTL hoặc đổi denominator.

Diagnostic cũ20.46%/6.72m và run mới6.38%/10.72m thuộc boot/source/load khác;
không causal A/B chứng minh rolling tạo ra toàn bộ cải thiện. Baseline hiện tại
60s cũng đã0misses. Selected300s extent4.388×1.540m;30s-retention300s extent
4.210×2.048m. Quãng đường dài hơn không chứng minh khám phá rộng hơn. Không GT
coverage/semantic/room accuracy proof; Hydra vẫn1room, ObjectNav chưa hoàn chỉnh.

Bước tiếp hợp lý: thiết kế local current-depth clearance độc lập full NavMap
planning với provenance/TTL riêng, hoặc exact ROI ray traversal có oracle bảo
đảm mọi vote cần cho footprint. Chưa implement hai hướng này trong task hiện tại.
Không600s, multi-map readiness hoặc long-performance acceptance claim.

## Kiểm chứng và tái lập

TDD rolling: initial10missing-interface RED; GREEN24rolling regressions. Các
findings clipper đọc stale occupied trước expiry và reject equal timestamps đã
được sửa RED→GREEN. Mapping/guard+kernel52passed. Config/telemetry/stage có RED→GREEN;
harness metric tests ban đầu4passed không capturedRED, clock helper sau đó có
RED→GREEN5passed. Independent read-only safety và supplemental optimization
reviews/hash ở artifacts/review/; không có unresolved blocker.

Full suite:
`env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 ./.venv/bin/python -m pytest -q`
→ **2627passed,10skipped,172.09s,exit0**. Không sửa product source sau suite;
final source closure khớp `fused-source-hashes.json`. `git diff --check` exit0.

Từ worktreeKiet_branch2:

```bash
NEUSYMNAV_HYDRA_DEMO_CONFIG=configs/demo-00805.hydra-rolling.local.json \
bash tools/run_hydra_map_demo.sh 00805 120
```

300s vẫn là diagnostic khi gate chưa đạt. Harness `tools/measure_navmap_window.py
--help` có recording/config/output/radius/retention, sampling và paired reference.
Lệnh thực tế/rawframe/per-frame timings ở artifacts; kết quả cuối:
`native-results.json`, `selected-300s-windows.json`, `strict-native-validation.json`,
`final-verification.json`, ledger `progress.md`. Không commit/push/install/download.
Accidental harness copy vào checkout nguồn đã được di chuyển ngay và parent
absence được kiểm tra; không surviving source edit ởKiet_branch.
