# Hydra multi-scene geometry baseline và local-map audit

Bắt đầu2026-11-07, hoàn tất các phép chạy2026-11-08 trong Kiet_branch2 HEAD62f16fc. Đây là task bốn bước được giao; không triển khai SLM, không đổi mặc định.

## Trạng thái thực hiện

- **Implemented:** capture/replay/native seed audit/temporal metrics/overlay và phép đo CPU dưới `runs/hydra-objectnav/`. Product source, installed Hydra, private stable DSO, navigation policy, source calibration và guard300ms/horizon100ms giữ nguyên. Thêm một profile thử nghiệm2Hz, opt-in.
- **Correctness-verified:**97focused tests passed11.47s/exit0;61replay/goal-feedback tests passed5.96s/exit0, không trùng file với nhóm97. Không fullsuite. Verifier kiểm tra158capture packets, calibration, selected source/hash, native graph/source prefix và source locks exit0.
- **Runtime-validated:** hai scene capture thật; bốn fresh native OFF/ON replays; thêm exact23-input00805 replay; CPU replay và ba live60s. Accuracy trên scene mới **pending human annotation**. Không tuyên bố movement/freshness dài hoặc toàn bộ ObjectNav đạt.

## 1. Hai scene mới, cấu hình cố định

| Scene | Mục tiêu quan sát | Full capture | Selected native inputs mỗi mode | Final places / room nodes OFF=ON |
|---|---|---:|---:|---:|
|00806|Hai vùng có nội thất qua ô cửa/lối nối; out-and-back5.902m|94|48|354 /3|
|00807|Open footprint có các opening lân cận; out-and-back2.807m|64|33|384 /2|

Điểm và pose là RGB-D/camera+AgentState thực của Habitat. Source-Y range gate≤.25m, khoảng cách capture≤.4m, yaw step≤30°, timestamp thật cách≥1.05s để khớp full_update_separation1s. Actual min spacing1.0887s/1.0854s, calibration ID ổn định, mount drift1.8e-15/5.96e-8. Navmesh chỉ chọn/check đường chụp offline; đặt pose trực tiếp, **không phải actuation hay bằng chứng robot tự đi được đường này**.

Cấu hình giữ compression.5m, node_merge.25m, component min3, room min10, TSDF.1m, stable DSO9364ca…; cùng DSO/config/semantic input, chỉ toggle policy. Semantic geometry-only: valid=unknown_static0, invalid=1 qua production rasterizer; empty batch completion unknown. Không dùng detector/semanticGT, không có object/evidence claim cho hai recording này.

Ruling trước kết quả native: smooth trajectory cần94/64captures; chọn đều mỗi2frame và frame cuối, giữ nguyên packet/time/pose, để giảm xử lý redundant turns. `selected-inputs.json` đóng băng tập48/33 trước native; cùng tập và cùng serialized HydraFrame hash/prefix ở OFF/ON. Không chọn frame dựa trên kết quả phòng. Bản đồ annotation chỉ dùng các selected frames; all-frame capture/map vẫn giữ.

Capture-only report: [/home/kiettran05/Desktop/test_Room_segmentation/NeuSymNav/.runtime/worktrees/Kiet_branch2/runs/hydra-objectnav/B1-multiscene-20261107/capture-report.md](/home/kiettran05/Desktop/test_Room_segmentation/NeuSymNav/.runtime/worktrees/Kiet_branch2/runs/hydra-objectnav/B1-multiscene-20261107/capture-report.md). Chỉ provenance của invocation probe00806 bị ghi đè nhầm trước fix; có bản reconstruction ghi rõ mất exact old script hash/start time. Full capture invocation, packets, calibration, chosen route và bốn native command/hash không bị mất. Không giấu hoặc đưa thử lỗi vào pass.

## 2. Every-revision geometry và temporal audit

162/162selected inputs được chấp nhận qua bốn workers. XYZ/clearance/weighted edges/input prefix khớp81/81paired revisions. Stock native RoomFinder reconstruction khớp assigned sets và partition81/81, độc lập việc renumber room IDs.

Mỗi revision có `.sparkdsg`, actual membership, clearance/cạnh, native OFF filtration/raw components/seeds/post-NEIGHBORS; ON effective components được tái dựng độc lập ở **actual logged effective threshold**, kiểm count với native decision và kiểm raw implementation với native OFF. Không gọi raw fresh clustering là actual ON khi policy hold threshold. SVG ON hiển thị actual ON membership và nêu rõ seed reconstruction.

| Scene | OFF split / merge | ON split / merge | Revision OFF/ON khác partition | Max unassigned OFF / ON |
|---|---:|---:|---:|---:|
|00806|10 /12|4 /4|9/48|10 /10|
|00807|0 /2|0 /2|5/33|8 /3|

Đây là overlap events trên stationary observed place IDs (≤.25m displacement, overlap≥2points và20%), **không phải physical room lineage hoặc accuracy**. Một điểm đổi membership cũng có thể làm pair partition thay đổi. Final partitions hai mode giống nhau. Số3/2rooms không chứng minh các vùng mục tiêu được tách đúng; open-footprint có opening lân cận, không giả định toàn bộ map chỉ có một phòng.

