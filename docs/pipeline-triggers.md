# Trigger: mỗi pipeline chạy riêng khi nào

Repo có 4 workflow, 3 cái deploy + 1 cái validate. Bài này giải thích **điều
kiện nào làm mỗI cái chạy**, vì sao chúng không chồng lấn nhau — và 1 bug thật
đã gặp phải khi viết path filter cho GitHub Actions.

## Tóm tắt

| Workflow | Event | Điều kiện | 
| --- | --- | --- |
| `validate-pr.yml` | `pull_request` → `test` | file trong `fabric/**`, `cicd/**`, `.github/workflows/**` |
| `deploy-warehouse.yml` | `push` → `test` | có file trong `fabric/*.Warehouse/**` |
| `deploy-lakehouse.yml` | `push` → `test` | có file trong `fabric/*.Lakehouse/**` |
| `deploy-to-fabric.yml` | `push` → `test` | **không phải** mọi file đều nằm trong 2 pattern trên |

3 workflow deploy đều có thêm `workflow_dispatch` để chạy tay, không phụ thuộc
path filter.

---

## Cơ chế `paths` vs `paths-ignore`

GitHub Actions cho 2 khoá filter, ngược nhau:

- **`paths`** (allow-list) — workflow chạy nếu **có ít nhất 1 file** trong
  push khớp 1 trong các pattern.
- **`paths-ignore`** (deny-list) — workflow **bị bỏ qua** chỉ khi **toàn bộ**
  file trong push đều khớp pattern. Push có dù chỉ 1 file nằm ngoài pattern là
  vẫn chạy.

`deploy-warehouse.yml` và `deploy-lakehouse.yml` dùng `paths` (chỉ quan tâm
file của chính mình). `deploy-to-fabric.yml` dùng `paths-ignore` (nhận hết,
trừ 2 loại kia) — nên đúng vai trò "còn lại bao nhiêu thì tôi lo".

### Hệ quả: 1 push đụng nhiều loại file → nhiều workflow cùng chạy

Ví dụ push gồm 2 file: `fabric/insurance_WH.Warehouse/Gold/Tables/dim_customer.sql`
và `cicd/run_sql.py`.

- `deploy-warehouse.yml`: có file khớp `fabric/*.Warehouse/**` → **chạy**.
- `deploy-to-fabric.yml`: không phải *toàn bộ* file khớp pattern bị ignore
  (`cicd/run_sql.py` nằm ngoài) → **cũng chạy**.

Cả 2 chạy song song, không có thứ tự đảm bảo giữa 2 workflow khác file — đây
là hành vi **có chủ đích**, không phải bug: mỗi workflow tự lo đúng phần việc
của nó (warehouse deploy dacpac, deploy-to-fabric deploy script khác), không
việc gì phải chờ nhau.

---

## Bug đã gặp: `**` trong path filter là wildcard cấp ký tự, không phải cấp thư mục

Bản đầu viết pattern kiểu Unix glob quen thuộc:

```yaml
paths:
  - 'fabric/**/*.Warehouse/**'
```

