# NeuSymNav Implementation Plan

> **For agentic workers:** Khi được giao thực thi, dùng `superpowers:subagent-driven-development` hoặc `superpowers:executing-plans` nếu có; nếu không có skill, vẫn thực thi theo task/gate và chính sách local. Skill không được thay model allowlist, mở rộng quyền hay tự chọn Astra. Các bước dùng checkbox để theo dõi.

**Goal:** Hợp nhất các tài sản đã chọn thành pipeline single-floor online có canonical object graph, geometric room hierarchy, frontier navigation, replay và kiểm chứng.

**Architecture:** Port chọn lọc vào package `neusymnav`; object state/evidence dựa trên NewOH3DSG, appearance và region backend dựa trên 3DSG. Navigation và historical graph có freshness contract riêng, dùng một canonical object owner; worker cô lập các dependency khác ABI.

**Tech Stack:** Python, NumPy/SciPy, SQLite WAL, YOLOE, OpenCLIP, native DuDe/C++, Habitat qua worker, PyQt UI. Versions/interpreters pin sau P00; core host Python 3.12 là đề xuất cần preflight.

**Spec:** [architecture.md](architecture.md). **Agent routing:** [agent-orchestration.md](agent-orchestration.md). **Checkpoint:** [implementation-status.md](implementation-status.md).

## Global Constraints

- Chỉ sửa `NeuSymNav/`; hai folder nguồn chỉ đọc. Source cuối tự chứa, model/dataset ngoài package có manifest/checksum.
- Canonical world Z-up, right-handed; mét/radian; optical camera +X phải/+Y xuống/+Z trước; metric axial depth. Y-up adapter theo ma trận trong spec.
- Runtime single-floor, pose simulator, frontier-only; semantic GT chỉ evaluator. Extensions E1–E4 chưa thuộc core.
- Một canonical object owner; alias/provenance xuyên consumers. Region ID độc lập nhãn phòng. Unknown không free; structural connectivity không bảo đảm robot passability.
- Chọn model và effort theo [chính sách điều phối hiện hành](agent-orchestration.md); các nhãn owner/reviewer cụ thể bên dưới là phân công của kế hoạch cũ, không ghi đè chính sách hiện hành.
- Không training/tải lớn/push/publish hoặc tự commit. Một GPU workload/benchmark tại một thời điểm; không đổi gate/TTL để che fail.
- Tài liệu mô tả **lệnh và files sẽ được tạo**, không khẳng định chúng đã có hoặc đã chạy. Lệnh dưới đây chạy từ `NeuSymNav/` bằng interpreter được P00 khóa; `python` là interpreter đó, không mặc định Python hệ thống.

## Review Focus

1. Transform chỉ đúng centroid nhưng sai yaw/AABB/covariance hoặc camera axes: test P01 roundtrip và known-point oracle.
2. Replay frame trùng sau restart/alias gây double-count hoặc dangling membership: test P04/P06/P07.
3. Graph lịch sử hoặc clock domain cũ được coi là fresh: test P01/P07 và fault injection P10.
4. Room worker reject/timeout nhưng hierarchy vẫn trình bày membership mới: test P06 giữ stale geometry và unavailable membership.
5. Packaging vẫn ngầm đọc source cũ hoặc scoring loại run fail khỏi denominator: test P09 isolation và P10 failed-run accounting.

## Cách thực thi mỗi task

Đọc đúng source cần port; ghi source hashes và các thay đổi thuật toán. Với hành vi mới/rủi ro, viết test đỏ bằng oracle độc lập, chạy để xác nhận lỗi mong đợi, port/implement tối thiểu rồi chạy lại xanh. Giữ tests hữu ích từ nguồn, bổ sung tests contract mới; không viết assertion chỉ sao chép implementation. Ghi command/exit/artifact vào status. Đóng task chỉ sau review/gate; được commit checkpoint riêng khi người dùng đã cho quyền commit.

