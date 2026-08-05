# cicd/deploy.py

import argparse
import json
import os
from pathlib import Path

from azure.identity import ClientSecretCredential
from fabric_cicd import FabricWorkspace, publish_all_items, unpublish_all_orphan_items


def main():
    parser = argparse.ArgumentParser(description="Deploy Fabric items to target workspace")

    # Credentials are read from the environment by default. Passing them as
    # command-line arguments works too, but env vars avoid two problems:
    # a stray newline in a secret breaking shell line-continuation, and
    # secrets appearing in the process list.
    parser.add_argument("--tenant-id",       required=False, default=os.environ.get("AZURE_TENANT_ID", ""),     help="Azure Entra tenant ID")
    parser.add_argument("--client-id",       required=False, default=os.environ.get("AZURE_CLIENT_ID", ""),     help="Service Principal client ID")
    parser.add_argument("--client-secret",   required=False, default=os.environ.get("AZURE_CLIENT_SECRET", ""), help="Service Principal client secret")
    parser.add_argument("--target-env",      required=True, help="Target environment name (e.g. test)")
    parser.add_argument("--workspace-name",  required=True, help="Target Fabric workspace name")
    parser.add_argument("--git-directory",   required=True, help="Folder containing Fabric items (e.g. fabric)")
    parser.add_argument(
        "--items-in-scope",
        required=False,
        default='["Lakehouse","Warehouse","Notebook","DataPipeline","SemanticModel","Report"]',
        help="JSON array of Fabric item types to deploy"
    )
    parser.add_argument(
        "--unpublish-orphans",
        required=False,
        default="true",
        help="'true' to delete workspace items no longer present in the repo. "
             "Set to 'false' during first runs or incident recovery."
    )

    args = parser.parse_args()

    items_in_scope = json.loads(args.items_in_scope)

    tenant_id     = (args.tenant_id or "").strip()
    client_id     = (args.client_id or "").strip()
    client_secret = (args.client_secret or "").strip()

    missing = [n for n, v in [
        ("tenant-id / AZURE_TENANT_ID", tenant_id),
        ("client-id / AZURE_CLIENT_ID", client_id),
        ("client-secret / AZURE_CLIENT_SECRET", client_secret),
    ] if not v]
    if missing:
        raise SystemExit(
            "Missing credential values: " + ", ".join(missing) + ".\n"
            "Set them as repository secrets in THIS repository and confirm the "
            "workflow passes them through to this script."
        )

    print(f"Credential lengths : tenant={len(tenant_id)} client={len(client_id)} secret={len(client_secret)}")

    credential = ClientSecretCredential(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
    )

    repo_root = Path(__file__).resolve().parent.parent
    repository_directory = str(repo_root / args.git_directory)

    # Fail early and clearly rather than letting fabric-cicd deploy nothing.
    if not os.path.isdir(repository_directory):
        raise SystemExit(
            f"Repository directory not found: {repository_directory}\n"
            f"Check the GIT_DIRECTORY variable — it should be the folder name "
            f"holding the Fabric items (e.g. 'fabric'), not a workspace name."
        )

    print(f"Repository dir     : {repository_directory}")
    print(f"Items found        : {sorted(os.listdir(repository_directory))}")
    print(f"Target environment : {args.target_env}")
    print(f"Target workspace   : {args.workspace_name}")
    print(f"Items in scope     : {items_in_scope}")
    print(f"Unpublish orphans  : {args.unpublish_orphans}")

    workspace = FabricWorkspace(
        workspace_name=args.workspace_name,
        environment=args.target_env,
        repository_directory=repository_directory,
        item_type_in_scope=items_in_scope,
        token_credential=credential,
    )

    publish_all_items(workspace)

    # unpublish_all_orphan_items DELETES items from the target workspace that
    # are not present in the repo. It is what keeps the workspace in sync, and
    # it is also what will empty a workspace if --git-directory is wrong.
    if args.unpublish_orphans.strip().lower() == "true":
        print("Unpublishing orphan items...")
        unpublish_all_orphan_items(workspace)
    else:
        print("Skipping unpublish of orphan items (--unpublish-orphans=false)")


if __name__ == "__main__":
    main()
