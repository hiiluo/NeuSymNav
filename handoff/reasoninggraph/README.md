# Bàn giao Hydra–ReasoningGraph ở chế độ chỉ đọc

Bản bàn giao gồm demo Habitat với Hydra lineage và evidence cùng phiên, bộ lệnh replay cho object, room và quan hệ trái–phải trong ảnh, cùng các kiểm tra an toàn khi đổi revision. Kết quả dưới đây áp dụng cho profile local đã ghim trên máy hiện tại.

## Chạy replay

Chạy từ root của NeuSymNav với mã nguồn của bản bàn giao hiện tại. Giải nén gói replay vào checkout nhận bàn giao. Gói chứa dữ liệu replay và giữ nguyên đường dẫn tương đối. Python `.runtime/detector26/bin/python` cần OpenAI CLIP, PyTorch, NumPy và Pillow. Python `.venv/bin/python` cần dependencies NeuSymNav. Đặt `REASONINGGRAPH_CLIP_CHECKPOINT` nếu checkpoint CLIP ViT-B/32 nằm ngoài vị trí trong profile. Công cụ xác minh SHA-256 checkpoint trước khi nạp. [Gói dữ liệu](../../runs/reasoninggraph/handoff-20261127/reasoninggraph-replay-20261127.tar.gz) · [SHA-256](../../runs/reasoninggraph/handoff-20261127/reasoninggraph-replay-20261127.tar.gz.sha256) · [Profile CLIP](../../configs/p10/demo-yoloe11s-conceptgraphs-visual-gpu-00861.json)

```bash
bundle=/path/to/reasoninggraph-replay-20261127.tar.gz
(cd "$(dirname "$bundle")" && sha256sum -c reasoninggraph-replay-20261127.tar.gz.sha256)
tar --keep-old-files -xzf "$bundle"
export REASONINGGRAPH_CLIP_CHECKPOINT=/path/to/ViT-B-32.pt
bash handoff/reasoninggraph/replay.sh /tmp/rg-handoff-replay-new
```

| Truy vấn | Kết quả đã chạy | Phạm vi |
| --- | --- | --- |
| Object | Query `kitchen island` ở revision 9 của replay 00770 trả ứng viên duy nhất `O(2)`, cosine 0,2686. Query ở revision 26 trả `no_evidence`. | CLIP trên crop đã che nền, endpoint Hydra theo revision và đã được rà soát. Mẫu này kiểm tra đường chạy và trạng thái thiếu evidence. |
| Room | ID `5908722711110090752` trả topology và nhãn native thô. ID `1` trả `no_evidence`. | Bản export 00806 có room bbox `INVALID`. Semantic room retrieval cần hình học membership đã được chứng nhận. |
| Quan hệ | Replay 00806 kiểm bốn chiều của hai cặp đối tượng. Ở frame 25, `O(2)` ở bên trái `O(3)`. Đảo chiều trả `no`. Ở frame 27, `O(5)` ở bên trái `O(7)`. Đảo chiều trả `no`. | Phép đo trên bbox tách biệt trong ảnh RGB đã lưu, có source frame, graph revision, prefix, mã băm ảnh và cặp ID. Qwen riêng đạt 2/4 và trả `no` cả bốn lần. Quan hệ 3D và suy luận quan hệ live vẫn mở. |

[Kết quả replay](../../runs/reasoninggraph/handoff-20261127/replay-smoke) · [Kết quả Qwen](../../runs/reasoninggraph/handoff-20261127/relation/summary.json)

## Chạy Habitat live

Profile hiện tại được sinh từ bản local HM3D 00806 có journal build. Trên máy teammate cần Habitat EGL, HM3D 00806, YOLOE, MobileCLIP, môi trường Python Hydra/Spark-DSG kèm binding journal và thư viện room-stability tương ứng, Qt, cùng các asset được pin trong profile. Các path và SHA trong config, setup script và YAML native phải trỏ về cùng bộ build trên máy đích. [Patch và probe native](../../tools/native/hydra_object_journal) · [Profile đã chạy](../../runs/reasoninggraph/handoff-20261127/live.json)

