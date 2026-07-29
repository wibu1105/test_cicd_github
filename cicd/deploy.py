# cicd/deploy.py

import argparse
import json
import os
from pathlib import Path

from azure.identity import ClientSecretCredential
from fabric_cicd import FabricWorkspace, publish_all_items, unpublish_all_orphan_items


def main():
    parser = argparse.ArgumentParser(description="Deploy Fabric items to target workspace")

    parser.add_argument("--tenant-id",       required=True, help="Azure Entra tenant ID")
    parser.add_argument("--client-id",       required=True, help="Service Principal client ID")
    parser.add_argument("--client-secret",   required=True, help="Service Principal client secret")
    parser.add_argument("--target-env",      required=True, help="Target environment name (e.g. test)")
    parser.add_argument("--workspace-name",  required=True, help="Target Fabric workspace name")
    parser.add_argument("--git-directory",   required=True, help="Folder containing Fabric items (e.g. fabric)")
    parser.add_argument(
        "--items-in-scope",
        required=False,
        default='["Notebook","DataPipeline","Warehouse","SemanticModel","Report"]',
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

    credential = ClientSecretCredential(
        tenant_id=args.tenant_id,
        client_id=args.client_id,
        client_secret=args.client_secret,
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
