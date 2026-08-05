# Flow sau khi deploy: populate data (Warehouse) & tạo schema (Lakehouse)

Hai pipeline `deploy-warehouse.yml` và `deploy-lakehouse.yml` đều làm 2 việc
tách biệt: **publish schema/item** rồi **chạy code để dữ liệu/schema thực sự
có mặt**. Bài này giải thích phần thứ 2 — chuyện gì xảy ra *sau khi* publish
xong, cho cả 2 bên, và vì sao 2 bên làm theo 2 cách khác hẳn nhau.

## Tóm tắt 1 câu

- **Warehouse**: publish schema bằng dacpac (SqlPackage tự tính diff) →
  chạy 1 loạt stored procedure T-SQL qua kết nối SQL trực tiếp để backfill
  dữ liệu cho cột/bảng vừa thêm.
- **Lakehouse**: publish item Lakehouse (không có schema-as-code) → gọi Fabric
  REST API để chạy 1 notebook Spark SQL, chính notebook đó chứa lệnh
  `CREATE SCHEMA` / `CREATE TABLE` để tạo ra schema.

---

## Phần 1 — Warehouse: publish schema → populate data

File: [`.github/workflows/deploy-warehouse.yml`](../.github/workflows/deploy-warehouse.yml)

### Sơ đồ các bước (job `deploy`, sau khi job `validate` pass)

```
1. Azure login (Reader SP, OIDC)
2. Lấy secret Deploy SP từ Key Vault
3. Publish item Warehouse (fabric-cicd, scope ["Warehouse"])
4. Resolve SQL endpoint + grant db_ddladmin cho Deploy SP
5. Build dacpac
6. Preview: DeployReport + Script  → ghi ra artifact TRƯỚC khi áp dụng
7. Publish schema: sqlpackage /Action:Publish
8. Populate new columns: loop qua POPULATE_PROCS, chạy từng stored procedure
```

Bước 1–7 là phần "dacpac" thông thường. Bài này tập trung vào **bước 8**.

### Bước 8 — Populate new columns

```yaml
env:
  POPULATE_PROCS: >-
    Bronze.usp_populate_new_columns
    Gold.usp_populate_new_columns

# ...
      - name: Populate new columns
        run: |
          for proc in $POPULATE_PROCS; do
            echo "::group::$proc"
            python cicd/run_sql.py \
              --server "$INSURANCE_WH_ENDPOINT" \
              --database "$WAREHOUSE" \
              --procedure "$proc" \
              --skip-if-missing
            echo "::endgroup::"
          done
```

Cơ chế:

- `POPULATE_PROCS` là **danh sách có thứ tự**, phân tách bằng khoảng trắng.
  Bash `for proc in $POPULATE_PROCS` lặp đúng theo thứ tự khai báo.
- **Bronze chạy trước Gold** — vì Gold đọc dữ liệu từ Bronze (`nb_transform`
  join từ các bảng `Bronze.*`). Bronze chưa đầy đủ thì backfill Gold dựa trên
  dữ liệu sai/thiếu.
- Mỗi lần lặp gọi [`cicd/run_sql.py`](../cicd/run_sql.py) — script này connect
  thẳng vào SQL endpoint của warehouse (cùng connection string dùng để publish
  dacpac) và chạy `EXEC <schema>.<procedure>`. Không qua Fabric REST API,
  không qua Job Scheduler — là 1 lệnh SQL bình thường.
- `--skip-if-missing`: nếu procedure chưa tồn tại trong warehouse (ví dụ mới
  khai báo cột nhưng chưa viết proc backfill), script chỉ log `::notice::` rồi
  thoát mã 0 — **không làm fail cả pipeline**. Thêm procedure mới vào
  `POPULATE_PROCS` là an toàn, không sợ pipeline đỏ trước khi kịp viết proc.
- Mỗi procedure chạy trong 1 khối `::group::...::endgroup::` riêng — log CI
  gấp/mở được từng procedure, dễ đọc khi danh sách dài ra.

### Vì sao mỗi procedure phải tự viết `IF NOT EXISTS` / `WHERE ... IS NULL`

Bước 8 **chạy lại ở MỌI lần** `deploy-warehouse.yml` chạy — không phải chỉ lần
đầu thêm cột. Nên mọi procedure trong `POPULATE_PROCS` bắt buộc phải
**idempotent** (chạy lại nhiều lần cho kết quả giống nhau, không phá dữ liệu
đã đúng). Ví dụ thật đang có trong repo:

```sql
-- Gold.usp_populate_new_columns (fabric/insurance_WH.Warehouse/Gold/StoredProcedures/)
UPDATE Gold.dim_customer
SET email_domain = LOWER(SUBSTRING(email, CHARINDEX('@', email) + 1, LEN(email)))
WHERE email_domain IS NULL          -- chỉ động vào dòng CHƯA có giá trị
  AND email LIKE '%@%';
```

```sql
-- Bronze.usp_populate_new_columns (fabric/insurance_WH.Warehouse/Bronze/StoredProcedures/)
UPDATE Bronze.customer
SET loyalty_signup_channel = 'unknown'
WHERE loyalty_signup_channel IS NULL;
```

Cả 2 đều `WHERE ... IS NULL` — lần chạy thứ 2 trở đi không có dòng nào khớp
điều kiện nữa nên `UPDATE` không làm gì, an toàn.

### Thêm 1 cột/bảng mới cần backfill — quy trình

1. Sửa file `.sql` của bảng trong `.sqlproj` (thêm cột, để `NULL` hoặc có
   default).
2. Viết 1 stored procedure mới (hoặc sửa procedure có sẵn của đúng schema đó),
   idempotent.
3. Nếu là procedure mới hoàn toàn, thêm tên vào `POPULATE_PROCS` trong
   `deploy-warehouse.yml`, đúng vị trí theo thứ tự phụ thuộc dữ liệu.
4. Push vào `test` — dacpac tự sinh `ALTER TABLE ADD COLUMN`, bước populate tự
   backfill dòng cũ.

Xem ví dụ đầy đủ, từng bước, đã code sẵn trong repo tại
[`docs/case-populate-after-alter.md`](case-populate-after-alter.md) (Case A —
Gold, Case B — Bronze).

---

## Phần 2 — Lakehouse: publish item → tạo schema qua notebook

File: [`.github/workflows/deploy-lakehouse.yml`](../.github/workflows/deploy-lakehouse.yml)

### Sơ đồ các bước (job `deploy`, sau khi job `validate` pass)

```
1. Azure login (Reader SP, OIDC)
2. Lấy secret Deploy SP từ Key Vault
3. Publish item Lakehouse (fabric-cicd, scope ["Lakehouse"])
4. Apply lakehouse schema: trigger notebook nb_lakehouse_schema
5. (tùy chọn) Run post-deploy job — workflow_dispatch input run_job
6. Deployment summary
```

### Bước 4 — Apply lakehouse schema

```yaml
env:
  SCHEMA_NOTEBOOK: nb_lakehouse_schema

# ...
      - name: Apply lakehouse schema
        run: |
          python cicd/trigger_job.py \
            --workspace-id "..." \
            --item-name "$SCHEMA_NOTEBOOK" \
            --item-type Notebook \
            --wait \
            --timeout-minutes 20 \
            --skip-if-missing
```

Cơ chế:

- [`cicd/trigger_job.py`](../cicd/trigger_job.py) gọi **Fabric REST API**
  (`POST .../items/{id}/jobs/instances?jobType=RunNotebook`) để khởi chạy
  notebook `nb_lakehouse_schema` — **khác hẳn** cách Warehouse làm (Warehouse
  không dùng REST API, gọi SQL trực tiếp).
- `--wait`: poll trạng thái job mỗi 20 giây tới khi `Completed`/`Failed`.
  `--timeout-minutes 20`: DDL nên nhanh, không cần đợi tới mặc định 60 phút.
- `--skip-if-missing`: notebook chưa tồn tại (chưa tạo trong Fabric UI) thì
  log notice rồi bỏ qua, không fail pipeline.
- Notebook `nb_lakehouse_schema` **không nằm trong scope publish của
  `deploy-lakehouse.yml`** (nó là `Notebook`, không phải `Lakehouse`) —
  `deploy-to-fabric.yml` mới là chỗ publish chính notebook này lên workspace.
  `deploy-lakehouse.yml` chỉ **trigger chạy nó**.

### Nội dung notebook `nb_lakehouse_schema` hiện tại

```python
%%sql
CREATE SCHEMA IF NOT EXISTS dbo
```