- Per-revision data/CSV/overlays: `/home/kiettran05/Desktop/test_Room_segmentation/NeuSymNav/.runtime/worktrees/Kiet_branch2/runs/hydra-objectnav/B1-multiscene-20261107/audits/00806/` và `00807/`.
- Final native membership: [00806](/home/kiettran05/Desktop/test_Room_segmentation/NeuSymNav/.runtime/worktrees/Kiet_branch2/runs/hydra-objectnav/B1-multiscene-20261107/audits/00806/final-membership.png), [00807](/home/kiettran05/Desktop/test_Room_segmentation/NeuSymNav/.runtime/worktrees/Kiet_branch2/runs/hydra-objectnav/B1-multiscene-20261107/audits/00807/final-membership.png).
- Annotation-neutral maps: [00806](/home/kiettran05/Desktop/test_Room_segmentation/NeuSymNav/.runtime/worktrees/Kiet_branch2/runs/hydra-objectnav/B1-multiscene-20261107/recordings/00806/annotation-map.png), [00807](/home/kiettran05/Desktop/test_Room_segmentation/NeuSymNav/.runtime/worktrees/Kiet_branch2/runs/hydra-objectnav/B1-multiscene-20261107/recordings/00807/annotation-map.png). Registration JSON đóng băng bounds/pixels/hash; RGB-D height band floor+.35..2.2m chỉ để thấy wall/object rõ, không đổi raw data hoặc UI floor cloud. Native overlay là XY projection của tất cả height, không chứng nhận navigability.

## 3. Immediate cause trên recording00805 mới

Exact23-input OFF replay có XYZ/clearance/parents/prefix khớp recording OFF cũ23/23; native seed reconstruction partition khớp23/23. Trong13mixed revisions:

- OFF4revision5,7–9: mọi điểm core phòng tắm ở/bên dưới clearance threshold.
- OFF9revision10–18: support vượt threshold chỉ thành component size1;17–18 là hai singleton riêng, bị min3 loại.
- ON ở actual effective threshold:3clearance-eliminated,10component-size-pruned; independently computed CC/raw native parity23/23, selected seed counts khớp native log.

Không có separate bathroom seed sống sót ở những revision mixed này. Bằng chứng chỉ ra mất seed **trước NEIGHBORS**, không phải hai seed phòng tắm/hành lang hợp lệ rồi bị clustering gộp. Chưa tách hết nguyên nhân sâu hơn giữa observed coverage, compression/merge và lựa chọn filtration; không hạ min3 hoặc chỉnh threshold để ép hai phòng.

Artifacts `/home/kiettran05/Desktop/test_Room_segmentation/NeuSymNav/.runtime/worktrees/Kiet_branch2/runs/hydra-objectnav/B1-newgeometry-20261107`: support-attribution/on-support-attribution, per-revision native JSON+SVG, seed-attribution.png, provenance hashes. Human partial cores00805 được dùng offline trong cùng registered world; không phải full-roomGT.

Native object→place→room chain của run có detector00805 cũng được xuất theo23graph revisions. Final5objects có room ancestry; **không chứng minh association/image-mask provenance đúng**. Newscene unknown-static captures không dùng làm object label/evidence benchmark.

## 4. CPU/GPU, local-map cost và live thử nghiệm

Original300s:903map stages đều bắt đầu với depth age≤300ms (entry max277ms);250cross300ms trong lúc dựng map. Early stale check ở đầu sẽ không bỏ được map nào ở trace này. Khi đã late, path follower p95~.135ms và guard~.063ms nên short-circuit sau map không tiết kiệm đáng kể.

Isolated12spread×3: warm p95112.61ms; projection/clipping/setup44.33ms, raycast69.02ms, coverage1.56ms (nested scopes, **không cộng quantiles**). Actual36Numba/0Python. Top8worst-live source frames (live630–815ms) replay riêng×3 cho warm p9570.66ms.10/12uniform sources join được live stage theo identity/time; median paired live-vs-isolated delta150.5ms, ratio2.73. Không suy toàn bộ gap là detector causality.

Sau reboot, clock domain đổi và forensic world replay bị future-source guard từ chối đúng contract. Giữ log exit1; chuyển các trial mới sang **existing ReplaySession**, fixed persistent replay domain/start1e9. Pixels/pose/K và relative intervals giữ nguyên; full snapshot parity so với baseline mới cùng replay domain. Không feed forensic clock vào live hoặc nới guard. Fresh isolated baseline44.21ms thuộc boot/load context khác, không trộn làm A/B với baseline112.61ms trước reboot.

World workers4→1→4→1: local p9558.77/57.55/58.91/57.61ms, world p95~42–43ms ở4workers thành~71ms ở1worker. Full local vote+snapshot parity144samples; world parity ở các cross-mode comparisons. Lợi ích nhỏ, world chậm hơn: không đổi default.

Counterfactual local workers1→2→1→2 dưới world4: local p95115.71/54.75/74.24/82.29ms, full masks/snapshots match nhưng lợi ích không lặp lại: không thêm production worker knob hoặc đổi default.

