# Controlled native Hydra room A/B — 2026-11-07

Mục tiêu: phân biệt ảnh hưởng của **support/mật độ places** và **bộ lọc kích thước**, trước khi đổi mặc định. Nhánh `Kiet_branch2`; cặp vùng bathroom/hallway00805. Kế thừa [chẩn đoán native](hydra-room-diagnostic-2026-11-07.md). Không dùng số room=2 làm tiêu chí thành công.

## Thiết kế đã khóa trước khi chạy

[Protocol](../../runs/hydra-objectnav/B1-ab-20261107/protocol.md). Hai thí nghiệm:

1. **Size factorial:** giữ nguyên bytes graph, positions, clearance và edges; chạy đầy đủ RoomFinder cho `min_component_size={10,5,3}` × `min_room_size={10,5}`. Native tính lại filtration và ngưỡng cho từng cấu hình. Graph60s34places và300s102places; mỗi graph lặp lại baseline kiểm tra tính lặp được.
2. **Native density replay:** giữ nguyên chuỗi accepted RGB-D/pose/semantic frames và thứ tự, replay fresh worker; đối chiếu baseline với `compression_distance_m=0.5` thay vì1.0. Các tham số khác giữ nguyên. Mật độ phải do native extractor sinh ra, không nhân bản node graph.

ROI bathroom định tính đã khóa từ chẩn đoán trước: XY `[-0.9,0.4] × [-2.8,-0.8]m`; dùng để khảo sát support, không phải spatialGT hay accuracy. Count theo XY cells0.25m giúp phân biệt thêm nodes với mở rộng support; không diễn giải cell count là diện tích phòng chính xác. IDs chỉ so trực tiếp trong cùng graph; giữa density replays phải dựa trên tọa độ/observed support.

## A/B bộ lọc trên graph cố định

| Component min | Room min | Threshold60s (m) | Seeds60s | Threshold300s (m) | Seeds300s | Rooms60s/300s |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | 10 | 0.5656853318 | 16 | 0.5656853318 | 25 | 1 / 1 |
| 10 | 5 | 0.5656853318 | 16 | 0.5656853318 | 25 | 1 / 1 |
| 5 | 10 | 0.5656853318 | 16 | 0.5656853318 | 25 | 1 / 1 |
| 5 | 5 | 0.5656853318 | 16 | 0.5656853318 | 25 | 1 / 1 |
| 3 | 10 | 0.6000000238 | 11 | 0.6000000834 | 22 | 1 / 1 |
| 3 | 5 | 0.6000000238 | 11 | 0.6000000834 | 22 | 1 / 1 |

**Không cấu hình nào trong grid tạo thêm seed phòng tắm.** Hạ component min xuống3 làm thay đổi filtration dùng để chọn PLATEAU; ngưỡng tăng tới giá trị clearance khoảng0.60m. Cutoff native là strict `>` nên các nodes đúng tại ngưỡng bị loại. Component bathroom3nodes tại ngưỡng cũ không còn được giữ như phép thử “mọi raw component làm seed” trước đây.

Giải thích thêm từ filtration native và mã `getBestPlateau`: với component min3, các đoạn nhiều component chỉ tồn tại trên dải clearance khoảng0.034315m (hoặc độ dài0 tại các event đồng mức). Ngưỡng lifetime tương đối hiện tại yêu cầu khoảng0.100000m ở graph60s và0.109808m ở graph300s, nên các đoạn này không được chọn. Có nhánh fallback về sequence đầu nếu không đoạn có component dương nào vượt điều kiện; đây là hành vi native đã có, không do harness thay đổi. [Plateau explanation](../../runs/hydra-objectnav/B1-ab-20261107/plateau-explanation.json) xuất số liệu từ native logs; phép tái tính chọn sequence khớp threshold native cho cả6cases c10/5/3 trên hai graph.

