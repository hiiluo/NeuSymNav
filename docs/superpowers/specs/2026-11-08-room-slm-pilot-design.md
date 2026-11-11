# Thử nghiệm SLM gán nhãn phòng trên Hydra — thiết kế

Ngày 2026-11-08. Trạng thái: đề xuất để review; chưa triển khai SLM, chưa cài runtime/tải model.
Workspace: Kiet_branch2. Plan đồng hành: `../plans/2026-11-08-room-slm-pilot.md`.

## Mục tiêu và tiến bộ hiện tại

Người dùng đã chọn SLM đọc object/quan hệ dạng text; exploration có thể bàn giao đồng đội. Có thể phát triển pilot semantic overlay ngay, không đợi mọi run đạt freshness <5% hoặc segmentation hoàn hảo.
Hydra có native graph, place/object→room ancestry và export theo revision. Replay cố định 00806/00807 cho final 3/2 rooms; người dùng báo live 00807 phân đúng kỳ vọng và ảnh có 3 room nodes. Đây là hai protocol khác nhau, không mâu thuẫn và không thay formal annotation.
00805 vẫn có failure: trên 13 revision gộp chéo, support bathroom bị clearance loại hết hoặc còn singleton bị min-component loại; chưa chứng minh SLM hoặc threshold policy sửa geometry. Multi-scene annotation định lượng còn thiếu. Object→room ancestry có provenance không đồng nghĩa object association/detection đúng. Control freshness còn hạn chế, bàn giao riêng.

## Giữ baseline và ranh giới ownership

`docs/baselines/hydra-room-slm-pilot-2026-11-08.lock.json` ghi SHA256 profile 00805/006/007, YAML dataset/labelspace, private DSO và selected integration sources. Đây là khóa thực nghiệm, không phải commit, full dependency closure hoặc bằng chứng thư viện đã load trong run mới. Không chmod; không đóng băng graph online; không promote default. Hash profile/YAML/privateDSO là geometry baseline giữ nguyên; selected source hashes là điểm xuất phát audit, các sửa contract/service được plan cho phép phải có source manifest mới, không thay lock gốc hoặc gọi đó là geometry drift.
Giữ compression .5m, merge .25m, min-component3, min-room10, PLATEAU/NEIGHBORS, dilation .5–1.2m, private policy confirm3/tolerance .02/epsilon .0001. Trước replay phải kiểm hash và loaded DSO/build provenance như pipeline hiện có. Scene/spawn/calibration khác nhau phải có profile riêng.
SLM không sửa RoomFinder, native IDs, membership hay control. Đồng đội phụ trách exploration; nếu đổi navigation/cadence, ghi config hash riêng và không gọi live trước/sau là A/B SLM cùng cấu hình. Main giữ contracts và tích hợp UI. Không chạy benchmark tranh CPU/GPU. Không tự commit/push.

## Các cách tiếp cận và lựa chọn đề xuất

1. **Offline trên graph ghi sẵn, sau đó shadow worker local**: dễ cô lập lỗi semantic/geometry và đo tài nguyên; đề xuất dùng. Người dùng đã chọn text-input, các chi tiết runtime/model dưới đây là đề xuất của agent, chưa phải lựa chọn đã được benchmark/chấp thuận triển khai.
2. Chạy local SLM trong mọi live update ngay: nhanh có hình UI nhưng tăng contention, khó phân biệt lỗi scheduling và suy luận; hoãn.
3. Endpoint máy khác: giảm tải máy robot, cần quản lý mạng/model provenance/data transfer; phương án thay thế sau khi người dùng chọn, không tự gửi dữ liệu ra ngoài.

## Model và runtime thử nghiệm

