#!/usr/bin/env python3
# cicd/validate_repo.py
#
# Static checks that run on every pull request, before anything is merged or
# deployed. Nothing here touches Fabric — no API calls, no credentials — so it
# is fast, free, and safe to run on untrusted PR branches.
#
# The checks encode failure modes that are silent at deploy time: a semantic
# model quietly reading from the dev warehouse, a CREATE SCHEMA batch that
# only fails once it reaches the server, a notebook that regressed to a
# hardcoded endpoint. Catching them here turns a silent production problem
# into a red X on a pull request.
#
# Run locally the same way CI does:
#     python cicd/validate_repo.py --target-env test

import argparse
import ast
import json
import pathlib
import re
import sys

FABRIC_DIR = pathlib.Path("fabric")
CICD_DIR = pathlib.Path("cicd")

WAREHOUSE_HOST_RE = re.compile(r"[a-z0-9\-]+\.datawarehouse\.fabric\.microsoft\.com")
GUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")

# A DirectLake-on-OneLake model does not name a SQL endpoint at all. It reaches
# its warehouse or lakehouse through a OneLake path that carries two ids:
#     https://onelake.dfs.fabric.microsoft.com/<workspace id>/<item id>
# Both are environment-specific, and because neither is a *.datawarehouse.*
# hostname, a check that only looks for endpoints reports the model as clean
# while it keeps reading from dev after deploy. That is the exact failure this
# pattern exists to catch.
ONELAKE_URL_RE = re.compile(
    r"onelake\.dfs\.fabric\.microsoft\.com/"
    r"([0-9a-fA-F-]{36})/([0-9a-fA-F-]{36})")


class Report:
    """Collects findings and emits GitHub Actions annotations."""

    def __init__(self):
        self.errors = []
        self.warnings = []
        self.notes = []

    def error(self, check, message, file=None):
        self.errors.append((check, message, file))
        loc = f"file={file}::" if file else ""
        print(f"::error {loc}title={check}::{message}")

    def warn(self, check, message, file=None):
        self.warnings.append((check, message, file))
        loc = f"file={file}::" if file else ""
        print(f"::warning {loc}title={check}::{message}")

    def ok(self, message):
        self.notes.append(message)
        print(f"  OK: {message}")

    def info(self, message):
        print(f"  {message}")

    def summary(self):
        print()
        print("=" * 62)
        print(f"  {len(self.errors)} error(s), {len(self.warnings)} warning(s)")
        print("=" * 62)
        if self.errors:
            print("\nErrors:")
            for check, msg, f in self.errors:
                print(f"  [{check}] {msg}" + (f"  ({f})" if f else ""))
        return 1 if self.errors else 0


# ----------------------------------------------------------------------
# 1. Repository structure
# ----------------------------------------------------------------------
def check_structure(rep):
    print("\n[1] Repository structure")

    required_dirs = [FABRIC_DIR, CICD_DIR, pathlib.Path(".github/workflows")]
    for d in required_dirs:
        if d.is_dir():
            rep.ok(f"{d}/ exists")
        else:
            rep.error("structure", f"Missing required directory: {d}/")

    required_files = [
        CICD_DIR / "deploy.py",
        CICD_DIR / "grant_and_get_endpoints.py",
        CICD_DIR / "requirements.txt",
        CICD_DIR / "parameter.yml",
    ]
    for f in required_files:
        if f.is_file():
            rep.ok(f"{f} exists")
        else:
            rep.error("structure", f"Missing required file: {f}")

    if not FABRIC_DIR.is_dir():
        return

    # Every Fabric item folder must carry a .platform file. A folder without
    # one is usually a partial commit, and fabric-cicd will skip it silently.
    item_dirs = [p for p in FABRIC_DIR.iterdir()
                 if p.is_dir() and "." in p.name]
    if not item_dirs:
        rep.error("structure", f"No Fabric item folders found under {FABRIC_DIR}/")
        return

    for d in sorted(item_dirs):
        if (d / ".platform").is_file():
            rep.ok(f"{d.name} has .platform")
        else:
            rep.error("structure",
                      f"{d.name} has no .platform file — fabric-cicd will ignore it. "
                      f"Re-commit this item from the Source control pane in Fabric.",
                      file=str(d))


