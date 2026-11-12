# Hydra long demo — báo cáo hiện trạng và kế hoạch triển khai

> **For agentic workers:** Khi được giao triển khai, dùng `superpowers:executing-plans` hoặc `superpowers:subagent-driven-development`, thực hiện lần lượt các gate bên dưới. Tài liệu này không tự cho phép sửa runtime hoặc chạy campaign.

**Ngày:** 2026-11-05. **Branch:** `Kiet_branch2`.

**Goal:** Demo Hydra 3D Scene Graph có mesh/cloud, objects/places/rooms và robot khám phá liên tục; kiểm chứng300s rồi600s trên00805 trước khi mở sang map khác.

**Architecture:** Giữ Hydra là owner Scene Graph/phân phòng, Python binding trong child process. Giữ frontier policy, planner và controller hiện tại; giảm latency và hoàn thiện display adapter, không thay movement bằng trajectory generator của Hydra.

**Tech Stack:** NeuSymNav Python, PyQt5, Hydra/Spark-DSG native binding, OpenVINO GPU detector theo profile đã pin, Habitat sensor worker hiện tại.

**Spec:** [Kế hoạch tích hợp Hydra](../superpowers/plans/2026-11-04-kiet-branch2-hydra.md), [status hiện hành](../implementation-status.md). Các ngưỡng long-run bên dưới là đề xuất cho campaign kế tiếp, phải chốt trước khi chạy; không thay thế hoặc nới checker hiện có.

## 1. Kết luận hiện tại

**Demo ngắn trên00805 đã chạy được: UI có Hydra graph3D và measured RGB-D point cloud, robot có di chuyển. Demo dài300–600s chưa qua gate vì freshness/cadence của NavMap/control.**

Checkpoint implementation mới đã hoàn thiện đường hiển thị Hydra XYZ; nhận định cũ rằng tab3D chỉ đọc legacy không còn phản ánh code hiện tại. Cloud đang trình diễn là point cloud từ measured RGB-D có source binding, không tự đồng nghĩa với native Hydra TSDF mesh renderer. Lỗi RSS census đã sửa và được xác nhận bằng smoke30s; không còn là blocker chính đang mở, nhưng run120s cũ không được đổi hồi tố từ incomplete thành completed.

Ưu tiên hiện tại là D2 map-core tail → smoke30/60s → hai run120s đạt gate →300s, sau đó mới600s và map thứ hai. Không tăng TTL300ms, không thay frontier/movement policy để che lỗi. Telemetry GPU, full-suite cuối và runtime tối thiểu độc lập ROS là các trạng thái kiểm chứng riêng. Evidence chi tiết: [báo cáo implementation mới](hydra-long-demo-readiness-2026-11-05.md).

## 2. Bằng chứng đã kiểm tra

### 2.1 Checkpoint mới nhất — supersedes baseline bên dưới

Artifact root `.runtime/hydra_ws/artifacts/hydra-readiness-D1-00805-20261105/`:

| Chỉ số | `ui-on-30s-rss-fix` | `ui-on-120s-first-gated` |
| --- | ---: | ---: |
| Outcome |completed|incomplete, nguyên nhân RSS cũ|
| Recorded frames |268/268|986/986|
| Body translation lower bound |1.065m|4.539m|
| Executed controls |141|522|
| Proof records / executed thiếu proof |141 / 0|525 / 0|
| Hydra revision |9|29|
| RSS supported / samples |427/427|1030/1031 trước fix|
| `navigation_source_pending` |1|3|
| `expired_before_step` |0|3|

Run120s có6/546 freshness misses =1.10% (3 pending +3 expired-before-step), hơi vượt gate≤1%. Có525 proof records không có nghĩa là525 lệnh executed; control results ghi522 executed và không lệnh executed nào thiếu proof. Recording, Hydra export, UI render cuối và shutdown của run120s đều hoàn tất. Graph không ngừng dựng; control từ chối nguồn quá300ms là hành vi an toàn đúng.

