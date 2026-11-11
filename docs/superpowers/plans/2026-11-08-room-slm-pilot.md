# Hydra room-label SLM pilot — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development hoặc superpowers:executing-plans để thực thi từng task. Checklist dưới đây là việc tương lai; không tự commit, tải model hoặc triển khai khi mới đọc plan.

**Goal:** Thử nghiệm nhãn loại phòng bằng SLM text trên native Hydra graph, có provenance và abstention, rồi mới cân nhắc shadow UI.

**Architecture:** Hydra giữ geometry và IDs. Read-only snapshot → bounded text context → process SLM riêng → strict validator → revision-bound semantic overlay; control/exploration không phụ thuộc kết quả.

**Tech Stack:** Python contracts/query/evaluator hiện có; đề xuất Qwen3-1.7B non-thinking/GGUF Q4_K_M + llama.cpp CPU, chưa cài/chưa pin asset thực tế.

**Spec:** [Thiết kế và quyết định đề xuất](../specs/2026-11-08-room-slm-pilot-design.md). Bổ sung/ưu tiên phần pilot của B2/B3 trong `2026-11-06-hydra-rooms-slm.md`, không tuyên bố các task cũ hoàn tất.

## Global Constraints

- Chỉ Kiet_branch2; Hydra baseline `docs/baselines/hydra-room-slm-pilot-2026-11-08.lock.json`; không sửa source siblings, private DSO hoặc default geometry config.
- Guard300ms/horizon100ms/source gốc; GT/annotation evaluator-only; no actuator/room geometry writes từ SLM.
- Native room ID độc lập semantic label; evidence membership không tự chứng minh association đúng.
- Offline trước; model download/install riêng sau khi người dùng giao thực thi và chấp thuận asset/budget theo AGENTS. Không tải trong lượt chuẩn bị plan.
- Main quản lý shared contracts/producer/UI. Luna xhigh cho task đóng; chỉ nâng model khi có bất định kỹ thuật; cấm astra. Không dispatch cho mỗi thao tác nhỏ.
- Mỗi task ghi implemented/correctness-verified/runtime-validated riêng, commands/exit/artifacts. Không full-suite/native-quality claim từ fixture.

## Review Focus

1. Cùng R(0) nhưng run/episode khác: không attach/reuse; test S1/S4.
2. Cùng room ID nhưng split/merge/reparent hoặc revision tăng khi job chạy: stale; test S1/S4/S5.
3. Object hallucination/unsupported ID/ambiguous membership, empty graph-only scene: abstain/invalid; test S2/S3.
4. Nhanh cập nhật graph làm mọi reply stale và room nhiều làm queue quá tải: bounded/fair, hiện pending/history; test S4/S5.
5. Nhãn bathroom trông đúng nhưng geometry gộp hành lang hoặc mất evidence: stratified evaluation/uncertain UI, không geometry success; test S3/S5/S6.

## File map và interfaces

**Existing, tái sử dụng:**
- `src/neusymnav/rooms/context.py`: `build_room_context(query,evidence,room_support,room_id)->RoomContext` (64objects).
- `src/neusymnav/contracts/room_semantics.py`: `RoomLabelProposal`, `RoomLabelResult`, `validate_room_label(proposal,context)`; giữ compatibility; sửa mapping proposal invalid_output→result invalid (hiện validator có mismatch gây ValueError).
- `src/neusymnav/backends/hydra/query.py`: native category + room ancestry read-only.

