# Fabric CI/CD — Word Guide Outline

Table of contents to follow when writing `Fabric_CICD_Github_Guide.docx`.
Each entry says what to write and where a screenshot belongs.

---

## 1. Overview

- 1.1 Purpose — what this CI/CD does, who it is for
- 1.2 Scope — Fabric Warehouse + Lakehouse + Power BI items, deployed from GitHub
- 1.3 Architecture diagram
  - 📷 *Screenshot: GitHub repo → Actions → Fabric workspace flow*
- 1.4 Branch strategy — `dev` (Fabric Git sync) → PR → `test` (deploy target) → `main`

## 2. Repository Structure

- 2.1 Folder layout — `fabric/`, `cicd/`, `.github/workflows/`
- 2.2 Fabric items in the repo
  | Item | Type | Deployed by |
  |---|---|---|
  | `insurance_WH` | Warehouse (.sqlproj) | `deploy-warehouse.yml` |
  | `test_LH` | Lakehouse | `deploy-lakehouse.yml` |
  | `nb_transform` | Notebook (SQL) | `deploy-to-fabric.yml` |
  | `pl_silver` | DataPipeline | `deploy-to-fabric.yml` |
  | `sales_semantic_model` | SemanticModel | `deploy-to-fabric.yml` |
  | `report` | Report | `deploy-to-fabric.yml` |
- 2.3 CI/CD scripts in `cicd/` — one line each on what the script does
  - 📷 *Screenshot: repo file tree in VS Code*

## 3. Prerequisites

- 3.1 Azure resources — Entra tenant, Key Vault, 2 service principals
- 3.2 Fabric — workspace, capacity/trial, Git integration connected to `dev`
- 3.3 Fabric tenant setting: **Service principals can use Fabric APIs** must be ON
  - 📷 *Screenshot: Fabric Admin portal → Tenant settings*
- 3.4 GitHub — repo, Environments (`test`), branch ruleset on `test`

## 4. Authentication Model ⭐

> Explain honestly: this is **not** secret-free. A long-lived Deploy SP secret
> exists in Key Vault and is used in the SqlPackage connection string.

- 4.1 Why two service principals
  - **Reader SP** — logs into Azure via OIDC (no stored secret), only reads Key Vault
  - **Deploy SP** — has the actual Fabric/Warehouse permissions; its secret lives in Key Vault
- 4.2 Flow diagram: GitHub OIDC → Reader SP → Key Vault → Deploy SP secret → Fabric + SqlPackage
  - 📷 *Screenshot: sequence/flow diagram*
- 4.3 Why the secret is overwritten into `AZURE_*` env vars mid-workflow, and why that is safe
  (`azure/login` takes credentials from `with:`, not from env — it has already finished)

## 5. Key Vault Setup — Step by Step ⭐

Write each step as: action → screenshot → verification.

- 5.1 Create the Key Vault
  - 📷 *Screenshot: Azure Portal → Create Key Vault*
- 5.2 Create the **Deploy SP** (App registration)
  - Register app → copy Application (client) ID + Directory (tenant) ID
  - 📷 *Screenshot: App registration Overview page*
- 5.3 Create a client secret for the Deploy SP
  - Certificates & secrets → New client secret → copy **Value** immediately
  - Note the expiry date — this secret must be rotated
  - 📷 *Screenshot: Certificates & secrets page*
- 5.4 Store the three secrets in Key Vault
  | Secret name | Value |
  |---|---|
  | `deploy-sp-tenant-id` | Directory (tenant) ID |
  | `deploy-sp-client-id` | Application (client) ID |
  | `deploy-sp-client-secret` | the secret Value from 5.3 |
  - 📷 *Screenshot: Key Vault → Secrets list showing all 3*
- 5.5 Create the **Reader SP** and its federated credential (OIDC)
  - App registration → Certificates & secrets → Federated credentials → Add
  - Scenario: GitHub Actions deploying Azure resources
  - Entity type: **Environment** = `test` (must match `environment:` in the workflow)
  - 📷 *Screenshot: Federated credential configuration*
- 5.6 Grant the Reader SP access to Key Vault
  - RBAC: **Key Vault Secrets User** role, or Access policy: **Get** + **List** on secrets
  - 📷 *Screenshot: Key Vault → Access control (IAM) role assignment*
- 5.7 Grant the Deploy SP access to the Fabric workspace
  - Fabric workspace → Manage access → add Deploy SP as **Admin** (or Member)
  - 📷 *Screenshot: Fabric workspace Manage access*
- 5.8 Verification checklist — how to confirm each step worked before running the pipeline

