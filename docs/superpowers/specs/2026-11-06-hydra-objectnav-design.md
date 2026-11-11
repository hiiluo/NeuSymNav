# Hydra graph, evidence, room semantics và ObjectNav — thiết kế đề xuất

Trạng thái: đề xuất để review; chỉ tài liệu, chưa cho phép triển khai trong lượt lập plan.
Workspace: `.runtime/worktrees/Kiet_branch2`, HEAD `62f16fcf0b1ae508b49820e0184e99714387c490`, working tree dirty đã có từ trước.

## Mục đích và những gì đã thống nhất

Tiếp tục hoàn thiện graph/query/object evidence và ObjectNav kiểm thử độc lập; song song cải thiện control. Dưới5% freshness là mục tiêu hiệu năng, không khóa mọi task graph. Guard300ms/source gốc/horizon100ms vẫn bắt buộc.
Người dùng chọn SLM đọc **object/quan hệ dạng văn bản**, chưa dùng ảnh làm input SLM. Cần giảm place clutter, click object xem ảnh để kiểm tra association, và bằng chứng phân phòng chính xác.
Graph hiển thị được chưa chứng minh đúng association, room geometry hay ObjectNav success.

## Hiện trạng đã đọc từ code

- `backends/hydra/query.py`: `HydraSceneGraphQuery.objects/get`, pinned revision/category/XYZ/room chain đã có. `per_object_evidence_refs/confidence/verified/lifecycle` hiện None; `usable_for_targeting` KHÔNG là clearance certificate.
- `visualization/scene_graph.py`: graph2D có layer filter. `spatial_scene.py` dựng cả native place nodes; click object đã emit signal. Cần bộ lọc chung cho 2D/3D, không viết lại picking từ đầu.
- `desktop.py:_render_selected_object`: nhánh Hydra chủ động báo không có legacy best-view evidence.
- `HydraLabelRasterizer`: pixel mang CATEGORY label, không phải detection instance ID. Native Hydra là owner object IDs; không nối legacy ObjectOwner để tạo owner thứ hai.
- `_graph_summary` mới xuất ID/semantic/XYZ/parent/edge; chưa xuất geometry support/evidence per object. Source Spark-DSG hiện có `ObjectNodeAttributes.mesh_connections` và Python binding; cần probe graph artifact thực tế trước khi dựa vào mesh support/pose correction.
- Hydra room config hiện `min_dilation_m=.5`, `max_dilation_m=1.2`, `min_component_size=10`, `min_room_size=10`, mode PLATEAU. Đây là baseline đo, chưa có bằng chứng là cấu hình đúng cho mọi map.
- Control local-depth đã implement/test, nhưng300s fullrate6.96%/9.869m. Các thử cadence/GC/parallel không chứng minh long performance đạt mục tiêu. Xem `docs/results/navmap-critical-path-2026-11-06.md`.

## Hướng chọn và phạm vi

Đề xuất: giữ Hydra làm graph/room geometry owner; thêm read-only evidence/semantic services và UI; ObjectNav bắt đầu bằng replay/pure modules. Control đi nhánh riêng.
Phương án chỉ sửa UI nhanh hơn nhưng không cung cấp provenance ảnh. Phương án đưa legacy association owner vào Hydra gây hai hệ ID và không được chọn. SLM/VLM can thiệp split/merge geometry chưa có cơ sở và nằm ngoài bản đầu.
Các đề xuất số dưới đây là defaults reviewable, không phải chất lượng đã đo.

## UI dễ đọc

Preset mặc định **Rooms + Objects**, Places OFF; presets **Topology** và **All debug**. Checkbox Room/Object/Place/Building/point cloud độc lập, cùng state cho2D/3D. Giữ orbit/zoom/pan/resize và floor point cloud đang có.
Place nhỏ hơn room/object; place labels OFF; mặc định khi bật chỉ hiển thị tối đa200places, chọn deterministic theo vùng nhìn/selection, có chế độ đầy đủ trong display budget hiện có. Room/object được ưu tiên trước places khi cắt budget. Hiện raw/shown/filtered/budget-hidden counts riêng.
Picking chỉ nhận node đang visible; selected object giữ ID qua repaint, mất node phải báo unavailable. Không đổi native graph vì filter.
Nếu ẩn place làm mất đường nối, có overlay **derived room membership** từ parent chain đã biết, style/tooltip riêng; không giả làm native edge, không nối object unassigned vào phòng gần nhất. Structural edge không chứng minh đường robot đi được.

## Object evidence và association