Hạ room min10→5 không có tác dụng khi chỉ có một seed lớn. Toàn bộ membership vẫn một room với34/102places, không unassigned; co-membership disagreement với baseline0%. Đây là **độ nhạy tham số trên cùng graph**, không là accuracy hay ổn định thời gian. Hai baseline repeats cho kết quả thuật toán giống hệt.14native calls trong lượt xác nhận có source/library fingerprints exit0; lượt đầu14calls cũng cùng kết quả, lưu riêng. Original graph/config hashes giữ nguyên.

[Size60s summary](../../runs/hydra-objectnav/B1-ab-20261107/size-verified/short60/summary.json), [size300s summary](../../runs/hydra-objectnav/B1-ab-20261107/size-verified/long300/summary.json). Mỗi case có YAML riêng, compiler-linked native command, filtration, raw output và overlay SVG.

## Density replay

Đã chạy baseline fresh worker và một lần lặp lại trên cùng10accepted frames từ recording60s. Cả hai khớp input-prefix SHA `2761790bdecfcc63324b678a32f955ddc74b759895fb1b41920b693b97471bae`, native source/binding/config hashes và đóng sạch. Thời gian wall khoảng31–32s/case chỉ là chi phí replay offline, không là benchmark control hay latency live.

Hash toàn file graph khác giữa bản ghi, replay và repeat. Tuy nhiên JSON native **places (bao gồm XYZ/clearance/recorded memberships), edges và toàn bộ room_finder output giống hệt** cả ba; baseline có34places/91edges/raw16,1,3/seed16/room34. Vì vậy đối chứng của nhánh phân phòng đạt parity cấu trúc; chưa giải thích toàn bộ khác biệt bytes của mesh/attributes ngoài phạm vi room audit.

### Kết quả recording60s và tương tác hai yếu tố

| Compression (m) | Component min | Room min | Places / edges | Seeds | Room sizes | Support ROI |
| --- | --- | --- | --- | --- | --- | --- |
| 1.0 | 10 | 10 | 34 / 91 | 16 | 34 | 6nodes; chưa seed riêng |
| 1.0 | 3 | 10 | 34 / 91 | 11 | 34 | chưa seed riêng |
| 0.5 | 10 | 10 | 48 / 123 | 23 | 48 | 8nodes; chưa seed riêng |
| 0.5 | 3 | 10 | 48 / 123 | 23,3 | **38,10** | 8/8ROInodes vào room10 |

Compression1.0→0.5 tăng số places toàn graph34→48, ROI6→8, số XYcells0.25m toàn graph32→39 và trong ROI5→6. Cùng RGB-D nên đây là **thay cách giữ/biểu diễn support**, không thêm quan sát hay mở rộng coverage camera. Chỉ tăng density chưa tạo room riêng; chỉ hạ filter cũng chưa tạo room riêng. Kết hợp hai thay đổi mới giữ được seed3 và sau NEIGHBORS đủ10places để qua `min_room_size=10`.

Ở cấu hình kết hợp, native chọn threshold0.5656853914m. Đoạn2component tồn tại khoảng0.097640m, vượt yêu cầu PLATEAU khoảng0.069722m; đoạn3component chỉ khoảng0.029495m nên không qua. Đây là giải thích từ log cho việc nhánh nén0.5 + component3 khác với nhánh chỉ component3. Đã chạy đủ sizegrid trên graph nén0.5, giữ nguyên clearance/edges của nó: c10/5 vẫn1room; c3 với cả roommin10/5 cho2rooms38/10. Không thêm điều chỉnh PLATEAU, min-node-clearance hay merge distance.

![Cùng10frames: baseline và cấu hình kết hợp](../../runs/hydra-objectnav/B1-ab-20261107/comparison/short60-combined/density-comparison.png)

[Density-size60s fullgrid](../../runs/hydra-objectnav/B1-ab-20261107/density-size/short60/summary.json), [common XY support](../../runs/hydra-objectnav/B1-ab-20261107/comparison/short60/common-support.json). Common-cell co-membership dùng chung tọa độ, loại cells có nhiều nhãn; báo kết quả ở độ chia0.25/0.5/1.0m để lộ độ nhạy theo lưới. Đó vẫn không là accuracy.

### Recording300s: cùng hiệu ứng số room, nhưng chưa chứng minh tách đúng vùng mục tiêu

