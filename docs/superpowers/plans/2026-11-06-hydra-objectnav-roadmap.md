# Hydra / ObjectNav song song control — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development hoặc superpowers:executing-plans theo phương thức đã được người dùng chọn. Các task có checkbox; lượt này chỉ viết tài liệu.

**Goal:** Làm graph dễ debug, object có evidence truy nguồn, đo room geometry/SLM labels và tiến tới ObjectNav; control cải thiện song song.
**Architecture:** Hydra giữ owner IDs/room geometry; thêm read-only UI/evidence/room semantics và pure ObjectNav modules. Control có gate riêng, không đợi mọi run dưới5% để làm graph.
**Tech Stack:** Python, PyQt5, NumPy/SciPy, Hydra/Spark-DSG bindings hiện có; SLM adapter/model chưa chọn.
**Spec:** [Thiết kế](../specs/2026-11-06-hydra-objectnav-design.md).

## Global Constraints

- Chỉ Kiet_branch2; giữ nguyên Kiet_branch và source siblings. Không product code/model install/download/training/commit/push trong lượt lập plan.
- Một canonical owner IDs; native graph không bị UI/SLM/evidence service sửa.
- Guard300ms/horizon100ms/source gốc; unknown≠free; GT chỉ offline; room label≠room boundary.
- Main owns contracts/config/schema; mỗi file một writer;1GPU/native benchmark tại một thời điểm, không tranh với inference/build/tests nặng.
- Mọi task báo implemented/correctness/runtime riêng, command/exit/artifacts/unsupported cases. Không lấy2706tests cũ làm pass cho code tương lai.

## Review Focus

- Native node nhìn đúng nhưng không có per-object evidence: A2/A3 phải dùng linked observations, không latest camera.
- Same-class instances bị merge/split: A2/A3 test gallery nhiều source và ambiguity.
- Node/revision bị đổi trong lúc load ảnh/SLM: A1/A2/B2 reject stale response.
- SLM gắn đúng tên lên room bị merge sai: B1/B2 đánh giá geometry/semantics riêng.
- Freshness tốt vì robot không đi: C3 báo displacement/coverage/no-progress và tất cả STOP.

## Subplans và thứ tự ưu tiên

| Ưu tiên | Deliverable | Kế hoạch | Phụ thuộc | Gate |
|---|---|---|---|---|
|1|Ẩn/bật places thống nhất2D/3D, room/object rõ|[A1](2026-11-06-hydra-graph-evidence-objectnav.md)|Không cần control pass5%|UI fixtures, native smoke|
|2|Click object xem gallery đúng nguồn, debug association|[A2–A3](2026-11-06-hydra-graph-evidence-objectnav.md)|Geometry/evidence capability probe|Link correctness + manual pilot|
|3|Room segmentation audit|[B1](2026-11-06-hydra-rooms-slm.md)|Canonical room/place export; có thể song song A2|Observed-support metrics, không giả accuracy|
|4|Query/approach/verification ObjectNav offline|[A4](2026-11-06-hydra-graph-evidence-objectnav.md)|A2/A3, gate trước live|Replay/pure tests, không motor|
|5|SLM nhãn phòng dạng text|[B2–B3](2026-11-06-hydra-rooms-slm.md)|Room context/membership; model asset để chạy thật|Unknown/stale/quality report|
|Song song|Đo và cô lập critical control process|[C1–C3](2026-11-06-control-isolation.md)|Safety contract/review riêng|Safety hard;performance riêng|

- [ ] M0: Main freeze spec/interfaces/fixtures và ghi snapshot hashes trước dispatch.
- [ ] M1: Giao A1 UI trước; demo Rooms+Objects, places OFF, giữ floor cloud/orbit/zoom.
- [ ] M2: A2 capability/evidence; B1 audit có thể làm song song chỉ khi files/CPU không tranh nhau.
- [ ] M3: A3 gallery + reviewed association cases; A4 pure ObjectNav; B2 SLM stub/context.
- [ ] M4: Chọn/pin SLM sau inventory model sẵn có và ngân sách; B3 pilot không cản A/C nếu thiếu model.
- [ ] M5: C process prototype chỉ triển khai sau safety/owner design review; không thay default tự động.
- [ ] M6: Freeze một native profile, tối đa2scene sẵn có×2seed×300s cho đợt nghiệm thu; chỉ1workload. Không tự tải scene hay rerun để chọn run đẹp. Thiếu annotation/scene ghi pilot/unsupported.

## Điều phối

Main quản lý shared `contracts/`, `runtime/coordinator.py`, `launcher.py`, `configuration.py`, `visualization/publisher.py` và schema. Integration vào `desktop.py` tuần tự A1→A3→B3 bởi một writer; các widget/services riêng có thể làm độc lập. Native producer/query files `backends/hydra/{worker,graph_adapter,query,runtime,session}.py` chỉ một owner tích hợp A2/B1/A4; B1 chỉ chạy song song A2 trên evaluator/fixtures sau khi khóa export schema, không hai worker sửa producer. Tránh giao A và C cùng sửa coordinator; tách integration commits/diffs theo owner, không tự commit khi chưa được yêu cầu.
Luna xhigh cho UI/query/fixtures/evaluators có oracle rõ; Terra khi evidence native lineage hoặc process/IPC safety bất định; Sol khi race/bất đồng chưa giải được. Không Astra. Không worker con ngoài phân công main.

## Phần chưa xác nhận

SLM text đã được người dùng chọn; chưa chọn model/backend/license/runtime asset, chưa có room-GT coverage audit. UI defaults/budgets và lifecycle/evidence methods là đề xuất để review, không phải thông số đã benchmark. Chưa implement bất kỳ task nào của roadmap.