**Proposed new:**
- `rooms/requests.py`: `RoomLabelRequestKey` frozen dataclass(episode_id:str, run_id:str, room_id:str, graph_revision:int, input_prefix_sha256:str, geometry_hash:str|None, context_hash:str, world_epoch:str|None); `RoomLabelRequest(key,context,relations,source_manifest)`; `make_room_label_request(query,evidence,room_support,world_epoch=None)->tuple[RoomLabelRequest,...]` dùng room IDs native, không IDs tự tạo. Relations là tuple các ancestry/structural records từ cùng projection, không distance semantics.
- `rooms/prompt.py`: `render_room_prompt(request,tokenizer,budget)->PromptRecord` gồm prompt bytes/hash, retained object IDs, truncation và exact payload schema; input quá3072tokens thì fail typed `insufficient_evidence:context_budget_exceeded`, không cắt identity hoặc âm thầm mất support. V1 không token-trim context khác với contract.
- `rooms/labels.py`: `RoomLabelBackend.infer(request:RoomLabelRequest)->RoomLabelProposal`; `adapt_model_reply(raw:str,request,model_hash:str,prompt_hash:str)->RoomLabelProposal`; request identity do host gắn.
- `rooms/slm_backend.py`: `LlamaCppRoomLabelBackend`, timeout/schema/response bounds, local-only transport. Không thêm dependency vào Hydra env.
- `rooms/service.py`: `RoomLabelService.offer(request)->bool`, `poll(current_keys:Mapping[str,RoomLabelRequestKey])->tuple[RoomLabelPublication,...]`, `snapshot(key)->RoomLabelPublication|None`, `close(timeout_s:float)->ShutdownReport`.
- `contracts/room_label_publication.py`: immutable `RoomLabelPublication(request_key,result,model_manifest_hash,prompt_hash,schema_hash,runtime_hash,started_at_ns,completed_at_ns,display_state)`. Service wrapper so sánh exact full key trước attach; result historical giữ original key. Time dùng process monotonic và clock domain riêng, không giả capture mới.
- `rooms/worker.py`: process ownership, JSON wire/version, no graph/control access, max1inflight.
- `evaluation/room_labels.py`, `tools/{infer_room_labels,evaluate_room_labels}.py`: offline exports, baselines/evaluation.
- `configs/room-label-slm.experimental.json`: opt-in runtime budgets/model path+hash, mặc định disabled.
- UI integration tuần tự `visualization/{publisher,desktop}.py`, runtime launch plumbing `runtime/{configuration,launcher}.py` chỉ sau offline gates.

Signature chi tiết dataclass publication wire được main khóa trong S1 trước worker/UI; không để worker tự mở rộng fields hoặc đổi existing constructors. Dùng `RoomLabelResult` hiện có, không tạo status spelling khác.

### S0 — Baseline và asset inventory (không model execution)

**Files:** lock trên; `runs/room-slm-pilot/S0/{inventory,baseline-check}.json`, `docs/implementation-status.md`.

- [ ] Kiểm SHA từng entry lock; lưu gitHEAD+dirty manifest và live profile thực tế nếu người dùng cung cấp run00807; báo chưa có run file thì chưa xác minh user-run config.
- [ ] Kiểm native loaded-build closure theo metadata hiện có, config/extrinsics/vocabulary/source identity. Giữ hash geometry riêng và full-run hash riêng cho teammate navigation.
- [ ] Inventory có giới hạn local model/runtime paths, RAM/CPU/device exposure; ghi model/runtime missing nếu không có. Không scan dữ liệu riêng ngoài project/cache được phép.
- [ ] Ghi proposed exact download/conversion size/license/source và disk/RSS allowance cho1.7B; chỉ thực hiện asset step khi quyền tương ứng rõ. Không tự tải4B hoặc đổi Hydra env.
- [ ] Deliverable inventory/baseline-check exit0 với hashes match; missing model là typed unavailable, không fake success. Nếu hash drift, tạo lock mới được giải thích, không overwrite lịch sử.

### S1 — Request identity và read-only context snapshot

**Files:** create `rooms/requests.py`, `contracts/room_label_publication.py`, `tests/test_room_label_requests.py`; modify `contracts/room_semantics.py` cho status mapping; extend `tests/test_room_context.py`, `tests/test_room_label_contract.py` khi cần, main owner.

