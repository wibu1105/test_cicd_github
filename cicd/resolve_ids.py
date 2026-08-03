#!/usr/bin/env python3
# cicd/resolve_ids.py
#
# Generates the find_replace rules that repoint a notebook's attached lakehouse
# or warehouse at publish time, so no environment GUID is ever written down in
# cicd/parameter.yml.
#
# Everything comes from the Fabric REST API at runtime: it lists the items in
# the source workspace and, for every lakehouse and warehouse, emits a rule
# mapping that item's id to $items.<Type>.<name>.id. The source workspace id
# itself maps to $workspace.id. Recreate a store as often as you like — as long
# as its name holds, the next run picks up the new id on its own.
#
# Rules whose find_value matches nothing are harmless: fabric-cicd only applies
# a rule where the text actually occurs, so listing a store no notebook attaches
# to costs nothing.
#
# Usage (deploy pipeline, after parameter.yml is staged into the git directory):
#   python cicd/resolve_ids.py --target-env test \
#       --source-workspace-id "$SOURCE_WORKSPACE_ID" \
#       --parameter-file fabric/parameter.yml

import argparse
import os
import pathlib

import requests
import yaml
from azure.identity import ClientSecretCredential

FABRIC_API = "https://api.fabric.microsoft.com/v1"

# Item types whose ids get baked into a notebook's METADATA header when it is
# attached to them.
ATTACHABLE = ("Lakehouse", "Warehouse")


def fabric_token() -> str:
    creds = {k: os.environ.get(f"AZURE_{k.upper()}", "").strip()
             for k in ("tenant_id", "client_id", "client_secret")}
    missing = [k for k, v in creds.items() if not v]
    if missing:
        raise SystemExit("Missing AZURE_" + ", AZURE_".join(
            m.upper() for m in missing))

    return ClientSecretCredential(
        tenant_id=creds["tenant_id"],
        client_id=creds["client_id"],
        client_secret=creds["client_secret"],
    ).get_token("https://api.fabric.microsoft.com/.default").token


def source_items(token: str, workspace_id: str) -> list[dict]:
    """Every attachable item in the source workspace, newest state."""
    response = requests.get(
        f"{FABRIC_API}/workspaces/{workspace_id}/items",
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    response.raise_for_status()
    return [i for i in response.json().get("value", [])
            if i.get("type") in ATTACHABLE]


def build_rules(items: list[dict], workspace_id: str, target_env: str) -> list[dict]:
    rules = [
        {
            "find_value": item["id"],
            "replace_value": {target_env: f"$items.{item['type']}.{item['displayName']}.id"},
            "item_type": "Notebook",
        }
        for item in sorted(items, key=lambda i: i["displayName"])
    ]
    # A lakehouse attachment also carries the workspace it lives in, and Fabric
    # rejects the notebook outright if that field is empty.
    rules.append({
        "find_value": workspace_id,
        "replace_value": {target_env: "$workspace.id"},
        "item_type": "Notebook",
    })
    return rules


def main():
    p = argparse.ArgumentParser(
        description="Resolve attached-store ids from the Fabric API into parameter.yml")
    p.add_argument("--target-env", required=True)
    p.add_argument("--source-workspace-id", required=True,
                   help="Workspace the notebooks were authored in (dev)")
    p.add_argument("--parameter-file", required=True,
                   help="parameter.yml to append the generated rules to")
    args = p.parse_args()

    items = source_items(fabric_token(), args.source_workspace_id)
    if not items:
        print(f"::warning::No {' or '.join(ATTACHABLE)} items in workspace "
              f"{args.source_workspace_id} — nothing to resolve.")

    rules = build_rules(items, args.source_workspace_id, args.target_env)

    print(f"Resolved {len(rules)} id(s) from workspace {args.source_workspace_id}:")
    for rule in rules:
        print(f"  {rule['find_value']} -> {rule['replace_value'][args.target_env]}")

    parameter_file = pathlib.Path(args.parameter_file)
    doc = yaml.safe_load(parameter_file.read_text()) if parameter_file.is_file() else {}
    doc = doc or {}
    doc.setdefault("find_replace", []).extend(rules)
    parameter_file.write_text(yaml.safe_dump(doc, sort_keys=False))
    print(f"Appended {len(rules)} rule(s) to {parameter_file}")


if __name__ == "__main__":
    main()
