# GVD support → compression → merge và fullhistory audit — 2026-11-07

User giao ba bước sau [A/B trước](hydra-room-ab-2026-11-07.md): truy nguồn support bathroom, chỉ thay merge khi có bằng chứng, rồi replay toàn pipeline theo revision và đối chiếu annotation trước live/default promotion. WorktreeKiet_branch2, mặc định1.0/10/10 giữ nguyên.

## 1. Native trace thật và parity

Đã compile một translation unit từ **bản sao** GraphExtractor, relink private `libhydra.so`; không sửa source/library đã cài. Probe ghi các GVD nodes mà extractor đang giữ, eligibility, compressed refs/representative, node `in_graph`, graph places trước/sau merge, resolved merge pairs và timestamp. Không dùng graph export cuối để đoán các trạng thái này.

Hooks và giới hạn: [probe README](../../tools/native/gvd_trace_probe/README.md). Các điểm zero-basis bị loại trước hook không được coi là toàn bộ input voxels; trace cuối phản ánh surviving GVD state. Merge pairs đã resolve chuỗi, không nhất thiết là từng phép so sánh trực tiếp; không suy refs chuyển từ loser sang winner.

Main chạy short60probe10frame, long300probe58frame cho compression1.0 và0.5. Mỗi run chấp nhận đủ prefix original, capture timestamp thứ tự khớp; per-revision `/proc/self/maps` chứng minh child nạp private lib. **Final backend places, edges và full RoomFinder output giống hệt bản ghi/replay thư viện gốc** cho cả ba case. Installedlib vẫn SHA `5cce5ce5c6d7bb374226969a69144a55a7d5d70862f8976fdfcae16f719a62dc`. FileSHA toàngraph không dùng làm tiêu chí parity cấu trúc vì khác biệt serialization đã có ở task trước.

## 2. Vì sao ROI support8→5

ROI XY `[-0.9,0.4] × [-2.8,-0.8]m` giữ nguyên từ khảo sát trước; **không là spatialGT**. Full58revision trace cho thấy:

| Trạng thái cuối trong ROI | Compression1.0 | Compression0.5 |
| --- | --- | --- |
| Surviving GVD physical voxel indices | 147 | 147 |
| GVD đủ clearance0.4m | 120 | 120 |
| Representative groups có best point trong ROI | 14 | 15 |
| Representative hiển thị trong graph | 8 | 5 |
| Groups bị ẩn nhưng còn support refs | 6 | 10 |

Tập147voxel trùng physical index, XYZ, clearance, basis và eligibility. **Không mất GVD quan sát ở bước cuối.** Compression thay cách chia group/chọn representative; lịch sử merge để lại nhiều groups không còn node hiển thị. Ở extract cuối bản thân mergepass chỉ8→8 và5→5, nên chỉ nhìn frame cuối sẽ bỏ sót lịch sử.

Ví dụ nhánh0.5 có representative216 tại(-0.7,-1.9,1.7),221 tại(-0.7,-1.3,1.9),223 tại(-0.3,-2.3,1.9) bị ẩn cuối dù vẫn còn14/13/1eligible support members. Các resolved losing merges gần nhất là216→217(rev19),221→217(rev21),223→222(rev15); endpoint distances khoảng0.40/0.283/0.40m. Nhánh1.0 giữ representative tại những vị trí losing này, nhưng IDs/group membership khác nhau, nên không đối chiếu IDs trực tiếp giữa hai compression.

Đây là bằng chứng đủ để **thử riêng** merge-distance0.5→0.25; chưa chứng minh chỉnh merge một mình sẽ khôi phục đúng ba nodes vì lịch sử mới có thể chọn representative khác. Frontend/back-end cũng được tách:103/102places ở1.0,137/135ở0.5; frontend-only nodes nằm ngoài ROI và commonID positions khớp, chưa suy nguyên nhân bị backend bỏ chỉ từ đó.

[Phân tích đầy đủ, refs và commands](../../runs/hydra-objectnav/B1-support-20261107/native-probe/analysis/README.md), [JSON comparison](../../runs/hydra-objectnav/B1-support-20261107/native-probe/analysis/long300-comparison.json). Cả hai58timestamp khớp revision và input prefix `1103b62bf0cfedf5d285991f60b0bd8d9c167056693da9747a75dd3773244bf9`.

## 3. A/B merge và replay policy xuyên lịch sử

Bằng chứng trace đã có trước khi chạy pair. Hai cấu hình clean dùng compression0.5, component min3, room min10; chỉ đổi `node_merge_distance_m`0.5→0.25. Min GVD clearance0.4m, voxel size, semantic inputs, calibration, pose, acceptedframeorder, native binary đều giữ nguyên. Configs riêng trong artifacts; structural diff đúng một field.

Full worker dùng room policy ngay từ frame đầu, không chỉ chạy RoomFinder posthoc ở snapshot cuối. Artifact entry kế thừa worker gốc, lưu graph/clearance/membership thật sau từng accepted step; không sửa production entry. Lưu snapshot không mesh và index có hash, timestamp, prefix, config/source/binding. Các cạnh places khác membership được xuất làm **boundary proxy của observed graph**, không coi là physicalwall/door/traversability proof.