Các thư mục bên dưới là cấu trúc đích; P00 chỉ tạo scaffold cần cho kiểm tra import, các task sau tạo modules của mình. Không copy toàn bộ `runs`, datasets, weights, virtualenv, caches hay `.git`.

## P00 — Khóa nguồn, môi trường và phạm vi port

**Owner:** Luna xhigh; main review. **Dependency:** yêu cầu thực thi của người dùng.

**Create:** `pyproject.toml`, `pytest.ini` (đăng ký marker `native`), `src/neusymnav/__init__.py`, `tools/inventory_sources.py`, `tools/preflight.py`, `docs/source-provenance.json`, `docs/environment-matrix.md`, `configs/runtime.example.json`, `.gitignore`, `tests/test_import_isolation.py`, `THIRD_PARTY_NOTICES.md`.

**Interface:** `inventory_sources(roots: tuple[Path,...]) -> dict`; JSON lưu relative path, SHA-256, upstream origin/license nếu có, selected/deferred và lý do; runtime config chứa executable paths cho sensor/detector/appearance/native/UI, không chứa credentials.

- [ ] Kiểm kê files/env/assets sẵn có; xác định Python Fusion và native Rebuild thực dùng, đọc notices DuDe/FIST, OctoMap/CGAL, model và HM3D. Ghi missing assets; không tải tự động.
- [ ] Tạo inventory có SHA cho selected source/dependency closure và baseline profiles. Chọn host interpreter sau import-only probe; ghi command/version/exit, không đổi môi trường nguồn.
- [ ] Tạo package namespace tránh `core`, `mapping`, `standalone_sg` đụng import. Test import chỉ package scaffold từ cwd bất kỳ, không sửa `sys.path` để trỏ folder nguồn.
- [ ] Chạy `python tools/preflight.py --contracts-only` và `python -m pytest tests/test_import_isolation.py -q`; PASS khi không cần GPU/model/Habitat và mọi thiếu hụt runtime được báo riêng. Runtime không có thì ghi blocked theo capability, không báo đủ môi trường.

**Gate:** danh mục source chọn có hash/license trạng thái rõ, source gốc không đổi, environment matrix phân biệt verified/missing. Main chốt host và interpreter mapping trước P01.

## P01 — Contracts, clock và tọa độ

**Owner:** Sol High; reviewer Sol High độc lập. **Depends:** P00.

**Create:** `src/neusymnav/contracts/{observations,graphs,navigation}.py`, `src/neusymnav/geometry/{frames,projection}.py`, `configs/taxonomy-v1.json`, `tests/test_contracts.py`, `tests/test_geometry.py`, `tests/test_clocks.py`.

**Source:** New `core/types.py`, `core/geometry.py`, `perception/base.py`; 3DSG `exploration/contracts.py`, Fusion `geometry/simulator_frames.py`, `integration_v2/conceptgraphs_adapter.py`.

**Interface:** tạo các dataclasses/interface của spec §4; thêm `to_canonical_pose(T_old: ndarray, source_convention: str) -> ndarray`, `transform_bounds(bounds: ndarray, R: ndarray) -> ndarray`, `age_ns(capture_ns: int, domain: str, now_ns: int, now_domain: str) -> int` reject negative age/domain mismatch.

- [ ] Viết `test_y_up_to_z_up_known_points`, `test_camera_optical_ray`, `test_bounds_and_covariance_roundtrip`: `(0,1,0)→(0,0,1)`, `(0,0,1)→(0,-1,0)`, determinant +1, roundtrip float64 tolerance `1e-8`; box chứa cả tám đỉnh đã đổi.
- [ ] Viết tests RGB/mask shape, duplicate detection ID, invalid calibration, bất biến array; `test_clock_domain_mismatch_rejected` và timestamp tương lai bị reject.
- [ ] Port validations/transform, pin taxonomy version giữ raw labels và unknown. Canonical alias map không lấy active-scene GT; alias/synonym không âm thầm đổi evaluator exact-score.
- [ ] Chạy `python -m pytest tests/test_contracts.py tests/test_geometry.py tests/test_clocks.py -q`; reviewer kiểm phép đổi trục/camera độc lập. Main khóa schema v1 trước parallel tasks.

