# Object graph admission — 2026-11-01

## Quyết định hiện tại

Đã triển khai contract, committed evidence, admission engine/journal, publication,
export, bảng chẩn đoán Qt và evaluator. Default vẫn `off`; shadow/enforce là thử
nghiệm. Chưa đủ bằng chứng để promote: pilot recall giảm và GT không đủ đo
precision. Không đổi detector/CG+Visual/body/camera hay safety navigation.

## Cách hoạt động

Object được owner cấp canonical ID ngay khi thành ứng viên và tiếp tục được
association. Admission riêng với lifecycle và verification: candidate, admitted,
review_required. Chỉ enforce mới lọc public object graph. Point cloud và đầy đủ
memory giữ trong owner; occupancy và safety map hoạt động độc lập.

Bằng chứng depth/mask được ghi cùng owner transaction, không suy từ cloud gộp.
Bộ lọc v1 dùng 3 detector observations, 2 independent views, depth fraction .50,
ít nhất20voxel và geometry consistency. Label uncertainty tách khỏi presence.
Negative transition cần visibility proof; live-expired rejection không là recovery
gap. Journal lưu decision và watermark; crash gap không chứng minh được, legacy
thiếu provenance hoặc overflow vẫn unavailable. Merge canonicalize/dedup evidence
và giữ review state bảo thủ. Không chứng minh mọi crash interleaving.

Off/shadow giữ graph baseline; enforce dùng chung subset cho UI/export. Khi
không có snapshot đủ coherent, giữ graph cũ và báo stale/unavailable. UI có bảng
ứng viên/lý do/số view/depth. Public hierarchy export chỉ floor/room/object;
internal composer vẫn giữ structures nội bộ để runtime sử dụng.

## Pilot offline trên dữ liệu thật

Cùng57sourceframes,230GTobservations,25GTidentities một scene development.
Replay chạy qua owner thật với simulated capture clock,143embedded appearance
features; chưa tái dựng async appearance attachments, không claim nativeequivalence.
Graph cloud được chiếu vào ảnh, depth-support và boxIoU>=.5; đây là proxy sample,
không phải continuous fullgraph3D groundtruth.

| Nhánh | Matched GT observations | Recall quan sát | Matched GT identities |
|---|---:|---:|---:|
| Baseline |90/230|39,13%|8/25|
| Confidence >=.50 |59/230|25,65%|6/25|
| Multiview + geometry |55/230|23,91%|5/25|

GT không exhaustive nên unmatched nodes là unknown; không suy precision/FP.
Recall giảm16,2điểm phần trăm trong pilot, không đáp ứng đề xuất loss<=5điểm.
Không điều chỉnh threshold theo kết quả này. Cần annotation negative/exhaustive và
nhiều scene độc lập trước tuning/promotion. Confirmation latency chỉ theo sampled
frames; không dùng nó chứng nhận gate5giây. Falsemerge/roomaccuracy/IDF1/AssA/flicker
chưa được chứng minh qua pilot này.

## Evidence và kiểm chứng

Artifacts: `.runtime/object-admission/` gồm core-report.md, publication-report.md,
evaluation-report.md, review.md, source pins/probes, preflight-final.json,
evaluation/replay-final/replay.json, evaluation/pilot-recall-final.json.
Preflight00861 ready=true exit0. Core78, publication108, evaluator14focused tests
exit0 (không cộng thành fullsuite). Full CPU và native campaign được ghi tiếp sau
khi hoàn tất; trạng thái hiện tại xem implementation-status.

No training/download/commit/push/source-sibling writes trong task admission.

## Kết quả kiểm chứng cuối

Full CPU cuối: `PYTHONPATH=src QT_QPA_PLATFORM=offscreen OPENBLAS_NUM_THREADS=1
OMP_NUM_THREADS=1 .venv/bin/python -m pytest tests -q -rs -m 'not native'`:
**2331 passed,3skipped,9deselected,exit0,143.30s**; log full-cpu-final.log.
Skipped: host thiếu torch cho training-loss, optionalNumba, GPUunit yêu cầu slot
riêng. Không coi skip là pass. Lượt CPU trước bị main ngắt exit130 để sửa finding,
lượt evaluator trước gặp collectionerror khi module đang thay đổi; logs giữ nguyên.

Review độc lập Sol high ACCEPT scoped snapshot cuối; đã sửa expiry-gap poisoning,
startupjournal, merge union, recovery independence, finitequality, confirmation
identity và public export. Probes/pins trong review.md/review-final-pins.json.
UIworker pins cập nhật16JSON+5YAML (hash only), defaults admission vẫn off.

Campaign6lượt, mỗi lượt120s, mộtGPU workload; tất cả sourcepins giữ nguyên:

| Map | Mode | Exit | Admitted / candidate | RSS support / samples |
|---|---|---:|---:|---:|
|00861|shadow|0|7 /13|926/926|
|00861|enforce|0|5 /14|953/953|
|00802|shadow|0|0 /41|813/813|
|00802|enforce|1|0 /53|927/928|
|00770|shadow|0|5 /11|958/958|
|00770|enforce|1|6 /12|942/943|

Cả6shutdown sạch, nofailedworkers, noexportissue. Hai exit1 do mỗi lượt1RSS
readerror; không retry/nới gate. Admission snapshot cuối available trong cả6;
review_required chưa xuất hiện trong nativecampaign, chỉ được kiểm thử fixture.
Không suy accuracy từ nodecounts hay so trực tiếp trajectoriesonline khác nhau.
4/6lượt scoped runtimepass; whole-runtime/P10 acceptance vẫn chưa đạt.

Kiểm chứng export6lượt exit0: chỉfloor/room/object, mọi endpoint tồn tại,
objectIDs đúng bằng objects.json; artifact export-parity.json. Sourcepin final
recheck unchanged, gitdiffcheck0. Campaign results/summary/protocol và stdout/
stderr trong .runtime/object-admission/campaign/. Wrapper exit0 chỉ nghĩa đã chạy
hết6attempts, không ghi đè hai childexit1.

## Gate và bước tiếp theo

Implemented: A1–A4 functional paths, A5review/campaign/report executed.
Correctness-verified: các invariants được tests/probes chứng minh trong phạm vi
fixtures; không chứng nhận mọi crashinterleaving. Runtime-validated: nativewiring
và publicsubset trên3map, 4/6pass; reliabilitygate không đạt trọnvẹn.
Qualitygate chưa đạt: precision/falsemerge/roomaccuracy/multisceneheldout thiếu
GT phù hợp; recallpilot giảm, p95confirmation và p95controllatency-overhead chưa
được chứng minh theo protocol đủ support. Không promote default.

Đề xuất lượt sau: bổ sung exhaustiveannotation/negative scope trên nhiều scene;
phân nhóm lý do candidate theo depth/sparsity/viewbaseline/lifecycle trước khi
hiệu chuẩn ngưỡng trên development. Cần quan sát đủ near-consecutiveframes và
camera baselines để đo confirmation latency thật. RSSmissing vẫn là hạn chế
runtime cũ, không sửa bằng cách gánzero hoặc bỏ mẫu.
