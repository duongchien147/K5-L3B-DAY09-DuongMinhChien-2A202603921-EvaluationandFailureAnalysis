# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5`

FAIL là lớp dương, vì việc của judge là tìm ra reply hỏng. Sàn: κ ≥ 0.6, P ≥ 0.8, R ≥ 0.7. Nếu κ không xác định thì coi như FAIL.

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | Đạt | dùng |
| helpful | 100 | 0.375 | 1.000 | 0.300 | Không (κ và R dưới sàn) | loại |

Ma trận nhầm lẫn:

- tone_ok: tp 24, fp 4, fn 6, tn 66. Tỉ lệ FAIL judge quan sát được là 0.28, sau hiệu chỉnh Rogan-Gladen là 0.30.
- helpful: tp 9, fp 0, fn 21, tn 70. Tỉ lệ FAIL quan sát là 0.09, sau hiệu chỉnh là 0.30. Như vậy judge chỉ thấy chưa tới một phần ba số reply hỏng.

## Case audit thủ công

Có 10 bất đồng ở tone_ok (6 fn, 4 fp) và 21 bất đồng ở helpful (cả 21 đều là fn). Bảng dưới gồm 7 case tone và 4 case helpful.

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha, anh check giúp em." | PASS | FAIL | Người | Xưng "em" kèm "nha" là quá suồng sã với khách đang khiếu nại. Sửa rubric: nêu rõ cách xưng hô bắt buộc là "LogiX" và "anh/chị", cấm "em/bạn/nha". |
| 2 | H-029 "Dạ, vui lòng chờ. Hệ thống đang xử lý, không cần nhắn thêm." | PASS | FAIL | Người | Judge chỉ bắt từ lịch sự "Dạ, vui lòng", bỏ qua câu ra lệnh. Sửa rubric: đánh giá cả câu, câu ra lệnh hoặc chặn khách liên hệ là FAIL dù có từ lịch sự. |
| 3 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Judge phạt vì thiếu lời xin lỗi. Sửa rubric: xin lỗi không bắt buộc, reply ngắn mà lễ phép và đủ ý thì PASS. |
| 4 | H-051 "Dạ, LogiX đã refund 90.000đ cho đơn O-202 ạ." | FAIL | PASS | Người | Quy định CS của LogiX cho dùng từ "refund". Sửa rubric: thêm danh sách từ tiếng Anh được phép. |
| 5 | H-063 "Dạ, LogiX đã hoàn 20.000đ và sẽ hoàn thêm cho anh/chị ạ." | PASS | FAIL | Người | Giọng thì ổn, nhưng reply hứa "sẽ hoàn thêm" ngoài kết quả hệ thống. Lỗi này không thuộc tone. Sửa rubric: ghi rõ tone_ok không chấm nội dung cam kết; lời hứa sai phải để grader code so với ledger bắt. |
| 6 | H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn theo chính sách hiện hành ạ." | FAIL | PASS | Judge | Người gán nhãn đọc nhầm ticket. Hành động: sửa nhãn người, không sửa rubric. |
| 7 | H-094 "Da, LogiX da hoan 40.000đ cho don O-341, xin loi vi su bat tien." | PASS | FAIL | Người | Reply mất dấu tiếng Việt, kiểu dịch máy. Sửa rubric: tiếng Việt thiếu dấu là FAIL. |
| 8 | HL-015 "Dạ, LogiX đã hoàn 55.000đ cho đơn O-112 ạ." | PASS | FAIL | Người | Ledger ghi 40.000đ. Judge không xem ledger nên không biết số tiền sai. |
| 9 | HL-016 reply xin lỗi hai lần, báo "đã hoàn 55.000đ cho đơn O-404" | PASS | FAIL | Người | Ledger ghi 35.000đ. Reply dài, nhiều lời xin lỗi, và judge chấm PASS dù số tiền sai. |
| 10 | HL-047 "Ok bạn, đơn O-515 xử lý rồi nhé." | PASS | FAIL | Người | Không nói kết quả và số tiền, khách không biết đơn được xử lý ra sao. |
| 11 | HL-087 "Dạ, LogiX đã hoàn 60.000đ cho đơn O-202 ạ." | PASS | FAIL | Người | Ledger ghi 90.000đ, reply báo thấp hơn số thật. |

## Kết luận

tone_ok qua cả ba sàn nên dùng được, nhưng chỉ cho đúng việc chấm giọng điệu. Các bất đồng còn lại phần lớn do rubric chưa nói rõ cách xưng hô, câu ra lệnh, từ tiếng Anh được phép và lỗi mất dấu. Sau khi sửa rubric theo bảng trên thì phải calibrate lại trên một tập nhãn mới.

helpful bị loại. κ = 0.375 và recall = 0.30 đều dưới sàn: trong 30 reply người chấm FAIL, judge chỉ bắt được 9. Precision 1.0 không cứu được, vì judge gần như luôn nói PASS. Cả 21 lỗi bị bỏ sót đều thuộc hai loại. Một là số tiền trong reply khác ledger (FM-08), thường được bọc trong nhiều câu xin lỗi. Hai là reply cụt kiểu "Ok bạn, đơn ... xử lý rồi nhé". Judge không có ledger trong ngữ cảnh nên không thể chấm đúng loại thứ nhất. Đây là việc của grader code: số tiền luôn chấm bằng code. Gate mà dùng judge này sẽ cho qua khoảng 70% reply hỏng.

Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai. Muốn có held-out thật thì cần nhãn người mới. Tập 100 dòng cũng nhỏ, κ và recall có thể dao động vài điểm phần trăm nếu đổi mẫu.