# ----------------------------------------------------------------------
# 2. Python syntax of the deployment scripts
# ----------------------------------------------------------------------
def check_python_syntax(rep):
    print("\n[2] Deployment script syntax")
    scripts = sorted(CICD_DIR.glob("*.py")) if CICD_DIR.is_dir() else []
    if not scripts:
        rep.warn("python", "No Python scripts found in cicd/")
        return
    for s in scripts:
        try:
            ast.parse(s.read_text())
            rep.ok(f"{s.name} parses")
        except SyntaxError as e:
            rep.error("python", f"{s.name} line {e.lineno}: {e.msg}", file=str(s))


# ----------------------------------------------------------------------
# 3. Workflow YAML syntax
# ----------------------------------------------------------------------
def check_workflow_yaml(rep):
    print("\n[3] Workflow YAML syntax")
    try:
        import yaml
    except ImportError:
        rep.warn("yaml", "PyYAML not installed — skipping YAML checks")
        return

    wf_dir = pathlib.Path(".github/workflows")
    if not wf_dir.is_dir():
        return
    for wf in sorted(wf_dir.glob("*.y*ml")):
        try:
            yaml.safe_load(wf.read_text())
            rep.ok(f"{wf.name} parses")
        except yaml.YAMLError as e:
            rep.error("yaml", f"{wf.name} is not valid YAML: {e}", file=str(wf))


# ----------------------------------------------------------------------
# 4. T-SQL batch rules
# ----------------------------------------------------------------------
def check_tsql_batches(rep):
    print("\n[4] T-SQL batch separation")

    # CREATE SCHEMA must be alone in its batch. Without a GO after it, the
    # server rejects the whole script with "Incorrect syntax near 'CREATE'".
    # Same rule applies to CREATE VIEW / PROCEDURE / FUNCTION / TRIGGER.
    batch_only = re.compile(
        r"^\s*CREATE\s+(SCHEMA|VIEW|PROCEDURE|PROC|FUNCTION|TRIGGER)\b",
        re.IGNORECASE)

    sql_files = sorted(FABRIC_DIR.rglob("*.sql")) if FABRIC_DIR.is_dir() else []
    if not sql_files:
        rep.info("No .sql files found — skipping")
        return

    checked = 0
    for f in sql_files:
        lines = f.read_text(errors="replace").splitlines()
        for i, line in enumerate(lines):
            m = batch_only.match(line)
            if not m:
                continue
            checked += 1
            kw = m.group(1).upper()

            # Look backwards: only blanks/comments allowed between the previous
            # GO (or start of file) and this statement.
            for prev in reversed(lines[:i]):
                stripped = prev.strip()
                if not stripped or stripped.startswith("--"):
                    continue
                if stripped.upper() == "GO":
                    break
                rep.error(
                    "tsql",
                    f"{f.name}:{i+1} CREATE {kw} must be the first statement in "
                    f"its batch. Add 'GO' on the line before it.",
                    file=str(f))
                break

            # CREATE SCHEMA must also be the LAST statement in its batch —
            # this is the case that produces "Incorrect syntax near 'CREATE'".
            # For the other object types the body follows, so only SCHEMA is
            # checked forwards.
            if kw != "SCHEMA":
                continue
            for nxt in lines[i + 1:]:
                stripped = nxt.strip()
                if not stripped or stripped.startswith("--"):
                    continue
                if stripped.upper() == "GO":
                    break
                rep.error(
                    "tsql",
                    f"{f.name}:{i+1} CREATE SCHEMA must be alone in its batch, but "
                    f"another statement follows before any 'GO'. Add 'GO' after the "
                    f"CREATE SCHEMA line, or the server rejects the script with "
                    f'"Incorrect syntax near the keyword \'CREATE\'".',
                    file=str(f))
                break

    if checked:
        rep.ok(f"{checked} batch-scoped CREATE statement(s) checked")


