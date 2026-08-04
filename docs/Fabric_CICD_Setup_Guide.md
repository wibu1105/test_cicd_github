# Fabric CI/CD — Technical Setup Guide (Draft)

> Bản nháp, viết theo đúng state hiện tại của repo (branch `dev`). Copy nội
> dung này lên Claude web để format lại đẹp hơn / xuất ra Word nếu cần. Chỗ nào
> có `📷 [Figure ...]` là chỗ cần chụp màn hình rồi dán vào.

## Contents

1. [Overview](#1-overview)
2. [Azure Setup - Service Principal](#2-azure-setup---service-principal)
3. [GitHub Setup](#3-github-setup)
4. [Fabric Setup](#4-fabric-setup)
5. [Deployment Architecture](#5-deployment-architecture)
6. [Repository Structure](#6-repository-structure)
7. [Key Vault Setup](#7-key-vault-setup)
8. [Deployment Scripts](#8-deployment-scripts)
9. [Running the First Deployment](#9-running-the-first-deployment)

---

## 1. Overview

### 1.1 What we are building

Một pipeline CI/CD deploy các item Microsoft Fabric (Warehouse, Lakehouse,
Notebook, DataPipeline, SemanticModel, Report) từ GitHub repo này lên workspace
Fabric, chạy hoàn toàn bằng GitHub Actions. Không có bước thủ công nào trong
Fabric UI để publish — chỉ push code vào nhánh `test` là tự chạy.

Cơ chế xác thực: GitHub OIDC → **Reader SP** (không có secret lưu trữ) → đọc
Key Vault → lấy secret của **Deploy SP** → SP này mới có quyền thật trên
Fabric/Warehouse. Chi tiết ở mục 2 và mục 7.

```
GitHub repo (push/PR) → GitHub Actions
                            │
                 azure/login (Reader SP, OIDC)
                            │
                        Key Vault  ──► lấy secret Deploy SP
                            │
              fabric-cicd / SqlPackage / Fabric REST API
                            │
                    Fabric workspace (test)
```

📷 **[Figure 1 — Kiến trúc tổng quan: GitHub repo → Actions → Azure → Fabric workspace]**

### 1.2 Prerequisites

- Quyền tạo App registration + Key Vault trên Azure subscription.
- Một Fabric capacity (trial được) + quyền Fabric Admin để bật tenant setting
  **"Service principals can use Fabric APIs"**.
- Quyền Admin trên GitHub repo (branch ruleset, Environments, Secrets).
- Một workspace Fabric để làm dev (đặt tên gì cũng được, tài liệu này gọi là
  `my-dev`), có Git integration.

---

## 2. Azure Setup - Service Principal

Repo dùng **2 service principal** với 2 vai trò khác nhau — đây là điểm quan
trọng nhất của model xác thực, không nên gộp làm 1:

| SP | Vai trò | Cách xác thực |
| --- | --- | --- |
| **Reader SP** | Login vào Azure trong workflow, chỉ dùng để đọc Key Vault | OIDC (federated credential) — **không có secret nào lưu trữ** |
| **Deploy SP** | SP thật, có quyền publish lên Fabric workspace và quyền `db_ddladmin` trên Warehouse | Client secret, secret này lưu trong Key Vault |

Các bước tạo (App registration cho cả 2 SP):

1. Entra ID → App registrations → New registration → đặt tên (vd.
   `sp-fabric-reader`, `sp-fabric-deploy`).
2. Copy lại **Application (client) ID** và **Directory (tenant) ID** của cả 2.
3. Với **Deploy SP**: vào Certificates & secrets → New client secret → copy
   **Value** ngay lúc đó (chỉ hiện 1 lần). Ghi lại ngày hết hạn — secret này
   phải tự rotate thủ công định kỳ.
4. Với **Reader SP**: **không** tạo secret. Thay vào đó tạo **Federated
   credential** (xem mục 3.5 / 7.5) để login qua OIDC từ GitHub Actions.

📷 **[Figure 2 — App registration Overview page (Deploy SP)]**
📷 **[Figure 3 — Certificates & secrets: tạo client secret cho Deploy SP]**

---

## 3. GitHub Setup

### 3.1 Create the repository

Tạo repo GitHub bình thường, connect nó với Fabric workspace dev qua Git
integration (xem mục 4.5).

### 3.2 Create the branches

Repo dùng model:

```
dev  (Fabric Git-sync đổ thẳng vào đây)
  │  Pull Request
  ▼
test (nhánh deploy — 3 workflow deploy chạy khi push vào đây)
  │  (khi sẵn sàng lên prod)
  ▼
main
```

Hiện repo có `dev`, `test`, `main`. Workflow deploy hiện tại chỉ trigger trên
`test` — thêm `main`/`prod` sau này thì sửa `branches:` trong các file workflow
(đã có comment nhắc sẵn trong `deploy-to-fabric.yml` và `validate-pr.yml`).

### 3.3 Protect the test branch

Tạo branch ruleset (hoặc branch protection rule) trên `test`, yêu cầu các
status check của `validate-pr.yml` (`Static repository checks + ruff lint`,
`Warehouse dacpac build`) phải pass mới cho merge PR.

📷 **[Figure 4 — GitHub branch ruleset, required status checks]**

### 3.4 Secrets and variables

**Repository secrets** (Settings → Secrets and variables → Actions → Secrets):

| Secret | Giá trị |
| --- | --- |
| `AZURE_CLIENT_ID` | Client ID của **Reader SP** |
| `AZURE_TENANT_ID` | Tenant ID |
| `AZURE_SUBSCRIPTION_ID` | Subscription chứa Key Vault |
| `AZURE_KEYVAULT_NAME` | Tên Key Vault |

**Repository/Environment variables** (tab Variables):

| Variable | Ý nghĩa |
| --- | --- |
| `test_WORKSPACE_NAME` | Tên workspace Fabric môi trường `test` |
| `test_WORKSPACE_ID` | ID workspace `test` |
| `GIT_DIRECTORY` | Thư mục chứa item Fabric trong repo (mặc định `fabric` nếu để trống) |

Prefix `test_` khớp với tên nhánh (`github.ref_name`) — workflow đọc biến theo
kiểu `vars['${{ github.ref_name }}_WORKSPACE_NAME']`. Thêm môi trường `prod`
sau này thì thêm biến `prod_WORKSPACE_NAME` / `prod_WORKSPACE_ID` tương tự.

📷 **[Figure 5 — GitHub Settings → Secrets and variables → Actions]**

### 3.5 Create the test environment

Tạo GitHub **Environment** tên `test` (Settings → Environments → New
environment). Tên phải khớp chính xác entity trong federated credential của
Reader SP (xem mục 7.5) — sai tên là login OIDC fail. Có thể thêm required
reviewer ở đây nếu muốn có bước approve thủ công trước khi deploy.

---

## 4. Fabric Setup

### 4.1 Create the workspaces

Tạo 2 workspace Fabric: `my-dev` (author, Git-connected) và workspace cho
`test` (workspace deploy đích, không cần Git integration).

### 4.2 Build the objects in my-dev

Trong `my-dev`, tạo các item Fabric (qua Fabric UI):

| Item | Loại |
| --- | --- |
| `insurance_WH` | Warehouse |
| `test_LH` | Lakehouse |
| `nb_transform` | Notebook (T-SQL) |
| `nb_lakehouse_schema` | Notebook (PySpark) |
| `pl_silver` | Data Pipeline |
| `sales_semantic_model` | Semantic Model |
| `report` | Report (Power BI) |

### 4.3 Create the Bronze and Gold schemas

Trong Warehouse `insurance_WH`, tạo 2 schema `Bronze` và `Gold` (repo còn 1
schema `silver` cũ, không còn dùng activelly). Cấu trúc thật hiện có trong
`.sqlproj`:

```
insurance_WH.Warehouse/
├── Bronze/
│   ├── Tables/          (customer, address, product, sales_order, ...)
│   └── StoredProcedures/ (usp_seed_demo_data, usp_populate_new_columns)
└── Gold/
    ├── Tables/          (dim_customer, dim_date, dim_product, fact_sales, ...)
    └── StoredProcedures/ (sp_delete_gold, usp_populate_new_columns)
```

Lưu ý T-SQL: `CREATE SCHEMA` / `CREATE VIEW` / `CREATE PROCEDURE` phải đứng
1 mình trong batch (có `GO` trước/sau) — `validate_repo.py` check việc này ở
CI, sai là fail PR trước khi kịp deploy.

### 4.4 Populate the notebook

Hai notebook có vai trò khác nhau:

- **`nb_lakehouse_schema`** — Spark SQL, tạo schema/table cho Lakehouse
  `test_LH` (Lakehouse không có schema-as-code như Warehouse):

  ```sql
  CREATE SCHEMA IF NOT EXISTS dbo;

  CREATE TABLE IF NOT EXISTS dbo.publicholidays (
      countryOrRegion STRING, holidayName STRING, ...
  ) USING DELTA
  ```

- **`nb_transform`** — T-SQL, transform dữ liệu từ `Bronze.*` sang
  `Gold.dim_customer` / `Gold.fact_sales` (`DELETE` + `INSERT`, chạy trong
  `pl_silver`).

Mọi cell phải viết `IF NOT EXISTS` — notebook này chạy lại ở **mọi** lần deploy
lakehouse, không chỉ lần đầu.

📷 **[Figure 6 — Notebook `nb_lakehouse_schema` trong Fabric UI]**

### 4.5 Connect my-dev to GitHub

Workspace Settings → Git integration → chọn GitHub → chọn repo, branch `dev`,
folder `fabric` (khớp `GIT_DIRECTORY`). Sau khi connect, mọi thay đổi Fabric
UI trong `my-dev` tự commit về nhánh `dev`. Từ đó tạo PR `dev → test` để bắt
đầu chạy CI/CD.

📷 **[Figure 7 — Fabric workspace Settings → Git integration, connected to `dev`]**

---

## 5. Deployment Architecture

### 5.1 Why three phases

Deploy được tách thành **3 pipeline độc lập**, mỗi cái sở hữu 1 nhóm item
riêng, không overlap — lý do là mỗi loại item cần công cụ và mô hình deploy
khác nhau:

| Pipeline | Item sở hữu | Công cụ |
| --- | --- | --- |
| `deploy-warehouse.yml` | Warehouse (`insurance_WH`) | SqlPackage / dacpac — state-based, tự tính `ALTER` |
| `deploy-lakehouse.yml` | Lakehouse (`test_LH`) + trigger `nb_lakehouse_schema` | fabric-cicd + Fabric REST API (`RunNotebook`) — imperative |
| `deploy-to-fabric.yml` | Notebook, DataPipeline, SemanticModel, Report | fabric-cicd (`publish_all_items`) |

Mỗi pipeline dùng `paths`/`paths-ignore` filter theo folder item, nên 1 push
chỉ trigger đúng pipeline liên quan — tránh publish Warehouse 2 lần (từng là
bug: warehouse trước đây được publish cả ở `deploy-to-fabric.yml` lẫn ở bước
riêng, giờ đã tách hẳn ra `deploy-warehouse.yml`).

### 5.2 What needs parameterisation

ID item (workspace id, item id, sql endpoint) khác nhau giữa các workspace
(`my-dev` vs `test`). Nếu hardcode ID của `my-dev` vào file định nghĩa item,
sau khi deploy sang `test` item đó vẫn trỏ ngược về `my-dev` — sai môi trường,
không báo lỗi gì cả (silent failure).

`cicd/parameter.yml` giải quyết việc này bằng token động
(`$workspace.id`, `$items.<Type>.<name>.id`, `$items.Warehouse.<name>.sqlendpoint`),
kết hợp 2 cơ chế:

- **`find_replace`** — regex thay chuỗi trong định nghĩa item (vd. connection
  string của semantic model trỏ vào warehouse).
- **`key_value_replace`** — thay theo JSONPath trong file JSON (vd.
  `notebookId` của 1 activity trong pipeline).

Mọi GUID của môi trường **dev** đều khai thẳng trong `find_replace` của
`cicd/parameter.yml` — id workspace dev, id `test_LH`, id `insurance_WH`. Các
rule này **cố tình không đặt `item_type`**: cùng một GUID xuất hiện ở nhiều
loại item khác nhau (header METADATA của notebook *và* URL DirectLake của
semantic model), nên đặt filter là cách chắc chắn nhất để bỏ sót một chỗ.

Lưu ý semantic model `sales_semantic_model` là **DirectLake-on-OneLake**:
connection của nó nằm ở `definition/expressions.tmdl` dưới dạng
`AzureStorage.DataLake("https://onelake.dfs.fabric.microsoft.com/<workspace id>/<item id>")`
— trỏ warehouse bằng **item id**, không phải SQL endpoint. Rule khớp theo
hostname `*.datawarehouse.fabric.microsoft.com` sẽ không match gì cả.

### 5.3 Phase-by-phase reference

| # | Pipeline | Trigger | Việc chính |
| --- | --- | --- | --- |
| 1 | `validate-pr.yml` | `pull_request` → `test` | Static check + build thử dacpac, **không** đụng Fabric |
| 2 | `deploy-warehouse.yml` | push `test`, path `fabric/*.Warehouse/**` | Publish item Warehouse → resolve SQL endpoint → build/publish dacpac → backfill data |
| 3 | `deploy-lakehouse.yml` | push `test`, path `fabric/*.Lakehouse/**` hoặc `nb_lakehouse_schema.Notebook/**` | Publish item Lakehouse → trigger notebook tạo schema |
| 4 | `deploy-to-fabric.yml` | push `test`, mọi path còn lại | Publish Notebook/DataPipeline/SemanticModel/Report |

📷 **[Figure 8 — GitHub Actions tab, 4 workflow chạy song song sau 1 lần push]**

---

## 6. Repository Structure

```
.
├── .github/
│   ├── workflows/
│   │   ├── validate-pr.yml       # check trên mọi PR vào test
│   │   ├── deploy-warehouse.yml  # publish Warehouse (dacpac)
│   │   ├── deploy-lakehouse.yml  # publish Lakehouse + tạo schema
│   │   └── deploy-to-fabric.yml  # publish item còn lại
│   └── dependabot.yml            # pip (cicd/) + github-actions (/), cho cả dev & test
├── cicd/
│   ├── deploy.py                 # publish item Fabric qua fabric-cicd
│   ├── grant_and_get_endpoints.py# lấy SQL endpoint + grant db_ddladmin
│   ├── run_sql.py                # chạy 1 stored procedure qua SQL endpoint
│   ├── trigger_job.py            # chạy 1 job Fabric (notebook/pipeline) qua REST API
│   ├── validate_repo.py          # static check dùng ở validate-pr.yml
│   ├── parameter.yml             # rule tham số hoá cho fabric-cicd
│   └── requirements.txt
├── docs/                         # tài liệu giải thích các flow (file này ở đây)
└── fabric/                       # source Fabric, Git-sync từ workspace dev
    ├── insurance_WH.Warehouse/
    ├── test_LH.Lakehouse/
    ├── nb_transform.Notebook/
    ├── nb_lakehouse_schema.Notebook/
    ├── pl_silver.DataPipeline/
    ├── sales_semantic_model.SemanticModel/
    └── report.Report/
```

📷 **[Figure 9 — Repo file tree trong VS Code]**

---

## 7. Key Vault Setup

Viết theo kiểu: hành động → screenshot → cách verify.

1. **Tạo Key Vault** — Azure Portal → Create a resource → Key Vault.
   📷 *[Figure 10 — Tạo Key Vault]*
2. **Lưu 3 secret cho Deploy SP**:

   | Tên secret | Giá trị |
   | --- | --- |
   | `deploy-sp-tenant-id` | Tenant ID |
   | `deploy-sp-client-id` | Client ID Deploy SP |
   | `deploy-sp-client-secret` | Client secret Deploy SP (mục 2, bước 3) |

   📷 *[Figure 11 — Key Vault → Secrets, đủ 3 secret]*
3. **Cấp quyền Reader SP đọc Key Vault** — Access control (IAM) → thêm role
   **Key Vault Secrets User** cho Reader SP (hoặc Access policy: Get + List).
   📷 *[Figure 12 — Key Vault → IAM role assignment]*
4. **Cấp quyền Deploy SP trên Fabric workspace `test`** — workspace → Manage
   access → thêm Deploy SP, role Admin hoặc Member.
   📷 *[Figure 13 — Fabric workspace Manage access]*
5. **Tạo Federated credential cho Reader SP** (App registration → Certificates
   & secrets → Federated credentials → Add credential):
   - Scenario: **GitHub Actions deploying Azure resources**
   - Organization/Repo: đúng tên repo
   - Entity type: **Environment**, giá trị = `test` (khớp mục 3.5)

   📷 *[Figure 14 — Federated credential configuration]*
6. **Verification checklist**:
   - `az keyvault secret list --vault-name <name>` thấy đủ 3 secret.
   - Job `Fetch Deploy SP credentials` trong workflow chạy không lỗi 403.
   - `azure/login` (Reader SP) pass mà không cần secret nào trong `with:`.

---

## 8. Deployment Scripts

### 8.1 `deploy.py`

Wrapper quanh `fabric_cicd.publish_all_items` (+ `unpublish_all_orphan_items`).
Nhận `--items-in-scope` (JSON array loại item) để mỗi pipeline chỉ publish
đúng phần của mình, và `--unpublish-orphans` để bật/tắt xoá item mồ côi trong
workspace (tắt hẳn ở `deploy-warehouse.yml` / `deploy-lakehouse.yml` vì đây là
deploy phạm vi hẹp).

```bash
python cicd/deploy.py \
  --target-env test \
  --workspace-name <test_WORKSPACE_NAME> \
  --git-directory fabric \
  --items-in-scope '["Warehouse"]' \
  --unpublish-orphans false
```

### 8.2 `grant_and_get_endpoints.py`

Chạy sau `deploy.py` scope Warehouse. Làm 2 việc: (1) gọi Fabric REST API lấy
connection string của warehouse, ghi vào `GITHUB_ENV` dưới tên
`<WAREHOUSE>_ENDPOINT`; (2) connect thẳng qua `pyodbc` để
`ALTER ROLE db_ddladmin ADD MEMBER [<display name Deploy SP>]` — bắt buộc phải
có quyền này thì SqlPackage mới publish schema được.

### 8.3 `parameter.yml`

Đã giải thích ở mục 5.2 — 2 khối `find_replace` (regex trên nội dung file) và
`key_value_replace` (JSONPath). File này được copy vào `fabric/parameter.yml`
ngay trước khi `deploy.py` chạy (fabric-cicd đọc `parameter.yml` cùng cấp với
`--git-directory`).

### 8.4 `deploy-to-fabric.yml`

Pipeline "còn lại bao nhiêu tôi lo" — publish Notebook/DataPipeline/
SemanticModel/Report. Trình tự: checkout → cài `requirements.txt` → resolve
`GIT_DIRECTORY` → copy `parameter.yml` → login OIDC (Reader SP) → lấy secret
Deploy SP từ Key Vault → `deploy.py` với scope
`["Notebook","DataPipeline","SemanticModel","Report"]`. Có `paths-ignore` loại
`fabric/*.Warehouse/**` và `fabric/*.Lakehouse/**` để không đè lên 2 pipeline
kia.

### 8.5 `validate-pr.yml`

Chạy trên mọi PR vào `test`, **không** đụng Fabric/Azure — an toàn chạy trên
branch chưa review. 2 job song song:

- `static_checks` — `validate_repo.py` (cấu trúc, `.platform`, batching T-SQL,
  coverage `parameter.yml`, kiểu connection của Report) rồi `ruff check cicd/`.
- `build_dacpac` — `dotnet build` file `.sqlproj`, upload artifact, fail nếu
  không build ra `.dacpac`.

Job `summary` gộp kết quả 2 job trên vào 1 bảng, fail cả run nếu có job fail —
đây là check mà branch ruleset trên `test` (mục 3.3) yêu cầu phải pass.

📷 **[Figure 15 — PR checks + summary table]**

---

## 9. Running the First Deployment

1. Làm xong mục 2 → 7 (Azure SP, Key Vault, GitHub secrets/vars/environment,
   Fabric workspace + Git integration).
2. Tạo PR từ `dev` vào `test` — quan sát `validate-pr.yml` chạy, sửa lỗi nếu
   `validate_repo.py` báo đỏ (thường là thiếu `.platform`, thiếu rule trong
   `parameter.yml`, hoặc T-SQL thiếu `GO`).
3. Merge PR → push vào `test` → 3 pipeline deploy tự trigger theo path filter
   (mục 5.3). Thứ tự khuyến nghị cho lần đầu: **Warehouse trước** (semantic
   model cần warehouse tồn tại để bind connection).

### 9.1 Verifying the result

- Tab Actions: cả 3-4 workflow chạy xanh.
- Job `Preview changes` của `deploy-warehouse.yml` — mở artifact
  `warehouse-audit-<run_id>` (`deploy-report.xml`), xác nhận không có lệnh
  `DROP` ngoài ý muốn trước khi tin job `Publish schema` phía sau.
- Query thử warehouse: `SELECT TOP 20 * FROM Gold.dim_customer` — có dữ liệu
  từ `usp_seed_demo_data` + backfill.
- Mở workspace `test` trong Fabric UI — đủ 7 item, semantic model bind đúng
  vào `insurance_WH` trong `test` (không phải `my-dev`).

📷 **[Figure 16 — Warehouse deploy run, full step list]**
📷 **[Figure 17 — Query kết quả trong Fabric warehouse `test`]**

### 9.2 Manual steps

Vài việc **chưa** tự động hoá, phải làm tay sau lần deploy đầu (đúng như
`deploy-to-fabric.yml` tự in ra trong Step Summary):

- Add thủ công Deploy SP vào **Workspace Access** của workspace `test` (mục 7,
  bước 4) — nếu quên, mọi bước sau đều fail 403.
- Load dữ liệu vào `Bronze` (repo hiện dùng `usp_seed_demo_data` để seed demo,
  không có pipeline ingest thật từ nguồn ngoài).
- Bind credential nguồn dữ liệu cho `sales_semantic_model` trong Fabric UI
  (lần đầu connect tới warehouse `test` cần auth thủ công 1 lần).
- Chạy `pl_silver` (thủ công hoặc `workflow_dispatch` với `run_job`) để đổ dữ
  liệu Bronze → Gold qua `nb_transform`.

---

## Screenshot checklist (gom trước khi viết bản chính thức)

1. Kiến trúc tổng quan (Figure 1)
2. App registration overview — Deploy SP (Figure 2)
3. Certificates & secrets — tạo client secret (Figure 3)
4. Branch ruleset required checks (Figure 4)
5. GitHub Secrets & variables (Figure 5)
6. Notebook `nb_lakehouse_schema` trong Fabric UI (Figure 6)
7. Fabric Git integration settings (Figure 7)
8. Actions tab — nhiều workflow chạy song song (Figure 8)
9. Repo file tree (Figure 9)
10. Tạo Key Vault (Figure 10)
11. Key Vault Secrets list (Figure 11)
12. Key Vault IAM role assignment (Figure 12)
13. Fabric workspace Manage access (Figure 13)
14. Federated credential configuration (Figure 14)
15. PR checks + summary table (Figure 15)
16. Warehouse deploy run — full step list (Figure 16)
17. Query kết quả trong Fabric (Figure 17)

