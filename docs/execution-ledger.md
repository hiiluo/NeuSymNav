# Execution ledger — docs/implementation-plan.md

## Authorization and method (2026-10-27)

User explicitly requested execution of the documented merge plan. Core P00–P10 authorized; extensions, training, large downloads, source modifications, commit/push/publish excluded. Main owns shared contracts, dependency/config integration and status. Delegation follows agent-orchestration.md (Luna xhigh inventory, Sol high semantic implementation/review).

Workspace is the user-designated NeuSymNav directory. `.git` is an empty read-only directory; `git status --short` exits 128. No Git history/worktree/checkpoint scripts available. Evidence uses file hashes and logs; do not initialize Git or modify `.git`. No commits authorized.

## Interface preflight

| Producer → consumer | Shared interface | Resolution |
| --- | --- | --- |
| P00 → all | host/runtime paths, source hashes | lock after import probes, never import sibling runtime source |
| P01 → P02/P03/P04 | Observation, FrameKey, geometry, clock | architecture §4 binding; readonly arrays, Z-up/optical/axial |
| P02 → P03/P04 | calibrated observations and replay | secondary depth sensor navigation only; separate source keys |
| P03 → P06/P07 | NavSnapshot and freshness | floor support/clearance explicit; regions pin source map |
| P04 → P05/P06/P07 | CommitResult, objects, aliases | single object owner, durable complete-empty batch |
| P05 → P07 | AppearanceBatch | exact source/hash/space match before attach |
| P06 → P07/P08 | HierarchySnapshot | accepted pinned map, latest nav separate; stale memberships unavailable |
| P07/P08 → P09 | runtime, display publication | renderer read-only/process isolated from control |
| P09 → P10 | exports, config/provenance | no sibling source access; native gates require actual runtime |

No contradictory interfaces found in current spec/plan. Missing native capabilities block runtime validation only; continue independent fixture correctness without claiming native parity.

## P00

Owner: p00_inventory (gpt-6-luna/xhigh); main owns scaffold/import isolation.
- RED: `/usr/bin/python3 -m pytest tests/test_import_isolation.py -q` → 1 failure, expected missing package (`runs/p00-main/import-red.log`).
- Host: Python 3.12.3; system NumPy/SciPy/pytest/setuptools available. Default venv creation failed missing ensurepip. Created `.venv` with `--without-pip --system-site-packages`; no system environment changed.
- Installed cached wheel 0.48.0 from local uv archive into local venv (no download); `uv --no-cache pip install --python .venv/bin/python --no-build-isolation --no-deps -e .` → 0 (`runs/p00-main/install.log`).
- GREEN: `.venv/bin/python -m pytest tests/test_import_isolation.py -q` → 0, 1 passed (`runs/p00-main/import-green.log`), subprocess uses isolated interpreter and arbitrary cwd.

## Task self-consistency scan

| Task | Tests vs implementation/files | Finding |
| --- | --- | --- |
| P00 | Named tests, interfaces and deliverables compared against task brief | No internal contradiction; runtime tests conditional on audited assets, correctness gates remain mandatory |
| P01 | Named tests, interfaces and deliverables compared against task brief | No internal contradiction; runtime tests conditional on audited assets, correctness gates remain mandatory |
| P02 | Named tests, interfaces and deliverables compared against task brief | No internal contradiction; runtime tests conditional on audited assets, correctness gates remain mandatory |
| P03 | Named tests, interfaces and deliverables compared against task brief | No internal contradiction; runtime tests conditional on audited assets, correctness gates remain mandatory |
| P04 | Named tests, interfaces and deliverables compared against task brief | No internal contradiction; runtime tests conditional on audited assets, correctness gates remain mandatory |
| P05 | Named tests, interfaces and deliverables compared against task brief | No internal contradiction; runtime tests conditional on audited assets, correctness gates remain mandatory |
| P06 | Named tests, interfaces and deliverables compared against task brief | No internal contradiction; runtime tests conditional on audited assets, correctness gates remain mandatory |
| P07 | Named tests, interfaces and deliverables compared against task brief | No internal contradiction; runtime tests conditional on audited assets, correctness gates remain mandatory |
| P08 | Named tests, interfaces and deliverables compared against task brief | No internal contradiction; runtime tests conditional on audited assets, correctness gates remain mandatory |
| P09 | Named tests, interfaces and deliverables compared against task brief | No internal contradiction; runtime tests conditional on audited assets, correctness gates remain mandatory |
| P10 | Named tests, interfaces and deliverables compared against task brief | No internal contradiction; runtime tests conditional on audited assets, correctness gates remain mandatory |

Briefs copied verbatim to `runs/implementation/p00-brief.md` through `p10-brief.md`. Git-dependent skill scripts inapplicable to empty read-only `.git`; file snapshots/reports used instead. Local plan overrides generic skill commit/review/model rules.

P00 main gate: 2026-10-27, `.venv/bin/python -m pytest tests/test_import_isolation.py tests/test_inventory_sources.py tests/test_preflight.py -q` → exit 0, 7 passed. Final P00 audit185 selected source records; P01 taxonomy source appended →186. Main checked hashes and tools behavior. P00 correctness_verified; runtime capabilities pending, source/asset licenses recorded unresolved. No native/model/simulator workload. Host locked `.venv/bin/python` Python3.12.3 system numerical packages; separate worker envs pending user-reviewed install proposal.

P01: implemented43 focused tests /50 whole suite exit0; main independently reran43 pass. Snapshot `runs/p01/review-package.md`; independent SolHigh reviewer `p01_review` running, schema not yet locked. Static59-category source taxonomy reused with explicit aliases and literal raw exact matching; source hash recorded central manifest, no GT-derived vocabulary.

P01 fix round1: reviewer found scalar strings/maps accepted as character/key event IDs by string_tuple; main independently reproduced. Implementer added regression RED45 failures ->GREEN85 pass; tuple/list guard minimal fix. Independent scoped rereview approved (`runs/p01/scoped-rereview.md`). Main `.venv/bin/python -m pytest tests -q -m "not native"` → exit0,135 passed. Schema v1 LOCKED for dependent tasks; hash snapshot `runs/p01/fix-round1-hashes.json`, exact signatures `runs/p01/api.txt`. P01 correctness_verified; native/runtime not validated.

P02 dispatched SolHigh `p02_sensor_replay`, owns sensors/recording/tests only, contracts readonly. User supplemental instruction: search existing runtime envs read-only, keep worker environments independent; if missing propose before installing; no new models/dataset. Environment audit/proposal completed; no additional env found. Continue CPU code and correctness; no new dependency installs authorized.

P02 main gate: `.venv/bin/python -m pytest tests/test_replay.py tests/test_sensor_adapter.py -q` → exit0,25 passed. Main reviewed wire array bounds, calibrated transforms, recorder/certificate/quota and replay clocks. Worker full suite160 pass exit0. Report/hashes `runs/implementation/p02-report.md`, `runs/p02/snapshot-sha256.json`. Correctness_verified, native/runtime pending; native entrypoint exit1 explicit missing habitat_sim. Added4 missing source files at P02 port to manifest ->190 selected; existing recording files already pinned by directory roots. Low-level step/reset requires actuator-side MotionCommand guard in P07; source_frames is forensic and never enters control. Aggregate run8GiB quota remains P07 responsibility.

P03/P04 dispatched in parallel after P02 CPU gate. Separate writers: p03_navigation SolHigh mapping/navigation/config-navigation/tests-nav; p04_objects SolHigh perception/objects/config-perception/tests-objects. Shared contracts remain main-owned locked. No install/download/GPU/native simulator job authorized. P04 independent reviewer mandatory after stable snapshot.

## Resume checkpoint — 2026-10-27

