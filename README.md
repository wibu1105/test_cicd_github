Context Brief — Fabric CI/CD (for Claude Code)
Repo
wibu1105/test_cicd_github, branch dev. Monorepo, GitHub Actions, deploys to Microsoft Fabric. Domain: retail sales/insurance analytics (customer, product, sales_order, brand, geography). No healthcare/FHIR/OMOP — drop that framing entirely if you see it anywhere.
What's actually in the repo (ground truth, verified by reading the code)
Not a Lakehouse. Core data store is a Fabric Warehouse (fabric/insurance_WH.Warehouse), a .sqlproj deployed via SqlPackage/dacpac. T-SQL, not PySpark/Delta.
fabric/nb_transform.Notebook — a SQL notebook (not PySpark) that does DELETE + INSERT into Gold tables from Bronze. No transaction wrapper.
fabric/pl_silver.DataPipeline — misnomer; there is no Silver schema. It just triggers the Bronze→Gold notebook.
fabric/report.Report, fabric/sales_semantic_model.SemanticModel — Power BI artifacts synced via Git integration.
cicd/deploy.py — wraps fabric-cicd (publish_all_items / unpublish_all_orphan_items) to sync non-warehouse items.
cicd/grant_and_get_endpoints.py — resolves the warehouse SQL endpoint and grants db_ddladmin to the deploy SP.
cicd/validate_repo.py — pre-deploy repo/structure validation.
cicd/parameter.yml — fabric-cicd find/replace config; only rewrites IDs inside item definition files at publish time. It does not expose IDs to later pipeline steps.
.github/workflows/validate-pr.yml — existing PR-gate pipeline (not yet mentioned above). Runs on pull_request into test. Two parallel jobs: static_checks (runs cicd/validate_repo.py --target-env <base_ref> — structure + parameter.yml validation) and build_dacpac (compiles the .sqlproj, uploads the dacpac as an artifact). A summary job fails the run if either fails. No Python linter runs today — check_python_syntax in validate_repo.py only does an ast.parse compile check, not style/lint (no ruff).
Known real defects (not yet fixed — flag if touching this code, don't silently "fix" without asking)
nb_transform: DELETE+INSERT on Gold with no transaction — readers can see empty/partial data mid-run.
Dimension surrogate keys are ROW_NUMBER(), reassigned every full refresh — not stable across runs.
SCD2 columns (valid_from/valid_to/is_current) are hardcoded, not actually implemented.
ALTER ROLE db_ddladmin ADD MEMBER has no existence check — can error on repeat deploys.
unpublish_orphans defaults to true — wrong GIT_DIRECTORY can silently wipe the workspace.
Auth model (current reality, not "zero-secrets")
OIDC-federated Reader SP logs into Azure → reads a Deploy SP's client secret from Key Vault → that secret is used in the SqlPackage connection string (Authentication=Active Directory Service Principal). There is a standing long-lived secret in the flow, despite the "zero-secrets" framing in earlier docs. Don't claim it's secret-free.
Decisions already made (do not re-litigate / re-theme)
Only add features. Never modify or re-theme existing working code (deploy.py, grant_and_get_endpoints.py, validate_repo.py, parameter.yml, the warehouse SQL, the notebook) unless explicitly asked.
Do not scaffold a Lakehouse item. The user will create/commit it manually from the Fabric workspace via Git sync. The "all items" pipeline should pick it up automatically once it exists in the repo (fabric-cicd already supports "Lakehouse" in item_type_in_scope).
THREE separate deploy pipelines total — Warehouse and Lakehouse must be split from each other, not bundled:
.github/workflows/deploy-warehouse.yml — warehouse-only (already built). Best-practice guardrails: path-filtered trigger (fabric/**/*.Warehouse/**), DeployReport+Script artifact generated before publish for auditability, BlockOnPossibleDataLoss=true, DropObjectsNotInSource=false. Standalone (push/workflow_dispatch) and reusable (workflow_call).
.github/workflows/deploy-lakehouse.yml — NEW, not yet built. Lakehouse-only, mirrors the warehouse pipeline's separation pattern but for the Lakehouse item + its PySpark notebooks/pipelines once the user commits the Lakehouse from the workspace. Path-filtered on the Lakehouse item's folder(s). Deploys via fabric-cicd scoped to ["Lakehouse","Notebook","DataPipeline"] (only the ones tied to the Lakehouse — do not re-deploy warehouse-related notebooks here). Standalone and reusable (workflow_call), same shape as the warehouse pipeline.
.github/workflows/deploy-all.yml — orchestrator (already built, needs updating). Validates → deploys remaining non-warehouse/non-lakehouse items (Report, SemanticModel, etc.) via fabric-cicd → calls both deploy-warehouse.yml and deploy-lakehouse.yml via uses: (single source of truth for each, no duplicated logic in the orchestrator).
Old deploy-to-fabric.yml must be retired/deleted so a single push doesn't double-trigger deploys.
Warehouse data population — mechanism CHANGED. Do not use the REST-API job-trigger approach (cicd/trigger_job.py) for the warehouse. Instead: after SqlPackage /Action:Publish applies the ALTER TABLE/schema change, the CI/CD step connects to the warehouse SQL endpoint (same connection string already used for publish) and executes a T-SQL stored procedure (e.g. EXEC dbo.usp_PopulateNewColumns or similar, to be defined per schema change) that backfills the newly added columns/tables. This runs as a plain SQL call (sqlcmd or pyodbc/pymssql) in the same workflow step sequence, right after publish — not via the Fabric Job Scheduler REST API. The stored procedure itself should live in the .sqlproj (versioned, deployed by the same dacpac) so it's always in sync with the schema it populates.
cicd/trigger_job.py (REST-API job-trigger, already written) is kept but scoped to the Lakehouse/pipeline side only — e.g. triggering a Fabric Data Pipeline or PySpark notebook job after Lakehouse deploy (jobType=Pipeline for Data Pipelines, jobType=RunNotebook for Notebooks — confirmed via community sources, DefaultJob fails). This belongs in deploy-lakehouse.yml, not deploy-warehouse.yml.
Outstanding TODOs for this pass
Build .github/workflows/deploy-lakehouse.yml (new pipeline, mirrors warehouse pipeline's structure/guardrails but for Lakehouse items).
Update deploy-warehouse.yml: replace/augment the post-publish population step — drop the REST-API job trigger call, add a SQL step that executes a stored procedure against the warehouse endpoint right after SqlPackage /Action:Publish.
Add the stored procedure itself to the .sqlproj (versioned alongside the schema it populates) — ask the user for the exact backfill logic per table/column before inventing it.
Update deploy-all.yml: call both deploy-warehouse.yml and deploy-lakehouse.yml as separate reusable-workflow jobs.
Keep cicd/trigger_job.py but re-scope its usage to the Lakehouse pipeline only.
Add a Python linting (ruff) step to .github/workflows/validate-pr.yml, as a third check alongside the existing Repo structure checks and parameter.yml validation (both currently produced by cicd/validate_repo.py). Run ruff check cicd/ (and any Lakehouse PySpark notebook .py exports, once those exist) as its own job or step, surfaced in the PR summary table the same way the other two checks are.
Add .github/dependabot.yml — two updates entries: package-ecosystem: pip scoped to directory: /cicd (covers fabric-cicd, azure-identity, requests, etc.), and package-ecosystem: github-actions scoped to directory: / (covers all action pins across the 4 workflows). Weekly schedule. Note: the config the user pasted was missing the required top-level version: 2 and per-entry directory fields — schema needs those or Dependabot rejects the file.
Style/interaction preferences for this project
Be explicit about what's real vs. aspirational in any architecture description — don't accept marketing-style framing ("zero-secrets", "zero-touch") at face value without checking the code.
Prefer additive changes; ask before refactoring existing working pipeline code.
When citing Fabric REST API behavior, verify against current docs/community reports — the jobType parameter in particular is poorly documented and has known gotchas (DefaultJob fails; correct values are undocumented in the main spec page).
 # test_cicd_github

CI/CD cho workspace Microsoft Fabric (hiện có Warehouse + các item Power BI; sẽ có
thêm Lakehouse khi nào được commit từ workspace). Deploy qua GitHub Actions, dùng
[fabric-cicd](https://microsoft.github.io/fabric-cicd/) và SqlPackage/dacpac.

## Cấu trúc repo

```text
fabric/                          Các item Fabric, đồng bộ qua Git integration
  insurance_WH.Warehouse/        .sqlproj — schema Bronze + Gold (T-SQL)
  nb_transform.Notebook/         Notebook SQL: DELETE + INSERT Bronze -> Gold
  pl_silver.DataPipeline/        Trigger nb_transform
  report.Report/                 Report Power BI
  sales_semantic_model.SemanticModel/

cicd/
  deploy.py                      fabric-cicd publish/unpublish, chọn item type tùy ý
  deploy_lakehouse.py            [MỚI, hiện KHÔNG dùng] — xem ghi chú bên dưới
  grant_and_get_endpoints.py     Lấy SQL endpoint của warehouse, cấp quyền db_ddladmin
  run_sql.py                     [MỚI] Chạy stored procedure lên endpoint warehouse
  trigger_job.py                 [MỚI] Gọi Fabric REST API để trigger job (pipeline/notebook)
  validate_repo.py               Check cấu trúc/parameter trước khi deploy (không gọi Fabric)
  parameter.yml                  Rule find/replace của fabric-cicd
  requirements.txt

.github/workflows/
  validate-pr.yml                [ĐÃ SỬA] Gate cho PR — thêm bước lint ruff
  deploy-warehouse.yml           [MỚI] Deploy riêng Warehouse
  deploy-lakehouse.yml           [MỚI] Deploy riêng Lakehouse
  deploy-to-fabric.yml           [ĐÃ SỬA] Deploy Notebook/DataPipeline/SemanticModel/Report

.github/dependabot.yml           [MỚI] Update hàng tuần: cicd/ (pip), workflows (actions)
```

## Đã thay đổi/thêm gì trong đợt này

- **Thêm `deploy-warehouse.yml`**: pipeline deploy riêng cho Warehouse, chỉ chạy khi
  file trong `fabric/**/*.Warehouse/**` thay đổi.
- **Thêm `deploy-lakehouse.yml`**: pipeline deploy riêng cho Lakehouse, chỉ chạy khi
  file trong `fabric/**/*.Lakehouse/**` thay đổi. Chưa có Lakehouse trong repo thì
  workflow này no-op (log notice rồi pass).
- **Thêm `cicd/deploy_lakehouse.py`** — nhưng **hiện không còn được dùng**. Ban đầu
  script này gom item `*.Lakehouse` cùng các notebook/pipeline tham chiếu tới nó
  vào thư mục tạm rồi publish. Sau khi chốt lại "mọi item không phải Lakehouse /
  Warehouse đều do `deploy-to-fabric.yml` deploy", `deploy-lakehouse.yml` chuyển
  sang gọi thẳng `deploy.py --items-in-scope '["Lakehouse"]'`, nên file này thành
  thừa. Giữ lại chứ chưa xoá.
- **Thêm `cicd/run_sql.py`**: sau khi `sqlpackage /Action:Publish` xong, script này
  connect vào endpoint warehouse (cùng connection string) và `EXEC` một stored
  procedure để backfill cột/bảng mới thêm. Chạy SQL trực tiếp, không qua REST API
  Job Scheduler nữa.
- **Thêm `cicd/trigger_job.py`**: gọi Fabric REST API để trigger job (Data
  Pipeline / Notebook), chỉ dùng ở phía Lakehouse (`jobType=Pipeline` cho
  DataPipeline, `jobType=RunNotebook` cho Notebook — `DefaultJob` không dùng được).
- **Thêm `.github/dependabot.yml`**: 2 entry — `pip` ở `/cicd`, `github-actions` ở
  `/`, lịch chạy hàng tuần.
- **Sửa `validate-pr.yml`**: thêm bước `ruff check cicd/` ngay trong job
  `static_checks` (cùng chỗ với `validate_repo.py`), không tách job riêng.
- **Không đụng** vào `deploy.py`, `grant_and_get_endpoints.py`, `validate_repo.py`,
  `parameter.yml`, `deploy-to-fabric.yml`, hay bất kỳ file SQL/notebook nào theo
  đúng yêu cầu — chỉ thêm tính năng mới.
- **Chưa viết** stored procedure `Gold.usp_populate_new_columns` — theo yêu cầu để
  sau. Bước gọi nó trong `deploy-warehouse.yml` dùng `--skip-if-missing` nên hiện
  tại chỉ log notice rồi pass, không fail pipeline.

## Chi tiết từng workflow

### `validate-pr.yml` — gate cho PR

Chạy trên mọi pull request vào `test`. Không gọi Fabric, không dùng secret. 2 job,
đều bắt buộc pass mới merge được:

- **static_checks** — 2 bước chạy nối tiếp trong cùng job:
  - `cicd/validate_repo.py`: cấu trúc repo, file `.platform`, batch T-SQL, độ phủ
    `parameter.yml`, tính portable của notebook, kiểu connection của Report.
  - `ruff check cicd/`: lint Python, bắt các lỗi style/dead code mà check
    `ast.parse` trong `validate_repo.py` không thấy.
- **build_dacpac** — build thử `.sqlproj`, upload dacpac làm artifact.

Nên gắn với branch ruleset trên `test` yêu cầu các check này pass.

### `deploy-warehouse.yml` — chỉ deploy Warehouse

Trigger: push vào `test` **khi có thay đổi trong `fabric/**/*.Warehouse/**`**, hoặc
chạy tay qua `workflow_dispatch`.

1. Login Azure (OIDC, Reader SP) → lấy secret của Deploy SP từ Key Vault.
2. `deploy.py --items-in-scope '["Warehouse"]' --unpublish-orphans false` — publish
   item Warehouse. Luôn tắt unpublish orphan ở đây, vì đây là deploy có phạm vi hẹp,
   không được phép xóa bất cứ thứ gì.
3. `grant_and_get_endpoints.py` — lấy SQL endpoint, cấp quyền `db_ddladmin`.
4. Build dacpac.
5. `sqlpackage /Action:DeployReport` và `/Action:Script` — ghi ra artifact **trước
   khi** publish, để lúc nào cũng có bằng chứng những gì sắp bị thay đổi.
6. `sqlpackage /Action:Publish` với `BlockOnPossibleDataLoss=true` và
   `DropObjectsNotInSource=false`.
7. `run_sql.py --procedure Gold.usp_populate_new_columns --skip-if-missing` — chạy
   stored procedure backfill trên chính endpoint vừa publish. Procedure này nên
   nằm trong `.sqlproj` để luôn đồng bộ với schema mà nó backfill. **Chưa viết** —
   bước này hiện log notice rồi pass nhờ `--skip-if-missing`.

Phía warehouse không dùng REST API Job Scheduler — backfill gọi SQL trực tiếp nên
lỗi (nếu có) hiện đúng ngay ở bước gây ra nó.

### `deploy-lakehouse.yml` — chỉ deploy Lakehouse

Trigger: push vào `test` **khi có thay đổi trong `fabric/**/*.Lakehouse/**`**, hoặc
chạy tay.

Chạy `deploy.py --items-in-scope '["Lakehouse"]' --unpublish-orphans false` — **chỉ
deploy đúng item `Lakehouse`**. Notebook/DataPipeline/SemanticModel/Report (kể cả
notebook PySpark gắn với Lakehouse) luôn do `deploy-to-fabric.yml` deploy. Tắt
unpublish orphan vì đây là deploy phạm vi hẹp, không được phép xoá gì.

`workflow_dispatch` nhận input `run_job: Name:Type` (vd `pl_ingest:DataPipeline`)
để chạy pipeline/notebook qua `trigger_job.py` ngay sau khi deploy.

### `deploy-to-fabric.yml` — các item còn lại

Trigger: push vào `test`, **bỏ qua** `fabric/**/*.Warehouse/**` và
`fabric/**/*.Lakehouse/**` (`paths-ignore`). Deploy scope
`["Notebook","DataPipeline","SemanticModel","Report"]`.

Trước đây workflow này chạy trên mọi push và deploy chung cả `Warehouse` + publish
dacpac, nên push đổi file warehouse sẽ kích cả nó lẫn `deploy-warehouse.yml` →
publish 2 lần vào cùng 1 endpoint. Đã sửa: thêm `paths-ignore`, bỏ `Warehouse`
khỏi scope, và gỡ các bước chỉ dành cho warehouse (resolve endpoint, build/publish
dacpac, cài .NET/ODBC/SqlPackage).

## Ai deploy cái gì (không chồng lấn)

| Workflow | Trigger (path) | Deploy |
| --- | --- | --- |
| `deploy-warehouse.yml` | `fabric/**/*.Warehouse/**` | Item `Warehouse` + schema dacpac + backfill |
| `deploy-lakehouse.yml` | `fabric/**/*.Lakehouse/**` | Chỉ item `Lakehouse` |
| `deploy-to-fabric.yml` | mọi path khác | `Notebook`, `DataPipeline`, `SemanticModel`, `Report` |

Mỗi push chỉ kích đúng pipeline tương ứng với file bị đổi, không chồng lấn.
Quy tắc: **toàn bộ item không phải `Lakehouse` hay `Warehouse` đều luôn được deploy
bởi `deploy-to-fabric.yml`** — kể cả notebook PySpark gắn với Lakehouse (chúng nằm
ở `fabric/*.Notebook/`, không nằm trong folder `*.Lakehouse/`).

## Mô hình auth (thực tế hiện tại)

Reader SP đăng nhập Azure qua OIDC → đọc client secret của Deploy SP từ Key Vault →
secret đó được dùng trong connection string của SqlPackage
(`Authentication=Active Directory Service Principal`). Vẫn có 1 secret tồn tại lâu
dài trong luồng này — không phải "zero secrets" như một số tài liệu cũ mô tả.

## Cấu hình cần có trên repo

**Secrets** (repo hoặc environment): `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`,
`AZURE_SUBSCRIPTION_ID`, `AZURE_KEYVAULT_NAME`.

**Secret trong Key Vault**: `deploy-sp-tenant-id`, `deploy-sp-client-id`,
`deploy-sp-client-secret`.

**Variables** (theo từng environment, vd `test`): `<ENV>_WORKSPACE_NAME`,
`<ENV>_WORKSPACE_ID`, có thể thêm `GIT_DIRECTORY` (mặc định `fabric`).

## Lỗi đã biết (chưa sửa, cẩn thận khi đụng vào)

- `nb_transform`: `DELETE` + `INSERT` vào Gold không có transaction — người đọc có
  thể thấy dữ liệu rỗng/thiếu giữa lúc đang chạy.
- Surrogate key của dimension dùng `ROW_NUMBER()`, bị gán lại mỗi lần refresh toàn
  bộ — không ổn định qua các lần chạy.
- Các cột SCD2 (`valid_from`/`valid_to`/`is_current`) đang hardcode, chưa thực sự
  implement.
- `ALTER ROLE db_ddladmin ADD MEMBER` không check tồn tại trước — có thể lỗi khi
  deploy lại lần 2.
- `deploy-to-fabric.yml` (pipeline cũ) mặc định `unpublish_orphans=true` — sai
  `GIT_DIRECTORY` có thể xóa sạch workspace.