# ----------------------------------------------------------------------
# 5. Parameterisation coverage — the important one
# ----------------------------------------------------------------------
def load_parameter_file(rep, target_env):
    """Returns (entries, ok). Emits errors for structural problems."""
    try:
        import yaml
    except ImportError:
        rep.warn("parameter", "PyYAML not installed — skipping parameter checks")
        return [], False

    p = CICD_DIR / "parameter.yml"
    if not p.is_file():
        rep.warn("parameter", "cicd/parameter.yml not present")
        return [], False

    try:
        doc = yaml.safe_load(p.read_text()) or {}
    except yaml.YAMLError as e:
        rep.error("parameter", f"parameter.yml is not valid YAML: {e}", file=str(p))
        return [], False

    entries = doc.get("find_replace", []) or []
    rep.info(f"parameter.yml: {len(entries)} active find_replace entr(ies)")

    ok = True
    for i, e in enumerate(entries, 1):
        fv = str(e.get("find_value", ""))
        if fv.startswith("<") and fv.endswith(">"):
            rep.error("parameter",
                      f"Entry {i} still contains an unfilled placeholder: {fv}",
                      file=str(p))
            ok = False
        rv = e.get("replace_value") or {}
        if target_env not in rv:
            rep.error("parameter",
                      f"Entry {i} has no '{target_env}' key in replace_value "
                      f"(found: {sorted(rv) or 'none'})",
                      file=str(p))
            ok = False
        if str(e.get("is_regex", "")).lower() == "true":
            try:
                compiled = re.compile(fv)
            except re.error as ex:
                rep.error("parameter", f"Entry {i} regex is invalid: {ex}", file=str(p))
                ok = False
                continue
            if compiled.groups != 1:
                rep.error("parameter",
                          f"Entry {i} regex has {compiled.groups} capture groups; "
                          f"fabric-cicd requires exactly 1.",
                          file=str(p))
                ok = False
    if ok and entries:
        rep.ok("parameter.yml entries are well-formed")
    return entries, ok


def entry_matches(entry, text):
    """Does this find_replace entry match the given literal text?"""
    fv = str(entry.get("find_value", ""))
    if str(entry.get("is_regex", "")).lower() == "true":
        try:
            return re.search(fv, text) is not None
        except re.error:
            return False
    return fv in text


def item_type_of(path):
    """Fabric item type for a file, read from the .platform of its item folder."""
    for parent in path.parents:
        platform = parent / ".platform"
        if platform.is_file():
            try:
                return json.loads(platform.read_text(errors="replace")) \
                    .get("metadata", {}).get("type")
            except json.JSONDecodeError:
                return None
    return None


def apply_entries(text, entries, target_env, item_type=None):
    """Reproduce what fabric-cicd's find_replace would leave behind.

    Asking 'is this GUID mentioned somewhere in parameter.yml' is not the same
    question as 'would this GUID survive deployment', and the two answers
    diverge exactly where it hurts: a regex rule spanning a whole URL mentions
    no GUID at all, and a rule filtered to another item_type mentions one it
    will never touch. Applying the rules and looking at the result is the only
    check that cannot drift away from what actually gets published.
    """
    for entry in entries:
        wanted = entry.get("item_type")
        if wanted:
            wanted = [wanted] if isinstance(wanted, str) else list(wanted)
            if item_type not in wanted:
                continue

        fv = str(entry.get("find_value", ""))
        rv = str((entry.get("replace_value") or {}).get(target_env, ""))

        if str(entry.get("is_regex", "")).lower() == "true":
            try:
                # fabric-cicd substitutes capture group 1, not the whole match,
                # so everything around the group is preserved.
                text = re.sub(fv,
                              lambda m: m.group(0).replace(m.group(1), rv, 1),
                              text)
            except (re.error, IndexError):
                continue
        else:
            text = text.replace(fv, rv)
    return text