```bash
export QT_QPA_PLATFORM=offscreen EGL_PLATFORM=surfaceless
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=2 PYTHONPATH=src:.
config=runs/reasoninggraph/handoff-20261127/live.json
.venv/bin/python -m neusymnav.cli preflight --config "$config"
.venv/bin/python tools/reasoninggraph/handoff_live.py \
    --config "$config" --duration-s 48 --out /tmp/rg-handoff-live-new
```

- Probe đã qua tám kiểm tra. Quan sát được 21 revision có native lineage, năm revision phục vụ crop evidence qua API và 20 lần query cũ trả `stale`. Native export ghi 22 revision, recording 469 frame. Probe đối chiếu source và prefix với native export. Kiểm tra asset riêng đối chiếu RGB, mask và depth với digest, và mask với batch detector trong ledger. [Probe live](../../runs/reasoninggraph/handoff-20261127/combined/verification.json) · [Kiểm tra asset](../../runs/reasoninggraph/handoff-20261127/combined/live-verification.json)
- Probe có exit code 0 theo phạm vi đọc đã định. Launcher báo `incomplete` vì thiếu phép đo cho P10. UI dùng Hydra viewer hiện có. Truy vấn CLIP và quan hệ ảnh ở phần replay chạy bằng CLI.
- Tắt sidecar bằng `scene_graph.hydra.reasoninggraph_evidence=false` trong config và khởi động phiên mới. Để quay về build Hydra thông thường, dùng lại đồng thời setup script và native config root của profile trước journal. Chạy preflight để xác nhận bộ pin trước khi mở phiên. Khi query trả `stale`, lấy query mới từ phiên hiện tại. Khi thiếu dữ liệu, xử lý `no_evidence`, `unavailable` hoặc `not_recorded` theo API.

## Phạm vi nghiệm thu

| Mục | Kết luận |
| --- | --- |
| Native live và provenance | Đạt cho profile 00806 ở trên. Recording, native export, topology, lineage, crop evidence và từ chối revision cũ được quan sát cùng phiên. |
| Lifecycle có kiểm soát | Fixture C++ chạy chín ca, gồm backend chain merge. Fixture host đi qua durable journal, fold, truy vấn theo revision và thu hồi truy vấn sau lỗi continuity. Native replay dài quan sát bốn lần delete và probe native riêng kiểm tra reset. Cổng native merge → serialization → canonical query trên cùng một ca vẫn mở. |
| Ổn định | Replay bật/tắt sidecar tái dựng 18/18 accepted prefix và graph hash giống nhau, tối thiểu 0,5 giây giữa các frame. Native service p95 từ 113,1 lên 137,4 ms, trong ngưỡng tham chiếu của phép thử. Sidecar xuất 18/18, 3,6 MB, không lỗi. Fault probe HNA quan sát timeout và frame/control tiếp tục. Kiểm thử sidecar xác nhận staging tiếp tục khi worker bị giữ và báo trạng thái khi hết thời hạn dừng. Đo tải live ghép cặp và GPU dài hạn còn mở. |
| Chất lượng và phạm vi nghiên cứu | Phép thử CLIP/Qwen cục bộ là smoke. Room membership được chứng nhận, quan hệ 3D, ứng dụng Paper `advise`, DEV60/TEST180, P10 đầy đủ và parity DeepSeek-VL2 nằm ngoài phạm vi bản bàn giao này. |

```bash
.venv/bin/python tools/reasoninggraph/handoff_compare.py \
    --source /tmp/rg-handoff-live-new/live --config "$config" --out /tmp/rg-handoff-matched-new
OPENBLAS_NUM_THREADS=1 PYTHONPATH=src:.:tests .venv/bin/python -m pytest -q \
    -p no:cacheprovider -m 'not native' tests/test_rg*.py tests/test_hydra*.py tests/test_objectnav_paper*.py
```

[Replay cùng đầu vào](../../runs/reasoninggraph/handoff-20261127/matched-pinned/report.json) · [Lifecycle fixtures](../../runs/reasoninggraph/handoff-lifecycle-20261127/report.md) · [Native delete](../../runs/reasoninggraph/m1-native-lineage-20261127/replay-00806-long/journal-probe.json) · [Native reset](../../runs/reasoninggraph/m1-native-lineage-20261127/reset-probe.json) · [HNA fault probe](../../runs/hydra-attribute-query/hna-live-00806-8yoan0t4/acceptance.json) · [Hồi quy](../../runs/reasoninggraph/handoff-20261127/regression.log)
