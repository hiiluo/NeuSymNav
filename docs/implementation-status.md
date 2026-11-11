# Trạng thái NeuSymNav

### Room SLM async / snapshot debug — 2026-11-08 — implemented; error/cancel paths validated, no completed live label

Report: `docs/results/room-slm-async-debug-2026-11-08.md`; artifacts: `runs/room-slm-async-debug-20261108/`.

- **Implemented:** opt-in UI-child background service + persistent model backend, queue32/one inflight/latest per room/debounce/round-robin, history128/8MiB; source-bound semantic metadata and immutable snapshots. New Room labels (debug) tab shows state/context/hashes/evidence flags; historical graph has no current cloud/image sidebar. Zoom/Fit/Expand/Pop out supported. No model, Hydra geometry, movement or300ms/100ms guard change; shared SLM config remains disabled.
- **Correctness-verified:**245 distinct focused tests passed32.84s/exit0, including local HTTP fixtures/native grammar oracle, source staleness/epoch and queue race regressions, UI timer/unavailable/zoom/sidebar and launcher regressions. Not full suite. Terra independent review findings fixed with regression. New profile preflight exit0; legacy UI worker SHA unchanged. Old baseline15/17match, two semantic files already evolved; no claim17/17.
- **Runtime-validated, limited:** two00807 60s offscreen smokes completed/closed cleanly. Sandbox smoke exercised localhost PermissionError; permitted localhost smoke started real model but first job cancelled when demo ended. UI final Hydra revision2. No completed live label. Separate exact-content5object/10relation/661token context timed out twice at~60.72/~60.37s including cleanup; both reaped. New class native reuse not proven for this context. Actual timeout replay PNG/source1/current2 historical proof saved; no physical desktop interaction claim. Live58executed/134expired_or_zero, observed translation lower bound0m; strict actuation.complete=false, no freshness/movement acceptance claim.
- **Evidence:** three existing source-bound contexts14+18+9=41objects, zero linked observations. Quality flags/generic-only host abstention implemented; bed/sofa error and visual association remain unresolved. Human references evaluator-only, old cross-run00805links quarantined. No semantic quality/default/ObjectNav promotion.
- **Next:** compact-prompt A/B preserving all evidence and output policy to reduce cold prefill; then completed live result/UI source proof. Connect correct evidence sidecars/gallery independently. Profile `configs/demo-00807.hydra-room-slm-debug.experimental.local.json` is debug-only;120s command documented but not executed/accepted. No downloads, training, commits or push.

### Room SLM output consistency + persistent KV — 2026-11-08 — implemented offline; measured, no semantic/live promotion

Report `docs/results/room-slm-consistency-kv-2026-11-08.md`; artifacts `runs/room-slm-consistency-kv-20261108/`.
- **Implemented:** request-bound deterministicGBNF (`room-output-consistency-v1`): unique/sortedalternatives≠label;1..8unique/sortedassignedIDs;unknown/insufficient onlyunknown+emptyarrays;boundedreason. Strictadapter/publicvalidator rejectsabstentionclaims, duplicateJSONkeys; backend sendsGBNFonly, logsgrammar/version/native timings/rawSHA, rejectsfinishlength. Sharedbodyhelper usedbyofflinebenchmark; productbackendstillperrequest, sharedSLMconfigdisabled. NoHydra/movement/guard/default/modelupgrade.
- **Correctness-verified:** 97distinctfocusedtests pass2.05s/exit0, includes26nativegrammaroracles (no skip), max64objects52,487bytegrammar/~4ms;2policytestsrerun portabilitynotdoublecount. IndependentLunareview foundconditionalmeasurementtruncationgap; fixedfutureharness/helper+regression, archivedexactexecutedscript, observed9allstopunaffected. Verificationexit0/native9acceptances,6geometry/profilehashes+coordinator/safety/configunchanged.
- **Runtime-validated diagnostic:**9completions on1persistentserver, CPU1/Qwen1.7BQ4/samemodelruntime/grammar,2contextsOFFONOFFON+crosscontextprobe. Mirror meanHTTP34.709OFF→11.799ONs, prefill23.356→.240s,61decodedtokensboth.9objects88.551→15.493s, prefill56.686→.278s; decode136OFF/67ONtokens, do notattributeallHTTPgain tocache. Crosscontext331reused/75newtokens~16.3s. Startup2.784s separate, childRSS2.69GB, closescleanly. Diagnostic100sHTTPonly; production60s anddepthguard300ms/horizon100ms unchanged.
- **Not proven / remaining:**all9syntacticallyavailable doesnotmeansemanticcorrect: mirrorutilityunsupported,00807bedroomvsuserliving_room withnativeO0bed/actualsofa. Humanroomlabelset12eligible unmet; noquality/5slive/controlcontentiongate. KV≠resultcache; source/requestidentityunchanged. Needexplicitpersistentbackendlifecycle beforeeverydayreuse; S4/S5/UIremainunimplemented/gated. No commits/push/download/simulator.


### Room SLM small-context diagnosis — 2026-11-08 — measured offline; human visual references recorded, no live promotion

Report `docs/results/room-slm-diagnosis-2026-11-08.md`; artifacts `runs/room-slm-diagnosis-20261108/`.
- **Implemented:** artifact-only stage probes on existing pinnedQwen1.7BQ4/nativeCPU1thread, persistent server within each probe, rawresponse/template/metrics/validator audit. No product source/default/guard/Hydra edits or downloads. Separate Luna xhigh packages neutral real-RGB human review cards; AI draft is not humanGT.
- **Correctness-verified:** `PYTHONPATH=src .venv/bin/python runs/room-slm-diagnosis-20261108/analyze.py` exit0:7rawresponses/readapted results,3script/source/protocol chains,3loadedtemplate matches,6geometry/profile SHA matches; allcache_n0. Focused adapter/prompt/contract29tests passed0.62s/exit0; finalverification checks13source/outputPNGbindings,3humanreplies,14corrected00805objectmatches, sharedSLMconfigdisabled; `git diff --check` exit0. Artifact `runs/room-slm-diagnosis-20261108/final-verification.json`.
- **Runtime-validated diagnostic:**7requests/2frozencontexts/3serialserverprocesses. Startup→health2.67–2.99s (pagecache not flushed). Production-order singleton prefill20.75s/decode15.29s;9objects57.28s/33.62s→90.94s after diagnostic-only100s timeout. Production60s deadline unchanged. Loadedtemplate SHA exactupstream; rendered enable_thinking=false emptyclosedthink confirms nonthinking works. Parser correctly rejects primarylabel repeatedinalternatives;9object output also combines O(7),O(8) into one unknownsupportstring.
- **Ablation:**append generic abstention/alternatives policy to same singleton/context/schema→valid insufficient_evidence twice, stillunrequestedalternatives. Remove duplicated textualschema on onepair399→244tokens,HTTP36.05→24.36s butinvalid unknown/alternatives[unknown]. No semanticlabel accepted, no prompt/default promotion, no accuracy claim. Exploratoryfirstprobe sorted schemaorder differs production; keptseparate, notexactparitybaseline. NoKVcache, GPU/threadAB, live/control benchmark or S4/S5 integration.
- **Human data:**CardA actualRGB shown and unprimed humanroom/objectquestion requested; đã trảlời bathroom/sink, lưu verbatim/hashbound riêng chỉA1/frame340/O16 (khôngA2/A3/nativewholeR0). B–Eđãtrảlời: Bbedroom+bathroom; C/Dcùngbedroom; Dbackgroundbathroomqua small doorway; Eliving_room/O0sofa. Referenceimages khôngfullgeometryGT. Neutral reviewpack/source hashes và3humanreplies đãlưu; A2/A3/otherobjectreviews vẫnpending.13viewPNGbindings verified, initialsheetarchive+correctedidentityheader preserved; no invented humanlabels or12roomcoverage. Pháthiện00805AIdraftcrossrunbindingc569/af1 vs3aeb/3122 (O16missing/O17conflict);quarantineoldlink vàrebuildcorrected00805request c569/af1/context511c,14objectsmatchsource. C/D/E exactrun+graphmatchverified. AIdraft006“living+bedroommerge” khôngcòn làreference đángtin; humanC/Dsamebedroom, bathroombackground vẫn cầnmembershipcheck. SLMgeometry/evidenceknownfailures remain. ExistingS3code/model/runtime installation was completed by priorwork (latest checkpoint at bottom); older noimplementation headings below are historical.


### SLM room-label pilot — 2026-11-08 — historical planning checkpoint (before implementation)

Người dùng muốn tạm giữ Hydra geometry config và bàn giao exploration độc lập. Design: `docs/superpowers/specs/2026-11-08-room-slm-pilot-design.md`; plan: `docs/superpowers/plans/2026-11-08-room-slm-pilot.md`. Manifest `docs/baselines/hydra-room-slm-pilot-2026-11-08.lock.json` giữ17 hashes profile/YAML/privateDSO/selectedsources; không full installed dependency closure, không default promotion/chmod/freeze graph. User báo live00807 phân đúng kỳ vọng (ảnh3rooms), chưa có user-run artifact để main xác minh profile/trajectory; replay006/007 final3/2 thuộc protocol khác.

Đề xuất Qwen3-1.7B non-thinking Q4_K_M/llama.cpp CPU offline trước;4B-Instruct-2507 chỉ là đối chiếu tùy điều kiện. Exact model asset/runtime chưa pin/cài/tải. Existing context+labelcontract tái sử dụng nhưng phải thêm full run/episode wrapper, stricter supporting IDs và bounded service. Geometry-only006/007 emptydetections không làm semanticquality benchmark. Offline pilot dùng detector-backed contexts và human semanticreference, labels không sửa geometry/control. SLM replies exactrevision, stale giữ history, không tự reuse crossrevision.

**Implemented:** tài liệu/manifest thôi; không product code/runtime/config edit. **Correctness-verified:** Luna xhigh read-only builder review đã trả approve với limitation live attachment; plan thêm cổng usability và sửa3contract gaps ở mức thiết kế (chưa sửa code); manifest17/17 SHA match; document whitespace/gitdiffcheck exit0; đây không phải test code. **Runtime-validated:** chưa inference/model/liveSLM, chưa nghiệm thu quality/resource. Chờ review/giao triển khai; exploration/control và geometryknownfailures theo reportB1 vẫn độc lập. Không chạy lại simulator/replay hoàn tất trong lượt lập plan.


### Live profile006/007 — 2026-11-08 — prepared, preflight only

Đã thêm `configs/demo-00806.hydra-world2hz-room-stability.experimental.local.json` và tương ứng00807, lấy scene/spawn/measured floor từ local map calibration và Hydra camera mount từ captured manifest đã kiểm chứng. Giữ movement/guard/room config, chọn world2Hz opt-in. Hai preflight exit0/readytrue; chưa chạy autonomous live hai profile này. Native3rooms006/2rooms007 trước đó là targeted geometry-only replay, không hứa live tái tạo cùng count. Logs/hashes `runs/hydra-objectnav/B1-multiscene-20261107/live-{profiles.json,00806-preflight.log,00807-preflight.log}`. Không thay default/source.

### B1 multi-scene / seed attribution / local-map audit — 2026-11-08 — executed; annotation and long-run acceptance pending

User four-step task; report `docs/results/hydra-multiscene-geometry-localmap-2026-11-07.md`.

- **Implemented:** artifact-only capture/replay/audit/plots for00806+00807; no product source, installed library, default profile or300ms/100ms guard changes. Private stable DSO pinned. Geometry-only unknown_static semantic input; no detector or semanticGT in newscene baseline.
- **Correctness-verified:**97focusedtests passed11.47s/exit0 in this task; verifier exit0 validates158captured packets, selected source identities, calibration and native artifacts. Source/control/default-profile/stableDSO hashes match initial lock. Additional61replay/goal-feedback tests passed5.96s/exit0; not fullsuite.
- **Runtime-validated, geometry:**00806 captures94→48selected;00807 captures64→33selected. Four fresh OFF/ON replays accept162/162 selected inputs total. Same source prefix/XYZ/clearance/weighted edges81/81paired revisions; stock native reconstruction partition parity81/81. Final006354places/3rooms,007384places/2rooms (bothmodes). Counts are notaccuracy. Human neutral maps+registered pixels ready; need user room interiors/opening annotations for cross-region errors/fragmentation accuracy.
- **Temporal:**006 OFF split10/merge12 vsON4/4;007 OFF0/2 vsON0/2 under observed-ID overlap audit; not physical room lineage proof. ON/OFF partitions differ9/48 and5/33 revisions. NativeOFF seeds/thresholds exported eachrevision; ON effectiveCC reconstructed at loggedthreshold andchecked againstnative seedcount.
- **00805 immediate cause:** exact23-inputOFF replay/native partition parity23/23. Of13mixedrevisions OFF4 lose allbath support toclearance threshold,9 contain only size1bathcomponents filtered bymin3. ON3clearance/10size-pruned at actual loggedeffective threshold. No evidence of two viable bath/hall seeds later fused byNEIGHBORS in thosecases. No threshold tuning.
- **Cost:**map-only12spread×3 +top8worst-live×3 confirm realNumba; original903local stages allstart<300ms,250cross300duringmap. CPU/GPUprobe fresh:OpenVINO CPUonly, no/dev/dri inthisenvironment;Torch intra1/inter8. Worldworkers4→1 marginalbenefit/worldslower; localworkers2 benefit not repeatable; rejected asdefaults. Oldhostclock changedafterreboot; newpairedcostruns use existingReplaySession contract, preservingpixels/poses/intervals and fullhashparity; retain originalfuturetimestamp rejection.
- **Live60trials:**sameboot baseline38/210=18.10%freshnessmisses, observed0.698m; world1Hz4/449=.89% butonly.061m and411world_intent_unavailable — rejected despite metric. Found existing failure-watch1sgap resets at1.01s; deterministicfixture reproduces. Existing2Hz cap completed60s:28/264=10.61%, localp95240.41ms vsbaseline272.23ms, observed.936m vs.698m;7native revisions each. Singleexploratorycase, not<5%orlongpass. Profile `configs/demo-00805.hydra-world2hz-room-stability.experimental.local.json` opt-in; defaultunchanged. Do not use1Hz asrecommended demo.
- **Artifacts:**`runs/hydra-objectnav/B1-{multiscene,newgeometry,localmap-cost,next-baseline}-20261107/`. Latest ledger `B1-next-baseline-20261107/progress.md`; no repeats of completed captures/native replays needed. SLM not installed/started; readiness does not require universal freshness<5%, but geometry annotation and object evidence quality remain separate gates.


### B1 stability cost / live validation — 2026-11-07 — executed, acceptance not met; no promotion

Đã hoàn tất ba bước kiểm tra; [báo cáo](results/hydra-stability-validation-2026-11-07.md).

- **Implemented:** tooling timed DSO riêng + replay OFF/ON/OFF/ON; hai entry chẩn đoán
  tùy chọn được đóng gói trong `backends/hydra/validation_entry.py` và
  `runtime/ui_validation_entry.py` để giữ preflight source confinement. Default entries,
  threshold, core movement/safety, installed/stable Hydra giữ nguyên. Không bypass preflight.
- **Correctness-verified:** 207 focused tests passed10.92s/exit0 (gồm bundled UI fixture),
  native policy driver mới PASS/exit0; verifier source/hash/provenance exit0. Không fullsuite.
- **Runtime-validated, cost:** bốn fresh workers×58 inputs cùng .5/min3/merge.25;232/232
  graph revisions khớp prior stock/stable geometry/edges/partitions. Mean findRooms
  +0.210ms/bước; whole-step2591.40OFF/2585.76ONms, không slowdown lặp lại trong mẫu này.
  Native scopes lồng nhau; không cộng. Hai mẫu/mode, chưa có universal overhead guarantee.
- **Runtime-validated, live:** hai simulator runs300s completed/export/recording/shutdown sạch.
  Profile cũ (5Hz/world control) chỉ2.17m, freshness201/584=34.42%, UI20/20match, chưa qua hai cores.
  Chạy lại từ profile local-depth HIỆN CÓ (retention10s/primary.5Hz/guard không đổi):
  2.09m, body đã đi qua hai cores và cắt marked opening1lần; freshness293/903=32.45%,
  UI23/23match. Qt offscreen only; chưa physical desktop proof. Missing command proofs0;
  strict actuation.complete vẫnfalse, không nâng observed distance thành certified distance.
- **Geometry chưa đạt:** local-depth ON gộp chéo13/18eligible, strict1/18; replay OFF đúng
  cùng23inputs cũnggộp cùng13/18, strict0/18. Policy không phải nguyên nhân duy nhất;
  cần audit support/filtration/clustering recording mới. Independent short60 OFF/ON10+10
  geometry/cạnh khớp, ON hold5–8/adopt9 chứng minh sửa được nhưng có độ trễ. Không promote.
- **Telemetry/remaining:** detector yêu cầu OpenVINO GPU nhưng runtime chỉ thấyCPU,
  fallbackTorchCPU. Local-depth control_navigation_wait p95.0043ms (decoupling hoạt động),
  local_depth_map p95 449.14ms >depth300ms. Chưa quy causal toàn bộ cho fallback;
  bước tiếp kiểm tra device exposure/CPU contention và chi phí local map, giữ guard,
  song song trace geometry mới. SLM label không dùng làm geometry proof.
- **Profile đúng để thử tiếp:** `configs/demo-00805.hydra-room-stability-local-depth.experimental.local.json`;
  profile room-stability cũ vẫn được giữ để tái lập, không nên dùng làm current movement baseline.
- **Evidence/commands:** `runs/hydra-objectnav/B1-stability-validation-20261107/` với
  `plan.md`, `progress.md`, command/exit/log từng run, `benchmark-analysis.json`,
  `new-live-recording-comparison.json`, hai `room-validation.json`/`ui-validation.json`,
  `local-depth-control-profile.json`, `final-tests.log`, `verification.json`.
  `python3 .../verify_validation.py` exit0; `git diff --check` exit0. Wrong-profile smoke
  và preflight rejected-artifact-entry được giữ riêng; không đưa vào primary averages.

### B1 threshold/seed stability — 2026-11-07 — implemented, offline native replay validated

Đã thực hiện trong `Kiet_branch2`; [báo cáo](results/hydra-threshold-seed-stability-2026-11-07.md).

- **Implemented:** opt-in private Hydra RoomFinder hysteresis; ba timestamp graph mới
  trước khi nhận thay đổi đáng kể, seed tính lại trên geometry hiện tại, fallback khi
  mất held support, reset pending khi unavailable, reset instance khi kết thúc. Bridge
  pin DSO/version/hash; live snapshot/projection và accepted journal có provenance/decision.
- **Correctness-verified:** 206 focused Python/UI/GT-isolation tests passed, 10.87 s,
  exit 0; native temporal/geometry/reset/API fixtures và disabled seed parity exit 0.
  Test UI wire cũ được cập nhật để yêu cầu all layers và pick object đúng A1/A2.
  Không tuyên bố toàn bộ repository suite pass.
- **Runtime-validated (offline RGB-D):** hai worker mới replay đủ 58/58 + 10/10 accepted
  inputs, prefix/build/loaded-DSO verified, close/export sạch. Long300: places XYZ/
  clearance/edge weights/source prefix khớp đối chứng cả 58 revisions. Gộp chéo hai
  human cores 3/53 → 0/53; strict core separation 37/53 → 40/53. Hành lang vẫn bị
  phân mảnh ở revisions 6–18. GT chỉ evaluator offline; không chứng minh full boundary.
- **Phạm vi còn thiếu:** chưa live simulator/UI trong task; thời gian process quan sát
  cao hơn đối chứng (p95 3.990 → 5.830 ms, hai replay khác thời điểm, chưa suy causal
  overhead). Cần benchmark lặp + live/scene khác trước promotion. Default YAML, installed
  Hydra, GraphExtractor, coordinator và safety giữ nguyên SHA; không thay guard/control.
- **Sử dụng:** `configs/demo-00805.hydra-room-stability.experimental.local.json`
  qua `NEUSYMNAV_HYDRA_DEMO_CONFIG`; preflight exit 0. Lệnh demo trong báo cáo.
- **Lệnh kiểm chứng:** `python3 runs/hydra-objectnav/B1-stability-20261107/verify.py`
  exit 0; focused pytest command trong `commands.json`, exit 0; `git diff --check` exit 0.
  Artifact: `runs/hydra-objectnav/B1-stability-20261107/{verification.json,comparison.json,
  final-tests.log,preflight.log,clean/,native/}`. Bản ghi cũ bên dưới là lịch sử trước fix.

### B1 human-marked target evaluation — 2026-11-07 — partial reference evaluated; promotion still pending

User supplied greenbathroom/cyanhallway/redopening-range image; [báo cáo](results/hydra-human-regions-2026-11-07.md).
Image persisted/sourceSHA, gridregistration≤2pixels, partialinteriorpolygons and
0.10m extrauncertainty; outside/overlap/outline/redline unknown. GT offlineonly;
rednotwall/occupancy; no runtime/default/control/library changes.

- **Implemented:** Luna xhigh offlinepolygon→exactgraph support evaluator +8tests;
  maincolorcontours/registration/independentraster/report. Source/run/revision/
  graphSHA+acceptedchain, annotationJSONSHA/userimageSHA/sourceManifestSHA bound.
  Currentrow previously“annotationmissing” below is historical: now human partial
  corelabels exist; fullphysicalroom/door-boundary annotation still incomplete.
- **Correctness-verified:**78focusedtests passed2.67s/exit0 (nativefixtureenabled,
  noskip), notfullsuite.174primaryrevision evaluations (3profiles×58) CLIexit0;
 348sensitivityevaluations reuse samegraphs. Source/native/controlSHAunchanged,
  diffcheck0. Independent raster exactGTassignmentsmatchall3finalgraphs.
- **Observed target:** default mergesbothcores52/52eligible; comp.5/min3/M.5
  merges17/50eligible; M.25 merges3/53(revisions36/49/57). M.25 splits marked
  hallway6–18 (13revs). Strictcoreseparation31/50 vs37/53; on50commonavailable
  candidateframes31vs37, M.25fragment10vs0. Unknownframes notsuccesses.
- **Finalsnapshot:** defaultbath3/hall18sameR0; M.5bath3R1/hall21R0; M.25bath8R1/
  hall62R0. Bothcandidate finalF1=1onlyonpartialconfidentpoints (~17–21%graph),
  notwholemapaccuracy. Handmark reference differs oldqualROI; seedlocationoutside
  oldROI alone didn'tprovewrongsegmentation. Target3lateerrorsrobust margins
  .05/.10/.15m, so notremovedbyselectingannotationmargin.
- **Remaining mechanism:** nativefreshreconstruction threshold.5657→.6325 at36/49
  and→1.0000at57 removesbathroomseed (andhallseedat57); returnsnextframe. Actual
  partitionsmatchreconstruction previouslyverified. Need seed/merge persistence
  policy derivedfromnativeevidence, notmoreblind densitytuning/GTwallinjection.
- **Evidence:** `runs/hydra-objectnav/B1-human-20261107/{human-regions.json,
  annotation-registered.svg,evaluation/index.json,target-summary.json,
  bad-revision-seeds.json,tests-command.json,tests.log,tests.exit,verification.json}`.
  Verification command `PYTHONPATH=src .venv/bin/python runs/hydra-objectnav/B1-human-20261107/verify_human_eval.py`
  exit0. No new native/simulator/GPU/detector/modeldownload/training/commit/push.
- **Decision:** no defaultpromotion/liveacceptance. M.25 betteragainsttargetmerge
  but earlyfragments/latecollapses remain; roomgeometryboundary/globalaccuracy,
  livecost andObjectNav modulecompletion unproven. Existingcostfromprevious
  cleantrials unchanged; no performanceclaims fromthis label-onlyevaluation.


### B1 GVD support trace / merge A/B / revision audit — 2026-11-07 — offline complete; human annotation pending

User authorized3steps; [báo cáo](results/hydra-support-merge-2026-11-07.md).
Default promotion chưa đủ bằng chứng; defaults1.0/10/10 giữ nguyên.

- **Implemented:** Terra high isolated probe từ copiedGraphExtractor TU, parser;
  main perrevisionentry/temporal evaluator/CLI; Luna blindRGBD annotation packet.
  Production source/library/config/control unchanged (SHA gate). No Astra,
  simulator/GPU/detector/download/training/commit/push. Separate file owners.
- **Correctness-verified:**70focusedtests passed4.51s/exit0, no skip, gồm native
  fixture, exhaustive pair oracle, GT isolation/UI/query. Not fullsuite. Probe
  parity actual backend places/edges/fullRoomFinder exactold for10/58/58frames.
- **Native offline validated:**3probe +4cleanfullhistory replays; originalinput
  prefixes/counts/source/build/config and actualloadedlibraryverified.136clean
  snapshots andfreshRoomFinder reconstructions co-membershipmatchallrevisions.
  One interruptedM.25trial39frames archived/ineligible; full58restart complete.
- **Cause:** finalphysicalROI GVD147same/120eligible bothcompressions. Comp1
 14ROIrepresentativegroups/8visible/6hidden vscomp.5 15groups/5visible/10hidden;
  historicalresolvedmerges hide survivinglocalsupport. Exactrefs/eventIDs in
  native-probe/analysis/long300-comparison.json. Frontend/backend distinguished.
- **Isolatedmerge:** comp.5/component3/room10 held; M.5→.25 restoresROI5→14long,
 8→14short, butglobalplaces135→399long and48→127short. Longfinal2→3roomgroups,
  fineROIseed6 long butnone short (PLATEAU.7483); no physicalaccuracyclaim.
- **Stability/cost:** assignedstationarypair weightedchanges long7.20→7.49%,
  short0→13.93%; shortbaselinebathroomgroupbornonlylastrevision,0% notproof.
  Longnativep954.060→3.990s singletrials butmax4.111→5.343s; sampledRSS294→301MiB.
  Debugexportseparate; offlinecost notlivefreshness/budgetpass. Split/mergeevents
  descriptive onpersistentobservedplaceIDs, notconfirmedphysicalroomerrors.
- **Quality blocker:** no independent00805roomGT; userconfirmednone, askedblind
  map tolabel. Maps/sourceRGB/template prepared, no prediction/seed/ROI overlay;
  quality4reports unavailable/annotation_missing. Awaithumanpolygons before
  boundaryaccuracy/default/liveacceptance; no qualitativeROIasGT.
- **Evidence/commands:** `runs/hydra-objectnav/B1-support-20261107/verification.json`,
  paired-summary.json, tests-command.json/tests.log/tests.exit, clean/trace/audit/,
  annotation/. Final `PYTHONPATH=src .venv/bin/python runs/hydra-objectnav/B1-support-20261107/verify_support.py`
  exit0 checks7completecases, exactrevisionindex, library/sourceintegrity and
  gitdiffcheck0. Wholegeometryquality/ObjectNav roadmap remainsincomplete.

### B1 controlled room A/B — 2026-11-07 — offline experiment complete; defaults unchanged

User giao A/B support places vs size filters trước đổi default.
[Báo cáo](results/hydra-room-ab-2026-11-07.md); protocol khóa trước chạy ở
`runs/hydra-objectnav/B1-ab-20261107/protocol.md`.

- **Implemented:** offline sizefactorial harness + metrics/tests; artifact-local
  native accepted-prefix replay/XYsupport comparison. Main owns harness/docs;
  Luna xhigh owns replay; separate Luna read-only size review. No app/runtime/
  default config/library/control edits. Review provenancegap fixed and rerun.
- **Correctness-verified:**63focusedtests passed4.10s/exit0, no skip (native
  env enabled); six metric/config tests include exhaustive pair oracle. Four
  source/library-fingerprinted matrices c10/5/3 × r10/5 + baseline repeat each
  =28confirmed nativecalls; historical first14calls retained separately. Each
  graph's geometry fixed and baseline repeat exact; final diffcheck exit0.
- **Native offline validated:**6freshworker replays, exact10/10 or58/58 original
  accepted frameprefixes, same Hydra source/build. Baseline places/edges/RoomFinder
  exactlymatch frozen graphs60s/300s; comp0.5 shortrepeat exact. FileSHA drift
  outside roomstructuralparity unresolved, not claimed fullmesh byte parity.
- **Findings:** sizealone all1room; compression1→0.5 alone34→48places(60s),
  102→135(300s), still1room. Combined comp0.5/component3/room10 posthoc native
  gives38/10places(60s),113/22(300s). ShortbathROI8/8 in10place room withlocal
  seed3; longbathROI8→5places and no localseed (component2filtered);22place
  room propagates from seed6outsideROI. Globaldensity ≠ targetlocalsupport.
- **Decision/limits:** giữ1.0/10/10 defaults. No independent spatialGT/accuracy,
  roomID temporal stability, live candidate or runtime performance claim. Size
  variants run full RoomFinder on frozen exported graphs, not entire worker
  histories undercomponent3. Recordings60s/300s have different routes, not same
  episodeprefixes; do not infer temporal instability from their difference.
- **Evidence:** root `verification.json`, `final-tests-command.json/.log/.exit`,
  `size-verified/`, `density-size/`, `density/`, `comparison/`; repeat positive
  confirmation under `positive-repeat-short60/`. Verification script exit0:
  `PYTHONPATH=src .venv/bin/python runs/hydra-objectnav/B1-ab-20261107/verify_experiment.py`.
- **Next:** trace GVD→compressed representative→merge localROI and isolate
  merge-distance A/B, preservingclearance policy; independent geometry annotation
  before promotion; fullhistory candidate replay/live budget later. No new
  simulator/GPU/detector/modeldownload/commit/push. Full roadmap incomplete.

### B1 native Hydra room diagnosis — 2026-11-07 — mechanism verified; geometry accuracy chưa xác nhận

Task ưu tiên user giao trong `Kiet_branch2`, cặp bathroom/hallway00805.
[Báo cáo](results/hydra-room-diagnostic-2026-11-07.md).

- **Implemented:** helper native offline + CLI/report/overlay, export clearance,
  edgeweights, threshold, raw components, seeds trước NEIGHBORS và memberships.
  Không sửa production runtime/config/control hay thư viện Hydra.
- **Correctness-verified:** **57passed/3.56s/exit0** focused tests gồm native
  synthetic2room + offscreen UI/query/GT isolation. Build/native inputs exit0;
  graph/config/worker/coordinator/safety hashes không đổi. Không phải fullsuite.
- **Native offline validated:** graph60s34places→raw16/1/3→seed16→room34;
  graph300s102places→raw25/1/3/3/3/1/1→seed25→room102. Cùng threshold
  .5656853318214417m; recorded membership khớp34/34 và102/102.
  Component3nodes phía bathroom bị `min_component_size=10` lọc trước NEIGHBORS.
  Synthetic cùng config có2seeds16/16 và2rooms; không phải UI chỉ hiện1room.
- **Limits:** finalgraph reconstruction không là original per-frame trace;
  bathroomROI định tính, chưa có independent spatialGT/accuracy. Counterfactual
  giữ mọi rawseed cho bathroomcluster6(60s)/10(300s); không tương đương retune
  toànRoomFinder. `min_room_size=10` và oversegmentation cần kiểm tra riêng.
- **Evidence:** `runs/hydra-objectnav/B1-diagnostic-20261106/verification.json`,
  `short60/`, `long300/`, `synthetic/`, `worker/final-tests.log`. Exact commands
  trong report; no new simulator/liveUI run. No commit/push/download.
- **Next:** controlled recording A/B coverage/place support vs component/room
  filtering; independent annotation trước accuracy claim. A2sidecar/gallery và
  offlineObjectNav tiếp tục độc lập; SLM không chứng nhận geometry. Roadmap chưa
  hoàn tất. Phần “plan đề xuất” bên dưới là checkpoint lịch sử.


### Hydra graph/evidence/ObjectNav + control — 2026-11-06 — plan đề xuất, chưa implement

User đã đồng ý tiếp tục graph/query/evidence và ObjectNav kiểm thử độc lập, song
song control; chọn **text-SLM từ object/quan hệ** cho room labels.
[Roadmap](superpowers/plans/2026-11-06-hydra-objectnav-roadmap.md) liên kết spec và
3subplans: UI/gallery/query/ObjectNav; room geometry audit + SLM; control isolation.

Ưu tiên Rooms+Objects/placesOFF cả2D/3D, clickobject gallerycrop+mask/fullframe.
Current Hydra có picking/query nhưng per-objectevidenceNone và categoryraster
không giữ instanceID; galleryv1 phải candidate-debug với provenance, không claim
native identity. Roomsegmentation accuracy và roomlabel inference chấm riêng;
SLM không sửa geometry/native IDs. Geometry metrics phụ thuộc support domain.

Buildercheck Luna xhigh đã nêu3điểm: evidence revisioncarry-forward, graph↔nav
binding/freshness, point-domain metrics; main bổ sung quy tắc cụ thể và tự rà
soát. Chưa có implementation/design acceptance từ user cho các task mới; không
code, khôngtests/demo/modeldownload trong lượt plan. Sourcehash code khớp
checkpoint trước; link/whitespace/diff checks sẽ ghi ở
`.runtime/hydra-objectnav-plan-20261106/verification.json`. SLM model/license/asset
và threshold qualitypromotion chờ inventory/baseline, không suy đã được chọn.


### NavMap critical path / local-depth lane — 2026-11-06 — implemented/correctness; long performance FAIL

Chỉ `Kiet_branch2`; [báo cáo và hướng tiếp](results/navmap-critical-path-2026-11-06.md).

- **Implemented:** exact bounded rays; local measured-depth map/controller/guard
  độc lập world-map/Navigator, worldintent nguyên nguồn/expiry2s, local revision
  độc lập; telemetryv2 strict provenance; tùy chọn cadence world riêng.
  Giữ depth/mapTTL300ms/horizon100ms, unknown/floor/height/capsule. Không default
  hay profile long-ready mới. Experimentalfile:
  `configs/demo-00805.hydra-local-depth.experimental.local.json`.
- **Correctness-verified:** paired1211/1211 world/currentcoverage equal; independent
  review sửa goalblacklist tạm thời và race intentcũ xóa intentmới; realthread
  test điều khiển depthmới trong lúcworldworkerblocked; worldno-path watchdog
  recovery. Final **2706passed/10skipped,255.46s,exit0**, `full-release.log`.
- **Runtime-validated:**15nativeUIruns/9364actualcontrolinvocations, strictclosed
  source/clock/measurements/proofs, collectorcomplete/no drops/no missingproof or
  executedtimingviolations, recording/UI/export/shutdowncomplete; frozen source
  hashesmatch. `strict-final.log`/`.exit=0`, `final-verification.json`.
