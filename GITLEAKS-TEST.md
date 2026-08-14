# Gitleaks — Test Scenario

An end-to-end exercise of every rule, the allowlist, the history scan, and how
gitleaks interacts with the Fabric CI workflows.

> **Every secret below is fabricated.** They match by *shape*, not by value.
> Never test with a real credential, including an expired one.

> **Use a throwaway branch and delete it afterwards.** The fixtures land in that
> branch's history permanently. Never merge it.

---

## What is being tested

| # | Case | Proves |
|---|---|---|
| 1 | Default ruleset | `useDefault = true` is live |
| 2 | `fabric-connection-string-password` | custom rule 1 fires |
| 3 | `fabric-api-bearer-token` | custom rule 2 fires |
| 4 | Token inside `fabric/` | the folder is not path-excluded |
| 5 | Templated secrets | no false positive on real repo code |
| 6 | Allowlist patterns | `${{ secrets.X }}` and `$items.` pass |
| 7 | Deleted secret | history scan still finds it |
| 8 | PR gate | gitleaks blocks a PR alongside `validate-pr.yml` |

---

## Setup

```bash
git checkout dev
git pull
git checkout -b demo/gitleaks-test
mkdir -p gitleaks-fixtures
```

---

## Case 1 — Default ruleset

`gitleaks-fixtures/01-aws.txt`:

```
aws_access_key_id = AKIAIOSFODNN7EXAMPLE
aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
```

AWS's own documented example key. Expect rule `aws-access-token`.

**Why it matters:** confirms the custom config did not accidentally replace the
defaults. A config with `useDefault = false` would pass this file.

---

## Case 2 — Warehouse connection string

`gitleaks-fixtures/02-connection.txt`:

```
CONN="Server=tcp:abc123.datawarehouse.fabric.microsoft.com,1433;Initial Catalog=insurance_WH;User Id=svc-deploy;Password=Fabr1c!Demo2026;"
```

Expect rule `fabric-connection-string-password`.

This is the rule written for the real risk in this repo:
[`deploy-warehouse.yml`](.github/workflows/deploy-warehouse.yml) and
[`run_sql.py`](cicd/run_sql.py) both assemble ODBC connection strings, and the
failure mode is someone pasting a working one in to debug.

---

## Case 3 — Fabric REST API token

`gitleaks-fixtures/03-bearer.py`:

```python
headers = {
    "Authorization": "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJhdWQiOiJodHRwczovL2FwaS5mYWJyaWMubWljcm9zb2Z0LmNvbSJ9.Zm9yLXRlc3Rpbmctb25seS1ub3QtYS1yZWFsLXRva2Vu"
}
```

Expect rule `fabric-api-bearer-token`.

---

## Case 4 — Token inside `fabric/`

`fabric/test_LH.Lakehouse/04-debug-notes.json`:

```json
{
  "note": "temp while debugging the items API",
  "auth": "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJkZW1vIn0.ZmFrZS1zaWduYXR1cmUtZm9yLXRlc3Rpbmc"
}
```

Expect rule `fabric-api-bearer-token`.

**This is the most important case.** `fabric/` is the noisiest folder in the
repo — workspace GUIDs, logicalIds, OneLake paths — which makes excluding it
tempting the first time a scan is loud. It is also exactly where a debugging
token gets pasted. If this case passes silently, someone has added `fabric/` to
`paths` in [`.gitleaks.toml`](.gitleaks.toml) and the scanner is off where it is
needed most.

---

## Case 5 — Templated secrets must NOT fire

`gitleaks-fixtures/05-safe-templates.yml`:

```yaml
# Copies of real lines from this repo. All four must pass clean.
conn_yaml: "Password=$AZURE_CLIENT_SECRET"
conn_py: 'f"PWD={client_secret};"'
gh_expr: "${{ secrets.AZURE_CLIENT_ID }}"
placeholder: "$items.Lakehouse.test_LH.$id"
```

Expect **no findings**.

