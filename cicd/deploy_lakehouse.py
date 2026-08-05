#!/usr/bin/env python3
# cicd/deploy_lakehouse.py
#
# fabric-cicd scopes a publish by item type, not by item, so deploying
# ["Lakehouse","Notebook","DataPipeline"] against fabric/ would also republish
# the warehouse-side nb_transform and pl_silver. This copies just the Lakehouse
# items and whatever references them into a staging folder and publishes that.
#
# Orphan unpublish is never run here: the staging folder is a subset of the
# repo, so every other workspace item would look like an orphan.

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

from azure.identity import ClientSecretCredential
from fabric_cicd import FabricWorkspace, publish_all_items

ITEM_TYPES = ["Lakehouse", "Notebook", "DataPipeline"]
LINKABLE = (".Notebook", ".DataPipeline")


def platform(item: Path) -> dict:
    f = item / ".platform"
    if not f.is_file():
        return {}
    try:
        return json.loads(f.read_text(errors="replace"))
    except json.JSONDecodeError:
        return {}


def identifiers(lakehouses: list[Path]) -> set[str]:
    """Display name and logicalId of each lakehouse — how a notebook or
    pipeline definition refers to the lakehouse it is attached to."""
    out = set()
    for lh in lakehouses:
        meta = platform(lh)
        out.add(meta.get("metadata", {}).get("displayName") or lh.name.rsplit(".", 1)[0])
        out.add(meta.get("config", {}).get("logicalId", ""))
    return {i for i in out if i}


def references(item: Path, ids: set[str]) -> bool:
    return any(
        f.is_file() and any(i in f.read_text(errors="replace") for i in ids)
        for f in item.rglob("*")
    )


def main():
    p = argparse.ArgumentParser(description="Deploy Lakehouse items and what binds to them")
    p.add_argument("--tenant-id", default=os.environ.get("AZURE_TENANT_ID", ""))
    p.add_argument("--client-id", default=os.environ.get("AZURE_CLIENT_ID", ""))
    p.add_argument("--client-secret", default=os.environ.get("AZURE_CLIENT_SECRET", ""))
    p.add_argument("--target-env", required=True)
    p.add_argument("--workspace-name", required=True)
    p.add_argument("--git-directory", default="fabric")
    p.add_argument("--include-items", default="", help="Extra item names, comma-separated")
    args = p.parse_args()

    creds = {k: (getattr(args, k) or "").strip()
             for k in ("tenant_id", "client_id", "client_secret")}
    missing = [k for k, v in creds.items() if not v]
    if missing:
        raise SystemExit("Missing credentials: " + ", ".join(missing))

    git_dir = Path(__file__).resolve().parent.parent / args.git_directory
    if not git_dir.is_dir():
        raise SystemExit(f"Repository directory not found: {git_dir}")

    lakehouses = sorted(d for d in git_dir.iterdir()
                        if d.is_dir() and d.name.endswith(".Lakehouse"))
    if not lakehouses:
        print("::notice::No *.Lakehouse item in the repo yet — nothing to deploy.")
        return

    ids = identifiers(lakehouses)
    extra = {n.strip() for n in args.include_items.split(",") if n.strip()}
    items = lakehouses + [
        d for d in sorted(git_dir.iterdir())
        if d.is_dir() and d.name.endswith(LINKABLE)
        and (d.name in extra or references(d, ids))
    ]

    staging = Path(tempfile.mkdtemp(prefix="fabric-lakehouse-")) / "items"
    staging.mkdir(parents=True)
    try:
        for item in items:
            shutil.copytree(item, staging / item.name)
        if (git_dir / "parameter.yml").is_file():
            shutil.copy2(git_dir / "parameter.yml", staging / "parameter.yml")

        print(f"Deploying {[i.name for i in items]} to {args.workspace_name}")

        publish_all_items(FabricWorkspace(
            workspace_name=args.workspace_name,
            environment=args.target_env,
            repository_directory=str(staging),
            item_type_in_scope=ITEM_TYPES,
            token_credential=ClientSecretCredential(
                tenant_id=creds["tenant_id"],
                client_id=creds["client_id"],
                client_secret=creds["client_secret"],
            ),
        ))
    finally:
        shutil.rmtree(staging.parent, ignore_errors=True)


if __name__ == "__main__":
    main()