## 6. GitHub Configuration

- 6.1 Repository secrets
  | Secret | Purpose |
  |---|---|
  | `AZURE_CLIENT_ID` | Reader SP client ID |
  | `AZURE_TENANT_ID` | Tenant ID |
  | `AZURE_SUBSCRIPTION_ID` | Subscription holding the Key Vault |
  | `AZURE_KEYVAULT_NAME` | Key Vault name |
  - 📷 *Screenshot: GitHub Settings → Secrets and variables → Actions*
- 6.2 Repository variables — `test_WORKSPACE_NAME`, `test_WORKSPACE_ID`, `GIT_DIRECTORY`
- 6.3 Environments — create `test`, add reviewers if approval is wanted
- 6.4 Branch ruleset on `test` — require the PR validation checks to pass
  - 📷 *Screenshot: branch ruleset required status checks*

## 7. Pipeline 1 — Pull Request Validation (`validate-pr.yml`)

- 7.1 Trigger — `pull_request` into `test`
- 7.2 Job `static_checks` — `validate_repo.py` (structure, `.platform`, T-SQL batching,
      `parameter.yml` coverage, Report connection type) then `ruff check cicd/`
- 7.3 Job `build_dacpac` — compiles the `.sqlproj`, uploads dacpac artifact
- 7.4 Job `summary` — result table, fails the run if any check failed
  - 📷 *Screenshot: PR checks + job summary table*

## 8. Pipeline 2 — Deploy Warehouse (`deploy-warehouse.yml`) ⭐

- 8.1 Trigger — push to `test` on path `fabric/**/*.Warehouse/**`, or manual
- 8.2 Step sequence (write one short paragraph per step)
  1. Install tooling — Python, .NET 8, ODBC Driver 18, SqlPackage
  2. Azure login (Reader SP) → fetch Deploy SP credentials from Key Vault
  3. Deploy the Warehouse **item** — `deploy.py` scoped to `["Warehouse"]`, orphan unpublish **off**
  4. Resolve SQL endpoint + grant `db_ddladmin` — `grant_and_get_endpoints.py`
  5. Build dacpac
  6. **Preview changes** — `DeployReport` + `Script` written to the `audit/` artifact *before* anything is applied
  7. **Publish schema** — `BlockOnPossibleDataLoss=true`, `DropObjectsNotInSource=false`
  8. **Populate new columns** — `run_sql.py` executes the backfill stored procedure
- 8.3 Safety guardrails — explain each of the three: audit artifact, block on data loss, never drop
- 8.4 The populate-after-ALTER pattern (see `docs/case-populate-after-alter.md`)
  - Why the procedure lives in the `.sqlproj` — deployed by the same dacpac, cannot drift
  - Why it must be idempotent — it runs on **every** deploy, not just the one that added the column
  - Worked example: `Gold.dim_customer.email_domain`
  - 📷 *Screenshot: workflow run showing "Populate new columns" step log*
  - 📷 *Screenshot: query result in Fabric showing the backfilled column*

## 9. Pipeline 3 — Deploy Lakehouse (`deploy-lakehouse.yml`)

- 9.1 Trigger — push to `test` on path `fabric/**/*.Lakehouse/**`, or manual
- 9.2 Deploys **only** the Lakehouse item (`deploy.py` scoped to `["Lakehouse"]`)
- 9.3 Applying schema — `trigger_job.py` runs the `nb_lakehouse_schema` notebook
- 9.4 **How this differs from the Warehouse dacpac** ⭐ (important comparison)
  | | Warehouse | Lakehouse |
  |---|---|---|
  | Model | State-based — declare the table, SqlPackage generates the `ALTER` | Imperative — you write the DDL yourself |
  | Tool | SqlPackage / dacpac | Spark SQL notebook |
  | Idempotency | Handled by SqlPackage | You must write `IF NOT EXISTS` |
  | Preview before apply | Yes (`DeployReport`) | No |
- 9.5 The `nb_lakehouse_schema` notebook — create it in Fabric UI, attach to `test_LH`
  - 📷 *Screenshot: notebook cells with `CREATE SCHEMA` / `CREATE TABLE IF NOT EXISTS`*
- 9.6 Optional post-deploy job — `run_job` input, `Name:Type` format

## 10. Pipeline 4 — Deploy Remaining Items (`deploy-to-fabric.yml`)