```python
%%sql
CREATE TABLE IF NOT EXISTS dbo.publicholidays (
    countryOrRegion      STRING,
    holidayName           STRING,
    normalizeHolidayName  STRING,
    isPaidTimeOff         BOOLEAN,
    countryRegionCode     STRING,
    date                  TIMESTAMP
)
USING DELTA
```

Notebook gắn với Lakehouse `test_LH`, chạy Spark SQL, mỗi cell đều
`IF NOT EXISTS` — idempotent, vì cũng như bên Warehouse, notebook này **chạy
lại ở mọi lần** `deploy-lakehouse.yml` chạy.

### Vì sao Lakehouse KHÔNG có "dacpac" tương đương

Đây là khác biệt kiến trúc quan trọng nhất giữa 2 bên:

| | Warehouse | Lakehouse |
| --- | --- | --- |
| Cách khai báo schema | Khai báo bảng mong muốn trong `.sqlproj` | Không có schema-as-code — chỉ có notebook |
| Ai tính ra lệnh thay đổi | SqlPackage tự diff, tự sinh `ALTER TABLE` | Không ai tính — bạn tự viết `CREATE ... IF NOT EXISTS` |
| Idempotency | SqlPackage tự đảm bảo (diff-based) | Người viết notebook tự đảm bảo |
| Xem trước khi áp dụng | Có — `DeployReport`/`Script` artifact | Không có |
| Backfill dữ liệu | Stored procedure T-SQL, gọi SQL trực tiếp | Chưa có cơ chế tương đương — notebook hiện chỉ tạo schema, chưa insert data |
| Cơ chế trigger | Không qua REST API | Qua Fabric REST API (`jobType=RunNotebook`) |

Nói cách khác: dacpac là **state-based** (khai báo đích, công cụ tự tính đường
đi), notebook là **imperative** (tự viết từng lệnh). Muốn sửa cột có sẵn trong
Lakehouse (không phải thêm mới) thì phải tự viết `ALTER TABLE ... ADD COLUMNS
IF NOT EXISTS` (Delta hỗ trợ thêm cột kiểu này) — sửa/xoá cột thì Delta không
hỗ trợ an toàn qua `ALTER`, cần cân nhắc riêng (đổi tên bảng, tạo lại, v.v.),
không giống Warehouse chỉ cần sửa file `.sql` là dacpac tự lo.

### Thêm 1 bảng mới cho Lakehouse — quy trình

1. Mở notebook `nb_lakehouse_schema` trong Fabric UI.
2. Thêm 1 cell mới: `CREATE TABLE IF NOT EXISTS <schema>.<table> (...) USING DELTA`.
3. Fabric Git sync tự đẩy thay đổi về repo (`fabric/nb_lakehouse_schema.Notebook/notebook-content.py`).
4. Push (hoặc để Git sync tự tạo commit) — `deploy-to-fabric.yml` publish
   notebook, lần `deploy-lakehouse.yml` kế tiếp (khi có thay đổi trong
   `*.Lakehouse/**`) sẽ chạy lại notebook và tạo bảng mới.

Lưu ý: nếu chỉ sửa notebook mà **không** đụng gì trong
`fabric/**/*.Lakehouse/**`, `deploy-lakehouse.yml` sẽ không tự trigger — phải
chạy tay qua `workflow_dispatch`, hoặc đợi lần đổi Lakehouse tiếp theo.

---

## So sánh nhanh 2 flow

| | Warehouse (bước 8) | Lakehouse (bước 4) |
| --- | --- | --- |
| Script gọi | `cicd/run_sql.py` | `cicd/trigger_job.py` |
| Cách kết nối | SQL trực tiếp (pyodbc, cùng connection string publish) | Fabric REST API (`jobType=RunNotebook`) |
| Chạy gì | Danh sách stored procedure, có thứ tự (`POPULATE_PROCS`) | 1 notebook duy nhất (`nb_lakehouse_schema`) |
| An toàn khi chưa tồn tại | `--skip-if-missing` | `--skip-if-missing` |
| Idempotency | Do người viết procedure đảm bảo (`WHERE ... IS NULL`) | Do người viết notebook đảm bảo (`IF NOT EXISTS`) |
| Chạy lại mỗi lần deploy? | Có | Có |