Baseline58frame replay khớp chính xác original ở places/edges/RoomFinder, với cùng input-prefix `1103b62b…`. Treatment nén0.5 chấp nhận đủ58/58frames, giữ nguyên source/build, không lỗi worker.

| Compression (m) | Component min | Room min | Places / edges | Threshold (m) | Seeds | Room sizes |
| --- | --- | --- | --- | --- | --- | --- |
| 1.0 | 10 | 10 | 102 / 325 | 0.5656853318 | 25 | 102 |
| 1.0 | 3 | 10 | 102 / 325 | 0.6000000834 | 22 | 102 |
| 0.5 | 10 | 10 | 135 / 354 | 0.5656853914 | 56 | 135 |
| 0.5 | 5 | 10 | 135 / 354 | 0.6324554682 | 41 | 135 |
| 0.5 | 3 | 10 | 135 / 354 | 0.6000000238 | 48,6 | **113,22** |

Ở0.5/3/10, toàn bộ5ROIplaces vào room22, nhưng **không seed nào giao ROI phòng tắm**. Component giao ROI chỉ2nodes nên vẫn bị lọc. Seed6 hợp lệ nằm phía ngoài ROI; NEIGHBORS lan membership từ đó vào phòng tắm và một đoạn không gian bên ngoài. Không thể coi hai room này là bằng chứng đã tách đúng bathroom/hallway.

Đặc biệt, global places102→135 nhưng ROIplaces8→5 và ROI XYcells0.25m7→3. Nén nhỏ hơn **không bảo đảm mật độ/support cục bộ tăng đơn điệu**: extractor chọn representative và vẫn merge nearby nodes ở0.5m; min GVD clearance0.4m giữ nguyên. Chưa làm A/B merge distance hay truy nguyên từng GVD voxel, nên chưa quy toàn bộ mất support cho riêng bước merge.

![300s: room22 lan từ seed ngoài ROI](../../runs/hydra-objectnav/B1-ab-20261107/comparison/long300-combined/density-comparison.png)

[Density-size300s fullgrid](../../runs/hydra-objectnav/B1-ab-20261107/density-size/long300/summary.json), [density support300s](../../runs/hydra-objectnav/B1-ab-20261107/comparison/long300/common-support.json). Cả hai grid trên fine graphs có baseline repeat chính xác; không unassigned. Roommin10→5 không thay kết quả ở các case đã thử.

## Quyết định sau A/B

**Giữ nguyên mặc định1.0/10/10.** Nhánh kết hợp0.5/3/10 là ứng viên nghiên cứu, chưa đủ bằng chứng để chọn làm profile mặc định: tốt hơn về seed mục tiêu ở snapshot60s, nhưng snapshot300s vẫn thiếu seed tại đúng ROI và chia rộng hơn. Hai recording có route/coverage khác nhau, không phải các prefix của cùng một episode; chưa suy temporal instability từ việc đối chiếu hai recording.

Bước ưu tiên tiếp theo có căn cứ là truy nguồn support cục bộ ở GVD→compressed representative→merge, và A/B riêng node_merge_distance trên cùng recording; không tiếp tục hạ filter để ép số room. `min_node_distance_m` là **minimum GVD clearance được xét để compression**, không phải minimum spacing giữa nodes. Giữ voxel size/clearance eligibility và room policy cố định trong phép thử merge để không trộn nguyên nhân. Có thể xuất GVD memberships/representative positions của ROI trước/sau merge để biết support bị bỏ ở đâu.

Trước promotion, cần annotation độc lập boundary bathroom/hallway trên observed support, kiểm tra over/under-segmentation, replay toàn pipeline với candidate room policy xuyên lịch sử, rồi live smoke/budget CPU. A/B hiện tại không sửa ObjectNav/control, không tuyên bố độ chính xác phòng hay latency live.

## Kiểm chứng và giới hạn hiện hành