- [ ] RED tests: same R(0) cross-run; stale geometryhash/prefix/revision; room with zero semantic objects; >64objects/truncation; duplicate evidenceframes không nhân object count; ambiguous ancestry; missing geometry→host insufficient_evidence/no model call; truncated context→host insufficient_evidence/no model call; invalid_output proposal→invalid result không raise; relations unavailable; unsupported epoch.
- [ ] Run `.venv/bin/python -m pytest tests/test_room_label_requests.py tests/test_room_context.py tests/test_room_label_contract.py -q`; lưu failure thật.
- [ ] Implement `make_room_label_request`/publication wrapper với exact identity và nullable geometry hash khi unavailable; sửa existing validator mapping invalid_output→invalid; truncated=True hoặc missing geometry host abstain trước modelcall; giữ distinction geometry availability vs annotation correctness; không gọi `usable_for_targeting` là navigation proof. Relations missing trả tuple rỗng + provenance missing, không bịa edge.
- [ ] GREEN cùng command; snapshot serialization deterministic; hash native graph/assignments trước/sau build identical; episode reset fixture không nhận result cũ. Deliverable reusable snapshot CLI fixtures, chưa có model.

### S2 — Prompt, rules baseline và strict semantic adapter

**Files:** create `rooms/{prompt,labels}.py`, `evaluation/room_labels.py`, `tests/test_room_label_prompt.py`, `tests/test_room_label_adapter.py`.

- [ ] RED: valid bath(tub/toilet), sparse/noobjects→abstain, chair-only không ép office, room mixed cues không khẳng định repaired geometry; badJSON/extra fields/unknownlabels/duplicate alternatives/>2 alternatives/>8support/>256charreason/empty support/foreign or ambiguous IDs; raw prompt-like category; request hash do model tự khai bị reject.
- [ ] Run `.venv/bin/python -m pytest tests/test_room_label_prompt.py tests/test_room_label_adapter.py -q`; record RED.
- [ ] Implement bounded English canonical-input prompt, JSON schema, host `adapt_model_reply`; host strips no arbitrary prose để “cứu” invalid JSON; model status chỉ proposed/unknown/insufficient_evidence. Không dùng `reason` làm instruction hoặc generated text làm worker command.
- [ ] `rule_baseline(request)->RoomLabelProposal`: deterministic explicit rules versioned (toilet/bathtub→bathroom, bed→bedroom; contradictory anchors→mixed/unknown; otherwise insufficient_evidence); pin rule file hash trước held-out eval. Supporting IDs thật và cùng adapter checks; rule không ground truth.
- [ ] GREEN tests, include tokenbudget exact failclosed và geometry immutability. Deliverable prompt/schema/rule hashes, no semantic-quality claim từ fixtures.

### S3 — Asset spike và offline pilot thật

**Files:** create `rooms/slm_backend.py`, `tools/infer_room_labels.py`, `tests/test_room_slm_backend.py`, `configs/room-label-slm.experimental.json`; `runs/room-slm-pilot/S3/`.

- [ ] RED subprocess fixtures: absentfile/hashmismatch, oversizedresponse (>16KiB), timeout60s, crash/nonzeroexit, missing chattemplate/non-thinking support, JSON grammar unsupported, no-model returns unavailable. Run `.venv/bin/python -m pytest tests/test_room_slm_backend.py -q` RED.
- [ ] Sau asset authorization, tạo runtime riêng và pin manifest (upstreamrevision/conversion/GGUF/tokenizer/license/binary/grammar settings); compile/install chỉ runtime đó, không sửa native Hydra/detector. Nếu thiếu assets vẫn GREEN fixture, giữ runtime-unvalidated.
- [ ] Implement local CPU process/backend with1thread,4096context/3072input/384output, greedy/seed0,60sdeadline; template hard disables thinking for1.7B, không chỉ thêm `/no_think` vào usertext. Không remote fallback.
- [ ] GREEN tests; chạy model thực trên vài frozen reviewed contexts, log exact prompt/reply/IDs/model and runtime hashes/time/RSS; malformedreply→invalid_output, không sửa nhãn thủ công trong predictions.
- [ ] Thu detector-backed data phù hợp trước eval: kiểm dataset có semantic IDs thật và imagery. Existing006/007 geometry-only recording dùng negative tests, không substitute objects bằng annotation. Nếu chưa có, targeted primary RGB-D capture/detector replay riêng đã được giao khi triển khai; không phải exploration benchmark.
- [ ] Deliverable pilot report/limitations, process RSS≤3GiB mục tiêu, hostavailable và swap recorded. Nếu thiếu quality/resource, giữ offline và nêu nguyên nhân trước thử4B; không tự chạy2models cùng lúc.

