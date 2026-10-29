# Trạng thái NeuSymNav

Cập nhật: 2026-10-29.

**Checkpoint mới nhất — demo640×480 / YOLOE-26m:** đã đổi demo mặc định sang
`configs/p10/demo-yoloe26m-640x480-00861.json`, actual primaryRGB và depth640×480,
imgsz640, MobileCLIP2, confidence0.25; depth điều hướng giữ240×180. Môi trường
riêng `.runtime/detector26/bin/python` dùng Ultralytics8.4.24 khớp metadata
checkpoint, tái dùng Torch/CUDA; môi trường cũ giữ8.3.221. Người dùng đã cho phép
cài gói nhỏ; không tải model/dataset mới, không training.

Implemented / scoped correctness-verified / component-runtime demonstrated:
100focusedCPU pass0, K/calibration native và nonempty masks640×480 khớp nguồn,
59prompt embeddings khớp upstream bitwise, actualrecipe/seed/config binding pass0,
preflightreadytrue0,202siblinghashmatch0. 100Python production files không đổi;
không tuyên bố đã chạy lại fullsuite1388 cho môi trường mới.
Native30s incomplete vì rawquota380/381; giữ nguyên thất bại. Native20s completed,
raw292/292/resourcescomplete/cleanupclean,4detector commits và object evidence thật.
**Chưa đạt10Hz:** mean7.388Hz,p95165.476ms,p99173.716ms,142/142intervals>100ms.
Chưa chứng minh confidence/accuracy tăng. Defaultdemo20s để vừa quota1GiB;
không nới quota,TTL,clearance hay proof. P10 vẫnin_progress.
[Commands/exits/evidence/limits](../runs/yoloe26-640x480-20261029/report.md).
Chạy `bash tools/run_realtime_demo.sh 20`. Các lệnh/số đo bên dưới là lịch sử.


**Checkpoint trước — UI theo NewOH3DSG:** implemented / correctness-verified;
cửa sổ ưu tiên2160×1350 (+50% mỗi chiều, tự vừa màn hình), chữ lớn, focus từng
panel, detector observation có box/label/confidence/mask và tab Live RGB riêng.
Exact processed source + SHA/geometry/clock binding, immutable bounded DTO, old
wire compatibility; không ghép mask cũ lên ảnh mới. Robot/trail/FOV và ACK giữ nguyên.
Fullgate hiện tại **1.388 CPU passed /3native deselected /exit0**, package0,
preflight readytrue0,202siblinghashmatch0. Scoped review SolHigh ACCEPT51tests0;
graph-spacing follow-up ACCEPT10tests0. 100sourcefiles stable. Preview là dữ liệu
native đã ghi, STALE; publication smoke là CPU fixture với cửa sổ Qt con thật.
**Chưa đo native/realtime/desktop timing mới trên UI này; P10 vẫnin_progress.**
[Report/commands/exits/artifacts](../runs/ui-new-reference-20261029/report.md).
Demo: `bash tools/run_realtime_demo.sh 60`.


**Checkpoint trước — realtime:** opt-in profile đã implemented và main correctness-verified
(1.379 CPU tests, fault harness 4, native DuDe 3, packaging và 202 source hashes đều exit 0).
Native preparation 00861 × seeds 0/1 × 30 s: completed 2/2, mean control
11,181 / 10,503 Hz; interval p95/p99 124,653/135,205 và 131,239/146,490 ms.
Deadline >100 ms: 80/327 (24,46%) và 114/306 (37,25%). **Chưa đạt đều 10 Hz**;
không tuyên bố hard realtime hoặc semantic graph 10 Hz. TTL/RGB-D/clearance/proof giữ nguyên.
P10 vẫn `in_progress`; independent Sol High review còn chờ do account usage limit,
chưa có final frozen two-scene campaign / đầy đủ useful-demo và assigned-membership evidence.
Chi tiết và lệnh/exit/artifact: [báo cáo](../runs/realtime-fix-20261028/report.md).
Demo: `bash tools/run_realtime_demo.sh 60`; preflight ready true / exit 0.



**Tóm tắt hiện hành:** P00–P09 implemented/correctness-verified, P10 chưa nghiệm thu. Demo hiện tại là YOLOE-26m/640×480/20s, chưa đạt10Hz và chưa chứng minh tăng chất lượng. Xem checkpoint đầu trang; các số thấp-resolution và lệnh60s bên dưới không chứng nhận cấu hình mới.

## Quyền và checkpoint hiện hành

