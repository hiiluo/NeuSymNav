# Ordered runtime, evaluation, navigation and robot campaign

User explicitly authorizes executing priorities1–5 in order. Retain CG+Visual.
User confirms body radius0.125m/height1m. Siblings read-only, one writer/file,
one GPU workload at a time. No TTL/gate/cap relaxation or failed-run exclusion.
No commit/push. Training is conditional on valid independent data and evidence.

- [ ] P1: reproduce RSS/process lifecycle and GPU-raycast deadline failures;
  add precise evidence, fix proven causes, bounded real long run and shutdown.
- [x] P2: freeze current 1m baseline and evaluate same-duration/seed profiles on
  00770/00802/00861. Preserve failed attempts. Report detection/association only
  where independent semantic GT exists; distance, explored measured area,
  control blocked reasons and revisit support with explicit denominators.
- [ ] P3: diagnose moving goals and stopped robot from current map/source
  bindings, fix demonstrated faults; test known-width corridors using measured
  geometry and unchanged robot/safety contract. Revalidate affected maps.
- [x] P4: retain user-confirmed1m body, audit sensor positions/FOV/floor coverage
  and native collision/body consistency. Explicit versioned camera experiment;
  avoid silently replacing baseline quality with new-camera measurements.
- [ ] P5: group errors across scenes; validate available training data/splits and
  carry out justified detector adaptation/association changes with fixed-input
  comparison. If no valid data/support, record exact missing prerequisite and
  complete actionable dataset/config/eval preparation, never claim trained gain.
- [ ] Final independent review, frozen checks, report scope/artifacts/exits,
  implemented vs correctness-verified vs runtime-validated and remaining limits.

Checkpoint kết thúc lượt triển khai: P1 và P3 chưa đóng gate. Đã sửa các lỗi có
bằng chứng và review; native RSS vẫn thiếu1mẫu ở00770/90s00802,00802 chưa có
explorationgain dù nhánh recovery mới đã chạy thật2lần. P2 đánh giá3map x300s
hoàn tất trong phạm vi đo, accuracy chỉcó00861. P4 giữ camera theo user, đãaudit.
P5 đãkiểm nội dung1400triplets và lậpblocker/reviewqueue; chưatraining vì mapping,
nhãn/split chưahợp lệ. Independentreview scopedACCEPT; finalCPUfull+delta và
artifacts ở docs/results/reliability-campaign-2026-10-31.md. Không đánh dấu toàn
bộcomplete hoặc runtimeaccepted; không rerunloạifail, khôngcommit/push.
