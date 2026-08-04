#!/usr/bin/env python3
# cicd/verify_semantic_model.py
#
# Post-deploy assertion: does the semantic model that is now IN the target
# workspace actually point at that workspace's warehouse?
#
# Everything upstream of this is a statement of intent. parameter.yml says what
# should be rewritten, validate_repo.py says the rules would fire, fabric-cicd
# says the publish succeeded — and all three said exactly that while the model
# sat in test reading from dev for weeks. None of them read back what was
# actually stored. This does.
#
# It downloads the deployed definition over the Fabric REST API, decodes
# expressions.tmdl, and fails the job unless every OneLake URL in it resolves
# inside the target workspace. A find_replace rule that stops matching, an
# $items token that silently fails to resolve, or someone re-editing the model
# in the browser and reintroducing dev GUIDs all surface here as a red build
# instead of as quietly wrong numbers in a report.
#
# Usage:
#   python cicd/verify_semantic_model.py \
#       --workspace-id "$TEST_WORKSPACE_ID" \
#       --model-name sales_semantic_model \
#       --expect-warehouse insurance_WH

import argparse
import base64
import os
import re
import sys
import time

import requests
from azure.identity import ClientSecretCredential

FABRIC_API = "https://api.fabric.microsoft.com/v1"

ONELAKE_URL_RE = re.compile(
    r"onelake\.dfs\.fabric\.microsoft\.com/"
    r"([0-9a-fA-F-]{36})/([0-9a-fA-F-]{36})")


def token() -> str:
    creds = {k: os.environ.get(f"AZURE_{k.upper()}", "").strip()
             for k in ("tenant_id", "client_id", "client_secret")}
    missing = [k for k, v in creds.items() if not v]
    if missing:
        raise SystemExit("Missing AZURE_" + ", AZURE_".join(m.upper() for m in missing))
    return ClientSecretCredential(
        tenant_id=creds["tenant_id"],
        client_id=creds["client_id"],
        client_secret=creds["client_secret"],
    ).get_token("https://api.fabric.microsoft.com/.default").token


def items(session: requests.Session, workspace_id: str) -> list[dict]:
    r = session.get(f"{FABRIC_API}/workspaces/{workspace_id}/items", timeout=60)
    r.raise_for_status()
    return r.json().get("value", [])


def definition_parts(session: requests.Session, workspace_id: str, item_id: str) -> list[dict]:
    """getDefinition, following the long-running-operation dance if needed."""
    r = session.post(
        f"{FABRIC_API}/workspaces/{workspace_id}/items/{item_id}/getDefinition",
        timeout=120)

    if r.status_code != 202:
        r.raise_for_status()
        return r.json().get("definition", {}).get("parts", [])

    # 202: the body is not ready. Poll the operation until it settles, then
    # fetch the result from its own endpoint.
    operation = r.headers.get("Location")
    if not operation:
        raise SystemExit("getDefinition returned 202 with no Location header")
    retry_after = int(r.headers.get("Retry-After", 5))
    deadline = time.monotonic() + 300

    while True:
        if time.monotonic() > deadline:
            raise SystemExit("Timed out waiting for getDefinition to complete")
        time.sleep(retry_after)

        poll = session.get(operation, timeout=120)
        poll.raise_for_status()
        status = poll.json().get("status")

        if status == "Succeeded":
            break
        if status == "Failed":
            raise SystemExit(f"getDefinition failed: {poll.text}")

    result = session.get(operation.rstrip("/") + "/result", timeout=120)
    result.raise_for_status()
    return result.json().get("definition", {}).get("parts", [])


def main():
    p = argparse.ArgumentParser(
        description="Verify a deployed semantic model points at its own workspace")
    p.add_argument("--workspace-id", required=True, help="Target workspace id")
    p.add_argument("--model-name", required=True, help="Semantic model display name")
    p.add_argument("--expect-warehouse", required=True,
                   help="Warehouse the model must read from, by display name")
    args = p.parse_args()

    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token()}"

    workspace_items = items(session, args.workspace_id)

    def find(item_type: str, name: str) -> dict:
        for i in workspace_items:
            if i.get("type") == item_type and i.get("displayName") == name:
                return i
        raise SystemExit(
            f"::error::No {item_type} named '{name}' in workspace {args.workspace_id}. "
            f"Found: {sorted(i.get('displayName', '?') for i in workspace_items)}")

    model = find("SemanticModel", args.model_name)
    warehouse = find("Warehouse", args.expect_warehouse)

    print(f"Workspace : {args.workspace_id}")
    print(f"Model     : {args.model_name} ({model['id']})")
    print(f"Warehouse : {args.expect_warehouse} ({warehouse['id']})")

    errors = []
    checked = 0

    for part in definition_parts(session, args.workspace_id, model["id"]):
        path = part.get("path", "")
        if not path.endswith(".tmdl"):
            continue
        try:
            body = base64.b64decode(part.get("payload", "")).decode("utf-8", "replace")
        except (ValueError, TypeError):
            continue

        for found_workspace, found_item in ONELAKE_URL_RE.findall(body):
            checked += 1
            where = f"{args.model_name}/{path}"

            if found_workspace.lower() != args.workspace_id.lower():
                errors.append(
                    f"{where}: OneLake URL points at workspace {found_workspace}, "
                    f"but this model lives in {args.workspace_id}. The find_replace "
                    f"rule for the workspace id did not take effect.")
            elif found_item.lower() != warehouse["id"].lower():
                errors.append(
                    f"{where}: OneLake URL points at item {found_item}, but "
                    f"'{args.expect_warehouse}' in this workspace is {warehouse['id']}. "
                    f"The warehouse id was not rewritten.")
            else:
                print(f"  OK: {where} -> {args.expect_warehouse} in this workspace")

    if checked == 0:
        print(f"::warning::No OneLake URL found in {args.model_name}. If this model "
              f"is no longer DirectLake-on-OneLake, point this check at whatever "
              f"connection replaced it rather than deleting it.")

    for e in errors:
        print(f"::error::{e}")

    if errors:
        print(f"\n{len(errors)} of {checked} connection(s) still point outside "
              f"this workspace.")
        sys.exit(1)

    print(f"\n{checked} connection(s) verified inside workspace {args.workspace_id}.")


if __name__ == "__main__":
    main()
