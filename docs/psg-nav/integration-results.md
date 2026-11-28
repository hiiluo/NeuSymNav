# Kết quả kiểm chứng PSG-Nav Semantic Memory

Ngày 2026-11-27, branch `hiiluo-policy`, baseline HEAD `117df522cd3c206bccc3311ea85c46807f6e46c0`, trùng local tracking ref `origin/hiiluo-policy` và worktree sạch khi bắt đầu. Upstream source đã đọc ở `181d878ff207845a31e542a19a6592925c1e9bab`. Tests và run artifacts bên dưới được tạo trong phiên này. Kết quả paper nằm ở [technical analysis](technical-analysis.md).

| Milestone | Implemented | Correctness-verified | Runtime-validated |
| --- | --- | --- | --- |
| M0 | Audit, source pins, design, contracts, plan và protocol | CPU tests, DEV60 preflight, native replay A/B recording cố định đều đạt | Native Hydra/RG CPU replay và RG read-only handoff. Paper Habitat smoke dừng khi reset |
| M1 | Native retirement reconcile và confirmed receipt opt-in | **Nghiệm thu replay cô lập**, 393 test đạt và 1 skip | 739 held-out view, một owner reconcile đúng và một receipt xác minh bằng source RGB-D |
| M2–M4 | Hard-vote core, revision-safe store và query Hydra | Oracle unit, lifecycle, exact token và replay parity | Xác minh trên receipt native được replay |
| M5 | Paper shadow và B0 lockstep OFF/shadow/B2 có exact native join | 519 đạt, 1 skip. Parity và B2 verifier exit 0 | Nghiệm thu trên live dev lockstep có MotionGuard và cadence cố định |
| M6 | Offline belief, GT audit, paired verifier và profiling | CPU regression, deterministic replay và paired pilot đã kiểm | 3/180 UID pilot. TEST180 B0 đã khởi chạy, chưa nghiệm thu M6 |

## M0 — Baseline đang chạy được

| Kiểm chứng | Exit | Kết quả |
| --- | --- | --- |
| RG/Hydra/Paper CPU regression | 0 | 362 đạt, 1 skip. Pytest 12,52 s, peak host RSS theo `time` 400.536 KiB. [Log](../../runs/psg-nav/20261127/baseline-pytest.log) |
| DEV60 Paper B0 v2 preflight | 0 | 60 UID, 6 scenes, protocol `paper-objectnav-hm3d-v1` và detector Torch. Preflight chưa chạy simulator. [JSON](../../runs/psg-nav/20261127/paper-preflight.json) |
| ReasoningGraph handoff replay | 0 | CLIP query object `ok`, đối chứng `no_evidence`. Room có node `ok`, thiếu node `no_evidence`. Relation geometry-only trên hai frame. [Log](../../runs/psg-nav/20261127/rg-handoff.log) · [Relation](../../runs/psg-nav/20261127/rg-handoff/relation/summary.json) |
| ReasoningGraph native replay off/on | 0 | 18/18 accepted prefixes và graph SHA khớp, cả hai clean shutdown. Service p95 97,58/108,90 ms. Worker RSS ghi nhận 250.949.632/234.803.200 bytes. Sidecar 18/18, 0 drop/error, 3.602.755 bytes artifacts. Đây là baseline RG evidence, chưa có semantic memory. [Report](../../runs/psg-nav/20261127/native-baseline/report.json) · [Log](../../runs/psg-nav/20261127/native-baseline.log) |
| Paper B0 smoke và retries | 1 mỗi lượt | Cùng UID `hm3d_v2/val/LT9Jq6dN3Ea/0#2`, simulator worker dừng khi reset. Ép Mesa và thử software + surfaceless vẫn fail. Probe reset riêng ghi returncode `-11`, faulthandler đặt fault trong Habitat-Sim 0.3.3 `Simulator._config_backend`. GDB bị từ chối ptrace và không có native backtrace. Chưa xác định nguyên nhân native crash. Không có trajectory hoàn tất để tính SR/SPL. [Smoke](../../runs/psg-nav/20261127/paper-smoke.log) · [Mesa](../../runs/psg-nav/20261127/paper-smoke-mesa.log) · [Surfaceless](../../runs/psg-nav/20261127/paper-smoke-surfaceless.log) · [Faulthandler](../../runs/psg-nav/20261127/paper-reset-worker.log) · [GDB](../../runs/psg-nav/20261127/paper-debug.log) |

Môi trường đo là Ubuntu 24.04.5, AMD Ryzen 5 6600H, 12 logical CPU, Python 3.12.3 host/Hydra và 3.9.23 Habitat. `nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv,noheader` exit 9, không có device files NVIDIA trong session. VRAM chưa đo.

### Lệnh M0

Chạy từ repo root. Dùng output directory mới khi lặp lại các runtime probes.

```bash
out=runs/psg-nav/20261127-repro
mkdir -p "$out"
export QT_QPA_PLATFORM=offscreen OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=2
PYTHONPATH=src:.:tests /usr/bin/time -v .venv/bin/python -m pytest \
    tests/test_rg*.py tests/test_hydra*.py tests/test_objectnav_paper*.py \
    -q -m 'not native' -p no:cacheprovider --tb=short
PYTHONPATH=src:. .venv/bin/python tools/objectnav/run_paper_episodes.py \
    --policy b0 --manifest configs/objectnav/splits/hm3d_v2-val-dev.json --preflight
bash handoff/reasoninggraph/replay.sh "$out/rg-handoff"
live=runs/reasoninggraph/handoff-20261127
PYTHONPATH=src:. /usr/bin/time -v .venv/bin/python tools/reasoninggraph/handoff_compare.py \
    --source "$live/combined/live" --config "$live/live.json" --out "$out/native-baseline"
paper=runs/reasoninggraph/m0-20261126
PYTHONPATH=src:. /usr/bin/time -v .venv/bin/python tools/objectnav/run_paper_episodes.py \
    --policy b0 --policy-config configs/objectnav/paper-b0-v2.json \
    --protocol "$paper/smoke-protocol.json" --manifest "$paper/smoke-manifest.json" \
    --action-audit --reasoninggraph-mode off --run-id psg-m0-b0 --out-dir "$out/paper-smoke"
```

## M1 — Identity và evidence

### Native category intervention

Cả hai arm dùng view 0 từ journal 00806, 10.025 pixel mask ban đầu được gắn `television`. Gửi cùng RGB-D, pose và synthetic timestamps theo thứ tự, đổi duy nhất label raster trên mask. Lặp để quan sát label khác tích lũy trong native semantic integration. Các lần lặp chẩn đoán này không được tính như độc lập trong bất kỳ belief evaluation nào.

| Arm | Semantic sequence | Kết quả bước 12 |
| --- | --- | --- |
| Control | `chair` × 12 | Một active `O(0)`, tồn tại từ bước 1 |
| Flip | `chair` × 3, `armchair` × 4, `couch` (`sofa`) × 5 | Ba active IDs. `O(0)` label 18 từ bước 1, `O(1)` label 2 từ bước 7, `O(2)` label 49 từ bước 11. Position và AABB trùng chính xác ở bước 12 |

`bash runs/psg-nav/20261127/identity.sh runs/psg-nav/20261127/identity-pinned` exit 0. Probe gọi native CPU `HydraPipeline.step` và giữ nguyên native backend. Kiểm JSON đối chiếu same pin, timestamps, expected labels và valid AABB exit 0 và ghi `gate_passed=false`. Exit của lệnh kiểm chứng chỉ cho biết chẩn đoán đã hoàn tất. [Tool](../../tools/psg_nav/probe_native_identity.py) · [Runner](../../runs/psg-nav/20261127/identity.sh) · [Control](../../runs/psg-nav/20261127/identity-pinned/control/report.json) · [Flip](../../runs/psg-nav/20261127/identity-pinned/flip/report.json) · [Verdict](../../runs/psg-nav/20261127/m1-assessment.json).

```bash
source .runtime/hydra_ws/env.sh
export PYTHONPATH="src:.:${PYTHONPATH:-}" OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=2
args=(
  --journal runs/hydra-attribute-query/hna-live-00806-8yoan0t4/host-off/hydra/journal.jsonl
  --config runs/reasoninggraph/m1-live-20261127/config.json
  --expected-prefix 5f3ccfb9e19628768c4622be2335d2cff7bb42d9787e666d9a1cfaaef8afee23
)
.runtime/hydra_ws/.venv/bin/python tools/psg_nav/probe_native_identity.py "${args[@]}" \
  --output /tmp/psg-identity-control --labels 18 18 18 18 18 18 18 18 18 18 18 18
.runtime/hydra_ws/.venv/bin/python tools/psg_nav/probe_native_identity.py "${args[@]}" \
  --output /tmp/psg-identity-flip --labels 18 18 18 2 2 2 2 49 49 49 49 49
```

Fixture Python của existing `link_evidence` dùng chung source token và AABB IoU 1.0 với native reference label `chair`. Đổi duy nhất detection category. `chair` trả `geometric_candidate`, `armchair` và `sofa` trả `no_support`. Candidate status chưa chứng minh physical identity. [Probe](../../runs/psg-nav/20261127/linker-category-probe.json) · [Fixture nguồn](../../tests/test_rg_evidence.py).

### Kiểm khả năng dùng dữ liệu thật

