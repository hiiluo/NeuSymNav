# Human-marked bathroom/hallway reference — 2026-11-07

Người dùng cung cấp ảnh đánh dấu trực tiếp trên blindmap300s: xanh lá là phòng tắm, xanh lam/cyan là hành lang, đỏ là khoảng ô cửa. Đây là **vùng tham chiếu dương tính do người dùng chỉ ra**, không phải full-house room annotation hay đường bao tường vật lý đầy đủ.

## Chuyển tọa độ và phạm vi nhãn

Original source map2204×1285; markedimage2204×1286. Căn các gridlines ngoài vùng vẽ cho offsets X≤1px vàY≤2px (tối đa≈0.0154m), giữ piecewise mapping có thứ tự; sourceplot left86/top78,130px/m,worldXmin−6,Ymax2. Dùng tọa độ của bản đồ gốc, không trừ pose hay thay origin.

Tách màu từ nét vẽ, dùng interiors khép kín bởi nét màu (nét đỏ đóng phần ring xanh bị đè), lấy contour phía trong ink và simplify≤1.5px. Seed pixel của flood được assistant chọn bên trong nét người dùng, không lấy từ graph hay prediction. Contours không mở ra biên ảnh; lưu masks, vertices gốc, affine/grid mapping, SHA image vàsource manifest để kiểm tra.

- Bathroom:40vertices; X≈[-1.273,0.142],Y≈[-1.951,-0.996]m.
- Hallway:137vertices; X≈[-1.196,3.913],Y≈[-1.112,1.435]m.
- Đỏ: polyline phạm vi ô cửa; không đo chiều rộng thật, không biến thành wall/occupancy obstacle hay runtime portal.

Primaryuncertainty0.10m bổ sung từ innerstroke edge, quanh outline vàredline; overlap vàngoài hai vùng làunknown. Nhãn chỉ áp dụng interiors chắc chắn; không suy toàn bộ physicalroom từ các vòng khoanh. Đặc biệt, đây **khác qualitativeROI cũ** dùng khảo sát GVD. Không yêu cầu seed phải nằm trong vòng mới để kết luận corepoints đã tách.

[Annotation đã căn trên source map (SVG)](../../runs/hydra-objectnav/B1-human-20261107/annotation-registered.svg), [polygons/metadata](../../runs/hydra-objectnav/B1-human-20261107/human-regions.json), [ảnh người dùng giữ nguyên](../../runs/hydra-objectnav/B1-human-20261107/marked-by-user.png). SourcefileSHA vàpixelmaps trong JSON; script extraction vàrastercheck là analysis-only.

## Phương pháp đối chiếu

Chỉ đối chiếu recordinglong300 cùng58accepted inputs, prefix `1103b62bf0cfedf5d285991f60b0bd8d9c167056693da9747a75dd3773244bf9`:

1. Default comp1.0/component10/merge0.5:102places cuối.
2. Experimental comp0.5/component3/merge0.5:135places cuối.
3. Experimental comp0.5/component3/merge0.25:399places cuối.

Actualnative membership và graph snapshots từ task trước, không chạy simulator/decoder/detector mới và không đưa GT vào runtime. Mỗi output annotation gắn exactgraphSHA/runID/revision; cùng một polygonworld được chiếu độc lập lên support của từng graph, không truyền IDs giữa density variants. Offlineannotation từ cuối recording có thể đánh giá observedsupport ở prefix trước đó khi sourcebinding được kiểm tra; đó là evaluator-only, không làm robot biết trước GT.

Báo regioncounts, unknown/unassigned, confusion GT×predroom vàcoverage. Chỉ coi hai vùng có thể so sánh khi mỗi vùng có confident assigned support; một vùng mất prediction không được tính purity1 rồi gọi là tách đúng. Ưu tiên cross-region coassignment rate (bathroom×hallway assignedpairs bịgán cùngpredroom), cùng fragmentation vàexistingpairwise metrics. IoU/purity có thể bị classimbalance hay unmatched-GT làm trông cao, không dùng một mình để chọn default.

Điểm domain lànative3Dplacepoints chiếuXY trong singlefloor; nhiều điểm cùngXYkhácZ không là independentfloorarea samples. Scores mô tả humaninteriors, không phải accuracytổngthể hay physicalboundaryF1. Cần lượngsupport/coverage vàtimeline để diễn giải.

## Kết quả trên174snapshot