User requested continuation. Previous P03/P04 workers are no longer active; no P03/P04 implementation files or reports were present at resume. The previous P03 dispatch reported a usage limit before producing implementation. Redispatched as `p03_navigation_resume` and `p04_objects_resume`, both explicit `gpt-6.1-sol`/`high`, with the same disjoint ownership and locked schema. Both acknowledged source/contract inspection; no claim of completed P03/P04 yet.

Main baseline: `.venv/bin/python -m pytest tests -q -m 'not native'` → exit 0, **160 passed**. SHA-256 verification of all **190/190** selected source records matched the pinned inventory. Evidence: `runs/resume-20261027/baseline-tests.log`, `runs/resume-20261027/source-integrity.json`. No environment installation, model/dataset download, GPU workload or source modification performed.

Continuation was interrupted while P03/P04 workers were running; workers did not persist. P03 writer resumed as `p03_finish_checkpoint` (Sol High). P04 code was stable with focused29 pass; main reran focused command exit0 (`runs/p04/main-focused.log`), captured16-file hash snapshot and API signatures, assembled implementation report, and dispatched independent `p04_independent_review` (Sol High). P04 remains implemented, not correctness_verified until review findings are resolved. The concurrent full-suite failure is in a P03 test fixture whose height-bin shape did not match its mapper; P03 is diagnosing and fixing within its ownership.

Main captured tested host version constraints in `configs/host-constraints.txt` (no installation; not a wheel-hash lock), corrected concatenated interpreter/version paths in provenance, and added the actual local CLIP tokenizer API requirement to the runtime environment proposal. These metadata edits do not change source snapshot hashes or authorize installations.

P03 main gate: fresh `.venv/bin/python -m pytest tests/test_navmap.py tests/test_navigation.py -q` →37 passed, exit0;19/19 stable file hashes verified (`runs/p03/main-hash-verification.json`). Main read planner/grid/controller/guard and mapper changes against explicit bootstrap/footprint/freshness limits. P03 correctness_verified for recorded CPU profiles; native floor/noise/low-obstacle tolerance and actuation remain pending. The bare Habitat step must not be used as a validated pulse: P07 must enforce deadline/domain and actual action displacement at the actuator.

P04 review/fix gate: original reviewer rejected partial-final asset write and missing taxonomy. Main reproduced OS SIGXFSZ death/retry failure; regression RED then temp/fsync/atomic no-replace publication GREEN. Round1 reviewer reproduced missing directory fsync when reusing an asset published immediately before death. Main added reuse barrier regression and reran the owner-level independent probe RED2 then GREEN32. Scoped round2 independent SolHigh approval:31focused+7probes,16current/13unchanged/9source hashes. Sources and shared contracts untouched. P04 correctness_verified; ordered graph-thread stream and staging-file quota are P07 integration preconditions. Reports preserve rejected snapshots rather than rewriting their outcomes.

Whole main integrated gate after both stable: `.venv/bin/python -m pytest tests -q -m 'not native'` →228 passed, exit0, `runs/resume-20261027/integrated-p03-p04.log`. Central inventory extended190→194 with simulation/controller, mapping/raycast_kernel, perception/yoloe and perception/local_text pinned at P03/P04; prior190 hash matches checked before extension. Generator retains these roots and corrected interpreter/version metadata. No native/model/GPU workload run.

P05/P06 dispatched after these gates, four disjoint writers. `p05_feature_adapter` Luna xhigh owns perception appearance worker/client, contract tests/config; `p05_owner_appearance` SolHigh owns object appearance/store/association and association tests. Additive off/openclip profile remains off by default, preserves legacy off ledgers; geometry+visual score excludes extra label/track terms to isolate appearance ablation. Feature aggregation ports ConceptGraphs count-weighted normalized update with fixed vector+count and unique accepted detected events, not an arbitrary voxel-derived weight cap. Crop adapts source20px context to tight mask bounds (no locked bbox field), pins this difference into feature space and records lack of bbox-extent parity. Caller validates full feature batch before filtering unprojectable detections for strict attach helper.

`p06_regions_hierarchy` SolHigh owns regions/hierarchy/CPU tests; `p06_native_build` Luna xhigh owns native/vendor closure, build tool and opt-in native tests. Native worker wire remains protocol1 and preprocessing extended_unknown_boundary; one -j1 build, no concurrent native benchmark/GPU workload. Existing local dependency prefix may be read explicitly; no installation/download authorized. Source-built parity pending actual execution. P05 scoring and P06 gate will receive independent SolHigh reviews on stable snapshots.

P06 native audit corrected P00's FIST notice attribution: the actual restrictive text is in `Third_Party/dude_final/FIST/makefile:943`, not the paper-citation parent README. Main read both files, updated notices/generator/license evidence, pinned the makefile SHA and added its source record (194→195; previous194 hashes checked unchanged). Regression command `.venv/bin/python -m pytest tests/test_inventory_sources.py::test_fist_notice_uses_bundled_makefile_instead_of_paper_readme -q` initially exit1 (no correct notice selected); after correcting lookup, inventory/preflight7 tests pass exit0 (`runs/resume-20261027/provenance-notice-tests.log`). No permission/redistribution conclusion is inferred.

### Integration obligations to carry into P07/P09

- Create/use SQLite ObjectOwner in its one graph thread/process; accepted batches dispatch chronologically. Recovery restores persisted watermarks before admitting more frames. Historical projections use their actual capture geometry, never the latest pose.
- Bare P02 `step(action)` does not implement guarded actuation. P07 must enforce live clock/deadline/source at the actuator and bound actual displacement/yaw to the certified pulse; Habitat's default discrete action magnitude must not silently exceed P03's speed × horizon. Expired zero commands and guard exceptions mean stop.
- P03's 5cm near-ground band is explicit but unvalidated native; no physical low-obstacle safety claim. Navigation-depth coverage must be measured at the real scene calibration before native campaign.
- Recompute source age at consumer/publication/actuation boundaries; `temporal_status` recorded at object-commit entry is not a forever-fresh certificate after slow disk or worker delay. Historical/expired negatives cannot affect current verification.
- P05 full batch appearance validation precedes filtering unprojectable IDs for strict attachment; missing/cancelled features use geometry baseline, and feature attachment never creates detection/identity votes.
- P06 keeps one in-flight map and one accepted source map. Composer uses accepted map/region revisions while displaying latest-nav lag. Retained stale geometry cannot generate fresh membership.
- Aggregate run disk admission includes raw recordings, SQLite/WAL, assets, orphan staging files, tile archives and pending accepted refs; object asset staging bytes cannot disappear from quota accounting.
- ReplayReader currently creates a new replay domain per instance. CLI/recovery must not claim replay-process resume against an old object ledger until explicit replay session/clock restoration is implemented and tested. `source_frames()` remains forensic and must not bypass replay-domain safety in runtime.

## P05/P06 resume and review checkpoint

User requested continuation. Prior adapter/P06 reviewer hit usage limits and native metadata worker reported application network permission revoked; subsequent explicitly requested continuation resumed the same workers without changing model policy or using network workarounds. Main retained existing files and resumed exact remaining scopes.

P05 owner independent SolHigh acceptance:4 scoped hashes+4 sources,49 focused tests,11 adversarial probes and1,000 aggregate/200 scoring oracle comparisons pass (`runs/p05-review/review.md`). Adapter's original14tests missed pipe backpressure: main reproduced256x256 request stalled beyond1s despite timeout0.1s (`runs/p05-main/write-stall-repro.json`). Writer captured RED then changed to nonblocking selector writes/reads with operation deadlines and bounded process-group cleanup. Current18 focused tests pass in writer evidence; main combined P05+P04 focused67 pass exit0. Separate SolHigh IPC review `p05_owner_review` now audits this stable adapter snapshot; P05 gate remains open until disposition.

