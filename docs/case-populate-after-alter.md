# Case test: populate data sau khi ALTER TABLE ở Warehouse

Mục tiêu: test luồng `deploy-warehouse.yml` end-to-end — publish schema change
(thêm cột mới) → tự động chạy stored procedure backfill cột đó cho dữ liệu cũ.
Bước populate hiện tại (`cicd/run_sql.py`) đang chạy ở chế độ `--skip-if-missing`
vì `Gold.usp_populate_new_columns` chưa tồn tại — case này là lúc thêm procedure
đó vào để bước populate thật sự chạy.

> **Trạng thái: Case A và Case B đều đã được implement.** Code thật đã nằm
> trong repo — xem 2 bảng ngay dưới.

## Case A đã code những gì

| File | Thay đổi |
| --- | --- |
| `fabric/insurance_WH.Warehouse/Gold/Tables/dim_customer.sql` | Thêm cột `[email_domain] varchar(255) NULL` ở cuối bảng |
| `fabric/insurance_WH.Warehouse/Gold/StoredProcedures/usp_populate_new_columns.sql` | **File mới** — proc backfill, idempotent, kèm 1 `SELECT` thống kê |
| `fabric/nb_transform.Notebook/notebook-content.sql` | Thêm biểu thức tính `email_domain` ở cuối `SELECT` của cell `INSERT INTO Gold.dim_customer` |
| `cicd/run_sql.py` | In ra result set mà proc trả về, để log CI thấy số dòng đã backfill |

## Case B đã code những gì

| File | Thay đổi |
| --- | --- |
| `fabric/insurance_WH.Warehouse/Bronze/Tables/customer.sql` | Thêm cột `[loyalty_signup_channel] varchar(50) NULL` ở cuối bảng |
| `fabric/insurance_WH.Warehouse/Bronze/StoredProcedures/usp_populate_new_columns.sql` | **File mới** — backfill `'unknown'` cho dòng cũ |
| `fabric/insurance_WH.Warehouse/Bronze/StoredProcedures/usp_seed_demo_data.sql` | Thêm cột vào `INSERT` + giá trị thật (`web`/`mobile`/`store`/`partner`) cho 10 dòng seed |
| `.github/workflows/deploy-warehouse.yml` | `POPULATE_PROC` → `POPULATE_PROCS` (danh sách có thứ tự), bước populate loop qua từng proc |

Điểm khác nhau giữa 2 case — đây mới là phần đáng chú ý:

| | Case A (Gold) | Case B (Bronze) |
| --- | --- | --- |
| Nguồn giá trị backfill | Suy ra được từ dữ liệu sẵn có (`email` → `email_domain`) | Không suy ra được — phải gán quy ước `'unknown'` |
| Dữ liệu nạp mới | `nb_transform` tự tính, luôn đúng | `usp_seed_demo_data` cấp giá trị thật |
| Dấu hiệu nhận biết dòng cũ | Không cần | Chính giá trị `'unknown'` |

Lý do: Gold là layer đã qua transform nên thường có sẵn dữ liệu để tính cột mới.
Bronze là raw/landing layer — dữ liệu đã nạp là dữ liệu nguồn đưa sang, không có
chỗ nào để "chế" ra giá trị lịch sử. Đây là giới hạn thật của bài toán, không
phải hạn chế của pipeline.

Cột `loyalty_signup_channel` **không chảy sang Gold** — `nb_transform` chọn từng
cột cụ thể (`c.customer_id, c.first_name, ...`) chứ không `SELECT *`, nên thêm
cột ở Bronze không làm hỏng notebook và cũng không tự xuất hiện ở
`Gold.dim_customer`. Muốn đưa lên Gold thì làm thêm 1 vòng Case A nữa.

## Thứ tự chạy trong pipeline

`deploy-warehouse.yml` khai báo:

```yaml
POPULATE_PROCS: >-
  Bronze.usp_populate_new_columns
  Gold.usp_populate_new_columns
```

Bước `Populate new columns` loop qua danh sách này **theo đúng thứ tự** —
Bronze trước Gold, vì Gold đọc dữ liệu từ Bronze. Thêm schema/bảng cần backfill
thì thêm tên proc vào cuối danh sách, không phải sửa step.

Mỗi proc chạy trong 1 `::group::` riêng nên log CI gấp/mở được từng cái.