Key bắt buộc `(episode_id,run_id,native_id,graph_revision)`; refs chứa source FrameKey/capture/clock, detection_id, RGB/mask/depth hash, bbox, calibration/pose version, detector/vocabulary, input-prefix và link method/status.
Lưu detection/mask provenance bên cạnh admission, chỉ đánh dấu input integrated sau ACK processed/prefix của Hydra. Queued/rejected/replaced không được coi là integrated evidence. ACK là frame-level, KHÔNG chứng minh detection thuộc native object nào.
Observation asset key độc lập graph revision: `(episode,run,FrameKey,detection_id,detector_hash)`. Link key là `(HydraObjectKey,observation_key,link_method_version,transform_hash)`; current-revision gallery phải recompute/revalidate link against current support/pose binding. Chỉ tái sử dụng bytes/cache ảnh, không tự carry association từ revision trước. Link cũ có thể xem trong mục lịch sử đúng revision, không được giả là current. Node disappear/merge/split không chuyển evidence sang ID khác nếu thiếu native lineage xác thực.
Gallery v1 hỗ trợ **candidate-debug**: refs truy được đúng RGB/mask/capture, link geometric/ambiguous rõ; không cam kết authoritative detection→nativeID. `query.evidence()` trả candidate refs/status; legacy `per_object_evidence_refs/verified` vẫn None nếu chưa có cơ sở native identity/verification. Muốn native-confirmed association là gate mở rộng riêng. Run cũ không lưu detection batch thì báo not_recorded; không redetect rồi coi đó là detection đã tích hợp ban đầu.
Ưu tiên native object mesh/support đã xác minh và đúng transform để project vào ảnh, kiểm depth/occlusion/mask. Nếu chỉ geometry match, trạng thái **geometric_candidate/ambiguous**, không gắn mác native-confirmed. Không link bằng nearest centroid hoặc cùng category đơn thuần. Thiếu mesh/pose correction/source thì unavailable hoặc candidate có lý do.
Gallery top3 góc đa dạng (tham khảo `BestViewSelector`, baseline .3m), crop+mask và full RGB frame; quality là heuristic, không là xác suất đúng. Các observation còn lại có danh sách phân trang để không giấu merge.
Hai detection cùng frame vào một node, một detection vào nhiều node, thay loại/geometry bất thường: flag review, không tự merge/split native IDs. Manual notes `match/suspected_merge/suspected_split/wrong_label/uncertain` chỉ là annotation.
Mặc định đề xuất: decoded image cache32MiB; sidecar evidence256MiB/run nằm trong tổng quota; index cache64MiB; trả tối đa64observation refs/page. Quota/eviction có metadata rõ, không báo thành “không có object”. Không image I/O trong control hoặc paint callback.

## Room segmentation và SLM là hai bài toán

**Geometry:** lấy native place→room membership và observed floor support/mesh; không dựng ranh giới bằng nearest room centroid rồi coi là segmentation native. Missing support là unavailable. Xuất source/config/transform, unassigned places và coverage. Support domain phải ghi `place_points|surface_points|floor_cells`: cả hai point domains chỉ đo partition trên annotated points (ARI/pairwiseF1/purity; pointIoU nếu công bố đúng tên), không gọi đó là diện tích phòng hoặc boundary accuracy. AreaIoU/boundaryF1 chỉ có cho floor_cells với GT/support tương ứng.
Đánh giá trên observed support: room instance IoU/matching, over-merge/missed split, boundaryF1(tolerance.20m, sensitivity.10/.30m), ID-invariant temporal consistency và native-ID churn. Không coi mọi thay ID là đổi geometry; không chấm không gian chưa thấy như đã phân đúng/sai.
Dùng GT/annotation chỉ evaluator offline; check annotation room definition (doorless/open-plan/mixed). Nếu scene chỉ quan sát1GTroom thì không chứng minh khả năng tách2phòng. Nếu thiếu GT thì report unsupported, giữ visual audit riêng.
**SLM:** nhận context từ một room geometry revision, distinct object IDs/categories, association quality, membership và structural relations. Không đếm nhiều frame của cùng object thành nhiều object. Room label không sửa room ID, geometry hoặc edges.
Output JSON: room_id, geometry_revision, input_evidence_hash, label, alternatives, supporting_object_ids, status/reason. Vocabulary đề xuất: bedroom,bathroom,kitchen,living_room,dining_room,office,hallway,utility,mixed,unknown. Supporting IDs phải nằm trong input. Self-reported confidence không coi là calibrated probability.
So sánh SLM với baseline luật đơn giản trên cùng predicted object context; chấm riêng room geometry đã đúng và toànpipeline để không che lỗi segmentation. Backend/model/prompt/quantization hash và seed/inference settings phải được pin. Có unknown/insufficient_evidence; no-model/timeout/badJSON không chặn graph/control. Cache theo evidence content/model/prompt; debounce3s, không infer lại khi chỉ graph revision thay mà context không đổi. Queue tối đa32room jobs,1inflight; job cũ trả về phải reject theo geometry/context hash. Đề xuất timeout5s/1CPUthread cho pilot, cần đo tài nguyên trước khi bật live. Không tự tải model/training.

