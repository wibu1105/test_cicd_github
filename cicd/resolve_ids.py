#!/usr/bin/env python3
# cicd/resolve_ids.py
#
# Generates the find_replace rules that repoint a notebook's attached lakehouse
# or warehouse at publish time, so no environment GUID is ever written down in
# cicd/parameter.yml.
#
# Why the find side is read from the repo and not from the Fabric API: a
# find_replace rule matches text inside the item definition file, so find_value
# has to be whatever GUID that file currently carries. Asking the API what the
# dev workspace holds right now answers a different question — if a lakehouse
# was recreated and Fabric has not re-synced the notebook yet, the API returns
# the new GUID and the rule silently matches nothing. Reading the file is the
# only way to be sure the rule fires. --verify closes the gap the other way:
# it asks the API whether the repo has gone stale, and says so loudly.
#
# GUIDs that are an item's logicalId are left alone. Fabric already resolves
# those per workspace — that is how nb_transform attaches insurance_WH.
#
# Usage (deploy pipelines, after staging parameter.yml into the git directory):
#   python cicd/resolve_ids.py --target-env test --parameter-file fabric/parameter.yml
#   python cicd/resolve_ids.py --target-env test --parameter-file fabric/parameter.yml \
#       --verify --workspace-id "$SOURCE_WORKSPACE_ID"

import argparse
import json
import os
import pathlib
import re
import sys

import yaml

NOTEBOOK_SUFFIXES = {".py", ".sql"}

# Fabric writes the attached store into the notebook's METADATA header.
ATTACHED_RE = re.compile(
    r'"(default_(?:lakehouse|warehouse))"\s*:\s*"([0-9a-fA-F-]{36})"')
NAME_RE = re.compile(
    r'"default_(?:lakehouse|warehouse)_name"\s*:\s*"([^"]+)"')
WORKSPACE_RE = re.compile(
    r'"default_(?:lakehouse|warehouse)_workspace_id"\s*:\s*"([0-9a-fA-F-]{36})"')

ITEM_TYPE = {"default_lakehouse": "Lakehouse", "default_warehouse": "Warehouse"}

FABRIC_API = "https://api.fabric.microsoft.com/v1"


def repo_logical_ids(git_dir: pathlib.Path) -> dict[str, str]:
    """logicalId -> item folder name, for every Fabric item in the repo."""
    ids = {}
    for platform in git_dir.rglob(".platform"):
        try:
            doc = json.loads(platform.read_text(errors="replace"))
        except json.JSONDecodeError:
            continue
        logical_id = doc.get("config", {}).get("logicalId")
        if logical_id:
            ids[logical_id] = platform.parent.name
    return ids


def notebook_files(git_dir: pathlib.Path) -> list[pathlib.Path]:
    return sorted(p for p in git_dir.rglob("*")
                  if p.is_file()
                  and p.suffix.lower() in NOTEBOOK_SUFFIXES
                  and ".Notebook" in str(p))


def discover(git_dir: pathlib.Path):
    """Returns (rules, problems).

    rules maps each environment-specific GUID found in a notebook header to the
    fabric-cicd token that should replace it, plus where it came from.
    """
    logical_ids = repo_logical_ids(git_dir)
    rules: dict[str, dict] = {}
    problems: list[str] = []

    for nb in notebook_files(git_dir):
        text = nb.read_text(errors="replace")
        where = nb.relative_to(git_dir)

        name_match = NAME_RE.search(text)
        store_name = name_match.group(1) if name_match else None

        for key, guid in ATTACHED_RE.findall(text):
            if guid in logical_ids:
                # logicalId — Fabric maps it to the right item per workspace.
                continue
            if not store_name:
                problems.append(
                    f"{where}: {key} is {guid} but there is no "
                    f"{key}_name next to it, so the item cannot be named. "
                    f"Re-attach the store in Fabric so it writes the name too.")
                continue
            rules[guid] = {
                "token": f"$items.{ITEM_TYPE[key]}.{store_name}.id",
                "source": f"{where} ({key} -> {store_name})",
            }

        for guid in WORKSPACE_RE.findall(text):
            rules[guid] = {
                "token": "$workspace.id",
                "source": f"{where} (workspace)",
            }

    return rules, problems