P06 original independent review rejected non-simple polygon fresh publication, bool/float protocol versions and surviving TERM-ignoring descendant. Main independently reproduced polygon acceptance (`runs/p06-review/main-self-intersection-repro.json`). Writer RED8fail then GREEN38focused; fix moves simple-ring validation into a shared region predicate before wire/backend/tracker acceptance, requires exact integer protocol version and always kills owned process group even after leader exit. Per-ring1024vertices cap precedes quadratic geometry work; global geometry caches removed. Stable fix snapshot `runs/p06/fix-round1/snapshot.json` preserves original19file snapshot and11source hashes. Independent SolHigh scoped rereview underway; native synthetic accepted map1/latestnav4 smoke rerun, not a real-scene quality claim.

Native source closure metadata5duplicated basename paths corrected;89/89 original+vendored byte hashes main verified, manifest `d827de8eb85b96f0c54cf9d900175e32b7b255611ac624be6596a63ef710e8d8`, binary remains `c03c10d71a28e8fa7a2943de5d6d75cdad962d20101209e8e1c844645b7c366b`. Incremental serial build exit0; main native3tests pass exit0 (`runs/p06-native/main-native-tests.log`). Correct FIST notice refs included; no install/download. Central source manifest195→197 adds selected crop source and Fusion config schema; prior195 hashes unchanged.

Main integrated CPU command `.venv/bin/python -m pytest tests -q -m 'not native'` → **303 passed,3 deselected,exit0** (`runs/resume-20261027/integrated-p05-p06.log`). Deselected3 are the separately executed native tests. Source integrity197/197 matched (`source-integrity-p05-p06.json`). Review gates remain distinct from this test result; P07 not yet opened.

P05 lifecycle fix final independent acceptance: `runs/p05-ipc-review/scoped-rereview.md`, stable20-file followup manifest,5sources+4owner hashes unchanged. Original startup/close repro now closes in0.101s with no worker/request thread. Independent long-Popen before/after-spawn cases explicitly require `AppearanceShutdownPending`, terminal closed state and eventual late-child reaping. Main69focused pass exit0 (`runs/p05-main/final-focused.log`). Main suite excluding2in-progressP08files305pass3deselected exit0 (`p05-p06-post-lifecycle.log`). P05 correctness_verified; nativeOpenCLIP still missing; appearanceoff remainsbaseline. Reviewer corrected original report's manifest count typo15vs16; no evidence silently changed.

P06 independent fixround1 acceptance read bymain, all3originalfindingsclosed,38focused+source/analytic oracles; native89source/vendorhashes and3native tests main verified. P06 correctness_verified and bounded synthetic native protocol exercised; no real-scene graph quality/robot/runtime acceptance.

P07 dispatched only after P05/P06 gates: SolHigh `p07_runtime` owns runtime scheduler/workers/health/coordinator/quota/config+runtime/failure tests; SolHigh `p07_verification` owns committed verifier/bestviews/negative and verificationtests; SolHigh `p07_sensor_detector_ipc` owns additive sensor guarded execute/source-bound robot pose and detector client/worker+newtests. Shared schema/deps/status remain main-owned; no sources/GPU/install/download. P08 Luna xhigh owns only visualization/UI/tests/runningguide in parallel after P06; main integration pending.

P07 admission clarification: submit(None-return) is bounded nonblocking reservation/offer, not a durability ACK. Counts distinguish offered/reserved/durableaccepted/committed. Durable acceptance follows atomically written source+SQLitejournal; accepted refs remain until graph+verifier ACK and are recoverable. Scheduler32MiB includes in-flight and recorder-reserved items, not an extra hiddenqueue. Age250ms start gate controls fast eligibility; historical durableaccepted frames can infer later and must not be dropped merely for age. Source age is rechecked before current consumers and actuation. Runtime must honor pending shutdown exception and report unresolved cleanup rather than is_aliveFalse-based success during spawn gap.

P08 main review: first7focused/offscreen passed, but main found testfixture encoded verifier `verified` as ObjectState.lifecycle, violating the separation of identity lifecycle and support verification. Worker preserved rejected report/hashes in `runs/p08/rejected-review-20261027`, added Qt-free DisplayVerificationSnapshot/Record/Evidence boundary and revision checks, rendered active+verified versus active+unverified separately. Main fresh `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_display_snapshot.py tests/test_ui_offscreen.py -q` →10passed exit0; visually inspected corrected synthetic screenshot. P08 implemented/display correctness scoped; runtime ACK/P09 transport and real display remain pending. `xdpyinfo :1` exit1, no workaround or real-display claim. Two source presentation files added to central inventory197→199; prior197 hashes unchanged.

P07 detector worker profile is explicit Python>=3.12 because it loads actual package contracts/YOLOE adapter; main updated the reviewed environment proposal, without installing anything. Sensor/appearance standalone worker environments remain separate. P07 runtime constructor floor identity must be explicit; no native detector-to-fixture fallback. Main noted initial hierarchy composition under shared lock could block fast control; writer moved composition/copy validation outside submit/control lock before review.

## P07 continuation — 2026-10-27

User requested continuation. Live agent inventory contained only main; previous P07 verification writer had ended before report/stable hashes, and runtime had no final report. Resumed exact remaining scopes as `p07_runtime_finish` and `p07_verification_finish`, both Sol High with disjoint ownership. Stable IPC handoff exists at `runs/p07-ipc/snapshot.json`; independent Sol High `p07_ipc_review` assigned only that scope. P07 gate remains open until all stable scopes and independent review disposition; P09/P10 not started. No repeated native build/benchmark, installation, model/data download, commit or sibling source modification.

Main fresh `.venv/bin/python -m pytest tests/test_sensor_actuation.py tests/test_detector_worker.py tests/test_sensor_adapter.py -q` → **54 passed, exit 0**, log `runs/p07-main/ipc-focused.log`. This is CPU/stub/subprocess correctness evidence, not actual Habitat/model execution. Main extended central inventory199→200 with New `runtime/process_detector.py` already cited by IPC report; all previous199 hashes unchanged (`runs/p07-main/source-integrity.json`). `.venv/bin/python -m pytest tests/test_inventory_sources.py tests/test_preflight.py -q` → **7 passed, exit 0**. Existing audited asset/runtime metadata preserved.

P07 stable runtime/verifier checkpoints now available: runtime `runs/p07-runtime/snapshot.json` (`fc7afdeb32c292c5b6356c992b89a0cb8eacc5c74edc91f15d3d7003f9b56721`), verifier `runs/p07-verification/snapshot.json` (`da30a9c8bab44583971bd7035ab7162d4ce1977dd7a0146c519e8f8916849b02`). Both writers stopped. Main fresh integrated focused command `.venv/bin/python -m pytest tests/test_runtime_scheduling.py tests/test_verification.py tests/test_failure_recovery.py tests/test_display_snapshot.py tests/test_ui_offscreen.py -q` → **87 passed, exit0**, log `runs/p07-main/integrated-focused.log`. Independent SolHigh `p07_runtime_verifier_review` assigned fixed scopes. Worker reports whole437pass/3native-deselected; main does not substitute that for final post-fix integration gate.

Independent IPC review REQUEST CHANGES: source TTL only checked before actuator preparation (295ms+10ms reaches305ms at step); JSON/sensor decode can successfully return past operation deadline. Main reran actual review repro → same305ms movement and17.48ms response against1ms parse deadline (`runs/p07-main/ipc-review-reproduction.json`, exit0 reproduction). `p07_ipc_fix` SolHigh owns only IPC modules/related tests; original snapshot preserved, fix-round1 evidence required. Current P03 MotionGuard clamp already blocks paired command, but independent worker guarantee still needs correction. P07 remains in_progress.