## ObjectNav độc lập

Bản đầu là category ObjectNav (ví dụ chair), chưa làm language-goal/instance-specific task. Category query → candidate ranking → approach-pose proposals → verification → navigation intent adapter. Object centroid không mặc định là goal đi được. Room/SLM chỉ là prior tùy chọn, không quyết định motor hay success.
Approach poses phải kiểm footprint/support/route trên NavSnapshot; live consumer còn recheck depth/guard hiện tại.
`ObjectNavContext` pin episode/run/clock và `SpatialFrameBinding(T_nav_graph,binding_version,graph_world_epoch,nav_world_epoch,primary_calibration_hash,nav_calibration_hash,floor_datum)`. Hai sensor có calibration hash khác nhau là bình thường; cần registry/extrinsic/world-epoch binding hợp lệ, KHÔNG yêu cầu hash bằng nhau. Thiếu loop-closure/frame transform hợp lệ thì không propose approach.
SEARCH_PRIOR cho phép memory object cũ có integrity/source hợp lệ cùng run nhưng ghi age unknown khi thiếu per-object observation; graph.last_source KHÔNG là object.last_seen. APPROACH_PROPOSED đòi graph available/not-replay-required, unique fresh geometric visual match hoặc stronger verified lineage, target observation age≤2s (planning-only default), current NavSnapshot age≤300ms, source clock hợp lệ, observation.capture≤nav.capture≤now; latest target XYZ lấy từ fresh observation đã transform đúng frame. Missing/ambiguous evidence trả SEARCH/VERIFY_PENDING/unavailable thay vì commit target. Pure tests dùng clock/replay context explicit, không phát actuator command. Hai giây không gia hạn freshness motor. Verification dùng RGB-D evidence mới; ảnh gallery không tự chứng minh đã tới target. `VERIFIED` trong pure module chỉ là xác nhận quan sát target, không tự emit episode-success; distance/visibility/success protocol của native ObjectNav phải được khóa ở live integration gate. Không có GT trong runtime; state replay không phát lệnh thật.
Các node bị remove/reparent/revise, ambiguity, missing image, stale graph/map, closed goal và semantic unknown phải có kết quả typed, không fallback vô điều kiện.

## Control và rollout

Đo chi tiết sensor/render/IPC/projection/slab/raycast/raster/guard; A/B Hydra on/off với cùng recorded input để kiểm contribution, rồi native confirmation. Chưa quy toàn bộ trễ cho Hydra, frontier, CPU hay GPU.
Thiết kế process riêng sở hữu duy nhất SensorClient/capture/local-map/control/actuation. Parent chỉ gửi immutable intent, nhận publication/proofs; world/UI/SLM/telemetry không chung interpreter với critical process. Dùng spawn, bounded channels, epoch/slot leases, shutdown/timeout fail-closed; không tạo hai owner actuator. Primary capture cũng qua owner, không mở client cạnh tranh.
Đổi process không loại tranh CPU/GPU/RAM; không hứa hard-real-time. Telemetry streaming ngoài critical process vẫn giữ đủ actual invocations và proof. Dừng thread/worker không được bỏ lệnh cũ tiếp tục chạy.

## Gates riêng

A: UI/query/evidence correctness + reviewed gallery fixtures + native evidence pilot.
B: room geometry report + room-label report riêng, không claim accuracy khi chưa có annotation/support; không khóa A nếu B fail.
C: safety/provenance gate bắt buộc; freshness/movement là performance report riêng. <5% giữ là mục tiêu, không sửa denominator/TTL hay chấp nhận robot đứng để đạt nó.
E2E ObjectNav: chỉ bật bằng cờ explicit sau review adapter/verification; không suy full success từ query/replay pass. Các threshold promotion chất lượng phải chốt sau baseline annotation; bản plan này cho phép xây đo lường, không tuyên bố đạt quality.