Đề xuất đầu tiên **Qwen/Qwen3-1.7B**, non-thinking (`enable_thinking=False` đúng chat template), GGUF Q4_K_M với llama.cpp CPU local process riêng. Model card Apache-2.0, hỗ trợ tắt thinking. Không suy luận tốc độ hay quality từ số tham số. Q4 là quantization, không phải fine-tuning.
Model đối chiếu tùy chọn **Qwen/Qwen3-4B-Instruct-2507**, model card là non-thinking, Apache-2.0; chỉ chạy sau nếu 1.7B thiếu chất lượng, đủ RAM và có quyền tải. Không tải cả hai mặc định. Đây là lựa chọn cho pilot, không phải tuyên bố model mới nhất/tốt nhất.
Máy đọc hiện tại: i5-13420H, 16GB RAM, khoảng 7GB available và đã dùng swap. Availability thay đổi; không mặc định UHD được runtime expose. Khởi đầu CPU-only offline, 1 thread; không cài chung môi trường Hydra/detector, không vLLM/CUDA dependency cho pilot này.
Pin revision model gốc, tokenizer/chat-template, file GGUF SHA/license/source/conversion/quantizer, llama.cpp commit/binary SHA, prompt/schema/vocabulary/decoding settings. GGUF chưa hiện hữu thì asset gate phải ghi missing; tên model không phải lock. Ưu tiên artifact publisher có provenance hoặc chuyển đổi từ model gốc được pin; chưa xác định nguồn exact GGUF, không tự chọn mirror vô danh.
Runtime proposal: context tối đa4096 tokens, input tối đa3072, output tối đa384, greedy temperature0/seed0 (không cam kết bitwise across builds), offline timeout60s/job. Pin params trước eval; overload/timeout trả typed failure, không sửa guard. Live chỉ thử sau benchmark riêng: deadline5s/job; nếu không đạt giữ offline, không âm thầm tăng thread/GPU hoặc deadline để báo pass.

## Input và output

Tái sử dụng `rooms/context.py:build_room_context` và `contracts/room_semantics.py`. Context hiện tối đa64 distinct native object IDs; v1 nếu truncated=True thì abstain insufficient_evidence:context_object_cap_exceeded trước modelcall, không suy nhãn từ first64 bị cắt; evaluator báo nhóm này riêng; category lấy vocabulary pin qua Hydra query. Relations v1 chỉ gồm native object→place→room ancestry nếu export có, room structural adjacency khi có; không bịa near/inside/door từ centroid. Không gửi raw class strings chưa canonicalize, room name GT, scene ID có semantic hint, annotation hay ảnh vào prompt.
Phân biệt geometry data available, geometry quality đã đánh giá, membership assigned, association evidence quality. Thiếu crop/mask không xóa semantic node: vẫn dùng trong nhóm graph-only, UI nêu evidence chưa kiểm; không gọi là verified. Ambiguous membership không dùng như support chắc chắn; không lấy graph last-source làm object last-seen.
Vocab giữ nguyên: bedroom,bathroom,kitchen,living_room,dining_room,office,hallway,utility,mixed,unknown. Hallway không được suy từ “không thấy object”; mixed không phải cách che room gộp sai. Unknown/insufficient_evidence hợp lệ.
Model chỉ trả JSON semantic fields: label, alternatives (≤2), supporting_object_ids (≤8), status, reason (≤256 ký tự). Host gắn room_id/revision/hash/model/prompt từ request đáng tin, không tin model tự khai identity. Strict JSON/schema + validator; proposed label cần ít nhất1 supporting ID trong context có assigned membership, có reason; ID hợp lệ chưa chứng minh rationale đúng. Không dùng self-confidence làm xác suất hiệu chuẩn. No model/timeout/bad JSON không thành label available. Có mismatch hiện hữu: proposal cho invalid_output nhưng result không cho; S1 phải chốt mapping invalid_output→invalid trong validate_room_label trước adapter, thêm regression test, giữ status invalid_output ở proposal để tương thích producer.
Envelope bắt buộc episode_id,run_id,room_id,graph revision,input-prefix hash,geometry hash (nullable khi support unavailable; trường hợp này host abstain trước model),context hash,request ID,world epoch nếu export có; model/prompt/schema/runtime hashes. Contract hiện thiếu run/episode trong proposal, validator chưa yêu cầu support không rỗng: bổ sung wrapper/check ở service, không tuyên bố đã có đủ.

## Revision, cache và label stability

Exact result gắn snapshot đã gửi. Replay/offline được hiển thị lịch sử với revision gốc. Live chỉ attach nếu episode/run/room/revision/geometry/context vẫn khớp; khác thì stale và giữ trong history, không gắn revision mới. Nếu graph cập nhật nhanh hơn inference, chưa được mở rộng reuse khi chưa có kiểm chứng tương đương geometry/membership. V1 không reuse giữa revisions; exact-key cache gồm full envelope+model/prompt/schema. Tối ưu reuse nội dung là follow-up riêng, không copy model envelope cũ.
Mỗi room chỉ giữ latest pending, tối đa32 pending và1 in-flight, round-robin để không starve room khác; debounce3s tính từ lần dispatch gần nhất của room, không chờ graph yên3s và không reset timer bởi mỗi update; không tạo backlog vô hạn. Timeout/cancel/crash bounded; reset episode hủy job/cache cũ. Nhãn proposed có thể hiện ngay; stable-display cần2 kết quả đồng thuận từ distinct evidence-context hashes cùng tập assigned object IDs và parent links (exact match), không coi đó là independent views hoặc xác suất đúng. Không ép có2 kết quả khi context không đổi; giữ proposed. Room split/merge/reparent mất tính tương thích: bỏ trạng thái stable, không kế thừa bằng ID đơn thuần.

