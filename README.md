# Fabric CI/CD

GitHub Actions pipeline for deploying Microsoft Fabric items and a Fabric
Warehouse schema. If this document and the code disagree, the code wins.

## Branches

```
dev  ──PR──►  test  ──PR──►  prod
```

| Branch | Role | Deploys? |
|---|---|---|
| `dev` | where work happens | no |
| `test` | test environment | no |
| `prod` | default branch, production record | no |

**Neither `test` nor `prod` deploys on merge.** Both workflows are dispatch-only
— a push carries no way to say *which release* is going out, so nothing ships
without someone picking a tag and a workspace in Run workflow. Merging a PR
only moves code onto a branch; it never triggers Fabric.

`prod` being the default branch matters for one reason unrelated to deploying:
the dispatch form's inputs are read from whatever is on the default branch. If
an input changes, `prod` needs the merge before the new form shows up — not per
release, only when the workflow files themselves change.

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

### `gitleaks.yml`

Scans the working tree and git history for hardcoded secrets. The only workflow
here that is **not** dispatch-only: it runs on every push and pull request, plus
daily at 04:00.

That is deliberate. A scanner nobody remembers to run catches nothing, and the
window that matters is the push that introduced the leak — before it reaches
another branch.

A finding fails the run and comments on the pull request. Treat a hit as a
**rotate the credential** signal, not a "delete the line" one: removing a secret
in a later commit leaves it in the history, where it is still readable.

### `deploy-to-fabric.yml`

Publishes **every Fabric item** — and runs none of them.

Trigger: Run workflow only.

```
validate  →  resolve workspace  →  Azure login + Key Vault
          →  stage parameter.yml
          →  publish items
```

Warehouse and Lakehouse are in `--items-in-scope`, but only their **item shell**
is published here — no schema. They are in scope because `fabric-cicd` resolves
`$items.<Type>.<name>.$id` only for types in scope for that run, and
`parameter.yml` needs both ids.

### `deploy-warehouse.yml`

The warehouse **schema** only: dacpac build, SqlPackage publish. It changes
shape, never data. Separate because it is the one pipeline needing .NET,
SqlPackage and msodbcsql18.

Trigger: Run workflow only.

```
validate  →  resolve SQL endpoint  →  build dacpac
          →  preview (report + script, uploaded as an artifact)
          →  publish schema
```

It does **not** create the Warehouse item — `deploy-to-fabric.yml` owns every
item shell. That split is what stops the two workflows from writing the same
item at once.

Consequence: a brand-new warehouse needs one `deploy-to-fabric.yml` run first.
Until then this workflow fails at the endpoint lookup and lists the warehouses
that do exist.

### `run-fabric-item.yml`

Executes one thing in a workspace. Deploying publishes definitions; this runs
them, so a failure here means the code is wrong rather than the deploy.

| `item_type` | `item_name` | Goes through |
|---|---|---|
| `Notebook` | `nb_lakehouse_schema` | Fabric REST API, polled to completion |
| `DataPipeline` | `pl_silver` | same |
| `StoredProcedure` | `Gold.usp_populate_new_columns` | ODBC against the warehouse |

Unlike the deploy path, a missing item fails the run. Asking for something by
name and not getting it is a mistake, not a no-op.

## Deploying

Same flow for `test` and `prod` — the only difference is which workspace you
pick and, for `prod`, an approval in the middle.

1. Push (or merge into `dev`, or tag any commit you want, including `test`'s
   current HEAD):
   ```bash
   git tag -a releases/1.3.0 -m "releases/1.3.0"
   git push origin releases/1.3.0
   ```
2. **Actions** → **Deploy to Fabric** (or **Deploy warehouse**) → **Run workflow**
3. **Use workflow from** → **Tags** tab → pick the tag
4. **Choose target workspace** → `test` or `prod`
5. Run workflow. A `prod` run pauses for approval at the environment gate;
   `test` does not.

A dispatch always runs in full — there is no path filter deciding which
workflow applies, so you decide which to run based on what the tag changed:

| Tag contains | Run |
|---|---|
| notebook / pipeline / model changes | Deploy to Fabric |
| warehouse `.sql` changes | Deploy warehouse |
| both | both, **Deploy to Fabric first** |

Unsure? Run both. Each is idempotent.

The usual order is deploy to `test`, look at the result in Fabric, then run the
same tag again against `prod` — but nothing enforces that order. Nothing stops
tagging straight to `prod` either; the approval gate is the only checkpoint.

### After a deploy

A deploy publishes definitions and stops. Anything that has to *execute* is a
separate run of **Run Fabric item**:

| After | Run | Because |
|---|---|---|
| Deploy to Fabric, on a new workspace | `nb_lakehouse_schema` (Notebook) | the lakehouse has no tables until it does |
| Deploy warehouse, when the release added a column | `Bronze.usp_populate_new_columns`, then the Gold one | Gold reads from Bronze, so the order matters |
| Bronze has new data | `pl_silver` (DataPipeline) | populates Gold |

Splitting them is deliberate: publishing a definition is safe to repeat,
running one is not always. Adding a column and deciding to populate it are two
decisions, and a deploy should not make the second one for you.

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

Deploying the schema does **not** run the procs. After `Deploy warehouse`, run
them yourself through **Run Fabric item** — Bronze first, Gold second, because
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
| `run_sql.py` | run-fabric-item | `EXEC` a stored procedure, echo its result sets |
| `trigger_job.py` | run-fabric-item | runs a notebook/pipeline through the Fabric REST API, polls to completion |
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
