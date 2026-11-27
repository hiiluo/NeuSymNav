# Audit thuộc tính native Hydra và Spark-DSG

Audit này là đầu vào bắt buộc của [milestone Native Hydra Attribute and Query API Enhancement](../superpowers/plans/2026-11-26-native-hydra-attribute-query.md). Phạm vi gồm sáu kiểu được yêu cầu, các trường bounding box và membership/topology liên quan. Kết luận mô tả NeuSymNav working tree trên HEAD `8f0521e5d10f6965ce96173329673033d23d350b`, đang có thay đổi local. [Repo NeuSymNav](https://github.com/hiiluo/NeuSymNav), [Hydra 2.0.0 tại 2e58a35baea629eee8838409771876acff015daf](https://github.com/MIT-SPARK/Hydra/tree/2e58a35baea629eee8838409771876acff015daf), [Spark-DSG 1.1.3 tại 3c40997e4ae739c56ed3cdd6ef5e882d403d8b64](https://github.com/MIT-SPARK/Spark-DSG/tree/3c40997e4ae739c56ed3cdd6ef5e882d403d8b64).

## Cách đọc ma trận

- **Schema / Py** xác nhận thứ tự khai báo native và thuộc tính Python ở đúng commit. Probe kiểm tra 30 trường khai báo, gồm cả kế thừa khi đọc node thực tế. `metadata` được bind thành `_metadata` và package có getter `metadata.get()`. `NO_SEMANTIC_LABEL` là hằng số sentinel, được ghi cùng `semantic_label`. [node schema][node-schema], [edge schema][edge-schema], [bindings][attrs], [scene graph][scene], [bbox binding][bbox].
- **Hydra hiện tại** phân biệt trường có producer trong đường active, default, producer có điều kiện hoặc chưa có bằng chứng. **Export sống** là JSON từ `_graph_summary`. **Downstream** là adapter/query/context/UI đang đọc field đó. Native file cuối lượt là đường export riêng. [Worker](../../src/neusymnav/backends/hydra/worker.py), [adapter](../../src/neusymnav/backends/hydra/graph_adapter.py), [query](../../src/neusymnav/backends/hydra/query.py).
- **Bằng chứng** là kiểm trực tiếp hai native artifacts lịch sử bằng binding local. `18 O`, `9 R`, `1.344 P` là tổng objects, rooms và places trong đúng hai snapshot, với NodeAttributes và SemanticNodeAttributes kế thừa kiểm ở cả ba loại. Giá trị default/rỗng được quan sát chỉ xác nhận trạng thái của hai snapshot. Chưa có rollout mới hay trace theo nhiều revision trong milestone audit.
- **RG** và **Tương lai** nêu nhu cầu consumer. `Gián tiếp` là tín hiệu hỗ trợ và có thể thay bằng nguồn có provenance tương đương. `—` là chưa có consumer cụ thể. Danh sách module theo [roadmap](future-module-integration-roadmap.md).

## NodeAttributes và SemanticNodeAttributes

| Trường | Schema / Py | Hydra hiện tại | Export sống | Downstream hiện tại | Bằng chứng hai export | RG | Tương lai |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `position` | Có / có | Object từ mesh, room từ place cluster, place từ GVD | XYZ | Adapter, UI, object query | Hữu hạn ở O/R/P | Có | HAM, VL, HSGM |
| `last_update_time_ns` | Có / có | Object cập nhật khi mesh segmenter tạo/update. GVD place có timestamp. Room mặc định trong makeRoomLayer | — | — | O/P > 0, R = 0 | Gián tiếp, provenance | HAM, Apex |
| `is_active` | Có / có | Object theo active mesh support/archive. Place theo active GVD. Room mặc định | — | — | O 16 true, P 1.153 true, R đều false | Gián tiếp, diagnostics | HAM |
| `is_predicted` | Có / có | Chưa thấy predictor ghi cho O/R/P ở profile này | — | — | Tất cả false | — | Có thể dùng nếu có prediction producer |
| `metadata` | Có / `_metadata` và facade | Không thấy metadata có nghĩa ở mẫu | — | — | Rỗng ở toàn bộ O/R/P | Gián tiếp, allowlist provenance | Consumer theo key cụ thể |
| `name` | Có / có | MeshSegmenter và RoomFinder không gán tên trong đường đã đọc | Dùng tên nếu có, fallback label số | Display name, taxonomy query dựa ID | Tất cả native name rỗng | Gián tiếp | HAM, VL |
| `color` | Có / có RGB | Không thấy producer native color cho O/R/P profile hiện tại | — | Viewer tự dùng màu hiển thị | Native RGB zero | — | — |
| `bounding_box` | Có / có | Object bbox được tính lại từ mesh. Room/place không có bbox hợp lệ trong mẫu | Riêng object, envelope từ min/max của tám corners | Projection/UI crop qua `object_bounds`. Object query chưa trả native box | 18 AABB hợp lệ, R/P invalid | Có, hình học và liên kết evidence | HSGM, Apex, VL |
| `semantic_label` | Có / có, sentinel uint32 max | Object từ class raster. RoomFinder đặt 0. Place dùng sentinel ở mẫu | Label số | Taxonomy object và UI, room labeling riêng | O có nhãn class, R = 0, P = 4294967295 | Có, gốc detector | PSG, HAM, VL, Apex |
| `semantic_feature` | Có / có float matrix | Worker gọi `step(..., depth, labels, rgb)` thiếu feature arg. Native view feature path có điều kiện, producer chưa nối trong profile | — | — | Tất cả O/R/P shape 0×0 | Có với feature mới và spec tương thích. Native raw nullable | PSG, HAM, VL |

Bbox bind riêng `type` (INVALID/AABB/OBB/RAABB), `dimensions`, `world_P_center`, `world_R_center`, `corners()` và `is_valid()`. Probe xác nhận dimensions finite và tám corners cho 18 AABB. Kiểm fixture OBB/RAABB trước khi công bố parity cho các kiểu này. Envelope cũ tiếp tục tính từ đủ tám góc. Giữ box orientation riêng với `world_R_object`. `BoundingBox.min/max` ở binding áp rotation lên hai góc đối diện, nên không dùng hai property đó để suy world AABB cho rotated box. [Bbox binding][bbox], [mesh objects][mesh], [backend objects][objects], [GVD place update][gvd].

`last_update_time_ns` phản ánh lần writer native cập nhật node theo clock frame được truyền vào. Lần Hydra chấp nhận frame gần nhất có `last_source`/capture time và revision, mô tả snapshot. Thời điểm publish snapshot là thời gian xử lý, có clock provenance riêng nếu cần đo. `verified_last_seen` chỉ có khi một observation có liên kết đủ mức xác minh cho đúng native object và có timestamp nguồn. Không lấy MAX giữa ba loại timestamp hoặc coi node active là object đang thấy. [Frame contract](../../src/neusymnav/contracts/hydra_graph.py), [evidence](../../src/neusymnav/contracts/hydra_evidence.py), [mesh writes][mesh].

## ObjectNodeAttributes và RoomNodeAttributes

| Trường | Schema / Py | Hydra hiện tại | Export sống | Downstream hiện tại | Bằng chứng hai export | RG | Tương lai |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `mesh_connections` | Có / có | MeshSegmenter quản lý list vertex indices, remap khi mesh delta và gộp khi merge. Backend hợp nhất và cập nhật geometry | — | Reader native offline. UI crop hiện dùng bounds/raster/depth | 18/18 nonempty, mọi index thuộc range mesh của chính export | Có cho support/linking, mesh-faithful arm cần chi tiết | Apex, HSGM |
| `registered` | Có / có | Chưa thấy producer registration cho object profile | — | — | 18 false | — | Theo consumer registration thực tế |
| `world_R_object` | Có / có Quaternion | Constructor identity, transform có thể đổi frame. Mesh box orientation có trường riêng | — | — | 18 identity, chưa chứng minh estimated object rotation | — | Theo consumer pose thực tế |
| `semantic_class_probabilities` | Có / có map string→double | RoomFinder dựng room geometry và label 0. Room label service chạy riêng | — | `RoomLabelResult` và `RoomLabelPublication` mang kết quả local riêng | 9/9 entries=0 | —. Embedding/retrieval là giá trị khác | PSG/HAM nếu có calibrated room-belief producer |

Room bbox/semantic feature là trường kế thừa. Native room không có polygon/bbox hợp lệ trong hai export. Room geometry support hiện có thể truy qua membership và các place positions. Nếu room-support của repo có geometry hash trùng graph revision và source prefix thì dùng support đó. Hull từ các place positions nếu thêm trong tương lai phải gắn tag derived, floor và coverage. Room labels SLM/VLM giữ trong `RoomLabelPublication`, với request key bao gồm revision, geometry/context hashes và world epoch nếu có. Label score chưa hiệu chuẩn giữ riêng với map probability. [Room finder][room], [RoomContext](../../src/neusymnav/rooms/context.py), [RoomLabelResult](../../src/neusymnav/contracts/room_semantics.py), [publication](../../src/neusymnav/contracts/room_label_publication.py), [room stability](../../src/neusymnav/backends/hydra/room_stability.py).

## PlaceNodeAttributes

| Trường | Schema / Py | Hydra hiện tại | Export sống | Downstream hiện tại | Bằng chứng hai export | RG | Tương lai |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `distance` | Có / có | Khoảng cách GVD tới mặt cản tại voxel đại diện, theo mét ở profile này | — | Native room filtration | 1.344/1.344 dương | Gián tiếp cho spatial support | HSGM, VL |
| `num_basis_points` | Có / có | Số basis points GVD của voxel đại diện được extractor chép vào place | — | Native extraction, không có query Python | 1.344/1.344 dương | — | Diagnostics topology |
| `voxblox_mesh_connections` | Có / có, `NearestVertexInfo` | GVD extractor gắn basis/support refs theo block/voxel/vertex/optional label | — | Native, không có consumer live | 1.344/1.344 nonempty. Chưa kiểm remap | Gián tiếp, optional geometry | HSGM |
| `pcl_mesh_connections` | Có / có | Có đường ghi có điều kiện trong PlaceMeshConnector | — | — | Toàn bộ rỗng | — | Nếu producer và consumer cùng có |
| `mesh_vertex_labels` | Có / có | Có đường ghi cùng PlaceMeshConnector | — | — | Toàn bộ rỗng | — | Như trên |
| `deformation_connections` | Có / có | Có đường ánh xạ sang deformation graph trong PlaceMeshConnector | — | Native có consumer PGMO, không expose | Toàn bộ rỗng trong file đã đọc | — | Diagnostics PGMO |
| `real_place` | Có / có | Default true. Frontier extractor đặt false cho synthetic frontier node | — | — | Toàn bộ true, profile không bật native frontier | Gián tiếp để lọc | VL, Apex, HSGM |
| `need_cleanup` | Có / có | Flag nội bộ. Frontier extractor đặt true khi tạo frontier. Default false | — | — | Toàn bộ false | — | — |
| `active_frontier` | Có / có | Frontier extractor gán theo frontier type. Hiện tắt native frontier | — | NeuSymNav dùng frontier riêng | Toàn bộ false | — | VL/Apex nếu bật và xác minh native consumer |
| `anti_frontier` | Có / có | Default false. Chưa thấy writer active trong profile | — | — | Toàn bộ false | — | Khi semantics producer đã xác minh |
| `frontier_scale` | Có / có | Scale của frontier representation do FrontierExtractor ghi | — | — | Toàn bộ zero. Native frontier tắt | — | VL/HSGM nếu có native consumer |
| `orientation` | Có / có Quaternion | FrontierExtractor gán orientation khi tạo frontier. GVD place không có heading được xác nhận | — | — | Toàn bộ identity | — | Visualization nếu có valid producer |
| `num_frontier_voxels` | Có / có | Số voxel trong frontier cluster do FrontierExtractor gán | — | — | Toàn bộ 0. Native frontier tắt | — | VL/Apex nếu có native consumer |

`distance` là thông tin local của GVD. Nó không xác minh clearance hiện tại trên toàn đường, robot footprint, unknown cells hoặc chướng ngại mới. `real_place=true` là cờ kiểu native, không xác nhận robot đi tới được. `NearestVertexInfo.vertex` phải giữ namespace/block và nguồn của chính producer. Chưa có bằng chứng nó tương đương list mesh index của object. [Graph extractor][extract], [GVD update][gvd], [FrontierExtractor][frontier], [PlaceMeshConnector][place-mesh], [hai profile](current-system-audit.md#provenance-và-môi-trường).

## EdgeAttributes và topology

| Trường | Schema / Py | Hydra hiện tại | Export sống | Downstream hiện tại | Bằng chứng hai export | RG | Tương lai |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `weighted` | Có / có | Constructor có weight đặt flag. Edge membership/room adjacency không có weight trong mẫu | — | Topology chỉ đọc edge kind/endpoints | 6.050 place-place true, 8 room-room và 1.416 interlayer false | Có nếu query weight | HSGM, VL |
| `weight` | Có / có | GVD place edges theo min clearance của endpoints/voxels được lấy mẫu. Freespace heuristic edge có đường kiểm observed/threshold riêng. Chưa có provenance chính xác từng edge | — | Không đưa planner làm cost | 6.050 finite, 00770 khoảng 0,20–1,81 m, 00806 0,20–1,20 m. Weight ở edges `weighted=false` không hợp lệ về nghĩa | Gián tiếp | Spatial cue, không phải path length |
| `metadata` | Có / `_metadata` và facade | Chưa thấy metadata có nghĩa ở edges đã đọc | — | — | Rỗng ở place/room edges mẫu. Không có object-object edge để kiểm | Gián tiếp nếu có producer | Consumer theo key cụ thể |

| Quan hệ | Producer / view hiện tại | Bằng chứng | Hướng mở rộng |
| --- | --- | --- | --- |
| Room → places | RoomFinder tạo parent edges cho place trong cluster. Summary có parent và edge | 1.341/1.344 places lần được tới room | Query children theo revision, giữ unassigned và floor |
| Room ↔ room | Adjacency từ place clusters kết nối qua place graph | 7 + 1 room-room edges ở hai export | Trả structural adjacency và provenance. Không suy portal/door clearance |
| Object → room | Query đi theo parent chain. Chấp nhận chain hợp lệ tới room | 18/18 objects lần được tới room trong hai export | Trả chain và membership kind. Không suy containment trực tiếp từ bbox hay gần tâm |
| Object ↔ object | Kiểu EdgeAttributes native có weight/metadata, không có relational tensor riêng | 0 cạnh nội tầng ở 18 object. Mẫu này chỉ nói về hai export | Typed structural relation giữ riêng với visual relation/evidence/predicate trên sidecar |

Ở cùng snapshot, classification `weighted=true` chỉ xác nhận field được writer đánh dấu hợp lệ. Chỉ gắn đơn vị và `weight_kind=gvd_clearance` khi scope/layer/profile đã pin và chứng minh source. Cạnh source không rõ dùng `native_untyped`. Freespace heuristic và overlap nếu được bật có cách tính theo producer. Không dùng reconstruction graph làm chứng nhận chuyển động. [GVD edge weights][extract], [heuristic edges][edge-util], [room adjacency][room-util], [serialization edge][edge-serialization].

## Replay, serialization và giới hạn kiểm chứng

| Artifact | Revision | Mesh vertices | Objects / places / rooms | Gọi lại `_graph_summary` |
| --- | ---: | ---: | ---: | --- |
| 00770 | 196 | 46.142 | 7 / 1.062 / 7 | 656.885 byte JSON compact, 5.914 edges |
| 00806 | 34 | 14.246 | 11 / 282 / 2 | 169.342 byte JSON compact, 1.503 edges |

Đọc đúng hai `graph_path` từ [audit artifacts](../../runs/objectnav/hydra-msgnav-audit/local-graph-audit.json), tính SHA-256 khớp manifest rồi mở bằng `DynamicSceneGraph.load`. Probe save/reload vào thư mục tạm với mesh giữ đúng mảng vertices, summary, edge weights và các phân loại thuộc tính node trong bảng. Kích thước đo chỉ tính body của summary, chưa gồm envelope, overhead IPC, compression hoặc peak RSS. So sánh giữa các file schema cũ cần lưu header Spark-DSG. `is_predicted` có guard file version 1.0.4 và `anti_frontier` từ 1.1.3. Default của file cũ không chứng minh producer đã đo giá trị. [Serializer][node-serialization].

- `git -C .runtime/hydra_ws/src/hydra rev-parse HEAD` và `git -C .runtime/hydra_ws/src/spark_dsg rev-parse HEAD` exit 0, khớp hai pin. Cả hai checkout sạch ở lượt audit.
- `bash -c 'source .runtime/hydra_ws/env.sh && export PYTHONPATH="src:${PYTHONPATH:-}" && .runtime/hydra_ws/.venv/bin/python runs/hydra-attribute-query/native-attribute-audit-20261126/inspect_attributes.py'` exit 0. Binding probe chạy CPU trên artifacts đã lưu. [Script audit](../../runs/hydra-attribute-query/native-attribute-audit-20261126/inspect_attributes.py), [kết quả](../../runs/hydra-attribute-query/native-attribute-audit-20261126/attributes.log). Chưa kiểm stability của mesh indices qua revision, lineage object/room, fresh native features, performance IPC mới hoặc integration policy.
- `HydraPipeline.graph` trả clone của backend. Pybind setter có thể chỉnh object trên clone. Mutation của clone không cập nhật state mapping đang chạy. [Hydra Python binding][clone].

[node-schema]: https://github.com/MIT-SPARK/Spark-DSG/blob/3c40997e4ae739c56ed3cdd6ef5e882d403d8b64/include/spark_dsg/node_attributes.h#L94-L305
[edge-schema]: https://github.com/MIT-SPARK/Spark-DSG/blob/3c40997e4ae739c56ed3cdd6ef5e882d403d8b64/include/spark_dsg/edge_attributes.h#L64-L85
[attrs]: https://github.com/MIT-SPARK/Spark-DSG/blob/3c40997e4ae739c56ed3cdd6ef5e882d403d8b64/python/bindings/src/attributes.cpp
[scene]: https://github.com/MIT-SPARK/Spark-DSG/blob/3c40997e4ae739c56ed3cdd6ef5e882d403d8b64/python/bindings/src/scene_graph.cpp#L217-L266
[bbox]: https://github.com/MIT-SPARK/Spark-DSG/blob/3c40997e4ae739c56ed3cdd6ef5e882d403d8b64/python/bindings/src/bounding_box.cpp#L50-L79
[node-serialization]: https://github.com/MIT-SPARK/Spark-DSG/blob/3c40997e4ae739c56ed3cdd6ef5e882d403d8b64/src/node_attributes.cpp
[edge-serialization]: https://github.com/MIT-SPARK/Spark-DSG/blob/3c40997e4ae739c56ed3cdd6ef5e882d403d8b64/src/edge_attributes.cpp
[mesh]: https://github.com/MIT-SPARK/Hydra/blob/2e58a35baea629eee8838409771876acff015daf/src/frontend/mesh_segmenter.cpp#L165-L318
[objects]: https://github.com/MIT-SPARK/Hydra/blob/2e58a35baea629eee8838409771876acff015daf/src/backend/update_objects_functor.cpp
[room]: https://github.com/MIT-SPARK/Hydra/blob/2e58a35baea629eee8838409771876acff015daf/src/rooms/room_finder.cpp#L311-L353
[room-util]: https://github.com/MIT-SPARK/Hydra/blob/2e58a35baea629eee8838409771876acff015daf/src/rooms/room_utilities.cpp
[gvd]: https://github.com/MIT-SPARK/Hydra/blob/2e58a35baea629eee8838409771876acff015daf/src/frontend/gvd_place_extractor.cpp
[extract]: https://github.com/MIT-SPARK/Hydra/blob/2e58a35baea629eee8838409771876acff015daf/src/places/graph_extractor.cpp
[edge-util]: https://github.com/MIT-SPARK/Hydra/blob/2e58a35baea629eee8838409771876acff015daf/src/places/graph_extractor_utilities.cpp
[frontier]: https://github.com/MIT-SPARK/Hydra/blob/2e58a35baea629eee8838409771876acff015daf/src/frontend/frontier_extractor.cpp#L509-L553
[place-mesh]: https://github.com/MIT-SPARK/Hydra/blob/2e58a35baea629eee8838409771876acff015daf/src/frontend/place_mesh_connector.cpp
[clone]: https://github.com/MIT-SPARK/Hydra/blob/2e58a35baea629eee8838409771876acff015daf/python/bindings/src/python_pipeline.cpp#L230-L246