def check_parameterisation_coverage(rep, entries, target_env):
    print("\n[5] Parameterisation coverage")

    if not FABRIC_DIR.is_dir():
        return

    # Any dev warehouse endpoint baked into an item definition must be covered
    # by a parameter.yml rule. If it is not, the item deploys successfully and
    # then reads from the wrong environment — no error, wrong data.
    definition_files = [
        p for p in FABRIC_DIR.rglob("*")
        if p.is_file() and p.suffix.lower() in {".tmdl", ".json", ".pbir", ".pbism", ".bim"}
    ]

    findings = 0
    for f in definition_files:
        text = f.read_text(errors="replace")
        name = f.relative_to(FABRIC_DIR)

        if not (WAREHOUSE_HOST_RE.search(text) or ONELAKE_URL_RE.search(text)):
            continue

        findings += 1
        deployed = apply_entries(text, entries, target_env, item_type_of(f))

        for host in set(WAREHOUSE_HOST_RE.findall(deployed)):
            rep.error(
                "coverage",
                f"{name} would still contain the hardcoded warehouse endpoint "
                f"{host} after the '{target_env}' rules are applied. The item "
                f"deploys without error and then reads from the dev warehouse.",
                file=str(f))

        # A OneLake URL that still holds raw GUIDs after substitution is the
        # DirectLake failure: rewriting the workspace but not the item id
        # leaves the model pointing into another workspace just as surely as
        # rewriting neither.
        for workspace_guid, item_guid in set(ONELAKE_URL_RE.findall(deployed)):
            rep.error(
                "coverage",
                f"{name} has a DirectLake OneLake URL that is still literal after "
                f"the '{target_env}' rules are applied: workspace {workspace_guid}, "
                f"item {item_guid}. The model deploys clean and then keeps reading "
                f"from the source workspace. Add or widen a find_replace rule so "
                f"both segments become $workspace / $items tokens.",
                file=str(f))

        if not WAREHOUSE_HOST_RE.search(deployed) and not ONELAKE_URL_RE.search(deployed):
            rep.ok(f"{name}: every store reference is rewritten for '{target_env}'")

    if findings == 0:
        rep.ok("No environment-specific data-store references found in item definitions")


# ----------------------------------------------------------------------
# 6. Notebooks must resolve their data store by name, not by GUID
# ----------------------------------------------------------------------
# A notebook that names its store resolves it in whatever workspace it runs in,
# so one file works in dev and test. A notebook carrying a GUID keeps pointing
# at the workspace it was authored in — it deploys clean and then reads or
# writes the wrong environment.
RESOLVE_BY_NAME = (
    "connect_to_artifact",      # warehouse, resolved via notebookutils
    "lakehouse.get(",           # lakehouse, resolved via notebookutils
)

# A notebook attaches its store by writing GUIDs into its METADATA header. Those
# GUIDs are environment-specific, so each one has to be either:
#   - the item's logicalId from its .platform, which Fabric maps to whichever
#     real item carries it in the target workspace (what nb_transform does), or
#   - covered by a find_replace rule in parameter.yml, which rewrites it at
#     publish time (what nb_lakehouse_schema does)
# Anything else deploys cleanly and then reads or writes the wrong workspace.
#
# There is no third option. Recording the store's *name* beside the id does not
# make the notebook portable on its own — nothing reads that name at deploy
# time — so a named-but-unmapped GUID is still an error here.
#
# The two store types are not symmetric: a lakehouse block also requires
# default_lakehouse_workspace_id, and omitting it fails the job outright with
# "LakehouseWorkspaceId is not a valid GUID:".
ATTACHED_GUID_RE = re.compile(
    r'"(default_(?:lakehouse|warehouse)(?:_workspace_id)?)"\s*:\s*"([0-9a-fA-F-]{36})"')


def repo_logical_ids():
    """logicalId -> item folder name, for every Fabric item in the repo."""
    ids = {}
    for platform in FABRIC_DIR.rglob(".platform"):
        try:
            doc = json.loads(platform.read_text(errors="replace"))
        except json.JSONDecodeError:
            continue
        logical_id = doc.get("config", {}).get("logicalId")
        if logical_id:
            ids[logical_id] = platform.parent.name
    return ids


