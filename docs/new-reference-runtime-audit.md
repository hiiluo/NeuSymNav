# Đối chiếu NewOH3DSG:10phút và control20Hz — 2026-10-29

Đây là kết quả đọc mã/log gốc và probe CPU trên dữ liệu đã ghi. Chưa thay code,
quota, thời lượng hay contract của NeuSymNav; chưa chạy workload native mới.

## Kết luận

NewOH3DSG có evidence chạy10–15phút gần20Hz trung bình. Bản gộp hiện tại chưa
kế thừa đầy đủ cách tách nhịp runtime của New: capture RGB-D/navigation nối tiếp,
chờ map đúng source rồi mới plan/guard/execute. Giới hạn recording1GiB và run300s
là policy hiện có của NeuSymNav; không phải giới hạn máy hay điều kiện an toàn
vật lý. Cần sửa runtime và recording có kiểm chứng, không dùng20s như giải pháp
cho yêu cầu chạy dài hoặc tăng quota đơn lẻ như giải pháp cho10Hz.

## Evidence gốc

| Nguồn | Thời lượng / control trung bình | Phạm vi quan trọng |
| --- | --- | --- |
| New geometry soak |600s/~20Hz|không chứng nhận semantic/navigation|
| New11s/26s semantic/UI|900s/~20Hz|RGB640×480,modelinput480/544; hầu hếtSTOP,0forward; có jitter|
| New report26m native|60s/19.54Hz|modelinput480;17forward; p95interval164.9ms|
| New latest moving demo|600s/14.31Hz|5.86m, khôngfullrawreplay; reportkhôngpinmodelhash|
| New run khai báo26m|300s/11.62Hz|4.85m; requested640→adaptive480; khôngfullrawreplay|
| Neu current26m fixed640|20s/7.39Hz|fullprimary+navigationraw292/292; p95/p99165.5/173.7ms|

New count simulator.step bao gồmSTOP. Absolute timer có thể catch up sau vòng
chậm; ~20Hz trung bình không chứng minh mọi deadline50ms. CSV26s15min có1463/17999
khoảng>100ms và891khoảng<5ms. Neu đang đo invocation starts, New là post-step CSV:
không dùng hai population như một phép so sánh chuẩn hóa. Log này vẫn là căn cứ
để học tổ chức runtime, không nên bác nhận xét20Hz của người dùng.

Ba demo New600s có rawreplay=null. Một lượt600s bật replay chỉ ghi562/2357primary
observations, certificateincomplete, payloads còn lại phủ94.88s capture time.
Source hiện tại của New ghi primary-only, không giữ đủ mọidown/up/low-up sensor;
writer async NPZ DEFLATElevel1, lossless đối với normalized Observation arrays.
Mứccompressionlevel của artifact lịch sử không suy từ source hiện tại.

Chi tiết có dòng source, SHA và phép tính CSV:
- `runs/new-reference-runtime-audit-20261029/control/report.md`
- `runs/new-reference-runtime-audit-20261029/recording/report.md`

## Nguyên nhân trong NeuSymNav đã xác minh

1. `runtime/launcher.py:380–382,558–560`: captureprimary → capturenav → poseRPC →
   chờexactnav → control. Detector/room/UI đã tách, nhưng đó chưa phải tách nhịp
   sensor/mapping/planning/control. `_append_raw` vốn đã async, median0.02ms;
   không được quy lỗi cho producer đangfsync.
2. `sensors/habitat_worker.py:553` gọi render-all cho mỗi lane. Habitat0.3.3
   `Simulator.get_sensor_observations` lặpdraw/read tất cả3sensor. Probe CPU chạy
   nguyên method đã cài với3countingsensor:2calls→6draw/read. Chưa đo speedup;
   không suy chỉ bỏ render lặp là đủ20Hz.
3. Current30s timing:pairedcapturemedian60.33ms,mapwait28.28ms,controlstep46.10ms;
   UIpublish25.97ms ở graph lane. Cácstage overlap, không cộngquantile thành
   critical-path proof. Chuỗi chờ thực tế và jitter cần tách rõ ở bản sửa.
4. ReplayWriter đã async nhưng ghi ndarray JSON/base64 không nén, kiểm durability
   fsyncfile+directory và chứng nhận đủsource. Quota cộngdồnupperbound~2×arraybytes
   cộngmetadata, không hoàn trả phầnchênh so với durablebytes. Nén mà giữaccounting
   cũ chỉ giảm bytes thật, không tự kéo dài sốframe được nhận.
5. Ngoài1GiBarchivecap còn `cli.MAX_CAMPAIGN_DURATION_S=300` vàlauncher<=300s.
   Probe `_duration('600')` bị reject; tăng riêngarchivecap vẫn không chạy10phút.

