# Gitleaks — Demo Scenario

Three cases, run entirely through GitHub Actions. No local gitleaks install.

Each case has a point to make; run them in order, the narrative builds.

> **Every secret below is fabricated.** They match by *shape*, not by value.
> Never demo with a real credential, including an expired one.

> **Use a throwaway branch and delete it afterwards.** The fixtures stay in that
> branch's history permanently. Never merge it.

---

## Setup

```bash
git checkout dev
git pull
git checkout -b demo/gitleaks
```

---

## Case 1 — It catches a leak, and leaves real code alone

The point: **the ruleset was written for this repo, not copied off the shelf.**

Create `demo-leak.yml`:

```yaml
# One of these four is a leak. Three are lines copied from this repo.
leaked:      "Password=Fabr1c!Demo2026;"
from_yml:    "Password=$AZURE_CLIENT_SECRET"
from_python: 'f"PWD={client_secret};"'
gh_secret:   "${{ secrets.AZURE_CLIENT_ID }}"
```

```bash
git add demo-leak.yml
git commit -m "demo: leaked connection string"
git push origin demo/gitleaks
```

Actions → **Gitleaks** → run fails with **exactly one** finding:

```
RuleID:  fabric-connection-string-password
File:    demo-leak.yml
Line:    2
```

### What to show the audience

Put the finding next to the file. Four lines, all containing `Password=` or a
secret reference. **One red, three green.**

| Line | Result | Why |
|---|---|---|
| `Password=Fabr1c!Demo2026;` | 🔴 | a literal value |
| `Password=$AZURE_CLIENT_SECRET` | 🟢 | rule excludes `$` after `=` |
| `PWD={client_secret}` | 🟢 | rule excludes `{` after `=` |
| `${{ secrets.AZURE_CLIENT_ID }}` | 🟢 | allowlisted — only the name is in the repo |

Open [`deploy-warehouse.yml`](.github/workflows/deploy-warehouse.yml) and
[`run_sql.py`](cicd/run_sql.py) alongside it: those green lines are real,
shipping code. A ruleset that flagged them would be switched off within a week.

---

## Case 2 — Deleting the secret does not fix it

The point: **a hit means rotate the credential, not delete the line.**

```bash
git rm demo-leak.yml
git commit -m "demo: remove the leak"
git push origin demo/gitleaks
```

The working tree is clean now. Show that the secret is not:

```bash
git log -p -- demo-leak.yml
```

Then Actions → **Gitleaks** → **Run workflow**, with `demo/gitleaks` selected.
That is the full-history scan.

Expected: **still fails, still reports the same finding.**

### What to show the audience

Deleting the file changed nothing about who can read the secret. Anyone who
cloned already has it; forks keep their own copy.

This is what `fetch-depth: 0` in the workflow is for — a shallow clone has no
history, and this case would pass.

It is also the reason [`GITLEAKS.md`](GITLEAKS.md#when-a-scan-goes-red) leads
with `az ad app credential reset` rather than "remove the line".

---

## Case 3 — It gates the pull request, next to the Fabric checks

The point: **two workflows, two different questions.**

Open a pull request from `demo/gitleaks` into `test`.

Two workflows run:

| Workflow | Asks | Result |
|---|---|---|
| **Gitleaks** | is anything in here secret? | 🔴 fails, comments on the PR |
| **Validate pull request** | will this deploy correctly? | 🟢 passes |

### What to show the audience

The PR page, with one check red and one green.

`validate-pr.yml` passes because the fixture breaks nothing it looks at — repo
structure, `parameter.yml` coverage, notebook portability, T-SQL batching, the
dacpac build. It is a perfectly valid deployment that happens to contain a
credential.

That is the argument for having both. A change can pass one and fail the other,
and neither substitutes for the other.

The bot comment on the PR is worth pointing at too — the developer who caused it
sees it where they are already looking, without opening the Actions tab.

---

## Cleanup

```bash
git checkout dev
git branch -D demo/gitleaks
git push origin --delete demo/gitleaks
```

Close the pull request without merging.

Delete the remote branch, not just the local one — otherwise the fixtures stay
in the repo and the nightly full-history scan keeps failing on them.
