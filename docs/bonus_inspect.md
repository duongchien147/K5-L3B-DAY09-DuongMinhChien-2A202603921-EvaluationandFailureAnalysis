# Bonus: port 3 grader sang Inspect AI

Ba grader được viết lại thành scorer của Inspect AI (`inspect-ai==0.3.291`): `approval_bypass`, `refund_amount_correct`, `reply_matches_ledger` (FM-08). Sau đó mình so kết quả từng dòng với lần chạy pydantic-evals của `lab9.eval`.

```bash
cd src
pip install -r requirements-bonus.txt
python -m lab9.inspect_port                                    # spec v1
python -m lab9.inspect_port --spec config/metric_spec_v2.yaml \
  --shapes swarm,fixed,seeded_regression,slice_regression,flaky_regression,probe_sibling_refund,probe_misreport \
  --out reports/bonus_inspect_compare_v2.json                  # spec v2
```

## Cách làm

- Scorer được viết lại từ luật chấm trong `src/lab9/inspect_port.py`, không import từ `lab9.graders`. Nếu hai bên chỉ gọi chung một hàm thì kết quả khớp chẳng chứng minh được gì.
- Hai harness chấm trên cùng các trial. Solver của Inspect chạy shape bằng `lab9.eval.make_task`, đúng runner mà pydantic-evals dùng: mỗi lần một SQLite store mới, MockLLM, và `max_samples=1` để thứ tự chạy cố định. Model của Inspect là `mockllm/model`, chạy offline nên không cần API key. Model này không sinh ra gì cả, phần việc của "model" ở đây do shape đảm nhận.
- Mỗi `(item, seed)` là một `Sample`. Nhãn nằm trong metadata của sample, không nằm trong input.
- Inspect không có sẵn metric đếm vi phạm, nên mình viết thêm metric `count` cho `approval_bypass`. Đây là metric an toàn, phải bằng 0, không lấy trung bình.
- Các variant công khai không bao giờ ghi dòng ledger dưới claim khác, nên nếu chỉ dùng chúng thì `approval_bypass` lúc nào cũng ra False. Vì vậy mình thêm hai shape thử: `probe_sibling_refund` (bật FM-07) và `probe_misreport` (bật FM-08). Nhờ đó grader nào cũng có dòng báo lỗi thật để so.

## Kết quả

Cột "khớp" là số dòng hai harness cho cùng giá trị. Cột "báo lỗi" là số dòng grader đánh dấu có vấn đề.

Spec v1 (eval set `5ccde78aad06`, 14 item × 5 seed), report `src/reports/bonus_inspect_compare.json`:

| Shape | approval_bypass khớp / báo lỗi | refund_amount_correct | reply_matches_ledger |
|---|---|---|---|
| swarm | 70/70, 0 | 70/70, 1 | 70/70, 0 |
| fixed | 70/70, 0 | 70/70, 0 | 70/70, 0 |
| seeded_regression | 70/70, 0 | 70/70, 10 | 70/70, 15 |
| probe_sibling_refund | 70/70, 20 | 70/70, 20 | 70/70, 0 |
| probe_misreport | 70/70, 0 | 70/70, 0 | 70/70, 10 |

Spec v2 (eval set `3adcd5fff633`, 28 item × 5 seed), report `src/reports/bonus_inspect_compare_v2.json`:

| Shape | approval_bypass | refund_amount_correct | reply_matches_ledger |
|---|---|---|---|
| swarm | 140/140, 0 | 140/140, 3 | 140/140, 0 |
| fixed | 140/140, 0 | 140/140, 0 | 140/140, 0 |
| seeded_regression | 140/140, 0 | 140/140, 30 | 140/140, 40 |
| slice_regression | 140/140, 0 | 140/140, 9 | 140/140, 0 |
| flaky_regression | 140/140, 0 | 140/140, 5 | 140/140, 0 |
| probe_sibling_refund | 140/140, 55 | 140/140, 55 | 140/140, 0 |
| probe_misreport | 140/140, 0 | 140/140, 0 | 140/140, 30 |

Tổng cộng có 1.050 phép so sánh ở v1 và 2.940 ở v2, không có bất đồng nào. Lệnh trả exit 0.

Ngoài ra, `src/tests/test_lab9_inspect_port.py` so luật của bản port với `lab9.graders` trên 6 trial dựng tay: trial sạch, thiếu approval, dòng ledger lạ, sai số tiền trong ledger, reply nói sai số tiền, và reply từ chối không nêu số tiền. Cả 7 test đều xanh. Test tự bỏ qua khi máy chưa cài `inspect-ai`, nên job CI `eval-gate` không bị ảnh hưởng.

## Nhận xét

Hai harness khớp hoàn toàn là điều dễ hiểu: cả ba grader đều là code tất định, chỉ đọc ledger, trace và nhãn. Phép so sánh vẫn có giá trị ở hai điểm. Thứ nhất, luật chấm được viết hai lần một cách độc lập mà cho cùng kết quả trên 3.990 ô. Thứ hai, mọi grader đều có lúc báo lỗi, nên kết quả khớp không phải do cả hai bên luôn trả cùng một giá trị mặc định.

Khác biệt giữa hai framework nằm ở cách tổ chức. Inspect tách solver (chạy agent) khỏi scorer (chấm), và có thể lưu từng sample vào log `.eval` để xem lại bằng `inspect view`. Bản port hiện ghi log vào thư mục tạm rồi xoá sau khi đọc điểm. pydantic-evals gọn hơn khi chỉ cần một hàm task và vài evaluator. Gate của lab vẫn dùng pydantic-evals, phần port này chỉ để đối chứng.

Giới hạn: bản port chỉ chạy trên MockLLM. Với LLM thật, kết quả mỗi lần chạy có thể khác nhau, nên muốn so hai harness thì phải cho cả hai chấm trên cùng một trace đã ghi lại, thay vì để mỗi bên tự chạy agent.