### S4 — Bounded asynchronous service và lifecycle

**Files:** create `rooms/{worker,service}.py`, `tests/test_room_label_worker.py`, `tests/test_room_label_service.py`.

- [ ] RED fake-clock/fake-backend tests: max32pending/1inflight, latest-per-room replacement, fairness32rooms, debounce3s từlastdispatch không reset khi graphupdate, crash/cancel/5s-live-timeout, run reset, removed/split/reparented room, full-key invalidation, cache exact key only, all responses stale under highrevisioncadence.
- [ ] Run `.venv/bin/python -m pytest tests/test_room_label_worker.py tests/test_room_label_service.py -q` RED.
- [ ] Implement separate process, bounded queues/cache(history cap128entries/8MiB; evict with status), statuses from existingcontract; service doesnot block control/publisher; outstanding jobs canceled atclose≤2s thenterminate/reap. Identity wrapper prevents crossrun even if same context hash.
- [ ] Stable-display2consistent distinct evidence hashes only while assigned object IDset/parentlinks exactmatch; duplicate hash not secondvote; split/merge resets. New result proposed allowed without false stabilization. Cache no crossrevision reuse v1.
- [ ] GREEN; saturation/crash fixtures prove graph/control callbacks unaffected; stale/history vs available distinguish. Deliverable service correctness; no native live claim yet.

### S5 — Opt-in room UI và short shadow demo

**Files:** modify `runtime/{configuration,launcher}.py`, `visualization/{publisher,desktop}.py`; create `tests/test_room_label_ui.py`, `tests/test_room_label_runtime_isolation.py`.

- [ ] RED label update during scene reset/picking; unavailable/evidence-not-reviewed badge; same semanticlabel2roominstances; stale result onlyhistorical; rooms noobjects show insufficient; label onmergedgeometry has qualitywarning. Run `.venv/bin/python -m pytest tests/test_room_label_ui.py tests/test_room_label_runtime_isolation.py -q` RED.
- [ ] UI room ID + inferredlabel/proposed-stable status, supporting canonicalobjectIDs/categories, revision/model/prompt, evidence tier; click highlights native members. Không gắn confidencepercent hoặc sửa nativeRoomname thànhID mới. Khi job stale liên tục, hiển thị historical snapshot và pending, không bỏ revisioncheck.
- [ ] Add disabled-by-default config/launch plumbing, preflight modelhash/budget. No call/awaitservice inside capture/control or synchronouspaint; image evidence unavailable vẫn nêu rõ.
- [ ] GREEN plus existing UI/contract tests touched (list exact files from repository, no blanket claim). Chạy replay control-isolation OFF/ON trước live; so graph geometry hashes/IDs/membership identical trên cùng recording.
- [ ] Nếu offline quality/resource đạt: paired OFF/ON30–60s shortshadow with currentmotionguard; record freshness + movingcontrols/trajectory, localmap p95, RAM/swap, graphrev age, discardedjobratio, UI rendering proof. Usability gate:≥10completedjobs/≥2rooms,≥50%allcompletedjobs (timeout/invalid vẫn trongdenominator) attach hợp lệ exact-current key; labelavailable/abstention báo riêng. Thiếumẫu/stalequánhiều→inconclusive/notready, giữoffline/history, không nới revisioncheck. Stop criteria trong spec; fail thì keep offline, không giảm guard.