- Người dùng đã yêu cầu **thực thi toàn bộ kế hoạch gộp trong docs/** ngày 2026-10-27. Đã triển khai P00–P09 và chạy các lượt native preparation; hai folder nguồn chỉ đọc. Không training/tải lớn/extension/commit/push/publish.
- Chính sách model đã được người dùng chỉ định: main GPT-6.1 Sol Medium; Luna xhigh; Sol theo độ quan trọng; cấm Astra. Chi tiết trong [điều phối](agent-orchestration.md).
- Thực thi theo thiết kế và dependency P00–P10; evidence và quyết định nằm ở [execution ledger](execution-ledger.md). `.git` hiện là thư mục rỗng read-only, không phải repository hợp lệ; dùng hashes/logs làm checkpoint, không tự tạo Git history.

## Tiến độ thực thi

| Task | State | Evidence | Bước kế |
| --- | --- | --- | --- |
| P00 kiểm kê/provenance | correctness_verified | `runs/p00-main/`, `runs/p00-inventory/`, [report](../runs/implementation/p00-report.md) | Host 3.12 khóa; runtime pending |
| P01 contracts/geometry | correctness_verified | `runs/p01/`, [review](../runs/p01/scoped-rereview.md) | Schema v1 locked; CPU135 pass tổng suite |
| P02 sensor/replay | correctness_verified | [report](../runs/implementation/p02-report.md), `runs/p02/` | Native capture blocked: thiếu Habitat |
| P03 navigation | correctness_verified | [report](../runs/implementation/p03-report.md), `runs/p03/main-hash-verification.json` | Main37 focused pass; native bootstrap/5cm tolerance pending |
| P04 object core | correctness_verified | [report](../runs/implementation/p04-report.md), [review](../runs/p04/scoped-rereview-round2.md) | Crash/retry fixes reviewed; native detector pending |
| P05 appearance | correctness_verified | [owner review](../runs/p05-review/review.md), [IPC review](../runs/p05-ipc-review/scoped-rereview.md) | Lifecycle/backpressure fixes accepted; default off; model inference pending |
| P06 region/hierarchy | correctness_verified | [fix report](../runs/p06/fix-round1/report.md), [review](../runs/p06-review/fix-round1/scoped-rereview.md), `runs/p06-native/` | 38 focused + independent oracles pass; native synthetic only, live quality pending |
| P07 runtime/verification | correctness_verified | `runs/p07-runtime/`, `runs/p07-verification/`, `runs/p07-ipc/` | IPC + runtime/verifier scoped review ACCEPT; main453CPU pass +6independent probes; native pending |
| P08 UI | correctness_verified | [report](../runs/implementation/p08-report.md), `runs/p08/` | Main10 focused/offscreen + P07 ACK integration pass; P09 process transport và display thật pending |
| P09 packaging | correctness_verified | `runs/p09-launcher/`, `runs/p09-cli/`; P07/P08 gates đạt | Review ACCEPT; main520CPU +source-only +12independent probes pass; native pending |
| P10 validation | in_progress | `runs/p10-native-preparation/`; latest scoped manifests/reviews ở checkpoint dưới | Planar A implemented; runtime12 full gate1305CPU0 + independentACCEPT. Native preparation completed with detector/regions, useful/membership gates incomplete. Latest translation preflight207focused0/259CPUproofs valid; independent review pending usage limit. No frozen4slotcampaign. |

Checkpoint tiếp tục: worker P03/P04 lượt trước không còn hoạt động và chưa tạo implementation. Đã giao lại `p03_navigation_resume` / `p04_objects_resume` (Sol High), ownership tách biệt. Main chạy lại CPU suite: **160 passed, exit 0**; **190/190 source hashes** nguyên vẹn. Evidence: `runs/resume-20261027/`. Chi tiết interpreter thực tế và đề xuất trước khi cài ở [runtime environment proposal](runtime-environment-proposal.md); chưa cài môi trường mới.

Gate P03/P04: main chạy suite tổng `.venv/bin/python -m pytest tests -q -m 'not native'` → **228 passed, exit 0**, log `runs/resume-20261027/integrated-p03-p04.log`. Nguồn hiện có **194 selected records**: bổ sung bốn source/reference files được pin tại P03/P04; 190 hashes trước đó vẫn khớp.

Hoàn thành gate implementation: **10/11 task** (P00–P09). Correctness verified: **10/11** (P00–P09). Native/runtime: DuDe source-built và candidate đã chạy request synthetic hữu hạn, **chưa có pipeline native được nghiệm thu**. Không dùng số milestone của NewOH3DSG hoặc tests của 3DSG thay cho các số này.

Checkpoint P05/P06 tiếp tục: owner appearance review độc lập chấp nhận4file snapshot,49 focused +11 probes + source AST oracle; encoder IPC có lỗi blocking write đã main tái hiện và đang hoàn tất regression/fix. Main chạy riêng appearance contracts hiện tại17 pass exit0 (chưa thay scoped IPC review). P06 reviewer tái hiện polygon tự cắt vẫn publish fresh, protocol bool/float được nhận và descendant còn sống sau timeout; main xác nhận polygon bug. Native closure89files build/3tests/synthetic smoke đã pass;5source metadata paths bị lặp basename đang sửa. Các lần dispatch gặp usage limit/network permission được ghi nhận; chưa bỏ qua review hay mở P07 trước gate.

Checkpoint mới: P06 fix-round1 đã được reviewer độc lập ACCEPT (19hashes/11sources;38focused;120 source guard/tracker +200 source membership +1000 analytic cases). Native closure5paths đã sửa, main kiểm89source/vendorhashes +native3tests pass. Main suiteCPU303pass3deselected exit0 `runs/resume-20261027/integrated-p05-p06.log`;source197/197khớp. P05 IPC còn race concurrentclose/startup tái hiện main qua `runs/p05-ipc-review/close_startup_race.py`;writer đang sửa, gatechưađóng. P08 đã giao riêng vì dependency P06 đạt; P07 chờ P05, không bỏ review.

Gate P05 cuối: lifecycle fix được reviewer độc lập ACCEPT (`runs/p05-ipc-review/scoped-rereview.md`),20focused+27adversarial+originalrace+2pending probes/sourceAST pass; shutdown pending không coi clean. Main69focused pass và suiteP00–P07dependencies **305pass,3deselected,exit0** (`runs/resume-20261027/p05-p06-post-lifecycle.log`), chủ ý bỏ hai fileUI đang phát triển khỏi lần gate này. P07 đã giao sau gate cho3SolHigh writers riêng. P08 offscreen7tests pass theo worker; main chưa đóng gateUI, display thật chưa mở được.

Checkpoint P07 hiện hành: tiếp tục đúng hai scope runtime/verifier còn thiếu report; IPC đã có report và main54 test pass exit0 (`runs/p07-main/ipc-focused.log`), đang review Sol High độc lập. Central source inventory **200 selected records**, toàn bộ199hashes trước đó khớp. Chưa mở P09/P10; không cài thêm môi trường hoặc tải tài sản.

## Mẫu cập nhật sau mỗi task

```text
Task / owner / model-effort:
State: in_progress | implemented | correctness_verified | runtime_validated | blocked
Source snapshot / files changed:
Command / interpreter / exit code:
Evidence path / profile actual / scene-seed:
Review findings và disposition:
Quyết định khác kế hoạch + người duyệt nếu cần:
Blocker / phần chưa kiểm chứng:
Bước độc lập tiếp theo:
```

## Kiểm tra bộ tài liệu — 2026-10-27

- Có 6 tài liệu Markdown; đã kiểm tra links nội bộ, code fences và đủ P00–P10 bằng script Python 3, exit 0. Chưa có product tests để chạy.
- Builder review độc lập bằng `gpt-6.1-sol` / `high`: đã xử lý 4 findings về commit empty batch/negative evidence, NavMap→DuDe raster, bootstrap depth/floor datum và pinned map revision. Reviewer xác nhận không còn blocker trong các phần đã sửa.
- Model policy được reviewer đối chiếu với yêu cầu người dùng. Các điều kiện native/runtime vẫn là gate thực thi tương lai, chưa được chứng minh bằng việc review tài liệu.
- Bước tiếp theo: người dùng đọc kế hoạch; khi có yêu cầu triển khai, main chạy P00. Prompt bắt đầu nằm ở mục 7 của tài liệu điều phối.

Gate P07/P08 cuối: IPC review ACCEPT (`runs/p07-ipc-review/fix-round1/scoped-rereview.md`), runtime/verifier review ACCEPT (`runs/p07-integrated-review/fix-round1/review.md`). Main453CPU pass/3native-deselected exit0; fresh6independent probes pass0 (`runs/p07-main/runtime-fix-independent-confirmation.log`); source200/200khớp. P08 correctness gồm typed verifier/lifecycle, offscreen và runtime ACK; process transport thuộc P09, real display chưa runtime-validated. P09 được mở sau gate này.

Checkpoint P10 mới nhất: main `.venv/bin/python -m pytest tests -q -m 'not native'` → **546passed,3deselected,exit0**,50.32s; source-only verifier→exit0 (`runs/p10-main/confirmed-exits.json`, `cpu-confirmed.log`, `source-only.log`). Focused26pass/fault4pass/nativeDuDe synthetic3pass đều exit0; native pilot evaluator expectedexit1:1scene×2seed,0attempted/0completed/2missing. P10 correctness gate chưa đóng vì review SolHigh độc lập còn pending. Main sửa điều kiện chờ trong một regression P09 sau deterministic admission-race probe; runtime/TTL không đổi. Central inventory202selected source records, prior200 giữ nguyên. Chưa cài môi trường, tải tài sản hay chạy native campaign; xem acceptance-report.md và runtime-environment-proposal.md.

P10 evaluator fix-round1 scoped ACCEPT: independentSolHigh45focused+8original+6newboundary probes pass0,43/43finalmanifest records/refs before-after match. Main fresh565CPU/3deselected exit0 (52.51s),45focused+8originalpass0,source-only0,pilotexpected1; evidence runs/p10-main/fix-round1/exits.json and runs/p10-review/fix-round1/. This closes evaluator findings only. P10 overall remainsin_progress: executed native seed ACK/provenance and measurement instrumentation need implementation under existing full-plan authorization; separate snapshot/review required. Native dependencies/calibration/realusefuldemonstration still missing, no runtime acceptance or installation.

P10 native-readiness slice1 đang triển khai (SolHigh, một writer): seed/source ACK trong configuration/launcher/sensor client/worker, hai test mới và hai profile `configs/p10/baseline-seed-{0,1}.yaml`. Main khóa contract bổ sung tại runtime-measurements-contract.md: giữ v1 immutable, suite/export v2 cho evidence mới, bounded telemetry ngoài control. Profile v1 thiếu seed vẫn đọc được nhưng không được suy có executedseedproof. Chưa có native capture/inference; checkpoint565CPU là snapshot trước slice này, không tự áp cho code đang sửa.

Seed/source ACK slice correctness scoped ACCEPT sau fix deadline: manifest c413e88308124093a1b581e2a649d4ce7071c557505eb11f98c47e18fb951d3b; reviewer103fresh tests pass0 và36/36before-after hashes. Main independent5probes+98focusedpass0 (`runs/p10-main/seed/fix-round1/`); originalexpiredACK RED retained. Primitives frozen riêng (measurements/resources +2tests),35focusedpass0 mainconfirmed; manifest1ceb67a635aef43bce0b7e022edadc454f800e1693868a748199d5cb7878715c; reviewerSolHigh mới đang kiểm (`runs/p10-readiness/primitives-review/`). Chưa tích hợp collector/resource/actuation/measurementartifact/exportv2/suitev2; main đang chạy toànCPU không bỏhai primitivefiles sau khi cảhai writers đã freeze (`runs/p10-main/readiness-base/`). Các con số595excluded/565trước đó không phải gate cuối của snapshot mới.

Primitives fix-round1 scoped ACCEPT:48focused+25original+17newboundary pass0,6/6before-after working/copy hashes; main fresh42independent+boundary pass0 (`runs/p10-main/primitives/fix-round1/independent-confirmed.log`). Actuation checkpoint do main triển khai vì worker chạm account usage limit sau khi đã lưu checkpoint trước. Frozen manifest34c76da5537f5849c46916975ae6c5f5a59fb25b254a3f0112cb918db6af4947; fresh122focused,668CPU/3native deselected,source-only exit0 (`runs/p10-readiness/actuation/exits.json`). Review SolHigh đang kiểm riêng, chưa nghiệm thu. Main độc lập thêm gpu_provider.py/tests CPU fake executable, chưa tích hợp hoặc query device thật. Collector/resource/actuation/export/suite v2 chưa nối; P10 tổng thể vẫnin_progress, không nativevalidated.

Checkpoint wiring mới (main writer): optional observer nối trước Pipeline threads, capture/infer-return/commit-return/admission/control, bounded body/proof records; sampler trước sensor/model startup và partial failure artifact; manifest v2 +16MiB/quota/incomplete policy. Frozen SHA5665eefc552da5438b7be08339e803cb73d4a3f11debad9de00adc971b9b45fa (`runs/p10-readiness/wiring/manifest.json`), fresh698CPU/3native deselected0,96focused0,source-only0; độc lập review tại wiring-review đang mở. Actuationfix vàGPUproviderfix đã scopedACCEPT, refs source giữ nguyên. Evaluator/suite v2 chưa nối; P10 chưa đóng và native vẫnblocked. Main chỉ sửa NEW evaluator module/tests trong lúc runtime snapshot review, không sửa source frozen.

Checkpoint wiring fix-round2 scoped ACCEPT: main tái hiện original2fail và raw-recorder-pending1fail; sửa admission ACK/rejected và cleanup sensor/UI/resources/raw recorder trước measurement finalization. Independent30freshpass0,31/31before-after hashes; manifest aa19046d7a004348896cd99239b85a2c51f84d813660cfea7bfa64afa87b998d, report runs/p10-readiness/wiring-review/fix-round2/review.md. Main round1 fresh702CPU/3native-deselected0,145focused0,source-only0,202/202source match;702 là checkpoint trước raw-fix2/evaluator mới, không suy pass cho delta sau đó. Finalrawfix main26focused0. Shared offline actuation extraction scopedACCEPT:99mainfocused0,independent130fresh0 gồm200endpoint+100pose parity scenarios,12hashes;manifest ee4579bd7564b39110afdf8d93b406b51084b33e0ae9a3a1cb45ce7129ae940e. Chỉ source metadata proof checker/no-progress shared math; không dựng Observation giả.

Evaluator measurements mới implemented/frozen, chưa correctness-verified: manifest134aec9346a8d407dee18cacdc08290e5df9719f848a4c6e67c3ac8f32352e50,125focused0 (runs/p10-readiness/evaluation-measurements/exits.json), review SolHigh pending. Recompute trace counts/quantiles/source binding; sampled resources và body lowerbounds có support/limitation, dropped trace không tạo metric toàn pha; native_eligible=false tới execution binder riêng. Main tiếp tục NEW execution_proof.py/tests trong lúc review giữ nguyên evaluator/runtime/refs. Manifest/suitev2 và partial performance integration vẫn chưa nối; native/P10 tổng thể incomplete, chưa install/download/campaign.

## Checkpoint hiện hành — 2026-10-28

- **Implemented:** measurement evaluator, executed seed/config binder, export manifest v2, suite/result v2 và partial performance đã nối. V1/ba config cũ giữ nguyên. Main đã tái hiện/sửa original8 evaluator failures và5boundary failures bị lưu trước khi reviewer chạm quota; không suy review ACCEPT từ lượt bị ngắt.
- **Kiểm chứng mới trên snapshot ổn định:** `.venv/bin/python -m pytest tests -q -m 'not native'` → **787passed,3deselected,exit0**,56.72s;137focused0;21retained independent probes0;source-only0;202/202selectedsourcehashesmatch0. Lệnh/exits/logs tại `runs/p10-readiness/integration-v2/final/exits.json`. Intermediate784CPU không dùng làm final gate vì có late delta khi chạy.
- **Frozen chờ independent SolHigh review:** `runs/p10-readiness/integration-v2/final/manifest.json`, SHA **c6076ad07257f2d000547240cf7a14749e438392a5838acdc0daa63a4cb011c4**; report.md cùng thư mục. Reviewer bị account usage limit, reset được báo 2026-10-28 01:55 giờ Việt Nam. Chưa retry hoặc đổi agent/model để né quota. Gate P10 correctness mới **chưa đóng**; không tự thay bằng author review.
- **Runtime:** suite-v2 pilot expectedexit1,1scene×2seed;planned2/attempted0/completed0/missing2. Chưa có Habitat/detector/GPU native campaign, measured bootstrap/body clearance/floorcalibration/useful demonstration. Không có score accuracy/FPS hay native acceptance. Bản đề xuất môi trường đã có, chưa install/download được duyệt.
- **Bước kế:** review snapshot v2 bằng SolHigh khi quota sẵn sàng; sửa findings nếu có, sau đó mới đóng phần software correctness. Native vẫn cần environments/assets/calibration thực và smoke hữu hạn theo kế hoạch; không được bỏ missing/fail khỏi denominator. Hai folder nguồn chỉ đọc, chưa training/extension/commit/publish.

### P10 native preparation đang chạy — 2026-10-28, sau yêu cầu triển khai toàn bộ

Người dùng đã giao triển khai mọi phần còn lại và hoàn thành P10. Main đang cài dependency riêng và chạy smoke hữu hạn theo quyền này; không tải model/dataset, không sửa nguồn/driver/training/extension. Audit mở rộng tìm thêm3HM3Dbasis scenes trong NewOH3DSG/data/versioned_data, nên giới hạn một scene trước đây là inventory chưa đầy đủ. GPU bị ẩn trong sandbox; outside execution được duyệt thấy RTX3060Laptop6GiB/driver580.178.04 dùng được, không cần sửa driver.

Đã cài `.runtime/sensor` Habitat0.3.3/Python3.9, `.runtime/detector` torch2.7.1cu126/torchvision0.22.1/Ultralytics8.3.221/localMITCLIP, `.runtime/host` NumPy1.26.4+Numba0.61.2 (existing accelerator seam). Core `.venv` giữ nguyên. Locks tại runtime/environments; exactlogs tại runs/p10-native-preparation/. GPU CUDA import và sensor capture/seed/pose thật pass trên00802,00861; calibration00861 đủ100/100footprint+166/166corridor, startup00802yaw cũ hướng cửa sổ cần kiểm lại theo yaw mới. OptionalNumba parity đang kiểm riêng.

Smoke tích hợp00861 đã có native detector object commit thật và accepted region, cleanup sạch sau native reap fix, nhưng **chưa translation/membership**: control depthage~368ms trước threadlimits,~280ms khi hạprimaryresolutiondiagnostic và limitsCPUthreads1. Timings cho thấy mapwait~134ms+navigator~32ms+bootstrap~95ms; command100ms horizon bị chiếm gần hết bởi validation nên stepturnchỉ~0.02–0.18deg, chưa quãngđường. Không nớiTTL/robot. Main đang chẩn đoán giảm compute/reuseproof có sourcebinding đúng; chưa chạy campaign để chọn run đẹp.

Đã RED→GREEN hai startup/cleanup lỗi thực: `_BoundedProcess.close` dùng remainingdeadline để observe reap sau SIGKILL; launcher recapture sau setup và giữ startupcapture vào rawhistory để không mất frame0. Regression36IPC và42startup/binderfocusedpass trước rawhistoryfix;rawhistory17pass0 saufix. Ba testfixture ban đầu dùng maprevision=frame_index+1 giữa2sensor nên backward sau recapture; sửa fakeMapper dùng monotonicglobalrevision, giữ productionrevisiongate nguyên. **Các delta mới chưa independent review, snapshot787CPU trước đó không chứng nhận chúng.** Old frozen evaluator finalmanifest vẫnarchived; runtime refs launcher/test đã thay nên cần snapshot mới cho review tổng.

Resource sampler native báo partial support (ví dụRSS156/172,GPU17/21 trong20s): PID/scope churn/read errors làm resources.completefalse và summaryincomplete đúngcontract hiện tại. Không đổi unsupported thành0 hoặc bỏ sample. Cần điều tra scope/provider hoặc proofcgroup có attribution nếu có; không tự hạ gate. Actuationproofs ghi các turns thực, body/frontierlowerbound0 trongdiagnostic20s; useful demonstration và P10overall vẫnchưađạt.

### Checkpoint review + coverage reuse — 2026-10-28

Integrated independent SolHigh review completed on manifest4db335e9f6fff37397d7bed92528158de32b5f0062892c512800839e8b1f6542,43/43hashes unchanged: original evaluator/startup recapture/raw history/shared-deadline reaping fixes accepted;211freshfocused/seam tests0. Two new binder P2 findings reproduced independently (2fail/3pass): decoded resolution support trusts inflated counter; malformed worker_runtime array raises AttributeError. Fix writer owns execution_proof.py/test_execution_proof.py only; reviewer released original scope. Report runs/p10-native-preparation/integrated-review/review.md. P10 correctness remains open.

Main implemented geometry acceleration after RED: private MapDelta retains this integration's unaccumulated votes long enough to construct bounded immutable current-frame measured coverage; full Observation.geometry_hash guards reuse, no-return falls back to measured-only reconstruction, reset drops cache. Historical map/TTL/command horizon unchanged. Main41focused0,6paritytests0 (40mixed-depth independent fresh-mapper comparisons),44host-Numbafocused0 (including80Python/Numba kernel comparisons). Frozen geometry checkpoint28c65081e207373392feda371f4cb3136e226b97106ac4d029285382ee4ca192; independent SolHigh review active, no native claim yet. Resource scope diagnosis read-only separate; strict unsupported/completeness gates retained.

### Checkpoint tiếp tục native — 2026-10-28

Coverage cache đã independentSolHigh ACCEPT47fresh tests0,12hashes; native20s diagnostic bootstrapmedian6.6ms (trước~94ms),body/frontierlowerbound~0.00195m, chưa useful. Native action publicAPI khôngrender (agent.act+step_physics1/60) implemented,49focused/129seams0; main bounded5mmpulse actual0.004981m và~0.112ms, originalspawn collisionfilterđúng, không chỉnhspawn/floor. Independent review mới đang kiểm actuator+binder. Binder false-stable resolution flag đã main RED→GREEN, giữ startupstickychange và audited dimension population. Resourceprovider rootedallthreadscensus+freshretry/summarydiagnostics implemented; main17wiring0,77focused vừa phát hiện1deadlineclassification failure, đang review/reproduce, chưa đóng correctness. Hai reviewerSolHigh scopes frozen riêng, không sửa đồng thời. Không campaign/nativeacceptance claim.

Native preparation tiếp tục:00802 yaw mới đã capture/calibrate và bootstrap99/99footprint,165/165corridor,cleanupclean (sensor-calibration-00802-runtime2). Native actiontime parity old/new đúng world0→0.024s và postcapture0.024s/poseversion1; dt1/60 là API request, backendquantizedthật0.024s không gán thành elapsed1/60. Resource deadline R1 RED tái hiện rồi sửa ngay sau queryreturns và genericlateexception branch;90focused/independentpass0. Reviewerfollowup xác nhận fix và release snapshot313ada965d1b02846e593c2eff4a7a1cad77dc74d30cd14b325aaa613420a4fd; reportACCEPT đangpackaging. Main đang chạy fullCPU snapshot mới, chưa có verdict cuối hoặc nativecampaign. Campaignrecipe2scene tách2suitev2 pin riêng calibration/pose, envelope giữ4planned slots; xem runtime-measurements-contract.md.

### Native runtime2 diagnostic / phát hiện còn lại

Main fullCPU `.venv/bin/python -m pytest tests -q -m 'not native'`→865passed/3native-deselected/exit0,62.08s (integrated-cpu-current.log), trước RSSyield/archive/capsule deltas. Independent actuator+binder ACCEPT138focused+10adversarial0/19hashes. ResourceR1 fix ACCEPT90fresh0/9hashes; reports respective actuation-binder-review và resource-scoped-review/fix-round1.

60s diagnostic live-profile-00861-no-render exit1/incomplete,errornull,338frames (thực tế dừng~47s do rawarchive256MiB); detector4evidencecommits/acceptedregion, chưa assignedmembership;frontier/bodylowerbound0.017381m. GPU44/44supported;RSS383/389,trialdiagnostics retained. Main tái hiện realLinuxzombie RSS race RED rồi thêm schedulingyield≤5ms trong same100msdeadline/3trial;91relatedpass0, independentreviewđangmở. Thêm optionalarchiveallocation≤halfrawbudget (default256MiB giữ nguyên),90archive/launcher/RSS/wiringpass0;newruntime3profile chia1GiB archive trong raw2GiB/total8GiB, không nângaggregatecap. Contractđãghi beforecampaign.

MotionGuard filtermedian~66ms khi validationtoànpath, nativeforwardrequested~0.037m/actual~0.017m; khôngnớiTTL. Geometryowner đangvector hóa capsuleclosed-square exactoracle boundedchunks; preliminaryCPUrecomputed10segmentpath~22xfaster, chưanativeclaim/review. Runtime3smoke/configs chuẩn bị; chưafreeze/launch acceptancecampaign và chưaP10runtime-validated.

Runtime3 verification snapshot (trước precision/wiring/closed-boundary fixes):898CPU/3native-deselected0,4faultinjection0,source-only0,nativeDuDe3pass0,202sourcehashesmatch0; logs runtime3-verification/exits.json. Capsuleacceleration parityreview139focused+7independent0/8hashes, nhưng phát hiện preexisting lower-tangent candidate omission là hardgeometryblocker; writerđangRED→fixvàreviewriêng, không bỏ qua vì oldcode cũng lỗi. Native runtime3 smoke chưaactuate: TypeError archive_cap lọt Pipelinekwargs, sourcefinallycleanupchạy nhưng không cócompleteexport. Maintái hiệncorrectfixtureRED và sửa allowlistPipelinebudget; regressionintegrationkhông chỉconfigloader. Nativefloat32segmentendpoint trộn float32norm vớifloat64candidate bị fraction1.000000052 từchối sai; mainRED1fail1pass originalfrozenexecute, sửa promote start/endfloat64 trướcmath, khôngnới[0,1]/1e-7.88focusedpass0; precision/wiringreviewpendingmanifestba8dda7d8ab38732f36b54deec6d8b7ca864b171eff74ec1874d8a5850282ae7. Runtime4configs/scriptsmoke chuẩn bị, campaignchưalaunch/nativeacceptancechưađạt.

Precision/wiring independentACCEPT84focused+9independent0,7/7hashes: actualhorizontalfloat32endpoint regression、200randomendpoint/clip cases and strictoutside/nonfinitechecks; replayconstructorrepro fixes archivekwarg wiring. Closed-boundary firstfix171focused0,16newRED→GREEN, nhưng independenthugeoriginprobe tìm6failure (2rationaltranslation±1e16+4guardmissingcells) do worldcoordinates rounding nuốtbánkính. Main giữ hardgeometryblocker, writerchuyểntoàncapsulemath sang originrelative; manifestfirstfix3f0736f98c541b34c395a4e324354c450656facc83c370b232c1fa6edcf1a443 released. Reviewevidence closed-boundary-review/test_independent.py; chưalaunchruntime4smoke/campaign tronglúcfix. 898CPU snapshot trước các fixsaunàykhôngđượcgánchoheadhiệntại.

Closedgeometry round2: mainfrozenminimalRED ghi origin0 trả12cells, origin1e16 chỉ4, thiếu8tangentcells. Writerchuyểntoàncapsulebounds/distance/fallback sangoriginrelative (khôngchỉbounds),196focusedpass0 gồm15retainedreviewerprobes. Frozenmainmanifest9eec517e4a92d9d2924c4a43c1e9c87eefc59bf639c25263996732a8f0f89ecc; writerreport capsule-closed-fix/round2/report.md;occupancySHAcb39792eaa0bee256a2ab2004547d17e5311e748e06e3f4495310dc22d1a5847. IndependentSolHighround2active, mainfullCPU/fault/package/nativeDuDe/sourcehash đangchạy runtime4-verification. KhôngGPUjobhiệnđangchạy; runtime4smoke chưalaunch, campaign4slotschưafreeze/chưalaunch. Workerprecision/wiringreviewđãACCEPT, runtime4configspinsnewworkerhash, archive1GiBtrongraw2GiB unchangedaggregatecaps.

### P10 tiếp tục — native/runtime4 và RSS proof

Fullruntime4 snapshot928CPU/3native-deselected0,4fault0,source-only0,nativeDuDe3pass0,202sourcehashesmatch0; runtime4-verification/exits.json. Closedboundaryround2 independentSolHighACCEPT92focused+16newprobes0/9hashes, original6P2probespass; no geometrygate loosened.

45s runtime4diagnostic failedearly68frames với sensorclosed; lỗiIPCexecute gốc đã bịcontrolhandlerconsume nên artifactchỉthấy nextsensorclosed. Guardmedian~2ms (prior~66ms),raw68/68complete,GPU13/13,RSS120/125;nomotion/membership. New25serrorprobe khôngtáihiệnIPCerror:244frames,raw244/244complete,GPU28/28,RSS258/262,frontierlowerbound.083055m,realcommits/acceptedregion,nomembership. 60szombie-rss diagnostic similarly noIPCerror,454frames/rawcomplete,GPU59/59,RSS540/548,frontier.088414m;forwardrequested.08841385matchesactual.08841380m, quay235.8deg, chưauseful>1m. Runtimeeventrecorder7durable/42offered/35missing, khôngcomplete; khônggiấu dropped/rejected.

RSSworkerrealzombie RED +live-threadcounterexample: zero chỉsafe vớiStateZ/Threads1/singletask/sevenzerostatm, khôngchỉleaderStateZ. Mainimplementedboundedstrictproof and75focusedpass0, artifactzombie-rss-diagnosis/main-report.md; independentreviewpending. Reviewer báo usage limit reset1:18PM; không retry/đổi model để né. Maincòn tiếp tục CPU/diagnostic, không đóngP10bằngauthorreview. Zero-proofkhôngxoámissing/historicalsamples hoặc continuouspeakclaims. Sourcefulltest928pre-delta khôngchứngnhận RSSheadmới.

Low-nav120×160calibrationmới cả2scene đủfootprint/corridor:00861 100/100+166/166,00802 99/99+165/165. Newruntime5configs pin measuredfloor/calib vàactualres; native60s diagnostic đangchạy giảmraycast, khôngphảiacceptancecampaign. TTL300ms/command100ms/robot/raw2GiB/total8GiB/RSS10GiB/GPU5GiB giữnguyên;chưa4slotcampaign/nativeacceptance.

RSS reviewer availability đã kiểm bằng trusted app get_usage_limits: ordinaryUsageAllowed=true,rateLimitReachedType=null,primary9%/secondary80%; main gửi lại đúngreviewer cũ một lần, agentresumed (không modeloverride/alternate để néquota). Scope finalzombieRSSmanifest5e6b27865f1c1f210d47a7a10590f859dc53456f9c2e552712414a544b2c490f đangreview; reviewer91focused+24adversarial+realzombie1pass0, chưareportfinal. Original diagnosis test ghi lại fixedactual-zombie-evidence.json khi chạy GREEN; reviewerđãcopysangzombie-rss-review/actual-zombie-green-evidence.json và sẽ ghi rõ fileold bịreplace, REDlog cũ cònnguyên; không suy JSONhiện tại là oldRED.

Low-nav120×160native60s:768frames/rawcomplete,GPU60/60,RSS552/557,runtimeeventrecordercomplete2durable/0missing nhưng frontier0, quay11pulse rồi khôngtiếp. Calibrationinitialfootprintpass chưađủchứngminhallorientation; mainđangkiểm24yaw cho120x160/180x240/240x320. Scriptcalibfirstattemptfailedserialization np.int64 saufirst24captures; đã sửa chỉserialization và dùngnewoutputnavigation-yaw-coverage-fixed để khôngghiđèlogs; khôngrunselectiveperformance/campaign. RSSproofnative60s trướcđó540/548 cho thấy fallbackZ1khôngtựlàmresourcescomplete, cònrealunknown/teardown/clockdeadline; gate vẫnfalse.

### Tiếp tục P10 — medium navigation và thread RSS snapshot

Yaw sweep hữu hạn đã hoàn tất: `navigation-yaw-coverage-final/report.json` kiểm24yaw mỗi resolution, footprint ready120×160=12/24,180×240=24/24,240×320=24/24. Vì thế low-nav runtime5 không được chọn; runtime6 giữ primary120×160 và nav180×240, pin calibration medium của hai scene. Đây là profile chuẩn bị, chưa campaign hoặc runtime acceptance.

Thread RSS fallback implemented, writer135focusedpass0 (3.63s), real Linux surviving-thread RSS11972608bytes/process_count1; manifest `thread-rss-fallback/manifest.json` SHA3f8ef6fa29f40491e35fe8a8c0c15b1c6f8431ae5346e8224888351a28a4d4db. Chỉ chọn một liveTID có shared-mm và identity/topology trước-sau đã xác minh; null khi thiếu/churn, giữ shared deadline và Z1proof. IndependentSolHigh review tại `thread-rss-review/` đang chạy. Worker fullCPU đã bị main yêu cầu dừng để điều phối tải, exit130/incomplete; không tính pass. Full928CPU trước delta không chứng nhận head này.

Read-only prospective design audit `keyframe-backpressure-design/design-audit.md` kết luận optional idle-only semantic sampling và explicit RSS acquisition budget có thể phù hợp nếu pin trước run, ghi đủ denominators/actual gaps và giữ mọi reject/null cũ. Chưa triển khai hai option này. Không thay TTL300ms/horizon100ms/caps/strict completeness hoặc hồi tố artifact cũ. Bước tiếp: independent RSS review rồi diagnostic60s medium-nav với error capture mọi sensor operation; campaign4slots chưa freeze/chạy, useful>1m/membership và lỗi intermittent sensorclosed vẫn chưa chứng minh.

Thread RSS independent scoped ACCEPT: `thread-rss-review/review.md`,135focused+19adversarialpass0,5records+3frozencopies unchanged; source scope released. Native runtime6medium-nav attempted60s, exited1early94frames; `execution-errors.json` now preserves original **ValueError yaw bounds mismatch** for turn_right, then closed sensor on next capture. Diagnostic44Navigatoralign/44bootstrapready/44Guardalign shows initial orientation coverage no longer blocks that portion, but no useful translation. RSS149/152,GPU15/15; cleanup pending detector/resources explicit. This is failed diagnosis evidence, not campaign. Dedicated bounded native yawproof probe is being prepared; compound bound error does not yet prove quaternion rounding. Do not loosen proof tolerance.

Main prospective profile config/launcher implemented after RED9failed/18passed: optional live-only capacity semantic sampling and RSS acquisition timeout validation/propagation;27newtests GREEN after fixing a test's preexisting YAML scientific-number lexical mismatch (1e-06 parsed string; use .001 numeric). Main81focusedpass0 includes launcher/archive/measurement regressions; additional builder/replay propagation30newtestspass0. No independent implementation review yet. Coordinator/scheduler capacity writer has separate ownership, uses bounded counters/no historical recount; source head changing,928CPU old snapshot remains historical. These options do not close any native gate.

Bounded native yaw witness captured: `.venv/bin/python runs/p10-native-preparation/yaw-proof-diagnosis/probe.py --out runs/p10-native-preparation/yaw-proof-diagnosis/native-right-120 --pulses 120 --direction right` under approved nativeGPU environment→exit1 (diagnostic validation failures),120actualturns/0nativeerrors/2proofvalidationfailures. Raw quaternions are float32; failed85/97 measuredyaw exceeds configuredangle by1.33469038e-7/1.04786885e-7rad, just beyond unchanged1e-7 proof tolerance; commandfull3deg budget not exceeded, translation0. Exactraw/proof/sourcepins retained. This gives a concrete witness for the error class; it does not prove the prior native6 failing pulse had identical numeric cause because its rawfailedproof was unavailable. Actuator fix choice is under analysis; do not increase tolerance or rewrite configuredamount afteraction.

Optional sampling/RSS profiles scoped ACCEPT sau P2fix: reviewer tái hiện live-mode replay bypass recordeddetectorguard (1fail/5pass), main RED mới và chặn mọi capacity-profile replay trước output/session/worker; directbuilder cũng chặn replayclock. Exact selected-journal replay optionalprofile hiện chưa hỗ trợ, không giả rawresampling thành exactreplay. Main111focusedpass0; independent68freshpass0 (31options+26capacity+11reviewer),18/18hashes ổn định. Finalmanifest `sampling-profile-checkpoint/fix-round1/manifest.json` SHA2cf3658c2bcad437998fc4093b8ae60531ec79668af98f62f62e6dc550e1201d; review `sampling-profile-review/review.md`. Runtime validation và full head suite vẫn chưa chứng minh.

Main chọn conservative yaw preflight approachA tại `yaw-proof-diagnosis/decision-analysis.md`: actual installed Magnum CPU expression tái tạo120/120quaternions native; helper sẽ xét≤32positivefloat32candidates≤requested, chỉ chọn khi predictedyaw đạt **nguyên1e-7 proofv1/sign/budget**, finalTTLgate sau preflight, candidate=configured=proof.amount. API/state/parent không xác minh hoặc hếtcandidates thì không bước; actualpoststep vẫn kiểm nguyênvẹn. Không tăngepsilon hay sửaproofs cũ. Writer sở hữu habitat_worker/newquantizedtests và explicitactuatorfixtures, đangTDD; phải độc lập review và freshnativeprobe trước đổiworkerpins/runtime7. Prepared `make_runtime7_configs.py` CHƯA CHẠY; native7 CHƯA CHẠY. No4slotcampaign/nativeacceptance.

Quantizedyaw initialsnapshot fullintegration: `runtime7-verification/exits.json` CPU1068passed/3native-deselected0 (87.52s),fault4pass0,source-only0,nativeDuDe3pass0,source202match0. This gate used explicitPYTHONPATH=tests:src. Independentreview correctlyfound fixtureP2 maskedbythatsetting: copiedactuationworker derives testhelperpathfromtemporarylocation, ModuleNotFoundError withoutPYTHONPATH (74pass4fail). Onlyfixturewriterreleasedforrelocatableimportfix, productworkerhash00f0db... remainsfrozen. Do notclaimunqualifiedreviewACCEPT/fullheadpassbeforefix. IndependentinstalledCPUprobes120originalexact/240left-rightcandidateactualexact/180randomstates(93accepted/87safe-refusal)/4qualificationrefusals passed; noSimulator/GPU. Native7configsnowcreatedwithworker00f0db...,capacitydeferred/RSS.5 explicit, butnative7notlaunched.

Yaw review additionalcorrectnessfindings: fixture-onlyimportfix RED4fail74pass→GREEN78pass withunsetPYTHONPATH, fixturemanifest9965433809dbe7523cdec290c2d868e70719bda128d51bceb4ba33d276bb2f1f. RevieweractualMagnumCPUminimumpositivefloat32degreeincrement underflows nativeidentity, yet previousprepareallowed dyaw0; actualtinyyawworkerpathreports executedtrue (independent1fail13pass). Mainacceptsrequiredcontractfix: strictpositiverepresentedyaw/nativeincrementidentity rejection, no upsize/epsilonchange; worker/newtestreleasedtoauthor, TDDongoing. Initial1068CPU snapshotremains validonlyforpreviouscode, notnewfix. runtime7configs unusedpreserved; prospective runtime8scriptspreparedonly, campaign/native8notstarted.

Finalyawfixsnapshot frozen210b1fac40f60fb12c1e48077a44715a4dc8c0a36fa09c982b041950d5e735f6 (`quantized-yaw-fix/underflow-fix/manifest.json`), worker d8c250c24cdc822d74adb4e05c4da748603023705e3dcd047a0410326ec61d25. UnderflowRED3fail→GREEN81focusedunsetPYTHONPATH0; realMagnumCPUidentityincrementprepareNone, tinyyawworkerdoesnotstep/pose0,120original+chosenquaternionparity0. Independentnarrowreview active. Runtime8configscreatedexplicitcapacity/RSS.5/newworkerpin; fullCPU/fault/package/DuDe/sourcegate running `runtime8-verification/`. Oldruntime7configs remainunused. Allnewnative/runtime8/yawconfirmation runs pending; no4slotcampaignfreeze.

Artifactretentionnote: writerCPUparityscriptoriginallywroteparentnative-cpu-parity.json againwithnewworkerhash; newcontentcopiedunderunderflow-fix and reportdisclosesreplacement. Originalnative120rawproofs/frozenoriginalsource/manifests retained; do notattributecurrentparentJSONtoinitialworkerhash. CorrectedinlineunderflowdiagnosticinitiallyexpectedproofNone; a validemptyactionsproofislegitimatestoppedproof, so assertion correctedwithoutproductrelaxation.

Finalyaw scopedACCEPT `quantized-yaw-review/review.md`,manifest210b1fac...12/12hashesunchanged,95hosttests(81unsetPYTHONPATH+14independent)0; installedCPU120original/240left-rightparity+180adversarial+tinyyawactualworker0. Mainfreshfullgate `runtime8-verification/exits.json`: **1071CPU/3native-deselected0**,4fault0,source-only0,nativeDuDe3pass0,202sourcehashmatch0. No unresolvedscopedsoftwarefinding.

Freshnativeyaw confirmation `yaw-proof-diagnosis/native-runtime8-right-120/`:120rows/0proofvalidationfailures/0nativeerrors/child0/parent0, originalraw/sourcepins preserved. This validates bounded nativeyaw slice, notwholeP10. Newprofile native60s `profile_live_runtime8_quantized_yaw.py` nowrunningaloneGPU: capacitydeferredsemantic sampling/RSSacquisition.5 explicitlypinned,newworker d8c250...,primary120×160/nav180×240; TTL300ms/horizon100ms/robot/capsunchanged. No4slotcampaignfreeze/runsyet; nativeusefultranslation/membership/resourcecompleteness/cleanup awaitingactualresult.

Runtime8native60sresult: exit1/incomplete,errornull,494frames/raw494/494complete,event6offered/6durable0missingcomplete,semantic246seen=76deferred+170evaluated,170=164unselected+6offered; allcleanupclean. GPU60/60,RSS490/497 (missing2/readerror4/identity1),peakRSS~2.858GB/GPU327MBsampled,nocapbreach; maxRSSgap234.5ms/.5acquisitionexplicit. Noexecution/invalidprooferrors. Frontier/bodylowerbound **.119022556m**,not>1m;6live detectorcommits/3objectevidencecommits/acceptedregion,nomembership. Report `runtime8-diagnostic-summary.json`. Historicalnullsamplesremainnull; noacceptancecampaign.

Nativewaitmapmedian150.25ms,NavMapper.update49.05ms,Navigator.step64.88ms,Guard7.51ms;106forwardpulsesrequested.119022573m matchactual.119022556m,medianpulse.000698m,medianbeforestep12.6ms. It is currently lowthroughput/shortsourcebudget andcontrolleroutput, notcollisionclippingevidence. Read-only CPUprofileassigned; must preservealgorithm/TTL/safety. Bounded/procRSSwitnessretainednow: leaderZThreads2+otherStateRwithoutVmRSS; diagnosisassigned, nozeroassumption. No productdeltaafter1071gateyet.

Native8forensicCPU/read-only: `runtime8-navigation-profile/report.md` reproduces final-nav Navigator~15–18ms isolated, plan_many8.6–8.8ms/frontier4–7ms; native65msincludescontention/interleaving.244/246waitsoverlap2mapupdates. `runtime8-rss-diagnosis/report.md` proves snapshots ofexitingtaskgroupswithallcapturedmmRSSfieldsabsent/statm0/PF_EXITING, but notstablepairedproof orphysicalreclaim; mainexplicitlydoesnotadoptnewR-zero proof/cgroupsubstitution. Cgroupisread-onlyChromiumapplication scope/notattemptattributed. Retryfailuregroupsspan~127mswhileold3rapidtrials~13ms; explicitprospective.2retrywait chosenwithsame.5deadline, notretroactivepass.

Implementedpairedcapturepublication/RSSwaitslicesinprogress: provider141focused0,23newcases, manifest513d08129121a7fb9a09502f47663ed76c465baafa262f39e9f6cfcc671616f0; source88fae3c17feaf60da64af7527319fe85fe4fc7c193af7002344270ca45126b77. Mainlauncher/config RED→GREEN15retryenum/5capturefailuretests,53newfocused0 and119launcher/archive/seed/measurementintegration0. Coordinatorpairwriterownsnewmethod+tests, snapshotnotyetreleased. Native9scripts/explicitretryconfiggeneratorpreparedbutnotexecuted; needcombinedreview/currentfullgate before60sdiagnostic. P10runtimeincomplete/no4slotcampaign. Default5msretry/novelty unchanged; allraw/semanticnull/rejectiondenominatorsstrict, TTL/robot unchanged.

Pairedcapture+RSSwaitcombinedsnapshot frozen: `pair-retry-checkpoint/manifest.json` SHA9de40f0a0214c11c275cf646a7ff389f2f85909fa925f9224f66ca2d1fdfde48,8owned6refs/8copies. Pairwriter126focusedunsetPYTHONPATH0, coordinator9230eeae53cca687310bb6a23cc1b4b9077f18d404c5d6749ea9e6ebdeddde8e; invalidpairbeforeadmission, queuepublicationatomic/inflightoldmapallowed, fixedsource/captureidentity/measurements/rawnochanges. Fiveintermediatefailureswereharnessfield/terminalcloseassumptions, notproductbugs; logsretained. RSSwriter141focused0/default5msunchanged. Main119launcherseedarchiveintegration0/53newhelper-options0. Independentreview at `pair-retry-review/` active; freshfullCPU/fault/package/nativeDuDe/sourcegate running `runtime9-verification/`. Native9configscreatedprospective.2retry/.5acquisition,pairsourcefrozen; nativerunnotstartedandcampaign4slotsnotfrozen. Prior1071suite/nativeruntime8do notcertifynewhead.

Maincurrentpair/retryintegrationgatecomplete: `runtime9-verification/exits.json` **1161CPU/3native-deselected0** (88.10s),fault4pass0,source-only0,nativeDuDe3pass0,202sourcehashmatch0. Scope9de40f... remainsfrozen, independentreview121new-scopefocusedpass0 andfullactuallauncher/rawfailureprobesinprogress. Native9notstarteduntilCPUquiet/reviewresult. No nativeacceptanceclaimfrom1161tests; lastreal60snative8still.119m/RSSpartial/nomembership.

Combinedpair/retryreview scopedACCEPT:9de40f...22/22hashesunchanged,121focused0+7independent0; actualfull launcher.run realPipeline/RunMeasurements/ReplayWriter navfailure/posefailure/realmax_framesrawreject preservedrawRGB/captureonce/noRGBsemanticoffer/nocontrol/truthfulincomplete+cleanworkers. Report `pair-retry-review/review.md` packaging. Native9diagnostic60s nowrunningaloneGPU, sourceunchangedafter1161gate, new.2wait/.5deadline explicit. Historicalnative8nulls/partialmovement retained. Campaign4slotstillnotfrozen/launched; awaitingactualtranslation/membership/resources/cleanup.

Native9diagnostic60s **completed/exit0**,errornull,834raw/834complete,13offered/durable0missing,eventcertificatecomplete,allworkersclean. RSS513/513/GPU61/61supported,resourcecomplete (sampledonly),maxRSSgap430.65ms,.5budget/.2waitexplicit; noinvalidproof/IPCerror. Observedfrontier/bodylowerbound **1.036866531m** (>1m),13live detectorcommits/7objectevidencecommits/acceptedregion,stillfirstassignedmembershipnull. `runtime9-diagnostic-summary.json` andoriginalartifacts retained. This ispreparationdiagnostic,notfrozen4-slotcampaign/P10acceptance.

Scene00802sameprofile60ssmokenowrunning via `-m neusymnav.cli run`. Firstcommandused `-m neusymnav` incorrectly(packagehasno__main__),exit1beforepipeline/outputcreation; preservedfirstlog thennew-cli.logcorrectentry, no nativeselectivererun. PreparedcampaignrunnerprototypesmustusecorrectCLIbeforefreeze; theyhaveNEVERexecutedcampaign.

Reviewerreported usage-limit afterfinishedpair/retryACCEPT/report/source-release (128freshtests/22hashes). Do notretry/alternate model to bypassquota. Existingacceptedheadcanstillrunboundednative/analysis; finalP10independentreviewavailabilitymustbecheckedbeforeattemptingnewreviewdispatch.

Scene00802runtime9smoke60s completed/exit0,errornull,1144rawcomplete/event4durablecomplete/RSS577/577/GPU61/61/clean; **frontier0m/noacceptedregion/membership**.532forwardpulsesrequested2.54136mactual0, notcontrollerabsence. One5mmboundedcollisionprobe `collision-filter-00802/report.json` exit0 preservesstartY.123999998 andnativefilteredY.110607646 withdesiredXZaccepted, so3Dsegmentresidual1e-7rejectsverticalgroundingsnap; snap_pointforactuationdiagnosisonlyY.112816878 (11mmoffset),posewasnotchanged/mapwasnotseeded. Lateyawtiny-ratepreflightrefusalsaresecondary; forwardalreadyblockedindependently.

Maindoesnotloosenfilter/heightbound. Read-onlydesignauditapproachesatplanar-actuation-design/: preservehorizontalXZsegment+strictboundseparateverticalgroundingsupport vsbroaderphysicalYmotion vsdeclareunsupportedscene. Needcontractdecision/evidencebeforeimplementation. Trustedappget_usage_limitsnowordinaryUsageAllowedtrue/noReachedType/primary7%secondary1%,2026-10-2807:50UTC; resumedSAMErevieweronceafterchangedavailability,noalternatequotaevasion. Campaignstillnotfrozen/launched;00861completed>1m aloneinsufficientP10.

### Blocker quyết định contract sau qualification hình học — 2026-10-28

Strict3Dcompatibility prequalification retained:00802nearby25candidates0pass;00337fixed25contact2pass(index0/11),freshRGBDindex0bootstrap0/101+0/167,lowcameraexperimentstill0;index11 nav180and240both88/100footprint+149/168corridor so blocked (actualobstruction, notdensity). PrimaryRGB/depthinspectionindex0showscloseframe/wall; initialceilinghypothesiswasnotestablishedandlowercameradidnotresolveit.00770fixed25contact0pass. Allassetsalreadyexisting, noactualpipelineperformance-basedspawnselection; no newmodel/data/OS/sourcechanges.

Mainwrote `docs/p10-planar-adapter-proposal.md`: A explicitopt-in planar_fixed_y_v1/constantanchorY/newboundednativeYprojectiondiscrepancy contract vs B keepstrict3D/nativepilot incomplete. Importantnewcontractnotimplicitnear-groundtolerancereuse; defaultstrict3D/XYproof/TTL/depth/robotgatesunchangedifAselected. UserchoiceaskedasyncbecauseAGENTS→orchestration§6requiresclarificationforimportantcontractchange. **Awaiting userchoice, noadapterimplementationorModeAnativerun.** Continueevidence/docsindependently; do not inferapprovalfromelapsedtime. P10campaignnotfreeze; currentsourcecorrectness1161CPU+scopedreviews/native00861usefulproof remainsvalidwithinactualscope.

User explicitchoice received: **A — opt-in planar2Dconstantheight, preserveRGBD/footprint/TTL/proof; disclose nogrounding/terrain3D**. This resolvesimportantcontractapprovalblock; no needaskagainforscopedimplementation. Proposalstateupdatedandnewcontractappendedruntime-measurements-contract.md. Mainconfig/launcherenum/defaultprofileidentity RED→GREEN; sourceworker/newplanartestwriteractiveunderTDD, defaultstrict_3dunchanged. Need independentSolHighreview/currentfullgate/native5mm+smokesbeforecampaign. Priorstrict3Druns/qualificationfailuresremainfailed/unsupported; alternativeCnotcurrentimplementationchoiceafteruserA.

Planar A source frozen: combined `planar-fixed-y-checkpoint/manifest.json` SHA1d133796e8d6da96705e7a527f942a2948fc951cf0ac753124460bba694d712c,17records; worker56dad4bd58b34e513b93c75196ef9d2b38009251c66811c7eceab42e34ab2a53. Writer183focusedunsetPYTHONPATH0 and actual nativeCPU Agent/ObjectControls ~4.9708mm/Yexactunchanged0; this is no fresh Simulator/scene certificate. Main real configuration→launcher→workerACK61optiontests0. IndependentSolHighreview active, freshfullgate `runtime10-verification/` running. Fourruntime10configs generatedexplicitplanar+newworkerpin; native5mm script prepared but notrun. Strict/default and old failures retained. No4slotcampaignfreeze/nativeacceptance.

Planar scoped review CPU-DONE/ACCEPT:244focused0,34source/copyhashesunchanged; installedCPU90translation+8failclosed/mixedyawcases retainY. Hostproof93:81pass/12lateralprecisionreject; first4sameexactflatcontactstrictbaseline also reject. These unsupported unchangedprecision cases remain rejected, not relaxed or nativeacceptance. Fresh actualSimulator00802 one≤5mmpulse exit0: qualificationtrue,4.9610138mm actualXZ, actualY.12399999797344208 exactlyunchanged, nativefiltercandidateY.110594615 retainedasdiagnostic; hostproofv1validation0. Evidence `planar-native-00802/report.json`, `host-proof-validation.json`, original log. New60s00802ModeA pipeline smoke launched aloneGPU; no4slotcampaignfreeze.

ModeA00802first60ssmoke **failed/exit1** after10rawframes: top error sensorworkerclosed, graph/raw/resourcecleanup incomplete/pending, one accepted ~.658mmfrontierproof, zero detectorcommits/region/membership. No capbreach but sampledcompletefalse; this remainsfailure. Original `live-smoke-00802-runtime10/` preserved. Plain CLI maskedfirstcontrol exception, so one bounded diagnostic `diagnose_runtime10_first_failure.py` launched with existingwrappers retaining execute/request/invalidproofs; no sourcechange/rerunselection/campaign. Mustrootcausebeforefix; native00861smoke/campaignpending.

Bounded diagnostic reproducedfirst00802failure: hostproof rejects `body moved outside forward segment` onforwardactionamount.0011951623508512177, beforeXY[2.7526586055755615,5.162430286407471], after[2.7514634132385254,5.162425994873047], yaw-3.1380968235830613. `diagnose-00802-runtime10-first-failure/invalid-proofs.json` retains exactproof/command; sensorclosed issecondary afterhostcorrectrejection. SourceXZlinecheck and canonicalheadingproofbound differ at float32endpoints. Mainreleasedworker/newplanartest tooriginalauthor forModeA-only conservative endpointveto BEFOREactualmovement, preservingstrictdefault and1e-7bounds, no pose/proofrewrite. Prior1248fullgate/review applies previoussnapshotonly. NewTDD/frozenreview/currentgate/nativechecksrequired; no campaignfreeze. Diagnostic itselfexit1/failure retained, notbest-runselection.

Resume after interruption: prior agents no longer active. Main verified writer frozen files/manifests available, focused-green187pass0/nativehost101valid artifacts; adopted source freeze worker`e2d825a0fb4d363c6f1a6c842ee44facf139178001b9c121fc9f981a9acc8a68`, combined`planar-endpoint-checkpoint/manifest.json` SHA492f1ffec5e795f968abf465f21c0563b4b731b78dd2fc7e07c973a966689048. No edits by main to worker/test. IndependentSolHighreviewnewagent `endpoint_review` active because previousreviewer no longer present. Main fresh `runtime11-verification/` running with PYTHONPATH=src only (not tests); runtime11fourconfigs creatednewworkerpin. Prior1248suite doesnotcertifynewhead. Diagnostic-onlyregion_capsule helper mainfixtureconfirmexit0 (boundedfirststale/eviction/cap/restoration), next60ssmokedriver preparedcapturingregioncauses; neveruseitforcampaignperformance. Native11/campaignnotstarted.

Runtime11 main currentgate:1252CPU/3native-deselected0 (91.27s), no tests-directory PYTHONPATH masking. Fault standalone initiallycollectionexit2 (`test_runtime_scheduling` fixture unavailable withsrc-onlypath), retained `faults.log`; explicitfault-onlyPYTHONPATHtests:src then4pass0 (`faults-harness-path.log`). No product change needed. Source-only0/nativeDuDe3pass0/202selectedsourcehashmatch0. Allcommandsincludinginitialharnessfailure retained inruntime11-verification/exits.json. Independentendpointreviewpending; no native11jobstarted.

Endpoint scoped independent SolHigh ACCEPT `planar-endpoint-review/review.md`:131focused0,85/85actualCPUproofshostvalid/11positivetranslations,34/34frozen/livehashmatch; savedruntime10badproofstillreject, defaultsharedclient/validatorunchanged. CPU-DONE beforeGPU. Fresh actualSimulatorruntime11single≤5mmpulse exit0:4.9557686mm,actualYexactunchanged; hostproof0 (`planar-native-runtime11-00802/`). New00802smoke60s launchedaloneGPU using diagnosticwrappers+boundedregioncapsule, no4slotcampaignfreeze. Main1252CPU/fault4/package/DuDe3/source202 currentgates0 asabove; runtimeoutcomenotyetknown.

Native11smokes60s each completed/exit0/clean withcurrentworker, noinvalidproof/IPCerrors.00802:1100rawcomplete,2/2durableoffers/2realobjectcommits,RSS588/588/GPU61/61complete,frontierlowerbound.118585989m then455bootstrap_blocked, noacceptedregion/membership. Regioncapsule showsclientpoisonedbyinvalidpolygon `region polygon must be simple and nonzero`.00861:890rawcomplete,14/14durableoffers/14detectorcommits/6objectevidencecommits,RSS532/532/GPU61/61complete,frontierlowerbound1.105631123m,acceptedregion,nomembership. Detailed `live-smoke-*-runtime11-diagnostic-summary.json`, originalcapsules/errors/raw retained. Sampledresourcepeaks only; observedmovementlowerboundsnotfullruntraces. Bothnopendingworkers; oldnative10failuresremainfailed.

No4slotcampaignfreeze because00802usefulgate andsuiteassignedmembershipstillmissing. SolHighread-onlydiagnoses dispatched: runtime11-bootstrap-diagnosis actualfewframes currentRGBDsupport, runtime11-region-diagnosis exactnativepolygonfailure; GPUidleafterbothsmokes, boundedCPUdiagnosisapproved. No sourceedits/gaterelaxation authorizedbythese scopes; mainwillverifyactualrootcausebeforefix.

Rootcause boundeddiagnosis updates: actual00802RGBD/navframes5/94/95/550 showbody100/100valid atblock, .3mforwardcorridor156/166with10OCCUPIEDcells, observedbody-heightreturns(~.84855m), floor_supportpresent. This islegitimateobstacle/corridorstop, notfloor/axis/sparsedepthbug. Pureyawalreadyusesbootstrapcorridor0 andactualcoldfinalnavallowsyaw, so no universal yawtrap. Upstream3DSG runtime `_reject_goal` wiresreport_goal_failure/resetcontroller; NeuSymNav existingAPI notboundafterGuardrejection. Originalwarmgoalworldtargetnotretained; bounded100/500heldtargetsearchfailedtoreproduce, mustnotclaimoriginalexactdeadlockproof. MainauthorizesnarrowmissingbindingTDD oncoordinator/newtest only forsourcecoherentgeometricguardstop, leavingcurrentcommandzeroandallgatesunchanged. Nativeeffectunprovenuntilfreshsmoke.

Regiondiagnosis `runtime11-region-diagnosis/report.md`: exactfinal00802raster twofreshnativeprocessrequestsreproduceidenticalsuccess/accept_incremental20vertexring withpixelzeroareas spur/retrace; inputpreprocessedOpenCVcontour isexactreversecyclicmatch ofexportedring. Integeralreadyinvalid, notfloattransform/clientfalsepositive. Originalfirstfatallivewireunavailable; exactlategridrootcausereproducedonly. Mainruling: structurallyvalidbutnon-simplecandidate mustrejectcurrentupdate/stale underarchitecture61, whilehealthyIPCcanparsefutureindependentcandidate. Transport/schema/type/cap/malformedlaterregion remainfatal. No ringrepair/hull/dilation/nativealgorithmchange. Writerowns dude_client.py/newtest +onlytwoexistingsemanticpoisonassertions; TDD/frozenSolHighreviewrequired. This isadmissionfailureclassification, notacceptancegate orgeometrytolerancerelaxation; noauto retry/reset/nativebuild/vendorchange. Bothnewscopesinprogress; current1252suitecertifiesprecedingsnapshotonly. No campaignfreeze.

Runtime12 software checkpoint frozen `runtime12-checkpoint/manifest.json` SHAd16ae6ce45700827ae7f1550dbfbdc7dfdde15edd430b3b8b6d3422f936b8388 (13source/test/contractrefs+copies). Regionwriter64focused0/2actualsameprocesssemanticrejectswithhealthyIPC; goalwriter91focused0, new27bindingcases/resetandboundedexistingmemory; changedclockcaseRED→GREEN retained. Independentreviewregionpart1ACCEPT64focused+23adversarial0, goalpart2pending. Main fullcurrentheadgate running `runtime12-verification/`; fourconfigs12created,sensorworkere2dunchanged. No native12orcampaignlaunchedyet. Diagnosticcapsule nowprotectsfirstvalid→stale andfirstnativeerror separately andcapturesboundedrawnativewire; priorcapsulesunchanged. Priorhelperfixtureoutput regeneratedduringhelperchecks (diagnosticfixtureonly), originalnativecapsules/raw/sourcefreezesretained.

Runtime12 currentmain gatecomplete:1305CPU/3native-deselected0 (92.55s),fault4pass0,source-only0,nativeDuDe3pass0,202selectedsourcehashmatch0; `runtime12-verification/exits.json`. IndependentSolHigh combinedACCEPT `runtime12-integration-review/review.md`:26/26combinedlive/copyhashesunchanged; region64focused+23independent0; goal91focused+11independent0, exact300ms/+1ns/futureTTL/paused/closing/sourceclock/callbacknegativecases. CPU-DONE beforenative.00802native12smoke60s nowrunningaloneGPU, sourcefrozen; campaignnotfrozen. Preparedcampaign12scripts choose90sper4slots beforefreeze because observed60s rawconservativereservations~.46–.58GB againstunchanged1GiBarchivecap; old120/180prototypesneverexecuted,90snotyetlaunched. Needactualuseful/region/membershipsmokeevidencebeforefreeze.

Native12-00802completed/exit0/clean:1138rawcomplete,11durableoffers/11realobjectevidencecommits,RSS577/577/GPU62/62complete,noinvalidproof;frontierlowerbound.061049325m, noacceptedregion/membership. Actualfeedbackeventsreportoriginalc72goal/map63/world[2.575,5.325] thenalternativeIDs:17geometricstopsvs385no_frontiers, no inventedmovement. Regionclient remainshealthy; every retainedcurrentringcorrectlydomainrejects(simple/nonzero), noerror-statepoison. Thus softwarecorrectionsworkbutscene00802stillinsufficientdemo, notthresholdbug.00861native12smoke nowrunningaloneGPU.

Mainopened finitegeometric-onlyqualification preparation onexisting00770then00337underapprovedModeA, fixed25candidates/cardinalheadings, no detector/performance/semanticoutcomeselection. PriorstrictCcontactqualificationnotModeAcompatibilityproof. Newagentprepare/readonlyuntilcurrentGPUquiet; no actualqualificationrun/configchange yet. CampaignhasNEVERbeenfrozen; selectedsceneprofilesmaybefinalizedonlyfromsafeobservationalgeometry, notrerun-bestbenchmark. Allassetsalreadyexisting/no download, sourcefoldersremainreadonly.

Native12-00861completed/exit0/clean:858rawcomplete,16durableoffers/16detectorcommits/8objectevidencecommits,RSS526/526/GPU61/61complete,noexecution/invalidprooferrors; frontierlowerbound.957119222m at60s (not>1, priornative11>1cannotreplacecurrentresult), acceptedregionbutnoassignedmembership. Movementcontinued, allnative12scene00802/00861artifactsretained; summaryfilespinactualdifferences. Geometry-onlycandidatequalification00770→00337 nowownssoleGPUafter00861ended, fixedlegacy25queryorder/cardinalheadingpolicy; legacyboundsY+.5spawnfilter supersededbyfiniteXZsnap≤.02plusactualsinglefloorcal/currentRGBDgate, NOTbyloweringnative.05plane orrobot/TTL. No newpipeline/modelworkload/campaignuntilqualificationreturns. Scene00802currentunsupportedusefuldemo keptaspreparationfailure, notexcludedfromhistoricalevidence.

Qualification harness issue retained: firstvisited00770candidate5/yaw0 geometryfails1m (98/98footprint,222/318corridor,159/200nativecontacts), thenJSONNumPyint64serializationfailed; originallog/script retained, failedrawalreadyremovedlimitationdisclosed. Primitive/checkpointfixcontinuednextheadingfixedorder,no recaptureselection. Subsequentvalidfloorbutclearance235/318,yaw180,native200/200hintedcamera visibility horizon. Mainidentifieditsownoverstrictprequalification: currentdowncameraH≈2m/FOV120 cannotobservefull1mforwardcylindertopheight1.5m+radius.25inoneframe. SentSTOPv1aftercurrentprocessclean; agentmustderiveactualK/Tfrustumbound. Proposedv2 usesEXACTexistingruntime.3mcorridor +footprint100%, retainsfixedY.05/native1mcontact-onlycheck. ThischangesONLYofflinequalificationpredicate toactualruntimecontract, notproductgate/camera/TTL. Movement>1mneedsmultiframefreshdepth. Allv1failuresremainretainedunderoriginalpredicate; no detector/performancebenchmarkselection. Awaitagentanalyticcheck+v1CPU-DONEbeforev2authorization.

Qualificationv2complete/exit0 after3fixed-orderposes; selected00770candidate5/nativeyaw180, currentfootprint98/98 and.3mRGBD164/164, separate1m/200nativecontactqueriesallpass/Ydiscrepancy0. Mainpolicyv1mistakepreserved: static1mvisibilityoutsideactualfrustum0/24, actualcandidate5/yaw90reach.782mvs1.25mneeded; v1stopped25poses/no00337, serializationfailure/exit130stop/rawlosslimitsreported. V2report/selectedraw/calibrationplus29pinsverified0, allprocessesreaped. `planar-scene-qualification/profile-fragment.json`/report.md. Sourceproductunchanged.

Maincreatedfourruntime13configs00770+00861×seed0/1, allvalidate0;00770floorZ.0047795772552494675, initial[-7.492470741271973,.10685312747955322,11.001004219055176], yaw180quaternion, calSHAec1b177f5fb878a18e9cdb96aa77d95cd1178839f772d9348a486c3711672dc0. Existing00861recipeunchangedexceptepisodeID. Fresh00770actualSimulator≤5mmpulse4.9543381mm/Yexactunchanged/hostproof0 (`planar-native-runtime13-00770/`). New00770pipeline60ssmokenowrunningaloneGPU, no campaignfreeze. Needactualdetector/usefuldistance/regionmembership/resourcecompleteness; qualificationnotactualmotion/terraincertificate.

Native13-00770completed/exit0/clean:958rawcomplete,6durableoffers/6detectorcommits/2objectevidencecommits,RSS562/562/GPU62/62complete; acceptedregionbutnoassigned; frontierlowerbound.322317527m. No invalidproof/source/workererror. Detailed `live-smoke-00770-runtime13-diagnostic-summary.json`. Guard475bootstrapready,464tracking/11align;463forwardactionsrequested2.015705483m,387actualzero, actual.322317527m. Newread-onlyboundeddiagnosis assignedtoqualificationagent(runtime13-translation-diagnosis),≤3actualnativefilterqueries/oneSimulator onfirst3zeroproofs, distinguishcontact/Yslab vsfloatcanonicalendpointveto. Sourcecodeunchanged1305gate; no campaignfreezeorbenchmarkrerun. No furthergeometric/room/TTLgaterelaxation authorized.

Runtime13translationrootcauseconfirmed bybounded3actualnativefilterqueries/oneSimulator, noact/step/execute: all3 candidates equalnativeendexactly,Ydiff0,XZfraction1/residual0; case1 lateral1.516e-7 +normovershoot2.347e-7; case2 lateral2.227e-7; case3 normovershoot2.013e-7. Quaternions recoveredasonefloat32pairper129²localsearch matching savedcanonicalyawexactly, globalnormuniquenessnotclaimed. Detachedcorrectionpredictmatchesnominalendpoint. Read-onlydiagnosisexit0/closed at runtime13-translation-diagnosis/. MainauthorizesModeA-only32descendingdistancepreflight withinCommandupperbound, no nativepointinterpolation/epsilonchange/trialaction;contractclarified. Writerownsworker/newtest +fakepreparefixtureupdatesonly, TDDongoing. Current1305fullgatevalidonlyprevioushead; newreview/fullgate/native14required. No campaignfrozen/launched.


### Latest status for user / runtime14 freeze

Main adopted final on-disk worker after author usage-limit interruption, not author report completion. `runtime13-translation-fix/focused-final.log`:207passed/exit0; `host-matrix-validation.json`:259/259 unchanged host-proof validations/exit0,106positive/132preparationveto/21postfilterzero. Actual first3 ratios in pinned artifact .90625/.875/.84375 supersede preliminary agent message .96875/.875/.875; timing-derived requested amounts vary and artifact is authoritative. No native Simulator or performance claim from detached CPU matrix. Writer and artifact-helper both hit account usage limit, reset announced Oct29 00:21 local; no rerouting/retry to bypass quota. Independent SolHigh review for new delta remains pending.

Main frozen checkpoint `runtime14-checkpoint/manifest.json` SHA ad300ca6d43b5fc8b126de2ac738a1d645d0fc31e8d97307e4bf7a88c79d1343, worker4dc00794b421e08e0f4b91b04be794e212ef072118854f3ccd802de43ca48a29; fourprofiles14 generated, not run. Main full gate `verify_runtime14.py` launched; result pending at this checkpoint. Prior1305 tests certify runtime12 only. No native14 job or frozen acceptance campaign. P10 remainsin_progress: native latest profile review/fullgate,>1m each of4slots,real object membership evidence and final campaign review missing. Existing simulator technical demo works; unattended/3Dphysical validation unsupported.


Runtime14 main verification completed: `.venv/bin/python -m pytest tests -q -m "not native"` →1334passed/3deselected/exit0 (93.49s); fault4pass0, source-only0, nativeDuDe3pass0,202selected sibling-sourcehashesmatch0. `runs/p10-native-preparation/runtime14-verification/exits.json` retains commands/exits. Fourprofiles14 load_config validated/exit0. No source change during full gate. IndependentSolHighreview remains pending after usage-limit interruption; no native14 pulse/smoke or campaign. Thus current software tests pass, runtime/useful membership acceptance remains unproven.


User-requested visual demo command: main created `configs/p10/demo-ui-00861.json` from frozen runtime14 scene00861/seed0, separate episode and enabled existing Qt process with pinned host interpreter/ui_transport script. CLI preflight `PYTHONPATH=src .runtime/host/bin/python -m neusymnav.cli preflight --config configs/p10/demo-ui-00861.json` →readytrue/issues[]/exit0. No simulator/GPU/UI launched by this check; real-display operation still unverified, no campaign or P10 acceptance claim.


### User-requested NewOH3DSG-style UI refresh

Main implemented presentation-only dark navy3panel RGB/occupancy/scenegraph layout, graph/tree tabs and object selection, green/red/distinctunknown map, responsive captions, scrollable evidence details and collapsible source diagnostics. New scene_graph.py caps300nodes/1200links and never invents assignment edges; pose/path/detections unavailable in DTO are not fabricated. UI process/immutable publications/control ACK contracts unchanged. Sibling sources read-only. `runs/ui-refresh-20261028/manifest.json` pins files and reference assets; report.md explains scope.

`QT_QPA_PLATFORM=offscreen PYTHONPATH=src .venv/bin/python -m pytest tests/test_scene_graph_ui.py tests/test_ui_offscreen.py tests/test_ui_transport.py tests/test_display_snapshot.py -q`→22passed/exit0; source-only packaging→exit0. Real retained demo publication rendered at1440x900/1100x720 withstale label (actual label STALE PUBLICATION), before/after PNGs retained. No new simulator/GPU execution or real-display confirmation, no claim P10 complete. Prior1334fullgate precedesUI delta; this slice verified focused22 only. Existing demo command/profile unchanged; restart UI to load presentation.


### Measured robot / trail / FOV UI overlay — user request

Main implemented optional immutable RobotTrack/RobotSample/CameraCone display DTOs, nonblocking1024sample capture observer using EXISTING alreadyvalidated body proof (no new sensor IPC), exact pinned-map source/time/clock selection and bounded typed IPC. UI paints measured robot/heading,1.3px sampled trajectory with missing/gap breaks, RGBcalibrated azimuth fan (1m schematic only), brighter occupied red; unknown/free and safety/TTL unchanged. Camera origin independent from body origin, marker grey/STALE after300ms. Old UI packets missingrobot accepted asNone. New source: `visualization/robot_overlay.py`; docs `ui-map-overlays.md`.

Retained actual demo raw+measurements reconstruct430samples with matched navigation source and actual primarycalibration; preview-historical.png explicitlySTALE, no new simulator/native run. Focused84pass0 (`runs/ui-map-overlay-20261028/verified.log`). Initial fullgate3failed/1347passed/3native-deselected, all3stale shippedUIworkerhashpins; fixed5activeYAMLpins anddemoJSON, original configs/logsretained. Finalfullgate running separately; no inference of P10 acceptance/currentnativevalidation.


UI map overlay final main gate:1350CPU passed/3native-deselected/exit0 (94.55s); source-only packaging exit0; logs/commands in `runs/ui-map-overlay-20261028/final-exits.json`. Focused84pass0 and postpin48pass0; demo preflight readytrue/issues[]/exit0. Source/test/config/overlay-contract snapshot frozen inmanifest.json. Initial3pin failures retained, all corrected; no product source edits during final fullgate. User can restart existing demo command/profile for robot/trail/FOV. NativeSimulator/live-display validation on this new overlay not performed; preview is historical real measured data. P10 remainsinprogress.


### User realtime concern — read-only audit

`runs/realtime-audit-20261028/audit.py` exit0 analyses all3retained demos includingincomplete, no newnativeworkload/sourcechange. Latest213409:observedfrontierlowerbound.929918659m/60s requested;363proofrows/58.891s→6.147Hz observedproofcadence;depthagemedian149.991/p95202.239ms.316forwardactions/0zero,median2.760862mm,positivecommandvmedian.06m/s. All316mixedyaw; worker splits≤100msacrosstwooperations,forwardequivalentmedian44.743ms.8detectorcommits,all-populationcapture-returnp5071.645ms/p957311.146ms includesstartup/smallsupport, notwarmsteady-state.2missingproofsretained.

Realtime whole-system remainsUNPROVEN; maintainedsafety/data-integritytests do notcertifylatency/liveness/semanticaccuracy. Serialcapture/raw/mapwait/control andsplitpulsebudget explaincontributingstructure, notindividuallytimedcosts. NewrobotUIoverlay hasNO freshperformanceclaim. report.md/report.json captureevidence/limits; do notnarrate1350CPUtestsasrealtimeacceptance orrelaxTTL/proof/geometrytoaccelerateappearance.


### Realtime optimization active — user target ≥10Hz

Read-only native baseline30s (`realtime-fix-20261028/baseline-native`) exited1/incomplete solelyresource support; clean shutdown/rawcomplete, no runtimefailure. Observedmap p5052.09ms,Navigator38.08ms,guard9.92ms,mapwait64.51ms; rawappend.02ms. Initial sandbox attempt failedsensorEOF, preservedbaseline.log; outsideGPU nativeattempt distinctfolder. No rerunbest/frozenacceptance.

Main TDD exact-content immutablefootprint reuse (100duplicatecomputationsRED→1GREEN), optionalraycast_workers1–4 withdisjointNumba masks/globalbounds/ORthenoccupiedwins, percallexecutorjoined and64MiBparallelcap. Default1retained. Fullraycount/samplingstride/robot/TTL/command/proof unchanged. Importantexistingproofv1sumduration100ms retained; notsilentlydoublingmotionauthority. 85focusedpass0,24actualrecordedframes complete tile/logodds bytes +snapshot parity1/2/4workers (`exact-mapping-four.json`); CPUmap medians49.9/32.7/24.0ms. Some helperfailuresretained: profile.pyshadowedstdlib, NaNequalityfixture, fourworkerscriptlist/syntaxediting mistakes, all corrected before native. Sourcecheckpoint notyetfullgated/reviewed.

Userexplicitlychosecontrol≥10Hz plusp95/p99/deadline misses viaasyncanswer. Contract/measurementdescription `realtime-runtime-profile.md`. Prospectiveconfigs/p10/demo-realtime-00861.json fourworkers; optimized30s native instrumentedpreparation runningsoleGPU afterCPU-DONE. Nativeafterresult/currentfullgate/reviewpending; no realtimeorP10acceptanceclaim.


Realtimeintermediate30s4workerscompleted/exit0/clean/raw/resourcescomplete;9.702855Hz,intervalp95140.239ms/p99158.464ms,110/282>100ms,frontierlowerbound.737292445m. Not10Hz,notacceptance. Allsourcepins/stagesretainedoptimized-four-native/.

Furtherdiagnosis:NavMapper25.29msbutmapwait45.79ms, navigationarchivescansrawtreeeveryframe despite noarchivewrite. TDDarchive-reservation3newcasesRED→GREEN;60relatedpass0 (`archive-green.log`). Originalconservativequota movedimmediatelybeforeBOTHactualarchivewritepaths;nativeNavMapperexacttype bindsonecontextbeforethreadsstart, old/custommappersretainperupdatefallback. No stalequota cache/noarchivewritewithoutcheck; quota denialbeforeactive-tile/maprevisionmutation verified. Newoptimized-archive-native30spreparationrunningsoleGPU, sourcefixed;fullgate/reviewpending.


Archiveoptimized30scompleted/exit0/clean/raw/resourcescomplete but9.909064Hzstillbelow10;intervalp95141.407ms/p99155.230ms,111/287>100ms; lowerbound.756557969m. Nativeafterarchive preserved (`optimized-archive-native/`), notroundeduporaccepted. Sourceprofilingnowmapwait31.94vsmapper30.96ms confirmsremovedredundantscan;Navigator31.7msremaining.

AddedTDDsingle-entry exacteroded-graph wavefrontreuse withcurrentrevisionreconstruction andbounded65goals/65536pathcells. Originalsingle-goalAStarindependentoracle, changedblockededge/contentinvalidates.30focusedpass0 (`wavefront-green.log`),80actualrecordedframeNavigator decisionsidenticalcachevsforce-recompute, heap operations25276vs42632 (`navigation-reuse-parity.json`). No path/clock/freshnessauthoritycached. New30soptimized-wavefront-nativepreparationrunningaloneGPU, no claimuntilresult.


Realtimesnapshotfinalmain gate1377CPU/3native-deselected0(85.89s),fault4/source-only/nativeDuDe3/source202all0;97Pythonfilehashesunchangedduringgate (`realtime-fix-20261028/gate-exits.json`). Finalcachekeyprimitives/blockedsetsfixTDDretainedin cache-key-red.log/current-focused.log. Fixed2seed×30s realtimeconfirmation frozenbeforelaunch (`confirmed-batch/frozen.json`,SHA409c0238facda4dc9dae8bb7d37f6ef2ebf5e981998b5f086141b2b3158ad8aa),once/slot,alloutcomeskept. BatchrunningsequentialsoleGPU;notP10campaign. IndependentSolHighreview remainsunavailablefromaccountusage-limit, notself-certifiedor bypassed.


Firstfixed2slotRTconfirmationcompletedboth/exit0/clean/raw/resourcescomplete, seed/config binding productionevaluatorpassed0. seed0:10.803548Hz,p95127.865/p99133.206ms,119/314>100ms,frontierLB.827051322m;seed1:11.566983Hz,p95118.385/p99122.394ms,89/337>100ms,LB.790679936m. Frozen97-sourceheadcopiedinconfirmed-batch; no harddeadlineclaim. Since26–38%intervals>100ms, maincontinuesjitterfixratherthanstoppingatmeanthroughput.

OptionalGILfreeNumbaDijkstra preservesexactheap(serialties),neighbororder,corner/blockededge/budget andpathreconstruction; no fastmath or alteredsource/guard/actuatorproof. Pythonfallbackforunsupportedtypes/sizes/withoutNumba;preparecompilebeforefreshcontrol. Mandatoryactualhost300caseexactdifferentialpass0; retainedcase84noncanonicalreverse-edgeRED→Pythonfallbackfix.80recordedframewholeNavigator decisionsidenticalJIT/cachevsPythonrecompute,heap0vs42632.31focusedpass0. Newfullgatejit-final-gate1379CPU/3native-deselected0(90.12s),fault4/package/nativeDuDe3/source202all0;98sourcepinhashesstable. Final2seed×30sRTbatchfrozenSHAabd3afbf24b6e04329897f361eb61056bded2a9e604b01d3ccc01c8efa551d01, runningsoleGPU,sequential/once/slot. Oldbatchespreserved; P10notclosed,independentSolHighreviewstillpendingaccountquota.


### Realtime final main checkpoint — 2026-10-28

Implemented: exact-content immutable footprint reuse; opt-in raycast_workers=4
(full rays, exact reduction); archive quota reservation at actual writes; bounded
wavefront reuse; optional stable GIL-free Dijkstra with Python fallback. No TTL,
footprint, unknown/free, source one-use, speed or proof-v1 relaxation.
Correctness: 24 recorded map frames bitwise identical at workers 1/2/4;
300 randomized exact planner differentials; 80 full recorded navigation decisions
identical. Fresh gate 1,379 CPU / 3 native deselected, fault 4, native DuDe 3,
source-only packaging and 202 sibling hashes all exit 0; 98 source pins stable.
`runs/realtime-fix-20261028/jit-final-gate/gate-exits.json` retains exact commands/exits.

Runtime preparation: fixed 00861 / seeds 0,1 / 30 s each executed once; completed
2/2 / exit 0, raw/resources complete, clean shutdown, no sampled cap breach.
Strict evaluator execution binding passed both (exit 0), actual seeds/configs pinned.
Mean invocation cadence 11.181 / 10.503 Hz; interval p95/p99 124.653/135.205 and
131.239/146.490 ms; deadline misses 80/327 and 114/306 (>100 ms).
Observed frontier lower bounds .845564 / .794027 m, actual detector commits 6/6,
object evidence commits 5/3. Control reasons remain explicit: seed 0 executed324,
expired-or-zero2, yaw-preflight-unavailable2; seed 1 executed305, expired-or-zero2.
All exploratory failures/incomplete runs and preceding fixed batch retained.
JIT did not consistently reduce native jitter relative to preceding cache-only
batch; no standalone native speedup claim. Active invocation cadence excludes
startup/shutdown; Qt offscreen, not real-display FPS or semantic update cadence.

Artifact: `runs/realtime-fix-20261028/{report.md,report.json,manifest.json}`;
final frozen envelope SHA256 abd3afbf24b6e04329897f361eb61056bded2a9e604b01d3ccc01c8efa551d01.
`bash -n tools/run_realtime_demo.sh` and `bash tools/run_realtime_demo.sh --preflight`
exit 0 (ready true); wrapper launches new profile on actual desktop when invoked.
Status: implemented / main correctness-verified / bounded native preparation measured;
stable >=10 Hz, sustained real-display timing and P10 acceptance remain unproven.
Independent Sol High review still pending account usage limit; main is not its substitute.


### UI theo NewOH3DSG / lớn hơn50% — 2026-10-29

User explicitly requests whole UI redesign against NewOH3DSG plus bbox/mask and
larger demo. Implemented preferred2160×1350/screen-capped/maximized,15pxbasefont,
largeRGB/mapworkspace+widegraph/evidencedrawer, focus controls, separate detector
observation/liveRGB tabs, box/mask toggles, measured graphlabel spacing. Existing
maprobot/trail/FOV, aliases and commandACK preserved. Source siblings readonly.

Main added immutable bounded DisplayInstance/DisplayObservation, graph-lane
read-only committed asset reader withSHA/source/geometry/clock/processed-frame
binding,64instances/8MiBmasks countedinside32MiBenvelope. Cacheone, no extra
inference/sensor/controlwait; oldoptionalwirefields decode.8activeUIworkerhashpins
refreshed, originalconfigsretained. No historicalrun manifest changed.

Fresh final `QT_QPA_PLATFORM=offscreen PYTHONPATH=src .venv/bin/python -m pytest tests -q -m "not native"`
→1388passed/3native-deselected/exit0(86.89s); source-only0, demo-preflight
readytrue/issues[]0;202selectedsiblingshashmatch0.100sourcefilehashesstable.
Independent SolHigh scopedreviewACCEPT51pass0 + graphfollowupACCEPT10pass0;
all9reviewedfilepinsstillmatch. CPUcommitted-source→actualQtchildpublication
smoke0/cleanshutdown, detectorframe0/liveframe2 distinct. Actualrecordednative
primary-rgbd:309 reconstructedbox/mask previews at2160×1350/1440×960 andfocus,
explicitSTALE/frozenhistoricalpresentationclock, no newnativebenchmark.

TDD/visualQA retainedinitialrenderRGB32stridefailure andtall-upscaleboundRED,
fixedexplicitRGB888conversion+boundedupscale; initialgate1failed1385passed and
pregraphgate1387passed preserved, final1388iscurrent. Actualgraphlabeloverlap
RED→GREEN. Firstfixturepublicationprocessedframemismatchcorrectlyomittedoverlay;
correctedhelperseparateconfirmedfolder, notproductrelaxation.

Artifacts/commands/exits/hashes/sourcecopies:
`runs/ui-new-reference-20261029/{report.md,report.json,manifest.json,exits.json,snapshot/}`;
review/review.md andgraph-followup.md. Design/sourcebinding docs/ui-reference-refresh.md;
run `bash tools/run_realtime_demo.sh 60` afterrestart. Implemented/correctness-verified;
UIliveinteractive/sustainedtiming, newnative/realtime andP10acceptance UNPROVEN.
Prior10Hzmeasurementsapplytopriorfrozenhead, notthisUIrevision. No model/data
install/download/training/commit/publish; pipeline safety/TTL/proof unchanged.


### User-requested YOLOE-26m / actual640×480 — 2026-10-29

Implemented new active profile `configs/p10/demo-yoloe26m-640x480-00861.json` and
wrapper default20s. PrimaryRGB AND matchingdepth640×480, imgsz640; navdepth240×180,
threshold0.25,max30,taxonomy,sourceTTL,footprint/proof and caps unchanged. Native
camera audit confirms actualK/pixel-centre scaling, changedprimarycalibration,
unchanged navcalibration. New/nonempty committed masks640×480 validate with exact
source/geometry/SHA. ProductionPython100files unchanged.

User explicitly approved isolated runtime smallpackage install. Current
`.runtime/detector26/bin/python` imports ownUltralytics8.4.24 (checkpoint producer
version), reuses oldTorch2.7.1cu126/NumPy1.26.4/deps through.pth. Oldenv remains
Ultralytics8.3.221. Initial8.4.0candidate preserved; both versions givezero outputs
on firstfixedframe. All59prompt embeddings match upstream bitwise on both, no
normalization/threshold/model fallback. OnlyUltralytics wheels1.1+1.2MiB downloaded;
no model/data/Torchdownload. Newenv~4.6MiB, shared dependencies require oldenv.
Staticuvpipcheck exit1 ignores.pth and reports12missing; retained honestly.
All12 actualmetadata/specifier/import checks pass0 from newruntime.

Fresh verification:100focusedCPU pass0 (1.90s); cameracaptureaudit0, matchednative
workerinference0, promptparity0, nativebatchmaskaudit0, productionevaluator
executionbinding0, preflightreadytrue/issues[]0, shellsyntax0,202siblinghashmatch0.
Fullsuite1388 belonged to preceding UI checkpoint; unchangedsource noted, not
rerun/claimed for newruntime. Independent review tracked in checkpointreport.

Native30s once:incomplete/exit1 due1GiBrawquota,380/381written,1diskrejection,
resourcescomplete/cleanupclean. Mean7.083Hz,p95168.644/p99177.574ms,186/187misses.
Prospectively bounded20s afterquota diagnosis:completed/exit0,raw292/292complete,
resourcescomplete,no sampled cap breach/cleanshutdown/UI0drops,4detector commits,
2objectevidencecommits,1canonicalobject,acceptedregion/noassignedmembership.
Mean7.388Hz,p95165.476/p99173.716ms,142/142intervals>100ms. Profiler retains
aggregates, notrawinvocationstartvector; notaccepted-motion/semantic cadence.
Bothoutcomes retained;20s isdemovalidation, notshortenedP10campaign acceptance.
Default20sfitscap; longerrequests mayhitquota, never silentlydroprecording.

Confidence gain UNPROVEN:20s outputs wardrobe0.3565/door0.3424;30s outputs
door/clock0.405–0.425. Fixed initial640frame old11s had6outputs incldoor0.591,
new26m0; no accuracycomparison fromunmatched trajectories/confidences. No hidden
threshold/vocab tuning orbettersample selection. P10 and10Hztarget remain unmet.

Artifacts: `runs/yoloe26-640x480-20261029/{report.md,report.json,manifest.json}`,
per-run summaries/stageprofiles, source/configfreezes, runtime-source-pins,
actualrecipe/seed/resolutionbindings, historicalSTALEpreview640×480. Installed
packagechecked in ownruntime; sibling source/modelassetsreadonly. No system
install/training/commit/push/publish. Run `bash tools/run_realtime_demo.sh 20`.


Independent SolHigh scoped profile/runtime review **ACCEPT**:
`runs/yoloe26-640x480-20261029/review/review.md`. Fresh independent audit exit0;
5reviewpins+100productionhashesstable; own8.4.24 import precedence,sharedoldTorch,
12dependencies and332installedRECORDhashesverified,all8committedbatch/sourcepairs
and16assetSHA/exact640×480masks/K/calibrationvalidated. Oldruntime/sourceinventory
retained. Reviewer explicitly does not certify10Hz,quality gain orP10acceptance.


### NewOH3DSG 10-minute/control comparison — 2026-10-29 (audit only)

Implemented: documentation and retained evidence audit only; production Python
100 files match the previous native freeze. No config/wrapper/runtime changes,
new dependencies, downloads or native/GPU workloads. Sources remain read-only.
Correctness-verified: retained New control CSV/statistics and recording inventory;
CPU probe confirms two capture calls draw/read all three sensors twice (six
operations), and four lossless NPZ diagnostic samples round-trip exact array
bytes/dtypes/shapes plus serialized Observation/provenance. This is not a new
production codec or measured runtime speedup.
Runtime-validated: no new run. Neu remains 20s demo, 7.388Hz measured previously;
10Hz and P10 acceptance remain unproven. New has genuine 600–900s ~20Hz average
logs, including mostly STOP runs; latest moving600s is14.31Hz and reported26m
300s is11.62Hz with adaptive480. Raw replay is absent in several long demos;
one enabled600s run is incomplete562/2357 primary observations.

Proposed direction: remove duplicate sensor rendering, separate fresh navigation
from slower RGB/semantic/UI work, versioned lossless binary recording with durable
and pending byte accounting, then bounded checks and a fixed600s measurement.
Keep source-one-use, TTL300ms, RGB-D/clearance/unknown/footprint/proof gates.
Duration currently capped300s; quota-only changes cannot enable600s. Current
full JSON replay estimates ~23.33GiB reserved at7.39 pairedHz /31.58GiB at10Hz
for600s; these are estimates, not disk measurements or approved final caps.

Commands: control/audit.py via python3 exit0; recording/audit.py via python3 exit0;
current/audit_current.py via PYTHONPATH=src .venv/bin/python exit0;
current/probe_render_calls.py via .venv/bin/python exit0. Initial helper error
exit1 retained in current/audit-first.log; recording initial python alias absent
exit127, rerun python3 succeeded. Aggregate freeze/hash verification exit0.
Artifacts: docs/new-reference-runtime-audit.md and
runs/new-reference-runtime-audit-20261029/{report.md,report.json,manifest.json},
control/, recording/, current/. No 10-minute Neu run or20Hz achievement claimed.


### Long-demo implementation checkpoint — 2026-10-29 (native600s active)

Implemented: opt-in runtimecadence(primary5Hz/navtarget20Hz), selective sensor
rendering/source-bound pose transaction, NPZ v2 lossless replay/backwardv1,
durable+pending accounting, fixed coveredarchive quota, explicit600s profile and
wrapper tools/run_long_demo.sh. Fixed640/26m, freshsourceone-use/TTL300ms/guard/
footprint/proof unchanged. Legacy default300s/JSON/caps remain.
Correctness: finalCPU1507pass/3native deselected exit0 (94.52s); hostNumba
raycast/navigation40pass exit0. Independent recording ACCEPT75, runtime254,
quota80+6, evaluator172 after twovalidmetricpolicyfindingsfixed.
Artifacts runs/long-demo-fix-20261029/ reviews, red/green logs and snapshots.

Native initial20s diagnostic used wrong .venv(noNumba): incomplete1.232Hz, raw52/52
complete but resources incomplete/noactuation. Retained; corrected runner to
actualdemo .runtime/host(Numba) without source/configchanges. Matched20s completed
exit0, raw270/270/125001271bytes complete, control190calls/9.662Hz, interval
p95143.648/p99169.340ms,111/189>100ms; usefulmotion endpointlowerbound0.435m,
187acceptedcommandproofs. Offline strict exports/measurement/seed/runtime/source
binding and fullrawread audit exit0. This does NOT meet10Hz or P10.

One fixed600s native validation started with same reviewedsource/config.
Results pending; don't rerun this in parallel after compact. Session10736,
log runs/long-demo-fix-20261029/native-host-600s.log. Frozen106pins under
host-native-freeze/. Finalsummary notyetavailable; no600s/10Hz/20Hzclaim.

Long-demo follow-up: prior600s run is finished, not active. Duration600 achieved;
raw5732/5732 complete3.303GB and715validproofs/1.877m endpointlowerbound, but
control5.716Hz andRSS19unsupported samples =>incomplete. NativeUI2candidate20s
achieves10.038Hz/raw283complete/resourcescomplete, but finalexportincomplete due
using throttledUI nav withnewer canonicalhierarchy. Canonicalpair fix implemented
108focusedpass; review/fullCPU pending. Current evidence/logs remain under
runs/long-demo-fix-20261029. No native workload active at this checkpoint.


### Long demo final checkpoint — 2026-10-29

Implemented: optional multirate selective sensor rendering/capture-bound pose,
NPZ v2 lossless full replay with durable+pending accounting, coveredarchivequota,
explicit600s profile/boundedmeasurement, UI2Hz earlycoalescing and canonical
hierarchy+nav export independentofUI. Fixed640×480/YOLOE26m imgsz640; primary5Hz
request/navigation20Hzrequest; sourceone-use/TTL300ms/RGB-D/unknown/clearance/
footprint/command/proof unchanged. New publiccommand `bash tools/run_long_demo.sh 600`; legacyprofile/defaultcaps remain available.

Correctness-verified: wholeCPU1536pass/3native deselected exit0(90.61s); source-only
package0/101Pythonfiles; hostNumba40checks0. IndependentSolHighACCEPT reviews
recording75,runtime254,quota80+6,evaluator172,UI59+5,canonicalexport103+3. Red
reproductions/fixes retained. Preflightreadytrue/issues[], final108pinsstable.

Runtime-validated for this single-scene/seed600s demo: finalnativeexit0/completed,
12612/12612fullraw(2609primary480×640+10003nav180×240),4462911063bytes, no gaps/
rejections/quota breach. Fullofflinepayload/export/source/proof/seed+effective
recipe auditexit0/errors[]. Officialproduction10001invocations/10000intervals:
16.6782718Hz,p9593.8302507ms,p99138.5388281ms,327>100ms(3.27%),5312>50ms(53.12%).
Allfive120swindows mean>10Hz; controlincludesSTOP/pending, notmotion/detectorHz.
1455validproofs (includingzeroaction), observedendpointtranslationlowerbound
1.95476m,51detector/33objectcommits, acceptedregion/noassignedmembership. RSS
5040/5040valid samples, sampledpeak2821062656B;GPU547356672B, resourcescomplete,
cleanworkers/shutdown/UI0drops8871coalesced. Qt offscreen timing only.

Earlier wronginterpreter20s, below10Hzhost20s, incompleteinitial600s (fullraw but
RSS19unsupported andlowcadence), andUI2candidate20s(finalexportmismatch) retained
andnotpromoted. Fixes: correctactualhostinterpreter,UIearlycoalescing,RSS1s/.2
boundedretry (criteriaunchanged), canonicalexportpair. No extra download/install,
sourcefoldermodification/training/commit/push/publish.

Artifacts: runs/long-demo-fix-20261029/{report.md,report.json,final-native-freeze/,
native-ui2-600s/,review-*/}, docs/running.md, tools/run_long_demo.sh. Mean10Hz
demo targetmet; hard20Hz/100msdeadlines notcertified. P10 remainsunaccepted:
fullfrozencampaign andassignedroommembership outstanding; planaradapter doesnot
model3Dgrounding/terrain. Noaccuracy/confidencegainclaim. No nativejobactive.

