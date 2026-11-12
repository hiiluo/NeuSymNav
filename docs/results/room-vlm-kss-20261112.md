# Qwen3-VL và chọn ảnh phòng theo KSS

00770 và 00806 có profile `demo-<scene>.hydra-vlm.{cpu,gpu}.local.json`.
Các profile dùng chung Qwen3-VL-2B-Instruct Q4_K_M và projector F16,
chuyển từ snapshot sẵn có `89644892e4d85e24eaac8bacfd4f463576704203`
trong `local-assets/models/qwen3-vl`. GPU dùng llama.cpp Vulkan0.

## Chọn và sử dụng ảnh

Bộ chọn duyệt tối đa 64 MiB phần cuối journal Hydra. Nó xác minh nguồn
frame đã được chấp nhận, rồi dùng điểm depth trong hệ tọa độ thế giới
và membership của các place để ước lượng ảnh đang nhìn vào phòng nào.
Ít nhất 80% mẫu depth hợp lệ và ít nhất một nửa tổng số mẫu ảnh phải
quy về phòng đích. Các mẫu xác định thuộc phòng bên được che trên JPEG.
Mỗi ảnh lưu riêng revision của frame đã chấp nhận và revision graph
dùng để xác định phòng.

Hai phương pháp dùng chung ảnh rộng đầu tiên, tối đa hai ảnh và cạnh
dài 448 px. Geometry ưu tiên ô không gian chưa phủ. KSS tính thêm vật
thể thấy mới, mức hỗ trợ mask/depth tốt hơn và cặp vật thể đồng xuất hiện.
Qwen3-VL có thể viện dẫn ảnh hợp lệ khi Hydra chưa gán được vật thể.
Nhãn được kiểm tra theo revision và ID ảnh đã gửi. Bước chọn ảnh và
suy luận chạy ở tiến trình UI ngoài đường điều khiển.

## Replay so sánh

Dùng cùng model GGUF, projector và request text cho từng phòng, với
ba điều kiện và thứ tự luân phiên trong từng run. Server được làm nóng
trước phép đo. KV prompt cache tắt trong các lượt đo. Chỉ ba phòng
được chấm theo nhãn tham chiếu xem ảnh thủ công trước suy luận, gồm
kitchen của 00770 và bedroom, hallway của 00806. Các nhãn này chỉ áp
dụng cho vùng thấy trong ảnh và không được đưa vào prompt.

| Điều kiện | Khớp tham chiếu | Median CPU | Median Vulkan |
| --- | ---: | ---: | ---: |
| Chỉ text | 1/3 | 2.00 s | 0.38 s |
| Text + ảnh theo hình học | 3/3 | 6.17 s | 0.81 s |
| Text + ảnh theo KSS | 3/3 | 6.02 s | 0.72 s |

Median tính trên các lần model thực sự suy luận, hai lượt cho chỉ text
và ba lượt cho mỗi điều kiện ảnh, trên mỗi thiết bị. Thời gian chưa
tính bước chọn ảnh. Hai phương pháp chọn cùng ảnh ở tập chính.

Ba replay bổ sung của 00806 được phục hồi bbox từ file Spark-DSG gốc
khớp SHA của publication. KSS chọn ảnh thứ hai khác ở cả ba case
(271→282, 13→11, 25→26). Hai điều kiện ảnh cùng trả `bedroom` ở
cả ba. Hai case có tham chiếu là các lượt ghi lặp của cùng một phòng
ngủ. Case còn lại không được chấm. Kết quả chưa cho thấy mức tăng độ
đúng của KSS so với geometry.

Trong demo 00806 CPU 65 giây, tại revision 23 model gán `hallway`
khi context có 0 vật thể, viện dẫn frame 37/rev20 và frame 35/rev19.
Launcher thoát 1 với `incomplete` vì bộ thu số liệu từ chối 628 bản ghi.
UI đóng sạch. Chưa đo mức ảnh hưởng lên cadence điều khiển, chất lượng
trên tập phòng lớn, hay tỷ lệ ảnh lẫn phòng bằng chú thích độc lập.

Các báo cáo theo điều kiện, JPEG đầu vào và provenance nằm dưới
`runs/room-vlm-kss-20261112/`. Tập chính dùng các thư mục
`eval-{00770,00806}-{cpu,gpu}`. Tập bổ sung dùng
`eval-extra-{0,1,2}-gpu`. Tổng hợp là `comparison-summary.json`.
