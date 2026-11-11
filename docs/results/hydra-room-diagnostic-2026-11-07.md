# Chẩn đoán native Hydra room segmentation — 2026-11-07

Task B1 có giới hạn trong `Kiet_branch2`: giải thích vì sao graph00805 chỉ có một room, với cặp vùng người dùng chọn là **phòng tắm và hành lang ngay bên ngoài**. Đã xác định cơ chế trên hai graph đã ghi; chưa sửa thuật toán hay tham số production, chưa chứng minh accuracy phân phòng.

## Kết luận từ native RoomFinder

Ở ngưỡng native chọn **0.5656853318214417 m**, cụm places phía phòng tắm chỉ có **3 nodes** vượt bộ lọc clearance/cạnh và nối thành một component. Nó bị loại bởi `min_component_size=10` **trước NEIGHBORS**. Còn một seed lớn; NEIGHBORS gán các places còn lại vào seed đó và tạo một room. Vì vậy, hai seed phòng hợp lệ chưa được tạo rồi mới bị gộp; nguyên nhân quan sát được nằm ở bước lọc component tạo seed.

Đây là kết quả gọi **thư viện Hydra native đã cài**, dùng RoomFinder/getBestComponents và clusterGraphByNeighbors thực tế. Không dùng thuật toán Python thay thế để suy ra seeds. Helper C++ chỉ bật filtration logging cho bản dựng offline; không rebuild/thay thư viện Hydra hay sửa graph gốc.

| Input ghi sẵn / fixture | Places / cạnh | Ngưỡng chọn (m) | Component trước lọc kích thước | Seeds còn lại | Membership sau NEIGHBORS | Rooms |
| --- | --- | --- | --- | --- | --- | --- |
| 00805, 60s, revision10 | 34 / 91 | 0.5656853318214417 | 16, 1, **3** | 16 | 34 | 1 |
| 00805, 300s, revision58 | 102 / 325 | 0.5656853318214417 | 25, 1, **3**, 3, 3, 1, 1 | 25 | 102 | 1 |
| Synthetic hai cụm đủ lớn, cùng cấu hình | 32 / 241 | 0.75 | 16, 16 | 16, 16 | 16, 16 | 2 |

Membership tái dựng khớp bản ghi **34/34 và 102/102 places**. Fixture chứng minh đường native có thể tạo hai room khi có hai seed đủ lớn; không chứng minh chất lượng trên nhà thật. Số component hợp lệ lớn nhất trong filtration native của cả hai graph ghi sẵn vẫn là một.

## Đối chiếu phòng tắm / hành lang

Dùng RGB-D và pose đã ghi để dựng montage camera, projection XY và đối chiếu places. ROI định tính XY `[-0.9,0.4] × [-2.8,-0.8] m` giúp định vị phía phòng tắm; đây là lựa chọn khảo sát từ dữ liệu quan sát và cặp vùng người dùng mô tả, **không phải annotation không gian độc lập**.

- Graph60s: ROI có6places; component vượt ngưỡng gồm `p(108), p(125), p(146)` →3nodes → bị lọc.
- Graph300s: ROI có8places; component vượt ngưỡng gồm `p(125), p(134), p(140)` →3nodes → bị lọc.
- Đường maximin trên graph từ ROI tới seed lớn có bottleneck lần lượt khoảng0.20m và0.40m, đều dưới ngưỡng0.565685m. Đây là clearance/trọng số graph, **không phải đo bề rộng cửa**.
- Số input được Hydra chấp nhận tăng10→58, places toàn graph tăng34→102, nhưng component phía phòng tắm vẫn3nodes. Chạy lâu hơn tự nó chưa giải quyết thiếu support cục bộ sau lọc.

![Clearance, seeds và membership — graph60s](../../runs/hydra-objectnav/B1-diagnostic-20261106/short60/room-stages.png)

[Overlay60s có tooltip clearance/cạnh/seeds/membership](../../runs/hydra-objectnav/B1-diagnostic-20261106/short60/room-overlay.svg), [overlay300s](../../runs/hydra-objectnav/B1-diagnostic-20261106/long300/room-overlay.svg), [montage10 input đã chấp nhận](../../runs/hydra-objectnav/B1-diagnostic-20261106/main/accepted-primary-montage.png), [observed RGB-D và places](../../runs/hydra-objectnav/B1-diagnostic-20261106/main/coverage-places-topdown.png).

## Vì sao chưa nên chỉ hạ ngưỡng10→3

Đã làm thêm một phép thử native **chỉ để chẩn đoán**: tại đúng ngưỡng đã chọn, truyền mọi raw component làm seeds cho NEIGHBORS. Không thay output RoomFinder gốc và không áp dụng cấu hình mới.

- Bản60s cho cluster sizes `27,1,6`; cluster chứa ba nodes phía phòng tắm có6places, vẫn dưới `min_room_size=10`.
- Bản300s cho `69,5,10,10,5,2,1`; cluster chứa ba nodes phía phòng tắm có10places, vừa đạt điều kiện kích thước room. Một cluster khác cũng có10places; chưa có annotation để biết nó là phòng thật hay tách sai.

Phép thử này **không tương đương chạy lại toàn bộ RoomFinder với min_component_size mới**: đổi tham số đó có thể thay filtration và ngưỡng được chọn. Nó chỉ tách vai trò hai bộ lọc. Kết quả nằm trong `room_finder.counterfactual_unfiltered_component_propagation` với scope riêng.