Map update p95/max148.5/295.9ms; control interval p95388.5ms. Core/raycast/vote là các phần cần profile/tối ưu tiếp, không chỉ nhìn tổng p95: tail cộng sensor/queue/wait có thể đẩy tuổi nguồn vượt300ms. RSS race fix đã có focused resource suite88 passed và smoke30s thành công, nhưng chưa có run120s sau fix đạt toàn bộ gate. Không tăng thời lượng trước khi có candidate qua offline parity/tail và smoke ngắn.

Profile durable `configs/demo-00805.hydra-long-demo.local.json` đã tồn tại. Các số liệu60/120s và profile `/tmp` ở2.2 là **baseline lịch sử**, không phải kết quả mới nhất.

### 2.2 Baseline lịch sử trước D1/D2 — giữ để đối chiếu

Nguồn chính: checkpoint smoke UI-on trong `docs/implementation-status.md` và artifact root:

```text
.runtime/hydra_ws/artifacts/hydra-telemetry-counter-fix-smoke-00805-20261105/
```

| Chỉ số | Run60s | Run120s |
| --- | ---: | ---: |
| Outcome / lỗi | completed / null | completed / null |
| Sensor frames |457|892|
| Executed controls có source-matched proof |224/224|433/433|
| Body translation lower bound |1.801m|3.543m|
| Hydra graph revision |12|25|
| UI final publication đã render |122|244|
| Control interval p95 |415ms|462ms|
| navigation_source_pending |0|13|
| Recording / Hydra export / shutdown |complete / complete / clean|complete / complete / clean|

Graph cuối run120s chứa12 objects,69 places,1 room,1 building,184 edges. SHA256 của native `.sparkdsg` khớp export manifest. Đây là graph có dữ liệu, không chỉ thành công ở bước import binding.

Trong13 pending events:12 có depth age301–314ms; một event còn depth mới nhưng map chưa xong khi control kết thúc. Có hai event gần deadline119.8/120.02s, vì vậy **vị trí gần cuối run và nguyên nhân stale không phải hai tập loại trừ nhau**. Báo cả timestamp lẫn nguyên nhân; không tự bỏ event stale khỏi denominator chỉ vì nó ở cuối run. Run xác nhận30s đã tái hiện một boundary event với depth84ms và map hoàn tất107ms sau control.

NavMap update p50/p95/max:81/200/414ms; navigation wait82/192/288ms. Run120s không có nonzero command bị `deadline_expired` hoặc `expired_before_step`;16 `expired_or_zero` là zero-motion stops. Không gọi chúng là16 lệnh thực thi bị mất proof.

RSS120s:1,043/1,043 samples được hỗ trợ, sampled peak1,998,946,304B. GPU memory chưa sample; `boundedness_certified=false`. Sampled peak không chứng minh absolute peak.

Profile đã dùng:

```text
/tmp/neusymnav-telemetry-smoke-00805-ui-on.json
SHA256 1aa2e14bb126cb66cce3982fcd98a9536e55c1b2bbe14a6f2571f6bfd815899d
```

Preflight kiểm lại trong lượt đánh giá trước: exit0, `ready=true`, `issues=[]`, `native_runtime_validated=false`; duration cap600s. Cap này cho phép nhập thời lượng, **không chứng nhận run600s đã đạt**. `/tmp` là profile tạm, cần chuyển thành profile ổn định trước bàn giao.

## 3. Vấn đề và trạng thái sau checkpoint implementation

