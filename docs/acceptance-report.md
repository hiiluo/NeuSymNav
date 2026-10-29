# NeuSymNav — nghiệm thu core

Ngày: 2026-10-27. **Verdict hiện hành: incomplete / insufficient demonstration.** P00–P09 đã qua correctness gates; P10 evaluator/GT-isolation fix-round1 đã được review độc lập ACCEPT. Phần mềm chuẩn bị native còn tiếp tục; chưa có nghiệm thu pipeline native.

## Kết quả đã có bằng chứng

| Gate | Kết quả hiện tại | Evidence |
| --- | --- | --- |
| Contracts, identity, replay, freshness, recovery | P00–P09 correctness-verified trên CPU; review findings đã sửa | implementation-status.md; execution-ledger.md |
| CPU regression trước P10 | 520 passed, 3 native deselected, exit0 | runs/p09-main/fix-round1/cpu-exit.json; cpu-confirmed.log |
| CPU tích hợp P10 fix-round1 | 565 passed, 3 native deselected, exit0; focused45 và original independent8 pass | runs/p10-main/fix-round1/exits.json; cpu.log; focused.log; independent.log |
| P10 package isolation | Source-only verifier exit0 trên package fix-round1 | runs/p10-main/fix-round1/source-only.log; exits.json |
| Seed/source ACK | Scoped Sol High ACCEPT sau sửa deadline; main98focused+5independent pass | runs/p10-readiness/seed-review/fix-round1/review.md; runs/p10-main/seed/fix-round1/exits.json |
| Readiness base trước integration | Main631CPU pass,3native deselected,exit0;source-only0. Primitives review còn mở nên chưa đóng gate | runs/p10-main/readiness-base/exits.json; cpu.log |
| P10 v2 phần mềm (2026-10-28) | Implemented/frozen;787CPU,137focused,21retained probes pass0; source-only0;202source hashes match. Independent review còn pending vì quota | runs/p10-readiness/integration-v2/final/exits.json; manifest.json; report.md |
| P10 v2 pilot | Expectedexit1;1scene,2planned/0attempted/0completed/2missing; không native acceptance | configs/evaluation/suite-v2.json; runs/p10-readiness/integration-v2/final/pilot/report.json |
| P10 native pilot | 1 scene ×2 seed: planned2, attempted0, completed0, missing2; evaluator exit1 đúng với incomplete | configs/evaluation/suite-v1.json; runs/p10-main/native-pilot/report.json; pilot-fault-exits.json |
| Package isolation | Copy package chạy replay từ cwd khác; khớp object/event/source; không đọc code nguồn cũ | runs/p09-main/fix-round1/source-only-final.json |
| UI transport | Process Qt thật, offscreen, command/ACK; display thật chưa chứng minh | tests/test_ui_transport.py; runs/p09-review/fix-round1/review.md |
| DuDe native | 3 tests synthetic finite pass, exit0, source-built và candidate | runs/p10-main/native-tests.log; native-exit.json |
| P09 độc lập | ACCEPT sau sửa exporter coherence, deadline shutdown và template hashes | runs/p09-review/fix-round1/review.md |

Lượt CPU và DuDe trên là bằng chứng mới của NeuSymNav. Không cộng số test/milestone từ hai nguồn và không dùng fixture làm bằng chứng Habitat/model inference.

## Phần chưa đạt

| Gate | Verdict | Lý do |
| --- | --- | --- |
| P10 evaluator/GT isolation | scoped correctness verified | Sol High ACCEPT R1–R4;45focused+8original+6newboundary probes pass;43/43 snapshot records match. Evidence: runs/p10-review/fix-round1/ |
| Native runtime boundedness | not measured | Thiếu Habitat, torch/Ultralytics/OpenCLIP trong các interpreter đã dò; NVIDIA-SMI chưa dùng được |
| Native software readiness | incomplete | Seed/source ACK, primitives, actuation và wiring đã scoped review ACCEPT. Evaluator measurement/execution binder/export/suite v2 đã implemented và đang kiểm chứng/review tích hợp; chưa đóng correctness gate mới. Completed live v1 vẫn chặn thiếu proof |
| Useful core demonstration | insufficient demonstration | Chưa có detector commit thật cùng frontier translation >1m và accepted room/object membership trong native suite |
| Hai scene | incomplete pilot | Chỉ có một scene HM3D 00802 được pin trong inventory hiện tại; không tự tải scene mới |
| Appearance benefit | unsupported / optional | Chưa có compatible checkpoint inference và same-input GT identity comparison; không promote default |
| Real display / physical bootstrap | not validated | Chỉ offscreen UI; floor/body-clearance/5cm tolerance chưa được đo trong scene thật |
| Legacy comparators / quality | pending support audit | Không tạo comparator hay score từ artifact không tương thích |