- Rerun `score_full_review.py` trên bản sao inputs 00806, exit 0. Policy frame-unique trên 46 panels có 9 proposals, cả 9 adjudicated correct trên 13 matched labels. 22/46 panel unresolved xét toàn bộ. Revision 8 thuộc pilot tuning. [Báo cáo](../../runs/psg-nav/20261127/pilot-link-review/visual-review-score.json).
- Rerun `tools/reasoninggraph/score_links.py <00770/probe-matched-cpu/report.json> --annotations <00770/annotations-ai-reviewed.json> --output <new-output>` exit 0. Trong 17 panels có 7 proposals, 1 correct, 0 known false, 6 unresolved. False-link bounds 0–85,71%. Hai gói review dùng annotation AI độc lập theo panel, chưa có longitudinal physical-track oracle. [Score](../../runs/psg-nav/20261127/holdout-link-score.json).
- `load_quality_pair` xác thực đủ 23 frame và masks exact-source của GT archive 00861 cùng detector baseline `pred-A`, thuộc campaign TrackGraph. Probe `qualify-00861.py` dùng category-agnostic mask IoU ≥0,5, chỉ giữ one-to-one unambiguous. Exit 0, có 17 matches, 3 physical tracks, 14 ambiguous candidate pairs và 0 track quan sát được category flip. Archive này không có native Hydra endpoint linkage. Scene 00806 thiếu `.semantic.glb/.txt` trong HM3D-val local root đã kiểm. 00861 và 00862 có asset semantic, nhưng chưa có cohort cross-category Hydra tương thích để nghiệm thu. [Inventory](../../runs/psg-nav/20261127/annotation-inventory.json) · [Lệnh audit cohort](../../runs/psg-nav/20261127/qualify-00861.py) · [Report](../../runs/psg-nav/20261127/qualify-00861.json).
- Producer hiện chỉ lưu `geometric_candidate` và latest revision. Contract chưa có receipt cung cấp cả canonical identity đã xác nhận và đúng detector category qua thời gian. Không có cơ sở promote votes từ AABB-only hoặc từ aggregate native label. [Source audit](current-system-audit.md#observation-availability).

**Điều kiện còn thiếu.** Tập fixed RGB-D nhiều góc nhìn có category transitions và các ca hai physical instances áp sát, được đối chiếu bằng instance GT hoặc blind longitudinal review. Trên tập này cần so sánh linker-only với baseline, và nếu cần, native owner experiment riêng. M1 chỉ đạt khi receipt đủ provenance và sự chuyển category giữ đúng canonical identity. M2–M6 chưa được mở theo gate. [Prerequisite A/B](implementation-plan.md#m1--identity-và-evidence-readiness).

### Pin SHA-256 dùng ở runtime

| Input | SHA-256 |
| --- | --- |
| Paper B0 v2 config | `586b160981268ff26c49fb95de65012be45368f0fce1a0990dcf6d1c81caeeaa` |
| DEV60 file | `0491818e95dd7cc9a13a6d5ab2f90b8f201dd46eb9a7f3fa45aebf1ecf5830eb` |
| Paper smoke protocol file | `5b18ae644b27478178d30ea93c684994dbe3fbbe07c6450247c6daa616196832` |
| Paper smoke UID manifest | `d69a3f209fa62cfe3d011c9aaa29d016379f83e3c4537325cad612208f3a78f8` |
| Taxonomy file | `04596183aa090cf6d0e561c6d4e469dafca11574f2d21f08202971c3436a2603` |
| Native baseline live config file | `9ba38c7c31ff5ba9242f7c21109c2f2400f72574e07bf6188b3445a6a3bbeb39` |
| Native baseline input recording certificate | `3649535ffe93e92cf4aefa9709d0ef2c7b709cff2083f4c9444cedcdbc73f144` |
| YOLOE-26m profile checkpoint pin trong nguồn recording | `585f5ec9028fd358035da8d860c27c56be285a795cba2076fba536a4391c2c83` |
| Identity profile file | `ee95d202651b4650b12961e9cd11e413b961a39f6ae6c143e32eeb4ee6b4da62` |
| Identity source journal | `daaa8a9ef9b684649dbe329f2aeceae90ef14519c9354dafb135b5c8139f8ba8` |
| Identity accepted input prefix | `5f3ccfb9e19628768c4622be2335d2cff7bb42d9787e666d9a1cfaaef8afee23` |
| Identity runtime binding | `43efadbeaa74c917d75cdaa81b6f603a26dd0799288a425ac45b4956778f10de` |
| Identity profile room-stability private library pin | `9972091688a8f666899614d4e90726ca8d4fac18d5a5f39b73b05bb35d69d179` |
| Identity composite build | `abb2c1d9538488d477c436e11721cfb07371f02e43f1fbdc077de60a3853f7b0` |

Profile sub-config hashes, timestamps và native step timings nằm trong probe JSON. Không có semantic accuracy, NLL/Brier/ECE, PSG latency/RAM, wrong-stop rate hoặc navigation gains để báo trong phiên này.

## Tiếp tục M1b–M1c — cohort thật và đối chứng linker

**Runtime.** Probe Habitat cảnh rỗng 32×32 trong sandbox exit 139 với device `-1`. Device `0` exit 1 vì không có EGL CUDA device phù hợp. Software softpipe tạo được GL context nhưng hết 30 giây trước khi có ảnh, exit 124. Cùng probe chạy ngoài sandbox với runtime đã có, exit 0 và trả RGB qua RTX 3060 Laptop GPU. Không có cài đặt hay tải thêm. [Probe](../../runs/psg-nav/m1-cohort-20261127/minimal-habitat.py) · [Sandbox](../../runs/psg-nav/m1-cohort-20261127/empty-cpu.log) · [Host](../../runs/psg-nav/m1-cohort-20261127/empty-host-runtime.log).

**Baseline Paper B0.** Lặp lệnh smoke M0 ngoài sandbox trong output mới, với cùng Paper B0 v2, protocol và UID. Exit 0, 28 action, 0 collision, đường đi 2,50 m, hết step budget và không STOP. Chấm bằng `.runtime/sensor/bin/python tools/objectnav/score_trajectories.py ... --set hm3d_v2 --split val` exit 0, một episode hợp lệ, SR/SPL 0, DTG 9,06 m. Đây là smoke một episode. [Run](../../runs/psg-nav/m1-cohort-20261127/paper-b0-host.log) · [Score](../../runs/psg-nav/m1-cohort-20261127/paper-b0-host/score-summary.json).

**M1b cohort qualification.** Tạo `tools/psg_nav/qualify_identity_cohort.py` làm evaluator offline, dùng exact-source frame binding và mask checksums từ quality loader. Chỉ giữ cặp có IoU ≥ 0,5 và duy nhất theo cả detection lẫn physical instance trong frame. Trên archive cũ 00861 có 17/73 detection được ghép, hai multi-view tracks và 0 category flip. Render thêm 40 view mỗi scene 00861 và 00862 bằng script `sample_views.py`, dùng pin trong run manifest. Tất cả 80 view đạt RGB-D alignment annotated/basis. Existing YOLOE-26m CPU xử lý 80/80 frame ở confidence floor 0,25. Kết quả mới có 103 cặp mask hợp lệ và 14 physical tracks đổi nhãn, mỗi scene 7. Ví dụ thực có `chair → stool` ở 00861, và `mirror → window` ở 00862. Đây là hai đường path chẩn đoán cố định, không phải mẫu benchmark navigation đại diện. [Tool](../../tools/psg_nav/qualify_identity_cohort.py) · [Archive cũ](../../runs/psg-nav/m1-cohort-20261127/00861.json) · [Input manifest](../../runs/psg-nav/m1-cohort-20261127/sample-manifest.json) · [80-view alignment](../../runs/psg-nav/m1-cohort-20261127/views/scenes.json) · [Cohort có pin](../../runs/psg-nav/m1-cohort-20261127/sampled-cohort.json).

**M1c đối chứng A0/A1.** Hai linker đọc chung 80 accepted graph revisions từ native replay. A0 là `rgbd_aabb_frame_unique_v1`. A1 thử nghiệm dùng điểm mesh chiếu lại theo camera, qua ngưỡng chênh depth 0,15 m, tối thiểu 12 pixel khớp mask, tỷ lệ 0,75 và khoảng cách score 0,15. A1 không dùng category trong xếp hạng và bỏ các claim cùng endpoint trong frame. Replay chỉ đọc RGB, depth và YOLOE output. Evaluator riêng dùng GT mask để chấm proposals đã đóng băng. Intrinsics và pose tái dựng từ metadata của camera/vị trí, depth lấy từ archive lượng tử 1 mm, nên đây là diagnostic replay của corpus mới. [Replay code](../../runs/psg-nav/m1-cohort-20261127/replay-linkers.py) · [Native hashes](../../runs/psg-nav/m1-cohort-20261127/native-link-arms.json) · [Offline score](../../runs/psg-nav/m1-cohort-20261127/native-link-score.json).

| Scene | Arm | Proposals | Đúng đã phân giải | Sai đã phân giải | Unresolved | Flip track có hai nhãn trên cùng raw ID |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 00861 | A0 | 14 | 6 | 0 | 8 | 0/7 |
| 00861 | A1 | 21 | 9 | 0 | 12 | 0/7 |
| 00862 | A0 | 44 | 19 | 0 | 25 | 0/7 |
| 00862 | A1 | 58 | 29 | 0 | 29 | 1/7 |

False-link bound gộp A0 là 0–56,9% và A1 là 0–51,9%. Quan sát A1 giữ `O(19)` từ `mirror` sang `window` trên track 00862, nhưng một track 00861 dùng `O(10)`, `O(14)`, `O(15)` qua `desk → kitchen island`. Cùng raw ID chưa đủ canonical lineage xuyên revision.

**M1d chẩn đoán owner.** Replay lần hai cùng input cho 80/80 prefix, graph SHA và proposals trùng. Cặp 00862 `O(14)/O(22)` của một physical track có ba frame cùng ít nhất 12 pixel visible support và max projected overlap 94,7% trên support nhỏ hơn. Tỷ lệ mutual 3D surface support cao nhất ở khoảng 10 cm là 56,8% qua chín snapshot. Cả ba cặp của track split 00861 đều thiếu snapshot chung có đủ support. Chín cặp khác instance đo được trong cùng frame có mutual support 0 tại 10 cm. Mẫu dương hiện chỉ có một cặp đồng quan sát, nên chưa đủ chứng nhận thay đổi owner hoặc suy alias cho các endpoint không đồng quan sát. [Projected support](../../runs/psg-nav/m1-cohort-20261127/native-co-visibility.json) · [3D support](../../runs/psg-nav/m1-cohort-20261127/native-mesh-score.json).

### Lệnh và exit code của cohort

```bash
out=runs/psg-nav/m1-cohort-20261127
EGL_PLATFORM=surfaceless OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=2 \
  .runtime/sensor/bin/python tools/objectnav/detector_eval/sample_views.py \
  --manifest "$out/sample-manifest.json" --habitat-data "$PWD/local-assets/datasets/hm3d-val" \
  --out-dir "$out/views" --path-step 0.75 --scan-points 3 --headings 6 \
  --max-frames-per-scene 40 --alignment-frames 40
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 PYTHONPATH=src:. \
  .runtime/detector26/bin/python -c 'import importlib.util, runpy; runpy.run_path("tools/objectnav/detector_eval/run_detector.py", run_name="__main__")' \
  --views "$out/views" --out "$out/predictions.jsonl" \
  --profile runs/reasoninggraph/m1-live-20261127/config.json --confidence-floor 0.25
PYTHONPATH=src:. .venv/bin/python "$out/qualify-sampled.py" > "$out/sampled-cohort.json"
source .runtime/hydra_ws/env.sh
PYTHONPATH="src:.:${PYTHONPATH:-}" OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=2 \
  .runtime/hydra_ws/.venv/bin/python "$out/replay-linkers.py"
PYTHONPATH=src:. .venv/bin/python "$out/score-native-link-arms.py" > "$out/native-link-score.json"
```

Render, detector retry, cohort score, native A0/A1, offline score và mesh diagnostic đều exit 0. Detector CLI lần đầu exit 1 vì `importlib.util` chưa được load trong interpreter 3.9. Retry import module trước khi gọi cùng script và profile. [Render log](../../runs/psg-nav/m1-cohort-20261127/sample-views.log) · [Detector log](../../runs/psg-nav/m1-cohort-20261127/run-detector-retry.log) · [Native replay log](../../runs/psg-nav/m1-cohort-20261127/native-link-arms.log).

**Trạng thái gate.** Đã mở được source cohort có transitions thật và kiểm nghiệm linker A1 ở mức offline. M1 vẫn chưa đạt vì evidence hiện tại chỉ xác nhận được một track giữ raw ID xuyên category, còn có split native trên scene khác và quá nhiều unresolved proposals. A2 owner treatment, receipt admission, M2–M6 và đánh giá PSG live còn mở. Default association và navigation không đổi.

## M1d — temporal mesh và held-out

Đóng băng hai scene mới 00814/00815 trước khi chạy probe. Dùng 00861/00862 làm tập phát triển. Hai scene held-out có 44 view mỗi scene, mỗi scene là một path cố định. Runner kiểm alignment annotated/basis và cả 88 view đạt. YOLOE-26m cùng pin infer 88/88 ở CPU. Cohort có 174 cặp mask ghép được và 7 physical tracks đổi nhãn. Native replay xuất 88 accepted revisions và giữ source/build/config trong replay scope. [Manifest](../../runs/psg-nav/m1-temporal-20261127/sample-manifest.json) · [Cohort](../../runs/psg-nav/m1-temporal-20261127/sampled-cohort.json) · [Locks](../../runs/psg-nav/m1-temporal-20261127/protocol.sha256).

Probe temporal offline chỉ dùng raw endpoint, visible mesh và A1. Các tham số thí nghiệm gồm lịch sử tối đa 12 revision, ít nhất 12 điểm, mutual surface coverage ≥ 0,55 ở khoảng 0,10 m, top-two margin > 0,15 và hai revision xác nhận. A1 claims vào các endpoint riêng trong cùng frame lập cannot-link. Evaluator độc lập đọc GT masks sau khi ghi proposals. Kết quả là raw-endpoint proposals, chưa có native owner commit hay alias. [Probe](../../tools/psg_nav/probe_temporal_identity.py).

| Tập | Revisions | Proposals | Cùng instance theo evaluator vocabulary mở rộng | Khác instance đã phân giải | Unresolved |
| --- | ---: | ---: | ---: | ---: | ---: |
| Dev 00861/00862 | 80 | 2 | 2 | 0 | 0 |
| Held-out 00814/00815 | 88 | 2 | 1 | 0 | 1 |

Evaluator ban đầu giới hạn vocabulary bỏ hai ca dev ngoài taxonomy. Chấm lại với toàn bộ tên GT đã annotate, cùng proposals và ngưỡng, phân giải được hai ca đó. Trên held-out, cặp xác nhận là `O(9)` và `O(11)` của cùng một tấm thảm ở 00815. Hai endpoint đều có native category `carpet`; physical track này cũng không nằm trong bảy detector category-flip tracks. Cặp còn lại ở 00814 đều có native category `lamp` và vẫn unresolved. Replay bổ sung category khớp 88/88 snapshot, proposal và mesh outputs. Không proposal held-out nào trùng 47 distinct-instance control pairs. Tập control này là các ca đồng quan sát có mask đủ rõ. Probe cũng không tìm lại ca 00861 tách ba ID. [Dev](../../runs/psg-nav/m1-temporal-20261127/dev-all-labels.json) · [Held-out](../../runs/psg-nav/m1-temporal-20261127/heldout-all-labels.json) · [Native categories](../../runs/psg-nav/m1-temporal-20261127/category-parity.json).

Chạy `sample_views.py` ngoài sandbox với manifest ở trên, `--path-step 0.5 --scan-points 4 --headings 6 --max-frames-per-scene 44 --alignment-frames 44`, exit 0. Chạy lại YOLOE bằng lệnh M1b với output mới và cùng checkpoint, exit 0. `qualify-sampled.py`, `replay-mesh-support.py`, probe, adjudication và category parity đều exit 0. Lệnh probe và adjudication chạy với `PYTHONPATH=src:.` và output mới.

```bash
out=runs/psg-nav/m1-temporal-20261127
sha256sum -c "$out/protocol.sha256"
PYTHONPATH=src:. .venv/bin/python tools/psg_nav/probe_temporal_identity.py \
    --replay "$out/native-mesh-support.json" --output "$out/heldout-proposals-repro.json"
PYTHONPATH=src:. .venv/bin/python "$out/adjudicate-all-labels.py" "$out" \
    "$out/heldout-proposals-repro.json" > "$out/heldout-adjudication-repro.json"
```

**Đối chiếu exact native vertex.** Phát lại 168 revision đã khóa và lấy `mesh_connections` nguyên vẹn để so trong cùng một snapshot. Không so raw vertex index giữa các revision vì native có remap. Cả 168 row khớp replay ban đầu ngoài các field chẩn đoán mới. Trong dev, 15 cặp khác category có ít nhất một shared index, chỉ hai cặp có ≥12 shared indices và ≥50% support ở cả hai đầu trong ít nhất hai revision. Cả hai cặp ở 00862 và có bằng chứng cùng instance từ evaluator trước đó. Ca 00861 tách ID vẫn thiếu support. Held-out có hai cặp chia sẻ index, cao nhất 18,4% và không cặp nào đạt tiêu chí lặp. `replay-indices.py` và `score-vertex-indices.py` lần lượt chạy trên cả hai tập, exit 0. Đây là chẩn đoán correspondence theo snapshot, chưa chạy owner mutation. [Script replay](../../runs/psg-nav/m1-temporal-20261127/replay-indices.py) · [Script score](../../runs/psg-nav/m1-temporal-20261127/score-vertex-indices.py) · [Dev](../../runs/psg-nav/m1-temporal-20261127/dev-vertex-sharing.json) · [Held-out](../../runs/psg-nav/m1-temporal-20261127/heldout-vertex-sharing.json).

**Gate.** Temporal proximity xác nhận được một bản sao cùng category trên held-out. Exact vertices chỉ có positive xuyên category trên dev. Hai kết quả chưa giải quyết continuity của những endpoint không đồng quan sát. M1d chưa đủ evidence để đưa owner merge vào pipeline. M1e và M2–M6 vẫn chờ gate. Không cần thêm package hoặc assets cho mức kiểm chứng hiện tại.

## M1d — A2 native admission cô lập

A2 thử **giữ ID ngay lúc tiếp nhận cluster**, trước khi phải merge hai endpoint đã tạo. Sau khi owner remap mesh indices, chỉ cân nhắc cluster khác category có ít nhất 12 vertex chung và ≥85% coverage ở cả hai phía. Baseline cùng category được ưu tiên. Nếu một cluster có nhiều endpoint đủ support hoặc nhiều cluster claim cùng endpoint thì bỏ nhánh A2. Native owner giữ semantic label và ID gốc khi cập nhật geometry. Đây là thử nghiệm admission nghiêm ngặt, chưa xử lý duplicate sau khi sinh hoặc continuity giữa hai bề mặt không chồng nhau. [Patch](../../tools/native/hydra_object_journal/cross_category_identity.patch).

Chỉ build lại translation unit `mesh_segmenter.cpp` rồi link với các object của build journal/room-stability đã pin. Thư viện mới nằm trong run scope, dùng cùng binding. Probe chỉ bật khi có native journal và biến `NEUSYMNAV_EXPERIMENT_EXACT_MESH_ADMISSION=1`. OFF/ON dùng cùng binary và config. Cấu hình kiểm thử giới hạn 64 active objects và 128 clusters mỗi revision cho nhánh thử nghiệm. Chưa profile overhead. [Build script](../../runs/psg-nav/m1-owner-a2-20261127/build.py) · [Build log](../../runs/psg-nav/m1-owner-a2-20261127/build.log) · [SHA lock](../../runs/psg-nav/m1-owner-a2-20261127/protocol.sha256).

| Fixture native từ view 00806 | Số object cuối OFF | Số object cuối ON | Quan sát |
| --- | ---: | ---: | --- |
| Label cố định | 1 | 1 | Graph object và journal report theo từng revision trùng |
| Một mask, đổi `chair → armchair → couch` | 3 | 1 | Owner giữ `O(0)` và label gốc, journal chỉ phát một create |
| Hai vùng sát nhau, chỉ một vùng đổi label | 4 | 2 | Giữ hai ID gốc và hai create |
| Một vùng cũ tách thành hai cluster cạnh tranh | 3 | 3 | Không nối cluster cạnh tranh vào ID cũ, journal report trùng |

Fixture là can thiệp label/mask trên một view thật, hai vùng sát nhau không phải hai GT instances độc lập. RED trên original library exit 1 với `cross-category ID fragment`. Experimental OFF và ON đều exit 0. Experimental OFF trùng toàn bộ fixture report với original library. Native owner journal và `NativeObjectLineage` cũng được kiểm lại trên fixture ON. [RED](../../runs/psg-nav/m1-owner-a2-20261127/red.log) · [OFF](../../runs/psg-nav/m1-owner-a2-20261127/off/report.json) · [ON](../../runs/psg-nav/m1-owner-a2-20261127/on/report.json) · [Lineage](../../runs/psg-nav/m1-owner-a2-20261127/lineage-on.log).

**Đối chứng A1/A2 trên dữ liệu thật.** Phát lại cùng input trên 80 revision dev và 88 held-out cho mỗi arm. Replay dùng input lock chỉ gồm RGB-D/pose và detector digests. Scorer đọc GT masks offline sau khi ghi output. **Cả 168/168 graph hashes trùng OFF/ON.** A1 proposals và score giữ nguyên, gồm 38 đúng trên dev và 70 đúng trên held-out, 41 và 33 unresolved. Dev có 1/14 và held-out có 2/7 track đổi category được liên kết đúng cùng raw endpoint ở cả hai arm. Tất cả 336 revision fold được native journal. Không có cải thiện trên corpus thật để nghiệm thu A2. [So sánh đầy đủ](../../runs/psg-nav/m1-owner-a2-20261127/comparison.json) · [Replay driver](../../runs/psg-nav/m1-owner-a2-20261127/replay.py).

**Kiểm chứng và verdict.** `build.py`, `probe-lineage.py --expect-a2`, bốn lượt `replay.py INPUT CONFIG OUTPUT`, bốn lượt `score.py INPUT OUTPUT` và `compare.py` chạy với env từ `combined-env.sh` cho native, `LD_LIBRARY_PATH` ưu tiên thư mục A2, `NEUSYMNAV_HYDRA_OBJECT_JOURNAL=1` và A2 flag 0/1 theo arm. Kết quả exit, input pins và lệnh link đầy đủ dưới run directory. M1d vẫn mở. A2 đã chứng minh causal ID preservation trong fixture, nhưng trên corpus thật không kích hoạt thay đổi graph. Không bật patch trong production và không phát vote receipt. Bước điều tra tiếp theo cần tìm nguồn evidence ngoài exact vertex hỗ trợ những lần đổi góc nhìn mà hai bề mặt không trùng nhau, rồi replay trên cohort held-out độc lập.

## M1d — continuity qua chiếu RGB-D

Probe chiếu các pixel detector mask có depth hợp lệ từ camera nguồn vào camera đích. Hai chiều đều phải có ít nhất 40 pixel đích hợp lệ và ít nhất 20% số điểm đã lấy mẫu, sai lệch axial depth tối đa 0,08 m, mask agreement ít nhất 0,75 và chênh top-two score >0,10. Giới hạn 512 mẫu mỗi mask và 12 revision trước mỗi frame. Chỉ giữ mutual unique match của từng cặp frame. Raw native endpoints từ A1 được gắn sau khi match observations. Đề xuất cặp raw ID cần hai cặp frame không dùng chung frame nào. Quan sát hai endpoint riêng trong cùng frame tạo cannot-link. Native graph và vote store không tham gia tính score và không bị sửa. [Probe](../../tools/psg_nav/probe_rgbd_continuity.py) · [Replay driver](../../runs/psg-nav/m1-rgbd-continuity-20261127/replay.py).

| Corpus | Liên kết quan sát đúng đã phân giải | Sai đã phân giải | Unresolved | Quan sát cùng vật thể và khác label trong cửa sổ |
| --- | ---: | ---: | ---: | ---: |
| 00861/00862 dev | 133 | 0 | 104 | 29/54 |
| 00814/00815 tập đối chứng đã khóa | 385 | 0 | 212 | 54/85 |

Các số đếm là observation pairs, có thể chia sẻ frame và không phải mẫu độc lập. Tỷ lệ false-link chưa thể suy từ số lỗi đã phân giải vì 316 liên kết unresolved. Raw-ID proposals chỉ có một cặp unresolved trên dev và cặp `carpet` cùng category đã biết trên tập đối chứng. [Dev](../../runs/psg-nav/m1-rgbd-continuity-20261127/dev-score.json) · [Đối chứng](../../runs/psg-nav/m1-rgbd-continuity-20261127/heldout-score.json).

Ca split 00861 `hm3d:310` có match đã phân giải từ `desk` ở `O(10)` sang `kitchen island` ở `O(14)`, score 0,787. Hai match sau đi từ `O(14)` đến `O(15)`, score 0,898 và 0,836. Hai match sau dùng chung frame nguồn nên chưa đủ tính độc lập, và không có quyết định alias. [Chi tiết observation links](../../runs/psg-nav/m1-rgbd-continuity-20261127/dev.json).

Probe bổ sung chỉ gợi ý đầu mối native cho detection chưa có A1 link nếu ít nhất hai revision trước cùng hỗ trợ đúng một ID còn hiện diện và chưa ai claim trong frame hiện tại. Không dùng đề xuất mới làm input cho các frame sau. Có 6 đề xuất dev, trong đó 3 đúng theo current mask adjudication. Ca đủ support xuyên category là `bench` gắn lại vào node `coffee table` tại 00862. Có 5 đề xuất trên tập đối chứng, tất cả unresolved ở frame hiện tại, trong đó 4 có hai historical anchors đã phân giải. Historical support không thay thế current owner proof. [Dev anchors](../../runs/psg-nav/m1-rgbd-continuity-20261127/dev-anchor-score-final.json) · [Anchors đối chứng](../../runs/psg-nav/m1-rgbd-continuity-20261127/heldout-anchor-score-final.json).

**00861 lấy thêm góc nhìn trên cùng path.** Render 88/88 view đạt alignment, dùng bước lấy mẫu 0,30 m thay cho 0,75 m. Cùng detector và native build chạy hết 88/88 frame, journal fold không gián đoạn. Replay giữ nguyên các ngưỡng chiếu. Hai cặp revision 69→81 và 72→82 cùng nối đúng `hm3d:310` qua `O(16)` mang nhãn native `desk` và `O(19)` mang nhãn `kitchen island`. Đây là bằng chứng offline xuyên category trên lớp quan sát, với bốn frame riêng. Raw IDs thuộc replay dày mới và không so trực tiếp với raw IDs của replay thưa. Trên 383 liên kết quan sát có 157 cùng vật thể, 2 khác vật thể và 224 unresolved. Có 58 trên 92 cross-label opportunities khớp đúng. Hai lỗi là các cặp `desk` khác instance, với score xấp xỉ 0,955 và 0,909. Một cặp lỗi đã mang cùng raw ID từ A1. Tăng score threshold đơn thuần có thể bỏ luôn liên kết hữu ích mà vẫn không giải quyết nhầm lẫn này. Prior-anchor probe trên replay dày có 8 đề xuất đúng ở frame đích, trong đó 5 xuyên category, và 9 unresolved. Cohort dày thuộc cùng scene dev nên không phải held-out mới. [Alignment](../../runs/psg-nav/m1-rgbd-dense-00861-20261127/views/scenes.json) · [Reprojection và hai ca sai](../../runs/psg-nav/m1-rgbd-continuity-20261127/dense-frozen-score.json) · [Anchors](../../runs/psg-nav/m1-rgbd-continuity-20261127/dense-frozen-anchor-score.json).

**Kiểm chứng.** Chạy `replay.py`, `score.py`, `anchor-proposals.py`, `score-anchors.py` với `PYTHONPATH=src:.`, output theo từng corpus và khóa SHA riêng. Các bước render, detector, native replay cho cohort dày và ba lượt freeze đều exit 0. Fixture pytest bao phủ pose, occlusion, mask cạnh tranh, bốn frame riêng, cannot-link và prior-anchor consensus. [Lệnh của cohort dày](../../runs/psg-nav/m1-rgbd-dense-00861-20261127/replay-dense.sh) · [SHA](../../runs/psg-nav/m1-rgbd-continuity-20261127/dense-frozen.sha256) · [Hồi quy](../../runs/psg-nav/m1-rgbd-continuity-20261127/regression.log).

**Gate.** Có candidate xuyên category thực trên 00861 với bốn frame riêng. Tập đối chứng vẫn thiếu candidate xuyên category đã phân giải ở cấp raw endpoint pair. Hai lỗi `desk` đã đo là negative controls cần giữ để kiểm tra cách loại match cùng loại vật thể sát nhau. Chưa tạo owner alias, receipt, hay thay config production.

## M1d — kiểm chứng độc lập trên 00839 và 00844

Chọn một episode mỗi scene trước khi xem detector output. Quy tắc chọn là stored geodesic gần 15 m nhất, rồi UID nếu hòa. Bước lấy mẫu là 0,30 m, tối đa 72 view mỗi path. Cả 144 view đạt RGB-D alignment giữa bản annotated và runtime basis. Probe, detector profile, scorer và ngưỡng được khóa SHA trước khi dựng cohort. Dùng cùng native build với A2 tắt. [Manifest](../../runs/psg-nav/m1-independent-20261128/sample-manifest.json) · [Alignment](../../runs/psg-nav/m1-independent-20261128/views/scenes.json) · [SHA lock](../../runs/psg-nav/m1-independent-20261128/protocol.sha256)

Render gọi `sample_views.py --path-step 0.30 --scan-points 0 --headings 6 --max-frames-per-scene 72 --alignment-frames 72` ngoài sandbox, exit 0. Script lần đầu dừng sau detector và qualification vì biến đường dẫn trong heredoc tạo input lock bị thay nhầm. Đã sửa đúng vị trí gán trong shell và resume từ output detector đã ghi đủ. Scorer dùng semantic raster của evaluator sau khi proposals được ghi. Audit lịch sử endpoint dùng toàn bộ annotation GT có đủ pixels và không đưa kết quả trở lại probe. [Replay script](../../runs/psg-nav/m1-independent-20261128/replay-fixed.sh) · [Resume](../../runs/psg-nav/m1-independent-20261128/resume.sh) · [Audit script](../../runs/psg-nav/m1-independent-20261128/audit-controls.py)

| Scene | Accepted revision có lineage | Cùng instance | Khác instance đã xác định | Unresolved | Quan sát đổi label khớp đúng / opportunities |
| --- | ---: | ---: | ---: | ---: | ---: |
| 00839 | 72/72 | 538 | 0 | 295 | 36/67 |
| 00844 | 72/72 | 796 | 0 | 335 | 76/125 |

Mask qualification có 415 matches và 12 physical tracks đổi label. Probe phát hai cặp raw ID trên 00844. Một cặp `basket` được xác nhận theo hai cặp detector masks. Cặp `stool` chưa phân giải theo phép chấm detector, nhưng audit mesh chiếu vào toàn bộ annotation cùng xác nhận một physical instance cho cả hai endpoint. Hai proposal đều cùng native category. Trên 00839, prior-anchor probe có một ca đổi nhãn thực, detector `storage box` nối đúng vào endpoint native `oven` đang tồn tại với hai prior witnesses đã kiểm. Tổng hai scene có 8 prior-anchor proposals đúng và 15 unresolved. [Scorer](../../runs/psg-nav/m1-independent-20261128/summarize.json) · [Anchor score](../../runs/psg-nav/m1-independent-20261128/anchor-score.json)

Audit còn ghi nhận `O(0)` ở 00844 có hai projected mesh observations thuộc hai GT instance ID khác nhau. Cả path vẫn có native lineage hợp lệ. Đây là đối chứng cho việc canonical lineage có thể ổn định trong khi physical association thay đổi. Chưa đủ coverage để lấy 0 lỗi đã phân giải làm tỷ lệ lỗi tổng quát vì 630 liên kết chưa phân giải. Cặp native xuyên category ở cấp alias vẫn chưa lặp lại trên scene độc lập. Chưa bật A2 hoặc receipt production. [Audit lịch sử endpoint](../../runs/psg-nav/m1-independent-20261128/audit-controls.json)

Resume, native replay, reprojection, hai offline scorer, summary và audit đều exit 0. Focused pytest cho cohort, temporal và RGB-D exit 0 với 10 test đạt. [Kết quả khóa SHA](../../runs/psg-nav/m1-independent-20261128/results.sha256) · [Focused tests](../../runs/psg-nav/m1-independent-20261128/focused.log)

## M1d — negative controls và frame trung gian

**Đối chiếu màu.** Probe đo median của sai số RGB max-channel trên các pixel cùng mask và đạt depth tolerance sau khi chiếu. Lấy directional median lớn hơn trong hai hướng. Replay trước/sau khi thêm phép đo trùng tất cả liên kết hình học. Hai ca sai `desk` có RGB residual 5 và 9 trên thang 0–255. Hai chứng cứ cần giữ cho cặp xuyên category `O(16)/O(19)` có residual 12 và 13. Vì vậy một ngưỡng colour residual không thể loại cả hai ca sai và giữ cả hai chứng cứ. Nhánh này chỉ dùng để chẩn đoán. [Đo màu](../../runs/psg-nav/m1-photometric-20261128/dense-score.json) · [Replay](../../runs/psg-nav/m1-photometric-20261128/measure.py)

**Hai frame trung gian.** Với một link nguồn→đích đã có, giữ link nếu ít nhất hai revision khác nhau nằm giữa nguồn và đích có observation khớp với cả hai đầu. Frame sau đích và hai detection trong cùng revision không tăng support. Chỉ lọc links đã đo, không tạo link theo transitive closure. Đề xuất native pair vẫn phải đạt cannot-link và hai cặp witness dùng bốn frame riêng. Quy tắc chọn từ negative controls trên 00861 rồi giữ cố định khi chấm các scene khác. [Filter](../../runs/psg-nav/m1-photometric-20261128/filter.py)

| Cohort | Đúng trước → sau | Sai đã phân giải trước → sau | Unresolved trước → sau | Cross-label đúng trước → sau |
| --- | ---: | ---: | ---: | ---: |
| 00861 dày | 157 → 56 | 2 → 0 | 224 → 74 | 58 → 22 |
| 00839/00844 | 1.334 → 781 | 0 → 0 | 630 → 310 | 112 → 65 |

Cặp `desk/kitchen island` trên 00861 vẫn giữ đúng hai witness pairs 69→81 và 72→82. 00839/00844 giữ hai đề xuất cặp native cùng category. Số đúng mất đi lớn, nên đây là phép lọc thử nghiệm có giảm coverage. Không suy tỷ lệ lỗi từ các link chưa phân giải. [00861](../../runs/psg-nav/m1-photometric-20261128/dense-cycle-score.json) · [00839/00844](../../runs/psg-nav/m1-photometric-20261128/independent-cycle-score.json)

Khi dùng các link đã lọc cho prior anchors, 00861 giữ 3 đề xuất đúng và 2 unresolved từ 8 đúng và 9 unresolved trước lọc. 00839/00844 giữ 7 đúng và 9 unresolved từ 8 đúng và 15 unresolved trước lọc. Ca xuyên category `storage box → oven` ở 00839 vẫn còn. [Anchors 00861](../../runs/psg-nav/m1-photometric-20261128/dense-cycle-anchor-score.json) · [Anchors 00839/00844](../../runs/psg-nav/m1-photometric-20261128/independent-cycle-anchor-score.json)

**Held-out mới 00820/00821.** Manifest chọn một episode mỗi scene theo stored geodesic gần 15 m nhất trước khi render. Dùng `sample_views.py --path-step 0.30 --scan-points 0 --headings 6 --max-frames-per-scene 72 --alignment-frames 72`. Cả 144/144 view đạt alignment và có accepted native lineage. Có tám physical tracks đổi label trong GT qualification. Giữ nguyên rule hai frame trung gian và toàn bộ detector profile. Lọc giữ 219/404 observation links đúng, giảm unresolved từ 385 xuống 169 và giữ 39/69 cross-label links đúng. Cả hai arm đều không có lỗi đã phân giải và không đề xuất raw-ID pair. Prior anchors mất một đề xuất đúng và còn một unresolved. Kiểm thêm toàn bộ endpoint histories chưa thấy raw ID lẫn nhiều instance trên hai path này trong phần có visible support. [Held-out manifest](../../runs/psg-nav/m1-cycle-heldout-20261128/sample-manifest.json) · [Baseline](../../runs/psg-nav/m1-cycle-heldout-20261128/reprojection-score.json) · [Sau lọc](../../runs/psg-nav/m1-cycle-heldout-20261128/summarize-cycle.json) · [Audit](../../runs/psg-nav/m1-cycle-heldout-20261128/audit-cycle.json)

Render, `replay.sh`, scorer, category summary và audit của held-out exit 0. Các lượt đo màu và lọc trên corpus đã khóa đều exit 0. Hồi quy CPU exit 0, 374 đạt và 1 skip. [Held-out replay](../../runs/psg-nav/m1-cycle-heldout-20261128/replay.sh) · [SHA](../../runs/psg-nav/m1-cycle-heldout-20261128/protocol.sha256) · [Hồi quy](../../runs/psg-nav/m1-photometric-20261128/regression.log)

**Gate.** Trên dev, có quy tắc loại cả hai ca sai đã biết và giữ candidate xuyên category chính. Rule giảm coverage đáng kể và chưa có native cross-category candidate để xác minh trên hai scene held-out mới. Kết quả hiện đủ giữ hai ca sai làm regression và tiếp tục đo targeted held-out. Chưa tạo owner alias hay receipt và chưa đổi production.

## M1d — kiểm tra số cơ hội nối hai ID native

Audit offline đối chiếu các physical tracks đã đổi detector label với A1 trên đúng source frame, sau khi kiểm khóa pose, detector và RGB-D. Với mỗi track, audit lần lượt đếm các cặp quan sát nối hai raw ID khác native category trong cửa sổ 12 revision, số cặp còn lại sau geometry, rồi số cặp có corroboration. Một raw-ID pair cần hai cặp quan sát không dùng chung revision và phải qua same-frame cannot-link. Semantic GT chỉ tham gia audit sau khi các đề xuất đã được ghi. [Script và lệnh tái lập](../../runs/psg-nav/m1-opportunity-audit-20261128/reproduce-all.sh) · [Audit các lượt đã khóa](../../runs/psg-nav/m1-opportunity-audit-20261128/report.json)

- **00820/00821.** Trong tám track đổi nhãn, ba track không có A1 endpoint, ba chỉ có một endpoint và hai có endpoint xuyên native category. Cả tám đều thiếu hai cặp quan sát độc lập ngay trước bước geometry. Ở 00820, mọi cặp giữa `bed` O(10) và `storage box` O(14) của `hm3d:296` đều dùng revision 71. Track `hm3d:334` chỉ có một cặp quan sát. Kết quả này giải thích vì sao lượt held-out trước không đo được khả năng xác nhận native alias.
- **00839/00844.** `hm3d:42` ở 00839 có ba cặp quan sát nối `oven` O(0) với `storage box` O(5) trước khi xét geometry. Geometry và corroboration đều giữ đúng một cặp, revision 3 → 15. Đây là track duy nhất trong 12 track đổi nhãn của hai scene đủ hai cặp độc lập trước geometry. Không có proposal phát ra cho track này.
- **Đối chứng 00861.** Audit tái lập hai cặp corroborated 69 → 81 và 72 → 82 nối O(16) với O(19) của `hm3d:310`. Lệnh xác minh audit exit 0, cùng hồi quy CPU 374 đạt và 1 skip. [Kiểm tra kết quả](../../runs/psg-nav/m1-opportunity-audit-20261128/verify.py) · [Hồi quy](../../runs/psg-nav/m1-opportunity-audit-20261128/regression.log)

Từ audit, chọn lại hai đường đã có dấu hiệu tách ID ở 00820 và 00839, giảm bước lấy mẫu từ 0,30 m xuống 0,15 m. Đây là phép đo chẩn đoán trên các đường đã xem kết quả. Giữ detector profile, A1 và rule 12 revision. Render 142 view ở 00820 và 156 view ở 00839, tất cả đạt alignment và có lineage. Trong 11 track đổi nhãn, ba track có quan sát nối raw ID xuyên category trong cửa sổ. Cả ba thiếu hai cặp quan sát độc lập trước geometry. Rule corroboration giữ 1.179/1.908 liên kết quan sát đúng và 64/129 liên kết đúng xuyên detector label. Có 993 unresolved sau lọc và không có lỗi trong phần đã phân giải. Cả hai arm không đề xuất native pair. [Render](../../runs/psg-nav/m1-opportunity-dense-20261128/render.sh) · [Replay](../../runs/psg-nav/m1-opportunity-dense-20261128/replay.sh) · [Điểm](../../runs/psg-nav/m1-opportunity-dense-20261128/summarize-cycle.json) · [Audit đầy đủ](../../runs/psg-nav/m1-opportunity-audit-20261128/report-all.json)

Chạy lại native admission A2 trên cùng 298 nguồn. A2 OFF và ON trùng 298/298 hash graph và 298/298 kết quả A1. Cả 596 revision ở hai arm có lineage. Báo cáo JSON native của hai arm trùng SHA-256. Các bước render, detector, qualification, hai lượt native, scorer và đối chiếu đều exit 0 theo exit file riêng. Shell bọc lượt replay đầu trả 1 khi ghi exit tổng hợp do biến `status` dành riêng của zsh. Lệnh xác minh sau đó kiểm từng exit file và SHA thành công. [Đối chiếu](../../runs/psg-nav/m1-opportunity-dense-20261128/compare-a2.json) · [Lệnh xác minh](../../runs/psg-nav/m1-opportunity-dense-20261128/verify-results.sh) · [SHA](../../runs/psg-nav/m1-opportunity-dense-20261128/results.sha256)

### Đối chứng cửa sổ 24 revision

Với cùng pose, detector output và native graph của lượt 0,15 m, tăng riêng cửa sổ offline từ 12 lên 24 revision. Đây là phép thử chẩn đoán sau audit để xấp xỉ khoảng cách di chuyển của cửa sổ cũ ở bước 0,30 m. Số revision không quy đổi chính xác thành khoảng cách vì mỗi điểm có nhiều heading.

- **00839.** Cửa sổ 24 và rule corroboration giữ cặp `oven` O(0) và `storage box` O(5), với hai witness độc lập 1 → 21 và 3 → 24. Hai endpoint đều được evaluator gán cho `hm3d:42`. Audit visible mesh riêng xác nhận đến revision 24 có 10 quan sát O(0) và 11 quan sát O(5) cùng instance. Trong toàn đường, 10 và 16 quan sát có thể xác định của hai endpoint vẫn thuộc duy nhất instance đó. Geometry thô còn đề xuất cặp O(12)/O(18) chưa xác định; rule corroboration loại cặp này. 00820 không đề xuất native pair. [Kết quả chấm](../../runs/psg-nav/m1-opportunity-window-20261128/m1-opportunity-dense-20261128-cycle-score.json) · [Lịch sử endpoint](../../runs/psg-nav/m1-opportunity-window-20261128/endpoint-history.json)
- **Đối chứng 00861.** Geometry với cửa sổ 24 thêm một liên kết sai `desk` → `dining table` ở revision 40 → 63. Corroboration loại lỗi mới và hai lỗi `desk` đã biết, giữ 97 liên kết đúng, 131 unresolved và giữ cặp O(16)/O(19). Trên hai đường lấy mẫu dày, corroboration ở cửa sổ 24 giữ 2.403 liên kết đúng, 1.948 unresolved và không có lỗi trong phần được phân giải. [So sánh 12 và 24](../../runs/psg-nav/m1-opportunity-window-20261128/compare.json)

`bash runs/psg-nav/m1-opportunity-window-20261128/run.sh` exit 0. `compare.py` exit 0 sau khi trỏ đến đúng scorer archive cho đối chứng 00861. Đối chiếu xác nhận các cạnh của lượt 12 vẫn có mặt và giữ nguyên bằng chứng ở lượt 24. Audit lịch sử và kiểm SHA exit 0. Kết quả bổ sung một cặp native xuyên category đúng trên dữ liệu thật. M1d cần lặp phép thử với window được khóa trước trên held-out mới và chứng minh owner xử lý duplicate. [Lệnh replay](../../runs/psg-nav/m1-opportunity-window-20261128/run.sh) · [SHA kết quả](../../runs/psg-nav/m1-opportunity-window-20261128/results.sha256) · [SHA audit](../../runs/psg-nav/m1-opportunity-window-20261128/verification.sha256)

## M1 — lượt nghiệm thu held-out 00823 và 00827

Hai episode HM3D val được chọn theo stored geodesic gần 8 m trong hai scene chưa dùng để phát triển probe PSG-Nav. Hai scene dự kiến ban đầu 00816/00817 thiếu semantic assets local, nên thay bằng 00823/00827 trước render và trước mọi kết quả detector. Khóa manifest, A1, bước render 0,15 m, cửa sổ 24 revision, hai revision trung gian, hai witness với bốn revision khác nhau và same-frame cannot-link trước chạy. A2 OFF và ON dùng cùng nguồn, detector và linker A1. GT chỉ được đọc sau khi tạo đề xuất hoặc trong tiến trình evaluator độc lập. [Tiêu chí đã khóa](../../runs/psg-nav/m1-acceptance-20261128/gate-lock.txt) · [Manifest](../../runs/psg-nav/m1-acceptance-20261128/sample-manifest.json) · [SHA giao thức](../../runs/psg-nav/m1-acceptance-20261128/protocol.sha256)

| Điều kiện nghiệm thu | Kết quả |
| --- | --- |
| Fixture owner giữ một ID khi đổi nhãn và giữ riêng các vật thể cạnh tranh | **Đạt.** A2 OFF tạo ba ID cho một mask đổi nhãn. A2 ON giữ O(0), giữ hai endpoint cho fixture liền kề và giữ hai nhãn độc lập trên fixture cạnh tranh. [OFF](../../runs/psg-nav/m1-acceptance-20261128/controls-0/report.json) · [ON](../../runs/psg-nav/m1-acceptance-20261128/controls-1/report.json) |
| Lặp bằng chứng nối xuyên category trên held-out mới | **Đạt phép lặp.** Ở 00827, `chair` O(12), `storage box` O(17) và `desk` O(19) đều là `hm3d:93`. Hai cặp O(12)/O(17) và O(12)/O(19) đều có hai witness độc lập và lịch sử endpoint nhất quán đến cutoff. Hai cặp thuộc cùng một physical track. 00823 không có đề xuất native pair. [Bằng chứng](../../runs/psg-nav/m1-acceptance-20261128/cycle-summary.json) · [Lịch sử endpoint](../../runs/psg-nav/m1-acceptance-20261128/audit-cycle.json) |
| Native owner giảm track bị cấp nhiều ID | **Không đạt.** A2 OFF/ON khớp 312/312 graph hashes và A1 assignments. Cả hai vẫn có ba split tracks, gồm `hm3d:93` với ba ID. Hai arm có 624/624 revision có lineage. [So sánh](../../runs/psg-nav/m1-acceptance-20261128/compare-a2.json) · [Điểm track](../../runs/psg-nav/m1-acceptance-20261128/track-metrics.json) |
| Receipt writer với exact token và owner continuity | **Chờ identity gate.** Chưa triển khai M1e. |

Cả 312 view đạt RGB-D alignment. Corroboration có 1.897 liên kết quan sát đúng, gồm 288 xuyên detector label, và 695 unresolved. Không thấy liên kết sai trong phần phân giải được. Biên tỷ lệ lỗi theo unresolved là 0–31,03% ở 00823 và 0–20,86% ở 00827. Trong hai native pair ở 00827, cả hai được adjudicate đúng, unresolved bằng 0; cỡ mẫu chỉ có một physical track. Native pair false bound ở 00823 không có denominator. IDF1 trên 535 observation được match GT mask duy nhất tăng từ 31,70% lên 58,68% ở 00823 và từ 35,51% lên 58,48% ở 00827 khi chuyển A0 sang A1. A2 giống A1, kể cả số switch giữa các observation đã có association là 1 và 8 tương ứng. [Scorer](../../runs/psg-nav/m1-acceptance-20261128/score-tracks.py) · [Kết quả gate](../../runs/psg-nav/m1-acceptance-20261128/gate-result.json)

Các lệnh `render.sh`, `owner-controls.sh`, `replay.sh`, `replay-a2.sh` và `finish-acceptance.sh` trong run directory hoàn tất exit 0. Kiểm SHA exit 0. Hồi quy CPU PSG-Nav, RG, Hydra và Paper ObjectNav exit 0, 374 đạt và 1 skip. **M1 chưa được nghiệm thu.** Kết quả held-out chứng minh detector observations đủ để nối một vật thể xuyên category, còn A2 exact mesh admission vẫn để vật thể đó phân mảnh trong native graph. [Lệnh xác minh](../../runs/psg-nav/m1-acceptance-20261128/finish-acceptance.sh) · [SHA](../../runs/psg-nav/m1-acceptance-20261128/pin-check.log) · [Hồi quy](../../runs/psg-nav/m1-acceptance-20261128/regression.log)

## M1d — A3 native owner từ bằng chứng RGB-D

A3 dùng phép đối chiếu causal trên cửa sổ 24 revision trong replay. Mỗi cặp cần hai witness qua bốn revision riêng và hai revision trung gian cho từng quan sát. A1 được tính lại trên arm A3. Chỉ dùng những revision đã được owner chấp nhận. Nếu nhiều cặp đủ chứng cứ cùng đòi một endpoint, selector giữ pending. Cannot-link từ các revision trước được truyền qua alias đã commit. Hai raw endpoint của mỗi cặp phải còn sống và có category native khác nhau. Selector giữ ID cấp trước và không dùng alias đã retire làm witness mới. [Selector](../../tools/psg_nav/owner_admission.py) · [Tests](../../tests/test_psg_owner_admission.py)

Bản build cô lập thêm một request đồng bộ, gắn với exact publication trước đó và timestamp tiếp theo. Hydra chạy callback frontend trên thread riêng rồi join, nên phiên bản dùng thread-local đã tái lập hai request nhưng không commit. Chuyển request sang một slot có mutex trong process replay một owner. Frontend chỉ nhận đúng timestamp khi journal và cờ A3 bật, kiểm endpoint và mesh index, gộp geometry qua native graph rồi ghi event merge vào journal. Stamp sai hoặc endpoint biến mất không phát event. Phiên bản dùng production worker vẫn cần một đường nhận evidence có lifecycle theo pipeline. [Patch native](../../tools/native/hydra_object_journal/rgbd_owner_merge.patch) · [Native RED](../../runs/psg-nav/m1-owner-a3-20261128/native-red.json)

Trên regression 00823/00827, A3 OFF khớp 312/312 graph hashes và A1 baseline. Journal fold thành công trên 624 revision của hai arm. A3 ON ghi O(17) → O(12) ở revision 134 và O(19) → O(12) ở revision 147 cho `hm3d:93` tại 00827. Sau khi resolve alias, track trong evaluator từ ba ID về một O(12). Audit mesh xác nhận hai commit đều cùng physical instance và chưa thấy endpoint lẫn instance trong phần đã phân giải. Số split tracks trên hai scene giảm 3 → 2. IDF1 có điều kiện trên unique mask observations ở 00827 tăng từ 58,48% lên 60,27% khi resolve alias cuối replay. [Native GREEN](../../runs/psg-nav/m1-owner-a3-20261128/native-green.json) · [Audit commit](../../runs/psg-nav/m1-owner-a3-20261128/arm-1-audit.json) · [Điểm track](../../runs/psg-nav/m1-owner-a3-20261128/arm-1-score.json)

**Held-out mới 00824/00829.** Khóa build và hai episode trước render. Cả 300 view đạt alignment và 600 revision của hai arm có lineage. Có 19 physical tracks đổi detector label. Corroboration giữ 4.690 observation links đúng và 4.734 unresolved, với 0 lỗi trong phần phân giải. A3 không phát lệnh merge. Hai arm trùng 300/300 graph hash và vẫn có bốn split tracks. Candidate duy nhất ở 00829 là O(1)/O(2), cùng native category và chưa phân giải được bằng GT. Owner đã delete O(1) ở revision 7 trước khi đủ hai witness. [Giao thức khóa](../../runs/psg-nav/m1-a3-heldout-20261128/gate-lock.txt) · [Kết quả held-out](../../runs/psg-nav/m1-a3-heldout-20261128/verification.json)

Replay chẩn đoán 00839 và 00861 cùng binary có exit 0 và không phát lệnh merge. Journal cho thấy hai ca xuyên category đã xác nhận offline đều mất endpoint trước khi đủ bằng chứng causal. Ở 00839, O(0) bị delete tại revision 21, trong khi witness thứ hai đến revision 24. Ở 00861, O(16) bị delete tại revision 81, trước witness hoàn tất tại revision 82. Cơ chế hiện tại yêu cầu hai endpoint cùng tồn tại lúc commit, nên hai ca vẫn pending. [00839](../../runs/psg-nav/m1-owner-a3-20261128/diagnostic-00839/native-link-arms.json) · [00861](../../runs/psg-nav/m1-owner-a3-20261128/negative-00861/native-link-arms.json)

`build.py`, hai arm regression, audit native và hồi quy CPU đều exit 0. Hồi quy có 378 đạt và 1 skip. Lượt chấm held-out đầu exit 1 do scorer tìm trường alias đã tính sẵn mà baseline gốc không xuất. Scorer lưu alias từ chính journal fold và chấm lại cùng hai output, exit 0. Kiểm SHA của binary, giao thức và kết quả exit 0. A3 đã giảm phân mảnh trên regression thật. Nghiệm thu M1 còn thiếu một owner commit đúng trên held-out mới và M1e receipt. [Lệnh held-out](../../runs/psg-nav/m1-a3-heldout-20261128/finish.sh) · [Lệnh chấm lại](../../runs/psg-nav/m1-a3-heldout-20261128/resume-scoring.sh) · [Test log](../../runs/psg-nav/m1-owner-a3-20261128/regression.log)

## M1 — nghiệm thu A4 và confirmed receipt

**Nghiệm thu trên replay cô lập.** Cấu hình nghiệm thu kết hợp exact-mesh retention ở frontend với `reconcile` cho ID đã xóa. Native journal v2 cho phép tombstone tồn tại tối đa 24 accepted revision để nối với một live ID mới hơn. Owner xác nhận endpoint, tuổi tombstone và category trước khi ghi alias. ID đã xóa không được đưa trở lại graph. Fold kiểm journal, build và exact revision. Cờ chỉ bật trong run nghiệm thu. [Patch](../../tools/native/hydra_object_journal/retired_object_alias.patch) · [Biên bản machine-readable](../../runs/psg-nav/m1-owner-a4-20261128/m1-signoff.json)

| Điều kiện | Kết quả |
| --- | --- |
| Fixture đổi nhãn, vật liền kề và ứng viên cạnh tranh | Hai arm native exit 0. Fixture đổi nhãn từ ba ID về một ID; fixture liền kề giữ hai endpoint; fixture cạnh tranh giữ hai nhãn độc lập. [Controls ON](../../runs/psg-nav/m1-owner-a4-20261128/controls-1/report.json) |
| Lặp case ID đã bị xóa trước witness thứ hai | 00839 reconcile O(0) → O(5) ở revision 25, đúng `hm3d:42`. 00861 reconcile O(16) → O(19) ở revision 83, đúng `hm3d:310`. Cả hai giữ graph hash và giảm một split track. [00839](../../runs/psg-nav/m1-owner-a4-20261128/case-00839-verification.json) · [00861](../../runs/psg-nav/m1-owner-a4-20261128/case-00861-verification.json) |
| Held-out owner continuity | 739 view ở năm scene đã khóa, 1.478 revision có lineage qua hai arm. Cấu hình nghiệm thu khớp baseline về graph hash, objects, visible mesh và A1. 00853 reconcile `cabinet` O(27) → `bed` O(29), đúng cùng `hm3d:520`. Split tracks trên qualified detector subset giảm 11 → 10. Có một owner association đúng, không có association đã commit sai hoặc unresolved. [427 view](../../runs/psg-nav/m1-owner-a4-20261128/accepted-primary-verification.json) · [312 view](../../runs/psg-nav/m1-owner-a4-20261128/accepted-receipt-verification.json) |
| M1e receipt và unique source | `EvidenceProducer` thử nghiệm phát đúng một `native_confirmed` receipt cho detection 2 ở revision 139, canonical O(29). Kiểm độc lập đối chiếu current accepted prefix, epoch, owner event v2, lineage SHA, dữ liệu crop và detector output. Mask IoU 0,959 với `hm3d:520`. Retry không ghi lại receipt. Cấu hình không có confirmation provider tiếp tục xuất manifest hiện tại. [Receipt verifier](../../runs/psg-nav/m1-owner-a4-20261128/accepted-receipt-verification-source.json) · [Producer](../../src/neusymnav/reasoninggraph/producer.py) |

Nhánh A3/A4 gộp geometry của hai node đang sống bị loại khỏi cấu hình nghiệm thu. Ở 00835, merge O(3) → O(0) đúng instance, nhưng replay về sau có ordinary native merge làm `hm3d:209` và `hm3d:211` cùng resolve về O(17). Cấu hình nghiệm thu chỉ dùng exact-mesh retention lúc admission và nối alias sau delete. Candidate khó vẫn pending. 4.716 observation candidates đúng, 3 sai và 1.913 unresolved trước owner admission. Tỷ lệ sai có biên từ 3/6.632 đến 1.916/6.632. Cả ba candidate sai đều không được owner hoặc receipt writer xác nhận. Độ phủ hold-out của owner còn thấp với một ca commit đúng. [Đối chứng nhánh live](../../runs/psg-nav/m1-owner-a4-20261128/fresh-1-visible.json) · [Chi tiết sign-off](../../runs/psg-nav/m1-owner-a4-20261128/m1-signoff.json)

Build native, controls, hai arm nghiệm thu, `final-verify.sh` và kiểm SHA exit 0. Hồi quy CPU PSG-Nav/RG/Hydra/Paper ObjectNav exit 0 với 393 test đạt và 1 skip. Lượt bổ sung khôi phục từ input lock lưu theo tên cohort. Lượt receipt cuối sửa biến cục bộ che trường journal trong bản replay đầu, rồi chạy lại từ nguồn khóa và chấm độc lập. Kết quả nghiệm thu áp dụng cho profile replay opt-in và đủ để bắt đầu M2. Runtime production vẫn cần cấp proof qua callback từ matcher native theo cùng contract trước khi bật xác nhận trực tiếp. [Lệnh nghiệm thu](../../runs/psg-nav/m1-owner-a4-20261128/final-verify.sh) · [Hồi quy](../../runs/psg-nav/m1-owner-a4-20261128/m1-final-regression.log) · [SHA](../../runs/psg-nav/m1-owner-a4-20261128/m1-signoff.sha256)

## M2–M5 — phiếu, graph store, truy vấn và Paper shadow

| Mốc | Kết quả kiểm chứng |
| --- | --- |
| M2 | Core hard votes dùng confirmed receipt của M1, khóa taxonomy, dedup theo run, FrameKey và detection ID. Fixture kiểm unavailable, 2:1, entropy nats, tie, unknown và rollback khi conflict. RED exit 2, GREEN exit 0 với 13 test. [Core](../../src/neusymnav/reasoninggraph/semantic_beliefs.py) · [Log](../../runs/psg-nav/m2-m3-20261128/m2-green.log) |
| M3 | Store xử lý ordered revision, alias `reconcile` đã chứng nhận, delete và invalidate vote khi gặp native merge thiếu proof. Con chỉ nhận vote sau khi owner công nhận continuity. Checkpoint seal/restore giữ nguyên digest. Native replay exit 0, graph, prefixes và A0/A1 khớp 312/312 revision. Một receipt thật ở revision 139 vào O(29). Runtime shadow đọc exact session token và journal. Launcher mặc định tắt, với proof provider được cấp trong replay. [Store](../../src/neusymnav/reasoninggraph/semantic_belief_store.py) · [Phiếu và checkpoint](../../runs/psg-nav/m1-owner-a4-20261128/m3-store/belief-verification.json) · [Parity](../../runs/psg-nav/m2-m3-20261128/m3-graph-parity.json) |
| M4 | API belief, probability, uncertainty, evidence và room/subgraph chạy trên đúng projection hiện có. Native replay exit 0. Alias về O(29), xác suất `bed` bằng 1, evidence page có một receipt và token sai revision trả stale. Test truy vấn giữ nguyên topology và kiểm cursor khi đổi scope. [API](../../src/neusymnav/backends/hydra/semantic_queries.py) · [Replay](../../runs/psg-nav/m1-owner-a4-20261128/m4-query/belief-verification.json) |
| M5 | Thêm join chính xác từ confirmed receipt sang CID đã được Paper xác minh, và shadow giữ quyết định deterministic. Replay exit 0, CID 2 khớp O(29) từ cùng detection và mask. Lượt này có một receipt; ngưỡng replay join dùng 1 observation, default thử nghiệm yêu cầu 2. Smoke Habitat OFF/shadow đều exit 0. Action sequence, pose, planner, frame pins và simulator execution receipt khớp qua 28 bước. Parity tổng thể exit 2, `unavailable`, vì Paper chưa xuất receipt requested-vs-applied và safety reasons của guard ngoài simulator. Shadow run cũng không có native publication tap online. Replay native từ archive Paper sau episode exit 0, cả 3 frame đã giữ được accept. Chưa có bằng chứng B2 live. [Join replay](../../runs/psg-nav/m1-owner-a4-20261128/m5-join/belief-verification.json) · [Parity live](../../runs/psg-nav/m2-m3-20261128/paper-parity.json) · [Paper native replay](../../runs/psg-nav/m2-m3-20261128/paper-native-replay/summary.json) |
| M6 | Chờ gate M5. Chưa chạy ablation khi B2 live chưa có xác nhận. |

Các lệnh `run-m3.sh`, `run-m4.sh`, `run-m5.sh` dùng cùng input lock A4 và đọc RGB-D, pose, detector output, journal qua native replay. Hồi quy CPU PSG-Nav/RG/Hydra/Paper exit 0 với 404 test đạt và 1 skip. [Kiểm chứng tổng hợp](../../runs/psg-nav/m2-m3-20261128/verification.json) · [Hồi quy](../../runs/psg-nav/m2-m3-20261128/final-regression.log)

## M5 — native publication và confirmed receipt trong Paper live

Paper shadow gửi Observation và DetectionBatch đang dùng qua hàng đợi nền một mục. Native sidecar lấy calibration từ pose camera thật và cadence từ cấu hình Hydra. Nó chỉ publish khi semantic store đã nhận exact accepted token và lineage. Đường điều khiển đọc snapshot đã có sẵn, loại snapshot đến từ frame tương lai hoặc cũ quá 16 frame. Candidate ranking chỉ áp dụng cho tập đã qua xác minh của Paper. [Sidecar](../../src/neusymnav/objectnav/paper/native_tap.py) · [Policy](../../src/neusymnav/objectnav/paper/b0.py)

Provider chỉ xác nhận native ID còn hoạt động khi mask có mesh support cùng depth và hai accepted anchors khác revision. Mỗi anchor cần hai frame trung gian, phép chiếu RGB-D hai chiều và cùng native endpoint. Thiếu page, cạnh tranh endpoint hoặc journal làm đổi alias sẽ giữ pending hoặc xóa lịch sử liên quan. Mesh và dữ liệu GT không vào luồng điều khiển. GT chỉ dùng để chấm sau rollout. [Confirmation](../../src/neusymnav/reasoninggraph/live_instance_confirmation.py)

| Lượt chạy | Kết quả |
| --- | --- |
| 00862, 28 bước, cadence 1,0 s | Ba publication native, shutdown sạch. OFF/shadow khớp action, pose, planner, source pins, collision và simulator execution. Parity tổng thể exit 2 vì Paper thiếu receipt requested-vs-applied và safety reason từ guard riêng. [Parity](../../runs/psg-nav/m5-live-20261128/parity-28.json) |
| 00853, 72 bước, cadence 1,0 s | Tám publication, 11 native claims và 0 proof. [Verification](../../runs/psg-nav/m5-live-20261128/verification.json) |
| Cùng 00853, 72 bước, cadence 0,2 s tại config cô lập | Hydra accept 36 revision, Paper thấy 35 publication trước các lần quyết định, và producer ghi sáu receipt. OFF/shadow khớp 72 action, pose, planner, input pins và simulator execution. Parity tổng thể exit 2 với hai trường guard vẫn unavailable. [Verification](../../runs/psg-nav/m5-live-20261128/verification.json) · [Parity](../../runs/psg-nav/m5-live-20261128/dense-parity.json) |

Render ngoại tuyến chấm đúng pose và input RGB-D cho cả 6/6 receipt. Năm receipt của O(6) trỏ cùng `hm3d:287` với IoU 0,981–0,989. Receipt `sofa` O(20) đạt IoU 0,471 và giữ unresolved theo ngưỡng 0,5. Hai lượt 72 bước tìm `bed`, chưa có Paper CID đủ điều kiện để so thứ hạng bằng receipt live. [Audit semantic](../../runs/psg-nav/m5-live-20261128/semantic-audit.json)

Lệnh Habitat dùng một GPU mỗi lượt. Môi trường ROS được nạp trước khi bật kiểm biến shell. Lượt chuẩn bị audit đầu cần kiểm only valid depth vì adapter Hydra đặt các pixel depth invalid về 0. Sau sửa, CPU preparation và native semantic render đều exit 0. [Lệnh chấm](../../runs/psg-nav/m5-live-20261128/render-audit.sh)

M5 đã có native publisher trong episode và proof provider cho stable ID. Gate B2 vẫn chờ một join live với CID đích đã được Paper xác minh và trace safety cấp guard. M6 tiếp tục chờ.

Đối chứng 00853 bắt đầu gần `bed` hơn cũng hoàn thành 72 bước, Paper đọc 35 publication. Có 33 claims, 3 frame mesh chưa đủ dữ liệu và 0 receipt. Candidate memory ghi nhận năm CID nhưng không có CID đích đã xác minh để so thứ hạng. [Lượt phát triển gần goal](../../runs/psg-nav/m5-live-20261128/goal/trajectories.jsonl)

Lượt phát triển bổ sung chọn một UID từng có Paper B0 STOP xác nhận trong lịch sử. Ở 00847, Paper thấy 25 publication và chọn CID 8 tại bước 38 theo policy cũ. Native provider có một receipt `door`, nên semantic rank của CID đích `bed` trả unavailable. Rollout kết thúc bằng STOP từ policy xác minh cũ tại bước 53, 0 collision. [Trace CID đích](../../runs/psg-nav/m5-live-20261128/verified-goal/trajectories.jsonl) · [Tổng hợp](../../runs/psg-nav/m5-live-20261128/verification.json)

## M5 — Causal join tại quyết định Paper và đối chứng MotionGuard

Cohort phát triển lấy ba episode từ Paper DEV60 đã có `confirmed_target`. Chọn từ lịch sử số frame mà detector từng gán vào CID đích trước quyết định. Thử cadence Hydra 0,2 s cho cả ba, sau đó 0,1 s cho hai episode 00802. Giữ ngưỡng belief 0,5 và ngưỡng support từ hai phiếu. [Manifest và cấu hình pin](../../runs/psg-nav/m5-target-window-20261128/inputs.sha256)

| Episode | Kết quả trước hoặc tại quyết định |
| --- | --- |
| 00847 `bCPU9suPUw9/0`, lượt cũ | Paper thấy CID 8 trên frame 36–38 và chọn ở bước 38. Hydra nhận duy nhất frame 37 có CID này trong khoảng đó. Receipt duy nhất là `door` ở frame 23. [Audit](../../runs/psg-nav/m5-target-window-20261128/00847-audit.json) |
| 00802 `wcojb4TFT35/3#4`, đích `bed` | Ở 0,2 s có bốn frame chứa CID 2 được Hydra accept đến bước 37. Ở 0,1 s có tám, query thực tế dùng revision 35 từ frame 36. Cả hai lượt có zero receipt khớp CID 2 trước quyết định. |
| 00847 `bCPU9suPUw9/5`, đích `bed` | Lượt 0,2 s giữ fallback tại bước 55, zero confirmed receipt. |
| 00802 `wcojb4TFT35/4#5`, đích `sofa` | Ở 0,2 s, cả chín receipt O(13) khớp mask Paper CID 6. Publication gần nhất được ghi ở bước 59 chứa bốn phiếu `chair` và hai phiếu `sofa`. Ở 0,1 s, query chính xác tại bước 59 dùng revision 58, O(15) có 9 phiếu `chair` và 5 phiếu `sofa` theo đối chiếu receipt. Shadow giữ baseline ở cả hai lượt. [0,2 s](../../runs/psg-nav/m5-target-window-20261128/shadow-audit.json) · [0,1 s](../../runs/psg-nav/m5-target-window-20261128/fast-shadow-audit.json) |

Audit offline ở cadence 0,2 s chấm 9/9 ảnh cùng `hm3d:427` (`armchair`), IoU 0,956–0,992. RGB/depth alignment khớp 9/9 source. Paper v2 đánh dấu `armchair` là near miss của `sofa`. Kết quả chứng minh continuity của cùng instance qua đổi label và cho một ca kiêng xếp ứng viên `sofa`. Chưa có ca B2 áp dụng rank. [Semantic audit](../../runs/psg-nav/m5-target-window-20261128/semantic-audit.json)

Trace mới ghi revision, input prefix hash và source/policy frame của chính query được dùng. Ở 00802 `/4#5`, đầu bước 59 thấy revision 57 và điểm xếp hạng đã dùng revision 58. Unit RED exit 1 ở field chưa có. Hồi quy GREEN exit 0, 409 đạt và 1 skip. [RED](../../runs/psg-nav/m5-target-window-20261128/trace-red.log) · [GREEN](../../runs/psg-nav/m5-target-window-20261128/regression.log)

Paper B0 điều khiển Habitat bằng discrete action và ghi simulator receipt. Bằng chứng yêu cầu, quyết định guard và worker response có entrypoint riêng là `tools/objectnav/run_episodes.py --trace` qua `LockstepRunner`. Protocol lockstep là baseline riêng cho việc kiểm chứng guard.

Probe `bed` có chuỗi RGB-D tiềm năng ở frame 35–36 dưới giả định bỏ qua competing detections và owner. A0 chỉ cho thấy spatial candidate O(10) ở hai frame 33 và 35 của đúng mask CID 2. Spatial candidate riêng lẻ chưa đủ chứng nhận continuity native. [Probe offline](../../runs/psg-nav/m5-target-window-20261128/bed-rgbd-audit.json)

| Lệnh | Exit | Kết quả |
| --- | --- | --- |
| `bash run.sh shadow` và `bash run.sh off` | 0 mỗi arm | 178 bước × 2. Action, pose, planner, STOP, input pin và simulator execution khớp. |
| `bash run-fast.sh shadow` và `bash run-fast.sh off` | 0 mỗi arm | 109 bước × 2, cùng các trường Paper khớp. |
| `tools/reasoninggraph/check_paper_parity.py --position-tolerance 1e-6`, hai cặp profile | 2 mỗi cặp | Guard requested/applied và guard safety reason unavailable ở Paper. [0,2 s](../../runs/psg-nav/m5-target-window-20261128/parity.json) · [0,1 s](../../runs/psg-nav/m5-target-window-20261128/fast-parity.json) |
| `PYTHONPATH=src .venv/bin/python prepare-semantic-audit.py` và `bash render-audit.sh` | 0 mỗi lệnh | 9 source và mask digest khớp, GT chỉ đọc offline. |
| `bash guard-smoke.sh` | 0 sau khi truyền `--habitat-data` | 8/8 cycles có trace. Guard trả `footprint_not_observed` ở chu kỳ 0, chặn yaw request. Executor xác nhận zero command. Bảy chu kỳ sau executor xác nhận quay và pose đo được đổi yaw. Baseline smoke có giới hạn 8 cycles và tolerance unknown bằng 0. [Lượt lỗi do path mặc định](../../runs/psg-nav/m5-target-window-20261128/guard-smoke-default-path.log) · [Trace](../../runs/psg-nav/m5-target-window-20261128/guard-smoke/trace/hm3d_v2_val_wcojb4TFT35_3_4-e678bb01dc53.jsonl) |

Wrapper và log ở `runs/psg-nav/m5-target-window-20261128/`. Gate B2 còn cần causal rerank và A/B trên runner mang MotionGuard thật. Lượt lockstep là baseline smoke, chưa có consumer xác suất. M6 chờ gate này.

## M5 — Nghiệm thu B2 trên lockstep có MotionGuard

`tools/objectnav/run_episodes.py` hỗ trợ ba chế độ riêng cho B0 lockstep. `off` là mặc định. `shadow` chạy cùng tap và dry-run reachability với planner nhưng áp dụng CID deterministic. `probabilistic` dùng rank khi có CID đã confirmed, đủ phiếu và có đường theo planner hiện có. Query immutable được chuẩn bị phía native sidecar. Token hiện hành được đọc theo try-lock và thiếu bằng chứng thì fallback. Join kiểm toàn bộ roster belief có giới hạn, gồm cả owner dưới ngưỡng rank, và theo alias của CID đã merge. Planner dùng chung logic `step_toward` và kiểm tra reachability đọc riêng. Lệnh vẫn qua MotionGuard và actuator. Xác minh đích vẫn chạy qua FACE, VERIFY và STOP cũ.

Probe `wcojb4TFT35/1#4` 335 cycles cho OFF/shadow parity qua guard, pose và executor. B2 fallback ở bước 66 vì chưa có đủ phiếu và ở bước 285 vì publication cũ quá 2 s. Receipt `sofa` gần nhất còn thuộc CID 5 đã bị reject. Verifier exit 2 cho probe này. [Probe](../../runs/psg-nav/m5-acceptance-20261128/verify.json)

Probe tiếp theo trên `wcojb4TFT35/0#3` thấy chọn CID 2 ở cycle 85 từ query revision 20. Native đã lưu một receipt `television` cùng CID tại revision 15. Receipt thứ hai đến ở revision 21, sau khi policy đã chọn. Thay đổi tiếp theo chỉ xếp công việc sidecar sớm ngay sau khi detector tính xong, trước thời gian mô phỏng release. Policy yêu cầu source frame đã release và tuổi tối đa 2 s trước khi đọc rank. Cấu hình detector latency giữ 400 ms. [Lượt chẩn đoán](../../runs/psg-nav/m5-acceptance-20261128/dev-positive/probabilistic/trajectories.jsonl)

Profile nghiệm thu lockstep dùng DEV UID `hm3d_v2/val/wcojb4TFT35/0#3`, giới hạn 210 cycles và cadence host cố định 0,42 s cho ba arm. Cadence này độc lập trạng thái detector và Hydra, đồng thời giữ nguyên clock mô phỏng, detector latency, TTL và MotionGuard. Lượt unpaced kết thúc đúng STOP và có 166 chu kỳ OFF/shadow khớp. B2 unpaced fallback vì receipt frame 21 chưa kịp publish. [Profile](../../runs/psg-nav/m5-acceptance-20261128/paced/lockstep.json) · [Unpaced](../../runs/psg-nav/m5-acceptance-20261128/final/verify.json)

Trong lượt paced B2, cycle 85 đọc revision 22, source frame 21 có tuổi 601 ms. Hai receipt exact cũng khớp các detection từ frame 15 và 21 của CID 2, cùng owner O(7) và `p(television)=1`. Planner xác nhận đường. MotionGuard cấp 0,15 m/s và Habitat xác nhận `move_forward` 0,04485 m trong cycle đó. B2 vào VERIFY ở cycle 157, có RGB-D frame 48 được chụp và release sau khi vào VERIFY, rồi STOP `confirmed_target` ở cycle 166. Có 154/154 lần thực thi với proof được sensor client xác thực và 12 chu kỳ guard giữ zero motion có pose không đổi. [Causal trace B2](../../runs/psg-nav/m5-acceptance-20261128/paced/b2-only.json)

CID xác suất trùng CID deterministic trong ca live này. Unit hai CID xác nhận selector đổi lựa chọn sang ứng viên có receipt và có đường, giữ deterministic khi stale, chưa release, thiếu confirmation hoặc mất đường. Code review độc lập phát hiện trường hợp second owner nằm ngoài ngưỡng rank, khóa store trên control thread và thiếu pin trong evidence archive. Hồi quy đã bao phủ nhánh conflict. Snapshot và trace pin được bổ sung trước chạy nghiệm thu. Suite CPU exit 0 với 519 đạt và 1 skip. [Log](../../runs/psg-nav/m5-acceptance-20261128/full-regression.log)

**Nghiệm thu M5** trong phạm vi live Habitat lockstep phát triển. Guard và executor audit đạt 166 chu kỳ cộng một STOP row ở cả ba arm. OFF/shadow, shadow/B2 khớp từng action, pose, planner, guard reason và executor. Offline render xác nhận hai receipt cùng TV `hm3d:349`, mask IoU 0,975 và 0,960. Scorer xác nhận success và khoảng cách cuối 0,043 m. [Biên bản](../../runs/psg-nav/m5-acceptance-20261128/m5-signoff.json) · [Parity và applied rank](../../runs/psg-nav/m5-acceptance-20261128/paced/verify.json) · [Semantic audit](../../runs/psg-nav/m5-acceptance-20261128/paced/semantic-audit.json) · [STOP score](../../runs/psg-nav/m5-acceptance-20261128/paced/score-outcomes.jsonl)

Các arm chạy tuần tự bằng `bash runs/psg-nav/m5-acceptance-20261128/run.sh <mode> runs/psg-nav/m5-acceptance-20261128/final/manifest.json runs/psg-nav/m5-acceptance-20261128/paced/lockstep.json paced/<mode>`, với `<mode>` lần lượt là `probabilistic`, `shadow` và `off`. Ba arm, chuẩn bị audit, render, scorer, verifier và suite hồi quy đều exit 0. Chi tiết lệnh đối chứng và artifact kiểm SHA nằm ở [close-gate.sh](../../runs/psg-nav/m5-acceptance-20261128/paced/close-gate.sh) và [pin-check.log](../../runs/psg-nav/m5-acceptance-20261128/pin-check.log). M6 đánh giá độ phủ unpaced, ablation và ảnh hưởng trên held-out.

## M6 — Pilot held-out, scorer và TEST180

Pilot 125 chu kỳ được khóa trước theo metadata của TEST180. B0/B1/B2 chạy tuần tự unpaced. Mỗi arm có 375 chu kỳ, 331 lần executor thực thi với proof, 32 lệnh yêu cầu chuyển động bị guard đưa về zero. Cả ba episode đều hết budget. SR/SPL bằng 0, SoftSPL 0,040 và DTG 5,61 m cho từng arm. Verifier exit 0 trong manifest pilot. B2 có zero quyết định rank và zero STOP. [Ablation](../../runs/psg-nav/m6-20261128/pilot-live.json) · [Resources](../../runs/psg-nav/m6-20261128/pilot-resources.json)

Render GT từ exact accepted Hydra source chấm được 4/13 visible instances thuộc taxonomy ở từng arm semantic. Top-1 deterministic và hard-vote cùng đúng 2/4, 9 unmatched, 55 out of domain mỗi arm. Hai instance có p(gt)=0 nên NLL thô vô hạn, NLL clip 13,816 và Brier 0,889. Không có target-category visible ở cutoff nên retrieval recall unavailable. Confidence interval theo scene và STOP attribution chưa có mẫu. Replay fold từ native journal và scoring cùng source cho byte-identical JSON. Các lệnh chạy, exit code và rollback nằm ở [bàn giao M6](m6-handoff.md).

TEST180 chính thức đã khóa 180 UID trong 30 scene. Preflight có đủ scene, navmesh và semantic assets. B0 chuẩn đang chạy; B1/B2 và score dài hạn còn lại. Giữ nguyên threshold đã khóa. Full gate và hiệu quả điều hướng chưa được chứng minh.