Thêm offline runner `tools/run_hydra_room_size_ab.py`; chỉ tạo YAML dưới artifacts. Sáu tests kiểm tra tách config, label-invariant co-membership (đối chiếu exhaustive pair oracle), unassigned và graphID mismatch.63focused tests passed4.10s/exit0, có native fixture thật và offscreenUI/query/GT isolation. Không phải whole-suite hay live demo mới.

Full command/logs: `runs/hydra-objectnav/B1-ab-20261107/final-tests.log`, `.exit`; exact native argv trong từng case `command.json`; `short60-verified-command.json`/`long300-verified-command.json` và `density-size-*-command.json` ghi lệnh chạy grid. Protocol, SHA baseline và output giữ ở cùng artifact root. Chưa đổi production defaults, native libraries, control guard hay movement. Không tải model, không simulator mới, không commit/push.

Review độc lập Luna xhigh không phát hiện lỗi metric/isolation ảnh hưởng kết quả; nêu thiếu fingerprints source/library trong summary ban đầu. Đã bổ sung hash của harness/helper/evaluator, native RoomFinder/clustering và actual linked libraries từ `ldd`, rồi chạy lại grid vào `size-verified/` (exit0). Không dùng output cũ thiếu metadata làm artifact xác nhận cuối.

Giới hạn quan trọng: các nhánh đổi component/room min chạy **RoomFinder native đầy đủ trên graph export cố định**, còn density replay chạy nguyên worker với room policy10/10. Vì vậy cấu hình kết hợp0.5/3/10 chưa được kiểm tra bằng một episode live hoặc một worker replay giữ room policy3 xuyên toàn lịch sử; chưa có bằng chứng về ổn định roomID/split-merge qua từng revision. Mật độ và clearance/edge hỗ trợ tạo seed ở snapshot cuối đã được kiểm tra; correctness vật lý và stability online vẫn cần bước nghiệm thu riêng.

Reproduce: source `.runtime/hydra_ws/env.sh` chỉ bên trong child process theo `density/replay_prefix.py`; runner giữ đường dẫn `.runtime/hydra_ws/.venv/bin/python` nguyên symlink, không resolve thành systempython. Mỗi case có `command.json`, `replay-summary.json`, `replay-graph-manifest.json` (manifest **offline dựng từ worker close result**, không giả runtime producer), graph và `diagnostic/`. Attempt gọi sai systempython và probe malformed ban đầu được giữ trong `baseline-system-python-attempt/`, không tính vào A/B thành công.

## Nghiệm thu task A/B

**Implemented:** runner offline, metric/config isolation tests, native replay và comparison artifacts. **Correctness-verified:**63focused tests/no skips, exit0; review sizeharness và fingerprints đã xử lý. **Native offline validated:**6freshworker replays (hai loại recording, baseline/treatment và short repeats), exact accepted input prefixes,28native RoomFinder cases trong bốn factorial matrices và một repeat cấu hình kết hợp dương tính. Short treatment repeat có places/edges/RoomFinder giống hệt; khi chạy lại0.5/3/10 trên graph repeat vẫn cho38/10places. Đây là tính lặp lại trên cùng dữ liệu cuối, không là temporal stability.

[Verification](../../runs/hydra-objectnav/B1-ab-20261107/verification.json) xác nhận source/library hashes, config diff duy nhất của density treatment, replay prefixes, sourcegraph/config/worker/coordinator/safety giữ nguyên, các baseline structure parity và report links. Lệnh xác minh dưới đây exit0:

```bash
PYTHONPATH=src .venv/bin/python runs/hydra-objectnav/B1-ab-20261107/verify_experiment.py
```

Exact test argv/env: [final-tests-command.json](../../runs/hydra-objectnav/B1-ab-20261107/final-tests-command.json). Exact replay argv/source hashes: `density/<recording>/<case>/command.json`; replay runner ở `density/replay_prefix.py`. Native binary dùng lại từ task B1, không rebuild thư viện. Failed setup attempt/probe giữ làm lịch sử, không gộp vào sáu replay thành công. Không có full-suite/liveUI/simulator hay accuracy claim; task A/B hoàn tất, baseline geometry evaluation và toàn bộ roadmap vẫn còn.
