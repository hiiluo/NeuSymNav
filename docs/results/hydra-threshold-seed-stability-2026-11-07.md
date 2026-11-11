# Hydra threshold/seed stability — 2026-11-07

Đã triển khai và chạy replay native trong worktree `Kiet_branch2`. Chính sách mới
loại bỏ ba lần gộp nhầm bathroom/hallway do spike threshold trên recording long300.
Chưa đổi cấu hình mặc định; chưa chạy live simulator trong task này.

## Cơ chế đã triển khai

Hydra PLATEAU vẫn tính ngưỡng đề xuất từ graph hiện tại. Thay đổi vượt sai số số học
0,0001 m phải lặp lại qua **ba timestamp cập nhật places mới**, với đề xuất nhất quán
trong 0,02 m, mới được nhận. Timestamp lấy từ maximum `last_update_time_ns` của
places: đây là proxy cập nhật graph, không chứng minh các góc nhìn độc lập.

Trong khi chờ, components/seed được **tính lại trên geometry hiện tại** ở ngưỡng
đã nhận, không phát lại membership cũ. Bootstrap nhận đề xuất hợp lệ đầu tiên;
held seed mất toàn bộ support thì fallback sang raw hợp lệ. Thiếu candidate/support
xóa pending và báo unavailable. Timestamp trùng không tăng đếm; destructor xóa state.
Thay đổi kéo dài vẫn có thể split/merge. Đây là ổn định chọn threshold/seed, chưa phải
chính sách xác nhận vòng đời từng phòng hoặc đảm bảo ranh giới vật lý đúng.

Private `libhydra.so` thay đúng RoomFinder translation unit, không thay header/layout,
installed library hay source Hydra gốc. Bridge kiểm SHA/version và duy nhất một DSO
được map trước khi chạy pipeline. Effective build hash bao gồm binding, private DSO,
policy, Python bridge và worker source. Snapshot/projection mang provenance và decision;
journal ghi decision gắn với revision/source prefix được nhận. Control không chờ worker.

## Replay có kiểm soát và vùng do người dùng đánh dấu

Giữ nguyên compression 0,5 m, component min 3, room min 10, merge 0,25 m của đối chứng;
chỉ bật policy. Hai worker mới replay đúng 58/58 và 10/10 accepted inputs của recording
300 s và 60 s. Cả hai đóng/export sạch; đây **không phải** hai demo live mới.
Tất cả 58 revision long300 khớp chính xác đối chứng về places XYZ/clearance, cạnh/weight
và source prefix. Human annotation chỉ được đọc trong evaluator offline.

| Tiêu chí trên hai vùng lõi được đánh dấu | Đối chứng | Policy bật |
| --- | ---: | ---: |
| Revision đủ điều kiện đánh giá | 53/58 | 53/58 |
| Revision gộp chéo bathroom–hallway | 3 (36, 49, 57) | **0** |
| Revision hành lang bị phân mảnh | 13 (6–18) | 13 (6–18) |
| Tách trọn các điểm lõi, không điểm lõi unassigned | 37/53 | **40/53** |
| Final confident bathroom/hallway support | 8 / 62 | 8 / 62 |

Revision 36 và 49: raw ~0,632 m, effective ~0,566 m. Revision 57: raw ~1,000 m,
effective ~0,566 m. Cả ba đều `hold`; bathroom/hallway ở hai membership khác nhau.
Revision 27 `adopt` ngưỡng mới sau đủ evidence: policy không đóng băng threshold.
Hành lang phân mảnh giai đoạn đầu chưa được sửa. Annotation là hai vùng lõi dương tính;
ngoài polygon/biên/ô cửa không có GT. Không suy ra accuracy toàn phòng/toàn scene từ kết quả này.

![So sánh membership tại ba spike](../../runs/hydra-objectnav/B1-stability-20261107/target-spikes-comparison.png)

## Chi phí và kiểm chứng

Thời gian native process (gồm graph summary, chưa gồm diagnostic export), long300:
median 3.002 → 3.869 ms; p95 3.990 → 5.830 ms; max 5.343 → 6.581 ms. Đây là **hai lần
replay khác thời điểm**, chưa phải benchmark lặp kiểm soát tải máy, nên chưa quy phần
chênh lệch cho policy. RSS quan sát tối đa 316.076.032 → 314.937.344 bytes; đây không
phải peak sampler liên tục. Cần A/B enabled/disabled lặp cùng điều kiện trước khi promote.
Không dùng kết quả này để tuyên bố freshness hay tốc độ điều khiển được cải thiện.

Native synthetic driver đã kiểm spike, duplicate timestamp, sustained transition,
current-geometry merge/split, held-support fallback, destructor reset, pending bị ngắt
bởi unavailable và empty filtration. C API checks và seed parity stock/private-disabled
trên ba fixture đều exit 0; không tuyên bố parity trên mọi graph.

Python/UI/GT-isolation suite tập trung: **206 passed, 10,87 s, exit 0**, không skip;
xem `final-tests.log`, `final-tests.exit` và `commands.json`.
Một test UI cũ giả định mặc định hiện cả bốn layer và room được pick như object;
đã sửa fixture để yêu cầu all layers rõ ràng và kiểm object picking đúng contract A1/A2.
Không thay hành vi UI trong task này. Không chạy toàn bộ repository suite.

Profile thử nghiệm qua preflight. Default Hydra YAML, installed DSO, GraphExtractor,
coordinator và MotionGuard giữ nguyên SHA. Guard depth 300 ms / command 100 ms không đổi.

## Chạy thử profile mới

Từ worktree `Kiet_branch2`:

```bash
NEUSYMNAV_HYDRA_DEMO_CONFIG=configs/demo-00805.hydra-room-stability.experimental.local.json \
  bash tools/run_hydra_map_demo.sh 00805 300 runs/hydra-room-stability-live-300s
```

Dùng output directory mới. Profile này kế thừa navigation/movement của
`demo-00805.hydra-long-demo.local.json`; room backend vẫn là Hydra. Không thay profile
mặc định. Build private DSO và yêu cầu cấu hình được mô tả trong
`tools/native/hydra_room_stability/README.md`; cấu hình thử nghiệm và SHA nằm dưới
`runs/hydra-objectnav/B1-stability-20261107/config-root/stable/`.

## Evidence và bước tiếp theo

Artifact root: `runs/hydra-objectnav/B1-stability-20261107/`.
`design.md`, `native/{build-commands.json,build.exit,test.log}`, `python-bridge/`,
`{long300,short60}-command.json`, `clean/{long300,short60}/stable/`,
`evaluation/`, `comparison.json`, `final-tests.log`, `preflight.log`, `verification.json`.
Private library SHA: `9364ca487e8826112705d942ff01734cdbe3372fbdcc91c21c42a14a42fb7e4b`.

Bước còn lại trước khi đổi mặc định: benchmark lặp enabled/disabled, live kiểm tra
revision/decision và UI, thêm recording/scene cùng annotation độc lập, xử lý phân mảnh
hành lang giai đoạn đầu. Phân loại SLM và object evidence tiếp tục độc lập; chưa dùng
nhãn phòng để chứng minh geometry đúng.
