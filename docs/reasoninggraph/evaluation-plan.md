# Giao thức đánh giá ReasoningGraph

## Baseline và reproduction

Có hai đối chứng khác mục đích. **Graph baseline** dùng demo Hydra, frozen journal prefix và native export. **Navigation baseline B0** dùng paper B0 v2 đã pin. Với consumer C, dùng thêm C cùng config với advisory off và shadow để tách ảnh hưởng của graph overhead. [Audit](current-system-audit.md), [roadmap M0/M8](implementation-plan.md).

- Freeze dataset/split/scenes/navmesh, UID order, per-episode seeds, RGB-D geometry, detector checkpoint/config, vocabulary, association, action space, step budget, policy/planner/scorer và host/runtime hashes. Đổi bắt buộc một yếu tố thì tạo arm matched và ghi khác biệt, không trộn vào đóng góp semantic.
- Disable path là parity gate. So same captured frames, action/STOP sequence, poses trong tolerance xác định trước, score, safety reasons và fallback. Shadow vẫn phát trace same actions. Đo runtime separately. Khi timing có nondeterminism, lặp baseline và tách offline deterministic replay.
- Preflight hiện tại với B0 v2 đọc DEV60, 6 scene, cap 500. Chưa đo lại native. Lịch sử B0 v2 trên DEV60 đạt SR 37/60, SPL 0,2376, SoftSPL 0,2892 và DTG 1,5478 m. C full trước tinh gọn đạt SR 30/60 và SPL 0,1943. Đây là mốc để đối chiếu snapshot khi M0 chạy lại. [B0 v2 đã lưu](../../runs/objectnav/paper-shared-upgrade/dev60/b0/schema3-summary.json), [C full đã lưu](../../runs/objectnav/paper-c-last-mile/dev60-full/schema3-summary.json).
- Sử dụng DEV60 cho tuning/grouped error analysis, giữ TEST180 untouched đến khi freeze settings. Report mẫu theo UID/scene/category, incomplete/timeouts/invalid và split leakage gate. Artifact chứa lockfile, exact command và exit code, hardware, schema, timings, model refs, trace và scorer outputs.

## Định nghĩa paper và phép đo nội bộ