**Gate:** fixtures hình học đúng theo oracle, contract serialization roundtrip, không copy axis giả định từ repo cũ vào core mới.

## P02 — Sensor adapter và replay chuẩn

**Owner:** Luna xhigh cho serialization; Sol High cho sensor geometry nếu khác contract. **Depends:** P01.

**Create:** `src/neusymnav/sensors/{habitat_worker,client}.py`, `src/neusymnav/recording/{writer,replay}.py`, `tests/test_replay.py`, `tests/test_sensor_adapter.py`, `tests/fixtures/rgbd/`.

**Source:** New `simulation/{habitat_adapter,pose_provider}.py`, `recording/{replay,live_replay}.py`; 3DSG `exploration/{habitat_online,keyframe_store}.py`.

**Interface:** `PoseSource.capture() -> Observation` và `capture_navigation() -> Observation` theo modality spec; `ReplayWriter.append(obs: Observation) -> bool`, `ReplayWriter.close() -> dict` completeness certificate; `ReplayReader.frames() -> Iterator[Observation]` validation trước yield.

- [ ] Test roundtrip RGB/depth/K/pose byte-identical, corrupt checksum fail, thiếu frame tạo incomplete certificate, episode restart không trộn ID, secondary navigation-depth sensor có calibration riêng/modality=depth_only và không đi qua detector; floor datum nonzero chuyển trục đúng.
- [ ] Port recorder bounded/nonblocking; replay clock riêng, nguồn pose ghi `simulator_ground_truth`, không semantic fields/navmesh geometry trong observation cấp cho mapper.
- [ ] Chạy `python -m pytest tests/test_replay.py tests/test_sensor_adapter.py -q`. Khi Habitat sẵn, capture ngắn tối đa 30 s vào `runs/p02-smoke/`; không có Habitat thì chỉ chốt replay correctness và ghi native pending.

**Gate:** một input chuẩn dùng cho cả map/object, recorder lỗi không ghi completed giả; provenance đủ để tái chiếu.

## P03 — NavMap, frontier và chuyển động an toàn

**Owner:** Sol High; Luna xhigh port exports/fixtures theo contract. **Depends:** P02.

**Create:** `src/neusymnav/mapping/{occupancy,tiles}.py`, `src/neusymnav/navigation/{frontiers,planner,controller,safety}.py`, `tests/test_navmap.py`, `tests/test_navigation.py`, `configs/navigation.yaml`.

**Source:** New sparse occupancy/tiles; 3DSG `exploration/{planner,frontier,policy,controller,depth_safety}.py`; New controller guards để đối chiếu.

**Interface:** `NavMapper.update()`, `Navigator.step()`, `MotionGuard.filter()` theo spec; `Planner.plan_many(nav: NavSnapshot, start_xy: tuple[float,float], goals: tuple[tuple[int,int],...]) -> dict` trả mỗi goal path/cost/reason/revision. Robot geometry explicit, không hardcode radius từ demo cũ.

- [ ] Test unknown/invalid/no-return phân biệt; một vote/cell/frame; occupied thắng free; clearance và floor support cần đủ; tile eviction/reload không biến unknown thành free. Không seed free từ navmesh.
- [ ] Test multi-goal cost bằng single-goal A* trên fixtures; chặn diagonal corner cutting, cửa hẹp hơn footprint, goal unreachable; map origin/revision đổi làm path cũ vô hiệu.
- [ ] Port planner/controller qua adapter map chung; cấu hình downward navigation-depth sensor và floor_z_m/provenance theo spec, test known-ground rays phủ starting footprint và corridor đầu tiên; bootstrap dùng depth đo được rồi mới cho bước đầu. Fixture không đủ FOV/depth phải bootstrap_blocked. Giữ visited/failed viewpoint memory theo vị trí; command stale depth >300 ms dừng, không gọi graph worker trong control.
- [ ] Chạy `python -m pytest tests/test_navmap.py tests/test_navigation.py -q`; nếu có simulator, xác minh bootstrap thực trước rồi smoke frontier tối đa 60 s, lưu actual command/collision filter/map revisions. Không coi smoke đi được một đoạn là exploration đã tốt hơn.

