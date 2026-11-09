# Kế hoạch thử tracker 2D của TrackGraph trên replay

> **Dành cho agent thực thi:** Khi người dùng giao triển khai, dùng `superpowers:executing-plans` hoặc `superpowers:subagent-driven-development` theo cách thực thi được chọn. Các checkbox dưới đây đều đang chờ.

**Mục tiêu:** Đo xem tín hiệu liên tục từ tracker 2D có giúp NeuSymNav giữ đúng canonical object ID qua các keyframe trên RTX 3060 Laptop 6 GiB hay không.

**Kiến trúc:** Replay RGB-D theo thứ tự capture. Tracker nhận RGB và mask YOLOE đã chốt, lan truyền identity qua các frame giữa keyframe và trả gợi ý cho ObjectOwner khi có detection mới. Dùng cùng geometry, CLIP features và evaluator cho cả hai nhánh. Canonical owner giữ quyền cấp ID và merge. Thử nghiệm chỉ nối tracker Python, với Hydra/ROS và backend TSDF nằm ngoài phạm vi.

**Công cụ:** Python, replay và ledger NeuSymNav, YOLOE outputs và CLIP cache hiện có, Python core `instance_tracking` cùng DINOv3 ViT-S+/16 trong môi trường worker riêng khi tài sản đã được cho phép.

