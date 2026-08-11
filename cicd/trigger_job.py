#!/usr/bin/env python3
# cicd/trigger_job.py
#
# Runs a Fabric item job (pipeline or notebook) via the REST API. Used by the
# lakehouse pipeline only — the warehouse backfills through cicd/run_sql.py.
#
# jobType is the awkward part of this API: it is required, not enumerated in
# the reference page, and the obvious-looking "DefaultJob" is rejected for
# these item types. The values below are the ones that work.

import argparse
import os
import sys
import time

import requests
from azure.identity import ClientSecretCredential
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API = "https://api.fabric.microsoft.com/v1"
JOB_TYPES = {"DataPipeline": "Pipeline", "Notebook": "RunNotebook"}
FAILED = {"Failed", "Cancelled", "Deduped"}


def build_session() -> requests.Session:
    """Retries transient failures (429/5xx, connection resets) with backoff.
    A CI run that fails because Fabric hiccupped for one request is a worse
    outcome than a few seconds of extra wait."""
    session = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def main():
    p = argparse.ArgumentParser(description="Trigger a Fabric item job")
    p.add_argument("--tenant-id", default=os.environ.get("AZURE_TENANT_ID", ""))
    p.add_argument("--client-id", default=os.environ.get("AZURE_CLIENT_ID", ""))
    p.add_argument("--client-secret", default=os.environ.get("AZURE_CLIENT_SECRET", ""))
    p.add_argument("--workspace-id", required=True)
    p.add_argument("--item-name", required=True)
    p.add_argument("--item-type", required=True, choices=sorted(JOB_TYPES))
    p.add_argument("--wait", action="store_true")
    p.add_argument("--timeout-minutes", type=int, default=60)
    p.add_argument("--skip-if-missing", action="store_true",
                   help="Exit 0 instead of failing when the item does not exist yet")
    args = p.parse_args()

    creds = {k: (getattr(args, k) or "").strip()
             for k in ("tenant_id", "client_id", "client_secret")}
    missing = [k for k, v in creds.items() if not v]
    if missing:
        raise SystemExit("Missing credentials: " + ", ".join(missing))

    token = ClientSecretCredential(
        tenant_id=creds["tenant_id"],
        client_id=creds["client_id"],
        client_secret=creds["client_secret"],
    ).get_token("https://api.fabric.microsoft.com/.default").token
    headers = {"Authorization": f"Bearer {token}"}
    session = build_session()

    items = session.get(
        f"{API}/workspaces/{args.workspace_id}/items",
        headers=headers, params={"type": args.item_type}, timeout=60,
    )
    items.raise_for_status()
    match = next((i for i in items.json().get("value", [])
                  if i.get("displayName") == args.item_name), None)
    if not match:
        message = f"No {args.item_type} named '{args.item_name}' in workspace {args.workspace_id}"
        if args.skip_if_missing:
            print(f"::notice::{message}. Skipped.")
            return
        raise SystemExit(message)

    job_type = JOB_TYPES[args.item_type]
    print(f"Starting {args.item_type} '{args.item_name}' (jobType={job_type})")
    started = session.post(
        f"{API}/workspaces/{args.workspace_id}/items/{match['id']}/jobs/instances",
        headers=headers, params={"jobType": job_type}, json={}, timeout=60,
    )
    if started.status_code not in (200, 201, 202):
        raise SystemExit(f"Failed to start job (HTTP {started.status_code}): {started.text}")

    # 202 Accepted carries the job instance URL in the Location header; there is
    # no body to fall back on, so without it there is nothing to poll.
    instance = started.headers.get("Location", "")
    if not args.wait or not instance:
        print("Job started." if instance else "::warning::No Location header — cannot poll.")
        return

    deadline = time.time() + args.timeout_minutes * 60
    last = ""
    while time.time() < deadline:
        poll = session.get(instance, headers=headers, timeout=60)
        poll.raise_for_status()
        body = poll.json()
        status = body.get("status", "Unknown")
        if status != last:
            print(f"  {status}")
            last = status
        if status == "Completed":
            return
        if status in FAILED:
            reason = (body.get("failureReason") or {})
            sys.exit(f"::error::Job {status}: {reason.get('message', 'no reason returned')}")
        time.sleep(20)

    sys.exit(f"::error::Job still {last or 'unknown'} after {args.timeout_minutes} minutes")


if __name__ == "__main__":
    main()