P09 handoff obligations: provide separate UI process publication/command transport, actual RGB/best-view tagged image loading (runtime DTO currently carries evidence tags), config asset/runtime path resolution+checksum verification, explicit replay-session clock restoration before any resume claim. Optional external asynchronous verifier requires bounded graph-thread inbox if enabled; current committed-view baseline does not silently create an external verifier worker. No P09 implementation before P07 review disposition.

Main fresh integrated CPU smoke: copied frozen smoke harness into `runs/p07-main/integrated_cpu_smoke.py` with only fresh output directory changed, then `.venv/bin/python runs/p07-main/integrated_cpu_smoke.py` → **exit0**. Artifact `runs/p07-main/cpu-run/`: detector calls[0,1,2,3,4],five unique committed views/three independent,active graph lifecycle+verified support,matching pause ACK,clean shutdown. Harness explicitly declares `fixture_cpu_no_models` and `native_runtime_validated=false`; no native/useful-core claim. Main hash verification11runtime-owned+10verifier-owned files match frozen snapshots (`runs/p07-main/frozen-scope-integrity.json`).

P07 IPC fix-round1 stable snapshot `8082f8e2cce6713952e66c5adf9929c5fcc39a80bb64ad40e71aac4af32b810b` accepted independently for spec+quality (`runs/p07-ipc-review/fix-round1/scoped-rereview.md`):32hashesbefore/after,64focused+39independent regressions+positiveoriginalscenarios pass. Main positiveconfirmation `.venv/bin/python runs/p07-ipc/fix-round1/confirmation_probes.py` →exit0 (`runs/p07-main/ipc-fix-confirmation.json`); mainwholeCPU `.venv/bin/python -m pytest tests -q -m 'not native'` → **446passed,3deselected,exit0**,44.01s (`runs/p07-main/post-ipc-fix-cpu.log`). Source+caller minimum deadline enforced; decoding overrun rejects rather than returning expired capture (synchronous decode/cleanup can finish after timeout; no hard preemption claim).

Independent runtime/verifier review found2negative freshness failures beyond existing tests. Main reproduction `PYTHONPATH=tests .venv/bin/python -m pytest runs/p07-integrated-review/test_adversarial.py -q` →2failed2passed exit1 (`runs/p07-main/runtime-review-reproduction-fixed-harness.log`). Initial invocation without tests module path failed collection exit2 and is preserved separately. Frozen snapshot initially captures now before slowSQL then credits expirednegative; runtime recovery disablesfast output but still ordinary verifierconsume can credit currentnegative. P07 remains in_progress until minimal fixes and scoped re-review, despite fullCPU446passing.

Runtime/verifier review original source scope explicitly frozen after113record hash audit and main-confirmed2findings; reviewer instructed finish original report from retained bytes/evidence, list any unreviewed portions. Main resumed `p07_runtime_finish` for combined minimal fix-round1 in coordinator/verifierledger+theirtests only; one writer. Preserve all original manifests. Additive historical-consumption seam allowed without changing locked ObjectOwner.commit/schema; consumers unable to handle historical replay must fail closed. Final negative freshness must be checked after I/O/query/gallery work, not merely move initial clock read. Correctness gate still open and requires scoped re-review plus any coverage explicitly outstanding from original reviewer.

P07 runtime/verifier fix-round1 MAIN ownership: interrupted prior resumed writer while no changed files/evidence existed, then main took coordinator/verifierledger/tests only. Original independent report finalized (`runs/p07-integrated-review/review.md`), no original-scope coverage pending. Main added four SQL/gallery timing regressions plus recovery regression: first run had missing fixture import; corrected harness yielded **5 meaningful failures** against original production (`main-red-valid.log`). Minimal fix →5pass; original independent4probes→4pass. Additional later-object gallery fixture initially had future capture and correctly failed source validation; corrected declared timestamp, production unchanged. Final focused90pass exit0; wholeCPU **453pass3deselected exit0**,42.46s (`runs/p07-runtime/fix-round1/cpu-suite.log`). Source6/6+oraclebyteparity pass; all200central sourcehashes unchanged.

Ruling: currentnegative final proof recheck retains at most17selected independent records/object afterSQL/gallery, expires before return and adjusts beta. If selectedproof expires and previouslybaseline-excluded neighbor could qualify, conservatively undercount untilnextsnapshot ratherthanretainunboundedhistory/reviveexpiredcredit; cost temporarynegativecredit loss. Existingcapunknown remains conservative. Additive `consume_historical(commit)` keepspositivevotes/emptybatch/negativehistory withoutcurrentcredit; unsupportedhistoricalACK failsclosed withpending/replayrequired. LockedObjectOwner.commit andschemas unchanged. Stable4changed/17unchanged-owned manifest `runs/p07-runtime/fix-round1/snapshot.json` SHA6a81193f71cfa3fd11c3238ab24c4334e568951a289a79eaabc1098ef6ef7213, report `runs/implementation/p07-runtime-fix-report.md`; scopedindependent originalreviewer resumed. No P09 beforedisposition.

Gate P07 closed as correctness_verified after both independent scoped ACCEPT reports. Main read runtime/verifier fix acceptance, fresh6adversarial probes rerun→6pass exit0 (`runs/p07-main/runtime-fix-independent-confirmation.log`); allrequiredfullCPU453pass/3native-deselected and200sources unchanged. P08 correctness_verified for offscreen/typedpublication/actualruntimeACK; separateprocess transport is P09, realdisplay native pending. 9/11implementation+correctnessgates nowclosed; no nativepipeline/runtimeacceptanceclaimed. Open P09 only now.

P09 dispatch after acceptedP07/P08: `p09_launcher` SolHigh owns runtime/configuration.py,launcher.py,ui_transport.py +additiveReplayReadersessionrestoration, baseline/geometry-only/appearanceconfig, launcher/UI/sessiontests; selectedHighforIPC/clockrecovery. `p09_cli_isolation` Luna xhigh owns thincli.py,verify_package.py,CLI/isolationtests,docs/running.md. PubliclauncherAPI locked: preflight(config_path)->dict ready, run(config_path,*,duration_s,out)->dict outcome, replay(input_path,config_path,*,out)->dict. CLIevaluate latebinds P10evaluate_suite(suite_path,*,out). Main ownsdeps/status/provenance. Schemaoutlineapproved; pathsconfig-relative+SHA, preservevenvargvpath despite symlink, calibratedfloorrequired, fixtureexplicitreplayonly, originalrecordhash validatedbefore replaygeometryhashrebinding, persistedsession/sourceinputhash forresume. UIversionedboundedno-pickle separateprocess; no nativeauto-fixturefallback.

Main pyproject declares existingPyYAML>=6,<7 core and optionalPyQt5>=5.15,<6 UI, noinstallation. ExistinghostNumPy1.26.4/SciPy1.11.4/PyYAML6.0.1/PyQt5 5.15.10 confirmed (`runs/p09-main/dependency-declarations.json`, exit0). No interpreter/environment installed; model/sensor/OpenCLIP availability unchanged. NativeP06binaryreuse onlyexplicitSHA asset. P09rawarchive shouldshareP07keyframesrawbudget2GiB; allrunoutput8GiB; blockingdiskworkkeptoffcontrol. CLIwriterreports17parser/calltests pass, actualisolatedfixture replaypendinglauncher.

P09 integration finding: P06 measured `HierarchyComposer.observe_place` exists, but acceptedP07runtimeconstructscomposer withoutrobot and hasno source-bound bodypose inlet, so onlineplacewiring absent. Main approvednarrow P09delta and explicitlytransferred solecoordinator.py ownership to `p09_launcher` (+newtests/test_runtime_places.py). Add bounded pendingpose1 pairedatomically WITHnavigationinput beforemapping, graphplacepair1 consumedonlygraphthread; exactkey/time/domain/poseversion/bodyXY source, no camerainference/replaybodyshortcut. Composer receivesexplicitmapper.robot; missing/invalidproof remainsunavailable. No sharedschema/hierarchyalgorithmchange. Newdelta mustreceiveindependentSolHigh P09review; P07acceptance referspreservedprevioussnapshot, notunreviewednewgeneration.