Không chạy GPU campaign, training, extension E1–E4, tải model/dataset, publish hoặc commit. Hai folder nguồn chỉ đọc. Thư viện/môi trường mới chưa được cài.

## Bước cần có trước nghiệm thu native

Phải hoàn tất seed provenance và instrumentation phần mềm trước native acceptance; cài dependency một mình chưa đủ. Xem runtime-environment-proposal.md để xem trước môi trường sensor/detector tách biệt và dung lượng dự trù. Sau khi có môi trường đã cài, cần xác minh imports và asset hashes, khai báo floor calibration thật, đo downward coverage/body clearance, chạy smoke hữu hạn trước campaign đã khóa. Không tự nới TTL, giảm robot geometry hoặc bỏ run fail/missing khỏi denominator.

Pilot giữ cả hai missing attempts trong denominator 2; completion 0/2 không phải accuracy bằng 0. Latency, memory peak, frontier distance và các quality metrics thiếu support giữ null, không thay bằng số fixture. GT isolation replay và fault artifacts tại `runs/p10-protocol/`; manifest fix-round1 SHA `c6cb1a391f44629fd0627141e81c57f023bf830d7df5be85590ef8888419dd46`. Lượt CPU trước đó có một lỗi điều kiện chờ của test admission, đã tái hiện và sửa trong fixture; log thất bại vẫn giữ tại `runs/p10-main/cpu-final.log`, chẩn đoán tại `runs/p10-main/admission-diagnosis/`. Những mục pending không được coi là pass.

## Cập nhật native preparation — 2026-10-28

P10 **chưa nghiệm thu**. Các runtime dependencies đã cài riêng; GPU ngoài sandbox, real sensor/detector/region hoạt động trên tài sản hiện có. Checkpoint phần mềm runtime4:928CPU/3native-deselected0,4faultinjection0,package/source-only0,nativeDuDe3pass0,202sourcehashesmatch0; geometry/actuation/binder/resource deltas đã có review scopes tại runs/p10-native-preparation. Snapshot này chưa bao gồm fallbackRSSliveTID đang triển khai; không gán928pass cho source mới hơn.

Diagnostic00861 đã có real object commit và accepted region, raw recording đầy đủ, GPU support59/59 hoặc60/60. Chưa assigned membership, frontiertranslation lớn nhất được đo trong diagnostics gần đây~0.0884m, thiếu gate>1m. RSS vẫn thiếu sample và chưa chứng minh boundedness toàn run; không đổi thiếu thành0. Một runtime4 smoke thất bại với sensorclosed, lần25s và60s có ghi executeerrors không tái hiện lỗi; rootcause chưa được chứng minh/sửa. 4slotcampaign chưafreeze/launch nên không có denominator4đãthử hay nativeacceptance.

Navigation-depth120x160 qua initialbootstrap nhưng chỉ12/24yaw footprintready; không chọn profile này. 180x240 và240x320 đều24/24 trên sweep00861; medium profile cần calibration từngscene vàsmoke riêng trướcfreeze. Single-task zombieRSS proof đãSolHighACCEPT91+24+1tests0, nhưng leaderZcònliveTID vẫnunsupported; đangtriểnkhai bằngchứngRSSqua sharedMMtask riêng và sẽreview. ThreadRSS không đượcsum/ignoreunreadabledata. Các originalfolders/model/dataset giữ nguyên, khôngtraining/downloadassets.

Evidence hiện hành: [implementation status](implementation-status.md), [runtime4 checks](../runs/p10-native-preparation/runtime4-verification/exits.json), [closed-boundary review](../runs/p10-native-preparation/closed-boundary-review/round2/review.md), [zombie RSS review](../runs/p10-native-preparation/zombie-rss-review/review.md), [yaw coverage](../runs/p10-native-preparation/navigation-yaw-coverage-final/report.json). P10 vẫn `in_progress`; implemented/correctness scopes không thay cho native/runtime gate.

