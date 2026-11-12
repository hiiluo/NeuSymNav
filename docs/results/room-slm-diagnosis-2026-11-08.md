# Room SLM: stage latency, non-thinking và output rejection — 2026-11-08

## Kết luận

Đã chẩn đoán bằng7 request thật trên2context cũ,3server process tuần tự; không model/download mới, không thay source product hoặc default/config geometry. **Chưa đạt quality/live gates.** Phép đo phân rã cho thấy CPU inference một thread (prefill+decode), không phải chỉ startup/model initialization, chiếm phần lớn thời gian. Non-thinking được áp dụng đúng. Lỗi invalid tái hiện là invariant semantic giữa các field không được JSON grammar hiện tại bảo đảm; không phải response JSON bị hỏng cú pháp.

Human review pack và phản hồi thật đã có dưới `runs/room-slm-diagnosis-20261108/human-review/`; tổng hợp `human-reviewed-readiness.json`. Đã nhận A1bathroom/sink, Bbedroom+bathroom, C/Dcùngbedroom, Dbackgroundbathroomqua small doorway, Eliving_room/O0sofa. Không gán cảmulti-viewcard thànhmộtroomtype hoặc gọi đó là boundaryGT. Chưa đạt12eligible physicalrooms.

## Protocol và reproducibility

- Model/runtime/config pin giữ nguyên từ `runs/room-slm-pilot/S2/qwen3-1.7b-q4km-cpu.json`; SHA model/runtime kiểm trước mỗi process. CPU1thread,4096context,384output,greedy/seed0, local127.0.0.1 only. No simulator/control/detector workload trong task này; worker chỉ chuẩn bị ảnh nhẹ.
- Hai frozen contexts chọn trước khi chạy: singleton `00805-r45/request-001.json` (mirror O(3)); `00807-r2/request-000.json` (9semanticobjects). Không dùng annotation/humananswer để chọn output hoặc chỉnh label. Query validity/membership không chứng minh visual category đúng.
- Diagnostic timeout100s để quan sát completion của request vốn timeout60s; **production deadline60s không đổi**, không ghi case>60s là performancepass. Source requests/calibration/graph hashes giữ nguyên.
- `cache_prompt=false`,1inflight; mỗi request có native `cache_n=0`: đo prefill không bị cache che. Server dùng chung giữa requests để tách startup khỏi inference. Không flush OS pagecache, nên startup là process spawn→health, gồm modelinit/warmup/HTTP; không gọi là cold-disk-load benchmark. Hashverification tách riêng trong protocol.
- Probe đầu dùng JSONschema có property order alphabetic từ canonical schema serialization, khác production insertion order. Đây là exploratory timing/template probe, **không** production-output parity; giữ riêng note. Hai probe sau dùng `_output_schema()` đúng property order production. Grammar property order có thể thay constrained decoding mặc dù semantic schema/hash canonical giống nhau; không gộp các output như deterministic repeated trials.
- First sandbox attempt bị chặn tạo socket trước khi model chạy; lần retry approved dùng escalation cho loopback local. Không coi đó là model/runtime failure.

## Đo trực tiếp từ native timings

Đơn vị giây. Startup là một lần/server, lặp trong hàng chỉ để tham chiếu, không cộng startup cho mọi warm request. HTTP gần tổng prefill+decode; adapter dưới1ms trong mẫu này. Đây là individual cases, không benchmark p95 hoặc paired statistical guarantee.

| Stage / case | Prompt tokens native | Startup→health | Prefill | Decode | HTTP request | Validator result |
|---|---:|---:|---:|---:|---:|---|
| probe / mirror | 334 | 2.99 | 18.91 | 16.32 | 35.24 | invalid |
| probe / nine-objects | 883 | 2.99 | 50.95 | 30.75 | 81.71 | invalid |
| probe/ablation / mirror-original | 334 | 2.67 | 20.75 | 15.29 | 36.05 | invalid |
| probe/ablation / mirror-policy-explicit | 399 | 2.67 | 26.00 | 12.57 | 38.58 | insufficient_evidence |
| probe/ablation / nine-original | 883 | 2.67 | 57.28 | 33.62 | 90.94 | invalid |
| probe/compact / mirror-policy-explicit | 399 | 2.77 | 24.85 | 11.19 | 36.05 | insufficient_evidence |
| probe/compact / mirror-policy-compact | 244 | 2.77 | 14.77 | 9.54 | 24.36 | invalid |

