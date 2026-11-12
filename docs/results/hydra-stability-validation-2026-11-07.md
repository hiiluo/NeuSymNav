# Kiểm chứng chi phí và live của Hydra threshold/seed policy — 2026-11-07

Đã thực hiện A/B luân phiên, hai demo simulator 300 giây, kiểm tra UI và recording
độc lập trong `Kiet_branch2`. **Chi phí policy thấp trong phép đo này, nhưng chưa đủ
điều kiện đổi mặc định:** geometry live còn sai và movement/freshness chưa đạt.
Không chỉnh threshold, không sửa thuật toán movement hay nới guard.

## 1. A/B chi phí có kiểm soát

Bốn worker mới, thứ tự **OFF → ON → OFF → ON**, mỗi worker xử lý đúng 58 accepted
inputs của recording long300. Cùng compression 0,5 m, component min 3, room min 10,
merge 0,25 m; cùng timed DSO, Hydra 2 threads, BLAS/OMP 1 thread; không chạy simulator,
detector, UI hay test đồng thời với benchmark. Timed DSO chỉ thêm RAII/counters vào
RoomFinder; private DSO dùng cho demo không bị ghi đè.

| Trung bình trên cùng 58 revision, hai lượt mỗi chế độ | OFF | ON | ON − OFF |
| --- | ---: | ---: | ---: |
| Toàn `process_frame`, wall, ms | 2591,403 | 2585,760 | −5,642 (−0,218%) |
| Toàn `process_frame`, process CPU, ms | 4687,104 | 4679,912 | −7,192 (−0,153%) |
| `findRooms`, inclusive, ms | 9,315 | 9,524 | **+0,210 (+2,25%)** |
| `getBestComponents`, inclusive, ms | 6,151 | 6,374 | +0,224 (+3,64%) |

`getBestComponents` nằm trong `findRooms`; **không cộng hai số này**. Toàn bước gồm
native initialization ở frame đầu và graph summary, chưa gồm custom diagnostic export.
Process CPU tính cộng các thread, nên có thể lớn hơn wall. RSS worker lấy mẫu 10 ms:
OFF **311,43 / 313,61 MiB**, ON **317,07 / 303,89 MiB**; không thấy mức tăng nhất quán.
RSS sampling bao gồm đọc/deserialize input giữa các bước, tạm dừng khi export custom;
không phải process-tree RSS và không phải chứng minh peak tức thời.

Chỉ hai mẫu mỗi chế độ: không tuyên bố significance, policy làm nhanh hơn, hoặc bảo đảm
mọi máy/run. Kết quả **không ủng hộ nhận định policy gây mức chậm toàn pipeline lớn**
đã quan sát khi so hai replay khác thời điểm ở lượt trước. Riêng phần RoomFinder có
chi phí tăng nhỏ, khoảng 0,21 ms/bước trong dữ liệu này.

Tất cả **232/232 revision** khớp đối chứng tương ứng về places XYZ/clearance, cạnh và
phân hoạch (so nhóm thành viên, không phụ thuộc tên room ID). Mỗi OFF tái hiện gộp chéo
ở 36/49/57; mỗi ON không còn ba lỗi đó, strict core separation 37/53 → 40/53.
GT chỉ là hai vùng lõi do người dùng đánh dấu, không phải accuracy toàn phòng.

## 2. Hai lượt live 300 giây — giữ cả kết quả không đạt

Lượt đầu dùng profile room-stability cũ, kế thừa primary 5 Hz/world-map control.
Telemetry và đối chiếu cấu hình phát hiện profile này **chưa ghép đường local-depth
hiện hành**. Vì vậy đã chạy lại từ profile có sẵn
`configs/demo-00805.hydra-local-depth.experimental.local.json`, chỉ ghép Hydra room
profile và hai entry ghi bằng chứng. Navigation, sensor launch, runtime, detector và
guard giữ nguyên so với profile local-depth đó: retention 10 s, primary 0,5 Hz,
navigation 10 Hz, `local_depth_control=true`, `defer_capture_gc=false`.
Đây không phải A/B chỉ riêng local-depth: cadence và retention cũng khác giữa hai lượt.