## Dung lượng10phút nếu giữ format/accounting hiện tại

Ước tính tuyến tính từ dtype/shape/kíchthước frame đo được; chưa chạy600s.
Các số không gồm toàn bộ semantic assets/exports và không phảicam kết dunglượng.

| PrimaryRGB-D Hz | Navigationdepth Hz | Quota upperbound GiB | JSONpayloadước tính GiB |
| ---: | ---: | ---: | ---: |
|7.39|7.39|23.33|15.44|
|10|10|31.58|20.90|
|20|20|63.16|41.80|
|5|20|21.77|14.32|

Đây là lý do không nên chỉ đề xuấtarchive4GiB rồi gắn nhãn10phút. Với cadence
khác, phải tính lại theo từng sensor. Nénlossless và accountingactualdurablebytes
có thể giảm đáng kể quota cần thiết, nhưng cần định dạng/reader và kiểm chứng mới.

Probe4frame thực (3primary/1nav):JSONprimary3,277,995–3,278,013B→NPZlevel1
969,943–1,328,633B;nav462,003B→132,359B. Mọi dtype/shape/arraybytes kể cảNaNbitpattern,
metadata vàgeometryhash khớp, reconstructedcontractJSON khớp. EncodeCPUprimary
25.8–35.1ms trongprobe; đây không phải nativeFPS hay thốngkê codec đủ cho600s.

## Hướng sửa đề xuất, chưa triển khai

**A. Chạy dài và replay:** formatbinarylossless cóversion và backwardreader,
queue/bytecaps,durablechecksums, đầyđủprimary+navigation, counters/gap/clock/
calibrationprovenance. Quota táchdurableactualbytes khỏipendingupperbound và
headroommetadata/atomicwrite. Giữ nguyên certificate fail/incomplete khi thiếu
source. Cóprofile600s rõ ngân sách per-run/availabledisk; không bỏ tất cảcaps.

**B. Tách nhịp như New:** ưu tiênfreshnavigationdepth/control, primaryRGB-D640×480
vàsemantic ở nhịp riêng phù hợpthroughput, globalplanner/map/UI preparation qua
immutableboundedslots. Bỏ render-all lặp và xem xét capturetransaction/binaryIPC
cóversion. Một ownerHabitat/actuator, không gọi simulator đa thread tùy tiện.

Primary5Hz/nav20Hz là candidateđểđo, không phải lựa chọn người dùng đã chốt.
Mọi frame được tạo phải ghi đủ; đặtcadencecapture khác việc drop frame đã nhận.
RGB không giảmresolution và detector không tự giảmimgsz640 trongprofilefixed640.

**C. Giữ correctness:** sourceone-use, actualtimestamps/pose/calibration,
RGB-D/clearance/unknown semantics, TTL300ms, command/proof/footprint giữ nguyên.
New tái dùnglatestmap/depth trongageguard riêng; không chép đoạn này thành phát
lại một source nhưfreshcontrol. Path cũ chỉ là candidate cần kiểm lại trên dữ
liệu hiện hành; không cachecommand/proof. Thay sensor/IPC/scheduling seam cần
reviewSolHigh theo repo trước khi nghiệm thu.

**D. Nghiệm thu10phút:** bắt đầu bằng regression/boundednative checks, rồifreeze
một600s run giữfixed640/26m/recordingpolicy. Báo rawinvocationstartvector để
recompute mean/p95/p99/miss50msvà100ms, unique freshdepth/map/command counts,
stop/acceptedmotion/displacement,graphprogress, allrawcomplete,RSS/VRAM/disk và
cleanup. Không dùng timer/STOP/catchup/FPSUI để suy nghiệm thu. Minimum10Hz vẫn
là yêu cầu người dùng;20Hz là hướng tổ chức/đối chiếu, chưa phải kết quả Neu.

Chưa chọn mứccap cuối: phải tính theo cadence/codec/pending và kiểm thử mẫu
moving-scene trước. Ước lượng cho việc chuẩn bị không thay một lượt600s thực.

## Reproduce / artifacts

```sh
python3 runs/new-reference-runtime-audit-20261029/control/audit.py
python3 runs/new-reference-runtime-audit-20261029/recording/audit.py
PYTHONPATH=src .venv/bin/python runs/new-reference-runtime-audit-20261029/current/audit_current.py
.venv/bin/python runs/new-reference-runtime-audit-20261029/current/probe_render_calls.py
```

Cáclệnh đã chạyexit0. Initialcodec helper dùngst_size() sai (intproperty) exit1,
đã sửahelper; logaudit-first.log giữ nguyên. Không sửaproduction/sourcefolders,
không cài/tải mới, khôngGPU/nativebenchmark. Aggregate report/pins ở
`runs/new-reference-runtime-audit-20261029/report.md` vàmanifest.json.