## Đánh giá và điều kiện tiếp tục

Geometry và label score riêng. Baseline luật đơn giản và SLM nhận cùng predicted context; annotation/evaluator tách khỏi runtime/prompt. Replay geometry-only 006/007 có empty detections: chỉ dùng negative test insufficient_evidence, không benchmark semantics. Cần detector-backed recording mới hoặc có sẵn với canonical semantic IDs, ancestry và representative RGB để người dùng gán nhãn semantic reference.
Pilot mục tiêu ≥12 physical room instances trên ≥3scenes, gồm sparse hallway/open-plan/ambiguous; repeated revisions không là mẫu độc lập. 00805/006 dev; 007 held-out theo scene nếu chưa dùng để chỉnh prompt. Nếu thiếu classes/support chỉ báo pilot per-room, không gán macroF1 đại diện mọi class. Human có thể unknown/multi-function; reference label không rút từ model hoặc Hydra room count. Không ép các native room thuộc cùng physical room thành nhiều GT rooms.
Báo macroF1 theo labelset có support, confusion, coverage/abstention/selective accuracy, invalid/hallucinated-support rate, temporal flips per distinct context, latency p50/p95/max, peak process/host RAM/swap. Tách geometry-correct subset và end-to-end (gộp/chia sai), graph-only evidence và reviewed evidence. Không dùng boundary unknown như correct; không gọi label đúng là geometry đúng.
Cổng đề xuất: correctness fixtures0 stale attachments/0 invalid-support accepted/0 geometry writes; semantic pilot accepted accuracy≥80% tại coverage≥50% trên reviewed eligible contexts và không kém baseline tại coverage tương đương. Nêu raw numerator/denominator và per-room uncertainty; với sample nhỏ chỉ cho phép shadow pilot, không production claim. Mục tiêu tài nguyên offline RSS process≤3GiB (đo cả file-backed/PSS và hostavailable/swap), tránh cạn hostRAM. Thất bại budget hoặc quality là kết quả spike, không ép pass.
Live OFF/ON cùng input replay trước, rồi paired short simulator trials chỉ sau khi resource/quality đạt; 30–60s shadow UI, không đi qua actuator. So sánh freshness, useful moving controls, localmap p95 và trajectory/coverage; ngưỡng dừng nếu timeout/stale liên tục, hostavailable<2GiB hoặc Δfreshness>2 percentage points / localmap p95 tăng>10% lặp lại. Nếu tải máy/run không tương đương: inconclusive, quay lại offline. Cổng usability live đề xuất: ít nhất10 job hoàn tất trên≥2rooms và≥50% tổng job hoàn tất (kể cả timeout/invalid) attach được publication hợp lệ với exact-current key; báo riêng tỷ lệ label available và abstention. Nếu thiếu mẫu hoặc thấp hơn, kết quả live là inconclusive/not ready, giữ offline/history; không nới revision check. Đây là budgets đề xuất chưa nghiệm thu, không universal guarantee.

## Nguồn chính thức đã kiểm tra 2026-11-08

- https://huggingface.co/Qwen/Qwen3-1.7B — model card, license, chat template thinking switch.
- https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507 — non-thinking instruct và license.
- https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md — subset JSON-schema constrained decoding; cần validator host vì syntax không bảo đảm factuality.

## Output consistency implementation addendum — 2026-11-08

`room-output-consistency-v1` now uses request-bound GBNF instead of unsupported JSONschema uniqueness/conditionals. Decoder compactJSON fixedfieldorder, canonical sorted subsetarrays, proposedknownlabel+assignedsupports1..8, alternatives0..2unique/excludingprimary; abstentionunknown+emptyarrays; reason1..256startingprintableASCII. HostJSONadapter stillvalidates alloutputs/rejectsduplicatekeys/truncation, corevalidator rejectsunknown/insufficientclaims. It doesnot establish evidencefactuality. Pin grammarpolicy/hash alongside structural-schema/model/prompt/runtime andfullrequestkey beforefutureS4 cache/publications; genericmodelmanifesthash alone doesnotclose decoderpolicy. Currentofflinebackendmetrics/CLI artifacts retainthosehashes; no publicpersistentworker/UIyet. OfflineKV measurement report `../../results/room-slm-consistency-kv-2026-11-08.md`; sharedconfigdisabled, no geometry/controlchanges.