Artifact `analysis.json` có raw native speed/counts, process RSS/PSS và source hashes. RSS là peak toàn vòng đời persistent server, không phải phép đo riêng từng request. Health2.67–2.99s so với original mirror inference36.04s và nine-object90.94s: riêng tiết kiệm load/startup chưa giải quyết deadline. Tuy nhiên persistent server **có thể** còn cho phép KV-prefix cache; cache reuse chưa đo trong task này, không suy rằng persistent chỉ có thể giúp đúng3s.

## Non-thinking: kiểm chứng tại runtime

1. `/props.chat_template` byte-identical với upstream tokenizer_config template, SHA `a55ee1b1660128b7098723e0abcd92caa0788061051c62d51cbe87d9cf1974d8`.
2. `/apply-template` với enable_thinking=false kết thúc bằng `<|im_start|>assistant\n<think>\n\n</think>\n\n`; true không có empty closed-thinking prefix. Cùng native template được dùng để parse chat request.
3. Chat request thực tế và server flag đều đặt false; response không có reasoning_content và không sinh chain-of-thought riêng. Không có bằng chứng thinking bị bật ngầm là nguyên nhân timeout. Non-thinking không loại chi phí prefill/decode bình thường.

## Output bị loại: nguyên nhân và thử nghiệm nhỏ

- **Reproduce exact historical singleton:** production schema+prompt gốc trả lại office/alternatives[office] và nguyên câu giải thích chiếc mirror chứng minhoffice. Adapter loại `response_field_invalid` đúng. JSON syntax/schema primitive hợp lệ, nhưng primary label trùng alternative. Semantic claim không được evidence mirror đơn lẻ hỗ trợ.
- **Nine-object original** hoàn tất sau~91s khi cho diagnostic deadline100s, nhưng vẫn invalid do primarylabel xuất hiện trong alternatives. Response còn gộp `O(7), O(8)` thành một supporting string không phải native ID hợp lệ; không tự tách/sửa. Production timeout60s là đủ để ngắt trước completion; tăngtimeout không sửa output consistency hoặc association error.
- **Prompt-policy-only A/B:** giữ nguyên context/schema, chỉ append generic abstention và alternatives rules. Mirror đổi từ invalid proposedoffice sang `insufficient_evidence` hợp lệ. Hai lần policy response vẫn cho bathroom/bedroom alternatives mặc dù prompt yêu cầuempty; host contract hiện cho phép điều này. Đây là schema-valid abstention, **không** accepted semantic roomlabel/accuracy evidence hoặc chứng minh full instruction following.
- **Compact-text A/B:** giữ context+policy+runtime constrained schema, bỏ schema text lặp.399→244nativeprompttokens, prefill24.85→14.77s; HTTP36.05→24.36s trong một cặp quan sát. Nhưng model trả unknown/alternatives[unknown], bị adapter loại. Không promote prompt rút gọn; không auto-repair hoặc lọc alternatives để báo pass.
- Output schema hiện ràng buộc types/enums/maxitems, không diễn đạt `label not in alternatives` và semantic-evidence adequacy. Host checks vẫn cần thiết; syntactically-valid output chưa chứng minh factuality. Không hạ strictvalidator.

## Dữ liệu kiểm duyệt

AI draft và dự đoán model giữ nguyên. Bộ review mới phải hiển thị actual RGB và source-bound opaque IDs, để người dùng tự xác nhận roomtype/unknown, samephysicalroom/different/unclear và suspected objectclass mismatch. Các subarea khác nhau nhưng cùng mergednativecontext không thành nhiều SLM samples độc lập. Evidence incomplete không đủ gate dù ảnh trông đúng.
HumanresponseA1 được lưu riêng/hash-bound (`human-question-response.json` và pack human-responses); chỉbathroom cho visibleviewA1 vàsink choO16, khônggánA2/A3/nativetotalR0. Đã nhận thêmB–E và Dclarification; source-bound responses/readiness ghi scope riêng, không gánnhãn cácobjectchưa được trảlời hoặc fullgeometry. Target12eligible physicalrooms/≥3scenes còn thiếu dữ liệu detector-backed với geometry/membership phù hợp, không thể lấp bằng cách đếm lại revisions.


### Human review nhận trong chat và sửa provenance