- **Performance NOT achieved:** fullrate local120s3.17%/4.782m;300s6.96%/9.869m,
  max4misses. World2.5Hz300s7.34%/7.830m;combinedGC120s5.32%/2.385m;
  capture5Hz120s0% nhưng.649m/450bootstrapblocked -> availabilityFAIL.
  Local4worker300s13.32%/5.977m -> rútoption khỏiproduction, lưu sourceexperiment.
- **Remaining:** fullrate worldwaitp95≈.003ms nhưng localmapp95172→274→279ms
  qua3đoạn100s; chưa xác nhận đơn nguyên nhân CPU/GIL/GC/render. Next ưu tiên
  process riêng cho capture/localdepth/control, telemetry ngoài criticalprocess,
  đo sensor/render/projection/raycast; không nới guard. Chưa600s/room-object
  accuracy/ObjectNav completion hay bảo đảm5%mọirun.
- **Artifacts:** `.runtime/navmap-critical-path-20261106/`, final `local-lane/`.
  Commands: `.venv/bin/python -m pytest -q` và
  `PYTHONPATH=src .venv/bin/python .runtime/navmap-critical-path-20261106/validate_local_lane.py`
  với15runnames (đủ argv trong `local-lane/commands.json`); exit0.
  No commit/push/source-sibling edits; historical checkpoints dưới giữ nguyên.


### Rolling NavMap — 2026-11-06 — implemented/đo hoàn tất; long gate FAIL

WorktreeKiet_branch2 only. [Báo cáo](results/navmap-sliding-window-2026-11-06.md).

- **Implemented:** optional local_retention_s; rolling spatial crop/eviction,
  independent planar/height/floor last-observed expiry→UNKNOWN; no archive reload.
  Bounded per-sensor dedup, exact fused maintenance prewarmed + NumPy fallback.
  Full measured rays/stride1/Hydra/controller/TTL300ms/horizon100ms không đổi;
  accumulated overview lịch sử riêng không là motion proof.
- **Correctness-verified:**24rolling regressions + independent scalar kernel
  oracle C/strided/no per-frameJIT;52mapping/guard tests. Full2627passed/10skipped,
  172.09s/exit0; independent reviews;7native strict schema/control inspections,
  no trace drops/missing executed proof/timing violation; final code hashes match.
- **Measured choice:**9radius/age combinations+repeated baseline screening;
  full1211sources×3shortlists;7native UI-on runs. Chốt bán kính2m / age10s
  (thay provisional30s sau direct120/300s comparison). Profile riêng
  `configs/demo-00805.hydra-rolling.local.json`, không đổi default/long-ready.
- **Runtime-validated:** baseline60s3.242m/0misses;1m10s30s1.349m/0;
  2m30s30s1.855m/0,120s5.072m/3.58%,300s11.013m/8.73%;
  2m10s120s5.655m/2.51%,300s10.719m/101of1584=6.38%. Cả7exit0,
  recording/UI/export/shutdowncomplete. Selected300sHydrarev59,15objects/77places/
  1room;RSS2049/2049supported. Localarrays4tiles6.24MB cuối;bound9tiles14.05MB.
- **Remaining:**≤1% gateFAIL, selectedmax3misses liên tiếp; latencytail vẫn tăng
  dù localmemorybounded. Selectedextent4.388×1.540m; không suy pathlength là
  coverage/accuracy hoặc ObjectNav completion. Không600s. Next: local-depth
  safety lane/full-map scheduling hoặc exactROI raytracing với oracle.
- **Artifacts:** `.runtime/navmap-window-20261106/`; current results/limits trong
  report và final-verification.json. Older checkpoints below remain historical.


### Hydra long-demo follow-up — 2026-11-05 — diagnostic hoàn tất

Chỉ thực thi trong `.runtime/worktrees/Kiet_branch2`; giữ nguyên checkout
`Kiet_branch`, không commit/push. Báo cáo và giới hạn:
[hydra-long-demo-fix-2026-11-05.md](results/hydra-long-demo-fix-2026-11-05.md).

- **Implemented:** startup probe, UI hover, accepted-source provenance,
  detached snapshots, canonical query API, exact log-odds kernel, byte-identical
  frame codec/wire reuse, bounded streaming export, strict RSS trace reconciliation.
- **Diagnostic runtime-validated:** user cho phép300s dù có thể fail1% gate.
  Recording1353/1353 complete; native graph revision40,15objects/76places/1room;
  UI295 rendered và export/shutdown sạch. Proof translation lower bound6.724m;
  942executed,0missing proof/0executed timing violation. Offline native reload
  query15/15objects có category/XYZ/room provenance, không chứng minh accuracy.
- **Không đạt long acceptance:**247/1207 freshness/deadline refusals20.46%, max11
  liên tiếp; map median103→132→142ms qua ba đoạn100s. Outcome incomplete/CLI1
  do1 RSS census deadline sau control cuối (1759/1760supported). Không nớiTTL300ms,
  horizon100ms hoặc guard. Không chạy600s, không promote candidate thất bại.
- **Correctness-verified sau diagnostic:** export streaming33focused passed/exit0;
  20MiB probe peak3.16MiB, thay vì41.99MiB legacy. Chưa chứng minh sửa được RSS
  timeout native300s; artifact cũ vẫn incomplete. Full suite cuối2580passed/10skipped,201.15s,exit0 ngày2026-11-06.
  Journal thật196.8MB: parser mới khớp40/40 manifest entries, peak Python15.55MB;
  chỉ kiểm chứng offline, không suy native RSS fix pass.
- **Bước tiếp đề xuất, chưa implement:** thiết kế local measured-clearance lane
  độc lập full world-map/planner với provenance/TTL riêng và safety regression;
  không dùng world map cũ như evidence motor mới. ObjectNav còn approach pose,
  target verification, object evidence/lifecycle/alias và quality eval nhiều map.
- **Artifacts:** `.runtime/hydra-long-demo-fix-20261105/`; profile diagnostic
  `configs/demo-00805.hydra-diagnostic.local.json`. Historical checkpoints bên
  dưới giữ nguyên theo thời điểm; kết luận readiness hiện hành là mục này.


### Long-demo report sync — 2026-11-05 — documentation only

Đã đối chiếu lại artifact30s RSS-fix và120s first-gated, cập nhật phần kết luận/
evidence/findings của [readiness plan](results/hydra-long-demo-readiness-plan-2026-11-05.md)
để không còn dùng snapshot cũ làm blocker: UI Hydra XYZ + measured cloud và
profile durable đã có; RSS fix được xác nhận30s. Blocker chính còn lại là
6/546 freshness misses của120s, cần giảm map/control tail rồi qua gate120s
trước300/600s. Native TSDF mesh và GPU memory vẫn là limitations riêng.
Lượt sync chỉ sửa tài liệu; `git diff --check` exit0, không chạy tests/demo mới.

### Hydra long-demo readiness — implementation checkpoint — 2026-11-05

Checkpoint mới nhất supersedes ghi chú documentation-only bên dưới. Profile bền
`configs/demo-00805.hydra-long-demo.local.json` preflight ready, UHD OpenVINO
GPU và X11 đã kết nối. Demo UI-on 30–60 giây trên map00805 đã có artifact hoàn
chỉnh; lệnh chạy và điều kiện nằm trong
[`hydra-long-demo-readiness-plan-2026-11-05.md`](results/hydra-long-demo-readiness-plan-2026-11-05.md).

- **Implemented/correctness-verified:** Hydra native graph + measured RGB-D
  point cloud hiển thị trong UI; source cuối khớp graph. Sửa RSS census race
  chỉ bỏ qua `children` read khi task directory vừa biến mất và process
  identity còn nguyên. Resource-focused suite:88 passed, exit0.
- **Runtime-validated:** smoke30s sau sửa RSS hoàn tất,268/268 frames, graph
  revision9, clean worker shutdown; RSS427/427 supported, zero missing/read
  errors. GPU process-memory provider unavailable.
- **D2/D3 chưa qua:** run120s trước fix RSS có6/546 freshness misses (1.10%),
  gồm3 pending +3 expired-before-step; tổng proofs525/525, translation LB
  4.539m. Map update p95/max148.5/295.9ms; tail tập trung vào core/raycast/
  vote. Nguyên nhân RSS đã sửa và xác nhận30s, nhưng run120s cũ vẫn incomplete;
  chưa có candidate map-core parity-safe giảm tail đủ.
- **Gate:** demo30/60s được dùng để trình diễn ngắn; không chạy120s lại cho tới
  khi tối ưu map qua offline parity/tail gate rồi xác nhận30/60. Chưa chạy
  300/600s hoặc map thứ hai; cần hai120s sạch trước300s. Full suite chưa chạy
  lại; baseline trước lượt này2436 passed/10 skipped/32 failed.
- **Artifacts:** `.runtime/hydra_ws/artifacts/hydra-readiness-D1-00805-20261105/`
  (`ui-on-30s-rss-fix`, `ui-on-60s-cloud-flush`, `ui-on-120s-first-gated`).
  Full evidence tại `docs/results/hydra-long-demo-readiness-2026-11-05.md`.

### Hydra long-demo readiness report — 2026-11-05 — documentation only

Đã tạo [báo cáo vấn đề và kế hoạch long demo](results/hydra-long-demo-readiness-plan-2026-11-05.md):
kiểm tra evidence UI-on60/120s, các seam3D còn dùng legacy data, map/control
freshness tail, profile/map readiness, resource limitations; kế hoạch D0–D6
đi từ baseline/projection/latency đến120→300→600s và map thứ hai. Các performance
targets mới là đề xuất cho campaign, không phải kết quả pass hoặc thay checker.

Lượt này chỉ tạo tài liệu, không sửa runtime/profile, chạy tests hoặc native demo.
Kiểm links/fences/coverage các task exit0; `git diff --check` exit0. Artifact:
`.runtime/hydra-long-demo-report-20261105/document-check.json`. Gate chưa cho lên
300s ở checkpoint bên dưới vẫn giữ nguyên; chưa tuyên bố demo3D hoặc long-run đạt.

### Kiet_branch2 / Hydra — checkpoint smoke UI-on 60 s → 120 s — 2026-11-05

**Profile:** `/tmp/neusymnav-telemetry-smoke-00805-ui-on.json`, SHA-256
`1aa2e14bb126cb66cce3982fcd98a9536e55c1b2bbe14a6f2571f6bfd815899d`, scene
00805, seed 0 applied, UI on, OpenVINO UHD active without fallback. Both runs
used this exact profile and completed with exit 0.

**60 s gate passed:** 457 frames; 224 executed controls and 224 source-matched
proofs; `missing_command_proofs=0`; no `navigation_source_pending`; body
translation lower bound 1.801 m (0.775 m first half, 1.027 m second half).
There was one deadline-expired movement command. The first 10.28 s had no
translation while heading error decreased monotonically during alignment; then
the robot tracked goals and moved. Recording/export complete, Hydra graph
revision 12, UI final publication 122 rendered, clean shutdown.

**120 s result — do not advance to 300 s yet:** 892 frames; 433 executed controls
and 433 source-matched proofs; `missing_command_proofs=0`; translation lower
bound 3.543 m (1.544 m first half, 1.984 m second half). No `expired_before_step`
or movement command with `deadline_expired`; the 16 `expired_or_zero` records
were no-op stops for blocked goal, stale depth or reached viewpoint. However,
there were 13 `navigation_source_pending` results: 11 isolated events and two
consecutive events at 119.8/120.02 s at the run boundary. Control interval p95
increased from 415 ms at 60 s to 462 ms at 120 s (max 589 ms). Two sampled
10-second intervals had under 0.1 m translation: the initial alignment and a
goal change at 71–81 s; both traces show monotonic heading convergence followed
by tracking, not oscillatory spinning. This is measured progress, but pending
source frequency and the run-boundary pair remain unresolved.

Both 120 s recording/Hydra export completed (graph revision 25), UI publication
244 rendered and shutdown was clean. RSS had 1,043/1,043 supported samples with
sampled peak 1,998,946,304 B. GPU memory remains unsampled and
`boundedness_certified=false`.

**Root cause traced and confirmed:** coordinator returns pending when the exact
map is unavailable or either source exceeds the 300 ms freshness bound. In the
120 s artifact, 12/13 pending controls had depth age 301–314 ms while that
frame's NavMap update was still running or had just completed; the remaining
fresh-depth frame saw its map update finish 196 ms after control returned.
NavMap update p50/p95/max was 81/200/414 ms; control navigation wait
82/192/288 ms. The 30 s confirmation produced one pending at the run boundary:
depth age 84 ms, wait 35 ms, with its update finishing 107 ms after control.
This confirms boundary pending occurs when shutdown reaches an in-flight map
update; the other 12 are freshness misses. The 300 ms gate was not relaxed.

**Next gate:** reduce map/control latency while preserving freshness and
fail-closed behavior, then repeat a bounded UI-on smoke. Do not start 300 s yet:
the 120 s run still has 12 in-run freshness misses and its control p95 is higher
than the 60 s run. Detailed cross-artifact analysis:
`.runtime/hydra_ws/artifacts/hydra-telemetry-counter-fix-smoke-00805-20261105/navigation-source-pending-investigation.json`.

**Commands/checks:** profile preflight — exit 0 (`ready=true`, `issues=[]`);
60 s, 120 s and 30 s UI-on smokes — each exit 0; JSON artifact audit and
`git diff --check` — exit 0. No 300 s run was started.

### Kiet_branch2 / Hydra — audit expired_or_zero và resource sampling — 2026-11-05

**Implemented:** `RunMeasurements.control()` chỉ tăng
`missing_command_proofs` khi worker báo lệnh đã `executed=true` nhưng không có
proof. Lệnh stop/expired không tạo simulator action nên không còn bị tính nhầm
là thiếu actuation proof. Không thay đổi hành vi điều khiển hoặc resource sampler.

**Correctness-verified:** test hồi quy mới trước sửa đỏ (counter là 1 thay vì 0);
sau sửa, `./.venv/bin/python -m pytest tests/test_runtime_measurement_wiring.py
tests/test_runtime_measurements.py tests/test_actuation_measurements.py -q` — 86
passed, exit 0. Lệnh thực thi thiếu proof vẫn được đếm; zero command không.

**Artifact audit:** trong smoke UI-on 60 s tại
`.runtime/hydra_ws/artifacts/hydra-bootstrap-command-sweep-00805-20261105/ui-on-60s/`,
cả 11 `expired_or_zero` đều là lệnh 0 m/s và 0 rad/s, vì thế không có simulator
step để tạo actuation proof. Sáu lệnh đến từ `committed_goal_blocked`, hai từ
`frontier_viewpoint_reached`, ba từ `depth_stale`. Cả 228 lệnh worker báo
`executed` đều có 228 proof; số executed thiếu proof là 0. Audit chi tiết:
`expired-zero-resource-audit.json`. Con số cũ “11 missing proofs” là sai nghĩa
counter, không phải 11 lần robot đã chạy mà mất bằng chứng.

**Resource sampling:** RSS sampler đã khôi phục và hoàn tất: 609/609 mẫu được hỗ
trợ, không mẫu truncated, không lỗi đọc cuối cùng, đỉnh RSS được lấy mẫu
1,934,004,224 B; một phản hồi tới sau khi sampler dừng bị loại có ghi nhận. Tuyệt
nhiên đây vẫn là peak quan sát giữa các mẫu, không phải chứng minh giới hạn tuyệt
đối. Cadence không đều: p50 gap 119 ms, p95 261 ms, tối đa 832 ms; thời gian gọi
provider p50 17.7 ms, p95 167 ms, tối đa 540 ms. Có 21 lần thiếu tiến trình tạm
thời trong census (19 lúc đầu, 2 lúc cuối), đều retry thành công. GPU memory vẫn
chưa được sample: 0 mẫu, `no_usable_provider`; nhận diện OpenVINO GPU không cung
cấp phép đo bộ nhớ GPU theo process. Vì vậy `boundedness_certified=false` vẫn
đúng.

**Runtime-validated:** UI-on smoke 20 s trên scene 00805, seed 0 và cùng profile
hash `1aa2e14b…`; preflight `ready=true`, `issues=[]`. Run exit 0,
`outcome=completed`, 163 frames, OpenVINO `openvino_gpu` không fallback, recording
complete, Hydra export graph revision 5 complete; UI publication cuối 43 đã
render và sensor/UI/resource shutdown sạch. Artifact mới ghi
`missing_command_proofs=0`. Có 78 control result `executed` và source-key join
cho thấy cả 78 có proof. Bảy `expired_or_zero` gồm sáu zero-motion stop và một
deadline-expired command; thêm một `expired_before_step`. Tổng 79 proof record
không hàm ý có 79 lệnh executed. `actuation.complete=false` vẫn theo contract vì
body distance chỉ là lower bound; không phải counter missing-proof còn dương.
Artifact xác minh: `.runtime/hydra_ws/artifacts/hydra-telemetry-counter-fix-smoke-00805-20261105/ui-on-20s/`.

**Gate:** giữ nguyên thời lượng; bước kế tiếp là đánh giá riêng cadence RSS tail
và bổ sung provider Intel GPU có process attribution được kiểm chứng trước khi
tuyên bố telemetry GPU đầy đủ. Không dùng kết quả này làm chứng nhận long-run.

**Commands/checks:**

- `./.venv/bin/python -m pytest tests/test_runtime_measurement_wiring.py::test_intentional_zero_command_does_not_count_as_missing_actuation_proof -q` — trước sửa: 1 failed (đỏ mong đợi), exit 1.
- `./.venv/bin/python -m pytest tests/test_runtime_measurement_wiring.py tests/test_runtime_measurements.py tests/test_actuation_measurements.py -q` — 86 passed, exit 0.
- Offline audit trên các JSON artifact nêu trên — 609 RSS mẫu được hỗ trợ; 228/228 executed có proof; 11/11 zero command không cần proof.
- `NEUSYMNAV_HYDRA_DEMO_CONFIG=/tmp/neusymnav-telemetry-smoke-00805-ui-on.json OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 bash tools/run_hydra_map_demo.sh 00805 20 .runtime/hydra_ws/artifacts/hydra-telemetry-counter-fix-smoke-00805-20261105/ui-on-20s` — exit 0.
- Smoke verification: `telemetry-counter-verification.json` — missing proof counter 0, 78/78 executed source-key proof, clean shutdown.

### Kiet_branch2 / Hydra — bootstrap theo xung quét và live smoke — 2026-11-05

**Implemented:** `MotionGuard` không còn áp corridor bootstrap tối thiểu 10 cm
ngoài quãng tịnh tiến của lệnh. Chiều dài kiểm tra là tốc độ tiến nhân với
thời lượng khả dụng, giới hạn bởi command horizon và phần depth/map TTL còn lại;
phần bù độ cong dùng cùng thời lượng đó. Các kiểm tra `_clear` về footprint,
`FREE`, floor support, clearance và đường path được giữ nguyên. Cấu hình YAML bỏ
tham số corridor cũ không còn được dùng.

**Correctness-verified:** regression test ban đầu đỏ vì lệnh 0.2 m/s trong 100 ms
đưa 10 cm thay vì 2 cm. Sau sửa, 101 test safety/navigation/map/goal-feedback/
robot-geometry pass trong 9.08 s. Test có depth hit ngoài footprint của xung ngắn nhưng trong
corridor 10 cm cho phép lệnh; depth hit trong footprint và depth không hợp lệ
vẫn chặn. Phát lại dữ liệu thật source frame 179 bằng profile geometry ghi lại:
10 cm → 123/124 cell, `bootstrap_blocked`; 1.5 cm → 105/105, `bootstrap_ready`.
Artifact: `.runtime/hydra_ws/artifacts/hydra-bootstrap-command-sweep-00805-20261105/frame179-verification.json`.

**Runtime-validated:** preflight hồ sơ `ready=true`, `issues=[]` (exit 0);
OpenVINO liệt kê `['CPU','GPU']` và `xdpyinfo -display :0` kết nối thành công
trong host context. Smoke UI-on 60 s, scene 00805/seed 0/vị trí đầu/config cũ,
exit 0; worker xác nhận `backend_active=openvino_gpu` không fallback, 459/459
frame đã lưu, Hydra export revision 14 complete, UI publication 122 đã render,
shutdown sạch. Không có `bootstrap_blocked` hoặc
`committed_goal_waiting_after_collision`. Với goal cũ
`frontier-a0782d8528ca`, frame 178–180 thực thi ba lệnh tiến ở 0.06/0.12/0.15
m/s; frame 181 đánh dấu `frontier_viewpoint_reached`, frame 182 chọn goal mới.
Body translation lower bound là 1.927 m. Control outcomes: 228 executed, 11
`expired_or_zero`; không có `navigation_source_pending` hay
`expired_before_step`.

**Giới hạn:** `actuation.complete=false`, còn thiếu 11 command proof tương ứng
với các zero/expired result; resource boundedness chưa được chứng nhận và GPU
resource sampler báo `no_usable_provider`. Smoke chứng minh frame 179 đã qua
guard và robot có tiến triển an toàn đo được trong 60 s, chưa chứng minh long-run
ổn định. Full non-native suite: 2,426 passed, 1 skipped, 9 deselected, 32 failed
trong 186.45 s; failures thuộc evaluation-measurements, execution-proof,
global/live-map publication, UI hash pin, navigation display và UI cadence.
Nhóm tests trực tiếp liên quan guard/navigation đều pass; lỗi suite rộng chưa
được điều tra trong task này.

**Next gate:** tiếp tục soát 11 thiếu command proof và các 11 `expired_or_zero`
trong artifact; giữ duration hiện tại, chưa tăng lên 120 s cho tới khi proof
telemetry đầy đủ và xác nhận không có regression về footprint/clearance.

**Commands/checks:**

- `./.venv/bin/python -m pytest tests/test_guard_forward_corridor.py tests/test_navigation.py tests/test_navmap.py tests/test_local_bootstrap_integration.py tests/test_guard_goal_feedback.py tests/test_robot_geometry_binding.py -q` — 101 passed, exit 0.
- `./.venv/bin/python -m pytest tests -q -m 'not native'` — 2,426 passed, 1 skipped, 9 deselected, 32 failed, exit 1.
- `NEUSYMNAV_HYDRA_DEMO_CONFIG=/tmp/neusymnav-telemetry-smoke-00805-ui-on.json OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 bash tools/run_hydra_map_demo.sh 00805 60 .runtime/hydra_ws/artifacts/hydra-bootstrap-command-sweep-00805-20261105/ui-on-60s` — exit 0.

Smoke artifact: `.runtime/hydra_ws/artifacts/hydra-bootstrap-command-sweep-00805-20261105/ui-on-60s/`.
Runtime log: `/tmp/neusymnav-bootstrap-command-sweep-00805-ui-on-60s.log`.

### Kiet_branch2 / Hydra — truy nguyên collision wait và smoke xác nhận — 2026-11-05

**Đã hiểu chuỗi của artifact 60 s trước.** Ở source frame 179, navigator muốn
tiến 0.15 m/s tới goal cách khoảng 5.8 cm. `MotionGuard` yêu cầu bootstrap
corridor tối thiểu 0.10 m (`navigation/safety.py:72`); replay đúng depth và pose
ghi nhận 123/124 cell hợp lệ, cell thiếu là `OCCUPIED` ở rìa capsule. Xung thực
tế chỉ đi 1.5 cm và sweep tương ứng đạt 105/105 cell. Guard trả
`bootstrap_blocked`; coordinator báo goal failure, nhưng chế độ commit giữ goal.
Policy sau đó phát `committed_goal_waiting_after_collision` qua 46 revision có
map khớp source, không phải chờ map. Watchdog generic mới bỏ goal sau 8.19 s / 47
revision. Đây là ngưỡng bootstrap quá bảo thủ cộng với commit-goal cooldown,
không phải robot đâm vào vật cản trong xung đã cấp.

**Căn hướng cuối là đoạn riêng.** Sau khi goal cũ bị bỏ, run trước chọn goal mới,
phát 12 xung quay phải trong khoảng 2.38 s; heading error giảm một chiều từ
−0.618 xuống −0.124 rad, rồi robot chuyển sang tracking và tiến. Không thấy quay
qua lại; cadence điều khiển thưa làm căn hướng chậm.

**Runtime-validated (smoke xác nhận 60 s, cùng profile/UI-on/scene/seed/pose):**
preflight `ready=true`, `issues=[]`, exit 0; CLI exit 0, outcome `completed`,
393/393 frame được ghi, Hydra export revision 10 hoàn tất, UI publication 119
không drop và shutdown sạch. Một `bootstrap_blocked` lặp lại; theo sau là ba
`committed_goal_waiting_after_collision` tick (~0.30 s) ở các revision cuối.
Control outcomes: 175 executed, 15 `expired_or_zero`, 6
`navigation_source_pending`, 1 `expired_before_step`; body translation lower
bound 1.367 m. Có ba xung căn hướng một chiều, sau đó ba xung tiến, rồi lần
bootstrap stop ở frame 194. Artifact kết thúc khi reason vẫn là
`committed_goal_waiting_after_collision`; do đó thời gian ngắn không chứng minh
watchdog/recovery đã giải quyết được tình huống.

**Giới hạn và quyết định:** recording và shutdown hoàn tất, nhưng actuation proof
telemetry thiếu 15 command proof (`actuation.complete=false`); RSS boundedness
chưa được chứng nhận và GPU resource sampler không có provider. Kết quả smoke
chỉ xác nhận stop an toàn và diễn biến ngắn, không chứng minh recovery ổn định.
Không chạy 120 s. Bước sau là sửa/đánh giá guard để kiểm tra bootstrap theo
thực tế đoạn swept command ngắn trong khi vẫn giữ footprint/clearance gate, rồi
đặt một test hồi quy trên frame 179; sau đó chạy smoke ngắn và xác nhận goal
được giải phóng, có lệnh tiến mới, không còn chuỗi WAIT kéo dài. Chưa sửa code
trong lượt này.

Artifacts:

- Gốc: `.runtime/hydra_ws/artifacts/hydra-forensic-telemetry-smoke-00805-20261105/ui-on-60s/`
- Smoke xác nhận: `.runtime/hydra_ws/artifacts/hydra-forensic-telemetry-smoke-00805-20261105/ui-on-60s-root-cause-confirmation/`
- **Implemented:** cơ chế goal recovery hiện có và guard vẫn như cũ.
- **Correctness-verified:** replay depth/pose frame 179 phân biệt corridor 10 cm thất bại với swept pulse 1.5 cm đạt; phân tích proof cho thấy heading error giảm một chiều.
- **Runtime-validated:** một smoke UI-on 60 s hoàn tất, nhưng kết thúc khi goal còn WAIT; không đủ điều kiện tăng thời lượng.
- **Commands/checks:** preflight exit 0, smoke CLI exit 0; không chạy test suite trong lượt này.

### Kiet_branch2 / Hydra — telemetry smoke UI-on 60 s — 2026-11-05

**Run/runtime:** preflight cuối cùng `ready=true`, `issues=[]`, exit 0; lần
preflight trước timeout thăm dò Hydra interpreter sau 3 s nhưng retry thành công.
Profile tạm cập nhật hash pin sensor/UI, còn scene 00805, seed 0, initial pose,
UI-on và navigation settings không đổi. Runtime ghi `backend_active=openvino_gpu`,
seed applied. Smoke 60 s exit 0, `outcome=completed`, 455 recording frames, 242
NavMap updates; recording, resource, measurement, collector, Hydra graph revision
11 đều complete. UI final publication 121, zero drop; shutdown sạch.

**RSS (first/second half):** provider calls 348/290 (638 total), accepted samples
637/637 supported, no deadline/truncation/read failure at sampler level. Retryable
provider failures 6/12: mostly transient `FileNotFoundError` in initial/final
children census, plus one thread RSS `ValueError` and one transient proc-stat
`FileNotFoundError` in the second half. All recovered. One final provider result
arrived after stop and was explicitly recorded `discarded_after_stop`; no trace
records dropped. The historical 120 s `ScopeDeadlineError` did not recur.

**NavMap p95/max, first → second half (ms):** update 161.7/216.0 → 172.2/241.4;
prepare 51.3/90.7 → 49.3/83.5; core integrate 130.0/171.0 → 139.7/172.4;
projection 5.1/28.0 → 4.3/28.7; raycast 81.0/142.3 → 90.8/149.0; vote
integration 19.7/91.4 → 48.0/82.9; core snapshot publish 0.1/0.1 → 0.1/0.1;
fresh coverage 3.0/23.3 → 3.9/28.2; NavSnapshot 9.4/27.7 → 7.7/61.2; overview
snapshot 0/0 → 0/0; tile overview 5.4/8.4 → 6.9/18.1. Collector trace is complete,
zero dropped, with all phase spans on 242/242 updates. Update p95/max rose modestly;
second-half max was frame 236 at 241.4 ms, split across core integrate 144.9 ms
(raycast 81.9, vote 59.7), NavSnapshot 61.2 ms and prepare 24.2 ms.

Control interval p95/max was 392.7/478.2 → 391.0/530.3 ms. 240 navigation traces
contain all fields. All 186 accepted actuation proofs are complete and remain
inside 0.15 m/s, 0.524 rad/s and 100 ms command caps. Translation lower bound is
1.408 m, close to the previous 60 s smoke's 1.473 m. However, second half has 47
`expired_or_zero` safe stops versus 7 in the first half; 46 are the navigator's
`committed_goal_waiting_after_collision`, not actuator deadline expiry. There
are also one `expired_before_step` and one `navigation_source_pending`.

**Progress gate:** the final 9.95 s contains only 0.046 m endpoint translation,
12 `turn_right` actions and 4 `move_forward` actions, with about 0.531 rad yaw
change. Goal/path telemetry shows the final goal stays fixed and heading error
decreases from -0.588 to -0.119 rad; this looks like slow one-direction heading
alignment rather than left/right oscillation, but it is still a near-stationary
tail. Latencies are not sharply degrading, though update p95/max and several
stage tails rise modestly. **Do not run 120 s yet**: the tail-progress and
collision-wait conditions did not pass. Investigate why the committed goal waits
after collision and why the final goal consumes ~10 s aligning, then use another
bounded confirmation before advancing the duration ladder.

Command exit 0; no tests run. `native_runtime_validated=false` remains. Artifact:
`.runtime/hydra_ws/artifacts/hydra-forensic-telemetry-smoke-00805-20261105/ui-on-60s/`.

### Kiet_branch2 / Hydra — smoke kiểm chứng forensic telemetry — 2026-11-05

**Runtime-validated (bounded smoke 20 s):** preflight exit 0 (`ready=true`,
`issues=[]`), OpenVINO có Intel UHD GPU và UI X11 hoạt động. Run scene 00805,
seed 0, UI-on kết thúc `outcome=completed`, CLI exit 0; recording và resource
certificate complete, Hydra export revision 5 complete, UI render publication
45/0 drop, shutdown sạch. `native_runtime_validated=false` vẫn là giới hạn P10.

Artifact mới có 358/358 RSS sample được hỗ trợ, trace/provider records đủ và
không bị drop; có 6 retry lỗi thoáng qua (5 `FileNotFoundError` khi census
children, 1 `ValueError` lúc đọc thread RSS), nhưng đều phục hồi. Không có
`ScopeDeadlineError`, truncated sample hoặc result bị bỏ sau stop. Vì deadline
timeout cũ không tái diễn, nguyên nhân chính xác của timeout trong run 120 s cũ
chưa được xác định; telemetry mới hiện đủ phase/PID để khóa nếu tái diễn.

Collector trace có 2,855 record, complete, 0 drop; đủ cả 10 NavMap span trên
82/82 update và navigation diagnostics trên 80/80 control record. NavMap p50/p95/
max là 75.5/186.3/278.2 ms. Đỉnh ở frame 34: core integrate 137.6 ms (raycast
104.5, vote integration 29.3), NavSnapshot 99.2 ms, prepare 32.1 ms; những
thành phần này gần như giải thích toàn bộ update 278.2 ms. Điều này định vị được
nguồn tail trong map/raycast/snapshot, không phải sensor roundtrip đơn thuần;
chưa chứng minh được vì sao frame 406 của artifact cũ đạt 597 ms.

Đoạn cuối smoke có goal/path đầy đủ, goal giữ ổn định, path 8 điểm; heading error
giảm từ khoảng -0.22 xuống -0.108 rad và reason chuyển từ `align_heading` sang
`tracking`. Không thấy dao động trái-phải hoặc đoạn xoay kéo dài trong 20 s này.
Artifact cũ không có goal/path/heading fields, nên run mới chưa giải thích trực
tiếp chuỗi xoay dài ở cuối 120 s; nó xác nhận telemetry cần thiết đã hoạt động.

**Artifact:** `.runtime/hydra_ws/artifacts/hydra-forensic-telemetry-smoke-00805-20261105/ui-on-20s-gpu/`.
Profile tạm trong `/tmp` chỉ cập nhật hash pin sensor/UI theo source hiện tại;
scene, seed, vị trí, UHD, UI và cấu hình chuyển động giữ nguyên. Một run 30 s
trước khi sửa thiếu accessor cho NavMap spans và một run trong sandbox rơi về CPU
được giữ lại để audit, không dùng làm kết luận runtime cuối.

**Next:** artifact đã chứng minh đường ghi telemetry. Chưa mở gate 300/600 s:
timeout RSS cũ chưa tái hiện và run 20 s chưa kiểm tra late-run map tail hay goal
rotation dài. Phân tích tiếp trên recording 120 s hoặc một bounded 60 s có
telemetry; không suy rộng từ smoke này thành long-run stability.

### Kiet_branch2 / Hydra — bổ sung forensic telemetry — 2026-11-05

**Implemented:** RSS provider/sampler nay giữ trace bounded tới 8192 records,
gồm timestamp/duration, số process, RSS/support, attempt count, pha/lớp lỗi/PID,
chi tiết từng retry và disposition `accepted_by_sampler` hoặc
`discarded_after_stop`. Deadline trong process census/thread census được gắn pha
và PID; các bộ đếm/resource-completion rule không đổi. NavMap ghi span theo source
frame cho prepare, core integrate, projection, raycast, vote integration, core
snapshot publish, fresh coverage, NavSnapshot và overview/tile update. Control
trace phiên bản 1 ghi goal ID/XY, số điểm đường đi, tối đa 64 điểm XY lấy mẫu,
lookahead, heading error và decision reason. Không đổi TTL, safety, policy hay
quyết định điều khiển.