ReasoningGraph §V-B báo top-k **category classification** theo cosine của mỗi object feature với text labels, Acc@k và AUC của top-k curve. Datasets Replica và HM3DSem dùng foreground comparison có filtering background. Số objects phụ thuộc detection và clustering. §V-C dùng 5 lượt trên mỗi task, báo SR theo thu hồi object/subtask đúng và FP counts, sau đó lặp 100 lần mỗi subtask T1–T4 để đánh giá accuracy và macro-F1. Table III báo pooled 79,30% accuracy, 79,11% macro-F1. §V-D là timing theo component ở Jetson Orin AGX, không phải latency đã đo trên RTX Laptop. [ReasoningGraph §V và bảng I–IV](https://arxiv.org/html/2602.02456v1), [source evaluator và giới hạn](technical-analysis.md).

| Nhóm | Đơn vị, định nghĩa và báo cáo |
| --- | --- |
| Object category Acc@k / AUC | Acc@k = fraction object matched có label đúng trong k nhãn đầu. Báo number matched/eligible, coverage và class frequency. Nếu chưa pin cách lấy AUC trong official code thì khóa lưới k và normalized trapezoidal convention cho metric nội bộ, ghi khác biệt. |
| Object retrieval | Query text → top-k canonical IDs. Báo Recall@k, hit@k, MRR và valid query coverage. Queries gồm synonyms, prompts trái ngữ cảnh, foreground long-tail và absent target. Unmatched GT tính là miss trong end-to-end retrieval. |
| Room retrieval | Query loại/chức năng → ranked room geometry IDs. Báo top-1/top-k và coverage, split/merge/pending breakdown. Room assignment accuracy dùng labels offline và containment oracle riêng. |
| Relation | Directed pair+question là sample. Positive, negative, unknown được annotate theo từng view và scene. Báo TP/FP/FN/TN, per-predicate precision/recall/macro-F1, coverage, abstention và conditional accuracy. Báo thêm end-to-end recall tính missing links/abstain dương là misses. Không ép unknown thành negative. |
| Graph integrity và association | Count dangling edges, alias cycles, cross-episode links, scope, hash, schema mismatch và event duplicates. Duplicate object rate = extra native objects trên GT matches chia detected matched objects, báo unmatched predictions riêng. IDF1 / ID switches chỉ khi có temporally matched GT, cross-frame ID oracle và pinned matching rule. |
| Process/runtime | Warm/cold load, p50/p95/p99 theo component/control, frame/evidence age, queue drops, calls/cost, peak CPU RSS/VRAM, bytes/revision và bytes/object/edge. Báo same-run resource telemetry và theo pha, không suy fit từ checkpoint size. |

### Tập quan hệ nhỏ

Pilot sealed offline replay từ các cảnh đã có export, bổ sung ít nhất hai cảnh ngoài tuning. Mỗi prompt phải nêu ordered pair hoặc target+anchor để QA. Sample cả same-class distractors, close-but-unrelated, reversed direction, missing evidence, occlusion, multi-view, room split và endpoint merge. Ghi ground truth bằng manual annotation hoặc evaluator geometry đã kiểm. Cùng object-pair/scene group không qua hai splits. Bước đầu so raw crop+VLM, single tokens, multi-view fusion và no-relation control trên cùng detection/graph. Dùng một file frozen annotation hash, double-label subset và adjudicate disagreement trước benchmark. Nếu thêm navigation task, generate goal set từ constraints offline, agent chỉ nhận instruction. Chấm tới hợp lệ target + STOP bằng scorer định nghĩa trước và báo riêng với HM3D ObjectNav standard.

## Navigation metrics và consumer exposure

Dùng `tools/objectnav/score_trajectories.py` schema 3 với cùng navmesh snap rule và threshold. SR là STOP có finite final DTG < 0,1 m. SPL là success × d_start/max(path_length,d_start), SoftSPL là max(0,1−DTG_final/d_start) × cùng efficiency. Báo DTG cuối/traversed minimum, OSR, steps, collisions, episode duration, VLM calls và timeout. False-positive STOP báo cả false/STOP và false/tất cả episodes, tách sai object và đúng object ngoài ngưỡng nếu có identity GT offline. [Scorer](../../src/neusymnav/evaluation/objectnav_metrics.py), [chạy baseline](../objectnav/paper-pr7-setup.md).

Đối chiếu Paper B0 `off` và `shadow` theo cùng cohort, recipe, input và action. Báo riêng độ phủ của shadow và overhead. Đánh giá `advise` phụ thuộc consumer, điều kiện join và safety gates của policy mới. Viewer, query phòng và truy vấn quan hệ dùng số đo riêng.

## Ablation B0–B7

Ký hiệu B0 trong bảng là mốc từng giao thức. Tắt feature giữ original navigation baseline, còn các semantic arms dùng cùng frozen Hydra input để tránh confound.

| Arm | Bật | Điều kiện so sánh |
| --- | --- | --- |
| B0 | Existing Hydra graph hoặc paper baseline | Frozen graph labels/geometry hoặc Paper B0 off tùy phép đo. |
| B1 | Object features | B0 + Eq. 3–4 adaptation, so mask/crop/text và từng drop-channel. |
| B2 | Room features | B0 + full-frame clustering, shared feature encoder có room-only config. |
| B3 | Object + room | Giữ checkpoint/seed M2–M3. Thêm scope room nếu query dùng. |
| B4 | Relation features | B0 + M1/M4/M5 và paired decoder. Pair-specific oracle dùng frozen endpoint/prompt để phân biệt representation với retrieval. |
| B5 | Full semantic enhancement | B3 + B4, M6 standalone queries trên cùng evidence. |
| B6 | Full ReasoningGraph-inspired integration | B5 + task orchestration benchmark và shadow/advice integration. Báo standalone task riêng navigation. |
| B7 | Lightweight | B6 hoặc highest available subset cùng interfaces và drop logs. Nếu bỏ relation decoder, chạy subcomparison B3/B7 thay vì so kết quả trộn thiếu relation. |

Bổ sung profile-control pairs: direct vs mesh reference nếu đủ ABI/data, ViT-L/14 vs B/32 giữ fusion recipe, single vs multi-view, full capped vs pruned pairs, image input vs paired latent evaluator, with/without room scope hoặc relation consumer. Pin threshold/latency budget trên DEV trước holdout. Cumulative seven-layer và module-level ablation ở [roadmap tương lai](future-module-integration-roadmap.md).

## Integrity và acceptance

Semantic annotations, unexplored map/target positions, success signals chỉ evaluator/generation hoặc explicit oracle arm. Evaluator chạy ở process riêng và không cấp GT/predicted success vào observation, memory, EEC hoặc verifier. Graph, feature/evidence cache, aliases, task progress và pending requests reset theo episode. Model weights và immutable text vocabulary caches có thể tồn tại nếu không mang episode data. Persistence chỉ arm ghi rõ protocol và cutoff. Test drift GT bằng input schema/oracle quarantine và reorder/replay checks. Gating yêu cầu graph integrity 100%, off parity, bounds và deadline pass, provenance đầy đủ. Ngưỡng chất lượng/chi phí chốt sau M0/M4 và trước holdout, cùng required coverage. Ghi failed/blocked và missing assets từng arm.