**Gate:** robot chỉ đi đường footprint-safe đã quan sát; thiếu evidence giữ đứng yên với reason; parity tests cho thuật toán được port.

## P04 — Perception, canonical object memory và durable identity

**Owner:** Sol High; reviewer Sol High độc lập. **Depends:** P02; độc lập P03 sau contract khóa.

**Create:** `src/neusymnav/perception/{detector,yoloe,projector}.py`, `src/neusymnav/objects/{association,fusion,store,ledger,assets}.py`, `tests/test_projection.py`, `tests/test_object_identity.py`, `tests/test_ledger_recovery.py`, `configs/perception.yaml`.

**Source:** New perception/projection/association/store; giữ nguyên invariants rồi port tọa độ/import, ghi rõ khác biệt algorithm nếu có.

**Interface:** `Detector.infer()`, `Projector.project()`, `ObjectOwner.commit()` theo spec; `ObjectOwner.snapshot() -> ObjectSnapshot`, `ObjectOwner.resolve_id(object_id: str) -> str`.

- [ ] Test kết quả detector chậm dùng pose của frame chụp; hai instances sát nhau không collapse chỉ do cùng tên; ambiguity không ép match; cannot-link cùng frame được giữ.
- [ ] Test event trùng trước/sau restart chỉ một evidence; complete-empty batch vẫn có durable batch event/source refs, partial/saturated không tạo negative vote; transaction lỗi không publish trial association; merge alias không cycle, evidence cũ truy được và geometry bounds còn hợp lệ.
- [ ] Port geometry-first matching/Hungarian, bounded voxel cloud, lifecycle và SQLite WAL/assets; source namespace UUID mới theo episode. YOLOE11s là default đề xuất, tests CPU dùng deterministic fixture detector; không cần model để chốt contract.
- [ ] Chạy `python -m pytest tests/test_projection.py tests/test_object_identity.py tests/test_ledger_recovery.py -q`; reviewer kiểm association, rollback, migration schema và fixture oracle. Native detector smoke khi asset có, chưa training/tuning.

**Gate:** graph thật được cập nhật từ RGB-D/masks, export/reopen giữ identity; số test/độ chính xác repo cũ không được dùng thay evidence mới.

## P05 — Appearance từ OpenCLIP, không thêm identity owner

**Owner:** Luna xhigh adapter feature có contract đóng; Sol High review scoring thay đổi. **Depends:** P04.

**Create:** `src/neusymnav/perception/{appearance_worker,appearance_client}.py`, `src/neusymnav/objects/appearance.py`, `tests/test_appearance_contract.py`, `tests/test_appearance_association.py`, `configs/appearance.yaml`.

**Source:** Fusion `integration_v2/perception_feature_sessions.py`, reference `conceptgraph/slam/{mapping,utils}.py`. Giữ attribution/license và source pin; port subset feature/aggregation thay vì kéo greedy merger vào canonical owner.

**Interface:** `AppearanceEncoder.encode()` theo spec; `attach_features(observations: tuple[ObjectObservation,...], features: AppearanceBatch) -> tuple[ObjectObservation,...]` giữ đúng source/detection; feature worker timeout trả explicit unavailable.