**Correctness-verified:** chưa. Static checks `python3 -m py_compile` trên các
module đã sửa và `git diff --check` đều exit 0. Không chạy product test vì yêu
cầu hiện tại là triển khai telemetry, không yêu cầu chạy test. **Runtime-validated:**
chưa; không chạy simulator, chưa sinh artifact mới và chưa xác nhận trace thực tế
được serialize/đọc lại từ run.

**Artifact/gate:** telemetry được ghi vào artifact run kế tiếp. Cần kiểm tra lại
smoke bounded để xác nhận trace RSS có phân loại sample timeout/late-discard;
NavMap subspans cộng khớp với envelope update; và chuỗi heading error/goal/path
giải thích đoạn xoay cuối. Run 120 s cũ vẫn incomplete, do đó chưa mở gate cho
300/600 s.

### Kiet_branch2 / Hydra — UI-on duration ladder 30/60/120 s — 2026-11-05

**Profile/control:** ba run lần lượt 30/60/120 s giữ cùng config SHA
`8470a61a…43c8`, scene 00805, seed 0, pose khởi đầu và UI-on. Goal blocked
`[-0.175, 0.575]` được recovery nhất quán sau 6 map revision mới trong khoảng
1.25–1.65 s; planner chọn goal mới. Translation lower bound tăng
0.602 → 1.473 → 2.906 m. Có 4 goal ID / 2 viewpoint reached ở 60 s và 6 goal
ID / 4 viewpoint reached ở 120 s. Smoke 60 s không có cửa sổ đứng yên 10 s sau
giai đoạn căn hướng đầu tiên. Smoke 120 s có thêm một cửa sổ cuối 10 s chỉ tiến
0.017 m; 25/29 proof trong cửa sổ đó là lệnh xoay phải cho cùng một goal, dấu
hiệu robot lại căn hướng/đứng lâu tại goal.

**Latency/control:** control interval mean/p95 30→60→120 s là
277/489 → 286/445 → 291/453 ms. NavMap update p50/p95 là 83/256 → 90/187 →
86/203 ms; exact-map wait p50/p95 là 83/250 → 91/189 → 87/203 ms. 120 s có
11 `navigation_source_pending` (so với 2 ở 60 s), 15 `expired_or_zero`, một
`expired_before_step` và một `yaw_preflight_unavailable`. Các zero là safe stop:
6 blocked-goal, 5 depth-stale, 4 viewpoint-reached. Nửa sau run 120 s chậm hơn
nửa đầu: NavMap p95 175→222 ms/max 274→597 ms; control p95 445→477 ms/max
702→740 ms. TTL và safety không thay đổi.

**Outcome/gate:** run 60 s exit 0, completed, recording 419/419, Hydra revision
12 complete, UI final seq 120 rendered/0 drop, shutdown sạch. Run 120 s exit 1,
`outcome=incomplete`: recording 817/817, Hydra revision 23 complete, UI final
seq 249 rendered/0 drop và runtime/sensor/UI shutdown sạch; nhưng measurement /
resource certificate không complete do RSS sampler có 1 truncated sample, 1
deadline exhaustion và 3 read errors. RSS peak quan sát được khoảng 1.997 GB,
không có breached resource; GPU peak vẫn không có provider. Do artifact 120 s
incomplete, latency tail xấu dần và cửa sổ cuối thiếu tiến triển, **không chạy
300 s**.

### Forensic offline follow-up — artifact 120 s — 2026-11-05