def verify_against_workspace(rules, workspace_id, git_dir):
    """Asks Fabric whether the GUIDs in the repo still exist in the source
    workspace under the names the repo claims. Catches a repo that has gone
    stale — a lakehouse recreated in Fabric but not yet re-synced to git."""
    # Imported here so the PR gate, which installs neither, can still run the
    # discovery half of this module.
    import requests
    from azure.identity import ClientSecretCredential

    creds = {k: os.environ.get(f"AZURE_{k.upper()}", "").strip()
             for k in ("tenant_id", "client_id", "client_secret")}
    missing = [k for k, v in creds.items() if not v]
    if missing:
        raise SystemExit("--verify needs AZURE_" + ", AZURE_".join(
            m.upper() for m in missing))

    token = ClientSecretCredential(
        tenant_id=creds["tenant_id"],
        client_id=creds["client_id"],
        client_secret=creds["client_secret"],
    ).get_token("https://api.fabric.microsoft.com/.default").token

    response = requests.get(
        f"{FABRIC_API}/workspaces/{workspace_id}/items",
        headers={"Authorization": f"Bearer {token}"}, timeout=60)
    response.raise_for_status()
    live = {i["id"]: i for i in response.json().get("value", [])}

    stale = []
    for guid, rule in sorted(rules.items()):
        if rule["token"] == "$workspace.id":
            if guid != workspace_id:
                stale.append(
                    f"  {guid} — the repo says this is the source workspace, but "
                    f"the deploy is reading {workspace_id}")
            continue
        if guid not in live:
            stale.append(
                f"  {guid} — {rule['source']}: no item with this id in workspace "
                f"{workspace_id}. It was probably recreated; re-sync the notebook "
                f"from Fabric so the header picks up the new id.")

    if stale:
        print("::error::The repo is out of sync with the source workspace:")
        for line in stale:
            print(line)
        sys.exit(1)
    print(f"  verified {len(rules)} id(s) against workspace {workspace_id}")


def main():
    p = argparse.ArgumentParser(
        description="Generate find_replace rules for attached-store GUIDs")
    p.add_argument("--target-env", required=True)
    p.add_argument("--git-directory", default="fabric")
    p.add_argument("--parameter-file", required=True,
                   help="parameter.yml to append the generated rules to")
    p.add_argument("--verify", action="store_true",
                   help="Also check the ids still exist in --workspace-id")
    p.add_argument("--workspace-id", default="",
                   help="Source workspace, required with --verify")
    args = p.parse_args()

    repo_root = pathlib.Path(__file__).resolve().parent.parent
    git_dir = repo_root / args.git_directory
    if not git_dir.is_dir():
        raise SystemExit(f"Repository directory not found: {git_dir}")

    rules, problems = discover(git_dir)
    for problem in problems:
        print(f"::error::{problem}")
    if problems:
        sys.exit(1)

    if not rules:
        print("No attached-store GUIDs need rewriting.")
        return

    print(f"Resolved {len(rules)} id(s) for '{args.target_env}':")
    for guid, rule in sorted(rules.items(), key=lambda kv: kv[1]["source"]):
        print(f"  {guid} -> {rule['token']}   [{rule['source']}]")

    if args.verify:
        if not args.workspace_id:
            raise SystemExit("--verify requires --workspace-id")
        verify_against_workspace(rules, args.workspace_id, git_dir)

    parameter_file = pathlib.Path(args.parameter_file)
    doc = {}
    if parameter_file.is_file():
        doc = yaml.safe_load(parameter_file.read_text()) or {}

    generated = [
        {
            "find_value": guid,
            "replace_value": {args.target_env: rule["token"]},
            "item_type": "Notebook",
        }
        for guid, rule in sorted(rules.items())
    ]
    doc.setdefault("find_replace", []).extend(generated)
    parameter_file.write_text(yaml.safe_dump(doc, sort_keys=False))
    print(f"Appended {len(generated)} rule(s) to {parameter_file}")


if __name__ == "__main__":
    main()
