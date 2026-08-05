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


def covered_at(entries, text, start, end):
    """Does some find_replace rule rewrite exactly the text[start:end] span?

    entry_matches only answers "does this rule match the file somewhere", which
    is too weak once the same GUID appears twice: a rule covering the first
    occurrence says nothing about the second. fabric-cicd only ever substitutes
    capture group 1, so a span is covered only when some rule's group 1 encloses
    it.
    """
    for entry in entries:
        fv = str(entry.get("find_value", ""))
        if not fv:
            continue
        if str(entry.get("is_regex", "")).lower() == "true":
            try:
                matches = list(re.finditer(fv, text))
            except re.error:
                continue
            for m in matches:
                try:
                    g_start, g_end = m.span(1)
                except IndexError:
                    continue
                if g_start != -1 and g_start <= start and g_end >= end:
                    return True
        else:
            idx = text.find(fv)
            while idx != -1:
                if idx <= start and idx + len(fv) >= end:
                    return True
                idx = text.find(fv, idx + 1)
    return False


# A Direct Lake model reads OneLake directly, so it carries no SQL endpoint
# hostname for WAREHOUSE_HOST_RE to find. Both path segments are per-workspace.
ONELAKE_PATH_RE = re.compile(
    r"onelake\.dfs\.fabric\.microsoft\.com/([0-9a-fA-F-]{36})/([0-9a-fA-F-]{36})")


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
        for host in set(WAREHOUSE_HOST_RE.findall(text)):
            findings += 1
            covered = any(entry_matches(e, text) for e in entries)
            if covered:
                rep.ok(f"{f.relative_to(FABRIC_DIR)}: endpoint covered by a parameter.yml rule")
            else:
                rep.error(
                    "coverage",
                    f"{f.relative_to(FABRIC_DIR)} contains a hardcoded warehouse endpoint "
                    f"({host}) with no matching find_replace rule for '{target_env}'. "
                    f"After deployment this item would still read from the dev warehouse.",
                    file=str(f))

        # Direct Lake models never mention a SQL endpoint, so the hostname scan
        # above cannot see them. sales_semantic_model is one: its source is a
        # OneLake path carrying the dev workspace id and the dev warehouse id.
        for m in ONELAKE_PATH_RE.finditer(text):
            for label, group in (("workspace", 1), ("item", 2)):
                findings += 1
                g_start, g_end = m.span(group)
                if covered_at(entries, text, g_start, g_end):
                    rep.ok(f"{f.relative_to(FABRIC_DIR)}: OneLake {label} id "
                           f"covered by a parameter.yml rule")
                else:
                    rep.error(
                        "coverage",
                        f"{f.relative_to(FABRIC_DIR)} pins {m.group(group)} as the "
                        f"{label} id of a OneLake path, with no find_replace rule "
                        f"covering that occurrence for '{target_env}'. After "
                        f"deployment this item would still read from the dev "
                        f"workspace.",
                        file=str(f))

    if findings == 0:
        rep.ok("No hardcoded warehouse endpoints or OneLake paths found in item definitions")


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
# The two store types are not symmetric: a lakehouse block also requires
# default_lakehouse_workspace_id, and omitting it fails the job outright with
# "LakehouseWorkspaceId is not a valid GUID:".
ATTACHED_GUID_RE = re.compile(
    r'"(default_(?:lakehouse|warehouse)(?:_workspace_id)?)"\s*:\s*"([0-9a-fA-F-]{36})"')