Đọc trực tiếp `summary.json`, `measurements.json`, `control-invocations.json`,
413 pose/control proofs, stage trace và mã sampler/controller; không khởi động
simulator. Kết luận chi tiết, gồm giới hạn không thể suy ra từ artifact, nằm ở
[báo cáo forensic](results/hydra-branch2-navigation-recovery-00805.md#offline-forensic-analysis-120-s).

- **RSS:** nguyên nhân trực tiếp của certificate incomplete là 1/1029 sample
  bị đánh dấu truncated; diagnostics ghi đúng 1 `ScopeDeadlineError` trong
  `ProcTreeProvider.__call__`. Sampler chỉ cấp `complete=true` khi mọi sample
  đều có RSS hợp lệ, nên một lần timeout đủ làm CLI exit 1. Có thêm 25 lần
  process biến mất và 3 lần đọc `/proc` lỗi; các retry phần lớn phục hồi. Mã
  artifact không lưu thời điểm/pha census hoặc PID của sample lỗi, nên chưa biết
  chính xác thao tác nào chạm deadline. 1030 provider calls so với 1029 sample
  được sampler nhận phù hợp với một phản hồi cuối bị bỏ khi stop bật; đây là
  suy luận từ luồng đóng sampler, không phải một record per-sample.
- **NavMap:** p50/p95/max toàn `navmap_update` là 86/203/597 ms; sensor
  navigation roundtrip p50/p95/max là 18/48/132 ms. Các đỉnh map ở frame
  387/397/406 lần lượt 527/568/597 ms, trong đó frame 406 chỉ có 25 ms sensor
  roundtrip. Bằng chứng nghiêng về công việc trong NavMapper, không phải sensor
  roundtrip đơn thuần. Stage hiện gộp ray-budget/projection, integrate/raycast,
  snapshot/coverage và tile overview; artifact chưa chia nội bộ nên chưa thể
  quy cho một hàm cụ thể. Runtime dùng CPU/Numba NavMap, không dùng UHD cho lane này.
- **Goal cuối:** proof lưu 39 lệnh `turn_right` liên tiếp cho goal
  `frontier-3c50d0f61d33-view-34--20`; yaw đổi một chiều từ 0.254 xuống
  -1.494 rad (khoảng 100 độ), không đảo dấu. Sau căn hướng, 5 proof kế tiếp đã
  `move_forward` cho cùng goal. Vì vậy dữ liệu không chỉ ra vòng xoay trái-phải
  hay goal không có route; nó chỉ ra căn hướng một chiều quá lâu. Trong cửa sổ
  cuối 10 s, translation chỉ 0.017 m và 25/29 proof là turn. Lệnh quay bị chặn
  ở 100 ms horizon trong khi control interval ở khoảng 0.3 s; giữa các tick có
  chờ exact-map. Tail NavMap/pending làm tốc độ phát xung quay hữu hiệu thấp.
  Proof không lưu goal XY/path/heading-error theo tick, nên chưa chứng minh được
  vì sao policy chọn viewpoint đó hoặc liệu replan có làm góc mục tiêu trôi.

Full 412-step offline NavMap rebuild được thử nhưng mất hơn 3 phút mà chưa sinh
kết quả, sau đó chủ động dừng (exit 130); không coi đó là replay pass. Phân tích
trên là phép đọc dữ liệu thô đã lưu, không replay lại NavMap. Gate tiếp tục đóng:
chưa chạy dài hơn cho tới khi có telemetry nội bộ NavMap, per-sample RSS error
phase/timestamp, và goal/path/heading trace đủ để xác nhận rồi có lại artifact
120 s đạt completion.

Artifacts: `.runtime/hydra_ws/artifacts/hydra-goal-recovery-smoke-00805-20261105/ui-on-{30s,60s,120s}/`.
CLI exit sidecars nằm cạnh từng folder. `native_runtime_validated=false` cho cả
ladder; 60 s là runtime-complete, 120 s chưa đạt completion contract.

### Kiet_branch2 / Hydra — blocked-goal recovery live confirmation — 2026-11-05

**Root cause:** committed frontier goal `[-0.175, 0.575]` ban đầu có route,
nhưng map mới làm một ô lân cận trong footprint robot trở thành occupied; goal
không còn traversable. Planner/MotionGuard trả zero stop đúng theo safety
contract. Watchdog đã có sẵn: sau tối thiểu 1 s và 6 map revision mới, đánh dấu
goal failed, bỏ commitment và tìm viewpoint khác. Không biến goal bị chặn thành
free, không nới TTL/footprint/unknown-space guard.

**Runtime-validated (bounded, live 30 s):** preflight của profile UI-on pass
(`ready=true`, `issues=[]`); host OpenVINO liệt kê CPU+GPU và `Intel(R) UHD
Graphics (iGPU)`, X11 `:0` kết nối. Run cùng scene 00805, seed 0, pose ban đầu
và profile UI-on; detector dùng `openvino_gpu`. Watchdog giải phóng goal sau
1.297 s / 6 map revision; planner chọn goal mới có route. Run có 94 `executed`,
9 `expired_or_zero` (6 goal-blocked stop, 3 depth-stale safe stop), 5
`navigation_source_pending`. Sau 48 tick `align_heading`, có 46 `move_forward`
action; actuation proof và pose sidecar ghi translation lower bound **0.602 m**.
Tốc độ lệnh tối đa 0.15 m/s, horizon tối đa 100 ms; cả 94 accepted proof đều
complete, source age tại thời điểm issue tối đa 286 ms. Ba depth-stale event bị
chặn an toàn.

CLI exit 0, `outcome=completed`, recording 214/214, native Hydra graph revision
7 complete; runtime, sensor, UI shutdown sạch. UI render final publication seq
67, 0 drop. Control interval mean/p50/p95/max 277.3/252.6/489.3/570.8 ms.
`native_runtime_validated=false`; GPU memory peak không có provider. Smoke 15 s
trước đó kết thúc sau 35 lệnh xoay, gần ngưỡng căn hướng; không chứng minh được
tịnh tiến vì chưa tới control tick đầu tiên sau khi căn hướng. Smoke 30 s này
xác nhận phần tịnh tiến xảy ra; chưa phải nghiệm thu run dài.

**Correctness-verified:** `PYTHONPATH=src:tests .venv/bin/pytest -q
tests/test_guard_goal_feedback.py tests/test_navigation.py
tests/test_controller_corner_pulse.py tests/test_navigation_motion_continuity.py`
— 72 passed, exit 0. Artifact:
`.runtime/hydra_ws/artifacts/hydra-goal-recovery-smoke-00805-20261105/ui-on-30s/`.
Giữ duration ở smoke ngắn cho tới khi mục tiêu coverage P10 và resource proof
được kiểm tra riêng.

### Kiet_branch2 / Hydra — command forensics, completion semantics, smoke — 2026-11-05

**Implemented:** telemetry của mỗi kết quả actuation giữ decision/command reason,
v/w, issued/deadline và `failure_detail`; phân biệt `zero_motion_command` với
`deadline_expired`. Hydra-only profile không còn bị hạ `incomplete` chỉ vì thiếu
legacy bundle, nếu native graph export, recording, measurements và cleanup đều
hoàn tất. `native_runtime_validated` vẫn là gate riêng.

**Correctness-verified:** các test tập trung cho actuation/telemetry và Hydra
export pass; nhóm liên quan đạt 123 passed, 3 deselected (exit 0), sau đó 4 test
trực tiếp cho thay đổi cuối đạt 4 passed (exit 0). `git diff --check` được chạy
ở cuối task. Ba test deselected là các pin SHA UI cũ ngoài phạm vi task.

**Runtime-validated (bounded, 15 s):** artifact
`.runtime/hydra_ws/artifacts/hydra-ui-diagnostics-smoke-00805-20261105/ui-on-15s-final/`
CLI exit 0, outcome `completed`; 96/96 frame ghi bền vững, Hydra native graph
revision 5 complete, runtime/sensor/UI shutdown sạch. UI render publication cuối
sequence 44, 0 drop. OpenVINO GPU và desktop X11 đã qua preflight; detector dùng
GPU trên run này. Có 47 control ticks: 35 `executed`, 8 `expired_or_zero`, 4
`navigation_source_pending`; interval mean/p50/p95/max 316.7/285.6/465.4/514.4
ms. Cả 8 `expired_or_zero` là zero command, không phải command nonzero hết hạn:
7 do `committed_goal_blocked:goal_not_traversable`, 1 do `depth_stale` sau
decision `nav_stale`. Bốn pending gồm ba source chạm/vượt freshness 300 ms khi
NavMap cập nhật (map update 217.6–316.7 ms; wait 193.1–273.9 ms) và một tick
cuối bị run deadline cắt khi map update còn chạy. Freshness/stop safety không
bị nới. Các 35 proof đều là `turn_right`; sampled body XY không đổi, nên smoke
chưa cho thấy tiến triển tịnh tiến.

**Forensic update trên live A/B cũ:** trong 15 `navigation_source_pending`,
10 là source/map không hoàn tất trong budget freshness 300 ms, 5 là tick cuối
bị deadline run kết thúc khi source/map còn in-flight. Cũ chưa có payload lệnh
để diễn giải `expired_or_zero`; telemetry smoke nay chứng minh tên này gộp zero
safe-stop với expiry, và trường `failure_detail` đã tách được hai loại cho run
mới. Không có căn cứ để xem các zero stop cũ là lỗi IPC.

**Gate:** smoke đạt completion/profile và lifecycle, nhưng điều khiển chưa đạt
mức chấp nhận cho tăng thời lượng: không tịnh tiến, goal bị kẹt
`goal_not_traversable`, có stale-depth stop và map-wait vượt freshness. Chưa chạy
nấc 30/60/300/600 s; trước tiên cần sửa/điều tra khả năng đi qua của goal và
đường cập nhật NavMap/cadence, rồi lặp smoke ngắn để chứng minh tịnh tiến an toàn.
`native_runtime_validated=false`; resource GPU peak cũng chưa được đo do provider
không khả dụng.

### Kiet_branch2 / Hydra — final UI graph publication and cadence diagnosis — 2026-11-04

**Implemented:** sau khi Hydra close drain các input đã nhận, coordinator đọc lại
snapshot/projection và phát publication cuối. Khi đóng, UI transport drain publication
đang chờ, chờ child xác nhận sequence đã render rồi mới dừng; report shutdown ghi rõ
sequence cuối và trạng thái render. Control lane không chờ UI trong lúc chạy.

**Correctness-verified:** regression tests chứng minh Hydra revision 6 được phát sau
close và UI render publication graph revision 6 trước shutdown. Bộ focused gồm
`tests/test_hydra_runtime.py`, `tests/test_ui_transport.py`,
`tests/test_hydra_projection.py`, `tests/test_runtime_scheduling.py`: 62 passed,
exit 0; `git diff --check` exit 0.

**Correctness/runtime follow-up:** A/B replay trên cùng recording SHA
`60dd7fc2…b7bf20` (172 observation) với UI tắt/bật xử lý cùng 7 detector call,
7 commit và Hydra revision 4. Cả hai dùng Torch CPU vì runtime hiện chỉ thấy
OpenVINO `CPU`; để replay được, hai profile A/B cùng đặt sampling `novelty`.
Wall time là 63.1 s off và 55.7 s on với Qt offscreen. Một cặp này không chứng
minh UI tăng tốc; replay không chạy sensor/control loop nên không đo cadence điều
khiển. Qt `:0` không truy cập được trong môi trường này.

Smoke UI live offscreen 15 s đã render publication cuối seq 34 chứa graph revision
3, trùng native export revision 3; UI ACK seq 34, 0 drop, UI/sensor/Hydra shutdown
sạch. Native graph có 0 node/edge. Run `incomplete` theo contract legacy do không
có hierarchy/NavMap/object bundle. Có 24 `executed`, 7 `expired_or_zero`, 2
`navigation_source_pending`; 32/32 control interval vượt 100 ms, mean 450 ms.
Detector fallback Torch CPU; đây không xác nhận cadence UHD. Một smoke 30 s offscreen
trước đó có UI exit `-6` và thiếu ACK; log không được giữ bởi close cũ. Close mới
thoát chờ khi child chết và vẫn lưu log ở các lần lỗi tiếp theo. Chưa biết nguyên
nhân cụ thể của exit `-6` trước đó.

**Verification:**
`PYTHONPATH=src:tests pytest -q tests/test_ui_transport.py tests/test_hydra_runtime.py tests/test_hydra_projection.py tests/test_runtime_scheduling.py tests/test_launcher.py -k 'not shipped_ui_script_sha_matches_local_package'`
— 93 passed, 3 deselected, exit 0. `git diff --check` exit 0.

**Artifacts:** A/B ở
`.runtime/hydra_ws/artifacts/hydra-openvino-recorded-ab-00805-20261104/`;
smoke ở `.runtime/hydra_ws/artifacts/hydra-openvino-ui-catchup-00805-15s-20261104/`.
Cadence UHD/live A/B, desktop X11, và runtime trên UHD vẫn chưa được xác nhận.
Không tăng thời lượng simulator hoặc đặt UHD làm mặc định.

**Cadence replay feasibility audit:** recording complete SHA
`60dd7fc2…b7bf20`, 85 primary + 87 navigation observations, source timeline
57.211 s; pose sidecar covers 86/87 navigation frames (startup frame 0 has no
control tick), and control sidecar has 85/85 source-bound trace rows. The
existing replay path never calls `control_step` or reads these sidecars, so the
previous replay A/B is not a control-cadence A/B. Recorder fields are sufficient
for an isolated replay harness. Pose admission deliberately rejects `replay:`
clocks at the live control seam, so a harness must preserve that safety boundary,
pace the recorded timeline, and use a separate non-actuating interface. Current
UI-on trace p50/p95 control intervals
327.1/527.4 ms; primary sensor roundtrip 102.56/207.34 ms, NavMap update
97.22/220.69 ms, exact-map wait 100.19/211.77 ms (p50/p95), n=85/86/85.
Audit artifact and details: `docs/results/hydra-branch2-live-ui-00805.md`.
This single-run breakdown does not establish UI causality; no cadence A/B or
additional simulator run has been made.

**Offline control-cadence A/B follow-up:** a dedicated `replay_control_cadence`
path and `tools/run_replay_control_cadence_ab.py` now join the checksummed source
recording to its measured pose/control sidecar and call the existing control
path using an isolated `replay:` clock and `OfflineReplayActuator`. Offline mode
is explicit at Coordinator/Navigator/MotionGuard, rejects live clocks and real
actuator objects; no Habitat client or simulator is created. NavMapper receives
only pose-bound navigation-depth frames in this mode. The A/B profiles differed
only in `ui.enabled` and passed preflight. Both arms used the same input SHA
`60dd7fc2…b7bf20`, 5 s pre-roll, 15 s measured source window, 112 observations,
42 control ticks, 42/42 exact map matches, and clean shutdown. Control interval
mean/p50/p95/max was 353.98/331.38/506.79/619.04 ms with UI off and
355.83/336.27/541.31/722.51 ms with UI on. Replay-generated
`expired_or_zero` was 0/1; `navigation_source_pending` was 0/0. The fake actuator
immediately acknowledges fresh nonzero commands and does not model real sensor
roundtrip/actuation delay: the selected original live window had 3
`expired_or_zero` and 3 pending. Both detector arms fell back to Torch CPU
(OpenVINO worker exposed only CPU). This one pair is offline evidence only; it
does not certify live UHD cadence or open the 300/600 s gate. Artifacts:
`.runtime/hydra_ws/artifacts/hydra-openvino-control-cadence-ab-00805-20261104/final-15s/`.
Focused tests: 86 passed, 3 deselected, exit 0; A/B artifact checks and
`git diff --check` exit 0.

**Live matched A/B preflight recheck:** UI-off/on configs identical except
`ui.enabled`; both `ready=true`, `issues=[]`, same scene/seed0/initial pose.
Runtime OpenVINO probe sees `['CPU']`, `/dev/dri` is absent, and
`xdpyinfo -display :0` cannot open X11. No live simulator was started because
this session cannot meet the requested UHD + visible desktop condition. The
live A/B remains pending in a desktop/runtime session exposing both resources.

**Live UHD + X11 matched A/B — bounded, 3 pairs:** the earlier preflight result
above was superseded when the current host session exposed `/dev/dri` and
`xdpyinfo :0` succeeded. The profile-pinned OpenVINO interpreter reported
`['CPU','GPU']`, `Intel(R) UHD Graphics (iGPU)`; both 15 s profiles were
`ready=true`, identical except `ui.enabled`, with scene 00805, seed 0 and the
same initial pose. Three sequential pairs ran in order off/on, on/off, off/on.
All six detector workers reported `backend_active=openvino_gpu` with no fallback;
all six sensor runs acknowledged seed 0 and shut down cleanly. Every Hydra graph
export completed at revision 5. All three desktop UI arms rendered their final
publication with graph revision 5 (publication sequences 40, 38, 38), zero drops,
and clean UI shutdown.

Control interval mean UI-on minus UI-off by pair was -23.0, +11.0 and +14.5 ms
(paired mean +0.9 ms); p95 deltas were -10.5, +38.5 and +31.2 ms (paired mean
+19.7 ms). `expired_or_zero` totaled 19 off / 21 on; `navigation_source_pending`
8 off / 7 on. Mean paired p50 UI-on deltas were +0.1 ms for primary sensor
roundtrip, -0.1 ms for navigation sensor roundtrip, -2.6 ms for NavMap update
and -1.9 ms for exact navigation-map wait. The three pairs show no consistent
mean-cadence effect, while UI-on p95 was higher in two of three pairs; this is
still a short sample, not a causal or 300/600 s certification.

The CLI returned exit 1 / `outcome=incomplete` on each arm because this Hydra
profile exports no legacy hierarchy/NavMap/object bundle. In all six artifacts
the Hydra-native export was complete and runtime shutdown was clean; no worker
`-9` or UI failure occurred. UI-on had 107–109 coalesced publications and zero
drops. Stage p50/p95 and per-run counts are in
`docs/results/hydra-branch2-live-ui-00805.md`; machine-readable rows are in
`.runtime/hydra_ws/artifacts/live-ui-ab-00805-20261104/live-ab-summary.json`.
JSON validation and `git diff --check` exit 0. No long run was started.

### Kiet_branch2 / Hydra — live UI verification — 2026-11-04

**Implemented/configured:** giữ profile UHD gốc nguyên trạng; tạo profile local
riêng với `ui.enabled=true`, publish 2 Hz. Preflight pass, UI transport kiểm
tra đúng worker pin.

**Correctness-verified:** `tests/test_ui_transport.py`,
`tests/test_ui_publication_cadence.py`, `tests/test_hydra_projection.py` — 36
passed, exit 0. Decoder UI đọc publication cuối với Hydra graph revision 4,
24 nodes/79 edges, status `available`.

**Runtime-validated (bounded):** trong smoke 30 s, cửa sổ `NeuSymNav / Live
Scene Explorer` xuất hiện trên X11 và là active window. Có 80 UI publication
sequences, 0 dropped, 190 coalesced; UI và Hydra đóng sạch. Native Hydra export
đạt revision 6, nhưng UI cuối dừng ở revision 4 nên chưa theo kịp graph cuối.
Smoke exit 1/incomplete do thiếu legacy hierarchy/NavMap/object bundle. UI-on
run có 172 frames, 71 `executed`, 7 `expired_or_zero`, 5
`navigation_source_pending`, translation lower bound 0.283 m.

So với smoke UI-off gần nhất (285 frames, 164 `executed`, 1 pending, 1.304 m),
throughput UI-on thấp hơn. Đây chưa phải so sánh nhân quả do simulator runs
riêng; **chưa được kết luận UI không ảnh hưởng cadence điều khiển**. Không tăng
thời lượng simulator cho tới khi điều tra catch-up cuối và khác biệt throughput.
Chi tiết: [báo cáo live UI](results/hydra-branch2-live-ui-00805.md).

### Kiet_branch2 / Hydra — bốn hướng tiếp theo — 2026-11-04

**Implemented:** launcher giữ kết quả close/export của Hydra, xác minh graph
native và promote manifest lên thư mục run; vẫn đánh dấu generic outcome
`incomplete` khi profile không cung cấp legacy hierarchy/NavMap/object bundle.
Detector `openvino_gpu` kiểm tra runtime có thiết bị GPU trước khi nạp IR; nếu
chỉ thấy CPU thì khởi tạo thất bại có lý do rõ ràng để policy fallback báo đúng
backend đang chạy.

**Correctness-verified:** 7 test OpenVINO pass. Projection actual native graph
(revision 7, 30 nodes, 102 edges) qua UI offscreen cùng 6 test projection/UI
pass. Replay 104 RGB-D frames đo UHD worker p50/p95 402/470 ms so với CPU
1358/1494 ms; UHD nhanh hơn khoảng 3.4x nhưng chỉ 65.3% candidate detections
khớp CPU theo cùng nhãn và mask IoU >= 0.5, đây không phải đánh giá accuracy.
Combined focused run có 42 pass, 10 deselected và 3 lỗi checksum UI đã biết
(`2e6cec…` trong config, `310ae171…` từ source).

**Runtime-validated (30 s bounded):** đúng UHD hoạt động, không fallback;
Hydra xử lý 12 input, graph revision 9 (50 nodes/120 edges), manifest native
complete và clean shutdown. Có 164 lệnh `executed`, 10 `expired_or_zero`, 1
`navigation_source_pending`; net translation lower bound 1.304 m. Goal bị chặn
được nhả sau 1.079 s/9 map revisions. Lệnh smoke exit 1 và outcome vẫn
`incomplete` do thiếu legacy bundle; GPU resource sampler không có provider.

**UI desktop:** đã mở cửa sổ Hydra viewer trực tiếp trên X11 `:0` từ graph đã
ghi (snapshot offline, revision 7: 30 nodes/102 edges), kiểm tra cửa sổ đang ở
foreground. Có lọc layer và chọn node; ảnh QA tại
`.runtime/hydra_ws/artifacts/hydra-openvino-navigation-recovery-00805-30s-20261104/hydra-recorded-graph-desktop.png`.
Đây chưa phải stream live từ coordinator/simulator; widget cũng chưa render
mesh/cloud. **Chưa chứng minh:** độ chính xác detector trên ground truth, GPU
memory peak, và H7 acceptance end to end. UHD vẫn opt-in. Artifact:
`.runtime/hydra_ws/artifacts/hydra-openvino-four-directions-00805-30s-20261104/`;
chi tiết tại [báo cáo bốn hướng](results/hydra-branch2-navigation-recovery-00805.md).

### Kiet_branch2 / Hydra — navigation recovery checkpoint — 2026-11-04

**Implemented:** a committed frontier with the specific failure
`committed_goal_blocked:goal_not_traversable` is now abandoned only after at
least 1 s and 6 distinct fresh map revisions. Other geometric failures retain
the existing 8 s / 20 revision threshold. Planner traversability, unknown-cell
handling, depth/map freshness, footprint clearance, collision filtering and
actuation deadlines are unchanged.

**Correctness-verified:** the focused goal-feedback tests pass (45 passed).
Offline replay of the previous 30 s capture rebuilt all 160 NavMap revisions
with zero revision mismatches. The counterfactual watchdog fired at frame 8;
the old policy held the same blocked goal through frame 56. Commands after the
counterfactual changes the goal are not comparable with the old recording.

**Runtime-validated (bounded):** one same-profile 30 s live smoke recorded the
watchdog firing after 1.383 s and 6 map revisions, then selected a different
reachable goal. It recorded 97 `executed`, 6 `expired_or_zero`, and 1
`navigation_source_pending`; the previous same-profile run had 54
`expired_or_zero`. Hydra processed 8 inputs, produced a non-stale revision-7
snapshot (74 edges), exited cleanly without `-9`, and reported no worker failure.
The Hydra-native graph export is verified and its manifest is complete (7
accepted inputs). The top-level legacy hierarchy/NavMap/object bundle remains
unavailable by design for this Hydra-only profile, so the overall smoke is
still incomplete; the room pipeline was disabled. GPU resource sampling was
unavailable. Details: [navigation recovery report](results/hydra-branch2-navigation-recovery-00805.md).

**Verification:** full non-native suite: 2,435 passed, 1 skipped, 9 deselected,
3 failed, exit 1. The only failures are the known baseline/geometry-only/
appearance UI script SHA mismatch (`2e6cec…` expected, `310ae171…` actual).
`tests/test_guard_goal_feedback.py`: 45 passed, exit 0. No run longer than 30 s
was started and OpenVINO UHD remains opt-in.

### Kiet_branch2 / Hydra — 2026-11-04 — implementation in progress

**OpenVINO UHD integration and bounded live smoke:** the detector now has an
opt-in, hash-pinned `openvino_gpu` backend. It initializes and compiles before
the pipeline accepts semantic frames; a configured `torch_cpu` fallback is
reported explicitly and only applies to initialization failure. Torch CPU
remains the default. Replaying all 95 recorded primary frames through the real
detector worker IPC measured 372.2/431.7 ms steady-state p50/p95 on UHD versus
1,362.2/1,470.0 ms on Torch CPU (about 3.7x/3.4x faster). UHD matched 296/314
CPU detections by same-label and mask-IoU>=0.5 criteria, with 431 candidates;
this is agreement, not accuracy, and shows a material output difference.

A subsequent bounded 30 s simulator smoke confirmed that the active backend
was `openvino_gpu`, with no fallback and 1.69 s warm-up. Preloading removed the
multi-second first-frame startup penalty: live capture-to-detector-return
p50/p95 was 669/910 ms over 7 calls, although p95 is above the 750 ms semantic
TTL. The robot's sampled body poses show 0.708 m net translation, while control
still recorded 54 `expired_or_zero` outcomes. The run is **incomplete**: five
Hydra inputs were accepted, then its child exited with `-9`; no live detector
evidence or object IDs were committed, and no coherent hierarchy/map was
exported. Offline replay found the cause of the parent validation error: the
serializer used packed numeric NodeSymbol values for parent and edge endpoints,
while node IDs used display strings. This was fixed and verified on all six
retained inputs, including frame 78, with clean worker close and 29-node/106-edge
revision-5 projection. The live `-9` most likely followed early graph cleanup
triggered by that projection error; the exact cleanup/exit timestamps were not
retained. The 54 no-motion results match 54 zero navigation decisions caused by
a committed goal being non-traversable (53 blocked decisions plus one
no-progress failure); exact grid-cell cause is absent from the artifact. Keep
the simulator duration bounded and UHD optional until the graph fix is
confirmed live and the blocked goal is diagnosed offline. See the
[OpenVINO integration and smoke report](results/hydra-branch2-openvino-integration-00805.md).

Focused OpenVINO/detector/projection/Hydra runtime checks and shell/format
checks are recorded in that report. The earlier full CPU suite result remains
70 passed, 3 known UI script SHA mismatches; it is not a pass for the branch.

**Latest bounded live smoke checkpoint:** 30 s map-00805 smoke after CPU raycast
warm-up. Startup compiled the Numba signature in **1.270 s**; the first live
NavMap update was **79.6 ms** (96 updates, p95 121.8 ms, max 148.9 ms), versus
the prior cold first-update outlier of 2.102 s. No NavMap update exceeded the
300 ms source TTL and no `navigation_unavailable` control reason was recorded.
The run captured 192 frames and shut down cleanly, but remains
`outcome=incomplete`, exit 1, `native_runtime_validated=false`: Hydra processed
2 inputs and could not export a coherent hierarchy/map. Control reasons include
33 `expired_or_zero` outcomes, still requiring separate diagnosis. See the
[JIT warm-up smoke report](results/hydra-branch2-jitwarm-00805.md).

**Offline follow-up diagnosis (same recorded smoke; no new simulator run):** the
33 `expired_or_zero` outcomes map to consecutive depth frames 3–35. Their depth
ages were 76.5–171.1 ms, below the 300 ms freshness limit. The actuator uses
that result for either a command past its 100 ms deadline or a zero linear and
angular command. The artifact does not retain those per-invocation command
fields, so it cannot distinguish those cases exactly. Navigation separately
reports 32 `committed_goal_blocked:goal_not_traversable` decisions; their count
and interval closely match the zero-result run, making geometric zero commands
the likely majority, but not a per-frame proof. Semantic throughput is bounded
by startup and CPU service: selected keyframes were frames 0 and 76; live
capture-to-detector-return was 22.74 s for frame 0 and 1.83 s for frame 76,
while Hydra service took 5.50 s and 4.88 s. Both inputs were accepted, but the
run recorded zero live detector/object evidence commits and zero object IDs.
This confirms that the smoke did not establish useful semantic/Hydra output.
Exact evidence and limits are in the [offline smoke diagnosis](results/hydra-branch2-offline-diagnosis-00805.md).

**Detector/iGPU check and recorded-frame A/B (offline only):** after the user
installed `intel-opencl-icd` `23.43.27642.40-1ubuntu3`, `clinfo` detects one
Intel OpenCL platform and the Intel Raptor Lake-P UHD Graphics device. Local
OpenVINO `2026.4.1` enumerates `CPU` and `GPU` (`Intel(R) UHD Graphics (iGPU)`).
On nine recorded RGB-D frames, OpenVINO UHD inference at 640 px measured
207.7/250.6 ms p50/p95, versus 1,294.5/1,377.2 ms for the current PyTorch CPU
baseline (about 6.2x/5.5x faster). It matched 27/28 baseline detections by
same-label and mask-IoU>=0.5 criteria, with 10 additional candidates. This is
agreement on nine frames, not ground-truth accuracy. OpenVINO's first GPU
compile/warm-up was 7.0 s. The production detector still uses PyTorch CPU;
this offline profile/export did not change app code/configuration or run a
simulator. CPU size results remain: 640 1,309/1,514 ms; 512 900/947 ms with
39.3% matched detections; 480 811/1,081 ms with 28.6% matched. Keep 640 pending
broader quality review. See the
[UHD/runtime and recorded-frame A/B report](results/hydra-branch2-detector-resolution-ab-00805.md)
and artifact directory `.runtime/hydra_ws/artifacts/hydra-cpu-resolution-ab-00805-20261104/`.

Earlier bounded smoke failures and startup fixes remain recorded in the
[initial smoke report](results/hydra-branch2-smoke-00805.md). Longer A/B and
300 s runs remain gated on semantic result throughput and acceptance.

**Offline latency profile:** replayed 9 captured RGB-D frames with the pinned
CPU detector, without starting the simulator. Worker initialization took
22.932 s (model/encoder load 21.370 s); warm inference p50/p95 was 1.301/1.868 s
and client round trip 1.406/1.967 s. In the live trace, primary and navigation
capture intervals both had ~295 ms medians, closely matching the 294 ms control
interval median; this points to sensor/update-to-control pacing as the immediate
cadence limit. The recording lacks simulator-step, render, NavMap, and scheduler
boundary timestamps, so those sub-stages cannot yet be separated. Full profile
and artifacts: [offline latency report](results/hydra-branch2-offline-profile-00805.md).

**Stage-profile follow-up:** added bounded source-bound monotonic timing for
sensor IPC/decode and worker capture stages, simulator action/step, NavMap update,
exact-map wait, and control/actuation. One new 30 s smoke recorded 168 frames,
82 NavMap updates and 83 control loops; cleanup was clean and runtime health had
no failed workers. Stage p50s: primary sensor round trip 171.6 ms, draw/render
48.8 ms, readback 8.4 ms, packet normalize/encode 29.1 ms, host decode 23.7 ms;
NavMap update 73.5 ms and exact-map wait 73.6 ms; actuation IPC 7.1 ms and
simulator step 0.21 ms. NavMap had a 2.10 s maximum outlier. This localizes
substantial time in sensor capture/serialization and mapping, while physical
simulator stepping is negligible in this sample. Smoke outcome remains
`incomplete` (only 2 Hydra inputs accepted; coherent map/hierarchy export
unavailable), exit 1, `native_runtime_validated=false`. It is diagnostic evidence,
not runtime acceptance. See [stage-profile report](results/hydra-branch2-stage-profile-00805.md).
Focused measurement/sensor suites: **101 passed**, exit 0; Python compilation,
runner shell syntax, and `git diff --check` also exit 0. The smoke command exited
1 because it could not export a coherent hierarchy/map, despite clean worker
shutdown and no runtime error. Overall Hydra live acceptance remains open.
Offline replay of the exact `downward-depth/frame-1` reproduced a cold NavMapper
update at 1.79 s wall / 2.88 s process CPU, versus 130 ms after JIT. The raycast
uses Numba `njit(cache=False)`; runtime now explicitly compiles the exact CPU
signature during pipeline setup and reports its cost in worker metadata. The
post-change 30 s smoke removed the first-map stall and related TTL misses. The
live artifact still has no timestamped CPU/RSS series, so direct host-load
correlation remains unavailable. See the [outlier investigation](results/hydra-branch2-navmap-outlier-00805.md).

Correctness follow-up: evaluator now validates and accepts bounded source-bound
`stage` records. Full non-native CPU suite after this change: **2426 passed, 3
failed, 1 skipped, 9 deselected**, exit 1 (181.87 s). All three failures are the
pre-existing baseline/geometry-only/appearance UI script SHA mismatch
(`2e6cec…` expected, `310ae171…` actual). Six focused evaluator/deadline
regressions pass. Full run is documented in the [JIT warm-up report](results/hydra-branch2-jitwarm-00805.md).

User giao thực hiện kế hoạch Hydra ngày 2026-11-04. H0 đã tạo worktree/branch
chính xác `Kiet_branch2` tại `.runtime/worktrees/Kiet_branch2`, từ `Kiet_branch`
HEAD `62f16fcf0b1ae508b49820e0184e99714387c490`; snapshot dirty tree gồm 22
tracked edits và 69 untracked files, toàn bộ 91 source/config hashes khớp. Checkout
`Kiet_branch` giữ nguyên HEAD/index và nội dung; không commit.

**Implemented:** H0 provision branch2 venv từ 14 wheel hash-pinned, exact package/native
parity verified; H1 clone/pin/build Hydra, workspace/Python/VCS/FetchContent dependencies,
native sysroot, `hydra_python` and Spark-DSG bindings. H2 added CPU-only `HydraCalibration`
/`HydraFrame`, a provenance-bound RGB-D/body-pose adapter and native transform/depth
oracles. H3 added deterministic YOLOE-mask label rasterization, pinned custom Hydra
labelspace and labelspace provenance, with native geometry/object/room fixtures. API audit:
[Hydra Python binding audit](hydra-python-bindings.md); reports:
[H0](results/hydra-branch2-baseline.md), [H1](results/hydra-branch2-h1.md),
[H2](results/hydra-branch2-h2.md), [H3](results/hydra-branch2-h3.md). H4 added the
bounded child session, selected-input journal, native worker, and replay helper; report:
[H4](results/hydra-branch2-h4.md). No packages were installed system-wide.

**Correctness-verified:** H0 navigation/controller/MotionGuard 135 passed (exit 0) and
recorded replay/evaluator 20 passed (exit 0). H1 native build/binding probe passed (exit 0).
H2 contract/input tests plus existing contract suite: **120 passed** (exit 0). H3 label,
Hydra frame/adapter/session and existing contract tests: **135 passed** (exit 0). Native plane
probe: four accepted frames, 3,485 mesh vertices, median world-Y 2.000078 m, correct
body-camera composition and red RGB sentinel; graph reload preserved mesh. All-invalid
depth probe produced zero mesh vertices. H3 native empty-detection unknown background
produced 718 mesh vertices while the invalid patch had none; two same-class detections
produced stable `O(0)`/`O(1)` across eight frames; the 8×6 m open-space and narrow-linked
two-room fixtures produced one and two native rooms. Native graphs reloaded successfully.
H2/H3 commands and artifact hashes are in their reports.

H4 native child step/save/reload/shutdown and exact selected-prefix replay passed. Effective
TSDF and mesh integrator threads were both2 in child logs; BLAS/OpenMP caps are1. H4 test
and native artifact hashes are recorded in its report.

**Runtime-validated:** H1 binding smoke, H2/H3 native Hydra fixtures, isolated H4
native child process, and one bounded post-fix H7 coordinator smoke ran. The
smoke validates worker startup, two Hydra graph updates/export, clean shutdown,
and absence of the prior publication mismatch; it did not reach runtime
acceptance. H5 wires selector/admission into the coordinator; H6 projects native
graph summaries and exports a verified manifest. Focused H6/H5/H2–H4/UI
tests: **43 passed** (exit 0). H0 navigation/controller/MotionGuard regressions:
**135 passed** (exit 0), with all 11 H0 navigation source files hash-identical. A broader
launcher/configuration check exposed three existing shipped UI worker checksum
failures (recorded in [H5 report](results/hydra-branch2-h5.md)). No visible UI
session, mesh/cloud rendering, movement-concurrency test, or H7 A/B/live
acceptance has run. The bounded smoke did not establish those gates.
At the time of this checkpoint, the sandbox could not reach `DISPLAY=:0`.
The later follow-up verified host X11 access and opened the recorded-graph
viewer on the desktop; that snapshot viewer does not imply a live simulator UI.

H6 report: [native graph projection and export](results/hydra-branch2-h6.md). An
existing H4 native graph's size/hash was verified and its exact selected-input
manifest was emitted; H4 separately verified native Spark-DSG reload. H6's offscreen
publication, DTO, layer filter and selection tests pass. The displayed graph currently
omits native mesh/cloud rendering and no live room membership selection was observed.

H7 adds a branch/worktree-safe runner and independent fail-closed acceptance checker
([H7 report](results/hydra-branch2-h7.md)). The checker finds the actual H3 native
fixture evidence and rejects the isolated H4 artifact because it lacks coordinator
and A/B evidence. The calibrated local 00805 profile now passes preflight
(`ready=true`, `issues=[]`, `native_runtime_validated=false`); calibration and
pin evidence is in the [profile report](results/hydra-branch2-calibration-00805.md).

Final full CPU suite after repairing a worktree-relative test fixture path:
**2416 passed, 10 skipped, 3 failed**, exit 1 (186.54 s). All remaining failures
are legacy `baseline`/`geometry-only`/`appearance` UI script SHA assertions
(`2e6cec…` expected, `310ae171…` actual), not Hydra tests. The exact H0 navigation
suite passes **135/135**; combined focused Hydra/UI and room-admission suite passes
**54/54**. `git diff --check` exits 0. Full stdout was not saved separately; exact
commands and outcomes are in the H6 report.

Final H0 source-manifest audit found 89/91 protected checkout file hashes still
match; the two mismatches are `docs/implementation-status.md` and the Hydra plan,
whose protected-checkout modification times are 10:23 local, after the H0
manifest at 10:03 and before this execution's branch2 edits. Active checkout still
reports `Kiet_branch` at HEAD `62f16fcf0b1ae508b49820e0184e99714387c490`; its Git
status was not modified by this execution. All H0 navigation source hashes and
the 14-package/native-extension lock comparison match. This two-document drift
remains unresolved against the H0 snapshot.

H0 clean-install wheelhouse and H1 27-wheel Python lock are hash-pinned. Hydra default
Habitat labelspace marks `0` invalid; H3 must use the planned custom labelspace for unknown
background. Binding has no Python `stop()`; child teardown relies on C++ destructor.

**Next:** Diagnose the detector IPC timeout in isolation, recording initialize
versus first-inference elapsed time and child stderr, then repeat only the
30-second smoke. Two attempts failed before any source frame was committed, so
latency p50/p95 have no samples and longer A/B runs are premature. Details:
[00805 smoke report](results/hydra-branch2-smoke-00805.md). Profile preflight
returns `ready=true`, `issues=[]`; it does not validate runtime behavior. H5
coordinator/live concurrency validation, H6 visible UI/live integration and
mesh/cloud rendering remain open.

### Exploration/movement optimization — 2026-11-04 — in progress

User authorizes improving exploration and movement; accepted Rebuild M5 remains
the room source. Main integrates, Luna workers own scoped policy/controller tests
and an independent Terra read-only latency review checks difficult seams. No
sibling writes, installs, model downloads, commits or publication.

Implemented and component-tested: gain/heading-aware selection with8 views per
boundary and a0.6m new-goal preference (close-goal fallback, held-goal stability),
committed-goal tracking without repeated boundary extraction, origin-only rolling
velocity continuity, discrete bounded yaw/translation with0.6m/s² configured ramp,
guard issuance after geometry checks with ORIGINAL300ms TTL/100ms horizon,
expired-capture recapture without control/relabeling or raw-recording gaps, and
UI marker pre-admission source binding. A real recorded corner regression proved
that the previous14cm controller preview vetoed a MotionGuard-accepted2cm pulse;
the discrete preview now checks the actual bounded pulse. NavMap10cm is distinct
from unchanged Rebuild M3/M5 at5cm/stride1. Experimental fresh-map lag remains off:
its runtime test regressed through added bootstrap/deadline cost.

Latest whole CPU snapshot: **2362 passed /10 skipped**, exit0,169.33s, artifact
`.runtime/movement-improvement-20261103/full-suite-final.log`. Earlier whole run
had7 failures: UI observer order was a real regression and restored with an early
side-effect-free expiry check; profile-constructor fakes were replaced with real
Navigator/Guard; an asynchronous capture fixture now waits for its first commit.
All earlier logs are retained. This is correctness evidence, not P10 acceptance.

Latest native snapshot `final-corner-90-run`:90s observation,1.5275m measured
action translation,2 reached viewpoints/3 goal IDs,0 dual-axis forward commands.
Deliberately delayed one source350ms, health records one expired capture,
no worker failure/error, clean shutdown. M3 accepted/latest14, M5r11 with2 valid
regions and not stale. Outcome remains **incomplete**, not a strict acceptance
pass; resource-measurement completion remains to be reported with exact checker
output. Artifacts `.runtime/movement-improvement-20261103/` preserve all variants,
failed startup/fatal-stale run, phase logs and geometry fixtures.

Hybrid regulated pursuit is implemented behind an explicit flag,33 integrated
regressions pass, and independent Terra static safety review found no actionable
regression. Native90s translates1.826m; primary0.5Hz variant2.205m. However the
300s run translates only2.663m:400/896 pending-map results, late map service
242–269ms versus92ms early, source age reaching300–338ms. Median forward request
remains0.2m/s; short remaining evidence lifetime, not curvature, dominates the
crawl. M3 accepted/latest39, M5r34,2 fresh regions, raw1167/1167, clean shutdown,
no runtime error; outcome incomplete. Performance objective remains open.

Four-worker isolated early/late replay is42–45ms/frame; one worker is slower and
not selected. Main measured a11.94MB late UI publication:153–168ms encoding,
dominated by Python JSON streaming. Luna now owns only `ui_transport.py` and a
new byte-budget/equivalence test file to add a bounded C-encoder fast path with
unchanged streaming fallback. Main will compare that with UI1Hz and primary0.5Hz,
then run final regressions/checker/preflight and update this checkpoint. Full
evidence and negative results: [movement report](results/exploration-movement-2026-11-04.md).

### M5-only hierarchy cleanup — 2026-11-03

**Implemented:** Rebuild RGB-D M1–M5 now uses accepted M5 polygons as its only
room partition source. Hierarchy object membership and UI links retain the M5
map domain plus accepted-map/M5 revisions; stale or rejected publications do
not produce assigned links. The generated M1–M5 profile omits the legacy
`workers.region` worker. Removed RoomOwner, stable-room/portal debug projection,
its UI and hierarchy consumer, replay tool, and RoomOwner-only tests. Removed
the leftover Control map legend for Confirmed/Tentative/Disputed rooms and portal
candidates. Generic region processing remains for profiles that do not enable
`workers.room_pipeline`.

**Correctness-verified:** the new wrong-episode regression failed before the
fix, proving that a mismatched M5 publication could fall back to generic
regions; it passes with M5 fail-closed selection. Focused M5/hierarchy tests:
10 passed (exit 0) before the final legend regression; focused hierarchy/UI suite:
9 passed (exit 0). Full suite on final source: 2,298 passed, 10 skipped (exit 0,
192.95 s).
Runner `bash -n`, generated-profile assertions, and `git diff --check` passed
(exit 0). Rebuild preflight passed for each locally available calibrated profile
00800–00809: all `ready=true`, `issues=[]`; each reported
`native_runtime_validated=false`.

**Not established by this cleanup:** runtime validation for arbitrary maps. Each
map still requires its own calibrated profile, Habitat scene/navmesh and matching
Rebuild source/native binary pins; preflight alone is not a runtime result.

### Local motion throughput experiment 00805 — 2026-11-03

Đã giữ nguyên stride 2 và mọi giới hạn an toàn, chỉ giảm `runtime.primary_hz`
từ 5 xuống 1 trong profile tạm dưới `.runtime/`. Mục đích là dành thêm vòng
owner thread cho sensor navigation: run nền 180 giây trước đó chỉ đạt khoảng
1.9 lần lặp/giây nên primary RGB-D đến ở mọi vòng.

**Implemented:** profile thí nghiệm riêng và tùy chọn cấu hình
`navigation.controller.nominal_speed_mps`; default vẫn 0.15 m/s. Local preflight
`ready=true`, `issues=[]` (exit 0). Sau khi đo được command forward tối đa
0.108 m/s ở cấu hình cũ, validator được giới hạn mức danh định tối đa 0.20 m/s.
Không đổi hard cap 0.2 m/s, depth TTL 300 ms, lệnh 100 ms, checker, M3/M5 source
hay validator.

**Runtime-validated:** smoke 60 giây lấy 52 primary và 174 navigation pose;
98 lệnh chạy, quãng đường dịch chuyển quan sát được tối thiểu 0.1574 m. Run
offscreen 180 giây lấy 153 primary/429 navigation frames, chạy 81 lệnh, translation
lower bound 0.1211 m; M3 accepted/latest r69, M5 r63 fresh với một polygon hợp lệ.
Rebuild xử lý 69/153 primary candidates. Chi tiết tại [báo cáo motion
throughput](results/local-room-motion-00805-2026-11-03.md).

**Correctness-verified:** strict acceptance checker từ chối run 180 giây chỉ vì
outcome `incomplete`; recording đủ 582/582 frame, UI offscreen đóng sạch, M3/M5
không stale. Resource measurement support chỉ 552/587 RSS samples, còn 32 mẫu
truncated; đây là blocker để checker chấp nhận. Run 300 giây nominal 0.20 m/s:
checker vẫn từ chối chỉ vì `incomplete`; recording đủ 1,003/1,003, M3
accepted/latest r143, M5 r136 fresh với hai polygon hợp lệ. RSS support
1,003/1,028, còn 21 mẫu truncated. Smoke 60 giây có lỗi UI vì môi trường chạy
không nối được `DISPLAY=:0`.

**Chưa chứng minh:** 319/427 control invocation của run 180 giây vẫn gặp
`navigation_source_pending`; 17 lần depth stale. Chưa có run đạt strict
acceptance, chưa xác minh đi qua ranh giới phòng, và offscreen không tạo cửa sổ
live để xem trực tiếp. Ở run 300 giây nominal 0.20, dịch chuyển lower bound
tăng từ 0.196 m lên 0.266 m so với nominal 0.15 trong cùng thời lượng, nhưng
max command chỉ tăng 0.108→0.117 m/s và `navigation_source_pending` vẫn là
441/744 lượt. Đã thử thêm NavMapper `sampling_stride=2` trong profile
tách riêng, nhưng 381/381 quyết định có depth phù hợp bị chặn tại
`robot_not_on_observed_free_cell`; không có lệnh chuyển động, M3 chưa accept và
M5 stale. Không dùng biến thể này. Primary 1 Hz chưa được nâng thành default.
Không chạy Kaggle.

### So sánh stride 1/2 trên cùng recording 00805 có quay — 2026-11-03

Tìm thấy recording local 00805 hoàn chỉnh 218/218 sensor frames, gồm 108 primary
RGB-D frame. Camera đi 0.0663 m và quét tổng khoảng 101.2°; có quay nhưng hầu
như không tịnh tiến, nên đây chưa phải room traversal. Đã replay đủ cùng 108
frame ở stride 1 và 2 bằng source/binary pins hiện tại; mỗi nhánh đóng session
sạch, M3/M5 có 108 update và một vùng fresh.

**Correctness-verified:** stride 2 so với stride 1: M3 known-cell recall
0.9987, occupied recall 0.8938, occupied precision 0.9862, occupied IoU
0.8827, free recall 0.9992. M5 có một vùng fresh ở mỗi nhánh; polygon IoU
0.9576, diện tích 8.255 so với 8.074 m². Offline comparator không gọi strict
acceptance. Một live stride-2 bounded run riêng đã pass strict checker (ghi ở
bên dưới).

**Runtime-validated:** replay stride 1 mất 824.53 s; stride 2 mất 241.65 s,
tăng tốc 3.41×. M2 median giảm từ 4.217 s còn 1.093 s mỗi update. Artifact
JSON và ảnh M3 A/B ở
`.runtime/local-room-fps-experiment-00805-20261103/stride-comparison-turning-108frames/`.

**Chưa chứng minh:** quãng đường 6.6 cm không kiểm tra khả năng giữ tường/cửa
khi đi qua ranh giới phòng. Stride 2 vẫn giữ trạng thái thử nghiệm, không đổi
default; Kaggle chưa chạy lại.

### Bounded live demo Rebuild stride 2 trên map 00805 — 2026-11-03

Đã tạo config tạm stride 2 trong `.runtime/`; stride mặc định production vẫn là
1. Preflight local `ready=true`, `issues=[]` (exit 0). Run 60 giây với Qt
offscreen hoàn tất sạch; raw recording đủ 186/186 frame, trong đó 92 primary
RGB-D frame. Room pipeline xử lý 22/92 candidates; median room service 2.749 s.
M3 accepted/latest revision 22, M5 revision 11, không stale/replay-required,
có 1 polygon hợp lệ. Strict acceptance accepted=true (exit 0). Snapshot:
`.runtime/local-room-fps-experiment-00805-20261103/stride2-live-demo-60s/stride2-accepted-snapshot.png`.

**Giới hạn:** pose chỉ đi 0.0066 m, nên run này không kiểm tra giữ ranh giới khi
đi qua phòng/hành lang. Lượt đầu không offscreen bị strict checker từ chối vì
môi trường không có X display; lượt offscreen thứ hai được checker chấp nhận.
Đây là runtime validation cho stride 2 và M5 trên cảnh gần tĩnh, không chứng minh
chất lượng trajectory hoặc khuyến nghị bật stride 2 mặc định.

### Thí nghiệm admission Rebuild FPS-cap trên local — 2026-11-03

Không chạy Kaggle trong lượt này. Đã thêm chính sách thử nghiệm opt-in
`fps_cap_hz` + `latest_wins`; profile FIFO mặc định không đổi. Khi FPS cap cho
phép frame mới, room queue chỉ giữ tối đa một frame chờ; các frame bị cap hoặc
bị thay đều có lý do journal riêng. Runtime đo queue wait, room service và source
age. Journal Rebuild giữ per-update stage timing/point counts. Adapter nay giữ
trạng thái M3 “đã có tích hợp” riêng với danh sách record bị pop, tránh chọn
`full_refresh` lặp lại.

**Correctness-verified:** 50 test focused pass (exit 0), local preflight
`ready=true`/`issues=[]` (exit 0), và `git diff --check` (exit 0). Chuỗi M3 trong
replay được xác nhận `full_refresh` lần đầu, `partial_update` các lần sau.

**Runtime-validated:** local bounded run 00805 ở 0.25 Hz, 30 giây, đủ 132/132
sensor frame; 65 room candidates, 57 FPS-limited, 8 offers, 3 pending frames
được thay, 5 processed, 0 queue rejection. M3 accepted/latest=5, M5 revision 3
có một polygon hợp lệ, không stale; acceptance checker accepted=true (exit 0).
Đối chứng cùng raw recording: chọn 8/65 frame, known-cell recall 0.9992,
occupied recall 0.9660, occupied IoU 0.8987; một polygon ở cả hai map, IoU
0.9165. Đây mới là run gần như đứng yên (path 0.0478 m), không chứng minh
coverage khi đi qua phòng/hành lang.

Timing full replay p50: M1 37 ms, M2 2.825 s, M3 78 ms, residual ngoài timer
M1/M2/M3 là 2.101 s; M4+M5 khoảng 7.1 ms. M2 timer bao gồm Python validate,
ASCII serialize và IPC qua `OctoMapWorker.integrate`, không chỉ OctoMap native;
residual chứa `ScanPoint` construction cùng bookkeeping, chưa được cô lập bằng
profiler. Chi tiết metrics/artifacts và giới hạn ở [local FPS-cap
report](results/local-room-fps-cap-00805-2026-11-03.md).

### M2 profile và stride comparison local — 2026-11-03

**Implemented:** thêm công cụ profiler diagnostic cho worker (phase wall timers
và tùy chọn cProfile) và tool replay full sequence với stride 1/2/4. Không sửa
source Rebuild, không đổi stride mặc định, acceptance hoặc Kaggle bundle.

**Correctness-verified:** Python compile/CLI help và `git diff --check` đạt.

**Runtime-validated:** phase timing trên 3 primary frames cho integrate wrapper
8.523 s tổng: pipe write 4.129 s, response read 1.306 s, point validation
0.033 s và format/other wrapper remainder 3.056 s. cProfile đếm khoảng 916k
`ScanPoint` generation/constructor calls qua ba frame; profiling wall time bị
phóng đại, chỉ dùng call counts để xác định hotspot. Full replay 65 frame:
stride 1 mất 369.08 s; stride 2 mất 109.76 s (3.36×) và giữ M3 occupied recall
0.8912, occupied IoU 0.8851, M5 polygon IoU 0.9659; stride 4 mất 39.79 s
(9.27×) nhưng occupied recall giảm còn 0.7415 / IoU 0.7267. M5 có một vùng
fresh ở cả ba variant. Báo cáo và artifacts tại [M2/stride report](results/local-room-m2-stride-00805-2026-11-03.md).

**Chưa chứng minh:** trajectory vẫn chỉ đi 0.0478 m; chưa có bằng chứng về
ranh giới phòng khi đi qua scene, run dài hoặc map khác. Stride 1 vẫn là mặc
định production; stride 2 chỉ là ứng viên để thử tiếp trên trajectory có
translation/turning và nhiều room boundaries. Acceptance không nới.

### Kaggle room-queue throughput evidence for map 00805 — 2026-11-03

Recorded user-provided output for bounded run
`20261103T103038Z-53d2b0a0-180s`: 335 Rebuild room offers, 26 enqueued/admitted/
processed, 309 queue drops (92.24%). This is the **00805 room lane**, not a
92% loss of all sensor data: the separate raw recording certificate reports
672/672 frames durable with no source gaps. M3 accepted/latest revision 26 and
M5 revision 22 were non-stale at shutdown. The strict acceptance output and
coverage evidence for this exact run were not included, so M5 acceptance and
scene coverage remain unproven. The detailed evidence and source semantics are
recorded in `docs/results/kaggle-room-queue-throughput-00805-2026-11-03.md`.

### Kaggle bundle v4: import được, nhưng smoke bị chặn bởi DNS — 2026-11-03

Đã mở draft `NeuSymNav Full M1-M5 Smoke 00805`, gắn dataset private
`rebuild-rgbd-00805-full` (Version 4), xác nhận GPU `T4 x2` đang được chọn và
Internet đang bật. Draft đã lưu đúng notebook chứa pin cho source tree
`9eab6fd4...`, detector diagnostic `6ec70d2c...` và GPU lock `e70fbd22...`.

**Implemented:** không có thay đổi source/runtime trong lượt này. Dataset gắn vào
draft và cấu hình GPU/Internet đã được xác nhận bằng UI. **Correctness-verified:**
draft hiện đúng tên notebook và input dataset; không có preflight nào được chạy.
**Runtime-validated:** hai lần Run All đều dừng ở cell bootstrap trước khi cài
micromamba, tạo Habitat/Python environments, preflight hoặc chạy RGB-D. Cả hai
lần báo `socket.gaierror: [Errno -3] Temporary failure in name resolution` khi
đọc `https://micro.mamba.pm/api/micromamba/linux-64/latest` (URLError); lần hai
cũng lỗi DNS. Không có bằng chứng hạ tầng GPU/room pipeline đã chạy. Draft
session đã được stop sau lỗi để nhả GPU.

Kết luận: đây là lỗi phân giải tên miền/egress từ kernel Kaggle dù UI báo
Internet bật; không phải lỗi map/profile hoặc acceptance. Chưa sửa local bundle
và không đổi timeout, queue hay checker. Cần thử lại khi Kaggle kernel phân giải
được `micro.mamba.pm` và các host conda/pip; sau đó Run All từ đầu, xác nhận
preflight `ready=true`, rồi mới đánh giá kết quả M5. Artifact hiện có là traceback
trong output của draft Kaggle trên; không có result archive mới. Lệnh kiểm chứng
cục bộ chưa chạy vì không có thay đổi file hoặc code trong lượt này.

### Kaggle bundle v3 đã publish nội bộ; smoke mới đang chờ editor — 2026-11-03

Lần kiểm tra notebook trước smoke phát hiện cell exporter gán lại `run_dir`
thành một đường dẫn 180 giây cố định từ lượt cũ. Điều đó có thể làm phần
export/acceptance đọc nhầm run cũ sau khi run mới hoàn tất. Đã bỏ gán đường dẫn
cố định; exporter, log và archive nay nằm dưới thư mục `run_root` của lượt hiện
tại. Notebook chỉ nhận bundle đúng pin source/helper/GPU lock và tìm bundle ZIP
qua manifest, không phụ thuộc tên ZIP cũ.

**Implemented:** sửa đường dẫn run-scoped trong notebook, xác thực helper và
GPU lock khi resolve ZIP hoặc bundle đã bung, thêm hướng dẫn chạy lặp lại và
cổng nghiêm ngặt trước khi chạy lâu; thêm `validate_bundle.py` để kiểm integrity
ZIP, đường dẫn member, bundle/map/GPU identity và SHA của notebook/helper/GPU
lock trước khi upload.
**Correctness-verified:** 6 kiểm tra `test_detector_diagnostic` đạt; notebook
JSON hợp lệ, 6 code cell parse AST, `git diff --check` đạt. Bundle
`.runtime/kaggle/rebuild-rgbd-00805-full-gpu-stable-v3.zip` có kích thước
346,429,803 bytes; `workflow_notebook_sha256=3418d590c829a361b5cd562683f268c91bc6ccf83750045d840bd65c928a01a3`, helper SHA
`6ec70d2c2235dcd2169c574d24c1baa104c1aeb7582c5ad209649e03c2e9216a`, GPU lock
SHA `e70fbd2261057cd183908f2ce0c1997980342ab776ade8f792289cbfe3280eb6`. Kaggle
xác nhận tạo **Dataset Version 4 (Private)** thành công. Verifier có 4 test
pass; kiểm tra cả ZIP và thư mục bundle v3 trả `OK`, exit 0; `git diff --check`
đạt.
**Runtime-validated:** chưa chạy notebook đã sửa. Notebook editor vẫn hiển thị
`Editor Loading`, các cell và `Run All` bị disable; log Chrome ghi Cloud
Firestore backend `unavailable` nhiều lần ở cả tab ban đầu và tab editor mới.
Vì vậy chưa import/đồng bộ notebook SHA mới vào Kaggle draft, chưa chạy
preflight/smoke mới và chưa có kết quả M5 mới. Không kết luận workflow hoặc run
dài đã ổn định.

Bundle/profile hiện vẫn giới hạn 600 giây, còn smoke Kaggle trước đó bị
incomplete/reject. Chỉ chuyển sang run dài sau khi notebook đúng SHA chạy được
bounded smoke và acceptance nghiêm ngặt pass; chưa có bằng chứng pipeline duyệt
hết scene trong một session Kaggle.

### Kaggle full M1–M5 smoke sau sửa Habitat depth — 2026-11-03

Đã tách `LD_LIBRARY_PATH` native Rebuild khỏi tiến trình Habitat sensor bằng
thay đổi ở `HabitatPoseSource`; đây là cách biệt lập thư viện Mesa/EGL sau khi
bundle native làm primary depth trả toàn số 0. Test hồi quy xác nhận sensor
worker không nhận override đó. Bundle GPU mới đã được upload thành Kaggle
Dataset Version 3 (Private), notebook đọc đúng source SHA
`9eab6fd4bc96150edd5e2d0e4f4b32ecafd78b0b87715f590bba51b69f1110a7`.

**Implemented:** cô lập môi trường thư viện sensor; notebook full GPU sử dụng
bundle đúng pin. **Correctness-verified:** test client sensor và preflight local
đạt. **Runtime-validated:** Kaggle preflight `ready=true`, `issues=[]`, exit 0;
T4 CUDA runtime và Triton hiện diện. Run cấu hình 180 giây dừng sớm sau 72.43
giây wall với `admission_stop=runtime_health_failed`; raw recording hoàn chỉnh
144/144 frame. M3/M5 có
`accepted_m3=latest_m3=5`, `m5=2`, không stale và có 1 polygon hợp lệ. Tuy
nhiên CLI exit 1 / `outcome=failed`, runtime shutdown không sạch, graph recorder
`offered=1 / durable=1 / missing=2`, measurement và resource cleanup chưa
complete; hierarchy export không có. Acceptance **reject** với các lý do run
không completed, runtime shutdown không sạch, room pipeline failed/replay cần
thiết và revision/clock mismatch trong bundle export. Không nới checker.

Detector recipe ghi `device=cuda:0`, runtime Torch `2.7.1+cu126`; tuy nhiên
request detector đầu tiên chưa hoàn tất nên chưa có bằng chứng một inference
thành công trên GPU. Raycast đã chạy thực trên T4: 71 request, worker `ready`,
timing gần nhất 14.89 ms end-to-end. Graph scheduler `offered=accepted=1`,
`processed=0`, lỗi `worker whole-operation deadline exceeded`; cấu hình detector
của attempt là deadline 5.0 giây. `run.stderr.log` trong artifact là 0 byte,
nên substage chậm trong phép infer (serialize/write, detector inference hay
response/decode) chưa được xác định. Đọc mã xác nhận deadline 5 giây bắt đầu
sau khi worker initialize xong; nó bao trùm serialize/write request, inference
trong worker, serialize/write response, JSON decode, contract validation. Vì
timeout chỉ báo `whole-operation`, artifact hiện tại không phân biệt các phần
này. Đã thử chạy một cell đo riêng sau khi khởi động Kaggle Draft Session mới,
nhưng `/kaggle/working` của phiên trước không còn chứa `attempts/*-startup.json`
hoặc frame. Cell thăm dò đó đã được xóa và GPU session đã dừng; chưa đo được
substage trên T4. Đọc frame keyframe đã tải về trên máy local:
JSON 3,277,984 bytes, `from_dict` 16.8 ms và serialize request 24.8 ms median
trong 5 lượt. Đây chỉ là host CPU measurement; không chứng minh stage nào chậm
trên Kaggle/T4.

Room queue nhận 70 frame, xử lý 5, drop 65 (92.9%). Snapshot timing cuối: M2
2,335.9 ms; M1–M3 tổng 3,862.6 ms; M4/M5 khoảng 12.8 ms. Đây là một snapshot,
không phải benchmark phân bố. Kết quả M5 polygon hợp lệ chưa đủ để chấp nhận
run. Artifact đầy đủ được tải về ở
`/home/kiettran05/Downloads/rebuild-rgbd-00805-m1-m5-results-180s/`; Kaggle
session đã dừng sau khi xuất kết quả.

Kiểm chứng: `.venv/bin/python -m pytest tests/test_sensor_adapter.py
tests/test_sensor_deadline.py tests/test_sensor_execution_metadata.py
tests/test_rebuild_rgbd_input.py tests/test_rebuild_room_session.py -q` → 49
passed, exit 0. Bundle local preflight `ready=true`,
`issues=[]`, exit 0. Kaggle preflight exit 0; Kaggle run exit 1; exporter tạo
JSON, ảnh M3/M5 và archive nhưng acceptance false. Bước kế tiếp là đo riêng
serialize/write, inference CUDA, response/decode trên cùng input frame. Cần
đưa frame và startup recipe vào Kaggle input bền vững hoặc thêm telemetry stage
vào worker rồi chạy lại smoke có pin mới; sau đó mới quyết định thay đổi code
hay profile. Không tăng timeout, queue cap hoặc nới acceptance trước khi có
bằng chứng.

### Tích hợp GPU vào Kaggle bundle 00805 — 2026-11-03

Kaggle notebook nay dùng lock `requirements-host-kaggle-gpu.txt` (PyTorch
2.7.1+cu126/TorchVision 0.22.1+cu126), kiểm tra CUDA và Triton có thiết bị
thật, đặt YOLOE detector trên `cuda:0`, đồng thời thêm worker Triton CUDA cho
NavMapper. `configure_runtime.py` vẫn giữ mặc định CPU; notebook GPU phải chọn
CUDA rõ ràng và dừng nếu thiếu GPU/backend. Lock CPU hiện có không đổi. Habitat
renderer vẫn dùng llvmpipe; Rebuild native M1–M5 room mapping vẫn chạy CPU.
GPU raycast chỉ tăng tốc NavMapper/control occupancy, không phải M3/M5 Rebuild.
Acceptance checker và ngưỡng không đổi.

**Implemented:** notebook, lock CUDA, runtime profile và worker cấu hình GPU.
**Correctness-verified:** test `test_configure_runtime.py` xác nhận chọn CUDA,
raycast worker path và giữ nguyên pin assets; notebook cells compile được.
**Runtime-validated:** chưa chạy bundle mới trên Kaggle. Các số đo T4 trước đó
chứng minh riêng detector/raycast backend, chưa chứng minh integration này trong
full live pipeline hoặc M1–M5 acceptance.

Kiểm chứng task này: `.venv/bin/python -m unittest
kaggle.rebuild_rgbd_00805.test_configure_runtime -v` → exit 0 (1 test);
JSON notebook/6 Python cells compile → exit 0; runtime configurator từ bundle
mới tạo profile CUDA thành công và giữ nguyên SHA M2/M3, M4. Bundle mới
`.runtime/kaggle/rebuild-rgbd-00805-full-gpu.zip` (~331 MiB) đã build, có GPU
lock và manifest pin. Chưa xác minh CUDA wheel installation, GPU raycast
startup hoặc acceptance trên Kaggle; cần thay dataset cũ bằng bundle mới rồi
chạy preflight/smoke. Acceptance gate không đổi.

### Kaggle GPU stage matrix và thiết kế runner nhiều map — 2026-11-03

Đo ngắn trên Kaggle GPU (2×T4 nhìn thấy, chỉ chạy tuần tự trên GPU 0). YOLOE
adapter trên frame RGB Habitat 00805: warm median CPU 0.522 s / CUDA 0.0716 s,
7.28×; device đặt `cuda:0`, detection count/label khớp nhưng mask area khác
75,935 so với 75,299 pixel. Chưa đo mask IoU. Môi trường đo là Torch
2.11.0+cu130 của kernel Kaggle, khác pin bundle `torch==2.7.1+cpu`; chưa chứng
minh bundle runtime hiện tại tự chạy detector trên GPU. Habitat-Sim 0.3.3 trả
renderer Mesa llvmpipe; hai T4 không được sử dụng ở lượt capture. Production
`GpuRaycastClient`/Triton chạy Tesla T4: 4,096 tia, CPU Python median 0.2889 s,
GPU end-to-end 0.01356 s (21.3×), năm occupancy masks khớp chính xác. Đây là
raycast NavMapper, không phải tăng tốc Rebuild room M1–M5.

Ma trận và giới hạn: `kaggle/rebuild_rgbd_multimap/GPU_STAGE_MATRIX_00805.md`.
Thiết kế profile riêng từng map, preflight scene/navmesh/calibration/floor/pins,
và smoke gate trước campaign: `kaggle/rebuild_rgbd_multimap/RUNNER_DESIGN.md`.
Runner nhiều map chưa được implement; chưa có profiles map khác trong bundle.

**Implemented:** phép đo ngắn đã chạy; ma trận và thiết kế lưu trong folder
Kaggle riêng. Tích hợp Kaggle GPU runtime được ghi ở checkpoint mới phía trên.
**Correctness-verified:** raycast masks CPU/GPU
chính xác trên bộ tia đo; YOLOE cho cùng detection class/label và score gần
nhau nhưng segmentation mask chưa chứng minh tương đương. **Runtime-validated:**
detector và Triton chạy CUDA T4; Habitat RGB-D chạy llvmpipe. Full M1–M5 smoke
vẫn `incomplete`, acceptance reject và 0 M5 region; không bắt đầu campaign.

Kiểm chứng: Kaggle Habitat probe exit 0; detector benchmark exit 0; raycast
benchmark exit 0. JSON lưu trong Kaggle working ở
`gpu-stage-matrix/{detector-00805,raycast-00805}.json` và
`gpu-stage-matrix/habitat-00805/habitat_probe.json`. Archive JSON gộp đã tạo
thành công (`gpu-stage-matrix/gpu-stage-matrix-00805-json-evidence.zip`, 4,779
bytes) và link nằm ở cell cuối notebook draft. Chưa tải archive về local hoặc
lưu Kaggle Version. `git diff --check` exit 0; test suite không chạy.

### Kaggle full M1–M5 smoke cho map 00805 — 2026-11-03

Bundle riêng được chuẩn bị ở `kaggle/rebuild_rgbd_00805/`; ZIP local ở
`.runtime/kaggle/rebuild-rgbd-00805-full.zip` (331 MiB). Kaggle draft đã nhập
notebook, gắn dataset private, tạo Python 3.12 host và Python 3.9 với
Habitat-Sim 0.3.3. Không sửa runtime `src/`.

**Implemented:** notebook hỗ trợ input đã bung thành thư mục; sửa CLIP vocab
Kaggle tự đổi từ `.txt.gz` thành `.txt` bằng cách dựng bản gzip trong working;
cài CLIP vào host env để interpreter probe cô lập `-I` tìm thấy module; chép
native workers sang writable working và đặt executable bit lại vì dataset không
giữ Unix mode; giới hạn smoke Kaggle rõ ràng ở `raw_cap=2 GiB`,
`total_cap=3 GiB`, `archive_cap=256 MiB`. Notebook xuất M3/M5, hierarchy, timing,
acceptance report và archive có link tải trong output.

**Correctness-verified:** preflight trên Kaggle `ready=true`, `issues=[]`, exit 0;
M23/M4/source SHA đúng pin và `ldd` không thiếu thư viện. Notebook JSON và code
cell parse hợp lệ tại local. CLIP host import và Habitat-Sim 0.3.3 import pass.

**Runtime-validated trên Kaggle:** smoke cấu hình 60 giây kết thúc sau 103.29 giây
wall time, 118 frame, recording complete và shutdown sạch. CLI exit 1,
`outcome=incomplete`; room worker xử lý 9/58 frame gửi, 49 frame bị queue đầy.
Snapshot cuối M3 revision 9 nhưng không có accepted M3 pair; M5 stale/không có
revision và có 0 vùng hợp lệ. Acceptance **reject** vì run incomplete, M3 không
được accept, M5 không ghép M3 mới nhất, stale và không có region. Hierarchy
export có 4 node / 2 edge. Một snapshot timing: M2 2307 ms, M1/M2/M3 tổng
4112 ms; đây là một mẫu, không phải benchmark ổn định. Kaggle render là Mesa
llvmpipe, CUDA không có.

Kết quả và ảnh PNG/JSON/log nằm trong Kaggle working output; archive
`rebuild-rgbd-00805-m1-m5-results.zip` được tạo và notebook có link tải trực tiếp.
Dataset chưa được cập nhật bằng notebook sửa local; Kaggle draft đang có bản sửa
và kết quả. Smoke không được coi là M5 thành công. Nguyên nhân bước kế tiếp cần
điều tra là throughput queue (58 offered / 9 processed) và thời điểm M3 snapshot
được accept; không tăng acceptance leniency.

Kiểm chứng: Kaggle preflight exit 0; CLI smoke exit 1 nhưng tạo summary/recording;
exporter exit 0 tạo `review.json`, PNG map/hierarchy và acceptance false; archive
được tạo trong `/kaggle/working`. Chưa lưu Kaggle notebook version hay tải archive
về workspace local.

### Kaggle 180 giây: queue throughput và incomplete gate — 2026-11-03

Lượt live mới chạy 180 giây, wall time 242.57 giây, 346 frame; preflight exit 0,
raw recording hoàn chỉnh, graph recorder `offered=1 / durable=1 / missing=0`,
shutdown sạch và không có cap breach. CLI vẫn trả exit 1 / `incomplete`: artifact
measurement có `completion.complete=false` vì resource sampler không đạt đủ
support. RSS chỉ có 438/560 sample hợp lệ (122 sample trễ/truncated, 2 lỗi đọc;
max gap 2.138 giây); GPU provider không khả dụng và không có sample. Đây là gate
resource evidence trong measurement exporter, không phải room queue hay M5.

Room queue nhận 172 frame, xử lý 23, drop 149 vì queue đầy (86.6%); payload 9.03
MB/frame, byte cap giữ 32 MiB và tối đa 2 pending. Throughput quan sát là 0.095
frame xử lý/giây wall. Timing cuối: M2 2,990.7 ms, M1–M3 tổng 5,166.4 ms; M4/M5
1.84 ms. Đây là snapshot cuối, chưa phải phân bố benchmark. M2 là phần chiếm thời
gian lớn trong snapshot, còn bounded queue làm các frame đến lúc worker bận bị
drop theo đúng policy.

M3 cuối revision 23 nhưng accepted M3 không có; M5 revision null, stale và 0
region hợp lệ. Acceptance checker exit 1/reject với đủ năm lý do: run incomplete,
thiếu accepted M3, M5 không pair latest M3, M5 stale/unavailable, không có region.
Không nới checker. Result JSON/archive 180 giây được tạo trong Kaggle working;
chưa lưu Kaggle version hoặc tải archive về local. Runtime source không đổi.

### Kaggle Habitat probe cho map 00805 — 2026-11-03

Đã tạo bộ thử riêng dưới `kaggle/rebuild_rgbd_00805/` mà không sửa runtime
`src/`. `prepare_input.py` tạo input bundle riêng 35 MiB và ZIP upload 30 MiB
trong `.runtime/kaggle/rebuild-rgbd-00805-input-final.zip`; gồm profile/calibration
đã lược đường dẫn máy, scene + navmesh 00805, Habitat worker, Rebuild source
closure và hai binary đúng SHA. Bộ này chỉ kiểm tra Habitat, chưa đóng gói full
NeuSymNav M1–M5, detector environment/models hay UI runtime.

Habitat probe chạy thành công trên máy hiện tại bằng Habitat-Sim 0.3.3/Python
3.9: renderer llvmpipe OpenGL 4.5; primary 480x640 RGB-D có 307,200 pixel depth
hợp lệ, downward depth 180x240 có 43,200 pixel hợp lệ; elapsed 11.98 s, exit 0.
Artifact: `.runtime/kaggle/local-habitat-smoke-00805/`. Habitat phát cảnh báo
semantic descriptor vắng mặt; probe chỉ dùng RGB-D hình học, không nạp semantic
GT. Project runner preflight cục bộ vẫn trả `ready=true`, `issues=[]`, exit 0.

Notebook Kaggle đã được nhập vào tài khoản, gắn dataset private và chạy thành
công sau khi bật Internet cho phiên cài dependency. Kaggle base là Python 3.13;
notebook tạo môi trường Python 3.9, cài Habitat-Sim 0.3.3 headless (85 gói,
370 MB tải xuống) và xác nhận `Habitat import: 0.3.3 False`.

**Runtime-validated trên Kaggle cho Habitat RGB-D map 00805:** các hash scene,
navmesh, scene config, Rebuild binaries và source closure 50 file khớp manifest;
capture hoàn tất trong 17.25 s. Primary RGB `[480,640,3]`, depth `[480,640]`
có 307,200 pixel hợp lệ (0.433–0.619 m); downward depth `[180,240]` có 43,200
pixel hợp lệ (0.262–2.129 m). Report và ảnh RGB/depth còn trong Kaggle notebook
draft. Renderer là Mesa llvmpipe / OpenGL 4.5; không có CUDA GPU. Cảnh basis
thiếu semantic descriptor nên Habitat cảnh báo; probe không dùng semantic GT.
Internet đã tắt lại và session đã dừng sau run.

Ảnh `depth.png` ban đầu gần như đen do preview scale cố định 0.1–10 m, trong khi
primary frame chỉ có range khoảng 0.433–0.619 m; report xác nhận 307,200/307,200
pixel hợp lệ. Đã sửa helper trong bundle Kaggle: preview stretch depth hợp lệ theo
percentile 2–98 từng frame, invalid vẫn đen; JSON ghi range và phương pháp scale.
Đây chỉ là biến đổi hiển thị, không đổi depth đo được. Kiểm chứng: fixture depth
hẹp xác nhận stretch 0–255 và invalid=đen → exit 0; `/home/kiettran05/miniconda3/envs/habitat/bin/python`
chạy lại helper trên scene 00805 → exit 0, 307,200/307,200 depth pixel hợp lệ,
range preview 0.4455–0.6141 m; ảnh nhìn rõ gradient thay vì gần đen. Artifact:
`.runtime/kaggle/local-habitat-smoke-00805-depth-preview-v2/`. `py_compile`, kiểm
JSON notebook và `git diff --check` đều exit 0; không chạy test suite. Input
dataset đã upload và ảnh trong notebook draft Kaggle vẫn là bản cũ cho đến khi
bundle mới được upload.

**Phạm vi chưa chứng minh:** chưa chạy NeuSymNav full M1–M5 trên Kaggle, chưa
runtime-validate graph exporter ở Kaggle, và chưa kiểm tra map khác. Local
runner preflight vẫn `ready=true`, `issues=[]`; local Habitat probe cũng pass.
Notebook/run: `https://www.kaggle.com/code/kittrnmuhaha/neusymnav-habitat-rgb-d-probe-00805/edit`;
dataset private: `https://www.kaggle.com/datasets/kittrnmuhaha/neusymnav-rebuild-rgb-d-habitat-probe-00805`.

### Dọn run artifacts và đánh giá Kaggle — 2026-11-02

Đợt dọn đầu đã xóa 20 thư mục run thất bại/chưa hoàn tất, không được tài liệu
tham chiếu: giải phóng 18.27 GiB. Sau đó người dùng yêu cầu xóa toàn bộ nội dung
`runs/`; đã dọn thêm 66 entries, giải phóng 34.64 GiB. `runs/` hiện rỗng. Các
recording, summaries và kết quả runtime đã bị xóa; để có lại cần chạy demo mới.
Không sửa/xóa mã nguồn:
hai runner trông tương tự nhưng một chạy M4/M5 trên occupancy map sẵn có, runner
còn lại chạy RGB-D M1–M5, nên chưa có bằng chứng chúng là code thừa.

Kaggle phù hợp để benchmark headless có checkpoint, nhưng chưa phải cách tăng tốc
đã được chứng minh cho graph rebuild: theo tài liệu Kaggle hiện hành, notebook
có giới hạn 12 giờ, ổ autosaved 20 GB, và máy GPU vẫn cấp 4 CPU cores. M1–M5
đang dùng Rebuild native mapping/decomposition trên CPU; GPU Kaggle không tự
tăng tốc các stage này. Cần đo riêng thời gian M1–M5 và kiểm tra khả năng build
native workers, simulator/scene assets, cùng cách xem UI từ notebook trước khi
chuyển run. Nguồn tài liệu: https://www.kaggle.com/docs/notebooks.

Kiểm chứng cleanup: preflight xác nhận cả 20 đường dẫn đều ignored, không tracked
và không được docs/tools/src/tests/.runtime tham chiếu; `du -sh runs` 54 GiB →
35 GiB; `git diff --check` exit 0. Tests không chạy; chưa benchmark Kaggle hoặc
profile stage latency. Mã nguồn: chưa có file nào được xác nhận là dead code.

### CI follow-up sau commit 8d7409d — 2026-11-02

Đã sửa failure trong CI: fixtures `Pipeline.__new__` thiếu `_room_publication`;
config/session tests dùng đường dẫn tuyệt đối của máy dev thay vì Rebuild fixture
trong `tmp_path`; splitter test không chừa vùng di chuyển vượt minimum pane;
source-only fixture dùng shutdown budget mặc định quá ngắn; worker timeout test
dùng 50 ms nên có thể timeout ngay startup; virtual-clock test poll dồn dập và
starve graph worker. Các thay đổi là test/fixture, không nới runtime acceptance.

Kiểm chứng đúng workflow: `pytest tests -q -m 'not native' --tb=short` →
2310 passed, 1 skipped, 9 deselected, exit 0; `tools/check_github_payload.py`
→ ready/exit 0; `neusymnav --help` và launcher fixture preflight → exit 0.
Các sửa test được commit `1347ff2` và push lên `Kiet_branch`; commit chỉ chứa 7
file test/fixture. Không gồm docs hoặc run artifacts.

### Rebuild RGB-D runner cho map bất kỳ — 2026-11-02

Đối chiếu R6 trong `docs/rebuild-full-room-pipeline-plan.md`: runner không còn
chặn map ngoài `0080x`. `tools/run_rebuild_rgbd_map_demo.sh MAP` nhận mã map an
toàn bất kỳ và `--config PATH` nhận profile calibrated ở vị trí tùy chọn; root
checkout Rebuild có thể đặt qua `NEUSYMNAV_REBUILD_ROOT`. Profile phát sinh vẫn
pin M2/M3 executable, M4 executable và Python source closure cố định.

Xác minh: `bash -n tools/run_rebuild_rgbd_map_demo.sh` → exit 0;
preflight của 00800–00809 đều exit 0, `ready=true`, `issues=[]` (gồm 00803 và
00804). Sau đó 00803 chạy offscreen 30 giây: 128 frame ghi đủ, shutdown sạch,
M3 latest/accepted rev8, M5 rev8 với 2 polygon hợp lệ không stale; acceptance
checker `accepted=true`. Artifact:
`runs/rebuild-rgbd-prepush-00803-30s/`. Đây là runtime validation cho 00803;
các map còn lại mới preflight. Chưa có `configs/demo-007*.local.json` trong checkout
này, vì vậy map 007xx chưa được runtime/preflight xác nhận ở đây. Mã nguồn
runner đã mở rộng cho 007xx; để chạy cần cung cấp scene asset, profile RGB-D
đã hiệu chuẩn và provenance floor cho map đó. Những profile/assets local không
được commit nên push NeuSymNav một mình không tự đem chúng sang máy teammate.
Quét checkout hiện tại cũng không thấy scene basis `00770` trong Rebuild asset
tree (dù có P10 config `00770`, config này trỏ tới đường dẫn máy khác và chưa
phải profile có thể chạy tại đây).
Đây là thay đổi R6 (đóng giới hạn mã map trong runner), không chứng minh mọi
map đều có calibration hoặc chất lượng phân vùng đạt yêu cầu.

### Follow-up M4 contour topology — 2026-11-02

The next Rebuild M4 source fix addresses the saved frame-243 contour in the
OpenCV 4.6 build used by the official worker. `CHAIN_APPROX_SIMPLE` may encode
a boundary touch where a contour vertex lies inside another segment; repeated
vertex splitting alone missed that contact. The wrapper now inserts those
contact vertices before splitting, and discards a recursively produced
two-point retraced spur while retaining its non-degenerate sibling loop. The
M4 fallback area guard and M5 polygon validator are unchanged.

The exact captured frame-243 mask probe now returns a valid 3,327.5-pixel loop
from the 142-point source contour. Rebuilt official worker SHA-256:
`6ff1fb5ba2275c9311004bcb7bd41995a7f4c64c76107dda8fba785d964a3693`; generated
`wrapper.cpp` matches the source. The 22-frame admitted recording replay with
that binary processes all 22 records. The first four updates have no region;
M5 accepts updates for M3 revisions 5–22, including frame243 at revision 19,
and finishes with a valid 7.9975 m² region on M3 revision 22. The final replay
record is not stale. Artifact:
`.runtime/rebuild-m4-vertex-diagnostic/live-run-22frame-degenerate-loop-replay.json`.

Current-pin synthetic source parity passes 3/3 frames. An offscreen 30-second
RGB-D run completed and admitted/processed all 7 room frames; M3 reached rev7,
M5 rev3 with one valid region, `stale=false`, and clean shutdown. Its acceptance
checker passes. A direct pinned-source oracle over the same 7 recorded frames
also passes exact M3 state/origin/revision/height-mask parity and exact M5
region ID/polygon parity. Artifacts:
`runs/rebuild-rgbd-currentpin-offscreen-00805-30s-20261102/` and
`runs/rebuild-rgbd-source-oracle-20261102-m4-topology-currentpin-recorded/parity-report.json/parity-report.json`.
Preflight is `ready=true`, `issues=[]`; all use M4 pin `6ff1fb5b…`.

The 29-frame admitted sequence from an older run profile also replays against
this pin: M5 accepts revisions 5–29 with two regions at M3 rev29 and no M4
failures. Artifact:
`.runtime/rebuild-m4-vertex-diagnostic/live-run-29frame-topology-replay.json`.
Therefore the M4 fix is implemented, correctness-verified on exact mask and
22/29-frame replays, and runtime-validated in a bounded offscreen integration
smoke. It is not yet validated in a visible 180-second run: `xdpyinfo` cannot
connect to `DISPLAY=:0`. R8 visible live acceptance remains open. See the newest
section in `docs/rebuild-full-room-pipeline-plan.md` and the source diagnosis
report.

Verification for this checkpoint: Rebuild `cmake --build build/native-m4-dude
-j2 --target occusg_dude_worker` → exit 0; NeuSymNav shell syntax and
`git diff --check` → exit 0; `bash tools/run_rebuild_rgbd_map_demo.sh 00805
--preflight` → exit 0, ready/no issues; `tools/compare_rebuild_rgbd_source_oracle.py
--frames 3` → exit 0, parity 3/3; the current-pin recorded oracle over 7 frames
→ exit 0, parity pass; 30-second offscreen run → exit 0, 7/7 room frames; demo
acceptance checker → exit 0, accepted; 22- and 29-frame saved replays → exit 0.
`xdpyinfo` → exit 1 (`unable to open display :0`). No unit-test suite was run.

### Follow-up live demo viewer crash — 2026-11-02

Inspection of `runs/rebuild-rgbd-live-00805-180s-m4-topology/summary.json` and
`ui/desktop.log` shows the viewer raised `KeyError: 'source_region'` in
`SpatialSceneWidget.paintEvent()` while sorting hierarchy nodes. The viewer
process exited `-6`; the main pipeline continued through its 180-second run.
The run captured 844 sensor frames and finished its raw and room-pipeline
recordings cleanly, but outcome is `incomplete` and the acceptance checker
rejects it because the UI failed and resource sampling was incomplete.

The completed pipeline processed 26/421 offered room updates (395 queue drops).
It ended at accepted/latest M3 rev26 and M5 rev21, with two valid non-stale
regions, 8.7313 m² and 1.6088 m² by polygon area. This confirms the contour fix
is producing valid geometry in the 180-second run; the low update throughput
and absence of room ground-truth scoring mean semantic segmentation quality is
not yet established.

`spatial_scene.py` now ranks `source_region` hierarchy nodes explicitly, places
them from their polygon geometry, and draws current M5 outlines in a distinct
color. A new 30-second offscreen run after the fix completes with UI failure
null, one valid M5 region, no stale state, and acceptance checker `accepted=true`.
Artifact: `runs/rebuild-rgbd-ui-source-region-fix-00805-30s-20261102/`.
Verification command exits 0. The same visible 180-second command can now be
rerun; R8 remains open until it completes with UI healthy and the checker passes.

### Alternate local Rebuild maps — 2026-11-02

Prepared two additional calibrated local profiles for the Rebuild RGB-D runner:
00802 (`wcojb4TFT35`) and 00806 (`tQ5s4ShP627`). Their scene assets and
calibration data were already present; only the pinned `habitat_worker.py`
checksum was stale after the existing calibration-ID precision update. The
local profile checksums now match the current worker source. Both map
preflights return exit 0 with `ready=true`, `issues=[]`.

Map 00802 has now completed a visible 180-second run at the current M4 pin.
Outcome is `completed`, 1,114 captured frames, clean UI/resources, and the demo
acceptance checker returns `accepted=true`. Final state is M3/M5 rev30,
`regions_stale=false`, with two valid adjacent M5 polygons of 8.620 m² and
2.874 m². The screenshots correspond to this run. Throughput remains limited:
the room lane processed 30/556 offers and dropped 526 to its bounded queue.
This proves the pipeline can produce and publish two current M5 regions on
00802; no semantic room ground-truth score is available. Map 00806 is
preflight-ready but has not yet had a runtime or M5 acceptance run.
Artifact: `runs/rebuild-rgbd-live-00802-180s/`.

### Full Rebuild room pipeline — R0–R7 partial source-oracle — 2026-11-02

User authorized implementation from `docs/rebuild-full-room-pipeline-plan.md`;
no subagents used. R0 source/caller audit and pins are recorded in
`docs/rebuild-full-room-audit.md`. In a later explicit instruction, the user
authorized a narrowly scoped M4 fix in Rebuild; 3DSG remains untouched.

R1 contract, R2 direct RGB-D adapter, R3 isolated M1–M5 worker/session and R4
opt-in independent runtime ingress are implemented. The ingress accepts the
primary `Observation`, not NavMapper geometry; it has a separate bounded queue,
run-wide recording reservation, telemetry/publication and failure state. The
progress audit exposed and this checkpoint fixes: accepted M3 revision beyond
latest, fresh publication with failure/replay state, missing retained accepted
raster, and absent host-side binding of worker responses to admitted frame/prefix
and startup pins. The integrated 30-second Habitat smoke completes through the
new lane. A five-frame prefix of its admitted Rebuild recording also passes
direct pinned-source M1–M5 parity. An audit-reproduced malformed M5 polygon is
now rejected transactionally inside the worker: latest M3 continues, prior
accepted M5 stays paired/stale, and invalid geometry does not poison the whole
session. A visible 180-second run opened the live UI. Diagnosis shows the raw M4
contour was already self-intersecting; M5 preserved it unchanged, so its final
publication has fresh M3 and no accepted M5. Follow-up verified that the saved
run's M4 settings match checked-in Rebuild caller defaults (1.5 m threshold,
0.5 m safety, `source` preprocessing), and replayed the admitted prefix while
capturing the exact M3 preprocessing mask. Source inspection found a
`Point2d`→integer `cv::Point` conversion in contour extraction; the current
trace proves the frame-39 bridge already exists in OpenCV `findContours` output
before DuDe; its integral `Point2d` ring is unchanged by conversion. Three
diagonal-only mask contacts explain the weakly-simple boundary. User then
authorized a source fix in Rebuild. M4 now splits weakly-simple repeated-vertex
contours into simple loops, resolves diagonal-only foreground contacts
deterministically, bypasses the raster round-trip for already-simple
incremental contours, and rejects self-intersecting output before accepting it.
Originals of the three changed files are backed up at
`.runtime/rebuild-m4-vertex-diagnostic/original-source-backup/`. The first
corrected official M4 binary pin was
`5e34759d1c32197ee207c408579604fb797e86839d034d5752ac42b222a9608d`; its exact
29-frame replay passed with M3 rev29, M5 rev24 bound to M3 rev29, two valid
regions, not stale. A 3/3 synthetic direct-source parity oracle also passes.
One requested visible 180-second live run remains unaccepted: the UI cannot
connect to `DISPLAY=:0`, room lane processed 22/289 offers, and M5 ended stale
(accepted M3 rev18 vs latest M3 rev22); the checker exits 1. See the source-fix
report linked below. Native empty-episode behavior, cumulative OctoMap voxel cap,
full R8 acceptance and room-quality comparison remain open.
Native empty-episode behavior and cumulative
OctoMap voxel cap remain unverified/missing; full R8 acceptance and room-quality
comparison remain open.