P09CLIcheckpoint:20focusedunitstests pass exit0; main actualCLI --help exit0. Luna report `runs/implementation/p09-cli-report.md` explicitlyimplemented/isolationpending; writerstoppeduntilSolstableinterface. Sourceonlycopiedfixture hascommittedobject+event/source expectedvalues; notmerelyemptybatch. Solreports13launcher/session/UItests pass incloffscreenactualdesktopchild+ACK; finalstrictconfig/quota/recovery/placeintegration stillpending. No native/model/runtimeacceptanceclaimed.

P09 continuation latest: launcherwriter hitusage limit beforefinalhandoff; liveagentinventoryconfirmed errored, maintookexclusivefiles. MainfreshP09suite60pass exit0, sourceonlyverifierexit0 exactcopiedfixture IDs/provenance/nolegacyreads, wholeCPU **513pass3native-deselected exit0**,46.58s (`runs/p09-main/resume/`). Main restored3newprofiletemplates fromunapproved640/CUDA to480/CPU consistentpreviousbaseline, no GPUavailabilityinferred. Baselinepreflightexit1readyfalse mandatoryfloorcalibration, asintended. Native/live/model/display remainunvalidated. Maincheckpointreport `runs/implementation/p09-launcher-report.md`,29filefrozenmanifest `runs/p09-main/resume/snapshot.json`. SingleindependentSolHighreviewrequest resumedcompletedreviewer `p07_runtime_verifier_review` forNEWP09scope; ifserviceusageunavailable no alternate-model/limitworkaround, retainpendinggate. P10notopened.

Additionalreadonlyhardwareevidence: PCI identifies RTX3060Mobile/Max-Q and AMD680M, kernelNVIDIA580.178.04 (`runs/p09-main/gpu-pci-readonly.txt`, `nvidia-kernel-readonly.txt`). NVIDIAdeviceaccess/nvidia-smi stillnotusable; VRAM/runtimebudgetnotverified. NoGPUjobor driver/environmentchange.

P09originalindependentreview REQUESTCHANGES (`runs/p09-review/review.md`):R1completedexportmap2/nav1 mismatch,P1;R2UIclose blockeddesktoplogfsync,P1;R3three staleUIworkerSHA,P2. Mainfreshoriginalprobes5fail1pass exit1 confirms all. Original29/29pre-review hashes; finalpackaging22/29 because mainfixesbegan afterreviewerconfirmedoriginalinvestigationcomplete; reviewerexplicitlyrecords7expecteddeltas, no claimunchangedoriginalafterfix. Advisorieseventsummary4096scope+wrongrunningguidepath; objectsjsonrepairfromDBpositivepassed, nofalsefinding.

MainP09fixround1: exactfinalepisode/object/map/clockcoherenceelseincomplete,no newhierarchy/navfiles; events_total/events_complete/events_scope added. UIasyncsinglefinalizerpersistsdiagnosticand releasesquota, boundedclosepending/errorhonest, nofalseclean andquotalockwaitoffcaller. Updated3templateUIhashes andrunningguideactualkeyframes/recording+rawbudget/scope. Main67focusedpass0,sourceonly0,200sourcehashesunchanged. CPU519passpre-finaldelta then520pass47.11final log; sessiontoolinterruption lostexitreturn, durableconfirmrerunlaunched (`cpu-confirmed.log`,`cpu-exit.json`), notinferredexit. New8changed21unchangedmanifest runs/p09-main/fix-round1/snapshot.json SHA9530ccf8bca83aa7ac67023f8e40429b6a1098a6a99969ec2756ffbb3f4f8054;report runs/implementation/p09-fix-report.md. Independentreviewerresumedscopedfixreview; allsourcewriterstopped. P09notcorrectness_verifiedyet,P10notopened.

P09 gate closed correctness_verified:independent fixround1 ACCEPT `runs/p09-review/fix-round1/review.md`,31/31hashesbeforeafter,67focused+12adversarialpass0,profileaudit3templates480CPU/hash/nulls. Mainfresh12independentprobespass0 (`runs/p09-main/fix-round1/independent-confirmation.log`). DurablefullCPUcertificateexit0 **520pass3deselected**,47.36s (`cpu-exit.json`,`cpu-confirmed.log`);sourceonlyverifierpass0 and200selectedsourcesunchanged. No scopedfindingsremaining. P09producerreportpendingexitstatement remainsimmutablepinned; certificate suppliesresult. Nativepipeline/realdisplay/qualityunvalidated. Open P10 onlyafterthisgate.

P10afterP09gate: SolHigh `p10_protocol` owns evaluation/protocol/metrics/GTisolation+suite/tests/harnessreport; Luna xhigh `p10_evidence_inventory` readonlyevidence/hashmatrixunder runs/p10-evidence only. Mainacceptancereport/status/deps/provenance owner. Publicevaluate_suite(suite_path,*,out) returnsoutcome; missingfailedtimeoutallplannedslotsindenominator; unsupportedmetricsnull, noGTinruntime, nativecampaignblocked missingdeps. NoGPU/envinstallation/download/legacycampaignstarted. Suitepilotonepinnedscene×2seeds, secondscenesupportincomplete, noeffectivemissing-sceneinventedslot. Mainfresh `.venv/bin/python -m pytest tests/native/test_dude.py -q`→3pass exit0 (`runs/p10-main/native-tests.log`,native-exit.json); thisonlyDuDe finiteprotocolsynthetic, notpipelineacceptance. READMEupdatedcurrentP00–P09/CLI/replaystatewithoutnativeclaim.

P10progress: protocolfocused18pass reported; same-session actualreplay objects/nav byteidentical, hierarchypublicationcounter nondeterministic. MainapprovednormalizationONLYrootHierarchySnapshot.revision forcanonicalcomparison; retainrawhashes/countervalues, canonicalIDs/aliases/allgeometry/evidence/otherrevisionsunchanged, regressionmutatedIDs/edgesmustfail. No blanketUUIDnormalization. Frozenone-scene2seednativepilotattemptsmissing/unattempted, completion0/2 notaccuracy0; no campaignlaunched. Evidenceinventoryfresh200/200source+89/89nativeoriginal/vendorhashes pass; fourinterpreterdependenciesmissing; report runs/implementation/p10-evidence-report.md pinsfullmatrixpendingprotocolartifactrefs.

P10faultaliascase foundactualQtbug: DashboardWindow.refresh selectedcanonicaloldID aftermerge aliasesit, _object_detail directlyindexesremovednode->KeyError. Main independentlyreproducedexit1 via QT_QPA_PLATFORM=offscreen PYTHONPATH=tests .venv/bin/python -m pytest runs/p10-protocol/fault_harness.py::test_alias_update_while_actual_dashboard_selects_object -q (`runs/p10-main/ui-alias-reproduction.log`). Mainexplicitlyexpanded p10_protocol soleownership to visualization/desktop.py+newtest_ui_alias_selection.py forminimalaliascanonicalization/current-snapshot-missing handling; publisher/contractsremainlocked. Delta requiresP10independentreview. Otherfaultnavwaitharnessinitiallyweakawaitsfix;SIGKILL/corrupttargetedtestsreportedpass. No nativevalidationinferred.

P10 main continuation: frozen protocol implementation `runs/p10-protocol/snapshot.json` has 26 owned files +5 source references; independent Sol High review resumed after a network-permission interruption (no review bypass). Main focused26pass exit0, fault4pass exit0, native synthetic3pass exit0. Native pilot evaluate exits1 as expected: planned2, attempted0, completed0, missing2; metrics unsupported/null and verdict incomplete. Central source inventory extended200→202 by pinning evaluation metrics/box-quality references; prior200 unchanged. No native campaign or environment installation.