Primarymargin0.10m. Cả ba finalsnapshot khớp **toàn bộ assignments** với kiểm tra độc lập image-space raster; không tune polygon/margin để ép khớp. Source graph/phần mesh-free revision kiểm tra SHA riêng với mesh-bearing close export, không yêu cầu SHAhai loại file bằng nhau.

| Profile | Confident bath/hall points cuối | Gán room cuối | Cross-region pairs cùng room cuối | Point-domain F1 cuối |
| --- | --- | --- | --- | --- |
| Default comp1/component10/merge0.5 | 3 /18 | Cả haiR0 | 54/54=100% | 0.8525 |
| Comp0.5/component3/merge0.5 | 3 /21 | BathR1,HallR0 | 0/63=0% | 1.0 |
| Comp0.5/component3/merge0.25 | 8 /62 | BathR1,HallR0 | 0/496=0% | 1.0 |

DefaultF1≈0.85 không có nghĩa phòng được tách đúng: hallway chiếm nhiều points, còn100%bath×hallpairs bị gộp. Confidentcoverage cuối chỉ21/102≈20.6%,24/135≈17.8%,70/399≈17.5% toànplacepoints; vùng ngoài/biên không được tính đúng hoặc sai. Hai candidates đúng trên **các corepoint được đánh dấu ở snapshot cuối**, chưa chứng minh toànphysicalroom/doorboundary.

### Qua58revision, không chỉsnapshot cuối

| Profile | Revisions đủ cả hai vùng có assigned support | Còn gộp hai vùng | Chia vụn một vùng đánh dấu | Core separation đầy đủ |
| --- | --- | --- | --- | --- |
| Default |52/58 |52 |0 |0 |
| Merge0.5 (comp0.5/min3) |50/58 |17 |0 |31 |
| Merge0.25 (comp0.5/min3) |53/58 |3 |13 |37 |

“Core separation đầy đủ” ở đây yêu cầu mỗi humanregion có mộtpredroom, hairoomkhác nhau và không corepoint nào unassigned. Qualityavailable là có sharedsupport, chưa đồng nghĩa completecoreassignment; merge0.5 có2frameavailable nhưng chỉ gán một phần corepoints. Các frame thiếu một vùng/confidentassignedsupport trảunavailable, không được tính như tách đúng.

Trên **50revision chung đủ dữ liệu của hai candidates**, merge0.5 có17mixed/0fragmented/31strictlyseparated; merge0.25 có3mixed/10fragmented/37strictlyseparated. Đây là so sánh cùng timestamps/regions; support density/point weights vẫn khác giữa profiles.

- Merge0.5 tái gộp ở16–18,25–32,37–38,45,52–53,56.
- Merge0.25 tái gộp ở **36,49,57**; chia hành lang trong reference thành hai groups ở6–18 rồi nối lại ở19. Giai đoạn đầu thiếu coverage có thể cần provisionalregions; không mặc nhiên coi mọi sửa đổi là lỗi confirmedroom.
- Default luôn gộp khi có thể chấm; revision24 có referencebathpoints nhưng chưa được graphgán room, được fail-closed thay vì chấm purity1 của hallway còn lại.

![Kết quả target theo từngrevision](../../runs/hydra-objectnav/B1-human-20261107/human-target-history.png)

Legend: xanh lục làstrictcoreseparation; đỏ làhai GTregions sharepredroom; tím làmộtGTregion bịfragment; vàng làpartialassignment; xám làchưa đủcặp đểchấm. Các màu này làoutcome visualization, không thay đổi nghĩa xanh lá/xanh lam trong ảnh người dùng.

### Vì sao ba lần tái gộp còn lại quan trọng

Đối chiếu native RoomFinder reconstruction trên actualcurrentgraphs (co-membershipmatchactualworker được kiểm tra ở task trước):

| Revision | Ngưỡng native tái dựng (m) | Seed chứa bathroomcorepoints |
| --- | --- | --- |
|35 |0.5656853 | Có,5corepoints |
|36 |0.6324555 | Không |
|37 |0.5656852 | Có,5corepoints |
|48 |0.5656852 | Có,5corepoints |
|49 |0.6324556 | Không |
|50 |0.5656852 | Có,5corepoints |
|56 |0.5656852 | Có,5corepoints |
|57 |1.0000001 | Không; hallwaycore cũng không nằm trongseed |
|58 |0.5656852 | Có,5corepoints |