R5 carries latest and retained accepted M3 map snapshots with the exact M5 pair;
UI has distinct Control map and Rebuild M3/M5 tabs, a Latest/Accepted map
selector, and does not overlay old M5 on a different latest M3 revision. Profile
auto-selects Rebuild M3/M5 when its lane is enabled. Raw M5 polygons and
footprint membership now enter hierarchy as separate `source_region` nodes and
domain-tagged edges on NeuSymNav's existing canonical object IDs. Stale/replay
or floor mismatch marks source membership unavailable. Control-map membership
and Stable Room source remain separately identified. Final export writes
`room-pipeline.json` separately from control `nav.json` and hierarchy, with
manifest checksum/source revisions. Cross-check: implementation-plan P07
failure state, P08 source-age/UI and P09 config/export. The final focused suite
and hierarchy coverage are recorded in the audit-response report.
R6 adds `tools/run_rebuild_rgbd_map_demo.sh` and versioned profile
`rebuild-rgbd-m1-m5-v1`. It derives a map-specific runtime config from the
existing calibrated local profile, pins M2/M3, M4 and the Rebuild Python source
closure, allows 60 seconds for Habitat startup, then invokes the existing CLI
preflight or bounded demo wrapper. The sensor calibration identity now hashes
the actual mount quantized at 1e-6 so body motion does not create a false
calibration change; per-frame world pose remains unmodified. It
does not alter the baseline or the older M4/M5 runner. The config parser now
allows this exact profile ID. Shell syntax and the 00805 preflight passed. A
bounded 30-second Habitat smoke exercised the integrated M1–M5 lane; this is
runtime-integrated evidence, not R8 acceptance. R1 has
no independent review. R7 has three-frame synthetic and five-frame recorded
Habitat source-oracle parity; historical caller parity remains open. The live
smoke was completed with 7/7 admitted room frames processed, but 60/67 room
offers were rejected by the bounded queue; this is not R8 acceptance. No
installation, training, download, commit or publish. Reports:
[R6 runner checkpoint](docs/results/rebuild-rgbd-runner-2026-11-02.md),
[audit](docs/rebuild-full-room-audit.md),
[architecture](docs/architecture.md); native smoke artifact:
`runs/rebuild-room-native-smoke-20261102-final/session/`.

R6 verification: `bash -n tools/run_rebuild_rgbd_map_demo.sh` → exit 0;
`bash tools/run_rebuild_rgbd_map_demo.sh 00805 --preflight` → ready/exit 0.
Generated profile: `.runtime/rebuild-rgbd-m1-m5-v1/configs/map-00805.json`.

Progress audit response, live smoke and recorded-source evidence:
[audit response](docs/results/rebuild-rgbd-progress-audit-response-2026-11-02.md),
[live smoke report](docs/results/rebuild-rgbd-live-smoke-2026-11-02.md).
The final focused CPU suite for this checkpoint passed 141 tests in 27.03s;
preflight is ready with no issues, shell syntax and `git diff --check` pass.
Root-cause details, polygon hashes, and gate results:
[M5 polygon diagnosis](docs/results/rebuild-rgbd-m5-invalid-polygon-diagnosis-2026-11-02.md).

Latest R8 blocker diagnosis: exact replay of the 22 admitted live frames with
the first corrected M4 pin showed frame243's full fallback generated a simple
0.11875 m² candidate against the prior 7.7175 m² region while M3 free cells
increased slightly (45.85%→45.93%). M5's existing 85% area-drop guard correctly
rejected it. Rebuild's fallback now preserves the prior M4 state when candidate
area is below 15% of prior stable area. Official M4 pin is
`b7c31163135740eb93a66ec56e2cb2abd0cb02e417bd75edbd97a34d9d83a164`; build
completed. This prevents state poisoning, but does not recover freshness: final
replay state remains accepted M3 rev18/M5 rev13 vs latest M3 rev22. Native logs
show expanded wrapper rejected 4/4 contours; full fallback received 12 contours,
rejected 11, and kept only a 47.5-pixel region from a 3,503-pixel connected M4
mask component. Topology-safe extraction that preserves the large component is
still open; no new live demo was run. See
`.runtime/rebuild-m4-vertex-diagnostic/live-frame243-native-stderr.txt` and
`.runtime/rebuild-m4-vertex-diagnostic/live-run-22frame-after-area-guard-replay-final.json`.
For pin `b7c31163…`, source containment is implemented and the 22-frame
regression replay confirms the fallback no longer replaces stable M4 state;
full source-oracle parity and the original 29-frame replay have not been rerun
against this new pin. It is not runtime-validated for live acceptance.

### User-authorized publication in logical commits — 2026-10-30

User explicitly requests allcurrentlocalchanges committed byfunction andpushedto
origin/main. Remote successfulfetch:HEAD=origin/main4366089 beforecommits. Publish
set68source/test/config/docfiles962527bytes; noruns/models/datasets/venvs/runtime
artifacts, no credential/privatekey patternfindings. Sixgroups:evaluationmetrics;
CGspatial+realCLIPassociation; detectorreplay/audit/calibration; nativebodygeometry;
GPU/multimapdemo profiles; results/statusdocumentation. Sharedlauncher staged in
twoparts tokeep appearanceassociation separatefromnativebodybinding, workingfile
unchanged. FullcurrentCPU2138passed/2skipped/3native-deselected in116.41s;
preflightreadytrue0,diffcheck0. NativeRSS/IPC andsingle-scenequalitylimitsremain;
publicationdoesnotclaimnewruntimeacceptance. Authorizeddestination
 git@github.com:hiiluo/NeuSymNav.git main; noforcepush/historyrewrite.
CommitIDs/pushresult/remoteverification saved .runtime/github-push-20261030/.


### Other-map selection and00770demo — 2026-10-30

Prepared currentGPUprofiles00770 and00802 from existingpinnedscene/measurement/
explicitspawn sources, retaining11s640/.30+CGvisual+robotradius.125/height1/margin.05.
Mapselector supports00770/00802/00861 and keepsIntel.localprofiles fallback;
GPUwrappers acceptNEUSYMNAV_DEMO_CONFIG, default00861 unchanged.00337meshpresent
butnotprepared; upstream00800–00809configs/assets absent onthisCUDAhost.

Implemented/configverified:3maps actualpreflight0readytrue, bashsyntax0/list0,
unknownmap99999expectedexit2, gitdiffcheck0. Config/wrapper/docs only; prior2138
CPUtestsnotrerun/reclaimed. Actual00770UI60s/wrapper72.036s exit1/incomplete due
1RSSsampleerror, nohealth/admission/exportfailure, cleanworkers.1107/1107raw,
11committedbatches/9objects/23realfeatures,379pinsstable. Actualagent/navmesh.125/1.
Noquality/P10/nativeoverallacceptance or previousRSSfixclaim. ReadonlySQLbackup
used forfirstsourceRGBpreview; strictqualityexportrefusednonemptyWAL, noexport/
checkpointrepairclaim. No modeldownload/install/source-siblingwrite/commit/push.
Evidence .runtime/map-switch-20261030/report.md +requests/exits/pins/proof/preflights.
Usage docs/running.md: bash tools/run_map_demo.sh 00770 300 (or00802/00861).


### GitHub main updated; all local changes retained — 2026-10-30

User requests pull/conflictcheck and explicitly allcurrentlocalchanges applied to
latestrepo. Fetched origin/main1e45fe8→4366089 (e222b24UI+PRmerge4366089), then
fast-forwardedmain. IntermediategitpullnetworkfailedSSHpublickey; localffmerge
usesalreadyverifiedsuccessfulfetch. No newprojectcommit/push/historyrewrite.
64dirtypaths backedupintar+binarypatches+stash7654d823c252fa3ff2f655b63047fcffca4fda84.
Stashapplycontentconflict onlydocs/implementation-status.md; resolvedpreserving
completeupstreamUI/environment+localquality/CG/detection/bodycheckpointlines.
Sourcesmergedwithouttextconflict;3local-onlyCGprofilesrepinnewupstreamUIworker.
All64localpathsverifiedpreserved; upstreamUI codebyteidenticaltoorigin/main.
SelectedCGvisual/11s.30/radius.125m/height1m retained. Localchangesremainunstaged/
uncommitted, indexempty/no unresolvedentries; stashandarchivekeptasbackup.