Tưởng nghĩa là "thư mục nào bên dưới `fabric/`, item nào đuôi `.Warehouse`".
Nhưng [theo docs GitHub Actions](https://docs.github.com/actions/using-workflows/workflow-syntax-for-github-actions),
`**` khớp **"zero or more of any character"** — kể cả `/`, nhưng là 1 khối
ký tự liên tục, không có khái niệm "1 cấp thư mục".

Parse lại `fabric/**/*.Warehouse/**` theo đúng nghĩa đó: `**` đầu tiên có thể
khớp chuỗi rỗng, nhưng ngay sau nó vẫn còn 1 dấu `/` **literal** trong pattern
— tức là pattern này đòi hỏi có **thêm một cấp thư mục nữa** giữa `fabric/` và
tên item `*.Warehouse`. Trong khi item Fabric (`insurance_WH.Warehouse/`) nằm
**ngay dưới** `fabric/`, không có cấp trung gian nào. Kết quả: pattern **không
khớp bất kỳ file thật nào trong repo** — `deploy-warehouse.yml` không bao giờ
tự trigger từ push, im lặng, không báo lỗi gì cả.

Cách phát hiện: theo dõi tab Actions không thấy `deploy-warehouse.yml` xuất
hiện dù đã push đổi file warehouse nhiều lần.

**Fix**: bỏ `**/` thừa, dùng `*` (khớp mọi ký tự trừ `/`, đúng ý "tên item ở
ngay cấp này"):

```yaml
paths:
  - 'fabric/*.Warehouse/**'
```

Bài học rút ra — 2 điều cần nhớ khi viết path filter cho GitHub Actions:

1. `**` không tự "ăn" luôn dấu `/` đứng sau nó trong pattern — nó chỉ là 1
   khối ký tự khớp tham lam, không phải toán tử "bỏ qua N cấp thư mục" như
   trong `.gitignore` hay rsync.
2. Test bằng file thật trước khi tin: viết 1 script nhỏ so khớp pattern với
   vài đường dẫn file thật trong repo, đừng chỉ đọc pattern bằng mắt rồi đoán.

---

## Bảng định tuyến — file nào đi pipeline nào

| Đường dẫn file thay đổi | `deploy-warehouse` | `deploy-lakehouse` | `deploy-to-fabric` |
| --- | --- | --- | --- |
| `fabric/insurance_WH.Warehouse/Gold/Tables/dim_customer.sql` | ✅ | – | – |
| `fabric/insurance_WH.Warehouse/Bronze/StoredProcedures/*.sql` | ✅ | – | – |
| `fabric/test_LH.Lakehouse/shortcuts.metadata.json` | – | ✅ | – |
| `fabric/nb_transform.Notebook/notebook-content.sql` | – | – | ✅ |
| `fabric/nb_lakehouse_schema.Notebook/notebook-content.py` | – | – | ✅ |
| `fabric/pl_silver.DataPipeline/pipeline-content.json` | – | – | ✅ |
| `fabric/sales_semantic_model.SemanticModel/**` | – | – | ✅ |
| `fabric/report.Report/**` | – | – | ✅ |
| `cicd/*.py` | – | – | ✅ |
| `docs/*.md` | – | – | ✅ |
| `.github/workflows/*.yml` | – | – | ✅ |

Điểm dễ nhầm: `nb_lakehouse_schema.Notebook` gắn với Lakehouse về mặt *chức
năng* (nó tạo schema cho `test_LH`), nhưng về mặt *loại item* nó là
`Notebook`, không phải `Lakehouse` — nên đường dẫn của nó không khớp
`fabric/*.Lakehouse/**`, và nó được `deploy-to-fabric.yml` publish, không phải
`deploy-lakehouse.yml`. `deploy-lakehouse.yml` chỉ **trigger chạy** notebook
đó sau khi publish Lakehouse xong (xem
[`docs/post-deploy-flow.md`](post-deploy-flow.md)), chứ không publish nó.

---

## `workflow_dispatch` — chạy tay, bỏ qua path filter

Cả 3 workflow deploy có `workflow_dispatch`, dùng khi:

- Muốn chạy lại 1 pipeline mà không cần đổi file (ví dụ: warehouse sống bị
  lệch trạng thái với repo, muốn publish lại dù không có commit mới).
- Test 1 pipeline riêng lẻ mà không phải tạo commit giả để trigger path
  filter.
- `deploy-lakehouse.yml` còn nhận thêm input `run_job` để chạy 1
  pipeline/notebook cụ thể sau khi deploy, không phụ thuộc file nào đổi.

`workflow_dispatch` không quan tâm `paths`/`paths-ignore` — bấm là chạy, path
filter chỉ áp dụng cho trigger `push`.

---

## `validate-pr.yml` — khác model, không phải deploy

Đây là workflow duy nhất chạy trên `pull_request`, không phải `push`. Path
filter của nó rộng hơn nhiều (`fabric/**`, `cicd/**`, `.github/workflows/**`)
vì mục đích khác: PR đổi bất cứ thứ gì trong 3 vùng đó đều cần validate trước
khi merge — không cần tách theo Warehouse/Lakehouse/khác như 3 pipeline deploy,
vì nó không publish gì lên Fabric cả, chỉ kiểm tra tĩnh.

Do dùng `**` giữa 2 dấu `/` với glob thường (không phải path filter GitHub
Actions), pattern `fabric/**` ở đây **không** dính bug ở trên — `paths` cấp
cao nhất của GitHub Actions cho phép `dir/**` khớp mọi thứ bên dưới `dir/`
bình thường; bug chỉ xảy ra khi `**` bị kẹp giữa 2 phần literal khác của
pattern (`fabric/**/*.Warehouse/**`).