Fresh device probe trong đúng detector interpreter: OpenVINO available_devices=[CPU], `/dev/dri` absent; Torch2.7.1+cpu intra1/inter8. Đây là exposure của môi trường hiện tại, không kết luận máy vật lý không có UHD. Không cài driver/model hay chạy GPU inference.

### Ba live60s cùng boot, giữ policy/guard

Chỉ thay existing `runtime.world_navigation_hz` cap; local map vẫn1worker, raycast/world4workers, primary.5Hz/navigation10Hz, room backend/config và source calibration không đổi. Qt offscreen, không physical desktop/picking proof. Thứ tự không randomize, chỉ một run mỗi mode và trajectories phản hồi khác nhau; đây là exploratory evidence, không statistical/general guarantee.

| Case | Freshness misses / all control results | Local map p95 | Observed body lower bound | Executed results | World intent unavailable | Native revision |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 38/210 = 18.10% | 272.23 ms | 0.698 m | 148 | 19 | 7 |
| world1hz | 4/449 = 0.89% | 138.48 ms | 0.061 m | 33 | 411 | 3 |
| world2hz | 28/264 = 10.61% | 240.39 ms | 0.936 m | 162 | 62 | 7 |

Freshness definition giữ nguyên từ audit trước; denominator đối chiếu control-invocations, deadline skips giữ riêng trong JSON. Không dùng tỷ lệ thấp lúc đứng yên làm thành công.1Hz bị từ chối:411unavailable intents,47world planner blocked-goal decisions, không có confirmed goal failure. Watchdog hiện reset khi observation gap>1s; fixture fresh maps1.01s reset count=1 mãi,0.5s đạt6revisions và bỏ đúng failed target sau2.5s. Cơ chế được tái hiện độc lập; không sửa movement/watchdog trong task này.

2Hz giảm local p95 và freshness miss trong mẫu, observed distance tăng, nhưng **10.61% chưa đạt5%**; chưa chạy120/300/600 để nghiệm thu. Cả ba recording/export/shutdown sạch, missing_command_proofs0; strict actuation.complete=false và certified_distance=null, native_runtime_validated=false — không nâng observed distance thành certified hoặc fullruntime pass.

Profile thử nghiệm opt-in: `/home/kiettran05/Desktop/test_Room_segmentation/NeuSymNav/.runtime/worktrees/Kiet_branch2/configs/demo-00805.hydra-world2hz-room-stability.experimental.local.json`; bytes giống profile2Hz đã chạy. Chỉ thêm runtime.world_navigation_hz=2.0; default cũ giữ nguyên. Không khuyến nghị1Hz trước khi giải quyết compatibility của failure-watch. Không có product source/library/guard edit trong đợt này.

```bash
cd /home/kiettran05/Desktop/test_Room_segmentation/NeuSymNav/.runtime/worktrees/Kiet_branch2
NEUSYMNAV_HYDRA_DEMO_CONFIG="$PWD/configs/demo-00805.hydra-world2hz-room-stability.experimental.local.json" \
QT_QPA_PLATFORM=offscreen bash tools/run_hydra_map_demo.sh 00805 120 runs/hydra-world2hz-00805-120s-NEW
```

Đây là lệnh thử tiếp, **chưa được chạy** trong task. Output phải mới; nếu chạy desktop thì bỏ offscreen theo display thật.

## Artifacts, verification và phần chưa chứng minh

- Main ledger/plan/verification: `/home/kiettran05/Desktop/test_Room_segmentation/NeuSymNav/.runtime/worktrees/Kiet_branch2/runs/hydra-objectnav/B1-next-baseline-20261107`. `verify.py` exit0;97+61tests exit0, không fullsuite. `git diff --check` exit0;21owned untracked source/docs/profile files kiểm whitespace riêng,0issues. Independentcost verifier exit0 kiểm288local/world sample hashes và3completedlive runs.
- CPU raw/commands/exits: `/home/kiettran05/Desktop/test_Room_segmentation/NeuSymNav/.runtime/worktrees/Kiet_branch2/runs/hydra-objectnav/B1-localmap-cost-20261107`; `cost-summary.json`, `live60-comparison.json`, three source-bound stage profiles, device JSON, failed future-clock trial và deterministic cadence-watch fixture đều giữ lại. All worker/default tuning rejected or opt-in; không commit/push/sibling edits.
- Pending: human room cores/openings trên2scene mới để đo cross-region merge, fragmentation và membership accuracy. Hiện chỉ có structural/temporal audit, không fabricated GT scores.
- Pending: stable low-tail live performance ở run dài; detector full-load attribution/process isolation chưa hoàn tất.2Hz là hướng thử có số đo, chưa default promotion.
- SLM readiness không đòi segmentation hoàn hảo hoặc mọi run freshness<5%. Sau khi có annotation để chốt baseline/failure cases, có thể bắt đầu text-only label inference có abstain, supporting objectIDs và graph revision/hash; không dùng nhãn SLM chứng minh geometry đúng. Object association/evidence còn phải kiểm tra riêng.