- [ ] Test vector normalize, checkpoint/preprocessing space mismatch reject; mapping crop/mask về đúng detection; response sai source/geometry_hash bị reject dù detection ID trùng; duplicate frame không làm feature vote tăng; missing feature dùng geometry baseline có status.
- [ ] Nối appearance vào P04 mà vẫn giữ geometry/cannot-link/ambiguity gates. Pin aggregation theo unique accepted event; không đếm số tracking frame như evidence mới.
- [ ] Chạy `python -m pytest tests/test_appearance_contract.py tests/test_appearance_association.py -q`; smoke model hiện có tối đa 20 keyframes, ghi latency/CPU/VRAM nếu GPU được chọn.

**Gate:** profile `appearance=off|openclip` cùng canonical identity engine; chưa promote default theo unit test. P10 đánh giá lợi ích trên replay.

## P06 — Region DuDe và hierarchy thống nhất

**Owner:** Sol High; Luna xhigh native build plumbing; reviewer Sol High độc lập. **Depends:** P03/P04.

**Create:** `src/neusymnav/regions/{grid_adapter,dude_client,tracker}.py`, `src/neusymnav/hierarchy/{membership,places,composer}.py`, `native/dude/`, `tools/build_native.py`, `tests/test_regions.py`, `tests/test_membership.py`, `tests/test_hierarchy.py`, `tests/native/test_dude.py`.

**Source:** Fusion regions guard/tracker/client, `integration_v2/unified_scene_graph.py`; native DuDe source closure từ Rebuild và dependencies pinned; New places/hierarchy/relations.

**Interface:** `RegionBackend.update()`, `HierarchyComposer.compose()` theo spec; `MembershipResolver.resolve(objects: ObjectSnapshot, regions: RegionSnapshot) -> tuple` gồm object_id, region_id nullable, status, candidates và source revisions.

- [ ] Test NavSnapshot→RegionGrid giữ resolution/origin và -1 unknown/0 free/100 occupied; dùng narrow raster wire, không tạo z_floor/z_ceiling giả. Pin extended_unknown_boundary và parity fixture so với native cùng policy; kiểm unknown không bị morphology mở thành free. Thiếu observed-free support thì unavailable, không tự bật OctoMap extension.
- [ ] Test mở cửa/room split-merge giữ lineage, bad region update không làm già track; timeout/crash không publish region mới. Synthetic tests ghi rõ synthetic.
- [ ] Test footprint qua ranh phòng→ambiguous; outside→unassigned; rejected/timed-out region→stale geometry và unavailable membership mới; accepted region dùng pinned source NavSnapshot dù latest nav đã tiến, không starvation; alias merge retarget endpoint, không dangling; floor mismatch không join. Place edge có footprint validation riêng, không dùng structural adjacency làm đường chạy.
- [ ] Implement composer xuất object/place/room cùng canonical namespace và revision provenance; single-floor root không claim multi-floor. Chạy `python -m pytest tests/test_regions.py tests/test_membership.py tests/test_hierarchy.py -q`; build native rồi `python -m pytest tests/native/test_dude.py -q` bằng runtime đã khóa.

**Gate:** snapshot có canonical objects thật và room membership, không phải chỉ ghép hai viewer branch. Native unavailable phải ghi blocked P06 runtime, không thay fixture thành native pass.

## P07 — Scheduling hai lane, verification và failure recovery

**Owner:** Sol High; reviewer Sol High độc lập. **Depends:** P05/P06.

**Create:** `src/neusymnav/runtime/{scheduler,workers,health,coordinator}.py`, `src/neusymnav/verification/{ledger,best_views,negative}.py`, `tests/test_runtime_scheduling.py`, `tests/test_verification.py`, `tests/test_failure_recovery.py`, `configs/runtime-policy.yaml`.

**Source:** New runtime/verification/negative evidence; 3DSG keyframe policy/scheduler/store/bridge/provider.

**Interface:** `Pipeline.submit(obs: Observation) -> None`, `Pipeline.snapshot() -> HierarchySnapshot | None`, `Pipeline.close(timeout_s: float) -> dict`; `VerificationOwner.consume()` theo spec; close report có drained/pending/failed/replay_required/clean_shutdown.

