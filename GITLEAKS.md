# Gitleaks

Secret scanning for this repo. Config: [`.gitleaks.toml`](.gitleaks.toml).
Workflow: [`.github/workflows/gitleaks.yml`](.github/workflows/gitleaks.yml).

## When it runs

| Event | Scans |
|---|---|
| every push | the commits in that push |
| every pull request | the commits on the branch |
| daily, 04:00 UTC | full history |
| Run workflow | full history |

It is the only workflow here that is not dispatch-only. A scanner that waits to
be remembered catches nothing — the window that matters is the push that
introduced the leak.

The daily full scan exists because rules improve. A commit that looked clean
last month can match a rule added since, and only a re-scan finds it.

## When it goes red

**Rotate the credential first. Do not start by deleting the line.**

Once a secret is pushed it is in the remote history. Deleting it in a later
commit does not remove it — `git log -p` still shows it, anyone who cloned
already has it, and forks keep their own copy. The secret is burned the moment
it lands. Cleaning the file changes nothing about that.

### 1. Rotate

For the Deploy service principal:

```bash
az ad app credential reset --id <APP_ID> --years 1
az keyvault secret set --vault-name <VAULT> \
  --name deploy-sp-client-secret --value <NEW_VALUE>
```

The workflows read credentials from Key Vault at runtime, so updating the vault
is enough — no workflow change, no re-deploy.

If what leaked was a GitHub secret instead (`AZURE_*`, `AZURE_KEYVAULT_NAME`),
replace it under **Settings → Secrets and variables → Actions**.

### 2. Then fix the code

Remove the literal and read it from a secret or variable instead. Commit
normally — the history rewrite below is optional and usually not worth it.

### 3. Rewriting history (rarely)

Only worth doing for a repo that is public or widely cloned, and only after
rotating. It requires a force push and breaks every existing clone. Rotating is
what actually makes the leak harmless; scrubbing history is cosmetic.

## False positives

The two most likely sources here, and why they do not fire:

| Pattern | Where | Why it passes |
|---|---|---|
| `Password=$AZURE_CLIENT_SECRET` | `deploy-warehouse.yml` | rule excludes a `$` after `=` |
| `PWD={client_secret}` | `run_sql.py`, `grant_and_get_endpoints.py` | rule excludes a `{` after `=` |
| `${{ secrets.X }}` | every workflow | allowlisted — only the name is in the repo |
| `$items.Lakehouse.test_LH.$id` | `parameter.yml` | allowlisted — a publish-time placeholder |

If something new fires and is genuinely safe, add it to `[allowlist]` in
`.gitleaks.toml` as a **specific regex**.

Do not add `fabric/` to `paths`. It is the noisiest folder — full of workspace
GUIDs, logicalIds and OneLake paths — which makes excluding it tempting. It is
also exactly where someone would paste a token while debugging a notebook.
Excluding a folder for being noisy switches the scanner off where it is needed
most.

Workspace GUIDs are not secrets, incidentally. They already live in repository
variables in the clear.

## Rules

Everything gitleaks ships by default, plus two for this stack:

- `fabric-connection-string-password` — a literal password in a warehouse
  connection string
- `fabric-api-bearer-token` — a Fabric / Power BI REST API JWT, the kind pasted
  in while debugging and forgotten

Regexes use Go RE2: **no lookahead, no backreferences**. That is why the
password rule excludes template syntax with a character class rather than
`(?!\$)`.

## Running it locally

Optional — CI covers every push either way. The reason to bother: CI finds a
leak *after* it is in history, and that always costs a credential rotation. A
pre-commit hook stops the commit from existing, so there is nothing to rotate.

Not currently set up in this repo. Each person sets it up on their own machine.

### 1. Install the binary

Standalone Go binary — no Python, no Node.

```powershell
winget install gitleaks
```

Alternatives: `scoop install gitleaks`, `choco install gitleaks`, or the `.exe`
from <https://github.com/gitleaks/gitleaks/releases>.

Check it took:

```bash
gitleaks version
```

### 2. Scan by hand

```bash
# staged changes only — what the hook will run, ~1s
gitleaks protect --staged --redact --config .gitleaks.toml --verbose

# whole history — what CI runs nightly, slower
gitleaks detect --redact --config .gitleaks.toml
```

`--redact` keeps the matched value out of your terminal and scrollback. Without
it you paste the secret somewhere new while asking about it.

> Gitleaks ≥ 8.19 prints a deprecation notice for `detect` and `protect` and
> prefers `gitleaks git`. Both still work. If a command errors outright, check
> `gitleaks --help` for the form your version wants.

### 3. Wire it into the hook

`.git/hooks/` is not tracked by git, so a hook placed there cannot be shared.
Point git at a tracked folder instead:

```bash
mkdir -p .githooks
```

`.githooks/pre-commit`:

```sh
#!/usr/bin/env sh
# Aborts the commit when gitleaks finds a secret in the staged changes.

if ! command -v gitleaks >/dev/null 2>&1; then
  echo "gitleaks not installed — skipping scan (CI will still catch it)"
  exit 0
fi

gitleaks protect --staged --redact --config .gitleaks.toml --verbose
```

Then, **once per clone**:

```bash
git config core.hooksPath .githooks
chmod +x .githooks/pre-commit    # Git Bash / WSL; not needed on Windows-only
```

Git for Windows ships its own `sh`, so the script runs from Git Bash, PowerShell
and the VS Code UI alike.

The `command -v` guard matters: without it, anyone who has not installed the
binary cannot commit at all. A missing scanner should degrade to CI, not block
the repo.

### 4. Check it actually fires

```bash
echo 'password=hunter2supersecret' > leak-test.txt
git add leak-test.txt
git commit -m "test"     # should be refused
rm leak-test.txt && git reset
```

If the commit goes through, `core.hooksPath` did not take — confirm with
`git config core.hooksPath`.

### Bypassing

```bash
git commit --no-verify
```

Left available deliberately. A hook that cannot be skipped gets deleted the
first time it is wrong. CI is the layer that cannot be skipped, which is why
both exist: the hook catches the ordinary slip, the workflow catches everything
else.