Cơ chế đã xác nhận là tương tác giữa support places cục bộ sau lọc clearance và các mức tối thiểu theo số node. Chưa chứng minh phần thiếu support xuất phát chủ yếu từ coverage, voxel/mesh, place compression hay tham số. Cấu hình có `compression_distance_m=1.0`, `node_merge_distance_m=0.5`, `min_node_distance_m=0.4`; ảnh hưởng nhân quả của chúng chưa được A/B.

## Phạm vi triển khai và kiểm chứng

**Implemented:** helper native `tools/native/hydra_room_diagnostic.cpp`, CLI `tools/diagnose_hydra_rooms.py`, bộ tổng hợp/overlay `src/neusymnav/evaluation/room_diagnostics.py`, tests. CLI kiểm tra graph/manifest/config hashes, membership parity và graph gốc không thay đổi; report không xuất accuracy khi thiếu annotation. Hỗ trợ baseline PLATEAU + NEIGHBORS hiện tại.

**Correctness-verified:**57 focused tests passed, exit0; gồm native synthetic thực tế (bật bằng biến môi trường, không skip), strict cutoff, component consistency, room-quality/GT isolation, scene query và UI offscreen. Đây không phải toàn bộ suite. Build helper exit0; hai native graph reconstruction và fixture exit0. Các SHA baseline của config, Hydra worker, coordinator, safety và hai graph/manifests khớp nguyên trạng.

**Runtime-validated:** helper offline đã chạy với thư viện native trên hai graph thật. Không chạy simulator/live UI mới, không tuyên bố demo mới hay sửa phân phòng production. Graph cuối có thể khác graph trung gian trước mỗi lần backend cập nhật; parity cuối không biến reconstruction thành trace lịch sử nguyên bản.

Native source commit `2e58a35baea629eee8838409771876acff015daf`; SHA256 thư viện `libhydra.so` là `5cce5ce5c6d7bb374226969a69144a55a7d5d70862f8976fdfcae16f719a62dc`. Config SHA256 `a76b01f3a96057012354fef1e55f9623e0195b435112438e80240567af549011`. Full fingerprints/exit codes: [verification.json](../../runs/hydra-objectnav/B1-diagnostic-20261106/verification.json).

Các lệnh từ worktree Kiet_branch2:

```bash
# Build helper bằng toolchain/dependencies đã có; exact compiler argv trong build-command.json
python3 runs/hydra-objectnav/B1-diagnostic-20261106/main/native/build.py

PYTHONPATH=src .venv/bin/python tools/diagnose_hydra_rooms.py \
  --native-binary runs/hydra-objectnav/B1-diagnostic-20261106/main/native/hydra_room_diagnostic \
  --graph runs/hydra-demo-00805-60s-NEW/hydra/native-output/hydra-graph.sparkdsg \
  --manifest runs/hydra-demo-00805-60s-NEW/hydra/native-output/hydra-export-manifest.json \
  --output-dir runs/hydra-objectnav/B1-diagnostic-20261106/short60

# Input300s: exact graph/manifest paths trong main/baseline.json;
# native argv riêng cho từng case trong short60/command.json và long300/command.json.
PYTHONPATH=src .venv/bin/python tools/diagnose_hydra_rooms.py \
  --native-binary runs/hydra-objectnav/B1-diagnostic-20261106/main/native/hydra_room_diagnostic \
  --synthetic-fixture --output-dir runs/hydra-objectnav/B1-diagnostic-20261106/synthetic

NEUSYMNAV_HYDRA_ROOM_DIAGNOSTIC_NATIVE=runs/hydra-objectnav/B1-diagnostic-20261106/main/native/hydra_room_diagnostic \
PYTHONPATH=src QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q \
  tests/test_hydra_room_diagnostics.py tests/test_hydra_room_quality.py \
  tests/test_room_gt_isolation.py tests/test_hydra_scene_graph_query.py \
  tests/test_hydra_layer_visibility.py tests/test_scene_graph_ui.py \
  tests/test_spatial_scene_regressions.py tests/test_hydra_spatial_scene.py
```

## Bước tiếp theo có căn cứ

1. Giữ baseline hiện tại; dùng cùng recording để thử riêng **coverage/place support** và **chính sách kích thước component/room**. Báo cả raw components, threshold, seed survival, final room size và assignment stability. Không đánh giá bằng mục tiêu “đủ2room”.
2. Bổ sung annotation không gian độc lập cho bathroom/hallway trên observed support; đánh giá under/over-segmentation riêng. Quan sát RGB-D hiện tại giúp định vị, chưa đủ chấm accuracy. Nếu recording chưa phủ đủ nội thất, mới chạy một route ngắn có mục tiêu quan sát hai bên lối nối.
3. Chỉ cân nhắc chỉnh compression hoặc ngưỡng số node khi A/B chỉ ra lợi ích; có thể khảo sát tiêu chí support không phụ thuộc quá mạnh mật độ node. Đây là thử nghiệm tiếp theo, **chưa triển khai**.
4. Tiếp tục A2 provenance/sidecar và A3 object gallery, query/ObjectNav offline độc lập. Bộ lọc UI A1 có test offscreen mới; live picking/gallery vẫn chưa chứng minh. SLM dùng text context sau baseline geometry, không dùng nhãn SLM để chứng nhận ranh giới đúng.

Mốc kết thúc task chẩn đoán đã đạt: **seed phía phòng tắm bị loại trước NEIGHBORS**, kèm dữ liệu native/overlay/parity. B1 đánh giá accuracy, toàn bộ roadmap, live evidence gallery và long-run performance vẫn chưa hoàn tất.