| Line | Passes because |
|---|---|
| `Password=$AZURE_CLIENT_SECRET` | rule excludes `$` after `=` |
| `PWD={client_secret}` | rule excludes `{` after `=` |
| `${{ secrets.X }}` | allowlist regex |
| `$items.Lakehouse.test_LH.$id` | allowlist regex |

A finding here is a **false positive** and means the rules would fire on real
repo code — the fastest way to get a scanner switched off entirely.

---

## Case 6 — Run the scan

### Locally (fastest)

```bash
gitleaks detect --no-git --source . --config .gitleaks.toml --verbose
```

Expected: **4 findings** — cases 1, 2, 3, 4. Nothing from case 5.

### In CI

```bash
git add gitleaks-fixtures fabric/test_LH.Lakehouse/04-debug-notes.json
git commit -m "test: gitleaks fixtures"
git push origin demo/gitleaks-test
```

Actions → **Gitleaks** → the run fails. Open it and check the `RuleID` of each
finding against the table above.

### Results checklist

| Case | Expected `RuleID` | Got it? |
|---|---|---|
| 1 | `aws-access-token` | ☐ |
| 2 | `fabric-connection-string-password` | ☐ |
| 3 | `fabric-api-bearer-token` | ☐ |
| 4 | `fabric-api-bearer-token` (in `fabric/`) | ☐ |
| 5 | *nothing* | ☐ |

---

## Case 7 — A deleted secret is still a leak

The point of `fetch-depth: 0`.

```bash
git rm gitleaks-fixtures/02-connection.txt
git commit -m "test: remove the leaked connection string"
git push origin demo/gitleaks-test
```

The working tree is now clean. The secret is not:

```bash
git log -p -- gitleaks-fixtures/02-connection.txt   # still there
```

Now run a **full-history** scan — Actions → Gitleaks → **Run workflow**, with
this branch selected.

Expected: **still fails**, still reports case 2.

This is the case that justifies the whole runbook. Deleting the line changed
nothing about who can read the secret, which is why a hit means *rotate the
credential*.

---

## Case 8 — The PR gate, with Fabric CI

Open a pull request from `demo/gitleaks-test` into `test`.

Two workflows fire, and they check different things:

| Workflow | Checks | Expected |
|---|---|---|
| **Gitleaks** | secrets in the diff and history | 🔴 fails, comments on the PR |
| **Validate pull request** | repo structure, `parameter.yml` coverage, notebook portability, T-SQL batching, dacpac build | 🟢 passes — fixtures break none of it |

The split is the point:

- `validate-pr.yml` answers *"will this deploy correctly?"*
- `gitleaks.yml` answers *"is anything in here secret?"*

A change can pass one and fail the other. Neither substitutes for the other, and
a branch ruleset requiring both is what makes the pair a gate rather than a
suggestion.

> Case 4 puts a stray `.json` inside a Lakehouse item folder. `validate_repo.py`
> tolerates it — it only requires each item folder to carry a `.platform`. But
> if this branch were ever deployed, `fabric-cicd` would publish that file as
> part of the item. One more reason never to merge it.

---

## Case 9 — Pre-commit hook (optional)

Only if the hook from [GITLEAKS.md](GITLEAKS.md#local-pre-commit-hook) is
installed.

```bash
echo 'password=hunter2supersecret' > gitleaks-fixtures/09-hook.txt
git add gitleaks-fixtures/09-hook.txt
git commit -m "test: hook"
```

Expected: **the commit is refused** before it exists.

```bash
git commit -m "test: hook" --no-verify   # succeeds — bypass is deliberate
```

The bypass proves why CI still matters: the hook is a convenience, not a
control.

---

## Cleanup

```bash
git checkout dev
git branch -D demo/gitleaks-test
git push origin --delete demo/gitleaks-test
```

Delete the branch on GitHub too, so the fixtures stop appearing in search and in
the nightly full-history scan.

> If the nightly scan keeps failing after cleanup, the branch still exists
> somewhere — check `git branch -a` and the repo's branch list.