# Fabric repeats the store id a second time inside known_lakehouses /
# known_warehouses, under a bare "id" key that ATTACHED_GUID_RE cannot see.
# Within a notebook's metadata this key occurs nowhere else, so matching it
# directly needs no block parsing and works for both "# META" and "-- META".
KNOWN_STORE_ID_RE = re.compile(r'"id"\s*:\s*"([0-9a-fA-F-]{36})"')


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

        # Rewriting default_lakehouse but not its twin inside known_lakehouses
        # leaves the notebook attached to BOTH stores — the target one and the
        # one it was authored against. Fabric shows that as the same store name
        # twice in the lineage view, in two different workspaces.
        for m in KNOWN_STORE_ID_RE.finditer(text):
            guid = m.group(1)
            g_start, g_end = m.span(1)
            owner = logical_ids.get(guid)
            if owner:
                rep.ok(f"{name}: known store {guid} is {owner}'s logicalId")
            elif covered_at(entries, text, g_start, g_end):
                rep.ok(f"{name}: known store {guid} is rewritten by parameter.yml")
            else:
                rep.error(
                    "notebook",
                    f"{name} repeats {guid} under known_lakehouses/known_warehouses "
                    f"with no find_replace rule covering that occurrence for "
                    f"'{target_env}', and it is not an item's logicalId. After "
                    f"deploy the notebook would stay attached to the workspace it "
                    f"was authored in, alongside the target one.",
                    file=str(f))

        attached = list(ATTACHED_GUID_RE.finditer(text))
        if attached:
            # Exactly two things neutralise an environment-specific GUID here,
            # and both are checked against this occurrence rather than the file
            # as a whole. Nothing resolves "by name" at deploy time any more —
            # that was resolve_ids.py, which no longer exists.
            for m in attached:
                key, guid = m.group(1), m.group(2)
                g_start, g_end = m.span(2)
                owner = logical_ids.get(guid)
                if owner:
                    rep.ok(f"{name}: {key} is {owner}'s logicalId")
                elif covered_at(entries, text, g_start, g_end):
                    rep.ok(f"{name}: {key} is rewritten by parameter.yml")
                else:
                    rep.error(
                        "notebook",
                        f"{name} sets {key} to {guid}, which is neither an item's "
                        f"logicalId nor covered by a find_replace rule for "
                        f"'{target_env}'. After deploy this notebook would still "
                        f"attach to the workspace it was authored in.",
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
# 8. Every find_replace rule must actually hit something
# ----------------------------------------------------------------------
# The failure mode this exists for: a rule that matches nothing is silent.
# fabric-cicd does not warn, the deploy goes green, and the item ships with its
# dev GUIDs intact — you only find out by opening the lineage view in Fabric.
#
# Both bugs that produced this check were of exactly that shape: rules written
# against Sql.Database when the semantic model is Direct Lake over OneLake, and
# rules prefixed "# META" aimed at a SQL notebook that writes "-- META".
#
# Only find_replace is covered. key_value_replace rules are JSONPath against
# specific items and are not reachable by text search.
def check_rule_effectiveness(rep, entries):
    print("\n[8] find_replace rules match at least one file")

    if not FABRIC_DIR.is_dir():
        return
    if not entries:
        rep.info("No find_replace entries — skipping")
        return

    for i, entry in enumerate(entries, 1):
        fv = str(entry.get("find_value", ""))
        if not fv:
            continue
        is_regex = str(entry.get("is_regex", "")).lower() == "true"
        item_type = entry.get("item_type")

        # Fabric item folders are named "<display name>.<ItemType>", and a rule
        # with an item_type only ever runs against items of that type. A rule can
        # be a perfectly good regex and still be dead because it is pointed at
        # the wrong one.
        if item_type:
            item_dirs = sorted(FABRIC_DIR.glob(f"*.{item_type}"))
            if not item_dirs:
                rep.warn("parameter",
                         f"Entry {i} targets item_type '{item_type}', but the repo "
                         f"contains no item of that type — the rule cannot fire.")
                continue
            candidates = [p for d in item_dirs for p in d.rglob("*") if p.is_file()]
        else:
            candidates = [p for p in FABRIC_DIR.rglob("*") if p.is_file()]

        hits = []
        for p in candidates:
            text = p.read_text(errors="replace")
            try:
                matched = (re.search(fv, text) is not None) if is_regex else (fv in text)
            except re.error:
                matched = False  # already reported by load_parameter_file
            if matched:
                hits.append(p.relative_to(FABRIC_DIR))

        label = f"Entry {i}" + (f" ({item_type})" if item_type else "")
        if hits:
            rep.ok(f"{label} matches {', '.join(str(h) for h in hits)}")
        else:
            rep.error(
                "parameter",
                f"{label} matches no file under any *.{item_type or '<any type>'} "
                f"item. find_value: {fv!r}. A rule that matches nothing is applied "
                f"silently and the item deploys with its source-workspace ids "
                f"intact — check the connector, the metadata comment prefix "
                f"('# META' for .py notebooks, '-- META' for .sql), and the "
                f"item_type.")


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
    check_rule_effectiveness(rep, entries)

    sys.exit(rep.summary())


if __name__ == "__main__":
    main()