- [ ] Test queue caps spec (1 in-flight, ≤2 pending, ≤1 protected, ≤32 MiB), chronological dispatch; commit event đúng một lần dù được consumer fast và historical nhìn thấy. Detector chạy một lần trên admitted frame; fast consumers chỉ dùng output còn TTL, object owner nhận ordered durable stream có historical status.
- [ ] Test stale source >750 ms không lọt fast semantic lane; depth >300 ms không chuyển động; host reboot/domain mismatch fail; worker restart cùng boot giữ clock domain nhưng phục hồi watermark; worker chậm/hỏng không block control hoặc publish partial hierarchy như complete.
- [ ] Test verification dùng committed views, tracking/refinement không tăng detection count; best views khác baseline; complete-empty batch vẫn đến verifier qua durable batch/source event; negative evidence bị chặn khi partial/failed/unknown, top-K saturated hoặc occluded; stale verifier response sau alias/revision bị reject.
- [ ] Port health/degradation, actual-config telemetry, graceful shutdown và replay pending; lỗi graph worker ghi recovery-required, không tự retry side effect không idempotent. Chạy `python -m pytest tests/test_runtime_scheduling.py tests/test_verification.py tests/test_failure_recovery.py -q` và short native smoke tối đa 60 s nếu đủ dependencies.

**Gate:** fault injection chứng minh freshness/safety; restart phục hồi evidence được accept; publication mismatch=0; bounded memory/queue có metrics chứ không chỉ constants.

## P08 — UI và observability

**Owner:** Luna xhigh; main review. **Depends:** P06; tích hợp runtime cần P07.

**Create:** `src/neusymnav/visualization/{desktop,publisher,hierarchy_view}.py`, `tests/test_display_snapshot.py`, `tests/test_ui_offscreen.py`, `docs/running.md`.

**Source:** PyQt desktop/live dashboard của 3DSG; presentation logic hierarchy/best-view New. Chỉ một UI framework/process trong core.

**Interface:** `DisplayPublisher.publish(snapshot: HierarchySnapshot, metrics: dict) -> None`; publish atomic, UI read-only; metrics chứa capture/processed/published frame IDs và source age riêng publication age, dropped/replaced counts, actual profile.

- [ ] Test UI đọc một revision nhất quán, không trộn map/graph mà thiếu source tags; stale room/unknown parent nhìn rõ, alias selection resolve được, missing image không crash.
- [ ] Implement RGB/map/hierarchy + selected object/best-view; hiển thị status candidate/active/verified như ba khái niệm khác nhau. Pause/Stop gửi command có ACK, không ghi trực tiếp graph.
- [ ] Chạy `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_display_snapshot.py tests/test_ui_offscreen.py -q`; với display thật chụp UI đang chạy và kiểm RGB/map/graph/labels không trống do wiring.

**Gate:** renderer không chạy trong control; headless vẫn đủ telemetry/export. Offscreen test không thay native UI screenshot.

## P09 — Entry point, packaging và portability

**Owner:** Luna xhigh; main review, Sol khi IPC/dependency contract đổi. **Depends:** P07/P08.

**Create:** `src/neusymnav/cli.py`, `configs/{baseline,appearance,geometry-only}.yaml`, `tools/verify_package.py`, `tests/test_cli.py`, `tests/test_package_isolation.py`; update preflight/notices/provenance/runtime config/running guide.

**Interface:** `python -m neusymnav.cli preflight --config <path>`; `run --config <path> --duration-s N --out <path>`; `replay --input <path> --config <path> --out <path>`; `evaluate --suite <path> --out <path>`. Config chỉ asset/runtime paths explicit; relative paths resolve theo config/package, không cwd ngẫu nhiên.

