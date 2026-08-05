#!/usr/bin/env python3
# cicd/run_sql.py
#
# Post-publish step of the warehouse pipeline: executes the stored procedure
# that backfills the columns/tables SqlPackage just deployed. The procedure
# ships in the same dacpac, so it cannot drift from the schema it populates.
#
# Plain SQL on purpose — not the Fabric job scheduler REST API, so a failure
# surfaces on the step that caused it.

import argparse
import os
import sys

import pyodbc


def split_name(procedure: str) -> tuple[str, str]:
    """'Gold.usp_x' -> ('Gold', 'usp_x'); a bare name defaults to dbo."""
    cleaned = procedure.replace("[", "").replace("]", "").strip()
    schema, _, name = cleaned.rpartition(".")
    return (schema or "dbo"), name


def main():
    p = argparse.ArgumentParser(description="Execute a stored procedure on a Fabric Warehouse")
    p.add_argument("--server", required=True)
    p.add_argument("--database", required=True)
    p.add_argument("--procedure", required=True, help="e.g. Gold.usp_populate_new_columns")
    p.add_argument("--client-id", default=os.environ.get("AZURE_CLIENT_ID", ""))
    p.add_argument("--client-secret", default=os.environ.get("AZURE_CLIENT_SECRET", ""))
    p.add_argument("--skip-if-missing", action="store_true",
                   help="Exit 0 when the procedure is not deployed yet")
    args = p.parse_args()

    client_id = args.client_id.strip()
    client_secret = args.client_secret.strip()
    if not (client_id and client_secret):
        raise SystemExit("Missing AZURE_CLIENT_ID / AZURE_CLIENT_SECRET")

    schema, name = split_name(args.procedure)
    if not name:
        raise SystemExit(f"Invalid procedure name: {args.procedure!r}")

    # autocommit: Fabric Warehouse rejects the implicit transaction pyodbc
    # would otherwise open around the batch.
    conn = pyodbc.connect(
        f"Driver={{ODBC Driver 18 for SQL Server}};"
        f"Server={args.server},1433;Database={args.database};"
        f"Authentication=ActiveDirectoryServicePrincipal;"
        f"UID={client_id};PWD={client_secret};"
        f"Encrypt=Yes;TrustServerCertificate=No;Connection Timeout=30;",
        autocommit=True,
    )
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT COUNT(*) FROM sys.procedures p"
            " JOIN sys.schemas s ON s.schema_id = p.schema_id"
            " WHERE s.name = ? AND p.name = ?",
            schema, name,
        )
        if not cursor.fetchone()[0]:
            msg = f"{args.procedure} does not exist in {args.database} — add it to the .sqlproj"
            if args.skip_if_missing:
                print(f"::notice::{msg}. Skipped.")
                return
            sys.exit(f"::error::{msg}")

        # Bracket-quoted so the name can never be read as SQL.
        print(f"EXEC [{schema}].[{name}]")
        cursor.execute(f"EXEC [{schema}].[{name}]")

        # Echo whatever the procedure SELECTed, so the CI log shows how many
        # rows were actually backfilled instead of just "it ran".
        while True:
            if cursor.description:
                print("  " + " | ".join(c[0] for c in cursor.description))
                for row in cursor.fetchall():
                    print("  " + " | ".join("NULL" if v is None else str(v) for v in row))
            if not cursor.nextset():
                break
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
