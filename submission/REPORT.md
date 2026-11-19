# Báo cáo Day 09 — Trương Mỹ Tâm, 03106

## 1. Kết luận trước

- Ảnh vào: 224 (tổng số ảnh trong data/raw)
- Ảnh ra: 202 (Số ảnh còn lại sau bước intake)
- 22 ảnh bị loại gồm:
    - 17 ảnh bị phát hiện trùng/ rò rỉ
    - 5 ảnh lỗi hoặc không đạt kích thước
- 80 ảnh reviewed: giới hạn trong configs/pipeline.yaml, mục review.budget_images.
- 38/202 (18.8%) ảnh cảnh báo chưa duyệt => HOLD (vì tỉ lệ 18.8% vượt ngưỡng 10%, clean_v1 chỉ là dataset nháp ở trạng thái Hold, chưa đủ điều kiện Release chính thức).


## 2. Lỗi và phân việc
Lấy từ `02_error_list_v1` (gom theo mã lỗi). Cột "ai sửa": **máy** (autofix) hay **người** (hàng đợi); chỉ ghi những mã có mặt trong lô của bạn.

| Mã lỗi | Số ảnh/dòng | Ai sửa (máy/người) | Vì sao |
|---|---:|---|---|
|BAD_CLASS_ID|6|MÁY|ID lớp ngoài khoảng cho phép, có thể xóa dòng chắc chắn sai|
|BAD_CLASS_NAME|2|Máy|Tên lớp sai, có thể sửa theo cấu hình chuẩn|
|BAD_FORMAT|3|Máy|Dòng nhãn sai định dạng, xóa được an toàn|
|BAD_SIZE|3|Máy|Ảnh nhỏ hơn kích thước tối thiểu|
|BOX_OUT_OF_IMAGE|8|Máy|Box vượt biên, có thể clip về trong ảnh|
|BOX_ZERO|4|Máy| Box có chiều rộng/cao bằng 0|
|CORRUPT_IMAGE|2|Máy|Ảnh không thể đọc, cần loại khỏi dòng dataset|
|DUP_BOX|7|Máy|Box cùng lớp bị trùng, có thể xóa dòng lặp|
|DUP_IMAGE_EXACT|8|Máy|Ảnh trùng hoàn toàn theo MD5|
|DUP_IMAGE_NEAR|4|Máy|Ảnh gần trùng theo perceptual hash|
|LEAK_TEST|5|Máy|Ảnh bị trùng hoặc rò rỉ với tập test/validation, có thể làm sai lệch kết quả đánh giá model|
|MISSING_LABEL_FILE|6|người|Máy không được tự tạo nhãn, cần người gán|
|BOX_HUGE|3|người|Box rất lớn, cần kiểm tra ngữ nghĩa|
|BOX_TINY|6|người|Box quá nhỏ, có thể là vật thể thật hoặc lỗi|
|CLASS_RARE|4|người|Lớp xuất hiện ít, cần kiểm tra phân bố|
|EMPTY_LABEL|12|Người|Model nghi ngờ nhãn thừa, cần người xác nhận|
|POSSIBLE_LOOSE_BOX|28|Người|Box lệch nhưng không thể tự sửa chắc chắn|
|POSSIBLE_MISSING|53|Người|Model thấy vật thể nhưng nhãn có thể bị thiếu|
|POSSIBLE_WRONG_CLASS|18|Người|Model và nhãn khác class, cần người quyết định|

Hàng đợi review có 125 ảnh, nhưng ngân sách người duyệt chỉ là 80 ảnh. Ảnh được ưu tiên theo trọng số lỗi trong cấu hình: NEEDS_LABEL có trọng số cao nhất, tiếp theo là các lỗi ngữ nghĩa như POSSIBLE_WRONG_CLASS, POSSIBLE_MISSING và POSSIBLE_LOOSE_BOX. Vì vậy các ảnh thiếu nhãn hoặc có nguy cơ sai ngữ nghĩa được ưu tiên đưa lên đầu hàng đợi.