Main whole CPU run `runs/p10-main/cpu-final.log` exited1:545passed,1failed,3deselected. Failure was the P09 exporter regression fixture offering frame1 after first UI publication, before frame0 durable dispatch could finish. Deterministic `runs/p10-main/admission-diagnosis/probe.py` blocked Journal.watermark after UI publication and demonstrated dispatch_pending rejecting frame1 while detector processed only frame0 (exit0; probe.json). Runtime behavior matches nonblocking admission contract. Main changed only tests/test_launcher.py to await committed==1 plus UI publication before frame1; no TTL, scheduler or product change. Launcher focused suite passed exit0; fresh wholeCPU/source-only checks running with durable exits under runs/p10-main/confirmed-exits.json. P10 remains in_progress pending independent review.

P10 fresh confirmation after fixture synchronization: wholeCPU546pass/3native-deselected exit0 in50.32s, source-only verifier exit0; durable command/exits runs/p10-main/confirmed-exits.json. These verify current code correctness/isolation only; P10 review pending and native verdict remains incomplete/insufficient demonstration. Running guide now documents implemented offline evaluate and explicit missing-slot outcome; acceptance report includes actual frozen pilot and support limits.

Independent P10 review original scope released after32/32before-after hashes match. Main reproduced `PYTHONPATH=tests .venv/bin/python -m pytest runs/p10-review/test_adversarial.py -q` →7failed1passed exit1 (`runs/p10-main/review-reproduction.log`): duplicate completed execution across seeds, configured resolution unbound to input, valid ambiguous null-object event rejected, hierarchy object geometry/evidence/lifecycle mismatch accepted. Fresh26focused,4faults,100instance+3IDF1source-parity checks pass independently but do not override findings. Original writer SolHigh resumed for narrow evaluator fix-round1 only after reviewer released snapshot. No runtime/schema mutation authorized; missing native seed/measurement proof must fail closed, not be invented. Main fresh selected-source integrity202/202match exit0 (`runs/p10-main/source-integrity-final.json`); two source folders untouched in selected audited closure.

P10 fix-round1 stable manifest finalSHA c6cb1a391f44629fd0627141e81c57f023bf830d7df5be85590ef8888419dd46 (initial39105... superseded only by report prose clarification). Four evaluator/test files changed,22original-owned unchanged; original32/32 audit preserved. Main fresh independent8pass0,focused45pass0,wholeCPU565pass/3deselected exit0,source-only0,pilotCLIexpected1/incomplete (`runs/p10-main/fix-round1/exits.json`). Mandatory scopedreview resumed originalSolHigh; gate pending disposition. Fix handles unique executions, deterministic recording seed0, exact pinned config/inputshape, nullunattributedevents and all8canonicalobjectprojection fields. Currentcompletedlive exports failclosed because actualexecutedseedproof absent. This is software readiness debt distinctfrommissingenv; user full-plan authorization already covers required software work, no new approval needed for that work. Original writer preparing read-only minimal instrumentation/seed plan while reviewer finishes; runtime files remain frozen until review ends. Installation/download/nativecampaign permission remains unchanged.

P10 fix-round1 mandatory scopedreview ACCEPT R1–R4: reviewer45focused+8original+6newboundaries pass0,43/43finalSHA records checkedbeforeafter; nativepilotCLIexpected1 honest. Main fresh565CPU/3deselected exit0,sourceonly0,focused45/original8pass0 independently. Reviewer releasedallsourceinspection before nextreadinessimplementation; proseonlyreport remains. Evaluator findings closed, P10 overallin_progress. Nextseed+measurement software readiness scope remains requiredbyoriginalplan, separatefromenvapproval/nativeexecution.

Main authorized P10readiness slice1 after scopedACCEPT releasedruntimeinspection: soleSolHigh p10_protocol owns configuration.py/launcher.py/sensorsclient+worker,2newseedtests,2newseedprofileconfigs,runs/p10-readiness/seed. Main contract docs/runtime-measurements-contract.md: additiveoptionaluint32seed retainsv1loadability, explicitseedrequiresactualseedACK beforecapture; reset invalidatesproof. SharedObservation/MotionCommand unchanged. Latermeasurementartifactv1/exportmanifestv2/suitev2 separatecheckpoints, one writer andindependentreview. Noenv/nativecampaign permissions changed. Oldfrozenprofile worker hashes mayno longerlaunchnewworker; newversionedprofilespinnewSHA, oldhistoricalevidence remainsimmutable. Main fresh6reviewboundaryprobes pass0 at runs/p10-main/fix-round1/new-boundaries.log.

P10 readiness concurrency: main dispatched SolHigh p10_measurement_primitives for independent NEW runtime/measurements.py/resources.py and tests/test_runtime_measurements.py,test_resource_sampling.py only, outputs runs/p10-readiness/primitives. Seedwriter retains configuration/launcher/sensors/newseedprofiles; no sharedfilewriters. Main owns artifact/publicintegrationcontract. Primitive API must be notified beforeimplementation, boundedsource/clock-aware collection and offcontrolresource thread, nofutureactuationproof fabricated. Seed focusedchecks can proceed; wholeCPU duringprimitivewrites must exclude those2in-progress tests and cannotclose integratedgate. Main finalCPU onlyafterbothstable. No GPU/nativecampaign/envinstallation.

Seedcheckpoint frozen SHAe7cd9dc7fde9b02c76093f4d655140b2d541139caa950a1dda70895e4b68dd2f:8owned,22records+4oldconfig/suiterefs. Main independent97focusedpass0 and26/26recordhashes match (`runs/p10-main/seed/`). Worker595CPU/3native-deselected excludes2primitivefiles explicitly; notintegratedgate. IndependentSolHigh originalreview27/27beforeafter,97focused0 and5adversarial1fail4pass identifies only startupACK validation beyonddeadline accepted. Main originalselector reproducesexit1 in ack-deadline-red.log. Reviewer completedallsourceinspection/releasedbefore minimalfix; writerresumed sensors/client.py +newseedtest only, nootherproductchanges. Originalmanifest/proof/logs immutable. Primitiveworker remainsdisjoint and addsboundedPPID-tree realCPUcoverage/noGPU.

Seed deadlinefix scopedACCEPT R1,103reviewtests0,36/36beforeafter hashes (`seed-review/fix-round1/review.md`). Main5independent+98focused0. Primitivewriter stopped35focused0 and own5/5hashescopies stable; main35focusedfresh0. Main dispatched NEWindependent SolHigh p10_primitives_review on4ownedfiles only, no integrationruntime/sensor reads exceptcontractsnecessary; oldreviewerhandlesseedseparately. Main wholeCPU+sourceonly fresh runningnowbothsourcewritersstopped, outputs runs/p10-main/readiness-base/. Seedworker onlyread-only nextintegrationplanning whileprimitivesreviewpending; no productwritersactive. Nativeeligibility/bodytravel/VRAM integration stilloutstanding, nofalseP10completion.

Main fresh wholeCPU631pass/3native-deselected exit0 in58.41s plus source-only0 (`runs/p10-main/readiness-base/exits.json`), includesbothprimitivefiles afterfreeze andseeddeadlinefix. Primitives mandatoryreview remainsopen; passcountdoesnotclosefindings. Reviewer investigating unsafevalidation ordering on mutableFrameKey inboundedproducer; awaitdeterministicrepro/originalscopecompletebeforenarrowfix. SeedscopedACCEPT remainsacceptedseparateboundary, no newruntimeintegrationwrites yet.