Evaluator `room_temporal_audit.py` tách:

- Raw roomID đổi khỏi co-membership thay đổi (không phạt IDrename thuần).
- Support chung di chuyển>0.25m, node mới và node bị bỏ khỏi persistent stationary support.
- Availability changes(null↔assigned) khỏi partition changes trên points được gán ở cả hai revision.
- Split/merge overlaps có ít nhất2points và fraction0.2; đây là events trên observedplaceIDs, chưa phải split/merge physicalroom được xác nhận.

Mỗi tỷ lệ có denominator; không coi không có cặp điểm đủ điều kiện là ổn định. Ngưỡng audit là policy mô tả, không phải quality promotion gate. RoomID/labels không làm chứng minh geometry đúng.

Clean cost đo trước export debug, gồm native process_frame và summary vốn có; exporttiming riêng. Không dùng trace-enabled times để kết luận chi phí. Offline CPU replay không là livecontrol freshness benchmark.

### Kết quả clean fullhistory

| Recording | Merge (m) | Places cuối | Rooms / sizes cuối | ROI places | ROI seed cuối | Native p95 (s) |
| --- | --- | --- | --- | --- | --- | --- |
| 60s / 10revisions | 0.5 | 48 | 2:38/10 | 8 | 3 | 2.966 |
| 60s / 10revisions | 0.25 | 127 | 2:96/31 | 14 | không | 3.249 |
| 300s / 58revisions | 0.5 | 135 | 2:113/22 | 5 | không | 4.060 |
| 300s / 58revisions | 0.25 | 399 | 3:336/28/32 | 14 | 6 | 3.990 |

Đối chiếu XYZ ở finalbackend xác nhận cả ba vị trí representative thua merge nêu trên hiện diện trở lại với sai số<1e-6m ở trial0.25; không dùng IDtrùng làm bằng chứng tương ứng. Distances được tính trực tiếp từ eventXYZ trong `resolved-merge-distances.json`, sửa nhầm số0.447m thành0.283m; gate0.25 không thay đổi.

Giảm merge đã giữ thêm support cục bộ trên cả hai recording, nhưng không giải quyết nhất quán việc tạo seed đúng vùng: ở60s, threshold cuối tăng lên0.7483315468m, component giaoROI chỉ2nodes nên bị lọc; ở300s, threshold0.5656851530m giữ seed6 trongROI, nhưng14ROIplaces phân vào hai roomIDs. ROI không là ranh giới vật lý đầy đủ nên không kết luận những membership đó đúng/sai chỉ từ hộpROI.

Tất cả136snapshot clean (10+10+58+58) có partition actualnative khớp co-membership của RoomFinder fresh trên cùng exact graph/config. Actualmembership trong audit lấy từ nativeworker sau từng step; các seed exports là reconstruction có scope riêng, không giả original per-frame trace của RoomFinder internals.

### Biến động membership và split/merge

| Recording / merge | Transitions có đổi partition / đủ cặp eligible | Tổng pair-disagreement / tổng eligible pairs | Split / merge overlap events |
| --- | --- | --- | --- |
| 60s /0.5 | 0/6 | 0.00% | 0/0 |
| 60s /0.25 | 6/6 | 13.93% | 2/3 |
| 300s /0.5 | 13/55 | 7.20% | 7/7 |
| 300s /0.25 | 43/55 | 7.49% | 6/3 |

So sánh chỉ dùng points được gán ở cả hai revision và dịch chuyển≤0.25m; null→assigned/newpoints không bị gộp thành geometry split. Cumulative pairs có thể lặp cùng cặp qua nhiều transition, không phải số independent unique samples. Thay đổi density làm phân bố support/pair weights khác nhau giữa profile, nên không dùng một tỷ lệ duy nhất để xếp hạng physicalaccuracy.

**0% của short60/merge0.5 không chứng minh phòng tắm đã ổn định**: room thứ hai chỉ xuất hiện ở revision10 cuối chuỗi, chưa có đoạn sau đó để kiểm tra. Ở300s, merge0.25 có nhiều thay đổi nhỏ thường xuyên hơn trong khi weighted fraction gần merge0.5; một split/merge event có thể là sửa hợp lý khi quan sát thêm, không mặc nhiên là lỗi. Chưa có bằng chứng profile0.25 cải thiện ổn định geometry mục tiêu.

![Room groups theo accepted revision](../../runs/hydra-objectnav/B1-support-20261107/room-count-history.png)

[Native membership comparison60s](../../runs/hydra-objectnav/B1-support-20261107/short60-merge-comparison.png), [300s](../../runs/hydra-objectnav/B1-support-20261107/long300-merge-comparison.png). Boundary proxy từngrevision, event overlaps, moved/new/removed counts, actualIDs và source hashes đều có trong `audit/<recording>/merge-*/temporal-audit.json`, CSV và snapshot graph.

### Chi phí và trial gián đoạn

