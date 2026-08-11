# Fabric CI/CD

GitHub Actions pipeline for deploying Microsoft Fabric items and a Fabric
Warehouse schema. If this document and the code disagree, the code wins.

## Branches

```
dev  ──PR──►  test  ──PR──►  prod
```

| Branch | Role | Deploys? |
|---|---|---|
| `dev` | where work happens | no — pushing here triggers nothing |
| `test` | test environment | yes, automatically on merge |
| `prod` | default branch, production record | **no** — production goes out by dispatch only |

`prod` deliberately has no push trigger. A push carries no inputs, so it has no
way to say *which release* is going out; production is deployed by picking a tag
in Run workflow instead.

That leaves `prod` with two jobs: it is the branch the dispatch form reads its
input definitions from, and it records what has been released. Merge into it
when the workflow files themselves change — not once per release.

## Workflows

### `validate-pr.yml`

Runs on every pull request into `test` or `prod`. Touches nothing outside the
runner: no Fabric API calls, no secrets, so it is safe on unreviewed branches.

- repository structure, every item folder has a `.platform`
- Python syntax (`ast.parse`) and `ruff` lint over `cicd/`
- workflow YAML parses
- T-SQL batch rules — `CREATE SCHEMA` must be alone in its batch
- **parameterisation coverage** — a hardcoded warehouse endpoint or OneLake
  GUID with no matching `find_replace` rule fails the build
- notebook portability — a notebook pinned to the workspace it was authored in
- every `find_replace` rule matches at least one file

The last three catch the failure mode that matters: an item that deploys green
and then reads from the wrong workspace.

### `deploy-to-fabric.yml`

Publishes **every Fabric item**, then applies the lakehouse schema.

Triggers: push to `test` (except warehouse-only changes), or Run workflow.

```
validate  →  resolve workspace  →  Azure login + Key Vault
          →  stage parameter.yml
          →  publish items
          →  run nb_lakehouse_schema
```

Warehouse and Lakehouse are in `--items-in-scope`, but only their **item shell**
is published here — no schema. They are in scope because `fabric-cicd` resolves
`$items.<Type>.<name>.$id` only for types in scope for that run, and
`parameter.yml` needs both ids.

### `deploy-warehouse.yml`

The warehouse **schema** only: dacpac build, SqlPackage publish, backfill procs.
Separate because it is the one pipeline needing .NET, SqlPackage and
msodbcsql18.

Triggers: push to `test` touching `fabric/*.Warehouse/**`, or Run workflow.

```
validate  →  resolve SQL endpoint  →  build dacpac
          →  preview (report + script, uploaded as an artifact)
          →  publish schema
          →  run backfill procs
```

It does **not** create the Warehouse item — `deploy-to-fabric.yml` owns every
item shell. That split is what stops the two workflows from writing the same
item at once on a commit that touches both.

Consequence: a brand-new warehouse needs one `deploy-to-fabric.yml` run first.
Until then this workflow fails at the endpoint lookup and lists the warehouses
that do exist.

## Deploying

### To `test`

Merge a pull request into `test`. Path filters decide which workflow runs:

| Commit touches | Deploy to Fabric | Deploy warehouse |
|---|---|---|
| only `fabric/*.Warehouse/**` | — | ✅ |
| only notebooks / pipelines / lakehouse | ✅ | — |
| both | ✅ | ✅ |
| only `cicd/**` or `.github/**` | ✅ | — |

### To `prod`

1. Tag the commit you verified on `test`:
   ```bash
   git tag -a releases/1.3.0 -m "releases/1.3.0"
   git push origin releases/1.3.0
   ```
2. **Actions** → **Deploy to Fabric** → **Run workflow**
3. **Use workflow from** → **Tags** tab → pick the tag
4. **Choose target workspace** → `prod`
5. Approve when the `prod` environment gate pauses the run

Path filters do **not** apply to a dispatch — it runs in full regardless of what
the tag changed. So you decide which workflow to run:

| Tag contains | Run |
|---|---|
| notebook / pipeline / model changes | Deploy to Fabric |
| warehouse `.sql` changes | Deploy warehouse |
| both | both, **Deploy to Fabric first** |