- **Blocker chính còn mở:** V2/D2 — giảm tail NavMap/control đủ để hai run120s đạt gate trước300s. Hydra graph/export và robot movement đã có bằng chứng hoạt động.
- **Đã xử lý trong scope demo ngắn:** V1/V3 — native Hydra XYZ/edges, counts và measured point cloud đã nối UI; V7 — đã có profile durable. Native TSDF mesh display, room membership UI và các chi tiết chưa kiểm đủ phải giữ limitations riêng.
- **RSS:** race gây incomplete đã được sửa và kiểm chứng30s; không coi là nguyên nhân chính còn mở. Full120s xác nhận lại và GPU memory sampling vẫn chưa hoàn tất.
- **Chưa thực hiện:** campaign300/600s và map thứ hai; full-suite cuối còn cần chạy/đánh giá.

Bảng sau cập nhật từng finding ban đầu theo evidence mới; các giới hạn còn lại không được hiểu là phủ nhận demo ngắn đã chạy được.

| ID / ưu tiên | Vấn đề và bằng chứng | Cần làm |
| --- | --- | --- |
| V1 — đã xử lý cho demo ngắn | Native Hydra XYZ/edges và measured RGB-D cloud đã hiện trong UI, có source-match evidence. | Giữ regression; native TSDF mesh display và các tương tác room chưa được kiểm đầy đủ vẫn ghi limitation riêng. |
| V2 — blocker chính |Run120s mới có6/546 freshness misses (1.10%); map p95/max148.5/295.9ms, cộng sensor/queue/wait có thể vượt TTL300ms. | Tối ưu tail qua offline parity rồi smoke30/60s, sau đó hai120s đạt gate; không nới TTL. |
| V3 — đã xử lý trong D1 | UI dùng native Hydra graph; backend M3/M5 legacy không được bật lại để tạo display data. | Giữ checks nguồn, layer counts, native IDs và unavailable states; kiểm thêm room membership UI khi bàn giao. |
| V4 — thiếu long-run evidence | Chưa có300s/600s được checkpoint mới nhất nghiệm thu. Khoảng di chuyển120s không chứng minh chất lượng khám phá dài hạn. | Campaign tăng thời lượng có gate, đo coverage/extent/goals/stalls cùng translation; không chỉ số frame/node. |
| V5 — chỉ có00805 | Local Hydra profiles hiện tại đều cho00805. Runner cần profile explicit, không tự tạo calibration cho map khác. | Provision map thứ hai sau khi00805 đạt; kiểm asset, spawn, calibration, floor/robot geometry và worker pins. |
| V6 — telemetry/quality | GPU memory chưa có process-attributed provider; chưa có full-suite xanh cuối cùng được chứng minh trong checkpoint. Các báo cáo cũ có UI hash và nhóm failure rộng. | Chạy lại suite cuối sau sửa, phân loại từng failure; không lặp lại số lỗi cũ như trạng thái hiện tại. Báo GPU memory unavailable nếu chưa có provider đúng. |
| V7 — profile đã ổn định, còn giới hạn native mesh/runtime | Đã có `configs/demo-00805.hydra-long-demo.local.json`; measured cloud đang hiển thị không phải bằng chứng native TSDF mesh live. | Giữ pins/manifest đúng source; audit native mesh và runtime tối thiểu riêng sau khi long-demo path ổn định. |

### V1/V3: chi tiết đường display

Ở baseline cũ, renderer hierarchy2D đặt node theo layer/hàng và SpatialSceneWidget/cloud reader còn dựa legacy. Code mới đã có `_build_hydra_nodes()` dùng native XYZ/edges cùng measured RGB-D cloud reader; smoke ngắn có evidence final source match. Findings cũ này đã được xử lý trong scope trên, không còn là lý do chặn tăng duration. Không đánh đồng measured cloud với native TSDF mesh hoặc coi mọi tính năng UI đã được nghiệm thu chỉ từ publication counter.

### V2: điều đã biết và chưa biết

Đã xác nhận pending do exact map chưa sẵn sàng/nguồn quá hạn. **Chưa đủ bằng chứng quy toàn bộ tail cho một hàm hoặc khẳng định Hydra là tác nhân duy nhất.** Cần đo capture, IPC, map queue/service, guard, action và UI serialization theo cùng source, kèm wall-time/thread-CPU khi phù hợp. Không tăng TTL, retimestamp, dùng map cũ như map mới hay bỏ depth/clearance gate để che latency.