Primitives fix-round1 accepted independently:48focused+25original+17newboundarypass0,6/6working/snapshot hashes match beforeafter; snapshot7edc3a72b55238ee2e020c7084b8bc20d45d6313a31c88f80df266bbaaf47acf, report primitives-review/fix-round1/report.md. Worker returned accountusage-limit after artifacts saved; no quota bypass/replacementwriter dispatched. Main took exclusive actuation scope after seedreview release: worker/client, newactuationhelper+2tests,newseedprofileworkerpins only; runtimecoordinator/launcher/eval/primitives unchanged. Main archived acceptedseed8files beforedelta. Helper/worker/client REDGREEN evidence under runs/p10-readiness/actuation;79focusedgreeninitial. Added selfreview wrongclockbodypose regression RED thenfix, sideways/backwards/giantinteger guards. Fullfocused/CPU/sourceonly running under actuation/exits.json. No nativeenv/GPU/data/model changes. OverallP10 remainsin_progress.

Mainactuation frozen34c76... sourcecopies9records+4unchangedconfigrefs,122focused0/668CPU3native-deselected0/sourceonly0. Originalseed8files archiverecoverable. Independentoriginalreviewer resumedSolHigh onactuationscopeonly,23hashchecks122focusedpassreported; inspectingcombinedpulsebudget andoverlapinvalidations, nosourcechangesduringreview. Mainstandalonegpu_provider.py/test_gpu_provider.py disjointscope, read-onlyboundedsubprocess/PIDstarttreeattribution,9CPUfake-tooltests0, noactualGPUquery. Providerstdout64KiB/4096rows/deadline<=1s, groupcleanupalways, missingdevice/scope/NaN/duplicate/PIDreuse->unsupported; sampledmemoryneverabsolutecapcertificate. Notyetintegrated/reviewed.

Actuation originalreviewREQUESTCHANGES R1/R2 mainreproduced4fail1pass0selector exit1;23/23hashesbeforeafter andalloriginalscopeinspectioncomplete before mainfix. R1 sum nominal translation/turn durations<=single100ms/source-commandbudget; R2 atomicproofgeneration guard invalidatedonnewcapture/execute/step/reset/close, finaldeadlinebeforepublish. Mainadded4permanentregressions RED4fail then33combinedgreen; fullfocused/CPU/sourceonly runningfixround1. Sourceoriginals immutable. GPUindependentreview originalscope stillfrozen; main spotted providerdeadlineunit mismatch with ResourceSampler(ns vsseconds), notifiedreviewer toconfirmbeforefix. This issoftwareintegrationgap, noactualGPUuse.

Actuationfix mandatoryreviewACCEPT:129focused+5original+13newboundaries0,23/23beforeafterhashes at04951889980e681a5ba23c38308a2a731afae8f229630c94c047b9c3478a3d44; originalR1/R2closed, sourceinspectionreleased. GPUfixmandatoryreviewACCEPT:37own/adaptedoracle+15newboundaries0,4/4beforeafterhashes c86f99585ab0c89d42f0840df309d52d721af58701f0c708dcfbe19923bcd3a7. No actualGPUquery, nativegatesunchanged. Mainnowsolewriter nextdisjointwiring: NEWruntime/observability.py +test_runtime_measurement_wiring.py andcoordinator.py/launcher.py/configuration.py/newseedprofiles foroptionalobserver; acceptedprimitives/actuation/GPU sourcesstayfrozen. PipelineconstructorobserverassignedBEFOREthreads; captures/actualinferreturn/ownercommitreturn/admission/control events fromrealtransitions; originliveTTLexpiredincluded. New3CPUwiringtests REDmoduleabsenttheninitialHealthattributefixtureintegrationbugcorrected; targetedruntimechecks running. Separatecheckpointreviewrequired beforeP10gate.

Wiring sourcefreeze main9records/copies+10readonlyrefs SHA5665eefc552da5438b7be08339e803cb73d4a3f11debad9de00adc971b9b45fa. Durable96focused0,698CPU3native-deselected0/57.68s,sourceonly0. OriginalSolHighreviewer assignedwiring-only scope; runtimeproductstopped. Mainnextpureevaluation.measurements module/tests only, no concurrentfrozenruntime/evaluatorportmutationsuntilcontractstable. Measurementrecordcaps+filecap incompleteness explicit; resourcephase excludesfinalserialization; lower-bounddistance notfullrun. Correctnesspasscounts never promotephysical/nativeacceptance.

## P10 wiring fixes và offline proof seam — 2026-10-27

Main confirmed reviewer original RED2 and pending-raw RED1. Wiring final scoped ACCEPT after source ACK/rejection transition and sensor/UI/resources/raw cleanup binding; exacttrue stopped marks cleanup clean while stopped/data-incomplete still outcome incomplete. Final26main+30reviewer pass0;31hashes. Evidence: runs/p10-readiness/wiring/fix-round{1,2}/ and wiring-review/fix-round2/review.md. Round1 fullCPU702/3deselected0,145focused0,source-only0,sources202match0 retained; not final gate for subsequent deltas. Wrong focused filename and test import logs retained with corrected commands, no hidden pass inference.

Main extracted pure source-bound actuation validator and shared sampled pose calculation; typed live wrapper/deadline/body math unchanged. ScopedSolHighACCEPT,130freshtests including200+100 deterministic paritycases,12hashes, runs/p10-readiness/actuation-offline-review/review.md. New measurement evaluator standalone frozen134aec9346a8d407dee18cacdc08290e5df9719f848a4c6e67c3ac8f32352e50,125focused0, independentreviewpending; root native eligibility alwaysfalse pending execution provenance binder. New execution binder only while evaluator/runtime refs frozen. No environment mutation, source folder edits, GPU/native run, download, extension or publish. Actual Habitat/detector/device/calibration/useful demonstration remain unproven.

## P10 evaluator v2 tiếp tục — 2026-10-28

Read retained independent review evidence after account quota interrupted reviewer (reset reported Oct28 01:55 Asia/Ho_Chi_Minh; no retry/alternate-agent quota workaround). Original evaluator R1–R4 independently reproduced8fail then fixed: proof/control exactreason/source/map/time even partial trace; missing frontier attribution nullsupport0; rawtype/hugeinteger guards; observed resource shutdown timestamp. Original scoped followup left13 boundary probes,5fail8pass: nestednavigation wrongcontainer and nulltrace escaped ValueError. Main independently confirmed5fail8pass, added rawcontainer guards; permanent copies initially omitted canonical_sha256 import (5NameError retained), corrected, fresh green. No independent ACCEPT inferred from interrupted review.

NEW execution_proof.py binds canonical inspection SHA, configfilehash+parsedcontent, effective config, resolved launch/scene/worker, executedseedACK, separate startup/final decodedsensor metadata, source/clock/outcome/cleanup. RealCPU sensor process/launcher test passes with dependency stub and pinned script/config; explicitly no native authentication/acceptance. NEW suite_v2.py validates each attempt config and recipe (onlyseed/episodevary, resolvedassetpaths), partial measuredphase pins/counts/qualityisolation. exports.py accepts v1exact4/v2exact5, crosspins measurement/rootcoherence. protocol.py routes v2 with perattemptconfigs, prevents duplicate measured executions across outcome/scene slots, keeps v1 tests/oldconfigssuite immutable. Added configs/evaluation/suite-v2.json one-scene/two-missing pilot; corrected CLI evaluate exits1 expected incomplete. Initial wrong module entrypoint lacks __main__, retained log, no pipeline was started.

Ruling: user AGENTS/docs mandatory independentSolHigh review remains gate over skill default single final review; quota interruption leaves reviewpending rather than replacing with author review. Existing emptyread-only .git means no worktree/commit/checkpoint scripts; durable sourcehash snapshots/logs/ledger continue under user's existing workspace authorization. Ruling: v2 missing templates validate pinned recipe but do not call runtime-ready loader for nullfloor; attempted configs MUST use real loader. This preserves explicit missing slots without manufacturing readiness; cost ifwrong is accepting an invalid *planned* recipe, never execution credit.

