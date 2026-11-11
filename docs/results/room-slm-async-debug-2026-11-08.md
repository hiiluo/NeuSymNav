# Room SLM: đường chạy bất đồng bộ và snapshot UI — 2026-11-08

Đã triển khai trong worktree `Kiet_branch2`, theo yêu cầu chuẩn bị **demo debug**, không nâng model. Đường chạy và xử lý lỗi đã có; **chưa có nhãn SLM live hoàn tất, chưa đạt chất lượng room labeling**.

## Phạm vi đã triển khai

- `RoomLabelDebugService` thuộc tiến trình UI riêng: Qt chỉ offer graph; manager dựng context, chạy inference và ghi artifact ở nền. Một inference tại một thời điểm; queue tối đa 32 room, giữ snapshot mới nhất, round-robin, debounce 3 giây tính từ lần dispatch. Lịch sử tối đa 128 record / 8 MiB, mỗi record 256 KiB. Không nối SLM vào coordinator, navigation hay actuator.
- `PersistentRoomLabelBackend` giữ một llama-server CPU/1 thread/1 slot, có KV-cache; timeout, crash, cancel, mutation asset và close có xử lý riêng. Deadline toàn job vẫn **60 giây**, gồm startup; hết hạn sẽ dừng/reap model, lần sau khởi động lại. Backend offline cũ và config SLM chung mặc định disabled vẫn được giữ.
- Hydra display projection mang semantic ID và digest của đúng source graph, không suy category từ tên node. Request kiểm tra run/revision/prefix, vocabulary/labelspace/calibration; snapshot lưu room, object và chuỗi ancestor thực, tách khỏi graph hiện hành. Digest display graph không được gọi là ground truth hình học.
- Tab **Room labels (debug)** có request/history, pending/running/result/error, source age/clock, revision/context/model/grammar hashes, categories/support IDs và cảnh báo evidence. Snapshot lịch sử không dùng cloud hiện hành; sidebar ảnh live được ẩn khi mở tab này. Zoom/Fit và Expand/Pop out dùng được; các nét đứt membership chỉ suy ra từ native parent chain, không phải cạnh native hay bằng chứng đi qua được.
- Kết quả cũ chỉ ở lịch sử; badge hiện hành cần khớp episode/run/revision/prefix/digest/world epoch và graph không stale/replay. Reset episode hủy việc cũ. Nhãn không thay geometry, membership hoặc điều khiển.
- Evidence policy `room-debug-evidence-v1` công bố link/association counts và cờ thiếu ảnh, chưa đo category/geometry accuracy. Context chỉ có các object chung như mirror/door/vase sẽ abstain ở host, không khởi động model. Human annotations không nhập vào prompt.

## Kiểm chứng code

**245 test khác nhau passed, exit 0**, trong `runs/room-slm-async-debug-20261108/final-tests.log` và `final-tests.xml`. Bộ tập trung gồm service/UI/config/transport/query/prompt/adapter/output grammar, backend HTTP fixtures, lifecycle và hồi quy launcher. Có native grammar validator sẵn có; không phải full repository suite.

Luna xhigh triển khai backend và widget; Terra high review các race về stale/epoch, queue, property UI và vòng đời. Các lỗi phát hiện đã được main sửa và có regression: stale/replay/epoch-only offer, bỏ pending snapshot đã supersede, phục hồi available→stale→available, UI timer, unavailable service, deep-freeze source metadata, zoom và sidebar ảnh live. Log RED/GREEN nằm cùng thư mục run. Kiểm thử fake HTTP không được coi là native model inference.

Profile mới chỉ thêm UI debug/assets và thay UI worker entry được pin. Legacy `ui_transport.py` giữ SHA `d095f3aa309ef4d87a4b7f5c5309ea3835ea62850a6d0027ff6c1c4f81a00781`, tránh phá worker pin của profile cũ. Preflight cuối exit 0. Hydra geometry config, movement, depth guard 300 ms và command horizon 100 ms không đổi.

Mốc lock cũ khớp **15/17** file: hai khác biệt là `room_semantics.py` và `rooms/context.py` đã phát triển trong các bước SLM trước; không diễn giải thành 17/17 unchanged. Chi tiết `baseline-verification.json`.

## Chạy thực tế và giới hạn

Hai smoke 00807, mỗi run cấu hình 60 giây, đã hoàn tất và shutdown sạch. Chúng diễn ra trước các bổ sung deep-freeze/recovery/zoom/sidebar cuối; các bổ sung này đã qua fixtures/offscreen nhưng chưa chạy lại simulator trên snapshot source cuối:


1. `live00807-60s`: sandbox chặn socket localhost của model; UI trả `unavailable/PermissionError`, giữ lịch sử và đóng sạch. Detector cũng fallback CPU trong môi trường này. Đây là kiểm tra error path.
2. `live00807-60s-localhost`: chạy với quyền localhost; server thực được khởi động, UI render graph cuối revision 2, inference đầu chưa xong khi hết demo nên bị hủy. Không có nhãn live hoàn tất. Worker/model reaped, không pending. Có 58 lệnh thực thi và 134 lượt `expired_or_zero`; không đổi số này thành tỷ lệ mất freshness. Observed translation lower bound 0 m, strict actuation.complete=false dù missing_command_proofs=0; không chứng nhận movement hay demo dài. RSS sampled peak ~3,84 GB, không phải absolute peak/boundedness proof. Hai môi trường detector khác nhau nên đây **không phải A/B hiệu năng SLM**.

Probe riêng trên đúng nội dung context đầu của run localhost: **5 object, 10 quan hệ, 661 prompt token**; hai lượt cold timeout lần lượt ~60,72 và ~60,37 giây, gồm cleanup sau deadline. Startup đầu ~2,85 giây. Prompt/hash và request ID được đối chiếu lại khi render; không bỏ object/quan hệ, không tăng deadline. Timeout dừng server nên cả hai lượt không reuse. Vì vậy chưa chứng minh native reuse bằng class mới trên context này; fixture đã chứng minh reuse, còn số đo KV ở task trước chỉ là benchmark khác.

`persistent-real.json`, `persistent-real-shutdown.json` giữ kết quả thật. Có một probe chuẩn bị bị dừng vì script bỏ thiếu relations; các file `aborted-missing-relations-*` bị loại khỏi kết luận. Request artifact của probe chính dựng lại từ plain history có list trong source manifest nên không round-trip wire trực tiếp; renderer đối chiếu request ID và **prompt SHA thực đã chạy**, không gọi đó là wire round-trip proof. Product DTO đã deep-freeze metadata và được test riêng.

Ảnh `snapshot-ui-frozen-timeout.png` là Qt offscreen render lại kết quả timeout thật: source revision 1, current revision 2, `is_current=false`. Không phải screenshot nhãn live thành công, không có inference mới trong render. Screenshot dashboard 800×600 của smoke sandbox bị chật; không dùng làm bằng chứng visual usability toàn màn hình hay thao tác desktop vật lý.

## Chất lượng evidence

`evidence-quality-audit.json` kiểm kê ba context đã có, đúng source: 00805 corrected 14 object, 00806 18 object, 00807 9 object — **41 object, 0 linked observation**. Human review giữ riêng: A1 bathroom/sink; C/D cùng primary bedroom, D thấy bathroom qua cửa; E living room/O(0) sofa trong khi input dự đoán bed. Không áp nhãn này sang run/native ID khác hoặc toàn room boundary.

Task này cải thiện phát hiện/hiển thị giới hạn evidence và abstention, **chưa sửa detector bed→sofa, chưa bổ sung object–image association hay gallery đã xác nhận**. Cross-run A/B00805 cũ tiếp tục bị quarantine. SLM output hợp lệ cú pháp vẫn không chứng minh nhãn đúng.

## Chạy thử trên desktop

```bash
cd /home/kiettran05/Desktop/test_Room_segmentation/NeuSymNav/.runtime/worktrees/Kiet_branch2
NEUSYMNAV_HYDRA_DEMO_CONFIG="$PWD/configs/demo-00807.hydra-room-slm-debug.experimental.local.json" \
  bash tools/run_hydra_map_demo.sh 00807 120 runs/slm-debug-00807-120s
```

Dùng thư mục output mới. Mở tab **Room labels (debug)**, chọn request, dùng **Expand/Pop out** để xem lớn; chọn history để kiểm tra đúng snapshot nguồn. Khi chạy từ shell desktop, bỏ biến `QT_QPA_PLATFORM=offscreen` nếu đã đặt. Cần cho model bind/kết nối `127.0.0.1`; không có dịch vụ bên ngoài.

120 giây là lệnh debug tùy chọn, **chưa được chạy/nghiệm thu trong task này**, không hứa sẽ có nhãn trước timeout. Guard/model vẫn giữ nguyên. Profile cũ tiếp tục chạy bằng UI entry cũ.

## Bước tiếp theo

1. Đo giảm chi phí prompt lạnh trước: schema đang lặp trong text và GBNF; thử prompt gọn nhưng giữ đủ object/relations, version/hash riêng, đối chiếu trên cùng context. Không tăng model hoặc deadline để che timeout.
2. Nối evidence sidecar đúng revision và kiểm tra association/category bằng gallery; không dùng human correction làm prompt input để báo accuracy.
3. Khi context thật hoàn tất trong deadline, chạy lại debug live có một kết quả hoàn tất + source snapshot/UI proof, rồi đánh giá quality trên human-reviewed rooms độc lập. Chưa bật mặc định, chưa dùng nhãn cho ObjectNav decisions.