- [ ] Tạo launcher/replay/export; config mặc định frontier-only, simulator pose, detector baseline và actual degradation logging. Appearance profile separate cho đến P10 decision.
- [ ] Port dependency closure đã pin vào `vendor/`/`native/`; build có source/hash/license record. Không mang hai `standalone_sg` lên cùng sys.path, không symlink source tới siblings. Models/scenes external phải declared và checksum checked.
- [ ] Chạy `python -m pytest tests/test_cli.py tests/test_package_isolation.py -q` và `python tools/verify_package.py --source-only`. Isolation test copy package sang temporary dir, unset source PYTHONPATH, chạy import/fixture replay; runtime import audit kiểm không đọc source từ folder cũ, kể cả absolute path hardcode.

**Gate:** đường chạy mới dùng source trong NeuSymNav, thiếu tài sản báo actionable error; fixture replay chạy được từ cwd khác. Native portability chỉ claim trên OS/ABI đã đo.

## P10 — Nghiệm thu tích hợp và chọn profile

**Owner:** Sol High cho protocol/GT/review; Luna xhigh dựng reports. **Depends:** P09.

**Create:** `src/neusymnav/evaluation/{protocol,metrics,gt_isolation}.py`, `configs/evaluation/suite-v1.json`, `tests/test_evaluation_protocol.py`, `tests/test_end_to_end.py`, `tests/test_gt_isolation.py`, `docs/acceptance-report.md`; results tại `runs/acceptance/<run-id>/`.

**Interface:** evaluator nhận runtime exports và offline GT tách biệt; suite pin scene/seed/input hash/model/config/taxonomy/actual resolution. Report per-run gồm outcome, support, latency/drop/freshness, memory, graph/region quality và limitations.

- [ ] Viết test failed/timeout/missing vẫn nằm denominator; exact-label score giữ riêng canonical score; GT không nhập runtime; same RGB-D/pose mà semantic GT thay đổi không thay runtime graph/nav outputs trên deterministic replay.
- [ ] Chạy `python -m pytest tests/test_evaluation_protocol.py tests/test_end_to_end.py tests/test_gt_isolation.py -q` rồi toàn bộ CPU suite `python -m pytest tests -q -m 'not native'` (đăng ký marker từ P00). Native suite chạy riêng; tổng kết cả skipped với lý do.
- [ ] Freeze suite trước GPU: tối đa **2 scene sẵn có × 2 seed × 300 s** cho core profile được chọn. Không đủ 2 scene thì báo pilot/incomplete, không tải thêm tự động. Smoke P02–P07 ngắn phải qua trước; một job mỗi lần; preflight stop khi không đủ RAM/disk. Không tự rerun nhiều lần để chọn run đẹp.
- [ ] Replay cùng inputs với appearance off/on và legacy New baseline adapter read-only (đầu ra chuẩn hóa trong NeuSymNav). Nếu có compatible legacy 3DSG artifacts, thêm đối chứng CG; nếu không có thì báo thiếu, không chế tạo comparator. Native trajectories khác nhau không dùng để kết luận detector/association thắng trực tiếp.
- [ ] Ghi capture-to-result/commit p50/p95, admitted/accepted/stale/replaced fractions, control depth age và stop reasons, actual input resolution/health state, RSS/VRAM peak, raw/export completeness, explored free area, distance, no-progress intervals, object ID switches/merges và room membership assigned/ambiguous coverage. Label/geometry/identity metrics tách riêng, report số GT objects/scenes có support.
- [ ] Fault injection bounded: delay graph 2 s, kill/restart graph worker sau accepted keyframe, corrupt replay payload, alias trong lúc UI đang chọn object. Dùng fixtures/short run riêng, không trộn vào performance samples. Reviewer Sol High kiểm source + evidence trước đóng P10.

### Gate và verdict

**Hard correctness:** tất cả tests bắt buộc pass; source/clock mismatches bị reject; graph endpoints không dangling; accepted events không double-count/mất sau restart; không command vượt freshness gate; không GT leakage; shutdown không còn worker; source gốc hashes không đổi. Sai bất kỳ điểm nào → fail, sửa trước campaign tiếp.