### S6 — Semantic evaluation, handoff và quyết định

**Files:** `tools/evaluate_room_labels.py`, extend `evaluation/room_labels.py`; create `tests/test_room_label_evaluation.py`; `docs/results/room-slm-pilot-<date>.md`, update status.

- [ ] Trước tuning freeze evalmanifest: physicalroominstance→reference label(s)/unknown, regions/evidence annotation hash, scene dev/heldout, eligible support, predictedsnapshot/context hashes. Mục tiêu≥12physicalrooms/≥3scenes; thiếu thì report smallpilot, không nhân samples bằng revision.
- [ ] RED toy oracle: perfect/allunknown/wrong confident/missingreference/mixed GT/manyrevisionssameroom/geometrymerge/split/novisualevidence/truncatedcontextabstention; verify separate per-room/endtoendscores and abstentiondenominators. Run `.venv/bin/python -m pytest tests/test_room_label_evaluation.py -q` RED.
- [ ] Implement evaluator, aggregate byphysicalroom/scene, labelset-supportedmacroF1/confusion/coverage/selectiveaccuracy, hallucinatedsupport/invalidrate/flips/resource; compare versionedrules and1.7B onidenticalcontext and comparablecoverage. Evaluate heldout once after promptfreeze; do not retune then callitheldout.
- [ ] GREEN; output source/prediction/reference hashes and skippedreasons; compare model/case tradeoffs, no promise statistical significance on12rooms. Gate proposed≥80%accuracy at≥50%coverage andnotworse rules atmatchedcoverage forreviewedeligible subset; insufficient support means inconclusive, notpass.
- [ ] Deliver report including snapshotgallery, failure cases from00805, known sparsehallway/openplanlimitations, no geometrywrites/staleattachment accepted; staged implemented/correctness/runtime status. No training/4Bdownload/defaultpromotion implicit.

## Bàn giao exploration

Đồng đội giữ frontier/movement/coverage task riêng, không cần SLM và không sửa geometry lock. Handoff cần navigation/config hash, actualbodytrajectory/crossing/coverage và freshness metrics. SLM dùng recording cố định để loại thay đổi exploration ra khỏi so sánh; sau đó live integration pin cả hai version. Không gửi tin nhắn cho đồng đội hoặc tạo thread nếu người dùng chưa giao.

## Thứ tự và mốc dừng

S0→S1→S2→S3 offline quality/resource→S4→S5; S6 annotation protocol chuẩn bị cùng S1, finaleval sauS3 và trướcliveS5. Không cần S5 để kết luận1.7B có ích haykhông. Nếu0evidence/emptyobjects thì task cần cải thiệnsemanticcapture, không đổiprompt để đoánphòng.
Một workerLuna xhigh có thể làm S1/S2 sau mainkhóa contract; mainlo sharedschema/tíchhợp, review các đầu ra. Không benchmark song song với simulator/detector/nativecost. Chỉnângmodelagent khi có finding cụ thể.

**Lượt hiện tại:** viết design/plan và manifest hash; chưa thực hiện S0 runtime inventory đầy đủ, chưa model/runtime asset, chưa test code hoặc inference. Review plan trước khi giao implement; triển khai không tự cho phép training/download lớn.

## 2026-11-08: authorized debug rollout amendment

User explicitly authorized asynchronous runtime and snapshot UI in debug/shadow while evidence quality continues, without model upgrade. This permits an opt-in debug profile before semantic-quality gates; it does not waive them or promote defaults. Implemented/report: `docs/results/room-slm-async-debug-2026-11-08.md`. Live labels are not yet validated: cold-context timeouts and object-image association remain open. Geometry/control remain independent.
