# Bàn giao PSG-Nav M6

Ngày 2026-11-28. Baseline Git `117df522cd3c206bccc3311ea85c46807f6e46c0`. M5 đã nghiệm thu trên development lockstep có MotionGuard. M6 đã qua kiểm chứng evaluator và pilot held-out. Gate đầy đủ dùng 180 UID thuộc 30 scene, đã khóa manifest. [Trạng thái](../implementation-status.md) · [Protocol](evaluation-plan.md) · [Biên bản M5](../../runs/psg-nav/m5-acceptance-20261128/m5-signoff.json)

## Kết quả đã đo

Pilot dùng ba UID từ scene đầu tiên của TEST180, chọn theo metadata và khóa trước khi xem kết quả. Cả ba arm chạy không điều tiết host, giới hạn 125 chu kỳ. MotionGuard và executor khớp 375/375 chu kỳ ở mỗi arm. Mỗi arm có 331 lệnh thực thi với proof và 32 yêu cầu chuyển động bị guard đưa về zero. Cả ba episode ở mỗi arm hết budget, không có STOP, cũng không có lần B2 đi vào bước chọn ứng viên. SR và SPL bằng 0 với mẫu này. SoftSPL trung bình 0,040 và khoảng cách cuối đến đích 5,61 m ở cả ba arm. Mẫu một scene chưa đủ để tính CI theo scene. [Live audit](../../runs/psg-nav/m6-20261128/pilot-live.json) · [Resources](../../runs/psg-nav/m6-20261128/pilot-resources.json)

Mỗi arm semantic có 13 GT vật thể nhìn thấy thuộc taxonomy tại snapshot cuối, 4 matched và 9 unmatched. Top-1 đạt 2/4 trên tập có belief và 2/13 trên toàn tập nhìn thấy. Deterministic label có cùng số đúng. NLL thô là vô hạn do 2 case có `p(gt)=0`. Brier 0,889. Hai lượt score cùng annotations cho output byte-identical. Snapshot cuối của hai arm là cutoff riêng theo exact native revision, có một episode lệch một revision. So sánh deterministic label và hard vote dùng cùng snapshot bên trong từng arm. Không có target đúng loại trong ảnh cutoff đã chấm nên retrieval recall chưa có mẫu. [Belief B1](../../runs/psg-nav/m6-20261128/belief-b1/metrics.json) · [Belief B2](../../runs/psg-nav/m6-20261128/belief-b2/metrics.json) · [Mask audit](../../runs/psg-nav/m6-20261128/belief-b2/mask-audit.json)

RSS process-tree lấy mẫu khoảng mỗi 2 s là 1,81 GiB OFF, 2,16 GiB shadow và 2,13 GiB B2. Số liệu có thể đếm trùng shared pages. VRAM đồ họa không có mẫu theo process từ compute query. Native journals shadow và B2 chiếm tổng cộng khoảng 0,88 GB cho ba UID ở budget pilot. Từ wall time pilot, ngoại suy cùng budget 125 chu kỳ cho ba arm của TEST180 khoảng 4,43 giờ trước scorer. Budget chuẩn dài hơn và chưa có số đo hoàn tất. [Lấy mẫu](../../tools/psg_nav/sample_ablation_resources.py) · [Preflight đủ tài sản](../../runs/psg-nav/m6-20261128/test180-preflight.json)

## Tiếp tục TEST180

B0 dùng profile chuẩn `configs/objectnav/lockstep-b0-v3h.json` và manifest `configs/objectnav/splits/hm3d_v2-val-test.json`. Thư mục chạy hiện tại là `runs/psg-nav/m6-20261128/test180`. Chỉ một workload GPU. Theo dõi `off.log`, `off.resources.jsonl`, `off.exit` và `off/trajectories.jsonl`. Hai UID đầu tiên có start snap ngoài giới hạn đã được lưu là failure trong mẫu số, kèm lý do.

Chạy từ repo root. Dùng đúng interpreter, dữ liệu HM3D, detector profile và cấu hình native đã pin. Script chấp nhận biến `M6_HABITAT_DATA`, `M6_HABITAT_PYTHON`, `M6_HYDRA_ENV`, `M6_HYDRA_CONFIG` khi teammate có đường dẫn khác. Trên workspace hiện tại, defaults trỏ vào môi trường đã kiểm. Các binary và weights cục bộ không nằm trong patch bàn giao. Khi dùng thư mục đã chạy dở, giữ nguyên source/config và theo dõi báo cáo mismatch ở provenance, do số thứ tự episode có thể thay đổi khi resume.

```bash
out=runs/psg-nav/m6-20261128/test180
bash tools/psg_nav/run_m6_arm.sh off "$out"
bash tools/psg_nav/run_m6_arm.sh shadow "$out"
bash tools/psg_nav/run_m6_arm.sh probabilistic "$out"
```

Để giới hạn dung lượng làm việc, có thể chạy từng manifest scene trong `runs/psg-nav/m6-20261128/test180-manifests`. Mỗi scene có 6 UID. Cần ghép và kiểm đúng 180 UID từ manifest gốc khi tổng hợp; workload sharded và unsharded dùng thư mục kết quả riêng. Bảo tồn native journal, accepted prefix, mask asset và output scorer trước khi nén hoặc di chuyển dữ liệu. Trên arm semantic, giới hạn artifact session hiện tại vẫn áp dụng và mọi quota/drop phải vào báo cáo.

```bash
export EGL_PLATFORM=surfaceless OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=2 PYTHONPATH="$PWD/src:$PWD"
out=runs/psg-nav/m6-20261128/test180
for arm in off shadow probabilistic; do
  .runtime/sensor/bin/python tools/objectnav/score_trajectories.py "$out/$arm/trajectories.jsonl" \
    --set hm3d_v2 --split val --habitat-data local-assets/datasets/hm3d-val --out-prefix "$out/$arm/score"
done
.venv/bin/python tools/psg_nav/compare_live_ablation.py \
  --manifest configs/objectnav/splits/hm3d_v2-val-test.json --root "$out" --out "$out/ablation.json"
```

Sau mỗi arm semantic, dùng `prepare_belief_annotations.py` trong môi trường Hydra để kiểm graph/journal SHA và trích nguồn accepted. Dùng `render_belief_annotations.py` trong interpreter Habitat và `score_beliefs.py` trong interpreter project. Đây là đường evaluator offline. Lệnh thực chạy trong [score-pilot.sh](../../runs/psg-nav/m6-20261128/score-pilot.sh). Báo cáo `compare_live_ablation.py` chỉ chấm các kiểm tra chính nó quan sát được. Với B2 có applied rank hoặc STOP, thực hiện kiểm receipt-to-instance và STOP attribution trước khi ký gate, theo mẫu [M5 verifier](../../runs/psg-nav/m5-acceptance-20261128/verify.py). Cặp scene đủ số lượng cho CI chỉ có ở lượt đầy đủ. B3 và B4 chờ consumer phòng và backend soft-evidence đã xác minh.

Rollback bằng cách đặt `--semantic-candidate-mode off` hoặc bỏ hai option semantic. OFF là mặc định.