**Runtime boundedness:** queue/byte caps trong spec giữ suốt run; không OOM/unhandled worker failure. Theo máy đích đã audit, đề xuất cap process-tree RSS 10 GiB và VRAM 5 GiB cho laptop RAM16/VRAM6; P00 phải xác nhận phần cứng. Cap không phù hợp máy thực thì báo trước khi chạy, không âm thầm thay. Record disk budget và stop/incomplete policy; không xóa evidence để qua cap.

**Useful core demonstration:** mỗi run phải có object commit thật từ detector và frontier translation >1 m; toàn suite có ít nhất một room geometry accepted và một object membership assigned có evidence. Đây là gate minh họa tối thiểu, không phải accuracy/coverage benchmark. Không đạt → `insufficient demonstration`, chẩn đoán perception/exploration/region, không lấy synthetic thay thế. P10 chưa runtime-validated nếu gate này chưa đạt.

**Appearance promotion:** default off cho tới khi cùng replay/labeled support cho thấy IDF1 không giảm, false merge rate không tăng và memory cap giữ; report support và per-scene result. Nếu thiếu GT identity thì chỉ chứng minh wiring/runtime, giữ optional, không tuyên bố accuracy gain. Được chốt core với appearance optional khi mọi core gate đạt; báo feature implemented nhưng quality chưa xác nhận.

Không đặt kỳ vọng FPS/F1 theo README thành số đo mới. Công bố latency/control cadence thực tế và tình trạng continuity; không gọi realtime hoặc tối ưu khi chưa có tiêu chí và evidence tương ứng. Các profile degraded640→480 phải báo adaptive, không lấy kết quả đó chứng nhận fixed640. Nếu cần mục tiêu hiệu năng/chất lượng cao hơn, ghi proposal riêng sau baseline.

**Gate cuối:** acceptance report có verdict từng gate, commands/exits/artifacts, model+source hashes, profile promoted/optional và giới hạn. Core hoàn tất chỉ khi correctness, boundedness, useful demonstration và packaging cùng đạt; danh sách extension vẫn chưa triển khai.

## Dependency và parallel execution

```text
P00 → P01 → P02 ┬→ P03 ─────────┐
               └→ P04 → P05 ──┼→ P07 ─┐
                   P03+P04→P06┘       ├→ P09 → P10
                             P06→P08 ─┘
```

- Sau P01: P02 serialization và sensor adapter có thể chia writer theo file; main giữ contracts.
- Sau P02: P03 navigation và P04 object core song song, không cùng GPU smoke. Main kiểm seam NavSnapshot/ObjectSnapshot.
- Sau P04: P05 appearance độc lập P06 nếu P03 đã xong; P08 chỉ bắt đầu khi hierarchy contract P06 khóa, dùng fixture trước P07.
- Native build P06 và docs/UI có thể song song trong RAM; không build nặng khi đo performance. P07 integration, P09 isolation và P10 campaigns có dependency, không chạy trước chỉ để tận dụng slot.

## Bàn giao và định nghĩa hoàn thành

Mỗi task có implementation, correctness, runtime evidence riêng trong status. Main bàn giao folder mới có entrypoint, configs, lock/env matrix, notices/source hashes, tests, hướng dẫn chạy, replay artifact manifest và acceptance report. Không cần sao chép model/dataset lớn vào folder để gọi là self-contained source.

Task scope không rõ hoặc source thay đổi sau audit: cập nhật provenance và kiểm tra contract impact trước port. Quyết định nhỏ theo spec do main tự xử lý; đổi canonical axis, identity owner, GT boundary, default policy hoặc mở extensions cần đưa người dùng xem lựa chọn cụ thể. Không gộp lỗi quality với lỗi implementation và không đánh dấu toàn bộ hoàn tất chỉ vì hết checklist code.