## 4. Giới hạn và phạm vi thực hiện

- Chỉ sửa trong worktree `Kiet_branch2`; không sửa source/config/environment của `Kiet_branch`.
- Giữ source IDs/timestamps/calibration, canonical coordinates và semantic vocabulary provenance. Không có semantic GT/runtime occupancy GT.
- Không đổi frontier ranking, controller mode/gain, tốc độ, geometry hoặc cadence cùng lúc với benchmark latency. Nếu cần thử cadence, dùng variant riêng, ghi rõ và đối chứng theo cùng variant.
- Giữ TTL300ms, horizon100ms, max speed0.2m/s và yaw cap đang pin; giữ kiểm footprint/path/unknown/free/collision.
- Mesh/cloud chỉ phục vụ display, không trở thành control map. Hydra rooms không bị ép thành polygon M5 hoặc convex hull xuyên cửa.
- Một writer/file; một native/GPU benchmark mỗi lúc. Không chạy CPU benchmark/full suite đồng thời với latency campaign.
- Không thay checker để biến failed/incomplete thành pass; không tự commit, push, cài hệ thống hoặc gỡ ROS.

## 5. Kế hoạch triển khai

### D0 — Khóa baseline và telemetry có thể đối chiếu

**Files:** profile branch2 ổn định; `docs/results/hydra-long-demo-*.md`; dùng lại measurement/checker code hiện có.

- [x] Lưu profile ổn định `configs/demo-00805.hydra-long-demo.local.json`; giữ scene/seed/pose, detector, cadence và movement. Ghi SHA profile, worker pins, preflight và runtime device/X11 trong report.
- [x] Đọc artifact 60/120s trước đó, so với smoke 30/60/120s mới, và chụp ảnh UI Hydra 3D.
- [x] Đối chiếu source/frame, stage latency, lý do pending/expired, command proof, translation, recording/export/UI/shutdown. Summary event list bị giới hạn theo hợp đồng; không thay denominator.
- [ ] Chạy lại full suite trên snapshot cuối và phân loại từng lỗi; chỉ có baseline trước lượt này (`2436 passed, 10 skipped, 32 failed`), chưa phải kết quả sau các thay đổi. Các focused suites của thay đổi liên quan đã chạy; không dùng baseline cũ làm pass mới.

**Pass:** baseline tái lập bằng profile durable; metrics phân biệt stop/no-op, missing proof thật, stale source và run cutoff.

### D1 — Nối Hydra graph và mesh/cloud vào3D Scene

**Modify:** `src/neusymnav/visualization/{spatial_scene,desktop,scene_graph}.py`, `src/neusymnav/backends/hydra/{worker,session,graph_adapter}.py`, DTO/transport khi cần. **Create:** `visualization/hydra_assets.py` trong package; `tests/test_hydra_spatial_scene.py`, `tests/test_hydra_asset_reader.py`.

**Interfaces đề xuất:** `HydraAssetReader.offer(projection, asset_ref) -> None`, `latest -> HydraDisplayGeometry | None`, `close(timeout_s) -> dict`; `HydraDisplayGeometry` chứa episode/run/revision/prefix, immutable vertices/colors/faces và original source metadata. Core importer không load native binding.

- [x] RED/green tests: Hydra graph render từ native XYZ/edge khi hierarchy legacy rỗng; layer labels/counts và selection ID đi theo Hydra.
- [x] Reader từ chối source sai/corrupt/oversized/wrong clock/domain, giữ last-good; queue async có một pending slot, close có bound.
- [ ] Chưa tạo mesh asset độc lập theo graph revision; hiện cloud được chiếu từ recording source đã xác minh, với hash/source provenance và cap điểm. Đây là đủ cho 3D cloud demo nhưng chưa phải mesh publication.
- [x] SpatialSceneWidget dùng Hydra native path; header/counts và M3/M5 unavailable đúng backend. Orbit/zoom/pan và chọn node được giữ.
- [x] Offscreen tests và visible smoke 30s xác nhận Hydra graph + point cloud thật; ảnh và final source match có trong report. Membership room và camera persistence qua revision chưa được kiểm đầy đủ.