Đã chạy `python cicd/validate_repo.py --target-env test` → 0 error.

Push thay đổi này vào `test` là `deploy-warehouse.yml` sẽ chạy (do có file trong
`fabric/**/*.Warehouse/**` đổi), và bước `Populate new columns` lần này sẽ **thật
sự chạy** chứ không còn skip.

## Điều cần biết trước khi code (quan trọng, dễ vỡ)

1. **`nb_transform` insert theo vị trí cột (positional), không có column list.**
   `INSERT INTO Gold.dim_customer SELECT ...` — nếu bạn thêm cột mới vào giữa
   bảng mà không sửa `SELECT` tương ứng trong
   `fabric/nb_transform.Notebook/notebook-content.sql`, lần `pl_silver` chạy tiếp
   theo sẽ lỗi "column count mismatch" ngay. Vì vậy: thêm cột mới **ở cuối** danh
   sách cột trong `CREATE TABLE`, để giảm rủi ro lệch vị trí.

2. **Backfill proc chỉ chạy 1 lần lúc CI deploy schema, không chạy lại mỗi khi
   `pl_silver` chạy.** `pl_silver`/`nb_transform` chạy độc lập (trigger riêng,
   không nằm trong `deploy-warehouse.yml`). Nếu sau này `pl_silver` chạy full
   rebuild (`DELETE` + `INSERT` lại toàn bộ `Gold.dim_customer`) mà `nb_transform`
   chưa được cập nhật để tự tính cột mới, cột đó sẽ quay lại `NULL` hết — proc
   backfill không tự chạy lại để sửa. Nên: cách đúng lâu dài là sửa luôn
   `nb_transform` để nó tự tính cột mới trong lần rebuild tiếp theo; proc backfill
   chỉ để vá cho các dòng **đã tồn tại từ trước** khi chưa kịp chạy lại
   `pl_silver`.

3. **Pipeline hiện tại chỉ gọi đúng 1 procedure**, tên cố định trong
   `deploy-warehouse.yml` (`env.POPULATE_PROC: Gold.usp_populate_new_columns`).
   Nếu muốn test thêm case cho Bronze (mục Case B bên dưới), phải tự thêm 1 lệnh
   gọi `run_sql.py` nữa trong workflow (procedure khác tên, ví dụ
   `Bronze.usp_populate_new_columns`) — pipeline chưa tự làm việc này.

4. **Trigger đúng path để pipeline chạy**: `deploy-warehouse.yml` chỉ kích hoạt
   khi có thay đổi trong `fabric/**/*.Warehouse/**`. Thêm file `.sql` mới trong
   `fabric/insurance_WH.Warehouse/...` là đủ để trigger.

## Case A — thêm cột cho Gold (khuyến nghị làm trước, đơn giản nhất)

Ví dụ: thêm `email_domain` vào `Gold.dim_customer`, suy ra từ cột `email` đã có
sẵn trong chính bảng đó — không cần đụng Bronze, không cần join thêm bảng nào.

**1. Thêm cột vào cuối bảng**
`fabric/insurance_WH.Warehouse/Gold/Tables/dim_customer.sql` — thêm dòng cuối
cùng trong danh sách cột (trước dấu `)`  đóng `CREATE TABLE`):

```sql
[email_domain] varchar(255) NULL,
```

**2. Viết stored procedure backfill**
File mới: `fabric/insurance_WH.Warehouse/Gold/StoredProcedures/usp_populate_new_columns.sql`

```sql
CREATE PROCEDURE Gold.usp_populate_new_columns
AS
BEGIN
    SET NOCOUNT ON;

    UPDATE Gold.dim_customer
    SET email_domain = LOWER(SUBSTRING(email, CHARINDEX('@', email) + 1, LEN(email)))
    WHERE email_domain IS NULL
      AND email LIKE '%@%';
END;
```

`WHERE email_domain IS NULL` làm cho proc idempotent — chạy lại nhiều lần không
sao, chỉ động vào dòng chưa có giá trị.

**3. (Nên làm) Cập nhật `nb_transform` để lần rebuild sau tự tính luôn cột này**
`fabric/nb_transform.Notebook/notebook-content.sql`, cell `INSERT INTO
Gold.dim_customer` — thêm 1 biểu thức nữa **ở cuối** danh sách `SELECT`, khớp
với vị trí cột vừa thêm ở bước 1:

```sql
    ...
    CAST(1 AS SMALLINT),
    LOWER(SUBSTRING(c.email, CHARINDEX('@', c.email) + 1, LEN(c.email)))
FROM       Bronze.customer  c
...
```

**4. Push và quan sát**

Push nhánh làm thay đổi 2-3 file trên vào `test` (hoặc `workflow_dispatch` tay
`deploy-warehouse.yml`). Kiểm tra theo thứ tự:

- Job `Preview changes` (artifact `warehouse-audit-<run_id>`, file
  `deploy-report.xml`) — xác nhận đúng 1 lệnh `ALTER TABLE ... ADD [email_domain]`,
  không có gì bị drop.
- Job `Publish schema` pass.
- Job `Populate new columns` — log phải in ra `EXEC [Gold].[usp_populate_new_columns]`
  (không phải notice "does not exist... Skipped").
- Query trực tiếp `SELECT TOP 20 customer_id, email, email_domain FROM
  Gold.dim_customer` trên warehouse — `email_domain` phải có giá trị cho các
  dòng cũ, không còn `NULL`.
- Chạy thử `pl_silver` (thủ công) sau đó — xác nhận không lỗi
  "column count mismatch" và `email_domain` vẫn được điền (nhờ bước 3).

## Case B — thêm cột cho Bronze (nếu muốn test luôn phía raw layer)

Bronze khác Gold ở chỗ: đây là raw/landing layer, không có công thức để "suy ra"
giá trị cho dữ liệu cũ — trừ khi bạn chấp nhận 1 giá trị mặc định. Ví dụ: thêm
`loyalty_signup_channel varchar(50) NULL` vào `Bronze.customer`.

**1. Thêm cột vào cuối bảng**
`fabric/insurance_WH.Warehouse/Bronze/Tables/customer.sql`:

```sql
[loyalty_signup_channel] varchar(50) NULL,
```

**2. Backfill — dùng giá trị mặc định vì không có nguồn thật để suy ra**
File mới: `fabric/insurance_WH.Warehouse/Bronze/StoredProcedures/usp_populate_new_columns.sql`

```sql
CREATE PROCEDURE Bronze.usp_populate_new_columns
AS
BEGIN
    SET NOCOUNT ON;

    UPDATE Bronze.customer
    SET loyalty_signup_channel = 'unknown'
    WHERE loyalty_signup_channel IS NULL;
END;
```

**3. Cập nhật seed data (vì repo này dùng `usp_seed_demo_data` thay cho ingest
thật)**
`fabric/insurance_WH.Warehouse/Bronze/StoredProcedures/usp_seed_demo_data.sql` —
thêm giá trị cho cột mới vào cuối `INSERT INTO Bronze.customer (...)`, nếu
không mọi lần seed lại từ đầu sẽ ra `NULL` và phải backfill lại.

**4. Wiring vào pipeline**
`deploy-warehouse.yml` hiện chỉ gọi `run_sql.py` một lần với
`--procedure "$POPULATE_PROC"` (mặc định `Gold.usp_populate_new_columns`). Muốn
proc Bronze cũng được gọi, thêm 1 step nữa (hoặc đổi `POPULATE_PROC` thành list
và loop), ví dụ:

```yaml
      - name: Populate Bronze new columns
        run: |
          python cicd/run_sql.py \
            --server "$INSURANCE_WH_ENDPOINT" \
            --database "$WAREHOUSE" \
            --procedure "Bronze.usp_populate_new_columns" \
            --skip-if-missing
```

Đặt step này **trước** step `Populate new columns` (Gold), vì Gold có thể phụ
thuộc dữ liệu Bronze mới trong tương lai.

## Dọn dẹp sau khi test xong

Nếu chỉ để test tính năng populate rồi không dùng cột demo này thật, nhớ:
xoá `email_domain` / `loyalty_signup_channel` khỏi 2 file `.sql` bảng, xoá 2
procedure, revert lại `nb_transform` — rồi push lại để `deploy-warehouse.yml`
đưa warehouse về đúng schema như cũ (`DropObjectsNotInSource=false` hiện đang
tắt nên object thừa sẽ **không** tự bị xoá — phải xoá thủ công trong file rồi
publish lại, hoặc chấp nhận cột đó ở lại warehouse).