| Kết quả | Lượt profile cũ | Lượt local-depth hiện hành |
| --- | ---: | ---: |
| Simulator run | 300 s, completed | 300 s, completed |
| Raw frames, recording complete | 1172 | 1047 |
| Quan sát body translation, m | 2,169 | 2,094 |
| Có body samples trong cả hai vùng lõi | Không | **Có** |
| Cắt qua khoảng ô cửa được đánh dấu | Chưa chứng minh | **1 lần** |
| Freshness misses / control results | 201 / 584 | 293 / 903 |
| Freshness misses | 34,418% | **32,447%** |
| Native graph revisions | 20 | 23 |
| Revision đủ target support | 11 | 18 |
| Revision gộp chéo hai vùng lõi | 2 | **13** |
| Strict core separation | 9/11 | **1/18** |
| UI revisions khớp native | 20/20 | **23/23** |

Cả hai recording/export/shutdown sạch; không thiếu command proof. Tuy nhiên
`actuation.complete=false` và strict certified distance là `null`; khoảng cách trên
là tổng chuyển vị body quan sát, không tự nâng thành chứng nhận actuation hoàn chỉnh.
Lượt local-depth có 474 accepted command/proof records, trong đó 462 control results
`executed` và 12 `expired_before_step`. Giữ nguyên mẫu số control results, không loại
các lượt không di chuyển hay freshness fail để làm đẹp tỷ lệ.

Đăng ký không gian của annotation được kiểm tra: sensor launch configuration giống
recording gốc, sensor worker SHA giống, phép đổi hệ trục tuyệt đối `normalize_capture`
không thêm dịch chuyển theo episode. Human polygons chỉ được dùng offline. Đường đỏ
là khoảng ô cửa do người dùng đánh dấu; không tuyên bố ranh giới cửa vật lý chính xác.

## 3. Telemetry: vấn đề đường điều khiển vẫn còn

Runtime của cả hai lượt **không thấy GPU OpenVINO**: `available devices: CPU`.
Detector yêu cầu `openvino_gpu` nhưng thực tế fallback **Torch CPU** theo policy có sẵn.
Không tuyên bố đây là kết quả chạy bằng UHD GPU.

Lượt local-depth:

| Stage | Support | P95, ms | Max, ms |
| --- | ---: | ---: | ---: |
| `sensor_navigation_roundtrip` | 907 | 112,17 | 276,56 |
| `sensor_primary_roundtrip` | 139 | 450,99 | 592,81 |
| `control_navigation_wait` | 904 | **0,0043** | 0,0106 |
| `local_depth_map` | 903 | **449,14** | 815,41 |
| `local_path_follow` | 903 | 29,63 | 164,17 |
| `local_motion_guard` | 903 | 25,66 | 94,66 |
| `navmap_update` | 905 | 434,17 | 829,03 |

Việc bỏ chờ world NavMap đã hoạt động trong run này, nhưng bước tạo local depth map
vẫn có đuôi vượt cửa sổ depth **300 ms**. CPU fallback/cạnh tranh tài nguyên là một
hướng cần kiểm tra; telemetry hiện tại chưa cô lập quan hệ nhân quả. Không cộng các
stage có thể chồng lấp. Không nới guard 300 ms hoặc command horizon 100 ms.

## 4. Recording độc lập và counterfactual trên recording live mới

Recording short60 độc lập đã replay OFF/ON đủ **10/10 mỗi chế độ**, source prefix và
geometry/cạnh khớp. ON bootstrap r4 ở 0,600 m, giữ r5–8 khi đề xuất 0,721 rồi 0,748 m,
nhận 0,748 m ở r9 và cho phép graph đổi từ một sang hai room. Đây là bằng chứng policy
không đóng băng partition; đồng thời cho thấy **độ trễ sửa** khi candidate tiếp tục trôi.
Tách được hai room không tự chứng minh đúng hai vùng vật lý. Probe hai vùng lõi của
short60 còn partial mix/unassigned ở các revision cuối.

Để giải thích lỗi live, đã replay **đúng 23 inputs của lượt local-depth mới với policy
OFF**, cùng cấu hình hình học. Tất cả places XYZ/clearance/source prefix khớp ON.
Kết quả trên cùng recording:

| Partial target geometry | OFF | ON |
| --- | ---: | ---: |
| Eligible revisions | 18 | 18 |
| Gộp chéo hai vùng lõi | **13/18** | **13/18** |
| Strict core separation | 0/18 | 1/18 |
| Hành lang/core bị phân mảnh | 8 revisions | 6 revisions |

Các revision gộp chéo giống nhau: 5, 7–18. ON giảm một phần phân mảnh nhưng chưa sửa
được lỗi nền. Không thể quy toàn bộ lỗi này cho hysteresis; cần audit geometry/support,
filtration và clustering trên recording mới. Ở lượt profile cũ, r10–11 giữ ngưỡng
0,721 m khi raw xuống 0,566 m; r12 mới nhận và tách các lõi đúng. Độ trễ hai graph
updates này là trade-off quan sát được, không phải thời gian hai control ticks.