**Pass:** xem được Hydra3D thật, không chỉ hierarchy2D hoặc mesh của ledger cũ; chọn/zoom/orbit được; không tăng control coupling.

### D2 — Giảm NavMap/control tail, giữ freshness

**Inspect/modify theo bằng chứng:** `mapping/occupancy.py`, mapping kernel/raycast; `runtime/{coordinator,launcher}.py`; UI writer chỉ khi profile chứng minh cần. **Tests:** thêm `tests/test_navigation_source_deadline.py`; dùng các safety/map parity tests hiện có.

- [x] Profile đầu/giữa/cuối của 120s và phân rã frame pending. Tail chủ yếu map core/raycast/vote integration; không thấy bằng chứng UI là nguyên nhân của freshness misses.
- [x] Thử cache geometry-only đúng intrinsics; parity đạt nhưng p95 không giảm đủ. Chưa có tối ưu map hiệu quả để bỏ miss.
- [x] So snapshot parity chính xác trên recorded frames; giữ NavMap stride 1, unknown/freshness/clearance gate nguyên trạng.
- [x] Đo freshness/timeout và phân biệt run deadline; 120s stale sources không được thực thi. Resource census race đã sửa bằng kiểm tra thread task biến mất cộng census thứ hai.
- [x] Đã chạy bounded 30s/60s/120s UI-on. RSS fix qua runtime smoke 30s: 427/427 mẫu; zero missing/read errors. 120s trước sửa RSS vẫn incomplete và có 6/546 freshness misses (~1.10%).
- [ ] Chưa có tối ưu map-core parity-safe nào chứng minh giảm tail trên workload ghi; vì vậy chưa lặp 120s sau RSS fix và không tăng duration.

**Gate đề xuất trước300s:** hai run120s liên tiếp completed/clean; executed proofs khớp100%; không worker failure, không command quá hạn được thực thi; in-run freshness-miss≤1% và không có chuỗi≥3 misses liên tiếp; control interval p95≤415ms (mốc60s), mục tiêu map source age p95≤250ms để còn margin. Đây là performance targets mới, không phải thay TTL300ms. Nếu fail, trở lại profile/D2; không tăng duration.

### D3 — Kiểm chứng UI/graph/performance chung trên120s

**Files:** `tests/test_hydra_projection.py`, `tests/test_hydra_spatial_scene.py`, measurement/safety suite, report mới.

- [x] Chạy targeted tests graph/asset/UI/map/resource. Full suite sau thay đổi chưa chạy; baseline cũ còn 32 fail.
- [ ] Run UI-on120s chưa đạt: artifact hiện tại incomplete do RSS sample cũ; ba pending và ba expired-before-step, freshness miss >1%. RSS fix chỉ được xác nhận bằng smoke30s.
- [x] Đối chiếu source/frame, stage latency theo ba phần run, UI final sequence, native graph, recording, command proofs, translation và shutdown cho artifact120s. Chưa suy coverage từ node count/yaw.
- [ ] Còn thiếu cửa sổ dài đã đạt gate và xác nhận RSS fix trên120s; GPU process memory sampling vẫn unavailable.
- [ ] Initial alignment và goal-change turn được đánh giá bằng heading trace; không gọi mọi đoạn ít translation là stall. Cũng không dùng heading convergence vô hạn để che việc không tiến: mục tiêu alignment ban đầu≤20s; cửa sổ20s có<0.1m và không có heading/goal/obstacle justification phải điều tra trước tăng thời lượng.