Unsure? Run both. Each is idempotent.

> **A dispatch runs the workflow file as it exists in the selected ref**, not the
> latest one. The *form* comes from the default branch, the *execution* comes
> from the tag. A tag older than an input will show that input on the form and
> then run a workflow that does not understand it.

## Adding a column, and backfilling it

1. Add the column to the table's `.sql` file. Never write `ALTER` — SqlPackage
   diffs the dacpac against the live warehouse and generates it.
2. Add the backfill to `Bronze/StoredProcedures/usp_populate_new_columns.sql`
   (or the Gold one):
   ```sql
   UPDATE Bronze.customer
   SET new_column = 'unknown'
   WHERE new_column IS NULL;
   ```
3. Commit both in the **same commit**.

Three rules:

- **Idempotent.** These procs run on *every* warehouse deploy, not just the one
  that adds the column. Always guard with `WHERE new_column IS NULL`, or a later
  deploy will overwrite real data.
- **Same dacpac.** The column and the proc ship together, so the proc can never
  reference a column that does not exist yet.
- **`SELECT` at the end.** `run_sql.py` echoes every result set, so the run log
  shows how many rows were actually backfilled rather than just "it ran".

Procs run in the order listed in `POPULATE_PROCS`: Bronze before Gold, because
Gold reads from Bronze.

`BlockOnPossibleDataLoss=true` is set, so adding a column is fine but dropping
one or narrowing a type fails the deploy. Changing a type takes several
releases: add the new column, backfill, repoint readers, then drop the old one.

## Configuration

### Repository / environment variables

| Name | Example |
|---|---|
| `TEST_WORKSPACE_ID` | GUID of the test workspace |
| `TEST_WORKSPACE_NAME` | display name |
| `PROD_WORKSPACE_ID` | GUID of the prod workspace |
| `PROD_WORKSPACE_NAME` | display name |
| `GIT_DIRECTORY` | optional, defaults to `fabric` |

A missing one fails the run at the "Resolve workspace" step with the variable
name, before anything reaches Fabric.

### Secrets

`AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` for the Reader SP
that logs in over OIDC, and `AZURE_KEYVAULT_NAME`.

The Deploy SP's own credentials are read at runtime from Key Vault:
`deploy-sp-tenant-id`, `deploy-sp-client-id`, `deploy-sp-client-secret`.

### Environments

`test` and `prod` under Settings → Environments. Put **Required reviewers** on
`prod` — that is the approval gate, and it is the only thing between a dispatch
and production.

## `cicd/`

| File | Used by | Does |
|---|---|---|
| `deploy.py` | both deploy workflows | `fabric_cicd.publish_all_items`, scoped by `--items-in-scope` |
| `grant_and_get_endpoints.py` | deploy-warehouse | reads the SQL endpoint, grants the SP `db_ddladmin` |
| `run_sql.py` | deploy-warehouse | `EXEC` a stored procedure, echo its result sets |
| `trigger_job.py` | deploy-to-fabric | runs a notebook/pipeline through the Fabric REST API, polls to completion |
| `validate_repo.py` | validate-pr, both deploys | every static check |
| `parameter.yml` | deploy-to-fabric | environment-specific ids, one key per environment |

### `parameter.yml`

Every rule needs a key per environment — `test` and `prod`. A missing key fails
`validate_repo.py` before anything is published. Both values are identical on
purpose: they are dynamic variables that resolve against whichever workspace the
run targets, so adding an environment means copying the line, never inventing a
GUID.

Every regex must have exactly one capture group — `fabric-cicd` only ever
replaces group 1.

## Manual steps, deliberately not automated

- Binding data-source credentials on `sales_semantic_model`. Fabric requires an
  interactive sign-in; there is no API for it.
- Loading data into Bronze, then running `pl_silver` to populate Gold.

## Known gap

Nothing verifies the result *after* a deploy. `validate_repo.py` reads files, not
Fabric. A green run means the commands did not error — not that the data is
right. The "Verify" block in each run's summary is a checklist for a human, not
a test.
