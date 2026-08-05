#!/usr/bin/env python3
# cicd/resolve_ids.py
#
# Resolves $items.Warehouse.<name>.$id and $items.Lakehouse.<name>.$id in the
# STAGED parameter.yml into real GUIDs, read from the target workspace over the
# Fabric REST API.
#
# WHY THIS EXISTS
# ---------------
# fabric-cicd resolves a $items.<Type>.<name>.$<attr> variable only when <Type>
# is inside --items-in-scope for that run. Existing in the workspace is not
# enough: a run scoped to ["Warehouse"] still fails with
#
#     Attribute value not found for Lakehouse 'test_LH'
#
# even though test_LH is sitting right there. That coupling forced Warehouse and
# Lakehouse into deploy-to-fabric.yml's scope purely so two GUIDs could be read.
# This script breaks it — it asks Fabric directly, so deploy-to-fabric.yml
# publishes no store item at all, and schema stays owned by deploy-warehouse.yml
# and deploy-lakehouse.yml.
#
# WHAT IT DOES NOT TOUCH
# ----------------------
# $workspace.$id is left alone. fabric-cicd resolves that from the workspace it
# is publishing into, with nothing required in scope.
#
# cicd/parameter.yml is never modified — only the copy staged into the git
# directory on the runner, which is gitignored.
#
# Usage:
#   python cicd/resolve_ids.py \
#       --workspace-id "$TEST_WORKSPACE_ID" \
#       --parameter-file fabric/parameter.yml

import argparse
import os
import pathlib
import re

import requests
from azure.identity import ClientSecretCredential

FABRIC_API = "https://api.fabric.microsoft.com/v1"

# Item types this script resolves. Everything else stays a dynamic variable,
# because its type remains inside --items-in-scope where fabric-cicd can see it.
RESOLVABLE = ("Warehouse", "Lakehouse")

# Non-greedy on the name so it stops at the first ".$id", and a display name
# containing a dot still resolves.
TOKEN_RE = re.compile(
    r"\$items\.(" + "|".join(RESOLVABLE) + r")\.(.+?)\.\$id")


def fabric_token() -> str:
    creds = {k: os.environ.get(f"AZURE_{k.upper()}", "").strip()
             for k in ("tenant_id", "client_id", "client_secret")}
    missing = [f"AZURE_{k.upper()}" for k, v in creds.items() if not v]
    if missing:
        raise SystemExit(f"::error::Missing credentials: {', '.join(missing)}")

    return ClientSecretCredential(
        tenant_id=creds["tenant_id"],
        client_id=creds["client_id"],
        client_secret=creds["client_secret"],
    ).get_token("https://api.fabric.microsoft.com/.default").token


def _paged(token: str, url: str) -> list[dict]:
    """Every page of a Fabric list endpoint.

    Without this a workspace that grows past one page starts reporting items as
    missing, which would read as "the warehouse is gone" rather than "keep
    reading".
    """
    out = []
    headers = {"Authorization": f"Bearer {token}"}
    while url:
        response = requests.get(url, headers=headers, timeout=60)
        response.raise_for_status()
        body = response.json()
        out.extend(body.get("value", []))
        url = body.get("continuationUri")
    return out


def resolve_workspace_id(token: str, name: str) -> str:
    for workspace in _paged(token, f"{FABRIC_API}/workspaces"):
        if workspace.get("displayName") == name:
            return workspace["id"]
    raise SystemExit(
        f"::error::Workspace '{name}' not found, or the Deploy SP has no access "
        f"to it. Add the SP to the workspace, or pass --workspace-id instead.")


def main():
    parser = argparse.ArgumentParser(
        description="Resolve store ids from the Fabric API into a staged parameter.yml")
    parser.add_argument("--workspace-id", default="",
                        help="Target workspace id. Preferred — skips a lookup.")
    parser.add_argument("--workspace-name", default="",
                        help="Target workspace display name, if the id is unknown.")
    parser.add_argument("--parameter-file", required=True,
                        help="The STAGED parameter.yml, e.g. fabric/parameter.yml")
    args = parser.parse_args()

    path = pathlib.Path(args.parameter_file)
    if not path.is_file():
        raise SystemExit(f"::error::Parameter file not found: {path}")

    text = path.read_text()
    wanted = sorted(set(TOKEN_RE.findall(text)))
    if not wanted:
        print(f"No {' or '.join(RESOLVABLE)} tokens in {path} — nothing to resolve.")
        return

    token = fabric_token()

    workspace_id = args.workspace_id.strip()
    if not workspace_id:
        if not args.workspace_name.strip():
            raise SystemExit("::error::Pass --workspace-id or --workspace-name")
        workspace_id = resolve_workspace_id(token, args.workspace_name.strip())
    print(f"Target workspace : {workspace_id}")

    items = _paged(token, f"{FABRIC_API}/workspaces/{workspace_id}/items")
    index = {(i.get("type"), i.get("displayName")): i.get("id") for i in items}

    missing = []
    for item_type, name in wanted:
        item_id = index.get((item_type, name))
        if not item_id:
            missing.append(f"{item_type} '{name}'")
            continue
        needle = f"$items.{item_type}.{name}.$id"
        text = text.replace(needle, item_id)
        print(f"  {needle} -> {item_id}")

    # Failing here beats letting the token through: fabric-cicd would write the
    # literal string "$items.Warehouse.insurance_WH.$id" into the deployed item,
    # which deploys green and then reads nothing.
    if missing:
        present = sorted(f"{t}/{n}" for t, n in index if t in RESOLVABLE)
        raise SystemExit(
            f"::error::Not found in workspace {workspace_id}: {', '.join(missing)}. "
            f"Present: {present or 'none'}. The store items are created by "
            f"deploy-warehouse.yml and deploy-lakehouse.yml — run those first.")

    path.write_text(text)
    print(f"Rewrote {path} with {len(wanted)} resolved id(s)")


if __name__ == "__main__":
    main()