Current validation: integration-v2 firstCPU784pass0 ran while late duplicate-phase regression/code was being added, so retained as intermediate evidence only; final stable rerun in integration-v2/final is authoritative once complete. No product writes after final stable rerun started. No installs/downloads/GPU query/campaign/extensions/sourcefolder edits/commit/publish. Native runtime/dependencies/calibration/useful demonstration gates remain open.

Final stable checkpoint:137focused0,21retainedindependentprobes0,787CPU/3native-deselected0 in56.72s,source-only0,202selectedsourcehashesmatch0. Pilotv2expected1 with planned2/attempted0/completed0/missing2. Frozenmanifest `runs/p10-readiness/integration-v2/final/manifest.json` SHA c6076ad07257f2d000547240cf7a14749e438392a5838acdc0daa63a4cb011c4; exactargv/exits and report alongside. No product mutation after stable verification started. State implemented/frozen, independent reviewpending; software/core/P10/runtime not declaredcomplete. Review reset reported01:55VietnamOct28; no quota retry/workaround. User authorization persists for review/fixes; no need ask to continue ordinary code work when service is available.

## P10 native preparation / coverage checkpoint — 2026-10-28

Authorization: user explicitly requested all remaining implementation and P10 acceptance. Isolated environments installed under .runtime with locks in runtime/environments; existing local detector/encoder/scene assets only. Broader inventory found additional HM3D scenes; approved outside-sandbox execution sees RTX3060Laptop GPU, while sandbox hides driver interface. No source/model/dataset/driver/training changes.

Independent integrated review: runs/p10-native-preparation/integrated-review/review.md,43/43 frozen hashes,211fresh tests0; original evaluator/startup/reaping fixes accepted,2newbinderP2 reproduced and fixed separately (main validation/review pending). Geometry cache manifest28c65081e207373392feda371f4cb3136e226b97106ac4d029285382ee4ca192 accepted by independentSolHigh,47fresh tests0,12/12hashes; main44Numba focused0. Diagnostic20s live-profile-00861-coverage-cache exit1/incomplete,errornull,170frames,bootstrapmedian6.59ms vs prior94ms; body/frontierlowerbound0.0019487m, realobjectcommit/acceptedregion,nomembership, resourcespartialRSS147/157 GPU18/20. Not campaign acceptance. Useful>1m/nativeboundedness remain unproven.

Next independent implementation scopes: rooted resource census/retries with explicit diagnostics and unchanged missing-sample gate; native action/physics without Simulator.step sensor render duplication (public API, samecollisionfilter/TTL/proof). No campaign frozen/launched yet. Current P10 in_progress, no runtime-validated claim.

### P10 native runtime2 → runtime3 preparation

865CPU/3native-deselected0 on pre-yield/archive/capsule snapshot. Actuation+binder review ACCEPT138+10independent0/19hashes; resource deadline scopedACCEPT90fresh0/9hashes. 00802 new-yaw native calibration99/99footprint165/165corridor0; old/new native actiontime bothworld0→.024/postcapture.024 poseversion1. Evidence in runs/p10-native-preparation/.

Runtime2 60s diagnostic exits1/incomplete after~47s rawarchive256MiB reached;338frames, frontierlowerbound.017381m, objects/regionaccepted, membershipabsent;GPU44/44,RSS383/389. Capsule validation CPUrecomputedpath bottleneck~54ms being vectorized under exactoracle; no gate relaxation. Main realLinuxzombie-reap race RED→bounded5msyield under same100ms/3trials GREEN. Explicitoptionalarchiveallocation≤raw/2, default256MiB unchanged; runtime3allocates1GiB inside raw2GiB/total8GiB, reserve+actualquota unchanged. RSS/archive independentACCEPT117+24fresh0/8hashes. Runtime3 not acceptance campaign; still smoke/review beforefreeze. No source sibling/model/data/driver/training change.

## P10 tiếp tục — 2026-10-28, sampling và native yaw

- Thread RSS: writer135focused0; độc lập135+19probes0; finalmanifest3f8ef6fa29f40491e35fe8a8c0c15b1c6f8431ae5346e8224888351a28a4d4db, report `runs/p10-native-preparation/thread-rss-review/review.md`. Implemented/correctness-verified scoped; native support completeness chưa đạt.
- Native medium-nav60s diagnostic exit1early94frames; actualoriginalerror `yaw bounds mismatch` rồi clientclosed. Report/error/proof context tại `live-profile-00861-runtime6-medium-nav/`; no useful translation, no acceptance.
- Bounded nativeyaw120turns: parentexit1 (2proofvalidationfailures),childnativeexit0; exactfloat32quaternions/proofs retained. CPU installedMagnum replays120/120exact. ApproachA preflight≤32float32amountcandidates đang triển khai; khôngđổiproofv1/epsilon/TTL.
- Optional sampling/RSSacquisition: main111focused0, independent68fresh0; replayP2 RED→fix→GREEN, finalmanifest2cf3658c2bcad437998fc4093b8ae60531ec79668af98f62f62e6dc550e1201d. Implemented/correctness-verified scoped; report `sampling-profile-review/review.md`. Capacity-profile replay explicitly unavailable pending exactselectedjournal support, defaultreplay unchanged. No historicaldenominator/rejection/null recount.
- Package source-only result `sampling-profile-checkpoint/source-only.log` has passed=true/no failures; sourcehash audit `sources.log`202True. Full headCPU/fault/nativeDuDe gate pending afteryawfreeze; prior928checkpoint doesnotcertifynewhead. Campaign4slots chưa freeze/chạy; runtimeuseful>1m/assignedmembership/resourcecompleteness stillunproven. Sourcesiblingsreadonly; no newmodels/datasets/training/commit/publish.

### P10 approved planar adapter checkpoint — 2026-10-28

User explicitly approved opt-in constant-Y 2D adapter A; default strict3D retained, no physical grounding/3D terrain claim. Worker56dad4bd…2a53 and combined manifest1d133796…712c frozen; source+config+actual ACK binding tested. Fresh main `runs/p10-native-preparation/verify_runtime10.py` exits: CPU1248passed/3native-deselected0 (82.70s test runtime), fault4pass0, source-only0, nativeDuDe3pass0, selected sibling source202/202match0. Detailed commands/exits in `runtime10-verification/exits.json`. Writer actual nativeCPU SceneGraph/Agent ~4.9708mm with exactY unchanged is not Simulator/scene acceptance. Independent SolHigh review and bounded native5mm/scene smokes pending. Four runtime10 configs generated; campaign scripts prepared only, envelope not frozen or launched. P10 remains in_progress.


Runtime14 main verification completed: `.venv/bin/python -m pytest tests -q -m "not native"` →1334passed/3deselected/exit0 (93.49s); fault4pass0, source-only0, nativeDuDe3pass0,202selected sibling-sourcehashesmatch0. `runs/p10-native-preparation/runtime14-verification/exits.json` retains commands/exits. Fourprofiles14 load_config validated/exit0. No source change during full gate. IndependentSolHighreview remains pending after usage-limit interruption; no native14 pulse/smoke or campaign. Thus current software tests pass, runtime/useful membership acceptance remains unproven.


UI map overlay final main gate:1350CPU passed/3native-deselected/exit0 (94.55s); source-only packaging exit0; logs/commands in `runs/ui-map-overlay-20261028/final-exits.json`. Focused84pass0 and postpin48pass0; demo preflight readytrue/issues[]/exit0. Source/test/config/overlay-contract snapshot frozen inmanifest.json. Initial3pin failures retained, all corrected; no product source edits during final fullgate. User can restart existing demo command/profile for robot/trail/FOV. NativeSimulator/live-display validation on this new overlay not performed; preview is historical real measured data. P10 remainsinprogress.


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