## 5. UI và kiểm chứng

DISPLAY `:0` không mở được. Đã chạy **Qt offscreen thật**, chụp widget 1600×1000 và
đối chiếu canonical place-parent fingerprint, source, prefix, revision, policy decision
với journal/native export. **43/43 revision của hai lượt live khớp**, không mismatch.
Có 10 và 13 screenshot, gồm bản cuối; filter mặc định Rooms + Objects giữ nguyên.
Chưa có bằng chứng cửa sổ hiển thị trên desktop vật lý, hoặc thao tác click của người.
Kết quả gộp sai trên UI là cùng dữ liệu native, không phải UI tự vẽ membership khác.

- Focused suite + bundled UI provenance smoke: **207 passed, 10,92 s, exit 0**.
- Native policy fixture driver chạy mới: **PASS, exit 0**; spike/duplicate timestamp/
  sustained transition/unavailable/reset/current-geometry fallback vẫn được kiểm tra.
- Bốn primary cost runs, hai short smoke, hai live, OFF replay recording mới,
  native/UI audits và source/hash verification đều có log/exit riêng.
- Giữ nguyên stable DSO `9364ca48…fb7e4b`; timed DSO riêng `ba17985e…fbd498`.
  Default YAML, worker/session/runtime chính, coordinator và safety không đổi hash.
- Preflight ban đầu chặn entry nằm trong artifacts; không bypass. Đã đặt hai entry
  **tùy chọn** trong package: `backends/hydra/validation_entry.py` và
  `runtime/ui_validation_entry.py`. Default worker/UI entry không đổi.
- Smoke đầu dùng nhầm profile mặc định được giữ dưới `ineligible-default-config-*`,
  không đưa vào A/B. Các preflight bị từ chối được lưu riêng, không xóa khỏi hồ sơ.

## 6. Kết luận và bước tiếp theo

**Không promote mặc định trong lượt này.** Điều kiện chi phí đã có bằng chứng thuận lợi
trên một recording, UI/provenance đã kiểm được, và có bằng chứng đi qua vùng cửa. Nhưng
freshness, tiến độ di chuyển và phân phòng live chưa đạt mục tiêu.

Ưu tiên tiếp theo là kiểm tra GPU exposure/CPU fallback và giảm chi phí **local_depth_map**
trong điều kiện detector + simulator + Hydra cùng hoạt động, giữ guard. Song song, audit
support/clearance/cạnh/seeds của recording mới trên cùng prefix, vì OFF cũng sai ở 13/18
revision. Chưa nên tiếp tục chỉnh threshold để ép ra hai room, hoặc dùng SLM label làm
bằng chứng geometry đúng.

Profile thử nghiệm ghép đúng movement hiện hành:
`configs/demo-00805.hydra-room-stability-local-depth.experimental.local.json`.

```bash
QT_QPA_PLATFORM=offscreen \
NEUSYMNAV_HYDRA_DEMO_CONFIG=configs/demo-00805.hydra-room-stability-local-depth.experimental.local.json \
  bash tools/run_hydra_map_demo.sh 00805 300 runs/hydra-room-stability-local-depth-300s-new
```

Dùng output directory mới; bỏ `QT_QPA_PLATFORM=offscreen` khi desktop thực sự khả dụng.
Lệnh trên dùng entry UI thông thường, không bắt buộc bật hai entry ghi bằng chứng.

## Artifacts

Root `runs/hydra-objectnav/B1-stability-validation-20261107/`:
`plan.md`, `progress.md`, `baseline-hashes.json`, `benchmark-protocol.json`,
`abab-progress.json`, `benchmark-analysis.json`, `benchmark-harness/`,
`additional-recording-validation.json`, `additional-recording-target-probe.json`,
`live300-00805/`, `live300-local-depth-00805/`, `new-live-recording-off/`,
`new-live-recording-comparison.json`, `live-control-profile.json`,
`local-depth-control-profile.json`, `final-tests.log`, `native-policy-fixture.log`,
`verification.json`. Mỗi live directory có `room-validation.json`, `ui-validation.json`,
`room-revisions/` và `ui/ui-harness/final-ui-view.png`. Không tự commit/push.

![Chi phí và bản đồ live](../../runs/hydra-objectnav/B1-stability-validation-20261107/validation-overview.png)