- 10.1 Trigger — push to `test`, with `paths-ignore` for Warehouse and Lakehouse
- 10.2 Scope — `Notebook`, `DataPipeline`, `SemanticModel`, `Report`
- 10.3 Why `paths-ignore` matters — without it, one push would publish the warehouse twice
- 10.4 Ownership table — who deploys what, no overlap
  - 📷 *Screenshot: Actions tab showing only the relevant workflow ran*

## 11. Parameterisation (`cicd/parameter.yml`)

- 11.1 Why it exists — item IDs differ per workspace; hardcoded IDs point at the wrong environment
- 11.2 `find_replace` — regex on item definition files (semantic model → warehouse connection)
- 11.3 `key_value_replace` — JSONPath on pipeline activities (`notebookId`, `workspaceId`)
- 11.4 Scaling to many pipelines/activities — use `item_name` to pin an entry to one pipeline;
      entries needed = number of distinct (pipeline, activity, target item) combinations
- 11.5 Dynamic tokens — `$workspace.id`, `$items.<Type>.<name>.id`, `$items.Warehouse.<name>.sqlendpoint`

## 12. Dependency Management (`.github/dependabot.yml`)

- 12.1 Two ecosystems — `pip` on `/cicd`, `github-actions` on `/`
- 12.2 `target-branch` for both `dev` and `test` — 4 entries total
  - 📷 *Screenshot: Dependabot PR*

## 13. Running & Troubleshooting

- 13.1 First-time run order (bootstrap) — Warehouse must exist before the semantic model binds
- 13.2 Reading the audit artifact before approving a schema change
- 13.3 Common errors table
  | Symptom | Cause | Fix |
  |---|---|---|
  | `INSURANCE_WH_ENDPOINT is empty` | Warehouse item not deployed yet / wrong workspace ID | check `<ENV>_WORKSPACE_ID` |
  | SqlPackage blocked on data loss | change would drop/truncate a column | intentional? script it manually |
  | `does not exist ... Skipped` | backfill procedure not in the `.sqlproj` yet | add it, or leave skipped |
  | Dependabot config rejected | missing `version: 2` or `directory` | fix schema |
  - 📷 *Screenshot: a failed run and where to read the error*

## 14. Known Limitations ⭐

Be explicit — these are real and currently unfixed:

- `nb_transform` does `DELETE` + `INSERT` on Gold with **no transaction** — readers can see partial data mid-run
- Dimension surrogate keys use `ROW_NUMBER()` — reassigned on every full refresh, not stable
- SCD2 columns (`effective_from` / `effective_to` / `is_current`) are hardcoded, not implemented
- `ALTER ROLE db_ddladmin ADD MEMBER` has no existence check — can error on repeat deploys
- `deploy-to-fabric.yml` defaults `unpublish_orphans=true` — a wrong `GIT_DIRECTORY` can wipe the workspace
- The Deploy SP secret is long-lived and must be rotated manually
- `cicd/deploy_lakehouse.py` is currently unused (superseded by `deploy.py` with `["Lakehouse"]` scope)

## 15. Appendix

- 15.1 Full workflow YAML listings
- 15.2 Script reference — arguments for `run_sql.py`, `trigger_job.py`, `deploy.py`
- 15.3 Glossary — dacpac, SqlPackage, OIDC, federated credential, orphan unpublish, `jobType`
- 15.4 Useful links — fabric-cicd docs, Fabric REST API, SqlPackage properties

---

## Screenshot checklist

Collect these before writing:

1. Repo file tree
2. Architecture / flow diagram
3. Fabric tenant setting — SP API access
4. Azure: Key Vault creation
5. Azure: App registration overview (Deploy SP)
6. Azure: client secret creation
7. Azure: Key Vault secrets list (3 secrets)
8. Azure: federated credential (Reader SP)
9. Azure: Key Vault IAM role assignment
10. Fabric: workspace Manage access
11. GitHub: Actions secrets and variables
12. GitHub: branch ruleset required checks
13. GitHub: PR checks + validation summary table
14. GitHub: warehouse deploy run — full step list
15. GitHub: "Populate new columns" step log
16. Fabric: query showing backfilled column
17. Fabric: `nb_lakehouse_schema` notebook cells
18. GitHub: Actions tab showing path-filtered trigger
19. GitHub: Dependabot PR
20. GitHub: a failed run with the error highlighted

## Writing conventions

- Screenshots: numbered caption, e.g. *Figure 5 — Key Vault secrets*
- Code: monospace, with the file path as a caption above the block
- Warnings: use a callout box for anything that can destroy data
  (orphan unpublish, `DropObjectsNotInSource`, data-loss block)
- Keep every claim checkable against the repo — no "zero-touch" / "zero-secrets" marketing