FreshwholeCPU2138pass/2skip/3native-deselected exit0/118.75s,377functionalpins
unchanged; mainGPUdemo preflightreadytrue0, gitdiffcheck0. NoGPU/native rerun or
newruntime/performance/qualityclaim; priorIPC/RSSlimitsnotclaimedfixed.
Evidence .runtime/git-pull-20261030/{report.md,before.json,working-files.tar.gz,
tracked.patch,index.patch,stash-commit.txt,preservation-verification.json,
conflict-resolution.json,integration-pin-updates.json,full-cpu.log,verification.json}.


### User body geometry: radius12.5cm / diameter25cm / height1m — 2026-10-30

Implemented/correctness-verified/nativeagent+navmesh+sensor smoke-validated.
Main11sCGvisualprofile now cylinder-r125-h1000-v1, radius.125m,height1m;
margin.05m/near-ground.05m/map5cm/speed/yaw/TTL/sensortransforms unchanged.
Idealbody+margin diameter35cm; rasterboundaries canrequiremore, notapassageguarantee.
Launcher derives nativegeometry from navigation.robot; worker validates/setsagent,
recomputes simulator-only navmesh preserving allnonbody loadedsettings, validates
actualreadback; hostrequires matchingclosedgeometryACK. No navmesh intoonline map.
Legacy noexplicitgeometry standalonepathcompatible;8currentworkerpinsresynced,
historicalconfigsnapshotpins/dimensionsnotmassrewritten. Need freshoutput/restart.

RED10fail1pass→focused100pass0; settingspreservation RED1fail→finalfocused208pass0.
FreshwholeCPU2097pass/2skip/3native-deselected0/114.83s,368pins unchanged.
IndependentSolHigh ACCEPT,13freshgeometrytests0, IPCACK/reaping+sweptguard probes0;
73snapshothashes/8profilepins/finalnativeartifact verified. Finalpreflight0readytrue,
gitdiffcheck0. ActualHabitat0.3.3 sensor-smokeexit0 agentradius.125,height1 and
navmesh.125/1readback, RGBD480x640/navdepth180x240, cleanreapedshutdown.
Nativepassagetraversal/collisionrate/coverage/fullpipelineP10/runtimeperformance
notmeasured; priorIPC/RSS issuesnotclaimedfixed. Source siblingsread-only;
noinstall/download/training/commit/push.
Report docs/results/household-robot-geometry-2026-10-30.md. Evidence
.runtime/robot-geometry-20261030/{red.log,preserve-settings-red.log,focused.log,
full-cpu.log,verification.json,native-smoke.json,preflight-final.json,review/}.


### CGvisual selected; measured detection improvement — 2026-10-30

User explicitly selects CG+Visual; tools/run_gpu_demo.sh and
run_conceptgraphs_demo.sh now use demo-yoloe11s-conceptgraphs-visual-gpu-00861.json.
YOLOE11s640/conf.30/cap30, pairedlocalMobileCLIPblt; existingCGcanonicalowner+real
openai_clip retained. Implemented/source+offlinecorrectness verified/livecomponent
wiring demonstrated. Overallnative acceptance remainsincomplete (detailsbelow).

Executed original79/223GT audit;29labelconfusions(table→diningtable14),24localization,
2duplicates, raw46TP108FP177FN unchanged. GT-free realGPU6variants+2runtimecap30
checks allexit0. Selected11s TP80FP134FN143, P37.38/R35.87/F136.61% versus
29.87/20.63/24.40 original. MoreFPabsolute; doorTP9→42 butchair21→19 andtable,
lamp,island,oven still0TP. Prompts and960 tested; no promptrewrite/perclassfitted
threshold promoted. APfloor/cap differences and one11slowfloorcap recorded.
79frames alreadydevelopment; noheldout/multiscene/generalizationclaim.

Fresh wholeCPU2084pass/2skip/3native-deselected0/113.86s,367pins stable.
IndependentSolHigh offline/sourceoracle reproduces allbbox/maskAP+PR within1e-12,
allsource/GT/mask/59classbindings and449ledgerassets;36freshfocused tests0.
Syntax/preflight0readytrue. Native117pins unchanged inbothattempts: firstfails
30.829s exit1 navigationIPCdeadline, secondaryexportmismatch, hostpausecorrelated
nearfirstcommit (rootcauseunproven); unchangedrepeat runsfull60s/71.772wrapper,
nohealth/exportfailure,25realfeatures/36visualpairs/0fallback,1256/1256raw. Repeat
still exit1/incomplete due1RSSreaderror. NoTTL/deadline/safetyweakened, nofixclaim,
no fullnative/P10/stabilityclaim. Failedattemptretained; no retrytohideRSSfailure.

Trainingreadiness:79RGB/223candidateCOCOmasks RLE/hash/bboxverified; one-scene
nonexhaustiveannotationsnottrainready. Existing1400Hypersimtriplets/14scenes
inventoried, HDF5/NYUmapping/completeness/splitsunvalidated; notraining/download/
install/source-siblingwrite/commit/push. Remaining: dataaudit/independentscene
validation and hostdeadline/RSS reliability diagnosis; SAHI/temporalconfirmation
notimplemented. Actualassociationquality undernewdetector notremeasured.
Report docs/results/detection-improvement-2026-10-30.md; traininghandoff
 docs/detection-finetuning-readiness.md. Evidence .runtime/detection-improvement-20261030/
(commandsexits,replays/evaluation,audit,training-readiness,fullsuite,pins,
final-review,native-attempt-1/2,native-proof.json). No sourcepublication.


### ConceptGraphs real visual completion — 2026-10-30

Implemented / correctness-verified / scoped native runtime-validated. Missing real
visual path is now closed with explicit local openai_clip/openai_jit CPU backend,
strict SHA/architecture/transform/feature-space provenance and full runtime/owner
wiring. Earlier “complete within available assets” wording was too narrow for the
user's requested full integration; this checkpoint supersedes that visual gap.
No install/download/training/sibling edits/default promotion/commit/push.

Fresh fullCPU2048passed/2skipped/3native-deselected exit0/105.22s,356pins unchanged.
IndependentSolHigh ACCEPT:44focused tests exit0 and artifact audit exit0, all154
vectors/79bindings/223GT, model+space hashes, independent four-mode globalIDF1 and
nativeDB proof. Native60s exit0/completed (70.996s wrapper),117pins unchanged,
1350/1350raw,15durable actualfeaturevectors,8/8objects appearance,14visualpairs,
0fallback. This is separate from fixed79 quality; no300s fullvisual/P10 claim.

Same79frames/137clouds/223GT: CGspatial→CGvisual IDF125.98→26.54%,
HOTA22.28→25.51%,AssA29.45→42.43%, but unresolved29→36, IDTP unchanged43.
237realvisualpairs/0fallback. Legacy+visual highestIDF128.57/HOTA26.32 on sample.
Detection unchanged; no heldout/multiscene improvement claim. Cache trust limitation
and conditional switch/revisit supports documented. Fullvisual launch:
`bash tools/run_conceptgraphs_demo.sh 300`; `--preflight` supported.
Report: docs/results/conceptgraphs-visual-completion-2026-10-30.md.
Evidence: .runtime/conceptgraphs-visual-20261030/; exactcommands/exits/pins,
replay/fixed79/, evaluation/, native-visual-proof.json, full-suite-result.json,
final-audit/{review.md,result.json}. Next: unresolved/ontology audit and independent
validation scenes before calibration/default decisions.


**Goal-change diagnosis — 2026-10-30 (read-only):** lượt user092615 có48lần
đổi goalID trong retainedproofs,27segment-start gaps<1s; ID không đủ suy tọa độ
đích. Đã tái hiện cơ chế targetdrift: _match_current nhận viewpoint gần<=10cm,
_remember(preserve_time=True) giữ thời gian chọn nhưng ghi đè worldtarget.
Probe productionpolicy CPU: goal_retained vẫn trôi30cm/0.6s, exit0. Chưa sửa
policy/config/gate, chưa có native/replay causality cho từng lần đổiID.
[Evidence và giới hạn](../runs/goal-change-diagnosis-20261030/report.md).


**Checkpoint mới nhất — FOV/frontier/goal trên occupancy map, 2026-10-30:**
implemented / CPU correctness-verified / Qt offscreen rendered. FOV dùng rigid
planar camera mount đã hiệu chuẩn từ RGB/body, cập nhật bằng mỗi measured navpose;
DTO tách nguồn calibration khỏi nguồn pose hiện tại, không relabel ảnh RGB cũ.
Frontier boundary points vàng, viewpoint xanh cyan, goal sao hồng và route từ
kết quả planner thật; không chạy thêm planner. Plan có source/maprevision/age
riêng, STALE rõ ràng; pause/stop/guardzero/actuatorreject/exception bỏ activegoal.
Giới hạn8192points/64viewpoints/2048route, UI-only sau coalescing, không đổi safety.

Final wholeCPU1886pass/2skip/3native deselect, exit0/98.71s; focused194pass0;
preflightreadytrue0, gitdiffcheck0. Đã sửa finding review actuator veto giữ goal;
probe độc lập rerun0. Reviewer hết usage limit trước finalACCEPT, không claim
review hoàn tất. Không chạy GPU/native hoặc đo lại Hz;17.698Hz là snapshot trước,
P10 vẫn chưa nghiệm thu. Demo mới: `bash tools/run_gpu_demo.sh 60`.
[Commands/evidence/limits](../runs/map-navigation-overlay-20261030/report.md).


**Checkpoint mới nhất — marker robot trên occupancy map, 2026-10-30:** đã sửa
lỗi overlay chỉ nhận pose ở nhịp RGB5Hz trong khi map dùng depth navigation riêng.
Mọi capture depth (kể cả startup) giờ gửi measured pose trước khi map được admit;
for_nav vẫn yêu cầu exact source/time/domain. Không tái dùng pose cũ, không dựng
FOV RGB khi chỉ có depth. Implemented/scoped correctness-verified: regression
RED2fail1 -> GREEN107pass0/6.07s, gồm capture/publication/Qt overlay/transport.
Không chạy native GPU hoặc đo lại Hz cho thay đổi này; benchmark60s phía dưới
thuộc snapshot trước. Không đổi gate/TTL/control/model/source repos.
[Evidence và lệnh](../runs/robot-marker-20261030/report.md).


**Checkpoint mới nhất — GPU/motion repair, 2026-10-30:** implemented /
correctness-verified / single-scene60s runtime-validated. GPU raycasting opt-in
trên RTX3060; primary640×480/YOLOE26m giữ nguyên, nav240×180, request5/30Hz,
UI2Hz/npzv2, TTL300ms/clearance/footprint/unknown/proof không đổi. Demo:
`bash tools/run_gpu_demo.sh 60`; CPU wrapper cũ vẫn có.

Frozen native60s **exit0/completed**, actualcontrol **17.698Hz**, interval
p95 **98.201ms**, p99 **124.398ms**; >50ms **436/1060(41.13%)**, >100ms
**49/1060(4.62%)**.1053nonzero executedproofs, observedmotionlowerbound
**1.985m**,1332/1332fullraw/485112599B,42detector/23objectevidencecommits.
RSS559/559valid/GPU63/63valid, cleanworkers/strict offlineexport+proof/fullrawdecode
exit0;223source/test/profile/scriptpins stable. WholeCPU1859passed/2skipped/
3native deselected0; actualCUDA31passed0; scopedSolHigh ACCEPT GPUIPC/lifecycle,
publication/finalregiondrain, geometrycache/config30/uint8check, projectionreuse.

8expired_or_zero không có proof, nên aggregate actuation.complete=false;1053
proof đã giữ khớp exact rawsource, motion chỉ là lowerbound.
**Chưa đạt20Hz hoặc deadline50ms ổn định; P10 chưa nghiệm thu.** OffscreenQt timing,
chưa đo600sGPU/finaltwoscene campaign/assignedroommembership. Không suy semantic
accuracy/confidence tăng. Lượt đứng im cũ khớp productionpause/source-cache
reproduction; không có ACK gốc để quy kết thao tác người dùng. Đã sửa paused
nonactuating result và thêm audit64UIcommands; không tựresume/hạsafetygate.
Chi tiết commands/exits/retainedfailures/reviews:
[GPU/motion report](../runs/realtime-motion-20261030/report.md),
[results](realtime-motion-results.md), [design](gpu-mapping-design.md).
Các checkpoint tiếp theo bên dưới là lịch sử và không thay thế kết quả này.


Cập nhật: 2026-10-30.

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


### GitHub publication and fresh-runner compatibility — 2026-10-29

Implemented/published: initial source commit625885f pushed to public
https://github.com/hiiluo/NeuSymNav (main), remote SHA independently matches;
SSH origin tracks main, working tree clean at publication. Source-only initial
payload339files/3053966bytes; ignored assets/native closure preserved locally.
Initial hosted CI40843647243 failed despite local1540pass: undeclared Pillow,
NumPy2 huge-int promotion, and /proc process-exit read races. Diagnostic follow-up
0226b95/run40844028506 exposed exact failure annotations without credentials.

Fix: declare Pillow>=10,<13 and supported NumPy>=1.26,<2 (verified host1.26.4),
handle only ENOENT/ESRCH during test /proc reads as exited, keeping all cleanup
assertions. No production source change or benchmark pin change; NumPy2 support
is not claimed. Fresh targeted appearance/capsule/detector/region suite92passed,
exit0/20.51s. CI retains failure exit status and bounded failure annotations.
Logs: runs/github-setup-20261029/ci-diagnostic-annotations.json and review/.
Remote rerun of compatibility fix remains pending at this checkpoint; see the
repository Actions tab for its live verdict. Runtime/P10 evidence is unchanged.


### Motion/realtime repair in progress — 2026-10-29

User authorizes diagnosing latest stationary demo and improving useful realtime
against NewOH3DSG; no installs/downloads/source-repo changes or publish requested.
Latest user run2348calls/19.85Hz contained4rightturns,2343control_rejected,0forward,
0measuredtranslation andmaprev5 frozen while2940rawframescontinued. Production
CPU repro identifies accepted-pause→supersededpose lookup as the exact pattern;
consumed UI mailboxes prevent attributing original request/timestamp. User unsure
about Pause. No automatic resume or model-wait explanation is assumed.

Implemented: explicit non-actuating paused/closing results; bounded UIcommandACK
audit at cleanfinalization; linear delimiter scan for fragmented RGB JSON-lines;
optional bounded prewarmed exact frontier reduction kernel. Independentreview
SolHighACCEPT69tests+750native differentialcases; newgeometry guard optimization
is still being verified/reviewed. FirstwholeCPU1564pass/1skip/3nativedeselected with
3failures only stale UI script SHA in shippedconfigs; updatedpins and launcher
28pass exit0. Final combined suite required after all optimizations freeze.

Runtime evidence retained: no-UI-input30s oldbaseline10.09Hz/0.7535m; firstcandidate
60s11.25Hz/p95138.20ms/p99158.42ms/227of670intervals>100ms,1.8117m lowerbound,
931/931rawcomplete,13detector/objectcommits. One unsupported RSSsample means
outcomeincomplete/exit1; not promoted to complete runtime or20Hz. No gate relaxed.
Raycast pool reuse CPUprobe only0.7% benefit, no persistentpool implementation
selected; RSSchurn causalityunproven. New20Hz includesSTOP; moving/control/sensor/
UI/model populations remain separate. Further measured optimization ongoing.

Artifacts runs/realtime-motion-20261029/, docs/realtime-motion-plan.md,
docs/realtime-motion-results.md. MainownsGPU/sharedcontracts; guardedgeometry
worker owns safety.py; no other GPUbenchmark active at this checkpoint.


### Offline object quality evaluation — 2026-10-30 (in progress)

User explicitly authorized detection/geometry/association metrics and resumed
implementation. Additive evaluator modules, versioned GT/prediction inputs,
offline CLI JSON/Markdown reports, read-only committed-ledger exporter. Existing
unrelated motion/runtime working-tree deltas preserved; no training/install/
download/publish or runtime semantic-GT inlet. Design: quality-evaluation-design.md;
usage: object-quality-evaluation.md. Evidence runs/quality-evaluation-20261029/.

Implemented: operating-point P/R/F1, bbox/mask AP subset, 3D/XY/cloud metrics,
IDF1/conditional pair diagnostics/switches/fragments/revisit, online/final policy.
HOTA/AssA explicitly unavailable. Independent original reviews found local
Hungarian pruning before global IDF1 and two integration seams; fixes implemented,
integration rereview ACCEPT19focused+16boundary groups0. Metrics review ongoing
for exact IoU boundary; exporter review ongoing. Main grouped193CPU pass0 before
latest boundary delta, not a final full-head gate. All RED evidence retained.

Native preparation (CPU extraction only): first12source-ordered committed batches
from frozen long600s ledger exported exit0,5detections/5identity observations;
total51committed batches. GT template unannotated, no accuracy values invented.
Scene00861 semantic assets exist; new offline-only aligned GT renderer is being
implemented/tested before a bounded12frame semantic render. No new GPU run yet.
Blockers/unproven: genuine quality baseline pending aligned GT; online historical
identity cannot be recovered from ledger IDs rewritten by merge; geometry GT
scope and full fixed multi-scene evaluation remain separately unproven.

### Fixed sequential exploration goals — 2026-10-30

User authorizes holding one world goal until within threshold, then selecting the
next; main owns navigation policy/controller and regression tests. Implemented:
runtime enables strict ID/XY/time commitment, replan only the same target on new
NavMap, arrival at <=0.20m emits a stopped observation tick before new selection.
Frontier drift/ID churn/closer alternatives/expired hysteresis never replace an
active target. Unsafe/missing path, outside map or collision cooldown => WAIT,
retain target; stale source still stops; episode reset clears old commitment.
Private baseline legacy mode remains for parity. Coarse rolling-origin quantization
found in review is addressed by exact terminal world target in controller with
same-cell and segment safety checks. Public route endpoint matches actual target.

Correctness checkpoint: final-focused.log99passed/22.43s exit0; runtime lifecycle
subset30passed/.62s exit0. Behavioral legacy RED exit1 retained. Full final CPU
suite and reviewer final verdict pending at this checkpoint. Artifacts:
`runs/committed-goal-20261030/`; instructions `docs/running.md`.
Runtime-validated: not yet for this change. No new Habitat/GPU benchmark; no new
20Hz/P10 acceptance claim. A permanently unreachable committed goal can wait
indefinitely instead of autonomously changing goal, as requested. Restart demo to
load changed code. Two source folders, models/data, TTL/footprint/RGB-D gates kept.

Final verification of the committed-goal change: **1897 passed,2 skipped,
3 native deselected**, exit0/102.47s (`final-cpu-suite.log`); final focused99pass
exit0. Independent SolHigh ACCEPT on final frozen policy/controller/tests,
61scoped tests exit0 plus coarse-origin and obstructed exact-endpoint probes.
`runs/committed-goal-20261030/review.md`, `source-sha256.txt`, `verify.sh`.
State: implemented + correctness-verified for this behavior; native
runtime-validated remains unproven. No P10/realtime acceptance upgrade.

### Goal wait diagnosis + 5cm arrival + bounded failure recovery — 2026-10-30

Latest retained user run094617: map258–1151 contains894 consecutive expired_or_zero
results over40.039s; last motion map257; UI has141frontier points/3viewpoints but
clears goal. Startup hashes match previous commitment fix. User Stop follows last
motion~40s later; cannot explain the prior standstill. Fresh policy on final map
finds a route, including with historical visited IDs alone; original held XY,
visited XY and upstream zero-command reasons were not retained. Exact physical
cause is unrecoverable; do not claim collision/unreachable/arrived/expired as
proved. Read-only repro: runs/goal-wait-5cm-20261030/analyze_run.py, diagnosis.json,
exit0. Legacy result reason erased upstream status and hid committed-goal intent.

User explicitly authorizes abandoning confirmed failed goal, avoiding continuous
switching. Implemented runtime arrival threshold.05m; hold ID/XY until reached or
>=8s persistent geometric stop,>=20distinct fresh map revisions,no3cm progress.
Then report failure/cooldown,clear failed goal without marking reached,select
next on following tick. Freshness/Pause/clock/non-geometric stops do not abandon.
Repeated revision does not count; actual progress resets watchdog. UI holds
blocked target marker without executable route; preserves command reason when
actuator says expired_or_zero. Bounded navigation telemetry retains current
ID/XY/reason counts and last failure. No safety gate relaxed.

Correctness: initial5cm/marker regression RED exit1; recovery RED exit1; reviewer
telemetry finding (just-abandoned route fallback shown as active) reproduced RED
exit1 and fixed. Final fullCPU1908passed/2skipped/3nativedeselected exit0/102.26s;
preceding focused118passed exit0/23.24s. Commands/artifacts under
runs/goal-wait-5cm-20261030/. SolHigh independent diagnosis/review found telemetry
issue; final re-review capacity error, no final ACCEPT claimed. Main verifies
regressions/fullsuite. Native45s smoke running separately; not P10/20Hz evidence.

Native smoke result: `bash tools/run_gpu_demo.sh 45
runs/goal-wait-5cm-20261030/native45` exit0/completed,measurement completiontrue,
noobservererrors/no cap breach. Body translation lowerbound1.1927447m,490motion
proofs;arrivalcount1;confirmedfailurecount2;finaltrackingnewgoal/routeavailable.
Guardbootstrapblocked4 thenwait368 corroborate blocked-commitment behavior on
newrun;lastfailedgoal8.042s/185maprevisions thenreleased. This reproduces that
class of stall and validates escape wiring;doesnot reconstruct exactoldcause.
Artifacts native45.log,native-result.json,native45/. Single45s smoke doesnot
certify fullP10,20Hz,explorationcompletion,orper-goalarrivaldistanceaccuracy.

Final review addendum: fallback independent SolHigh reviewer available; reproduced
watchdog counting source-pending/Pause/exception gap toward geometric failure.
Four live/gap regressions RED exit1 retained. Fixed control-wrapper reset on
unobserved outcomes and>1s gap resetting confirmation window; finalsource hashes
in final-source-sha256.txt. Native45s precedes only this reset delta; final CPU
verification/review pending. No newGPU rerun for gap-only delta.

Final frozen verification:1912passed/2skipped/3nativedeselected exit0/100.96s
(final-cpu-suite.log);independent SolHigh ACCEPT,76scoped tests exit0/1.16s and
livegaprepro exit0. Five finalsourcehashes match;git diff --check exit0.
State:implemented+correctness-verified;preceding native45 validates5cm/recovery
wiring;final interruptionreset delta CPU-only. No P10/20Hz acceptance upgrade.
See runs/goal-wait-5cm-20261030/{report.md,review.md,verify.sh}.

### Last goal before Stop — read-only diagnosis 2026-10-30

Latest userrun100703: lastgoal39a0b4e38a35 at(.625,.275) had23executed
align_heading commands over1.423s,actualyaw163.17->111.79deg,linear0/bodyunchanged;
userStop~.096s afterlastturn. It was turning,not reported blocked. Finalmap CPU
replan exit0 succeeds;lookaheadheadingerror~-72.49deg vs50deg rotate-onlythreshold.
Previous8.029s failedgoal(-.625,-.225) is distinct. No source/config changes or
newnative run. Evidence runs/last-goal-align-20261030/report.md,originalrunproofs/
UIStopACK. Arrivalifcontinued remains unproven;no newP10/realtimeclaim.

### Clarified previous failed goal — 2026-10-30, read-only

User refers to b3f41bf8ac07(-.625,-.225),not final39a...turninggoal. Real retained
singleframe depth CPU replay at stationarypose,sourceframe500(rawordinal620),
reproduces bootstrap_blocked:167capsulecells required,166free,1unknown,0occupied.
Unknownworldcell(-.475,-.075) is FREE in finalaccumulatedmap. Frame402 reproduces
same. Currentmeasuredcoverage differs from accumulated UI map;guardrequiresall
cells in.3mforward/.25mradiuscapsule free. Failure/cooldown then8.029s watchdog
explains blocked-intent mechanism;no actualphysicalobstacle proved. Exactoriginal
veto frame/history not restored. Probeexit0/artifacts
runs/previous-goal-bootstrap-20261030/. No source/config/gatechange.

### User-authorized forward coverage corridor 10cm — 2026-10-30

Main changed MotionGuard default .30->.10m and reference navigation.yaml; runtime
launcher uses default. Effective coverage max(.10,v*horizon),turn-only0. Robot
footprint/margin/sweptmargin,unknown rejection,depthTTL,source and path checks
unchanged. TestsRED2failed/1pass exit1;focused113pass exit0/43.67s. Recordedframe500
single-frame CPU replay .10m=>118/118free/bootstrap_ready vs .30m167/166free/
1unknown. Independent SolHigh ACCEPT47scoped pass exit0/29.59s. Artifacts
runs/guard-10cm-20261030/. State implemented+correctness-verified;native45pending.
No fullP10/parity30cm/20Hz claim,installs/downloads/sourceedits/push.

Native45s frozen10cm smoke exit0/completed,completiontrue/noobservererror/capbreach;
1.48679946m observedbodytranslation lowerbound,588motionproofs,4arrival events.
2bootstrapblocked/114collisionwaitticks remain;finalgoal waiting. Runtime-validated
bounded10cm wiring;not all stalls eliminated or fullP10/20Hz certified. Evidence
runs/guard-10cm-20261030/native-result.json,native45/. Final3hashes match.

### Missing selected-object best views — 2026-10-30

Rootcause confirmed run102221:13objects havepersistedcrops,publicationcontains
3globalpreviewimages allfromfirstobject;other12unavailablebecauseUI onlysearched
previewtuple. Implemented selectedobject lazyread in Qtchild usingreadonlyownerDB/
contenthashedassets,pinnedgallery/source/alias/revisionchecks,oneboundedcropcache;
keeps3previewpixelbudget. Compaction preserves existingoldergalleryrefs for all
objects. Noquality/confidencegate added,noverificationpromotion. Refresh13existing
UI scriptpins(8JSON/5YAML). User's13/13objects nowload/show viarealQtselectionaudit
exit0;artifact audit.json/selected-object.png visuallyinspected.

Finalfocused34passed exit0/7.95s;independentSolHigh ACCEPT28scopedpass exit0/7.46s
plus13/13archiveauditexit0. InitialmixedfullCPUhad7fail(staleYAMLpins+fixtureupdate
whiletestsloaded);fixedpins/finalmetadata,andseparatefinalfrozenCPUrerunongoing.
Artifacts runs/best-view-selection-20261030/. Implemented+focusedcorrectness+
archivedQtvalidated;notnativepipeline/P10/performanceclaim. NoGPU/install/download/
sourcefolderedits/commit/push. Restartdemo toloadchildassetprovider.

FinalfrozenbestviewCPU1923passed/2skipped/3nativedeselected exit0/110.22s;
final-cpu-suite.log,fourfinalhashesmatch,git diff --check exit0. Independent
reviewACCEPT+actualarchivedQt13/13showimages. State implemented/correctness-verified/
archivedUI-validated;no nativeP10/performanceupgrade. Requestedfixcomplete.

### Additional150% entire demo UI scale — 2026-10-30

User asks whole demo another50%. UiProcess multiplies child-only QT_SCALE_FACTOR
by1.5;allQtwidgets/paintedcontent scale together;logical screen bounds/maximize
remain. Existingpreferred2160x1350logical=>3240x2025physical atbasescale1 when
screenallows. Parent environment/control untouched.13UIworker scriptpinsupdated.
Subprocess regression RED exit1,then actualchild devicePixelRatio1.5 andparent
scale1.0 verified. RelatedUI/profile/crop suite88passed exit0/8.66s;gitdiffcheck0.
Artifacts runs/ui-scale-150-20261030/. Implemented+subprocessUI-validated;no new
nativeGPU/realtime/P10claim. Restartdemo required. Mainreview closedcosmeticchange.

### User-requested retention: only latest five run directories — 2026-10-30

User authorizes deletion of oldruns. Kept latest5 top-level directories by mtime:
ui-scale-150-20261030;demo...103827;best-view-selection-20261030;demo...102221;
guard-10cm-20261030. Deleted68olderdirs+oneoldrootlog;verifiedexactly5entries.
Freed~31.19GiB;remaining~3.14GiB. No activeprocesscmd/openFD matched deletedruns
atprecheck. Toavoidbreakingdemo,byte-verified11runtimeassets(binary,buildrecipe,
provenance/calibrations) relocated to.runtime/retained-assets(~2.5MB);updated72
config/buildtestpathfiles. BinarySHAunchanged;no build/install/download needed.
DemoGPU preflight exit0;nativeprofile61tests passed exit0/1.19s;gitdiffcheck0.
Manifest docs/run-cleanup-20261030.json;verificationlogs in.runtime/retained-assets/.
Historical docs references to deleted evidence are now intentionally unavailable;
priorgateclaims not reverified by cleanup. No nativeGPUbenchmark/commit/push.

### GitHub delivery authorized — 2026-10-30

User explicitly requests all current source changes split into logical commits
and pushed directly to origin/main. Existingbranchmain/remotemain synchronized
beforestaging. Sixcommitgroups:offlinequalityevaluation;mapping/frontier/region
performance;goalcommitment/recovery/safety;runtime+UIintegration;runtimeasset
relocation;documentation. Indexedconfigversions separate feature/pin changes from
retainedassetpaths without editingworkingtree. No models/datasets/runs/envs in
publishset:150source/test/config/doc files,~1.45MB;credential/privatekey scan no
findings. Fresh finalCPU1924passed/2skipped/3nativedeselected exit0/107.12s;
gitdiffcheck0. Native/P10/realtime limits remain as documented. Actual commit IDs
and finalremoteverification retained in.runtime/github-delivery-20261030/;
sourcepublication does not imply newnativeacceptance. Authorizeddestination:
git@github.com:hiiluo/NeuSymNav.git,main. No forcepush/rewrite intended.

### Local Intel/CPU demo environment — 2026-10-30

User authorizes full environment preparation before further code development.
Installed project-local core/dev/UI/Numba and Torch2.7.1CPU/torchvision0.22.1/
Ultralytics8.4.24/CLIP; downloaded official YOLOE26m+MobileCLIP2 with exact recipe
SHA matches. Reused stock Habitat0.3.3 Python3.9 read-only, Intel/Mesa EGL(-1),
copied local00802 scene/native worker, measured floor calibration1200samples.
Added ignored checksum-pinned configs/demo.local.json and run_local_demo.sh.
No production source/contract/safety change. See [setup report](local-demo-setup-20261030.md).

Implemented + bounded runtime-validated: preflight0 readytrue, actual desktopQt/
RGB-D/detector/object/motion45s smoke0 completed,291frames/12objects,139executed
controlresults,0.4064409m observed translationlowerbound,cleanworkers/completiontrue/
noobservererrors/capbreaches. Native protocol/preprocessingprobe0. One accepted
command lacks proof; aggregateactuationcompletefalse; no acceptedregion/membership.
No CUDA hardware on this host; no P10/realtime/quality certification. Initial20s
smoke preserved with unsupported modern Habitat planarhash; stock0.3.3 fixes
qualification through environment selection, no gate relaxed.

CPU correctness initially1924pass/1skip/3deselect/1fail exit1; execution-proof
20msfixture isolatedrerun1pass0/grouped51pass1fail1. Final idle rerun1924pass/1skip/3deselect/1fail exit1/124.26s; earlierproof
testpassesbutcapture-pairtesttimesoutwaiting3sfortwocommits. FullCPUgate
notgreen; no production/testfixperformed. Core/detector dependencycheck0,
shellsyntax/config-smokebinding/diffcheck0.
Evidence .runtime/setup-20261030/, runs/setup-demo-intel-stock-20261030/;
commands/exits/limitations in setupreport. No training/commit/push/publication.
Finalcapture-pairisolatedrerun1pass exit0/.87s; fullsuitefailure retained.
Environmenttaskcomplete; unresolvedCPUtimingfailuresreported, no P10upgrade.

### Local UI scale correction — 2026-10-30

User requests readable demo scaling. Found inherited per-screen1.375 multiplied
by hardcoded UI1.5 => actual2.0625. Removed unconditional child zoom; general UI
honors desktop settings. Local Intel launcher selects100%/clears per-screen
multipliers, supports NEUSYMNAV_UI_SCALE override. Refreshed13tracked+1local UI
scriptSHApins. Existing unrelated environment/docs deltas preserved.
Implemented + scoped correctness-verified:21UI tests passed exit0/9.78s;
actualdesktopfixture preview exit0,ratio1.0,1920x1018available/frame fits,
1920x978client; screenshot visuallychecked. Prior1.375preview retained in probe
history; actual final screenshot .runtime/ui-scale-fix-20261030/preview.png.
Preflightreadytrue0; shellsyntax/diffcheck0. No simulator/model/benchmark rerun,
no navigation/safety/semantic change or P10upgrade. Restartdemo to apply.
Evidence .runtime/ui-scale-fix-20261030/{tests.log,desktop.json,preview.png,pins.txt,
preflight.json}; commands: QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest
 tests/test_ui_scale.py tests/test_ui_reference_layout.py tests/test_ui_transport.py
 tests/test_ui_offscreen.py -q; bash tools/run_local_demo.sh --preflight.

### Longer local demo default — 2026-10-30

User requests longer demo. Local wrapper default20s->600s(10minutes); explicit
argument still overrides duration, UI Stop ends early. docs/running.md updated.
Implemented/config-verified: bash -n tools/run_local_demo.sh exit0;
git diff --check exit0; Python assertion local max_duration_s>=600 exit0.
Artifact tools/run_local_demo.sh; no quota/safety/profile changes or new native
run. A full600s run on this Intel host remains runtime-unvalidated; prior45s
smoke evidence is unchanged. No P10/performance claim.

### Select local maps from CLI — 2026-10-30

User asks commands for each available map. Added run_map_demo.sh MAP [seconds]
[output] / --list / MAP --preflight; local wrapper accepts explicit config via
NEUSYMNAV_DEMO_CONFIG, default remains existing00802. Duration600s/scale100% stay.
Added offline prepare_local_maps.py; calibrated10HM3D scenes00800–00809,1200valid
floor samples each, explicit frozen initialposes, source/script/asset/floor pins
in ignoredconfigs/demo-MAP.local.json. Setup navmesh seed0 used only for spawn;
runtime map starts empty, no navmesh occupancy input or random live spawn.