- Người dùng xác nhận A1 làbathroom, O16sink; B nhìn thấy bedroom vàbathroom ởhai phía; C/D cùngmộtbedroom; D cònthấy bathroom phía saucửa nhỏ; E living_room/O0sofa. Giữverbatim, sourceview/frame/PNGhash, parentcard vàscope. C/D không được đếm2physicalrooms; backgroundbathroom không làm primaryD thànhmixed. E nativecategorybed là inputsemanticerror được humanxácnhận chođúngsource, correction chỉevaluator.
- **Phát hiện cross-run trong AI draft00805:** ảnh/audit run`c5695459...`,graph`af1c335...`, nhưng draft gắn request run`3aeb490...`,graph`3122fd...`,context`cdcd80...`. O16không có trongrequestcũ, O17 sourcebathtub nhưngrequestpillow. `review-binding-audit.json` giữproof; scene/revision/localOID giống nhau không đủidentity. Không dùngannotation00805 đểchấm oldrequest hoặc gánlabelchooldmodeloutputs.
- **Đã tạo request mới đúngsource00805**, read-only load nativeexport ở `runs/hydra-demo-00805-300s-lan-2`, dùng existingproductiongraph-summary/snapshotbuilder. `corrected-00805/request-000.json`: runc569/graphaf1/context`511c7c7c0a70...`,14R0objects; cả14khớp sourceaudit ID/category/membership. Prefixactual`8f591e09...` khácold`c9ebfb7c...`. Olddraftbindingquarantined, không ghi đè request/prediction cũ, chưa infer requestmới. First nativeimport attempt thiếu PYTHONPATHnative được giữlog; retry giữ exportedenvironment chạyexit0, không cài dependency.
- C/Dsource00806 và Esource00807 có exactrun+nativegraphSHA match requests cũ; `audit_review_bindings.py` exit0. **Humanroomtype là visualreference**, fullnativeextent/boundaries và background-objectmembership cònchưa được annotation, nên không đưa vào geometry-correct subset như đãchứngminh.
- 00806 AI-draft “living+bedroom merge” không được tiếp tục coi là groundtruth: C/Dhumanreview chỉ ra cùngbedroom; vẫn có thể cần kiểm tra bathroomphíasaucửa riêng. Không nhân roomcount nhờmultiview hoặcsemanticslabel.
- `human-reviewed-readiness.json` có3source-contextgroups, trongđó00805multi-area cầnroomextent review; khôngtuyênbố12eligiblecases hoặc qualitypass. Cácviewgiữnull khihumanchưa trảlời. Mọi correction/reference chỉevaluator, khôngfeed vàoSLMprompt.00807 đãlộlabel/diagnosticoutputs, không gọi futuretuning trênnó là pristineheldout; cầnnewheldout choformalbenchmark.

## Hướng tiếp sau evidence này

1. Kiểm tra bounded request-specific schema/contract có thể ngăn label lặp trong alternatives và sai status/support ở thời điểm decoding, giữ validator và rawoutput audit. Đây là thay đổi cần tests và review riêng, chưa implement trong task này.
2. Sau khi output consistency ổn, A/B compact context/prompt và short reason trên cùng source; cân nhắc bỏ alternatives ở contractv2 nếu người dùng muốn, không âm thầm sửa v1. Không đưa roomGT hoặc correction từhuman vào runtimeprompt để làm đẹp điểm.
3. Đo persistent warm KV-prefix cache riêng, rồi mới cân nhắc threadbudget qua controlledAB với control telemetry; không tự tăng CPU/GPU lúc chưa đo contention. Không nâng model4B trước khi tách prompt/contract/data defects.
4. Thu human review và bổ sung independent detector-backed rooms; freeze reviewed dev/heldout trước qualityeval.1mẫuabstain hoặc7calls không là qualitybenchmark.

## Kiểm chứng / giới hạn

`PYTHONPATH=src .venv/bin/python runs/room-slm-diagnosis-20261108/analyze.py` exit0:7rawresponses được adapt+validate lại, request/source/script hashes match,3loadedtemplates match, cache_n0, timing reconciliation và6geometry/profile hashes match. Không sửa installedHydra/privateDSO/default/control, không nghiệm thu liveSLM. Source scripts/protocol/request/rawresponse/log/metrics được giữ dưới runtime/{.,ablation,compact}/; process đã đóng sau từng stage. Focused adapter/prompt/contract tests29passed0.62s/exit0. `audit_review_bindings.py` và correctedsourcebuilder exit0, 14objectchecks pass; `git diff --check` exit0. Humanpack source/outputhash checks lưu verification riêng; sheet initialdisplayarchive giữtrước khi sửaheader cross-run. Finalverification13source/outputPNGbindings,3humanreplies,14corrected00805objectmatches; sharedSLMconfigenabled=false. Artifact `runs/room-slm-diagnosis-20261108/final-verification.json`. Không biếnlogfixture thànhinferencequalitypass.