**Thiết kế tham chiếu:** [Luồng và ownership](../../architecture.md#3-luồng-và-quyền-sở-hữu), [P04/P05/P10](../../implementation-plan.md), [baseline CG + Visual](../../results/conceptgraphs-visual-completion-2026-10-30.md), [tracker upstream](https://github.com/ntnu-arl/instance_tracking/blob/main/instance_tracking/python/instance_tracking/tracker.py) và [TrackGraph, mục IV-B](https://arxiv.org/html/2609.31005v1#S4.SS2). Chốt lại source commit và seam trên checkout thực thi. Checkout lúc viết là `9b90d31`.

## Phạm vi và nguyên tắc

- Kế hoạch này chưa cấp quyền cài dependency, tải checkpoint/dataset, chạy benchmark GPU hay đổi cấu hình mặc định. Khi được giao thực thi, dùng tài sản đã có và phạm vi được cấp. Liệt kê chính xác tài sản thiếu và hoàn thành phần độc lập trước khi xin quyền cần thiết.
- Chỉ ghi trong `NeuSymNav/`. Hai repo nguồn chỉ đọc. Một GPU workload tại một thời điểm. Mỗi file một writer, main khóa contract và giữ quyền tích hợp.
- **A** là CG + Visual hiện tại. **B** dùng cùng detector batch, raw mask, depth, pose, projection và CLIP feature như A. Chỉ thêm gợi ý nối detection tại keyframe với canonical object đã thấy trong cùng đoạn track. Hai nhánh dùng ledger mới riêng theo episode.
- Trong pilot, mask propagation phục vụ tracker và diagnostics. Chúng không được commit thành observation 3D, tăng số detection, tạo negative evidence hay dùng để điều khiển. Batch và provenance detector giữ nguyên. Semantic GT chỉ đọc bởi evaluator sau khi outputs được đóng và hash.
- Phân biệt `FrameKey` gốc, thời điểm capture và clock domain replay. Mỗi source track là `(episode_id, sensor_id, tracker_generation, local_track_id)`. Generation đổi khi reset. Canonical ID và alias vẫn thuộc ObjectOwner.
- Các mức 320/480 px, giới hạn VRAM và ngưỡng chất lượng bên dưới là đề xuất cho pilot. Khóa trước khi xem kết quả đánh giá.

## Các bước thực hiện

### T0. Chốt replay và tài sản

**Sửa khi thực thi:** Tạo `tools/replay_trackgraph_2d.py` cho inventory và chạy thí nghiệm. Đọc `src/neusymnav/recording/replay.py`, `tools/replay_association_quality.py` và `tools/replay_visual_association.py` để tái dùng loader và binding thay vì viết decoder mới.

- [ ] Lập manifest cho tối đa ba cửa sổ, mỗi cửa sổ 15–30 giây, tối đa 600 frame xử lý. Tìm một đoạn có vật thể hiện diện liên tục và một đoạn có che khuất hoặc xuất hiện lại. Ưu tiên các đoạn cùng scene có GT nếu có. Ghi scene/episode, frame range, nhịp nguồn, nhịp xử lý, source hashes, detector/CLIP recipe, calibration, timestamp, số frame thiếu và số keyframe join được.
- [ ] Kiểm tra actual frame giữa các keyframe bằng manifest và decode. Run `runs/demo-conceptgraphs-visual-20261109-015456-661064060/recording-certificate.json` ghi 8 keyframe đã commit, nên certificate này chỉ là đầu mối kiểm kê. Keyframe-only có thể dùng để tái lập baseline, còn propagation cần chuỗi RGB thật. Nếu thiếu chuỗi phù hợp, ghi yêu cầu capture bounded và dừng phần đánh giá propagation tại đây.
- [ ] Đếm các cặp keyframe có frame trung gian thật và cách nhau tối đa 1 giây theo profile T1. Nếu lịch commit cũ quá thưa, đề xuất tạo một cache YOLOE chung ở nhịp 1 Hz trên clip liên tục đã khóa, dùng cùng recipe và cùng cache cho A/B. Việc này cần lượt inference được cấp phạm vi khi thực thi. Báo nhịp thử nghiệm tách khỏi nhịp commit lịch sử và giữ cohort đánh giá cố định. Dừng pilot chất lượng nếu thiếu cặp đủ điều kiện.
- [ ] Join đúng `(episode_id, sensor_id, frame_index, geometry_hash)` và đối chiếu RGB/mask hashes, pose version, calibration và timestamp. Khóa cách xử lý frame thiếu trước khi chạy A/B. Không nội suy frame thiếu hoặc thay detection bằng kết quả lần chạy khác.
- [ ] Pin commit tracker, license/notice, DINO checkpoint SHA-256, preprocessing, Python/Torch/CUDA và interpreter. Kiểm tra tài sản theo đường dẫn explicit. Mô hình và code phải load từ local đã pin, fail preflight khi thiếu. Tách quyền model weights khỏi license repo. DINOv3 cần checkpoint riêng theo [hướng dẫn upstream](https://github.com/ntnu-arl/trackgraph_ros#tracker-environment-and-weights).

**Đạt khi:** `input-manifest.json` có tập frame và tập detection có thể tái đọc. Báo số frame liên tục, số join lỗi và số GT identity/transition có thể chấm, kể cả khi bằng 0. Thiếu DINO vẫn có thể hoàn thành kiểm tra dữ liệu và fixture.

### T1. Adapter tracker và gợi ý có provenance

**Tạo khi thực thi:** `src/neusymnav/perception/trackgraph_2d.py`, `tests/test_trackgraph_2d_replay.py`. Môi trường chính dùng DTO và adapter. Torch/DINO chỉ được import trong worker khi chọn profile thử.

- [ ] Chốt interface replay `step(frame: Observation, batch: DetectionBatch | None) -> tuple[TrackHint, ...]`. `TrackHint` gồm frame key, geometry hash, capture timestamp/domain, detection ID, source track key, anchor keyframe, tuổi anchor, match IoU và tracker recipe ID. `batch=None` cập nhật state propagation và trả tuple rỗng. Batch rỗng vẫn là sự kiện keyframe hợp lệ.
- [ ] Adapter dùng đúng YOLOE mask của keyframe để khởi tạo/correct track. Kiểm tra seam mask ngoài tại commit đã pin. Nếu cần, thay lớp cung cấp masks hoặc trích hẹp propagation/track manager với notices. Giữ mapping từ mask gốc đến detection ID, xử lý overlap bằng quy tắc deterministic và bỏ gợi ý khi không join được duy nhất. Giữ nguyên mask của detector dùng cho projection.
- [ ] Khởi điểm profile `short_side=320`, context tối đa hai frame gồm anchor, tối đa 32 active tracks, một frame in-flight. Khóa giới hạn trước forward. Giữ toàn bộ detector output cho A và B, ghi riêng trường hợp tracker từ chối vì vượt cap. Chỉ thử 480 px nếu 320 còn đủ headroom và cần kiểm tra ảnh hưởng độ phân giải. Dense attention upstream tăng theo `T × N²` với số patch `N`. [Mã propagation](https://github.com/ntnu-arl/instance_tracking/blob/main/instance_tracking/python/instance_tracking/models/propagation.py)
- [ ] Reset khi đổi episode/camera/calibration, source bị đảo thứ tự, mất frame ngoài nhịp đã khai báo hoặc gap quá 500 ms giữa hai frame xử lý. Gợi ý tại keyframe mới chỉ hợp lệ nếu nối về anchor detection trước trong tối đa 1 giây. Đoạn không có anchor hợp lệ chạy association gốc và ghi lý do. Keyframe kế tiếp có thể khởi tạo generation mới.
- [ ] Dùng worker giả trong test `test_trackgraph_2d_replay.py` để pin đúng join, batch rỗng, giới hạn, reset khi gap, reused ID sau reset và thiếu model. Test phải chứng minh fixture dùng được khi thiếu Torch/Hydra/ROS và không phát hint từ frame propagation.

**Đạt khi:** `track-hints.jsonl` và `tracker-diagnostics.json` ghi được anchor, gap/reset, hint được chấp nhận hoặc bị từ chối. Fixture pass là bằng chứng contract, chưa chứng minh propagation từ DINO thật.

### T2. Nối gợi ý vào đúng canonical owner và chạy A/B

**Điểm nối khi thực thi:** `src/neusymnav/objects/store.py`, `src/neusymnav/objects/association.py`, `src/neusymnav/objects/association_recipe.py` và CLI T0. `AssociationObservation.track_id` đã tồn tại nhưng đường adapter từ store chưa truyền nó. Nhánh CG và legacy có cách chấm riêng, nên cần test đúng đường CG. Không tạo identity store mới.

- [ ] Thêm tùy chọn thử nghiệm rõ ràng cho replay. A chạy recipe CG + Visual gốc. B truyền `TrackHint` đã validate qua đường commit của owner, ghi recipe/hints và binding trong ledger hoặc manifest replay có hash. Không tự đổi schema cũ. Nếu cần resume, dựng lại hint state bằng replay prefix và so kết quả, hoặc đánh dấu lần chạy phải bắt đầu lại từ đầu.
- [ ] Với B, chỉ cộng tối đa `0.05` vào điểm cặp đã qua geometry, base threshold và cannot-link của recipe gốc, nếu anchor trỏ duy nhất đến canonical ID còn hợp lệ qua alias. So ambiguity margin trên điểm sau cộng và giữ Hungarian one-to-one. Hint mâu thuẫn, cũ, chưa có canonical match hoặc không qua gate có bonus 0. Một hint không tự tạo ID, ép merge hoặc bỏ qua kiểm tra hình học. Lưu base score, bonus và quyết định cho các hàng thay đổi.
- [ ] Xuất A/B theo cùng thứ tự frame, batch và mask hashes. Tập detections, projected observations, appearance cache và mẫu số cố định giống nhau. Báo riêng số projected không gán được, số hint được dùng và số gợi ý bị bỏ. So mode B với hint rỗng để xác nhận assignments/alias bằng A.
- [ ] Thêm test `tests/test_trackgraph_2d_association.py` cho bonus đổi lựa chọn trong cặp hợp lệ, không vượt gate, alias collision, reset/reused track ID, hint rỗng, commit lặp và rollback. Theo dõi verification để thấy hint không tạo thêm detection evidence. Chạy cùng `tests/test_conceptgraphs_integration.py`, `tests/test_association_replay.py` và `tests/test_verification.py`.

**Đạt khi:** A tái lập trên cùng replay, B với hint rỗng khớp A, mọi khác biệt của B đều truy ra được hint hợp lệ. Review độc lập đường ownership, replay và GT isolation theo chính sách repo trước khi dùng kết quả để chọn profile.

### T3. Đo chất lượng và tài nguyên, rồi ra quyết định

- [ ] Chạy CPU fixture trước. Nếu có tài sản được phép, chạy tracker thật offline sau khi detector đã tạo cache và nhả GPU. Đo một workload tại một thời điểm. Ghi p50/p95 thời gian tracker theo frame và keyframe, tốc độ trên nhịp đã chọn, số frame drop/gap, RSS peak, VRAM toàn thiết bị và peak allocated/reserved của Torch. Tách warmup, model load và steady state. Không cộng chồng các số đo allocator và VRAM toàn thiết bị.
- [ ] Dùng [evaluator association hiện có](../../../src/neusymnav/evaluation/association_quality.py) với endpoint ID tại thời điểm commit. Báo IDF1, AssA, ID switch theo cùng cơ hội, false merges, fragments, revisit đúng/tổng cơ hội và tỷ lệ assigned trên cùng tập projection. Ghi denominator, support theo clip và các mẫu track drift. Không dùng alias cuối run để viết lại score online. Nếu có ít dữ liệu, giữ báo cáo theo từng đoạn và tránh gộp ra kết luận tổng quát.
- [ ] **Ngưỡng tài nguyên pilot:** peak VRAM toàn thiết bị tối đa 5.120 MiB để chừa 1 GiB so với dung lượng 6.144 MiB. Giữ mọi OOM, timeout và run thiếu sample trong báo cáo. p95 phải nằm trong khoảng cách frame của cadence tracker đã khóa, với số frame bị bỏ báo riêng. Peak offline chỉ cấp bằng chứng cho offline. Nếu đi tiếp đến smoke online, đo lại VRAM và deadline điều khiển với simulator và các worker của profile thực tế.
- [ ] **Ngưỡng chất lượng pilot:** IDF1 tăng ít nhất 2 điểm phần trăm so với A, false merge không tăng, tỷ lệ assigned trên projection không giảm quá 2 điểm phần trăm. Kiểm tra ID switch và revisit trên cùng tập cơ hội cố định trước. Mục tiêu tối thiểu 20 chuyển tiếp có GT trên ít nhất hai clip không chồng nhau. Nếu thiếu support hoặc chỉ có một scene, kết quả chỉ có giá trị thăm dò. Giữ tách development và evaluation nếu đủ dữ liệu, khóa tham số trước khi chấm.
- [ ] Ghi `comparison.json`, `resources.json`, `decision.md` và source hashes dưới `runs/trackgraph-2d-<run-id>/`. Chọn một kết quả. **Thử smoke online opt-in** nếu chất lượng, provenance và tài nguyên đều đạt. **Giữ offline và chẩn đoán** nếu gain chưa rõ hoặc GPU sát cap. **Dừng hướng tracker này** nếu false merge tăng hoặc tracking thường xuyên mất dấu. Smoke online, đưa propagated mask vào fusion và bỏ ConceptGraphs là các quyết định tiếp theo sau pilot.

## Kiểm chứng và bàn giao

Lệnh CPU dự kiến từ root khi các test mới đã được viết:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_trackgraph_2d_replay.py tests/test_trackgraph_2d_association.py tests/test_conceptgraphs_integration.py tests/test_association_replay.py tests/test_verification.py
```

Các gate review tập trung vào source join sai, gap tạo liên kết giả, bonus vượt geometry gate, alias làm lệch owner, và mẫu số giảm do bỏ detections. T1/T2 pin bốn lỗi đầu. T2/T3 đối chiếu đủ tập nguồn và mẫu số. Báo `implemented`, `correctness-verified`, `runtime-validated` riêng theo từng task, kèm lệnh, exit code, artifact và phần chưa được chứng minh. Bản kế hoạch hiện chỉ là tài liệu để duyệt trước khi thực thi.