### Historical preparation checkpoint before native9 — 2026-10-28

P10 remains **in progress / not runtime-validated**. Scoped thread-RSS review accepted135focused+19independenttests, and optional semantic-sampling/RSS-acquisition review accepted68freshtests after a replay reselection P2 was fixed. These replace neither the full current-head CPU gate nor native acceptance. Capacity-mode replay is explicitly unavailable until exact selected-journal support exists; default replay remains supported. See `runs/p10-native-preparation/{thread-rss-review,sampling-profile-review}/review.md`.

The medium-nav180×240 calibration has ready footprint24/24tested orientations, whereas low-nav120×160 had12/24. The subsequent native60s diagnostic failed early at94frames. Preserved error shows yaw-proof validation rejection followed by client shutdown; it is not a clean run. Dedicated120turn native probe retained2rejected proofs with measured/configured-angle excess1.33469038e-7 and1.04786885e-7rad (unchanged epsilon1e-7),zero translation andno native execution errors. Installed CPU Magnum math reproduced all120nativequaternion outputs exactly. Conservative quantization-aware preflight is being implemented, must still pass independent review and fresh native evidence. Archived failures remain failures.

Read-only membership inspection found19objects across three coherent exports all outside the accepted region polygons; independent footprint predicate agrees. Runtime6has no coherent object/map/hierarchy export because shutdown remained pending. No evidence-based assignedmembership or>1m frontier translation has yet been demonstrated. No four-slot acceptance campaign was frozen or launched, no quality/accuracy superiority claimed, and no synthetic substitute is counted toward these gates. Original source-folder hashes still match202selectedrecords in latest source audit.

### Current checkpoint after native9 — 2026-10-28

Source before the new adapter passed1161CPU/3native-deselected, fault4, package isolation, nativeDuDe3 and202sourcehash checks, all exit0. Scoped yaw and paired-capture/RSS-retry reviews ACCEPT with retained before/after hashes and original failure reproductions. Fresh nativeyaw120pulse confirmation had0proof/native failures.

| Preparation run | Outcome/support | Useful demonstration |
| --- | --- | --- |
| 00861runtime9,60s | completed;raw834/834,event13/13,RSS513/513,GPU61/61,clean | frontierlowerbound1.036866531m;realobjectcommits/acceptedregion;noassignedmembership |
| 00802runtime9,60s | completed;raw1144/1144,event4/4,RSS577/577,GPU61/61,clean | frontier0m;532forwardpulsesblockedbystrict3Dcollisionfilter;noacceptedregion/membership |

These are preparation runs, not four frozen acceptance slots. The native00802candidate differs only inY from the issuedhorizontal segment; strict3Drejects it. Bounded deterministic contact/spawn checks and freshRGBDbootstrap in otherexistingassets didnot establish a second supportedstrict3Dcase. Failed/unsupported probes remain evidence. No newscene/model/download, source-sibling change or OS/driver change occurred.

The user explicitly selected opt-in `planar_fixed_y_v1` under `p10-planar-adapter-proposal.md`. It is being implemented/reviewed; defaultstrict3D stays unchanged. This adds an explicit constant-height planar simulator interpretation of native contact, not physicalgrounding or terrain3D support. Existing RGBDfloor/clearance, footprint, freshness, command/proof bounds remain required. Tests/nativeprobes and a fresh pinnedprofile/suite must precede any acceptance claim. P10 remains **in progress**, pending that validation, assignedmembership and all four planned runs; no accuracy/appearance superiority claim is supported.

### Opt-in planar A: correctness checkpoint and native preparation failure

User approved the prospective constant-height 2D simulator model; physical grounding, slopes, stairs and 3D terrain remain unsupported. Default `strict_3d` is unchanged. Snapshot combined `1d133796…712c`/worker`56dad4bd…2a53` passed main1248CPU tests, fault4, source-only, nativeDuDe3 and202selected sibling hashes (all exit0); independent SolHigh scoped ACCEPT at `runs/p10-native-preparation/planar-fixed-y-review/review.md` (244focused0/34hashes unchanged). Adversarial float32 endpoint cases still fail unchanged proof limits; this scoped acceptance does not certify a scene profile.

ActualSimulator one≤5mmpulse00802 passed: actual XZ4.9610138mm, pre/postY exactly`.12399999797344208`, unchanged proofv1 host validator exit0. Artifact `planar-native-00802/report.json`. This pulse is actuator evidence only, not RGB-D/map safety or a campaign result.