Clean trials dùng thư viện cài sẵn, CPU2native threads, không chạy heavy render/parse/tests khác trong cửa sổ đo. P95long gần nhau nhưng worst-step0.25 là5.343s(rev49), so với4.111s(rev36) ở0.5; không phải cold initialization. Short p95 tăng từ2.966 lên3.249s. Maximum sampled workerRSS sau export khoảng294.4→301.4MiB ởlong; đây không phải chứng nhận process peakRSS. Debugexport p95long13.17→42.67ms được ghi riêng, ngoài nativeprocess interval.

Một trial0.25 bị ngắt ở39/58 do turn interruption được lưu riêng `merge-0.25-interrupted-39/`, có `eligible_as_complete_trial:false`. Main chạy lại từ worker rỗng với toàn bộ58frame; không nối graph dở, không gộp trial gián đoạn vào performance/stability. Baseline0.5 hoàn tất trước gián đoạn; đây là single completed trial/profile, chưa có A/A timing repetitions để suy causal speedup1–2%. Cost là số quan sát offline; chưa chứng minh live CPU contention/freshness hay budget ObjectNav.

**Quyết định: không đổi mặc định và chưa chọn profile0.25 để live.** Nó phục hồi local support nhưng graph lớn hơn và kết quả seed/membership chưa nhất quán. Cần annotation trước khi gọi cấu hình nào là phân phòng tốt hơn; không tiếp tục giảm merge/chỉnh threshold chỉ để ép đúng số room.

## 4. Annotation độc lập và giới hạn nghiệm thu

Không tìm thấy independent roomGT00805 trong assets hiện có; user xác nhận chưa có và yêu cầu bản đồ để đánh dấu. Đã tạo bản đồ **chỉ từ observedRGBD/pose**, lưới0.5m, không room/seed/membership dự đoán hoặc ROI gợi ý. Vùng trống chỉ thiếu plotted samples sau visualfilter, không phải freespace.

- [Long300 observedXY](../../runs/hydra-objectnav/B1-support-20261107/annotation/long300/observed-xy-height-0p35-2p20m.png)
- [Long300 sourceRGB montage](../../runs/hydra-objectnav/B1-support-20261107/annotation/long300/accepted-primary-montage.png)
- [Hướng dẫn và template annotation](../../runs/hydra-objectnav/B1-support-20261107/annotation/README.md)
- [Short60 observedXY](../../runs/hydra-objectnav/B1-support-20261107/annotation/short60/observed-xy-height-0p35-2p20m.png)
- [Low-height observed returns](../../runs/hydra-objectnav/B1-support-20261107/annotation/short60/observed-xy-low-height-0p00-0p35m.png)
- [SourceRGB montage](../../runs/hydra-objectnav/B1-support-20261107/annotation/short60/accepted-primary-montage.png)

Source Observation tag `canonical_z_up_v1`, metric axial depth/pose; annotation/evaluator spelling `canonical_z_up_m_v1` được ghi rõ cùng units mét. Các maps và nguồn có hash/calibration/frame IDs. Human polygon sau khi khóa độc lập mới được chiếu lên support của từng exact graph; không dùng qualitativeROI làm annotation. Accuracy/boundary quality vẫn unavailable đến khi có labels; việc chuẩn bị template không là đánh giá đã qua.

## Phạm vi hoàn thành và phần chờ

- **Implemented:** isolated nativeprobe/parser; perrevision replayentry; offline temporal evaluator/CLI và tests; blind annotation packet. Production worker/control/config/library không sửa.
- **Correctness-verified:**70focused tests passed4.51s/exit0; có native fixture (env enabled, no skips), exhaustive pair oracle, roomquality/GT isolation/UI/query tests. Không fullsuite. Probe parity và checks source/config/prefix/library là các gate native độc lập với unit tests.
- **Native offline validated:**3probe replays (10,58,58inputs) và4clean fullhistory replays (58,58,10,10), source prefixes nguyên gốc, snapshot/revision completeness.136native reconstructions chỉ để giải thích seeds; không thay actualmembership.
- **Chờ người dùng:** annotation bathroom/hallway. Bốn quality reports trả `unavailable/annotation_missing`; không chuyển qualitativeROI/template thànhGT, không có accuracy hoặc physicalboundary pass. Chưa live demo, chưa promotion, chưa hoàn tất geometryquality/wholeObjectNav roadmap.

Lệnh tái tạo build/traceparser trong probeREADME. Replay argv/env trong `runs/hydra-objectnav/B1-support-20261107/*-command.json`; `audit-command.json` chứa lệnh audit4cases, `tests-command.json` chứa exacttest argv/env. Kiểm chứng tổng hợp:

```bash
PYTHONPATH=src .venv/bin/python runs/hydra-objectnav/B1-support-20261107/verify_support.py
```

[Verification](../../runs/hydra-objectnav/B1-support-20261107/verification.json), [paired summary](../../runs/hydra-objectnav/B1-support-20261107/paired-summary.json). Source frozen và nativeinstalled SHA giữ nguyên; `git diff --check` exit0. Không simulator/GPU/detector/modeldownload/training/commit/push.