ActualReplicaCADapt_0–apt_5 renders omit6articulated objects each because live
sensor has physics disabled. Trialconfigs quarantined under.runtime; preparation
and launcher now reject these scenes rather than certify incomplete geometry.
Assets exist but full ReplicaCAD demo remains unsupported; no Bullet/contract
change or download performed. Source folders read-only.

Implemented + scoped/native-preparation validated:10/10HM3D preflightreadytrue,
issuesempty/exit0; shellsyntax/AST/diffcheck0; invalidmap2,unsupportedReplicaCAD1.
Actual00800 45s wrapper smoke exit0/completed,330frames/7objects,cleanworkers,
measurementcompletiontrue/noobservererrors/capbreaches,0.25972448m observedbody
translationlowerbound. Aggregateactuationcompletefalse; no fullP10/quality/Hz
claim. EachotherHM3D has nativeRGB-D/floorpreview only, not fullpipeline/600srun.
Evidence .runtime/map-selection-20261030/{preparation.json,preparation.log,
preflight-results.json,smoke-result.json,*-calibration.json,*.png}; runartifact
runs/map-00800-smoke-20261030/. docs/running.md has commands. No commit/push.

### Spatial RGB-D / scene graph viewer — 2026-10-30

User requests reference-style 3D cloud + spatial room/object debug view.
Implemented default3DScene tab, canonicalZ-up objectcentroids/bluegeometryregion
anchors/purplevisitedplaces,orbit/pan/zoom/fit,canonicalselection/bounds/evidence.
ExistingGraphlayout/Hierarchy remain. Edgesonlyassignedrelations; preserve
unavailable/ambiguous/unassigned, no guessedmembership/roomsemantic/traversability.
Retiredhiddenunlessselected. UIchild readonlycommittedRGB-D/SHA/source/clock/
geometry/calibration/pose binding,oneasyncworker/queue1,80kvoxels/.04m/12kperframe/
128sources/300nodes. No sensor/control/owner/IPCcontract/geometry change.24UI
scriptpins refreshed(13tracked/11local). Source repos read-only.

Implemented+scopedcorrectnessverified+archivedQt/native45wiringvalidated.
Finalfocused65pass exit0/11.10s; finalcaption25pass0. IndependentSolHighACCEPT,
43focused0+15axis/24occlusionprobes; finalsourcehashesmatch. Fourreviewfindings
reproducedRED4fail1 thenfixed(Z,clock,splat,emptydepthage); preservedlogs.
Archivedreal00805:31,293points/21sources/25nodes,20notassigned,27hidden; realQt
screenshots inspected. Newnative45exit0/completed389frames/8objects/2detector
commits/acceptedregion/cleanworkers/completiontrue/noobservererrors/capbreaches;
translationlowerbound.63528688m; aggregateactuationcompletefalse. Nativeprecedes
onlytwofinalcaptionexpressions.10mappreflightsreadytrue0,diffcheck/hashcheck0.

WholeCPU1948pass/1skip/3deselect/2fail exit1/145.83s: samepreviouslyseen testnames
capture-paircommitwait and20msexecution-proofsourcefixture. Failuresretained,
notfixedhere; nofullCPUgreenclaim or proof of causalindependence. No P10/Hz/
quality/assignedmembership/600s certification. Cloudhistorical/committedonly,
canlagLiveRGB; no fabricatedobject-roomedges. Evidence
runs/spatial-scene-ui-20261030/{report.md,verify.sh,review/,final-source-sha256.txt,
preview.json,dashboard.png,spatial-focus.png,native-result.json,native45/}.
Guide docs/spatial-scene-ui.md. Restartdemo; no commit/push/publish.

### Resizable graph panel and navigation controls — 2026-10-30

User requests freely resizing and mousezoom/orbit fordebug. Implemented visible
12pxvertical-workspace/horizontalgraph-evidence splitters;collapsibleupperrow;
scrollingevidence;largerdefaultgraphshare. Toolbarzoom-/+,Fit,Top,Expand,Popout;
normalresizablewindow/sizegrip,Dockback/close restores samepanel,andmainclose
closespopup. No duplicatecloud/modelworker.3DShift-leftdragzoom,leftorbitfull
above/belowpitch,right/middlepan,wheelzoom.2DGraphlayoutwheelzoom/Ctrlwheelrotate/
leftpan,manualtransform survivespublication/selection/resize. Canonicalselection
and3Dcamera surviveundock/redock. No geometry/provenance/IPC/control/safetychange.

Implemented+scopedcorrectnessverified:6newQtinput/lifecycletests pass0/1.74s;
finalcombined71UI/display/gallery/transport/spatialtests pass0/12.98s. Actual
archive00805Qtpreviewfloated/resized1500x900,31,293points/21sources; screenshot
inspected,exit0. Preflightreadytrue0,diffcheck0,sourcehashesrecorded. No new
nativepipeline/600s/performance/fullCPUrun; priorwholeCPU2timingfailures remain
unresolved in previous checkpoint. Evidence runs/graph-controls-20261030/
{report.md,controls.log,final-focused.log,source-sha256.txt,preview.json,
floating-graph.png,preflight.json}. Guide docs/spatial-scene-ui.md; restartdemo.
No installs/downloads/commit/push/publish. MainclosedUI-scope review.

### Floor / ceiling cloud cutaway — 2026-10-30

Implemented: default display-only height cutaway at 0.12–2.20 m above the
published calibrated floor. Cloud menu toggles the filter and adjusts both
thresholds. Missing floor datum leaves cloud complete; no guessed zero.
The same mask preserves point/color pairing. Nodes, relations, bounds, source
cloud, RGB-D, navigation and control remain unchanged. Upper walls and other
points outside the range are clipped too; this is not semantic classification.

Correctness-verified: 81 focused Qt/spatial/display/transport tests passed,
exit 0 in 12.25 s, including 10 cutaway cases for translated floor elevations,
reversibility, missing datum, menu controls and invalid limits. Runtime-validated
only for the archived real 00805 desktop preview: exit 0, screenshots inspected,
20,198 / 31,293 points visible, 21 RGB-D sources, no reader error. No new native
pipeline, full CPU suite, long-duration run or P10 certification. The two
previous whole-suite timing failures remain unresolved at the prior checkpoint.
Evidence: runs/cloud-cutaway-20261030/{focused.log,focused.exit,preview.py,
preview.json,preview.log,floating-graph.png,all-points.png,preflight.json,
source-sha256.txt,report.md}. Guide: docs/spatial-scene-ui.md. Restart the demo.
No dependencies, downloads, commit, push or publish.

### Restore floor cloud by default — 2026-10-30

User revised the display preference to include floor point cloud. Implemented:
default lower threshold 0 means no lower clipping (including small negative
reconstruction offsets), upper cutaway remains 2.20 m above published floor.
Cloud menu now says Filter cloud height; lower spin displays Keep floor at 0.
Positive lower values still hide low points. Stored geometry and graph unchanged.
Correctness-verified: offscreen pytest tests/test_cloud_cutaway.py
tests/test_graph_controls.py tests/test_spatial_scene.py
tests/test_spatial_scene_regressions.py -q, with OPENBLAS_NUM_THREADS=1 and
OMP_NUM_THREADS=1: 41 passed in 2.80 s, exit 0. git diff --check exit 0.
Artifact: runs/cloud-floor-restored-20261030/focused.log. Main reviewed the
small display change; no new native runtime validation or full-suite run.
Restart demo to load the new default; no installs, commit or push.


### Object quality evaluation and measured pilot — 2026-10-30

Implemented: offline detector P/R/F1 + per-class bbox/mask101point AP,
3D/XY observed-surface metrics, standard eligible-pair/global IDF1, conditional
pair/switch/fragment/revisit metrics, and reference-pinned HOTA/AssA19alphas.
CLI evaluate-quality/export-quality; JSON/Markdown; source-bound offline HM3D
GT renderer. HOTA unavailable statement in the earlier checkpoint is superseded.
No online GT inlet, runtimecontrol/TTL change, model/data download or training.
Existing source publication occurred separately; this continuation did not commit/push.

Correctness-verified: fresh wholeCPU1960passed/2skipped/3native-deselected exit0
105.83s;314source/test/configpins stable. IndependentSolHigh scopedACCEPT108tests
+exact HOTA19row oracle/globalIDF1DP+47nativefiles/44masks+geometryinputaudit.
Skips: optionalNumba under venv and explicitly authorizedGPUslot test.
Native executed separately: firstsemantic attempt failed closed due runtime
datasetwithoutsemanticstage; evaluator-only derived dataset repaired that
inlet without touching captureconfig or thresholds. Second12frameGT renderexit0,
allRGB/depthalignmentgatespass. Failure retained, no dataset/GT tuning.

Measuredpilot: retained00861run demo...104928-497271978 first12/16committed batches,
21detectoroutputs,44GTobservations/13uniqueIDs. DetectionTP7/FP14/FN37,
P33.33/R15.91/F121.54%, boxAP50:95=10.53%,maskAP50:95=12.69%, limited to supplied
filtered outputs. Separate projected-memory17observations excludes exactly4
unassigneddetections while retainingall44GT: finalIDF1=20/61=32.79%,HOTA33.81%,
AssA65.95%,conditionalpairs10/10,noIDsw in6transitions; no revisit support.
Online historical IDs unavailable due ledgermerge rewriting; no invented IDs.
Geometry input is recordedRGBDobserved-surfaceproxy, notfullmesh/depthaccuracy.

Evidence: .runtime/quality-evaluation-20261030/{commands-exits.json,final-manifest.json,
final-verification/,final-audit/,native-gt-overlay/,detection-baseline/,memory-baseline/,
geometry-baseline/,error-previews/}. Historical runs/quality-evaluation-20261029
was intentionally deleted by usercleanup; not restored or cited as present.
Report: docs/results/object-quality-pilot-2026-10-30.md; usage docs/object-quality-evaluation.md.
Unproven: multi-scene/seedquality, low-score fullAP, onlineidentityhistory,
long-occlusion/revisitassociation, whole-scene3Dquality, anymodelimprovement/P10.
Next improvement: ontology/missed-door/window audit, then fixedsame-input detector
comparison; expand annotation to multiple scenes and revisit cases.

### ConceptGraphs-inspired association — design checkpoint 2026-10-30

User requests implementation based on ConceptGraphs and recommendations for other
quality metrics. User explicitly selects integration into existing canonical owner
with Hungarian rather than replacing matching with upstream greedy. Source review
confirms existing bounded RGB-D clouds, first512point symmetric legacy overlap,
and demo appearance off. Local read-only ConceptGraphs reference HEAD8aca1172;
actual mapping/utils/LICENSE hashes pinned in the proposed design. Source folders
unchanged; prior evaluator working-tree changes preserved.

Design: docs/superpowers/specs/2026-10-30-conceptgraphs-association-design.md.
Proposes opt-in directional cloud overlap + compatible visual cosine, complete
bounded map-cloud search, deterministic observation sampling, durable recipe
pinning, unchanged canonical ownership/transaction and safety contracts. SolHigh
builder review identified mixed-feature score bias; main resolved with explicit
row-wide spatial fallback and a required regression. Diagnostic limitations and
same-input evaluation are specified; no improvement in measured scores claimed.

State: design prepared, awaiting document approval required by brainstorming
workflow. Implementation/correctness/runtime validation of the new recipe are
not yet performed. Read-only code/config/source inventory and git diff --check
exit0; no GPU job, test rerun, install, training, download, commit or push.
Recommendations prioritize missed-class/ontology audit, fixed-image PR/AP replay,
existing-checkpoint comparison, projection-loss audit and multi-scene revisits.

### ConceptGraphs association — approved implementation in progress 2026-10-30

User approved the design and explicitly requested implementation. Plan:
docs/superpowers/plans/2026-10-30-conceptgraphs-association.md. Main owns immutable
recipe/store/runtime/config/docs; cg_engine(SolHigh) scorer/engine, cg_replay(SolHigh)
GT-free fixed-input replay; cg_final_review(SolHigh) independent review. No new
model download/install/training/GPU job/commit/push. Existing evaluator deltas kept.

Implemented candidate: directional cloud overlap/full bounded map tree, deterministic
voxel sampling, row-wide missing-feature fallback, raw cosine+bias utility, recipe
threshold/ambiguity; opt-in config through launcher/owner and durable recipe metadata;
atomic batch diagnostics and original online endpoints. Legacy remains default.
New-mode profile preflight exit0/readytrue; not native runtime validation. Main91
integration/legacy tests pass exit0/4.26s. Full frozen CPU/review/actual replay pending.
Supported OpenCLIP path unavailable in detector26 (missing open_clip+safetensors and
declared safetensors asset); alternate local OpenAI.pt exists but not interchanged.
Geometry-only measured ablation will remain distinct from visual behavior fixtures.
Artifacts: .runtime/conceptgraphs-association-20261030/; usage docs/conceptgraphs-association.md.

### ConceptGraphs association — implementation complete, measured pilot unchanged

Implemented + correctness-verified: opt-in directional cloud/visual recipe, bounded
sampling/full-map NN, owner/runtime config, immutable durable recipe, atomic batch
diagnostics and preserved original online endpoints; GT-free read-only fixed-input
replay. Legacy remains default; no threshold tuning/default promotion. Usage:
docs/conceptgraphs-association.md; measured report:
docs/results/conceptgraphs-association-2026-10-30.md.

Fresh frozen fullCPU2024passed/2skipped/3native-deselected exit0/105.73s;351source/
test/config/toolpins unchanged. IndependentSolHigh ACCEPT93fresh tests +100distance,
98exhaustiveassignment,90actualbaselineparity probes exit0. Engine additional
576baselineingest comparisons equal; main91integration/legacy pass. gitdiffcheck0.
RED/GREEN, commands/exits, fullgate/hashpins and review retained under
.runtime/conceptgraphs-association-20261030/.

Measured real recorded-cloud replay exit0:12frames,21detectoroutputs,17original
projected observations,4explicit projection losses; all44GT retained/13unique IDs.
Legacy and CGspatial identity partitions exactly equal:8IDs,0ambiguity/unresolved,
IDTP10/FP7/FN34,IDF132.79%,HOTA33.81%,AssA65.95%,DetA17.81%,LocA79.43%.
No measured quality improvement. Pair10/transitions6/revisits0; no robustnessclaim.
CG23spatialpairs/9matches/8newIDs,11fallbackrows,0samplingcap; max1590points/object,
4834total fusedpoints. Single association-only timing145.29vs150.83ms totals is
descriptive, not nativeFPS/performance evidence; no processpeakRSS measured.

Runtime-validated scope: fixture launcher-to-owner replay and real recorded-cloud
spatial path only. No new native live/GPU campaign or P10/realtime claim. Fullvisual
measurement unavailable:0original features; supportedOpenCLIP dependencies and
declaredsafetensors absent; alternate localOpenAI.pt not silently substituted.
Next quality step requires usableverifiedappearance +hardrevisit/heldoutscenes;
detector missedclass/ontology/PRAP audit remains separately recommended. No installs,
downloads,training,sourcefolder edits,commit orpush. User-authorized task complete
within available-asset scope; unexecuted visual/native validation remains explicit.

### User-requested300s demo and all-keyframe quality — 2026-10-30

User authorizes about5min demo for measured detection/association. Ran existing
opt-in CGspatial/YOLOE26m640 profile for300s (wrapper320.964s), singleGPUslot;
117production/configpins unchanged. Source run runs/demo-conceptgraphs-300s-20261030/.
4571/4571rawframes recorded/missing0;79/79accepted detector batches committed,
clean shutdown/no workerfailed. Nativecommand exit1/outcomeincomplete because one
RSSsample readerror; no capbreach. Do not claim full runtime/P10/20Hz acceptance.

All79committed primarykeyframes exported source-order with154detector outputs;
137typed projected observations,108assigned onlineIDs,17unprojected,29unresolved.
No frame selection by quality. OfflineGT79frames/223instanceobservations/19unique
IDs via7contiguous<=12frame batches; same original strictalignment/calibration/
taxonomy/min100pixel gates. All7native renders+merge exit0, no GT in runtime.
Assigned-memory derivative keeps all79frames/all223GT and excludes46unassigned
detector outputs with exactreason; detector metrics always use all154 separately.

Measured detectionTP46/FP108/FN177, P29.87/R20.63/F124.40%,boxAP50:95=13.71%,
maskAP50:95=14.16% over retained filtered outputs. Memoryonline/finalIDF1=25.98%,
HOTA22.28%,AssA29.45%,DetA17.16%;IDTP43/FP65/FN180,6switches/8fragments in33
transitions,revisit3/10. Same137cloud CPUreplay exactreproduces actualCGpartition;
legacy119assigned/18unresolved givesIDF126.90/HOTA25.81/AssA34.34%. Thus this
spatial-only recipe underperforms legacy here; default remains legacy, no tuning.

ObservedRGBDsurfaceproxy geometry:43pred/19GT,3DIoU>=.25TP9/FP34/FN10,
P20.93/R47.37/F129.03%,matchedpointF1@5cm86.79%(9matches only). Shareddepth/pose,
not independent sensor/fullmesh accuracy. Control11.11Hz includingSTOP/pending,
intervalp95164.99ms;bodytranslation lowerbound9.38m,9arrival/2recoveryevents.
Detectorcaptureage median494.45ms,p95656.25ms;commit670.80/916.72ms,37semanticstale.
Fullvisual remains unavailable; no new install/download/training/production edits.

Evidence: .runtime/quality-five-minute-20261030/ (native, export, memorysupport,
batchscripts/GT/alignment,3qualityreports,fixed79comparison,audit,sourcepins/exits).
Report: docs/results/object-quality-five-minute-2026-10-30.md. HelpersCPUfixture13
frames12+1 verifiespartition/merge rejection; final actualartifact audit pending at
this checkpoint. Prior2024suite not rerun/reclaimed for this experiment. No publish.

Final actual-artifact audit PASS(exit0): all79orderedsourceframes/117sourcepins/
154detector+108memory+223GTmasks verified, all137typed observations and immutable
online endpoint joins checked; exact17unprojected+29unresolved exclusion accounting.
Independent globalIDF1 reproduces43/65/180=86/331 online/final. Detectorcount
identities and19HOTAalpha denominators/arithmetic checked; no full independent
HOTA reimplementation claimed. Evidence audit/result.json and audit/report.md.
Nativeoverall remainsincomplete fromRSSsample; offline qualityscope verified.

Final scoped audit ACCEPT supplements: exact7GTchunk concatenation12x6+7 equals79
mergedframes; allnative/request/filepins and unchangedalignment records verified,
223GT/19IDs/1855excluded. CGactualonlinepartition equals fixedinputreplay;
independentlegacyIDF1=92/342 andCG86/331. Twoauditcommands exit0; no reportblocking
overclaim. No independent fullHOTA/manualGT/geometrynumeric rederivation claimed.
Artifacts audit/{report.md,result.json,supplement-result.json}, final-manifest.json.


2026-10-31 — Cập nhật chính sách điều phối model: Luna xhigh cho task thông thường, Terra cho task khó hơn, cân nhắc Sol cho task thật sự khó; cấm Astra. Implemented: `docs/agent-orchestration.md`, `docs/implementation-plan.md`. Correctness-verified: `git diff --check -- docs/agent-orchestration.md docs/implementation-plan.md docs/implementation-status.md` (exit 0). Runtime-validated: không áp dụng; chưa kiểm chứng việc dispatch model thực tế. Artifact: các tài liệu đã cập nhật.

### Room graph and current occupancy display — 2026-10-31

User-authorized implementation continues completed prior pipeline; scope/design:
`docs/room-graph-sync-{design,plan}.md`. Implemented: all UI views display only
Floor→Room→Object, accepted interior room centers/dynamic anchors, weighted floor
center, elevated Room/Floor only; Object XYZ/bounds and measured cloud unchanged.
Assigned supported parent edges only. Latest navigation display is independent of
graph/detector with exact source/time/robot binding and stale room-outline label.
Exact zero-area native ring retraces normalized after schema validation; native
origin cell-shift truncation corrected via tracked hash-bound local patch/fresh
staging build. Original89file closure and old worker unchanged. Three selected
CG+Visual GPU profiles use candidate worker/UI5Hz; maintained UI checksums refreshed.

Correctness-verified: focused UI72/map44/region79/integration141 tests exit0;
independent review source-focused76+95/measured-cloud54/frozen49 exit0; native
candidate7pass2skip exit0; patch-safety7pass exit0; overlay+patch17pass exit0.
First full CPU2178pass9fail and second2185pass2fail retained: legacy Qt fixtures
omitted source-map metadata and treated mismatched-map plan as current. Fixed
fixtures and added explicit mismatched-map STALE regression. Fully frozen final
whole-suite result follows below; do not infer pass from these earlier failures.
Native configure/build0; preflight0 ready=true; diffcheck0.

Runtime-validated (bounded wiring/display scope): once60s map00861 GPU run,
wrapper74.614s/exit0,summarycompleted/errornull,1038frames/16commits/no missing,
clean shutdown/no workerfailed/no UIpublicationdrops.387functionalpins unchanged.
62sampled publications/0readerrors;20adjacentpairs mapadvances while hierarchy
frozen; allsampleage median76.44ms/p95250.55ms including shutdown. Actual archived
Qt render0 retains20234RGB-Dpoints/16sources,only1Floor/1Room/15Objects,exactObjectXYZ,
acceptedRoomcenter. All15Objects unassigned; no invented Room→Object edges.
Native runtime flag remainsfalse/no P10 or semanticroomaccuracy claim. Local4.05m
roomwindow and persistentobjects outside it remain a membership limitation.

Artifacts: `.runtime/room-graph-sync-20261031/` (logs/sourcepins/native/render/review),
`runs/demo-room-graph-sync-60s-20261031/`, report
`docs/results/room-graph-sync-2026-10-31.md`; native recipe `native/dude/README.md`.
No sibling edits, installs, downloads, training, commit orpush. Next quality step:
persistent roomgeometry/support across localmapwindows + offline roomGT benchmark;
not silently included as verified semanticroomaccuracy in this task.

Final frozen gate: `PYTHONPATH=src QT_QPA_PLATFORM=offscreen OPENBLAS_NUM_THREADS=1
OMP_NUM_THREADS=1 .venv/bin/python -m pytest tests -q -rs -m 'not native'`
exit0:2188passed/2skipped/9deselected/121.02s (`full-cpu-frozen.log`). Skips optional
Numba and explicit GPUraycastgate, native separatelychecked. Independent scoped
ACCEPT `review/review.md`/`native-audit.json`/`final-source-hashes.json`:4findings
resolved; scope excludes semanticroomaccuracy/Room→Objectcompleteness/P10. Final
387functionalpins unchanged, diffcheck0, point_cloud.py unchanged. Implementation,
CPUcorrectness and boundednativewiring validation completed within statedscope.

### Graph links and occupancy map controls — 2026-10-31

User requests Room–Object/Room–Room lines and occupancy zoom/pan. Implemented:
shared display relation projection keeps assigned membership and adds accepted
current room adjacency as cyan dashed lines in 3D/2D; structural only, no robot
passage certificate. Deduplicated, visible-node bounded, stale/cross-floor and
unavailable links suppressed. Exactly three node kinds retained; canonical
membership and measured RGB-D/Object XYZ unchanged. Missing membership remains
explicit rather than guessed.

Map: cursor-anchored wheel zoom, all-button drag pan, double-click Fit; one world
transform for raster/regions/route/robot/camera with viewport clipping. Manual
world camera persists over source updates/moving origins/resize; resets at new
episode/domain. Review's ROBOT-label clipping finding reproduced RED then fixed.

Correctness-verified: new graph7pass/map6pass exit0; final focused123pass/4.79s/exit0
across15UI/map/navigation/publication/cloud test files. Independent scoped ACCEPT:
75focusedpass +8extra probes exit0, no unresolved findings. diffcheck0. Actual Qt
synthetic fixture render0, images inspected. Runtime-validated scope is Qt event
handling/rendering only; no new native/GPU run, performance or semantic-room-quality
claim. Prior local room-window/unassigned Object limitation persists.

Artifacts `.runtime/graph-links-map-controls-20261031/` (RED/GREEN/final logs,
rendered PNGs, source hashes and independent review). Plan
`docs/graph-links-map-controls-plan.md`; report
`docs/results/graph-links-map-controls-2026-10-31.md`; controls in
`docs/spatial-scene-ui.md`. No install/download/training/siblingwrites/commit/push.
Restart demo to load new UI: `bash tools/run_map_demo.sh 00861 300`.

### Whole accumulated occupancy map — 2026-10-31 correction

User clarifies zoom/pan must reveal all mapped history, not just the moving local
robot window. Implemented: every canonical dirty integration cell feeds bounded
immutable2D overview history across active3D tile eviction. Classification matches
localNav gates, unknown stays unknown; reset clears. UI-only full-extent raster
built off navigation/control lane, <=1million cells with conservative coarsening;
4096tile state budget/sticky incomplete indication. New typed MapOverview/source
Nav metadata, optional backward decoder, exact local robot binding/separate ages.
Local control/room snapshots remain unchanged. UI Fullmap/Focusrobot buttons,
world zoom/pan and both global/local-focus views preserve manual chosen location.
18UI script pins refreshed.

Correctness-verified: mapping20pass0; integrated139pass/19.76s0. Independent59pass0
and provider blocking/failure/provenance probes0; Focusrobot wheel bound issue RED
then fixed. Initial fullCPU2209pass2fail retained; splitter layout and overbroad
projection instrumentation corrected, original regression suites17pass/1.46s0.
Final frozen fullsuite result follows. diffcheck0; actual archived native Qt render0.

Runtime evidence: once45s GPU/wall56.38s/exit1/outcomeincomplete solely resource
monitor RSSread_errors1; runtimefailed{},794frames/9commits, cleanUI0drops/errors,
392pins unchanged during run. Global101×135@5cm=6.75×5.05m vs local81²=4.05²m;
4769knowncells,1126outsidefinallocal (789free/337occupied),267firstknownoutside
remainknown.46sampledoverviews complete=true/no parseerrors. Data-path component
validated; whole native/P10 acceptance NOT claimed. Desktop button-row layout
and projection test are the only post-native functional-pin deltas.

Artifacts `.runtime/global-map-view-20261031/`,
`runs/demo-global-map-view-45s-20261031/`; report
`docs/results/global-map-view-2026-10-31.md`, plan `docs/global-map-view-plan.md`.
Current limits: historical display, bounded/coarsened at large extent, room worker
still local (this does not fix room membership), native overall incomplete as above.
No installs/downloads/training/siblingwrites/commit/push. Restart demo to load UI.

Final frozen gate: `PYTHONPATH=src QT_QPA_PLATFORM=offscreen OPENBLAS_NUM_THREADS=1
OMP_NUM_THREADS=1 .venv/bin/python -m pytest tests -q -rs -m 'not native'` exit0,
2211passed/2skipped/9deselected/121.33s (`full-cpu-final.log`). Skips optionalNumba
and explicitGPUraycastgate. Independent post-delta22tests0/1.59s, scopedACCEPT
retained;392finalpins recorded, only2declaredpostnative deltas; finaldiffcheck0.
Wholemap display implementation and CPUcorrectness verified; actualnative-data
view validated withincomponent scope, whole45srun remainsincomplete/RSS1.

### Recent DuDe room-cut audit — 2026-10-31

User asks whether recent demos actually cut geometry into multiple rooms.
Read-only audit, no implementation/config changes. Final artifacts from local
070220/map00802 and070734/map00805 each contain one region, at region revisions
934/map935 and734/map735 respectively. Both native room inputs remain81x81@.05m
(4.05x4.05m). Full accumulated overview is UI-only; coordinator still feeds local
NavSnapshot into RegionBackend/RegionGrid. Room persistence/support over the whole
explored floor remains unimplemented as noted in earlier checkpoints.

Correctness/evidence verified: exact startup binary SHA matches current local
worker; strict saved contract decode. Two isolated cold CPU-native final-grid
queries exit0, both success/accept_incremental/kernel_invoked=true/one rawregion,
not fallback/reused in these probes. Historical inputs only, no live control,
sensor/GPU/pipeline run. This does not reconstruct live incremental history.
No full per-request region/rejection history is persisted, so no claim that
intermediate output was always one region. The00805 run's whole failure is body
pose stale, not recorded region-worker death; neither run certifies room quality.
Current local binary differs from separately patched GPU recipe; no causal
one-region claim from that difference. No threshold tuning or invented Room nodes.

Artifacts: .runtime/dude-audit-20261031/{audit.py,audit.log,result.json,report.md,
worker/}. Command in report, exit0; diffcheck0. Implemented: audit/report only;
runtime-validated scope: two cold native region requests. Whole-floor semantic
rooms, persistent geometry/membership and room-GT quality remain unproven.

### Accumulated room input fix — 2026-10-31

User authorizes implementation following the above audit. Implemented separate
region-lane full-resolution room NavSnapshot from immutable raw measured history,
not coarsened UI overview; local control/safety snapshot unchanged. Exact mapper
robot/source/frame/clock/floor/calibration binding, FREE-only floor support and
float64 historical clearance lower bound. Raw4096tile/16MiB and dense1Mcell bounds;
missing/stale/incomplete/oversized history yields stale/unavailable, no silent
crop/coarsen. Native reset on origin/res/shape changes retains Python canonical
tracking against accumulated geometry. Room/floor/edge historical scope and
extent, bounded request/raw-count/status/reset/rejection telemetry. Place admission
remains local/fresh; historical published paths have no motion certificate.

Correctness-verified: initial118focused0/11.77s; final accumulated/cadence22pass0/
4.93s. Independent P06 ACCEPT:53map/runtime+30display+16post-fix+6post-fixture
tests0, native controlled two-room rerun0. Startup local-unavailable provenance
finding fixed and scope pinned atomically with nav/region pair; deterministic
interleaving regression added. Frozen final fullCPU2229passed/1skipped/9deselected,
exit0/175.58s (`full-cpu-final-verified.log`). Prior full gate1execution-proof
failure/isolatedfailure retained; its20ms capture fixture wrapper alone now1s,
all real-source/seed/resolution/nativefalse assertions unchanged, no runtimeTTL
change. Main52proof/wiring0 and independent1test0; sharedhelper remains20ms.

Native CPU controlled geometry: expansion1->2chambers, actual cut/separatecenters,
stableleftIDoutsidecurrentrightlocalwindow, FREE->occupied removesleftregion at
samebounds,12assertions exit0; inspectedPNGs. Additional origin(-.05,-.05) pad/reset
keeps worldgeometry overlap>0.999999,exit0. Synthetic counts are not roomGT quality.

Runtime-validated: once60s Intel/CPU map00805, exit0/completed/errornull,435frames,
215acceptedregions/1initialnofree,14native resets,cleanworkers/noobservererror or
sampled capbreach. Accumulated room76x101@.05m vslocalcontrol81², samefinal source/
revision;175knownoccupiedcells retained outside local, no freeoutside in this run.
Travel lowerbound.52448m/aggregateactuationcompletefalse,2objectcommits/noassigned
membership. Real final1region: no claim of realmultiroom/semanticaccuracy/coverage/
P10/latency certification. Native thresholds and assets unchanged.

Artifacts `.runtime/accumulated-rooms-20261031/` (logs/nativefixtures/PNGs/review/
live-result.json/sourcehashes), `runs/demo-accumulated-rooms-60s-20261031/`;
plan `docs/accumulated-room-map-plan.md`, report
`docs/results/accumulated-rooms-2026-10-31.md`. Preflightreadytrue/exit0,diffcheck0.
No downloads/training/siblingwrites/commit/push/publish. Restart demo to apply,
e.g. bash tools/run_map_demo.sh 00805 600. Source input limitation from prior audit
is fixed; full-map room quality still requires sufficient measured coverage and
independent evaluation.

### Stable Room layer implementation started — 2026-11-02

User authorizes tentative/confirmed/disputed Room identity separate from DuDe,
portal/door/structure evidence, revisable boundaries and split/merge lineage;
first scope is stable segmentation/debug UI only. No room-guided navigation.
Three Luna6.0High workers own new policy, composer integration, and UI respectively;
main owns shared coordination/docs/verification. Earlier dispatches hit usage
limits before source writes; retry now, no claimed implementation/test pass yet.
Baseline HEAD9b90d317 plus existing accumulated-map edits preserved, including
user orchestration file. Plan docs/room-stability-plan.md. No downloads/training/
sibling writes/commit/push authorized or performed. Final evidence/limits pending.

### Stable Room policy + UI final checkpoint — 2026-11-02

Implemented: separate temporal RoomOwner (tentative/confirmed/disputed), source-bound
transactional evidence history, stable IDs despite proposal-only DuDe changes,
held aggregate/split/merge with shared-boundary evidence + predecessor/events,
optional committed door corroboration and independent metric occupancy portal
candidates. Door not mandatory; portal not passage proof. Source association
ambiguity is explicit, stale/rejected updates do not refresh confidence, caps
publish unavailable. New measured cell/class support is not multi-view evidence.
UI adds Room stability tab and accepted-vs-DuDe geometry in map/3D with reasons,
support/lineage; original zoom/orbit/splitter/popup retained. Raw-region object
membership and control/safety unchanged. Thresholds conservative/provisional;
axis-aligned portals, exact partition recurrence and250kcell policy cap limits.

Execution: initial Luna6.0High scaffold/integration/UI; main found core structural
state-machine invariants unresolved, escalated only core refinement to TerraHigh.
Independent LunaHigh review43focused+10probes0, then12cadence follow-up0; no Astra.
Intermediate full CPU failures preserved:12map-only helper failures,2GTstartup/
splitter failures,1frozenclock-fixture timeout. Fixed product bugs and deterministic
fixture correction; no GTnormalization, TTL/cadence or assertion weakening.

Correctness-verified final frozen wholeCPU2260passed/1skipped/9deselected exit0,
167.48s: `.runtime/room-stability-20261102/full-cpu-complete.log`. Single skip is
explicitGPUauthorizationgate; native9 not claimed pass. Final11source/test/tool
hashes verified, diffcheck0. Archived actualmap216/76x101 source passed Room repeat
invariance, UI wire roundtrip and inspected offscreen rendering; one tentativeRoom.