**Pass:** D2 gates giữ được khi3D view/mesh bật; không còn blocker ở đường chạy demo. Lỗi suite còn lại phải có đánh giá ảnh hưởng cụ thể, không chỉ ghi “pre-existing”.

### D4 — Demo300s trên00805

- [ ] Chạy output directory mới, graph/map bắt đầu rỗng, seed/profile/source pins đúng D3. Giữ một native workload; dừng tăng campaign nếu có crash, graph replay-required hoặc breach.
- [ ] Chia report thành bin30s và các third đầu/giữa/cuối: translation/proofs, extent/known area, goals, misses, map/control/UI age, RSS/asset bytes. Không chỉ báo tổng5 phút.
- [ ] Mục tiêu tiến triển đề xuất: translation lower bound≥8m/300s, có goal transitions và extent hoặc measured coverage tăng thực; không đạt chỉ bằng quay/đi vòng lại. Đây là mục tiêu cần đo, không phải kết quả đã có hoặc sự bảo đảm từ tuyến tính hóa120s.
- [ ] Graph không ngừng cập nhật>30s trong khi selected inputs được xử lý mà không có lý do; render có node/layer3D và mesh thật; recording/export/native reload/clean shutdown đầy đủ; giữ D2 proof/freshness gates.
- [ ] Kiểm resource/quota và memory growth ở cuối run, không chỉ sampled peak ban đầu. GPU memory unavailable phải hiện rõ; nếu chưa có provider đúng thì không gọi toàn bộ tài nguyên là boundedness-certified.

**Pass:** đạt các tiêu chí campaign đã chốt; nếu chưa đạt, ghi partial demo và quay về D1–D3. Không chuyển600s chỉ vì CLI exit0 hoặc graph có room.

### D5 — Demo600s và bàn giao

- [ ] Chỉ chạy sau D4 pass; preflight raw/archive/total budgets và duration cap600s. Không tự tăng quota để tránh admission stop mà không ghi config mới.
- [ ] Giữ gates D4, kiểm cuối run không suy giảm do graph/mesh/recording tích lũy. Mục tiêu translation≥15m/600s cùng bằng chứng coverage/goal progress; không tính extrapolation là validation.
- [ ] Bàn giao command, profile/source hashes, visible UI capture, native graph+mesh+input-prefix, acceptance output, shutdown/resource report và limitations. Nếu GPU provider hoặc minimal runtime chưa đạt, nêu riêng; không biến thiếu GPU measurement thành khẳng định demo trực quan không tồn tại, cũng không gọi demo pass là P10 pass.

### D6 — Map thứ hai, sau đó mới mở rộng

- [ ] Chọn map có scene/navmesh hợp lệ tại máy; tạo `configs/demo-MAP.hydra-long-demo.local.json` với spawn/seed/calibration/robot-floor geometry riêng. Không chỉ đổi tên00805 hoặc dùng calibration chưa kiểm.
- [ ] Capture calibration probe không action; kiểm transforms, depth convention, model/taxonomy/config pins, backend OpenVINO không fallback ngoài ý muốn.
- [ ] Lặp30→60→120s gates trước300s trên map đó. Mỗi map có báo cáo; không dùng00805 pass để tuyên bố mọi map pass.

## 6. Lệnh dự kiến khi được giao triển khai

Chạy trong worktree:

```bash
cd /home/kiettran05/Desktop/test_Room_segmentation/NeuSymNav/.runtime/worktrees/Kiet_branch2
export NEUSYMNAV_HYDRA_DEMO_CONFIG="$PWD/configs/demo-00805.hydra-long-demo.local.json"
bash tools/run_hydra_map_demo.sh 00805 --preflight
```

Profile `configs/demo-00805.hydra-long-demo.local.json` đã được tạo ở D0. Preflight gần nhất `ready=true`, issues rỗng, exit0. Để chạy demo UI-on ngắn đã được xác nhận:

```bash
bash tools/run_hydra_map_demo.sh 00805 30 runs/hydra-demo-00805-30s-NEW
# Hoặc 60 giây; đã có một run cùng profile hoàn tất sạch.
bash tools/run_hydra_map_demo.sh 00805 60 runs/hydra-demo-00805-60s-NEW
```

Mỗi lần dùng output directory mới. Cả hai lệnh cần UHD/OpenVINO và desktop X11 runtime khả dụng. Smoke30/60 xác nhận UI graph/cloud, export, recording, actuation proof và shutdown; đây là demo ngắn, chưa phải chứng nhận long-run hay coverage.

Chỉ chạy duration dài tiếp theo khi gate trước đạt:

```bash
bash tools/run_hydra_map_demo.sh 00805 60 runs/hydra-long-demo-00805-60s-NEW
bash tools/run_hydra_map_demo.sh 00805 120 runs/hydra-long-demo-00805-120s-NEW
bash tools/run_hydra_map_demo.sh 00805 300 runs/hydra-long-demo-00805-300s-NEW
bash tools/run_hydra_map_demo.sh 00805 600 runs/hydra-long-demo-00805-600s-NEW
```

Không copy cả block rồi chạy liên tiếp bỏ qua gate; mỗi output phải mới. Targeted commands sau khi có tests D1/D2:

```bash
.venv/bin/python -m pytest tests/test_hydra_projection.py tests/test_hydra_spatial_scene.py tests/test_hydra_asset_reader.py -q
.venv/bin/python -m pytest tests/test_navigation_source_deadline.py tests/test_sensor_actuation.py tests/test_runtime_measurement_wiring.py -q
.venv/bin/python -m pytest -q
git diff --check
```

Checker H7 hiện cần native fixtures và A/B acceptance evidence đầy đủ; output completed của smoke không tự thỏa checker. Giữ nguyên protocol A/B và checker đã có; dùng smoke diagnostic report để quyết định tăng duration, không đổi checker thành chỉ kiểm node count. Không suy GPU-peak certification hay runtime ROS-free từ graph export thành công.

## 7. Thứ tự và ownership

**D0 → D1/D2 → D3 → D4 → D5 → D6.** D1/D2 chỉ song song khi file ownership không giao nhau; coordinator, DTO/transport và shared contracts do main giữ. Luna xhigh mặc định cho adapter/UI/tests/report; Terra khi có bất định native/GIL/provenance thực tế. Reviewer độc lập kiểm D1/D2 trước native ladder và đánh giá kết quả D4 trước600s. Không lặp benchmark giữa các workers.

| Mốc | Được phép kết luận |
| --- | --- |
| Hiện tại | Hydra native graph + UI-on 30/60s hoạt động trên00805;120s gate chưa qua |
| D1 | Hiển thị Hydra3D thực, chưa long-run validated |
| D3 | Đủ điều kiện thử300s trên profile cụ thể |
| D4 | Demo300s validated trên00805 và snapshot/profile đã ghi |
| D5 | Demo600s validated trên cùng cấu hình; resource limitations vẫn tách riêng |
| D6 | Map thứ hai có kết quả riêng; không khẳng định map tùy ý |

## 8. Trạng thái báo cáo

**Trạng thái sau khi thực thi:** Có thể chạy demo UI-on ngắn 30–60s trên00805; profile durable và preflight đã sẵn sàng. D0 hoàn thành ngoài full-suite rerun; D1 đạt cho Hydra native graph + measured RGB-D point-cloud display (mesh asset độc lập chưa làm). RSS race fix đã correctness- và runtime-validated bằng smoke30s. D2 vẫn mở: run120s có freshness miss1.10%, tail map-core chưa được giảm bằng ứng viên parity-safe. D3 chưa qua. Không chạy300/600s hoặc map thứ hai. Xem chi tiết, artifact, command/exit và giới hạn tại [checkpoint](hydra-long-demo-readiness-2026-11-05.md). Không commit/push.