Ngưỡng globalPLATEAU thay đổi làm seed vùngmục tiêu biến mất rồi trởlại, tương ứngcác lần gộp đã thấy từ reference. Đây là bản dựng offline nativecùnginputgraph/config, không giả lognội bộhistoricalworker. Ởrev57 globalroomcount vẫn3 nhưng bathroom/hallway bịgộp: đếm sốrooms không phát hiện được lỗi này.

Vì vậy ưu tiên tiếp theo là chẩn đoán/ổn định **global threshold/seed survival và quyết định merge qua thời gian**, thay vì tiếp tục giảm khoảng cáchmerge đểtăngnodes. Bất kỳ roommemory/hysteresis nào sau đó phảicho phép sửa đúng khi có nhiều chứng cứmới, không khóa segmentation vĩnhviễn và không dùngGTpolygon/redline như runtimewall.

### Độ nhạy với annotation thô

Lặp cùng174snapshot với uncertainty0.05m và0.15m (chỉ đổi policy exclusion, giữ userpolygons/image/source): danh sách revisiontái gộp không đổi cho cảba profiles. Finalcandidates đều vẫn tách hai vùng; confidentpointcounts cóthay đổi (ví dụmerge0.25 bath8–12,hall61–65). Primary0.10m không được chọn lại dựa trênscore. Có174uniquegraphsnapshots;348sensitivityevaluations dùng lại graphs, không phải348đợtreplay.

## Kết luận và bước tiếp

Nhãn người dùng xác nhận **default đang undersegment hai vùng được đánh dấu**. Merge0.25 là ứng viên đáng kiểm tra tiếp hơn về việc tránh tái gộp target, nhưng không đạt ổn định và có oversplitbanđầu; chưa đưa thành mặc định. Quan sát seed nằm ngoài qualitativeROI trước đây không tự chứng minh phân phòng sai; hiện có referencecore nên đánh giá trực tiếp theo vùngngười dùng, và vẫn táchpartialreference khỏi completeboundaryaccuracy.

Giữ nguyên productiondefault trong lượt này. Bước có căn cứ tiếp theo là kiểm tra filtration/threshold/seed ở36/49/57 và thiết kế chính sách chống merge transient dựa trên evidence native, rồi nghiệm thu lại với reference đã khóa. Giá trị cost từ task trước vẫn làsingleoffline trials, không làlivefreshnesspass. Physicaldoorwidth, fullboundaryF1, unannotatedrooms vàliveObjectNav chưađược xác nhận.

## Kiểm chứng

- Implemented `tools/evaluate_hydra_human_regions.py` và8tests; labels chỉevaluation, exactgraphSHA/runID/revision vàacceptedinputchain được ràng buộc; annotationJSONSHA/markedimageSHA/sourceManifestSHA cùng xuấtprovenance.
- **78focusedtests passed2.67s/exit0**, nativefixtureenv enabled, khôngskip; khôngfullsuite. Evaluator CLI3cases×58revs exit0. Không chạy lại nativeHydra/simulator/GPU/detector/modeldownload/training, không thay runtime/default/control.
- Humanảnh/mapping/polygonsmasks giữdấu vết; polygonconvertersimple/concave, uncertainty/overlap, graphhash/sourcebinding, missingGTclass hoặcassignedclass được tests. Nét đỏ chỉuncertainty range.
- [Evaluation index](../../runs/hydra-objectnav/B1-human-20261107/evaluation/index.json), [target summary](../../runs/hydra-objectnav/B1-human-20261107/target-summary.json), [badrevision native seeds](../../runs/hydra-objectnav/B1-human-20261107/bad-revision-seeds.json), [verification](../../runs/hydra-objectnav/B1-human-20261107/verification.json).

ExactCLI evaluation/timingtest commands trongartifact evaluation/index.json, evalcommand/log files vàtests-command.json; testexit trongtests.exit, sensitivitycommands riêng. Lệnh tổng hợp:

```bash
PYTHONPATH=src .venv/bin/python runs/hydra-objectnav/B1-human-20261107/verify_human_eval.py
```

Task đối chiếu partialhumaninteriors đã hoàn tất. Fullroom boundaryquality, stabilitypromotion vàwholeObjectNavroadmap vẫn chưa hoàn tất; không suy metric1.0 ởsnapshot cuối thànhdemo/live/default-ready.