The first ModeA00802 pipeline smoke (`live-smoke-00802-runtime10/`) **failed**,10rawframes/one~.658mmfrontierproof/zero detector commits, no accepted region/membership, partial cleanup/resources. The one bounded diagnostic `diagnose-00802-runtime10-first-failure/` also failed and retained the first actual host error: float32 endpoint canonical lateral residual exceeds1e-7, `body moved outside forward segment`; sensorclosed is secondary to the correct rejection. Neither outcome is discarded or reclassified. A subsequent read-only host process audit found no matching worker processes, which does not repair failed cleanup certificates.

Original author is implementing a conservative ModeA-only endpoint veto under unchanged proof limits. Prior full-test/review counts do not certify the forthcoming source change. Runtime11 configuration/verification scripts are prepared but not yet run. No four-slot campaign has been frozen or launched; P10 remains **in_progress / native acceptance not proven**. Membership remains separately unsupported: the final native9 publication is stale and all7 footprints are outside its retained polygon (`runtime9-membership-diagnosis/report.md`).

### Current software checkpoint: runtime12

Main fresh gate: **1305CPU tests pass**,3native tests pass separately,fault4pass,source-only packaging and202selected sibling-source hashes match; all exit0. Independent combined review ACCEPT at `runs/p10-native-preparation/runtime12-integration-review/review.md`; source checkpoint`d16ae6ce…8388`. This includes conservative endpoint veto, domain-candidate rejection without weakening geometry validation, and existing failed-goal feedback binding.

| Native preparation60s / seed0 | Run outcome | Frontier observed lower bound | Detector commits | Region / assigned membership | Completeness |
| --- | --- | ---: | ---: | --- | --- |
|00802/runtime12|completed|.061049325m|11|none / none|1138raw,11durableoffers,RSS577/577,GPU62/62; clean|
|00861/runtime12|completed|.957119222m|16|accepted / none|858raw,16durableoffers,RSS526/526,GPU61/61; clean|

Neither row completes the P10 useful-demo gate. They are instrumented preparation runs, not frozen campaign performance. Scene00802's correct RGB-D corridor veto and subsequentno_frontiers remain unsupported demonstration. Scene00861's final region is fresh and exactly matches map427;6object footprints lie outside and2cross/touch its boundary, so no assigned membership is fabricated. Prior runtime11>1m does not replace runtime12's actual lowerbound.

The remaining preparation is a finite, predeclared geometric-only check of existing00770then00337 assets (fixed25queries/cardinal headings, firstfullyqualifiedgeometry), under the user-approved planar model. No detector/benchmark-outcome selection, asset download, source-folder modification or native geometry repair. No four-slot campaign has been frozen or executed. P10 remains **in_progress**, runtime acceptance unproven.


### Latest technical demo readiness — 2026-10-28

P00–P09 are implemented/correctness-verified. Actual headless simulator preparation runs execute RGB-D, native YOLOE commits, map/navigation and accepted region geometry. This supports a technical simulator demo, not P10 acceptance or physical3D deployment. Latest00770/runtime13 ran60s/completed/clean with6detector commits/2object-evidence commits/acceptedregion, observedfrontier.322317527m andnoassignedmembership. Prior00861/runtime11 observed1.105631123m but cannot certify the newer worker.

Latest translation preflight worker4dc00794…a48a29 has207focusedpass and259/259detachedCPUproofs host-valid; no new native Simulator certificate. Frozenruntime14manifestad300ca6…d1343/fourprofiles prepared; currenthead full gate pending, independentSolHighreview blocked by announced account usage limit (Oct29 00:21local). No frozen4slot campaign has been executed. Appearance remainsoptional/off withnoqualitygain claim; interactive UI on actual display remains separately unverified.


Runtime14 main verification completed: `.venv/bin/python -m pytest tests -q -m "not native"` →1334passed/3deselected/exit0 (93.49s); fault4pass0, source-only0, nativeDuDe3pass0,202selected sibling-sourcehashesmatch0. `runs/p10-native-preparation/runtime14-verification/exits.json` retains commands/exits. Fourprofiles14 load_config validated/exit0. No source change during full gate. IndependentSolHighreview remains pending after usage-limit interruption; no native14 pulse/smoke or campaign. Thus current software tests pass, runtime/useful membership acceptance remains unproven.


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