## 3. Calibration (2 ngưỡng)
| Tham số | Khởi đầu | Đã chọn | Precision / Recall (trước → sau) | Lý do (đánh đổi) |
|---|---|---|---|---|
| `duplicates.phash_dist` | 2 |10 |DUP_IMAGE_NEAR: 1,00 / 0,50 → 1,00 / 0,67|Tăng khả năng phát hiện ảnh gần trùng nhưng vẫn không tạo false positive trên tập calibration|
| `second_opinion.conf` | 0.25 |0.60|POSSIBLE_WRONG_CLASS: 0,56 / 0,83 → 0,62 / 0,83; POSSIBLE_MISSING: 0,50 / 1,00 → 0,57 / 1,00|Precision tốt hơn, recall của các lỗi quan trọng vẫn được giữ ở mức cao|

Ngưỡng cao hơn không phải lúc nào cũng tốt hơn. Ví dụ `second_opinion.conf = 0.8` có precision của `POSSIBLE_WRONG_CLASS` là 1,00 nhưng recall giảm đối với một số loại lỗi, nên có thể bỏ sót lỗi thật. Vì vậy không nên chỉ tối ưu một chỉ số mà cần cân bằng precision và recall.

## 4. Cửa chặn và điều pipeline KHÔNG bắt được
(a) Chứng minh gate chặn đúng:
Tôi chạy pipeline với ngân sách review = 0:

    $env:PYTHONUTF8='1'
    .\.venv\Scripts\python.exe -m pipeline.run `
    --budget 0 `
    --reports work/rep_nb `
    --export-dir work/exp_nb

  Vì không có ảnh nào được người duyệt xử lý, 6 lỗi MISSING_LABEL_FILE vẫn còn. Gate kết luận Rework, chương trình trả về mã thoát 20, và không xuất dataset vào work/exp_nb. Điều này chứng minh lỗi bắt buộc không thể bị bỏ qua chỉ vì ảnh chưa được review. Kết quả này nằm trong file tạm work/rep_nb/08_summary.json.

  Ý nghĩa:

- budget = 0: không có ngân sách cho người review.

- n_errors = 6: còn 6 lỗi bắt buộc.

- decision = Rework: phải quay lại sửa dữ liệu.

- Mã thoát 20: dùng cho CI hoặc script để biết pipeline thất bại do lỗi dữ liệu.

- Không có export: dataset chưa đủ điều kiện xuất.

(b) Hai điểm mù của pipeline

- Ảnh gần trùng bị biến đổi mạnh. Với phash_dist = 10, calibration đạt precision 1,00 nhưng recall chỉ 0,67 cho DUP_IMAGE_NEAR, nghĩa là pipeline vẫn có thể bỏ sót một số ảnh gần trùng. Nếu ảnh trùng lọt vào train, kết quả đánh giá model có thể bị sai lệch
- Các box lỏng nhẹ hoặc lệch nhẹ. Sau review vẫn còn 20 cảnh báo POSSIBLE_LOOSE_BOX trong 07_error_list_v3.csv. Model chỉ cho biết IoU thấp, nhưng không thể chắc chắn box đó sai hoàn toàn; do đó pipeline không tự sửa mà cần người kiểm tra.

## 5. Train: raw vs clean (tùy chọn, chấm riêng)

Chưa chạy vì không đủ thời gian làm.

## 6. Quyết định và ghi chú AI

- Quyết định cuối cùng của pipeline là Hold. Hiện không còn lỗi bắt buộc, nhưng vẫn còn cảnh báo trên 38/202 ảnh, tương đương 18,81%, cao hơn ngưỡng 10%. Để chuyển sang Release, cần review và xử lý thêm các ảnh còn cảnh báo, đặc biệt là POSSIBLE_MISSING, POSSIBLE_WRONG_CLASS và POSSIBLE_LOOSE_BOX, cho đến khi tỷ lệ cảnh báo chưa duyệt giảm xuống dưới 10%.

- Prompt chính: yêu cầu AI triển khai 4 module còn thiếu theo docstring, cấu hình và unit test có sẵn.
Cách kiểm tra: đọc và hiểu lại code, chạy toàn bộ 79 unit test, chạy pipeline end-to-end và đối chiếu các file report.
Một lần AI sai: AI đề xuất tự động sửa các lỗi ngữ nghĩa như sai class hoặc thiếu nhãn; tôi đã sửa lại để các lỗi này chỉ được cảnh báo và chuyển cho người review.

*(Thưởng +2, tùy chọn)* CVAT: lọc `width < 20`, ảnh/số box khớp, đối chiếu `BOX_TINY` (xem docs/CVAT_FILTER.md), 1 câu về `can_review`.
