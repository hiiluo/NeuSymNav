# Kế hoạch triển khai ReasoningGraph M0–M8

Trạng thái thực thi hiện hành được ghi ở [checkpoint M5 và M7](../implementation-status.md#reasoninggraph-tích-lũy-quan-hệ-m5-và-paper-shadow-m7--2026-11-27). [Audit](current-system-audit.md), [kiến trúc đích](target-architecture.md), [paper-to-code](technical-analysis.md), [contracts](shared-graph-and-semantic-contracts.md), [thiết kế](integration-design.md), [đánh giá](evaluation-plan.md), [rủi ro](integration-risk-analysis.md), [roadmap module tương lai](future-module-integration-roadmap.md).

Tất cả đường dẫn ở phần **Tạo** là file dự kiến. Những đường dẫn ở **Sửa** trỏ vào code hiện tại hoặc file được milestone trước tạo. Main quản lý contracts, pin configs và publication. Mỗi file một writer. M0 → HNA → M1, sau đó mở M2, M3 và M4 khi khóa evidence/worker interfaces. M3 có thể phát triển fixtures song song M2, và cần encoder full-frame khi integration. M4 → M5. M2 + M3 + M5 → M6 → M7 → M8. Sidecar và entry point cờ tắt được tích hợp tuần tự. Chạy CPU fixtures/replay có outputs tách biệt, chỉ một GPU workload tại một thời điểm. M1, M5 và M7 cần review invariant theo snapshot và mức rủi ro. Ghi commands, exit codes, input/config/build hashes, artifacts và điều chưa chứng minh trong status. Tách implemented, correctness-verified, runtime-validated.

## M0 — Kiểm kê và đóng băng baseline

**Phụ thuộc và nguồn.** Audit hiện hành, Hydra §III–VI và ReasoningGraph §V. Entry points `tools/run_hydra_map_demo.sh`, `tools/objectnav/run_paper_episodes.py`, `tools/objectnav/score_trajectories.py`.

**Tạo:** `tools/reasoninggraph/freeze_baseline.py`, `tests/test_rg_baseline_manifest.py`. **Sửa:** `docs/implementation-status.md` với checkpoint triển khai và evidence.

- [x] `freeze_baseline(config, manifest, source_root, output)` ghi lock input, code và artifacts. Lưu bản sao nội dung source của checkpoint.
- [x] Đóng băng Paper B0 v2, DEV60/Test180 và native export/replay. Ghi baseline CPU, giới hạn VRAM và sai khác theo profile. Việc chọn C ở M7 có gate pin riêng.
- [x] Kiểm schema/hashing, thiếu pin, thay đổi khi resume, preflight hai split và smoke Paper B0 v2 với scorer schema 3. Clean rebuild từ checkout chưa được chứng minh.

**Cấu hình/gate.** Manifest dùng `--policy-config configs/objectnav/paper-b0-v2.json` và protocol đã pin. Smoke giới hạn theo lock, không chạy song song. Pass khi 60 UID đúng split, config pins khớp và replay đối chứng có artifact cùng comparison script. Baseline history chỉ là prior evidence. Rủi ro dirty source hoặc thiếu proof build → dùng binary pin cho comparison, ghi blocker source-equivalence. Rollback bằng bỏ manifest thử nghiệm, runner hiện có vẫn dùng.

## HNA — Native Hydra Attribute and Query API Enhancement

Gate bắt buộc giữa M0 và M1. [Capability audit theo pinned commits](native-hydra-attribute-audit.md) đã đọc schema, bindings và hai native exports. [Kế hoạch HNA-01–04](../superpowers/plans/2026-11-26-native-hydra-attribute-query.md) mở rộng `HydraSceneGraphQuery`, pin native graph/mesh revision và thêm truy xuất theo nhu cầu. HNA hoàn tất khi có evidence về compatibility, exact-token access, room label parity, bounded IPC và profile mode được dùng. Fixture pass không chứng minh live capability. HNA đã triển khai. Native gate đạt ở chế độ saved export và CPU selected-prefix replay. [Habitat live 00806](../implementation-status.md#nghiệm-thu-hna-trên-habitat-live--2026-11-26) đã xác nhận chức năng HNA. Ngưỡng p95 live và chứng nhận P10 còn mở. M1 evidence/lineage có gate riêng. [Checkpoint hiện hành](../implementation-status.md#native-hydra-attribute-and-query-api-enhancement--triển-khai-2026-11-26).

## M1 — Shared IDs, evidence và graph lifecycle

**Tiến độ.** Evidence producer opt-in đã ghi sidecar từ Habitat live. Lifecycle đọc qua worker và journal đã được kiểm chứng trên replay và live với room stability. Canonical owner chỉ publish các bước có đủ event và khớp native projection. Hai đường merge có fixture native. Còn mở độ phủ nhãn trên hold-out, merge trong replay/live và truyền alias tới consumers. [Checkpoint lineage](../implementation-status.md#reasoninggraph-native-lineage-qua-worker-và-kiểm-chứng-m3-m7-m8--2026-11-27).

**Phụ thuộc và nguồn.** HNA gate và M0 pins, [ReasoningGraph §IV-A/B](https://arxiv.org/html/2602.02456v1), Alg. 2/4, local `contracts/{observations,hydra_evidence,hydra_graph}.py`, `HydraSession`, `HydraGraphRuntime`, `HydraSceneGraphQuery`.

**Tạo:** `src/neusymnav/contracts/reasoninggraph.py`, `src/neusymnav/reasoninggraph/{__init__,evidence,lifecycle,store}.py`, `configs/reasoninggraph/off.yaml`, `tests/test_rg_evidence.py`, `tests/test_rg_lifecycle.py`. **Sửa:** `backends/hydra/runtime.py` (trong `src/neusymnav/`), `backends/hydra/query.py` qua index argument hiện có, chỉ mở rộng `backends/hydra/worker.py` nếu thiếu native lineage và xác định được hook có proof.

- [ ] Implement scope, `GraphReadToken`, `GraphLifecycleDelta`, `NativeLink`, `FeatureSpec/Ref`. Ghi evidence sau detector đã validate và join đúng Hydra accepted prefix. Snapshot status phân biệt accepted frame và confirmed object.
- [ ] `link_evidence(evidence, projection, token)` kiểm class-version, 3D overlap, same frame và reject ambiguity. Pin labels/thresholds. Với neighboring same-label có competing support ghi ambiguous. Đo matched coverage và false link trên annotated replay. Giữ per-instance mapping ngoài class raster.
- [ ] `apply_delta(previous, native_snapshot, native_lineage)` chuẩn hóa lifecycle. Strict ownership, idempotent transaction và alias resolution. Khi thiếu lifetime proof, chỉ hỗ trợ exact-revision queries. M5 incremental và M7 goal advisory chờ proof, hoặc milestone được báo blocked ở các capability đó.
- [ ] `publish_read_view(native_pin, sidecar_manifest)` expose immutable generation. Snapshot unavailable khi thiếu prefix, output trễ, epoch khác hoặc calibration/clock mismatch. Default off không khởi động worker hay đổi publication cũ.

**Cấu hình/gate.** `enabled=false`, `link_policy_version`, queue+evidence max items/bytes/age, revision and generation policy. Unit duplicate, reordered/late results, alias cycle/reuse, same class adjacency, delete/orphan, corrupt manifest, incomplete prefix, cap/tombstone, restart/resume. Integration replay với Hydra graph exports và journal, verify matched endpoint support. Gating trước direct fusion: test split/merge/delete trên fixture, native lifecycle proof hoặc explicit revision-only degraded mode. M5 cumulative native không pass bằng fixture. Rollback tắt adapter và đọc native graph.

## M2 — Object semantic features

**Phụ thuộc và nguồn.** M1, paper Eq. 3–4/Alg. 1–2, prototype source extraction/aggregation trong [traceability](technical-analysis.md). Local `appearance_worker.py`, `appearance_client.py`, `Observation`.

**Tạo:** `src/neusymnav/reasoninggraph/{semantic_encoder,object_features}.py`, `configs/reasoninggraph/{faithful,lightweight}.yaml`, `tests/test_rg_object_features.py`. **Sửa:** `src/neusymnav/perception/{appearance_client,appearance_worker}.py` nếu mở rộng protocol image/text/full-frame tương thích, `reasoninggraph/store.py`.

- [ ] `encode_object(evidence, recipe)` trả bbox/mask/text vectors, compatible spec và validity. Cache prompt theo label và template. Chốt crop preprocessing theo profile. Pin source parity riêng với paper recipe. Paper chưa công bố exact fusion weights. Source config ghim 0,9/0,1/0 theo text/mask/bbox, các arm đều hoặc đổi weights phải ghi adaptation. Kiểm normalized versus raw output oracle.
- [ ] `ObjectFeatureStore.add(canonical_id, evidence_id, channels, recipe)` áp Eq. 3/4 với chosen direct-node adaptation. Log missing channel, reject invalid/incompatible events. Match event tới resolved ID khi publish. Tách normalized query view và accumulator.
- [ ] `rank_objects(view, query_vector, top_k, room_scope=None)` trả similarity, ranked IDs và support. Deterministic tie order. Không tái dùng score làm association hoặc probability.

**Cấu hình/gate.** Weights riêng, model/dim/spec, prompt templates, preprocessing/crop, device và max rank. Unit RGB/mask/text parity, dimension mismatch, zero/NaN, duplicate/order/alias, no-evidence. Integration same sealed RGB-D inputs từ M0 với frozen links, test raw vs fusion và hand-computed cosine. Native model smoke khi checkpoint đã có, xác minh paired image/text và p95. Risk closed feature space/chênh detection coverage → giữ baseline, tắt object features, không đổi existing appearance model.

## M3 — Room semantic features

**Tiến độ.** Replay 00806 đối chiếu và mã hóa CLIP đủ 18 frame. Bảy frame có chuỗi agent → place → room khớp timestamp và pose, nhưng chuỗi này được Hydra tạo theo place gần nhất. Chưa có gate containment/floor cho các frame đã ghi.

**Phụ thuộc và nguồn.** M1, dùng API encoder M2 sau khi khóa shape, paper Alg. 3, local `contracts/room_semantics.py`, native room projections và room views. Đối chiếu cách upstream gán pose/cluster trong [traceability](technical-analysis.md).

**Tạo:** `src/neusymnav/reasoninggraph/room_features.py`, `tests/test_rg_room_features.py`. **Sửa:** `src/neusymnav/reasoninggraph/store.py`, hai profile M2.

- [ ] `observe_room_view(source, full_frame_feature)` lưu bounded source pose và vectors. Room assignment dùng membership hiện hành, gate floor/containment, pending queue cho room xuất hiện muộn.
- [ ] `recluster(changed_room_ids, membership_revision)` xử lý split, merge, reassignment, corrected pose và cap. Deterministic fit và normalize centroids, publish đủ metadata/trạng thái.
- [ ] `rank_rooms(view, text_vec)` dùng mean centroid×prompt theo paper profile hoặc max single-query theo arm source-config-inspired và ghi support. Cache theo token. Đánh giá cùng ảnh trước/sau room edit và regular room label profile.

**Cấu hình/gate.** K=10, iters≤100 theo source config. K=3 là gợi ý lightweight pilot. Pin seed, scoring mode, min_support, max keyframes/bytes và nearest-place bound. Unit late room, boundary, ambiguous floor, eviction, split/merge/rebase, deterministic clustering. Integration fixture revision + saved Hydra room export. Correct reassignment, pending/drop reason, bounded memory, evaluator có per-room queries. Rủi ro reassign thiếu pose proof → quarantine, rollback tắt room semantic features.

## M4 — Relationship visual encoder

**Tiến độ.** Nhánh ảnh riêng đã chạy Qwen3-VL-2B CPU trên bốn cặp có đảo hướng từ replay 00806. Câu hỏi marker trung tính đúng 6/8 câu và 2/4 cặp ở cả hai chiều. Phép đo giới hạn ở bên trái trong mặt phẳng ảnh. Split-token parity và chất lượng ngoài pilot vẫn mở.

**Phụ thuộc và nguồn.** M1, paper Alg. 1 và Fig. 4, semantic_inference_ros + DeepSeek-VL2 source paths/pins trong [traceability](technical-analysis.md).

**Tạo:** `src/neusymnav/reasoninggraph/{pair_selection,relation_encoder}.py`, `tests/test_rg_relation_encoder.py`, golden fixture nhỏ trong `tests/fixtures/reasoninggraph/`. **Sửa:** hai profile M2.

- [ ] `select_pairs(evidence_frame, budget, task_scope=None)` deterministic co-visibility, pair direction, valid depth and spatial gate theo profile. So all pairs cap với pruned arms. Log rejected reasons. Tạo union crop, mapping hai marker order, clamp và hash.
- [ ] `RelationEncoder.encode(pair_crop, spec, deadline)` trả visual token payload, layout và checksum. Pin cut point, dtype, token metadata và decoder. Encode/decode roundtrip từ cùng raw crop, so whole-image baseline và split encoder reference trong tolerance đã pin. Lặp same-label, reversed roles, edge crops và multi-tile.
- [ ] Giới hạn payload trước decode, pin allowlist types, no deserialization executable object. Queue budget, deadline, timeout, circuit breaker. Đo single/batch và VRAM mỗi phase riêng biệt.

**Cấu hình/gate.** Keyframe cadence, max pairs and union bbox area, same-class policy, cap bytes, batch/precision, remote endpoint profile và deadline. Unit deterministic order/quota, RGB preprocess, shapes/layout, decoder mismatch, timeout. Integration mock transport và real paired encoder/decoder parity gate trước khi gọi faithful. Nếu assets/compute/service thiếu, ship fixture contract, native milestone blocked. Tắt relations hoặc dùng explicitly separate image-evaluation arm. Không đổi VLM room/STOP backend.

## M5 — Relationship-aware graph

**Tiến độ.** Store standalone đã kiểm thử trong một revision. Bộ tích lũy offline qua các view M1 đã kiểm merge/delete, dedup, quota theo cạnh và restore có xác thực lịch sử. Consumer live và provenance encoder/decoder vẫn mở.

**Phụ thuộc và nguồn.** M1 + M4, paper Eq. 5/Alg. 4, native merger/serializer upstream trong [traceability](technical-analysis.md).

**Tạo:** `src/neusymnav/reasoninggraph/relation_store.py`, `tests/test_rg_relation_store.py`. **Sửa:** `reasoninggraph/{store,lifecycle}.py`, contracts file M1 nếu thêm `RelFeatureSpec` sau proof của M4.

- [ ] `apply_pair(event, token)` resolve both endpoint IDs, reject missing/ambiguous/same/invalid. Add or update compatible layout mean/count. Keep original direction và provenance kể cả hai cạnh đối ứng. Bound edges và per-layout pools.
- [ ] `on_lifecycle(delta)` retarget/merge defensibly, drop self/orphan, tombstone deletion, invalidate jobs sau epoch/revision change. Replay đủ khi sample loss khiến aggregate cần rebuild. Không coi optimization là observation mới.
- [ ] `write_manifest/open_manifest` atomic commit native pin + edge records, validate schema, hashes, all referenced edges, endpoint revisions, duplicates và quota. UI và query dùng immutable published view.

**Cấu hình/gate.** max edges/global bytes/refs per edge, event retention, dtype and schema. Unit Eq. 5 oracle, reversed endpoints, alias collision, duplicate, split-layout rejection, stale concurrent completion, corrupt blob, partial write/restart. Integration replay relation graph trước/sau merge-delete-loop correction và deserialize. Endpoint integrity 100%, atomic mismatch bằng 0, evict/rebuild explicit. Nếu lifecycle chưa có proof native, chỉ xuất revision-local standalone, cumulative native chưa đạt. Rollback bỏ sidecar manifest và giữ Spark-DSG source untouched.

## M6 — Semantic query và standalone reasoning

**Tiến độ.** Query và reasoner chạy fixture theo exact revision. Reasoner chỉ nhận dạng yêu cầu tìm một danh mục, xếp hạng từ view và từ chối tác vụ quan hệ. Transport async, evaluator và grounding quan hệ còn mở.

**Phụ thuộc và nguồn.** M2+M3+M5, paper §IV-C/Fig. 3, upstream task parsing, retrieval, VLM và decisor scripts theo [traceability](technical-analysis.md). Local query và VLM worker transport.

**Tạo:** `src/neusymnav/reasoninggraph/{query,reasoner}.py`, `tools/reasoninggraph/evaluate_tasks.py`, `tests/test_rg_query.py`, `tests/test_rg_reasoner.py`. **Sửa:** `reasoninggraph/store.py` để expose tokenized read view khi cần.

- [ ] Implement object/room/relationship query, bounded `retrieve_subgraph` theo contracts. Supply coverage, scores, evidence pages và status.
- [ ] `TaskReasoner.propose(view, instruction, budget)` chạy async schema-checked stages, pin prompt/model IDs và allowed IDs, trả grounded proposals, evidence/insufficient-evidence với per-step trace. Disable actions và path planning ở standalone evaluator.
- [ ] Unit test order, malformed/foreign outputs, source mismatch, prompt schema, retry idempotency, abstain khi relation missing/stale, LLM timeout/degradation, deterministic mocks. Integration trên sealed snapshot + small labeled tasks, hand-crafted reference scenarios và encoder parity đã qua M4.

**Cấu hình/gate.** top-k, max nodes/edges, per-task call/token/latency budget, decoder checkpoint, parsing/decision model. Pass fixture positive, negative, impossible và ambiguous, output foreign-ID bằng 0, log task predictions/missing refs. Model quality report riêng sau repeat fixed protocol. Rủi ro model drift/cost → disable external reasoning. Query vector và saved graph vẫn hoạt động.

## M7 — End-to-end, visualization và consumer hiện có

**Tiến độ.** Paper có bounded shadow capture dùng cùng detector và native replay fixed rig. Cặp off/shadow B0 cùng lock đã đối chiếu 28 action và ba frame qua Hydra. Live native shadow, safety trace đầy đủ, CID→canonical và advise vẫn mở.

**Phụ thuộc và nguồn.** M6, baselines M0, local Hydra coordinator, `HydraGraphRuntime.offer`, `PaperRunner.run_episode`, `PaperB0Policy._perceive`, `PaperNav.go_to_cells`, `visualization/hydra_display.py`. Paper §V cho fidelity comparison, [integration design](integration-design.md) cho adoption.

**Tạo:** `src/neusymnav/reasoninggraph/advisor.py`, `tests/test_rg_runtime_wiring.py`, `tests/test_rg_paper_parity.py`. **Sửa:** `src/neusymnav/runtime/coordinator.py`, `tools/objectnav/run_paper_episodes.py`, `src/neusymnav/objectnav/paper/{runner,b0}.py` cùng viewer `visualization/hydra_display.py` theo từng arm. Móc reuse batch chỉ khi feature bật.

- [ ] Hydra demo nhận optional Semantic Worker, query viewer theo token. Hỗ trợ next/prev evidence và status. UI cứ render graph native nếu sidecar lỗi.
- [ ] Paper shadow tap dùng cùng `Observation`/`DetectionBatch`, không chạy detector thứ hai. Đầu tiên thử subset với camera fixed rig trong replay và đo bỏ frame. Paper `look_up/down` thay `calibration_id`, trong khi native worker khóa sensor/calibration. Muốn full coverage, pilot camera-as-body adapter với extrinsic cố định (ví dụ identity), `world_T_body=T_world_camera` đúng theo convention Hydra. Lưu calibration nguồn động riêng, verify bằng fixture analytic/reprojection ở các tilt, quan sát vị trí places/room, pose optimization và gắn geometry. Không dùng virtual body pose bên control. Nếu parity hoặc mapping topology không đủ, giữ replay fixed-rig scope hoặc ghi blocker cho native hook rõ ràng. Không ép source metadata sai để qua gate.
- [ ] Join CID→canonical qua evidence link+geometry, require unique match, generation/alias validation. Mode adviser chỉ đọc cached hint có TTL. Giữ B0 làm đối chứng. Chọn consumer và các cổng candidate cho policy mới trước khi thử advice. PaperNav fallback waypoint và guard lockstep khác nhau. Kiểm direct path clearance/current depth tại output boundary cho quyết định có advice. Nếu thiếu cổng phù hợp và cần thêm admission guard, thêm chỉ trong experimental arm với đối chứng cùng guard, hoặc giữ shadow. Không sửa mặc định PaperNav. Ghi coverage và actual consumption khi đã có consumer.
- [ ] `off|shadow|advise` explicit, mặc định off. Fault injection: OOM/crash, queue saturation, worker outage, stale replies, reset, missing depth, turn/tilt. Unit test no action escape, off branch byte-equivalence và inbox bounded. Native smoke dưới khóa một workload, pin device/timeouts, đủ route/verification tests trước DEV60.

**Cấu hình/gate.** mode, graph/worker profile and deadline/TTL, optional visualization. 100% off parity trên unit replay và paired native smoke với deterministic settings. Action, STOP, inputs/pins và safety reasons khớp. Shadow thêm overhead được đo và không thay decision. Advise chỉ mở khi có actual consumer exposure, hook fallback trace và no bypass. Giữ planner, verifier và evaluator hiện hành. Rủi ro lockstep timing khác → round-trip replay để tách scheduling, rollback cờ off.

## M8 — Đánh giá và ablation

**Phụ thuộc và nguồn.** M7 hoặc subset offline tương ứng M2–M6, paper §V/Tab. I–III, [traceability](technical-analysis.md), [evaluation protocol](evaluation-plan.md), `src/neusymnav/evaluation/{objectnav_metrics,tracking_quality}.py`.

**Tạo:** `tools/reasoninggraph/{score_semantics,compare_arms}.py`, `configs/reasoninggraph/evaluation-v1.yaml`, `tests/test_rg_eval.py`. **Sửa:** `docs/implementation-status.md` để link run artifacts, giữ schema 3 scorer.

- [ ] Khóa denominators, category text prompts, object/room assignment oracle, relational labeled dataset và splits, budgets, remote profile. Chạy semantic B0–B7 trên cùng frozen frame/graph prefix khi so representation. Ghi arm nào dùng model khác và marked coverage.
- [ ] Chạy DEV60/tập quan hệ nhỏ trước, TEST180 chỉ sau khi chốt params. Pairs cùng UID/seed/action cap/manifest, summarize paired differences/CI, false STOP/timeouts/skips/tài nguyên. Standalone và navigation ghi artifacts khác loại để giữ denominator.
- [ ] Unit test evaluator metrics bằng fixture tay, integration manifest mismatch/GT leakage guard, timestamp and repeated inference counters, paired scorer outputs. Báo exact provenance, token/latency/cost và limitations.

**Cấu hình/gate.** Eval protocol hashes, split/reference choices, bootstrap seed, test criteria từ [protocol](evaluation-plan.md). Pass coverage, integrity, parity và budgets theo M0 chốt trước test. Kết quả SR/SPL có CI và actual exposure, không đòi tăng SR nếu test chỉ đo graph. Không promote default khi fail hoặc chất lượng chưa chứng minh. Rollback mặc định off và giữ artifacts phân tích.

## Bàn giao mỗi milestone

Lưu `runs/reasoninggraph/<run-id>/` với `inputs.json`, `commands.log`, exits, `profile.json`, `summary.json`, per-UID/keyframe/evidence traces và graph/feature manifest tương ứng. Nêu gate pass/fail/blocked và ngày/host. Người triển khai cần kiểm paths/symbols lại với pinned source trước khi sửa và chỉ dùng quyền được giao cho milestone đó. Link checkpoint trong [trạng thái](../implementation-status.md).