Runtime component smoke: sandbox first30s attempt failed sensorstartup whole-op
deadline before seedACK/graph, retained. Separately approved outside-sandbox30s
map00805 completed exit0/errornull/227frames/cleanworkers, one real object commit,
non-stale source112 Roompublication with one tentativeRoom/support1. No causal
sensorfix from boundarychange; no assignedmembership/multiroomquality/coverage/
latency or overallnative/P10 claim (native_runtime_validated remainsfalse).
General accepted-update scheduler independence and multi-view confirmation unproven.

Report docs/results/room-stability-2026-11-02.md; design docs/room-stability-design.md;
artifacts `.runtime/room-stability-20261102/`, original native run
`runs/demo-room-stability-30s-native-20261102/` and failed sandbox run retained.
Preflight00805readytrue0. No installs/downloads/training/siblingwrites/commit/push.
User orchestration edits and prior accumulated-map changes preserved. Restart demo
for UI/policy; `bash tools/run_map_demo.sh 00805 600`.

### Rebuild M4/M5 backend + hidden portals — 2026-11-02

User explicitly authorizes runnable Rebuild room-backend comparison and temporarily
hiding P tentative; conserve tokens, one Luna6.0High implementer, main independent
backend review/UI/verification. Actual readonly Rebuild source M4 worker + source
M5 guard/tracker now selected via workers.region.backend=rebuild_m4_m5/source_root;
source M5 is canonical region owner, transactional validation preserves accepted
source pair on rejection, native-only extent reset retains M5 identity. Pinned
worker7868c892... and50-file source aggregate60aebf8a...; private imports/no sibling
bytecode writes. Same accumulated measured occupancy, original source preprocessing,
not a full OctoMap/RGB-D mapping replacement. Baseline backend retained.

Portal overlays and list entries hidden by default in map/3D/Room stability;
Portals(debug) toggles them. Selected mode visible in subtitle/actual_profile.
Command `bash tools/run_rebuild_map_demo.sh 00805 600` (or --preflight); wrapper
uses existing local runner environment, generates ignored pinned profile. No source
sibling edits/model downloads/installs/training/commit/push. Prior dirty work kept.

Correctness-verified final wholeCPU2267passed/1skipped/9deselected exit0/148.19s;
8finalcode/test/wrapperhashes unchanged, diffcheck0. Actual cold native equalinput
comparison: savedmap486 gives1vs1region/matchedIoU.7587; map1682 gives2vs2/.8618,.9234;
synthetic chambers+corridor3vs3/IoU1.0. Different binary AND preprocessing, so no
isolated kernel-quality claim. Unknown remains unknown in control; source outlines
can extend at unknown boundary. No historical incremental replay/GTquality claim.

Runtime component validated: approved native00805Rebuild30s completed0/errornull,
254frames/cleanworkers/125accepted of130requests,14extentresets;1initialno-free+
4non-simplepolygonrejections retainedoldgeometry. Finalmap130,76x101@.05,1M5region/
1tentativeRoom; exact externalworker/source/policy in telemetry, no silentfallback.
Overallnative_runtime_validated remainsfalse, no P10/semanticaccuracy/coverage or
performancecomparison claim. RoomOwner remains separate and can hold native splits.

Artifacts `.runtime/rebuild-backend-20261102/`, native run
`runs/demo-rebuild-00805-30s-20261102/`; design docs/rebuild-backend.md and
report docs/results/rebuild-room-backend-2026-11-02.md. Intermediate wrongtestpath
exit4 and legacyworkerconfig KeyError95-testfail retained; fixed lookup without
weakeningtests. Fullfinal run above is sole whole-suite pass claim for this change.

### Full Rebuild RGB-D room branch plan — 2026-11-02

User requests detailed plan BEFORE implementation. Wrote
`docs/rebuild-full-room-pipeline-plan.md`: R0–R8 source/caller audit, versioned
geometry-map contract, RGB-D adapter, isolated persistent Rebuild M1–M5 session,
bounded admission/replay, runtime/hierarchy/UI/export/runner, source parity and
fixed A/B/C comparison. Primary RGB-D baseline, control/downward lane unchanged;
M3 display distinct from control map, source M5 visible before Stable Room policy.
Original ObjectOwner retained, no second semantic/object ID owner. Pin M2/M3
binary61747752... plus currentM4/source closure; no fabricated NavSnapshot safety
fields, no GT mapping, no fallback hidden behind Rebuild label. LunaHigh default,
escalation by reproduced technical risk; independent frozen review gates.

Verification: read-only source inspection + executable existence/hash only;
document diffcheck recorded below. No implementation/native/demo/benchmark/
install/download/training/source-sibling edits/commit/push. This planning request
does not authorize executing R0–R8; previous M4/M5 smoke/tests not reused as pass
for the new RGB-D branch. Missing runtime/quality evidence explicitly planned.
Plan document verification: `git diff --check` exit0; no product tests run because
this task changes documentation only. Artifact: the linked detailed plan.

### Read-only full Rebuild plan progress audit — 2026-11-02

Historical snapshot from before the subsequent user authorization to implement.
Its findings describe that earlier checkout and are superseded by the current
checkpoint at the top of this file and the audit response linked there.

User requests status/issues review, tests if needed; no product implementation.
Current workspace has added R1contracts/R2adapter/R3worker+session/R4roomlane/
R5separateUI+export/R6runner since original plan-only checkpoint. R0–R6 partial,
not all gatesclosed; R7nativeoracle/ABC and R8integratedlive remainopen. Existing
native1frame synthetic smoke not equivalent to integrated Habitat live.

Fresh focused47passed/9.33s exit0; runner00805preflight readytrue/issues[] exit0;
private probes exit0 reproduce publiccontract allowing acceptedM3future revision
(latest1,accepted2,fresh) and replay_requiredtrue withfreshregions. Not claimed
observed in native live. R5doesnot consumeRebuildregions inhierarchy/membership,
Controlmap defaulttab and legacyregionlane remain; acceptedoldM3 raster notretained
inDTO, oldregions safelyomitted fromnewmap. CumulativeOctoMapcap/parity/review gates
unproven. Plan§8/status prose stale vs implementation files. No product/testsource
changes or new simulator/native campaign; previous dirtywork preserved.

Artifacts `.runtime/rebuild-rgbd-progress-audit-20261102/{report.md,focused.log,
preflight.log,probes.py,probes.json}`. Commandsexits inreport; diffcheck0. Next steps
are findings toresolve upon authorization, not silently performed during audit.


### Kiet_branch2 / Hydra — map/control cadence sau khi defer overview — 2026-11-05

- **Implemented:** NavSnapshot được publish ngay sau core map update; tile overview và room input tùy chọn chạy sau publish. Không có region worker thì bỏ hẳn tạo room tiles. Freshness 300 ms và guard footprint/clearance không đổi.
- **Correctness-verified:** focused suite: `./.venv/bin/python -m pytest tests/test_runtime_scheduling.py tests/test_navmap.py tests/test_runtime_measurement_wiring.py -q` — 67 passed, exit 0.
- **Runtime-validated:** same-profile UI-on smoke 30 s exit 0; artifact `.runtime/hydra_ws/artifacts/hydra-cadence-overview-publication-00805-20261105/ui-on-30s/`. `navmap_update` p95 164.1 ms; control wait p95 164.9 ms (baseline 196.9/198.0 ms). Freshness remains 300 ms. One pending remains at final frame while map update is in flight; body lower bound 0.765 m. Recording 238/238 and Hydra export revision 7 complete; UI sequence 67 rendered; clean shutdown. 7 zero-motion/expired outcomes remain, and GPU resource sampler is unavailable, so resource boundedness and long-run behavior remain unproven.
- **Next gate:** inspect/resolve control-before-map-start scheduling at terminal frame and maintain verified counter/resource evidence; do not infer readiness for 60/120/300/600 s from this 30 s confirmation.
- **Detailed result and cadence audit:** `docs/results/hydra-branch2-navigation-recovery-00805.md` and `.runtime/hydra_ws/artifacts/hydra-cadence-overview-publication-00805-20261105/ui-on-30s/cadence-smoke-audit.json`.


### Kiet_branch2 / Hydra — pending do run deadline — 2026-11-05

- **Root cause:** capture cuối có thể trả về sau run deadline; exact navigation wait bị cắt ở `run_deadline`, nhưng launcher cũ vẫn gọi `control_step()` dù map worker chưa publish source đó.
- **Implemented:** không phát control sau khi duration hết; ghi source vào `run_deadline_skips` riêng, không giả là executed/pending. Freshness gate 300 ms, map exactness và safety không đổi.
- **Correctness-verified:** test đỏ trước sửa, xanh sau sửa; `tests/test_long_runtime.py` — 22 passed. Tập focused rộng hơn: 104 passed, 3 test UI SHA cấu hình fail do hash cũ trong YAML so với script hiện tại (ngoài thay đổi).
- **Runtime-validated:** cùng profile/scene/seed/UI, smoke 30 s exit 0; terminal frame 132 được ghi thành một `run_deadline_skip`, wait 0.018 ms, map worker bắt đầu 0.8 ms sau wait và publish khoảng 189.5 ms sau đó. Không gọi control thiếu map ở ranh giới duration. Recording 243/243, export revision 8, UI 71 rendered, shutdown sạch.
- **Remaining:** còn 3 in-run `navigation_source_pending`, depth age 301.4–306.1 ms; `navmap_update` p95/max 187.1/339.4 ms. Freshness gate đang chặn đúng các source quá hạn. Chưa đủ điều kiện chạy dài hơn; GPU resource sampling cũng chưa khả dụng.
- **Artifact:** `.runtime/hydra_ws/artifacts/hydra-run-deadline-control-skip-00805-20261105/ui-on-30s/`; chi tiết tại `docs/results/hydra-branch2-navigation-recovery-00805.md`.


### Kiet_branch2 / Hydra — phân rã pending 27/92/131 và thử tối ưu raycast — 2026-11-05

- **Offline diagnosis:** frame 27 có sensor roundtrip/decode 72.1/91.3 ms và capture→map-start 165.2 ms; map update 187.1 ms. Frame 92: sensor 30.6/11.5 ms, dispatch 42.5 ms, map 279.7 ms. Frame 131: sensor 31.4/11.7 ms, dispatch 43.6 ms, map 339.4 ms. Raycast 109.4/166.3/195.3 ms; core vote integration 125.3/58.5/65.7 ms. Frame 27 nghiêng về sensor/dispatch; 92/131 nghiêng về raycast/map core. Age 301–306 ms vượt gate 300 ms đúng cách.
- **Implemented / experiment:** đã thử stride 2 chỉ trên free-space ray traversal, giữ endpoint/floor hits; mặc định vẫn stride 1. Offline 133 recorded frames giảm map update p95 143.3→73.5 ms, raycast p95 114.4→37.3 ms và không tạo FREE evidence mới so với baseline.
- **Correctness/runtime decision:** focused mapping suite — 56 passed, exit 0. Nhưng UI-on smoke 30 s với stride 2 dù hoàn tất recording 349/349, Hydra export rev1/UI final seq61 và shutdown sạch, có 0 accepted commands, 227 `expired_or_zero` (`robot_not_on_observed_free_cell`), translation lower bound 0.0 m. **Ứng viên bị bác bỏ cho runtime**; không nâng cấp thời lượng và không đổi freshness/footprint gate.
- **Resources:** RSS 421 mẫu; GPU/VRAM theo process chưa có provider hữu dụng. Artifact `.runtime/hydra_ws/artifacts/hydra-free-ray-stride2-00805-20261105/ui-on-30s/`. Báo cáo phân rã và lệnh kiểm chứng: `docs/results/hydra-branch2-pending-decomposition-00805.md`.
- **Next:** giữ stride 1; tối ưu raycast/core mà không loại evidence, chứng minh occupancy/bootstrap offline trước smoke 30 s kế tiếp. Chưa có bằng chứng cho run 60/120/300/600 s.


### Kiet_branch2 / Hydra long-demo readiness — 2026-11-05

- **D0 implemented:** durable profile `configs/demo-00805.hydra-long-demo.local.json`, current SHA `3170649c387e3770265f2895137a4574b1968a59043a9d252bf65625ad6aafcd`; preflight ready/issues[] exit0. UHD check returned OpenVINO `['CPU','GPU']`; `xdpyinfo :0` connected.
- **D1 implemented/correctness-verified:** Hydra native 3D positions/edges and layer counts feed SpatialSceneWidget; measured RGB-D cloud comes from exact recording source. Bounded incremental source index and final graph flush were added; final rendered artifact source matches graph source at 0 ns lag. Focused tests: 85 passed. Screenshot: `.runtime/hydra_ws/artifacts/hydra-readiness-D1-00805-20261105/ui-on-30s-final-verified/ui-screen.png`.
- **Runtime-validated 30s:** `.runtime/hydra_ws/artifacts/hydra-readiness-D1-00805-20261105/ui-on-30s-cloud-flush/`, completed/error null; 265/265 recording, Hydra export revision8, UI sequence62, 146/146 proofs, 1.024m translation lower bound, clean shutdown. Control interval p95 377.7ms; NavMap update p95/max146.3/243.5ms; one `expired_before_step` at frame28/301.1ms; 10 `expired_or_zero` zero-motion outcomes; no `navigation_source_pending`. RSS377/377; GPU memory provider unavailable.
- **Runtime-validated 60s:** `.runtime/hydra_ws/artifacts/hydra-readiness-D1-00805-20261105/ui-on-60s-cloud-flush/`, completed; 515/515 recording, graph revision16, UI sequence127, 276/276 proofs, 2.237m translation, clean shutdown. One `navigation_source_pending` at frame283/depth303ms (1/291=0.34%); control interval p95 360.8ms; map update p95/max158.9/301.3ms. RSS615/615; GPU memory provider unavailable.
- **120s not passed:** `.runtime/hydra_ws/artifacts/hydra-readiness-D1-00805-20261105/ui-on-120s-first-gated/`, CLI exit1 and `outcome=incomplete`, although recording986/986, Hydra revision29, UI sequence242, export and shutdown succeeded. There were 3 in-run pending sources (depth301.6–331.4ms), 3 expired-before-step events, 16 zero-motion outcomes, 6/546 freshness misses (1.10%), and translation lower bound4.539m. Control interval p95 rose mildly to388.5ms; map update p95/max148.5/295.9ms, with raycast/vote tails up to184.4/179.2ms. Three run thirds showed map-update p95/max144.2/241.6 →150.3/281.4 →155.4/295.9ms.
- **Incomplete cause:** one RSS sample (1030/1031 supported) exhausted three trials after `FileNotFoundError` while reading a `/proc/<pid>/task/<tid>/children` path for a thread that disappeared. Implemented a narrow check that ignores only a vanished task directory while retaining process identity and the full second census. Resource/proc focused suite: 88 passed, exit0; runtime validation remains outstanding.
- **Latency experiment:** NavMap intrinsics/pixel-lattice cache preserved exact recorded snapshot output; on 58 frames p50 preflight 13.588→12.738ms, p95 14.356→14.734ms, so it does not clear the tail. Offline raycast-worker A/B on80 recorded frames had identical snapshot SHA; four workers were fastest (update p50/p95/max126.3/137.7/143.2ms). Keep stride1/workers4; do not relax 300ms freshness.
- **Next:** validate RSS fix with bounded30s, continue D2 map-core tail investigation, then repeat60/120 only after gates pass. Two clean120s runs are still needed before300s. No300/600 or second-map run was attempted. The full suite baseline was2436 passed/10 skipped/32 failed before these edits and has not been rerun after them.
- **Detailed checkpoint:** `docs/results/hydra-long-demo-readiness-2026-11-05.md`; current gate ledger: `.superpowers/sdd/hydra-long-demo-readiness-plan-2026-11-05/progress.md`.


### Hydra ObjectNav roadmap implementation checkpoint — 2026-11-06

- **Implemented:** A1 shared Hydra graph visibility for 2D/3D; A2 immutable revision-pinned evidence contracts/index and query seam; B1 observed-place support extraction and offline room partition evaluator; C1 offline source-bound control-stage attribution.
- **Correctness-verified:** focused UI 26 passed; evidence/query/session 34 passed; room quality/GT isolation 17 passed; measurement evaluator 86 passed; `git diff --check` exit 0. These are focused checks only, not a repository-wide suite.
- **Runtime-validated from existing artifacts only:** A2 probe reloaded an existing 00805 `.sparkdsg`: manifest/hash match; 4 objects had valid bounding boxes and mesh support indices into a finite 6,379-vertex mesh. Cross-revision mesh-index stability and pose-correction history are unverified. B1 extracted 34 place points assigned to one room; no independent annotation was present, so room quality is unavailable. C1 analyzed an existing 60s trace (6,668 stage records, complete, 0 unbound): NavMap update p95/max 209.97/290.15 ms; core integration 149.24/218.30 ms; raycast 88.29/186.30 ms; control navigation wait 210.55/275.82 ms; primary sensor roundtrip 158.56/225.16 ms. Nested intervals overlap and are not additive.
- **Not implemented / not proven:** A2 detection sidecar and current-revision geometric association; A3 asynchronous object evidence gallery; A4 pure ObjectNav contracts/approach/verification; B2/B3 room text-label context/worker/UI; C2 process isolation; C3 profile accounting and live ladder. No new simulator run, live UI screenshot, detector/model download, model inference, or actuator change was made. C2 native actuation remains behind independent safety review; current session policy disallows subagent delegation, so that review has not been obtained.
- **Read scope:** inventoried 145 package Python files and 199 test files; read the full affected modules and their contracts/call paths for the implemented slices. A literal line-by-line read of all repository code is not complete and is not claimed.
- **Artifacts and ledger:** `.superpowers/sdd/2026-11-06-hydra-objectnav-roadmap/progress.md`, `runs/hydra-objectnav/A2/capabilities.json`, `runs/hydra-objectnav/B1/room-quality-00805-60s-NEW.json`, `runs/hydra-objectnav/C1/profile-control-stages-00805-60s-NEW.json`.
- **B2 added after this checkpoint:** bounded text-only `RoomContext` and revision-pinned `RoomLabelProposal/Result` contracts, with stale/invalid/insufficient-evidence abstention. Focused B2/query checks: 15 passed. No model asset or inference runtime was found; B3 does not run a real SLM. A1 native UI smoke remains unavailable in this session because `xdpyinfo -display :0` exited 1, so no screenshot/runtime validation is claimed.

### Room SLM pilot — S0/S1 checkpoint — 2026-11-08

- **S0 implemented / correctness-verified:** checked all 17 entries in `docs/baselines/hydra-room-slm-pilot-2026-11-08.lock.json`; all byte counts and SHA256 values match. HEAD `62f16fcf0b1ae508b49820e0184e99714387c490`, branch `Kiet_branch2`; baseline worktree was already dirty at 297 paths, manifest SHA `4a2bf1cd34e690bee9f4e0452ebf29503ea05f62164852181d87a91b24d8544b`. Kept existing dirty content.
- **S0 inventory:** `runs/room-slm-pilot/S0/{baseline-check,inventory}.json`. i5-13420H, 12 logical CPUs, ~6.88 GB available RAM, ~1.99 GB swap already used. No Qwen3-1.7B GGUF, llama.cpp executable/runtime, `llama_cpp` Python binding, or Qwen1.7B cache found in checked workspace/worktree locations. Official Qwen source is Apache-2.0, model repo lists 4.08 GB; no exact official Q4_K_M GGUF artifact was pinned, so converted output size remains estimate 0.9–1.2 GB and must be measured. No download/install occurred. A historical 00805 replay revision has a loaded Hydra library SHA matching the geometry lock; it is not current pilot runtime evidence. No user-supplied 00807 run.
- **S1 implemented:** immutable request identity binds episode/run/native room/revision/prefix/geometry/context/world epoch; relations are direct parent edges from the same Hydra projection; rooms with no objects still receive host-abstain requests. Publication envelope checks exact full key. `validate_room_label` maps `invalid_output` to `invalid`, requires nonempty support with assigned membership, and abstains for unavailable/truncated contexts. No graph/native geometry mutations.
- **S1 correctness-verified:** RED captured at `runs/room-slm-pilot/S1-red.log`; final focused command `./.venv/bin/python -m pytest tests/test_room_label_requests.py tests/test_room_context.py tests/test_room_label_contract.py -q` — 19 passed, exit 0 (`runs/room-slm-pilot/S1-final.log`). Runtime-validated: not applicable; no SLM/worker call.
- **S2 onward:** not yet implemented. Model/runtime asset gate remains unavailable; continue offline prompt/adapter/rule baseline, backend failure fixtures, annotation protocol/evaluator and fake-worker/service correctness. Do not connect live UI until offline quality/resource gates are evidenced.

### Room SLM pilot — S2 checkpoint — 2026-11-08

- **S2 implemented:** deterministic English prompt with pinned schema and categories drawn only from the request's canonical taxonomy; includes object IDs/categories, assigned membership, association status, evidence count and only native parent relations. Prompt never includes episode/run/room IDs, coordinates, labels/GT or raw untrusted class strings. Token count must fit exact budget (max 3072); truncation, stale/missing geometry and unavailable object support produce typed `insufficient_evidence` before model invocation.
- **Strict adapter:** exact JSON field set; no prose repair; bounds alternatives≤2, support≤8, reason≤256 chars, response≤16 KiB; validates canonical labels, known IDs and assigned membership. Host assigns room/revision/context/model/prompt hashes. Malformed or unsupported replies become `invalid_output`. Baseline `room-label-rules-v1` uses explicit semantic anchors only and abstains for weak/contradictory evidence; it is not ground truth.
- **Correctness-verified:** RED at `runs/room-slm-pilot/S2-red.log`; final focused command `./.venv/bin/python -m pytest tests/test_room_label_requests.py tests/test_room_context.py tests/test_room_label_contract.py tests/test_room_label_prompt.py tests/test_room_label_adapter.py -q` — 39 passed, exit 0 (`runs/room-slm-pilot/S2-focused.log`). Hashes/schema are in `runs/room-slm-pilot/S2/pinned-hashes.json`.
- **Runtime-validated:** none. Fixtures and rule baseline tests do not establish SLM semantic quality; no model/runtime available, no detector-backed semantic evaluation set established. S3 subprocess backend/config fixtures remain next; S4/S6 offline contracts can proceed, but live UI is gated.

### Room SLM pilot — S3 offline snapshot / S6 protocol checkpoint — 2026-11-08

- **S3 implemented:** local-only CPU `llama-server` adapter, disabled-by-default config, strict prompt/schema and `tools/infer_room_labels.py`; no remote fallback. Snapshot builder binds request identity to native room IDs, graph revision/prefix, graph/config/build/source/taxonomy hashes and native membership. Calibration ID uses the profile/revision ID when present; for this locked profile, which has no separate calibration ID, the request records a deterministic ID derived from the native calibration hash. The snapshot records that visual object evidence is not present.
- **S3 correctness-verified:** subprocess fake-server tests are in `runs/room-slm-pilot/S3-green.log` (6 passed, exit 0); CLI fixture test `runs/room-slm-pilot/S3-cli-green.log` (1 passed, exit 0). Snapshot/revision tests and relevant contracts passed as part of the fresh combined command below. Real model/runtime inference was not possible: Qwen3-1.7B GGUF and llama.cpp are absent and remain unpinned. No download or install was performed.
- **Asset follow-up:** official `Qwen/Qwen3-1.7B-GGUF` is Q8_0 (1.83 GB) and does not publish Q4_K_M; the official Transformers repository is 4.08 GB. The plan's Q4_K_M target therefore needs a permitted conversion or a deliberate quantization change. The 0.9–1.2 GB Q4 size remains an estimate. Official llama.cpp documents Linux installation/build routes; no runtime was installed. See the pilot report for the constraint.
- **S3 runtime artifact validation:** built three immutable requests from native 00805 replay graph revision 45 at `runs/room-slm-pilot/S3/00805-r45/`; each has 12, 1, and 1 native semantic object(s), all three contexts are untruncated and membership-assigned. On identical contexts, rules v1 returned one `unknown` (contradictory anchors) and two `insufficient_evidence` abstentions; the disabled SLM backend returned `unavailable:model_runtime_disabled` on all three. This validates snapshot/dispatch/result provenance only, not model quality. The source run is detector-backed according to the pinned run metadata, but this graph snapshot contains no reviewed image/object association evidence or room GT, so it cannot score room-label accuracy.
- **S6 implemented / correctness-verified:** frozen annotation protocol at `docs/results/room-slm-pilot-annotation-protocol-2026-11-08.md`; evaluator handles one selected context per physical room, multi-label references, missing annotations, geometry unavailable, distinct-context flips, support validity, coverage/selective accuracy/macro F1/confusion, latency and RSS fields. Synthetic correctness tests are in `tests/test_room_label_evaluation.py`; these are evaluator tests only, not semantic quality evidence. No annotation manifest or quality score exists yet.
- **Fresh verification:** `PYTHONPATH=.:src .venv/bin/pytest -q tests/test_room_slm_backend.py tests/test_room_label_evaluation.py tests/test_room_label_snapshot.py tests/test_room_label_requests.py tests/test_room_label_contract.py tests/test_room_context.py tests/test_hydra_scene_graph_query.py tests/test_room_label_prompt.py tests/test_room_label_adapter.py tests/test_room_slm_cli.py` — 64 passed, exit 0. The first combined run exposed and fixed a nested-tokenizer deadline call; this passing rerun covers the fix. `git diff --check` — exit 0. S2 pin artifact refreshed at `runs/room-slm-pilot/S2/pinned-hashes.json`; model/runtime/tokenizer/template hashes are explicitly null.
- **Not implemented / not proven:** S4 bounded async worker/service is gated on offline quality/resource results; S5 UI/live shadow is gated and remains unconnected. S6 final scoring is blocked by model/runtime assets and reviewed annotations (target ≥12 physical rooms / ≥3 scenes). No real SLM inference, latency/RSS measurement, or quality comparison ran; no UI or live worker integration claim.
- **Pilot report:** `docs/results/room-slm-pilot-2026-11-08.md` consolidates outcomes, source snapshot limitations and exact next gates. No changes to default profiles or external source repositories.

### Room SLM pilot — image audit, CPU runtime and real inference — 2026-11-08

- **S1 implemented:** `tools/audit_room_object_visual_association.py` verifies native graph and RGB-D recording hashes, projects native mesh support through recorded calibration/pose into depth, and emits per-object overlays/contact sheets. The visual annotation draft is `runs/room-slm-pilot/S1/annotations/image-reviewed-room-labels.json`. It contains 7 labeled physical-room candidates across 3 scenes, 4 distinct contexts and 1 eligible semantic sample; target 12 independent rooms is unmet. Visual labels are an AI-agent draft, not human ground truth. It records observed wrong associations (`00805 O(0) bed→sofa`, `O(21) wardrobe→door`), merged 00805/00806 `R(0)` contexts, and the incomplete outer certificate on 00807 bathroom evidence.
- **S2 implemented/runtime-validated:** official `Qwen/Qwen3-1.7B` revision `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e` downloaded, converted locally to F16 GGUF then Q4_K_M (1,282,439,168 bytes; SHA256 `9954a72ab369f967d40520ea5fd161485bf82593f9050ae8a93528e90aa4163f`). Official llama.cpp `b12189` commit `80d2c0c2c56e4a1bbf74be98f64b99927bf230bc` built Release/CPU/OpenMP; server SHA256 `39810101b9c23983133c660f6ec1ca96188d989b1e87cba66026f813645939cb`. All model/tokenizer/template/runtime input and binary hashes are recorded in `runs/room-slm-pilot/S2/model-runtime-lock.json`; enabled settings are run-scoped in `runs/room-slm-pilot/S2/qwen3-1.7b-q4km-cpu.json`. Shared experimental config remains disabled.
- **S3 runtime-validated, quality gate failed:** 5 real CPU single-thread calls across 5 immutable contexts/3 scenes, paired to the rules baseline on the exact same request. Outcomes: SLM 3 timeout / 2 invalid / 0 accepted labels; baseline 1 available / 2 unknown / 2 insufficient evidence. The 00807 living-room baseline proposal follows the `bed` semantic ID, which the image audit shows on a sofa; this is an association error, not a valid correctness score. Latency p50/p95/max `60.95/62.25/62.25 s`; sampled child RSS `2.55–2.57 GB`; 5/5 subprocesses launched and shut down cleanly. Artifact `runs/room-slm-pilot/S3/real-inference-summary.json`; one raw invalid response diagnostic at `runs/room-slm-pilot/S3/00805-r45/real-inference/request-001-raw-diagnostic.json`. No room-label quality metric is reported because there is only one eligible annotation and its inference timed out.
- **Correctness verification:** first regression run reproduced `launched=false` in a timeout despite child RSS samples. `src/neusymnav/rooms/slm_backend.py` now keeps `last_metrics` attached to the active request metrics; test asserts timeout retains `launched=true` and clean shutdown. Final command `PYTHONPATH=.:src .venv/bin/pytest -q tests/test_room_slm_backend.py tests/test_room_label_evaluation.py tests/test_room_label_snapshot.py tests/test_room_label_requests.py tests/test_room_label_contract.py tests/test_room_context.py tests/test_hydra_scene_graph_query.py tests/test_room_label_prompt.py tests/test_room_label_adapter.py tests/test_room_slm_cli.py tests/test_room_object_visual_association.py` — 66 passed, exit 0. An earlier run with `PYTHONPATH=src` had 3 collection errors; corrected with repository root included. A subsequent run briefly failed the CLI fixture because the shared config had been enabled; enabled config was moved to the run artifact and shared config restored disabled, then the full focused command passed.
- **Not implemented / not proven:** S4 asynchronous worker and S5 UI/live remain gated; real output failed with timeouts/invalid JSON and annotation target is unmet. No default profile, Hydra geometry, exploration, movement, freshness gate, command horizon or external source repository changed.
- **Final verification:** lock verifier checked 12 model/tokenizer assets and 3 runtime binaries, zero mismatches, exit 0; shared config `enabled=false`. `git diff --check` — exit 0. Focused test command above — 66 passed, exit 0.
- **Report:** `docs/results/room-slm-pilot-2026-11-08.md`.

### Real-time navigation, privileged tour and Hydra room checks (00806 benchmark) — 2026-11-09

Session log and per-run numbers: `docs/results/realtime-navigation-tour-2026-11-09.md`, `docs/results/room-slm-latency-2026-11-09.md`. 00806 is the benchmark scene from now on (`configs/demo-00806.hydra-tour-slm.experimental.local.json`).

- **Implemented** (all opt-in through config unless stated):
  - SLM compact-v2 prompt + semantic cache.
  - World/goal-selection age and intent TTL split.
  - `runtime.process_priority`.
  - Privileged navmesh tour (`navigation.tour`), with relaxed targets, approach, frontier fallback, route-length progress window, motion-aware stuck timer, goal gates and in-place scans.
  - Real-time pulses (`pulse_ms` / `rotation_pulse_ms`). The worker / host proof caps changed: worker SHA pins updated in 15 Kiet_branch2 profiles.
  - `gil_switch_interval_ms`, `overview_refresh_s`, `build_overview` fast path.
  - Hydra graph-lane state-token polling (default for every Hydra profile).
  - `keyframe_novelty`.
  - Polygon room GT `docs/results/gt/00806-rooms-gt-v1.json` and `tools/evaluate_rooms_vs_polygon_gt.py`.
  - `navigation.controller.start_unknown_tolerance`: implemented; **enabled only in `demo-00806.hydra-tour-slm` (0.2) by explicit owner decision 2026-11-09**, disabled elsewhere. It treats UNKNOWN cells inside the robot's own current footprint as FREE, which relaxes the "unknown ≠ free / missing depth blocks motion" invariant and needs an explicit owner decision.
- **Correctness-verified:**
  - New tests: `tests/test_navmesh_tour.py`, `tests/test_realtime_navigation_profile.py`, `tests/test_realtime_pulses.py`, `tests/test_gil_overview_throttle.py`, `tests/test_hydra_poll_cache.py`, `tests/test_tour_goal_gates_and_scan.py`, `tests/test_start_footprint_tolerance.py`, `tests/test_quantized_yaw_preflight.py` (cap 3° → 15°).
  - Container full suite: same 85 environment failures as the untouched baseline; no new failure.
- **Runtime-validated (user machine):**
  - Live runs v3–v8 on 00806.
  - v7/v8: control ≈ 300 commands/min stable over 10 min, `local_depth_map` p50 57–117 ms, 33.5 m in 600 s, tour coverage 76 %.
  - Room check v8 vs GT v1: west room / bedroom 2 recovered; bedroom 1 split; bathroom and hallway merged.
- **Not proven:**
  - Run v9 (gates/scans/denser Hydra input) was stopped by the user after the robot froze. Cause: one UNKNOWN cell in its own footprint blocked planning and the guard, including rotation.
  - Gates/scans and denser Hydra input therefore have no live result yet.
  - Hydra room parameters for small rooms are untested.
  - SLM label quality is unscored.
- **Update (evening) — tolerance disc mismatch fixed:**
  - Live v10 (600 s) ran without freezing (26.3 m, tour coverage 71 %), but four later runs with the same code/config (v8.1, v9.1, demo-00806-600s-live, live1) froze at (-5.94, 0.46).
  - Cause (reproduced on three real snapshots): the local follower and world planner tolerated a footprint disc padded by 0.75 cell, the guard map and guard bootstrap an unpadded one. The follower planned through a cell the guard still saw UNKNOWN, so every forward pulse was refused (`path_segment_blocked`, v9.1: 335×; `bootstrap_blocked` 52×) and the small heading error never triggered a rotation.
  - Fix (owner-approved 2026-11-09 19:58): one helper `start_footprint.tolerate_robot_footprint` (disc radius = radius + margin + 0.75·resolution) used by world planner, local follower, `MotionGuard.bind_nav` and `NavMapper.bootstrap`. The exception widens from 0.25 m to ≈ 0.29 m around the body; OCCUPIED in the disc and the 0.2 fraction cap still disable it, the swept corridor must still be measured FREE.
  - Correctness-verified: `tests/test_start_footprint_tolerance.py` (+2 tests, fixture `tests/fixtures/start_footprint_00806_guard_mismatch.json`; the new live test fails on the previous guard). Container full suite: identical 85 environment failures before/after.
  - Runtime-validated (v11, 600 s, user machine): passed the former freeze point in ≈ 2 s; no freeze; 28.3 m, tour coverage 0.770, 225–377 commands/min. Bathroom dead end still skipped (cause open); Hydra still merges hallway + bathroom at the end of the run (3/5 GT rooms).