def check_notebooks(rep, entries, target_env):
    print("\n[6] Notebook portability")

    if not FABRIC_DIR.is_dir():
        return

    # Both suffixes: a PySpark notebook exports as .py, a SQL one as .sql.
    nb_files = [p for p in FABRIC_DIR.rglob("*")
                if p.is_file() and p.suffix.lower() in {".py", ".sql"}
                and ".Notebook" in str(p)]
    if not nb_files:
        rep.info("No notebook source files found — skipping")
        return

    logical_ids = repo_logical_ids()

    for f in nb_files:
        text = f.read_text(errors="replace")
        name = f.relative_to(FABRIC_DIR)

        hosts = WAREHOUSE_HOST_RE.findall(text)
        if hosts:
            rep.error(
                "notebook",
                f"{name} hardcodes a warehouse endpoint ({hosts[0]}). Resolve the "
                f'warehouse by name instead — notebookutils.data.connect_to_artifact'
                f'("insurance_WH") — so the same file works in every workspace.',
                file=str(f))
            continue

        attached = ATTACHED_GUID_RE.findall(text)
        if attached:
            for key, guid in attached:
                owner = logical_ids.get(guid)
                if owner:
                    rep.ok(f"{name}: {key} is {owner}'s logicalId")
                elif apply_entries(guid, entries, target_env, "Notebook") != guid:
                    rep.ok(f"{name}: {key} is rewritten by parameter.yml")
                else:
                    rep.error(
                        "notebook",
                        f"{name} sets {key} to {guid}, which is neither an item's "
                        f"logicalId nor covered by a find_replace rule in "
                        f"parameter.yml for '{target_env}'. After deploy this "
                        f"notebook would still attach to the workspace it was "
                        f"authored in. Add a find_replace entry mapping {guid} to "
                        f"the right $workspace.id / $items.<Type>.<name>.id token.",
                        file=str(f))
            continue

        if any(marker in text for marker in RESOLVE_BY_NAME):
            rep.ok(f"{name} resolves its data store by name")
        else:
            rep.warn("notebook",
                     f"{name}: no attached store and no connect_to_artifact / "
                     f"lakehouse.get call — verify how it reaches its data store.",
                     file=str(f))


# ----------------------------------------------------------------------
# 7. Report items — byPath vs byConnection
# ----------------------------------------------------------------------
def check_reports(rep, entries):
    print("\n[7] Report connection type")

    if not FABRIC_DIR.is_dir():
        return
    reports = sorted(FABRIC_DIR.glob("*.Report"))
    if not reports:
        rep.info("No Report items found — skipping")
        return

    for r in reports:
        pbir = r / "definition.pbir"
        if not pbir.is_file():
            rep.warn("report", f"{r.name}: definition.pbir not found", file=str(r))
            continue
        try:
            ref = json.loads(pbir.read_text()).get("datasetReference", {})
        except json.JSONDecodeError as e:
            rep.error("report", f"{r.name}: definition.pbir is not valid JSON: {e}",
                      file=str(pbir))
            continue

        if ref.get("byPath"):
            rep.ok(f"{r.name} uses byPath — fabric-cicd re-points it automatically")
        elif ref.get("byConnection"):
            covered = any(entry_matches(e, pbir.read_text()) for e in entries)
            if covered:
                rep.ok(f"{r.name} uses byConnection and is covered by parameter.yml")
            else:
                rep.error(
                    "report",
                    f"{r.name} uses byConnection with no matching parameter.yml rule. "
                    f"It would keep pointing at the dev semantic model after deployment.",
                    file=str(pbir))
        else:
            rep.warn("report", f"{r.name}: unrecognised datasetReference shape",
                     file=str(pbir))


# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Static validation of the Fabric CI/CD repository")
    parser.add_argument("--target-env", default="test",
                        help="Environment key that parameter.yml must define")
    args = parser.parse_args()

    print("=" * 62)
    print(f"  Repository validation — target environment: {args.target_env}")
    print("=" * 62)

    rep = Report()

    check_structure(rep)
    check_python_syntax(rep)
    check_workflow_yaml(rep)
    check_tsql_batches(rep)
    entries, _ = load_parameter_file(rep, args.target_env)
    check_parameterisation_coverage(rep, entries, args.target_env)
    check_notebooks(rep, entries, args.target_env)
    check_reports(rep, entries)

    sys.exit(rep.summary())


if __name__ == "__main__":
    main()
