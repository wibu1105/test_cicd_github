# Gitleaks — Secret Scanning

Gitleaks is a SAST tool that detects hardcoded secrets — passwords, API keys,
tokens — in a git repository, both in the current working tree and throughout
its history.

This document covers how it is configured here, what to do when it fires, and
how to add the optional local pre-commit hook.

| | |
|---|---|
| Config | [`.gitleaks.toml`](.gitleaks.toml) |
| Workflow | [`.github/workflows/gitleaks.yml`](.github/workflows/gitleaks.yml) |
| Pre-commit hook | **not set up** — see [Local pre-commit hook](#local-pre-commit-hook) |
| Test scenario | [`GITLEAKS-TEST.md`](GITLEAKS-TEST.md) |

---

## Why two layers

A secret scanner can sit in two places, and they are not interchangeable.

```
   YOUR MACHINE                          │        GITHUB
                                         │
   edit  ──►  git add  ──►  git commit   │   push  ──►  Gitleaks workflow
                                ▲        │                     ▲
                                │        │                     │
                          pre-commit     │                CI scan
                             hook        │
                                         │
                    ┌───────────────┐    │      ┌────────────────────┐
                    │ Secret never  │    │      │ Secret is ALREADY  │
                    │ enters git.   │    │      │ in history.        │
                    │ Fix = delete  │    │      │ Fix = ROTATE the   │
                    │ the line.     │    │      │ credential.        │
                    └───────────────┘    │      └────────────────────┘
                       cheap             │              expensive
```

The moment a secret is committed and pushed, it is public to anyone with repo
access — permanently. Deleting it in a later commit does not remove it:

```bash
git log -p          # the old commit still shows the secret
```

Anyone who cloned already has it. Forks keep their own copy. GitHub may serve it
from cache. **The only thing that makes the leak harmless is rotating the
credential.**

That is the whole argument for the hook: not that CI is unreliable, but that by
the time CI speaks, the damage is done.

```
        leak introduced
              │
              ├──► caught by hook ......... 5 seconds, delete a line
              │
              └──► caught by CI ........... rotate the credential,
                                            update Key Vault,
                                            verify nothing broke
```

Neither layer replaces the other. The hook is bypassable (`--no-verify`) and
only exists on machines where it was installed. CI cannot be skipped and covers
everyone, including a new teammate on day one.

---

## What runs in CI

| Trigger | Scope scanned |
|---|---|
| every `push` | commits in that push |
| every `pull_request` | commits on the branch |
| `schedule`, daily 04:00 UTC | full history |
| `workflow_dispatch` | full history |

This is the **only** workflow in this repo that is not dispatch-only. Every
deploy workflow requires someone to pick a release; a scanner needs the
opposite. Its value is running on the push that introduced the leak, without
waiting to be remembered.

The nightly full-history scan exists because rules improve. A commit that looked
clean last month can match a rule added since, and only a re-scan finds it.

### Key workflow settings

```yaml
- uses: actions/checkout@v6
  with:
    fetch-depth: 0        # REQUIRED — see below
```

`fetch-depth: 0` is not a preference. The default shallow clone contains no
history, so a secret that was committed and then removed — the case that matters
most, because it is still in the log — would be invisible.

```yaml
permissions:
  contents: read
  pull-requests: write    # to comment on the PR
  security-events: write  # to upload the SARIF report
```

Without `pull-requests: write`, the scan still fails the build but the PR
comment silently never appears.

---

## Rules

Everything gitleaks ships by default (`useDefault = true`), plus two written for
this stack.

### `fabric-connection-string-password`

```toml
regex = '''(?i)(?:password|pwd)\s*=\s*([^$;"'\s{][^;"'\s]{7,})'''
```

Catches a literal password in a warehouse connection string. The leading
character class excludes `$` and `{`, so every templated form this repo actually
uses passes cleanly:

| Line | First char after `=` | Result |
|---|---|---|
| `Password=$AZURE_CLIENT_SECRET` — `deploy-warehouse.yml` | `$` | 🟢 ignored |
| `PWD={client_secret}` — `run_sql.py` | `{` | 🟢 ignored |
| `PWD={client_secret}` — `grant_and_get_endpoints.py` | `{` | 🟢 ignored |
| `Password=Fabr1c!Demo2026` — a real leak | `F` | 🔴 **flagged** |

> **Why a character class and not `(?!\$)`?**
> Gitleaks uses Go's RE2 engine, which has **no lookahead and no
> backreferences**. A lookahead does not compile — the config fails to load and
> the run falls back to defaults, silently dropping both custom rules.

### `fabric-api-bearer-token`

```toml
regex = '''(?i)bearer\s+(eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})'''
```

Catches a Fabric or Power BI REST API JWT. These are short-lived, which is
precisely why people paste one into a notebook while debugging and forget it.

---

## Allowlist

Three patterns, each traceable to a specific line in this repo:

```toml
'''\$\{\{\s*secrets\.[A-Za-z_][A-Za-z0-9_]*\s*\}\}'''   # ${{ secrets.X }}
'''\$items\.[A-Za-z]+\.[^.\s]+\.\$[a-z]+'''             # $items.Lakehouse.test_LH.$id
'''\$workspace\.\$id'''                                  # $workspace.$id
```

The first is a GitHub expression naming a secret — only the *name* is in the
repo, never the value. The other two are `fabric-cicd` placeholders resolved at
publish time against the target workspace.

### What is deliberately NOT allowlisted

**`fabric/` is not path-excluded.** It is by far the noisiest folder — workspace
GUIDs in `.platform`, logicalIds, OneLake paths in `.tmdl` — which makes
excluding it tempting the first time a scan is noisy.

It is also exactly where someone would paste a token while debugging a notebook.
Excluding a folder for being noisy switches the scanner off in the one place it
is most needed.

> Workspace GUIDs are **not secrets**. They already live in repository variables
> in the clear. If one is flagged, allowlist that specific pattern — never the
> folder.

---

## When a scan goes red

```
                    Gitleaks fails
                          │
                          ▼
              ┌───────────────────────┐
              │ Is it a real secret?  │
              └───────────┬───────────┘
                    ┌─────┴─────┐
                   YES          NO
                    │            │
                    ▼            ▼
         ┌──────────────┐   ┌──────────────────────┐
         │ 1. ROTATE    │   │ Add a SPECIFIC regex │
         │ 2. Fix code  │   │ to [allowlist].      │
         │ 3. Re-push   │   │ Never a path.        │
         └──────────────┘   └──────────────────────┘
```

### Step 1 — Rotate. Always first.

For the Deploy service principal:

```bash
# New client secret in Entra ID
az ad app credential reset --id <APP_ID> --years 1

# Push it into Key Vault — the workflows read from here at runtime
az keyvault secret set --vault-name <VAULT_NAME> \
  --name deploy-sp-client-secret \
  --value <NEW_VALUE>
```

No workflow change and no re-deploy are needed — every deploy job fetches
credentials from Key Vault at run time.

If what leaked was a GitHub secret instead (`AZURE_CLIENT_ID`,
`AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AZURE_KEYVAULT_NAME`), replace it
under **Settings → Secrets and variables → Actions**.

### Step 2 — Then fix the code

Remove the literal, read it from a secret or variable instead, commit normally.

### Step 3 — Rewriting history (rarely worth it)

Only for a public or widely-cloned repo, and only *after* rotating. It needs a
force push and breaks every existing clone. Rotating is what makes the leak
harmless; scrubbing history is cosmetic.

---

## Local pre-commit hook

**Not currently set up.** Each person enables it on their own machine. Optional
— CI covers every push either way — but it is the difference between deleting a
line and rotating a credential.

### 1. Install the binary

A standalone Go binary. No Python, no Node.

```powershell
winget install gitleaks
```

Alternatives: `scoop install gitleaks`, `choco install gitleaks`, or download
the `.exe` from <https://github.com/gitleaks/gitleaks/releases>.

```bash
gitleaks version
# 8.28.0
```

### 2. Try a scan by hand first

```bash
# staged changes only — what the hook will run. ~1 second.
gitleaks protect --staged --redact --config .gitleaks.toml --verbose

# entire history — what CI runs nightly. Slower.
gitleaks detect --redact --config .gitleaks.toml
```

`--redact` keeps the matched value out of your terminal and scrollback. Without
it, investigating a leak copies the secret somewhere new.

> Gitleaks ≥ 8.19 prints a deprecation notice for `detect` and `protect`,
> preferring `gitleaks git`. Both still work. If a command errors outright,
> check `gitleaks --help` for the form your version expects.

**A clean scan:**

```
    ○
    │╲
    │ ○
    ○ ░
    ░    gitleaks

12:04PM INF 3 commits scanned.
12:04PM INF scanned ~48293 bytes (48.29 KB) in 91.2ms
12:04PM INF no leaks found
```

**A scan that finds something:**

```
Finding:     Password=REDACTED
Secret:      REDACTED
RuleID:      fabric-connection-string-password
Entropy:     3.584963
File:        cicd/debug_connect.py
Line:        14
Fingerprint: cicd/debug_connect.py:fabric-connection-string-password:14

12:06PM WRN leaks found: 1
```

The `RuleID` tells you which rule fired — useful for deciding between "rotate"
and "allowlist".

### 3. Create the hook

`.git/hooks/` is not tracked by git, so a hook placed there cannot be shared.
Point git at a tracked folder instead.

Create `.githooks/pre-commit`:

```sh
#!/usr/bin/env sh
# Refuses a commit whose staged changes contain a secret.
# Enable once per clone:  git config core.hooksPath .githooks

# No binary, no block. A missing optional tool must not stop people committing;
# the workflow scans every push regardless.
command -v gitleaks >/dev/null 2>&1 || {
  echo "gitleaks not installed - skipping scan (CI will still catch it)"
  exit 0
}

exec gitleaks protect --staged --redact --config .gitleaks.toml --verbose
```

The `command -v` guard matters. Without it, anyone who has not installed the
binary cannot commit at all — a missing scanner should degrade to CI, not block
the repository.

### 4. Enable it — once per clone

```bash
git config core.hooksPath .githooks
chmod +x .githooks/pre-commit     # Git Bash / WSL; unnecessary on Windows-only
```

Git for Windows bundles its own `sh`, so the script runs identically from Git
Bash, PowerShell, and the VS Code source-control UI.

### 5. Verify it fires

```bash
echo 'password=hunter2supersecret' > leak-test.txt
git add leak-test.txt
git commit -m "test"
```

Expected — the commit is refused:

```
Finding:     password=REDACTED
Secret:      REDACTED
RuleID:      fabric-connection-string-password
File:        leak-test.txt
Line:        1

12:11PM WRN leaks found: 1
```

```bash
rm leak-test.txt && git reset
```

If the commit went through, `core.hooksPath` did not take:

```bash
git config core.hooksPath      # should print: .githooks
```

### Bypassing

```bash
git commit --no-verify
```

Left available deliberately. A hook that cannot be skipped gets deleted the
first time it is wrong. CI is the layer that cannot be skipped — which is
exactly why both exist.

---

## Demonstrating it

Use a throwaway branch. A fake secret still lands in that branch's history.

### Bait

```
CONN="Server=tcp:abc123.datawarehouse.fabric.microsoft.com,1433;Initial Catalog=insurance_WH;User Id=svc-deploy;Password=Fabr1c!Demo2026;"
```

Entirely fabricated. It matches by *shape*, not by value — never demo with a
real credential, including an expired one.

### The point worth making

Do not just show that it catches a secret; any default ruleset does that. Show
that the config was **written for this repo**:

| Line | Result |
|---|---|
| `Password=Fabr1c!Demo2026;` — the bait | 🔴 flagged |
| `Password=$AZURE_CLIENT_SECRET` — `deploy-warehouse.yml`, real code | 🟢 clean |
| `PWD={client_secret}` — `run_sql.py`, real code | 🟢 clean |
| `${{ secrets.AZURE_CLIENT_ID }}` — every workflow | 🟢 clean |

Open those files side by side. **The same word `Password=`, one red and three
green** — that is the evidence the ruleset was tuned rather than copied.

Close on the runbook: a hit means *rotate the credential*, not *delete the line*.

### Cleanup

```bash
git checkout dev
git branch -D demo/gitleaks
git push origin --delete demo/gitleaks
```

---

## Command reference

| Command | Scans | Typical use |
|---|---|---|
| `gitleaks protect --staged` | staged changes | pre-commit hook |
| `gitleaks protect` | all uncommitted changes | before staging |
| `gitleaks detect` | full git history | audit, nightly CI |
| `gitleaks detect --no-git --source .` | files on disk, ignoring git | a folder that is not a repo |

| Flag | Effect |
|---|---|
| `--config <path>` | rule file to use |
| `--redact` | print `REDACTED` instead of the matched value |
| `--verbose` | print each finding, not just a count |
| `--no-banner` | suppress the ASCII logo |
| `--exit-code <n>` | exit status when leaks are found (default `1`) |

Exit codes: `0` clean · `1` leaks found · `126` config or usage error.

---