Final independent native SolHigh review ACCEPT in
`runs/long-demo-fix-20261029/review-final-native/report.md`:108frozenpins/101source
pins stable; independently recomputed official timing/proof/rawinventory/export/
resource gates match. Main fullpayloaddecode audit0 pinned.45selected sibling
source/artifact hashes unchanged. Scope remains one600s scene/seed,mean>=10Hz;
noP10/hard20Hz/continuousresource/physicalgrounding/qualitygain certification.


### GitHub source publication preparation — 2026-10-29

User authorized setup/commit/push to https://github.com/hiiluo/NeuSymNav.git.
Existing repository is public and empty; SSH authentication as hiiluo succeeded.
Implemented: main/origin setup, runtime/raw/model/native-upstream exclusions,
portable exact-byte regression fixtures, dev dependency group, pinned read-only
CPU CI, exact-index heuristic payload checker, portable live config template and
clone/runtime/licensing guide (docs/github-setup.md). No blanket project license
asserted; restricted/unresolved native closure stays local. Source repositories,
production source and model/data assets unchanged; no install/download/GPU run.

Correctness-verified: index-export source-only tree (initially without runs,
.runtime, .venv or native upstream), using existing host Python dependencies:
`python -m pytest tests -q -m 'not native'` =>1540 passed/3 deselected, exit0,
92.93s. Source-only payload checker, CLI help and fixture preflight each exit0.
Independent Sol Medium packaging review ACCEPT: 339 staged files/3050298 bytes,
4 fixture provenance matches, 101 production source pins stable, 4 checker tests
pass. Exact-index heuristic scan findings=[]; not comprehensive secret/license
certification. Six existing blank-EOF warnings retained to preserve source pins;
other whitespace checked separately before commit.

Artifacts: runs/github-setup-20261029/{source-only-command.json,
source-only-full-suite.log,source-only-exit.json,source-only-extra-exits.json,
payload-staged.json,review/}. Guide: docs/github-setup.md; public runtime summary:
docs/results/long-demo-2026-10-29.md. Commit/push and remote CI verification are
next; this checkpoint does not claim remote CI success or fresh-machine native
readiness. Prior runtime/P10 limitations remain unchanged.
