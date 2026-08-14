# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {
# META     "lakehouse": {
# META       "default_lakehouse": "b55ebcb9-1444-450f-92eb-0dd5f28bbe6d",
# META       "default_lakehouse_name": "test_LH",
# META       "default_lakehouse_workspace_id": "20d6e797-9f3e-4e0a-a291-0789bdb1b623",
# META       "known_lakehouses": [
# META         {
# META           "id": "b55ebcb9-1444-450f-92eb-0dd5f28bbe6d"
# META         }
# META       ]
# META     }
# META   }
# META }

# MARKDOWN ********************

# # Lakehouse schema
# # Declares the schema of `test_LH`. Run by `deploy-to-fabric.yml` after the
# Lakehouse item is published — the Lakehouse equivalent of the dacpac publish
# on the warehouse side.
# # The GUIDs above are the **dev** lakehouse and workspace, exactly as Fabric
# writes them when the lakehouse is attached in the UI. They do not stay dev
# values after deploy: `cicd/parameter.yml` rewrites both to `$items.Lakehouse.
# test_LH.id` and `$workspace.id`, so the notebook attaches to the target
# workspace's own lakehouse.
# # Two things this block cannot do without:
# # - `default_lakehouse_workspace_id` is **required**. Omit it and the job fails
#   with `LakehouseWorkspaceId is not a valid GUID:` (empty). The `warehouse`
#   block in `nb_transform` has no such field — the two are not symmetric.
# - `default_lakehouse` must be the lakehouse's **item id**, not the `logicalId`
#   in `.platform`. Those two are different GUIDs for the same item.
# # Every statement is idempotent: this runs on every lakehouse deploy, not only
# when a table is added.

# CELL ********************

# MAGIC %%sql
# MAGIC CREATE SCHEMA IF NOT EXISTS dbo

# METADATA ********************

# META {
# META   "language": "sparksql",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# MAGIC %%sql
# MAGIC CREATE TABLE IF NOT EXISTS dbo.publicholidays (
# MAGIC     countryOrRegion      STRING,
# MAGIC     holidayName          STRING,
# MAGIC     normalizeHolidayName STRING,
# MAGIC     isPaidTimeOff        BOOLEAN,
# MAGIC     countryRegionCode    STRING,
# MAGIC     date                 TIMESTAMP
# MAGIC )
# MAGIC USING DELTA

# METADATA ********************

# META {
# META   "language": "sparksql",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Fails the notebook, and with it the pipeline step, when a table the deploy was
# supposed to create is not there. Without this the job reports Completed even
# when nothing was written, which is how a missing schema goes unnoticed.
EXPECTED_TABLES = ["publicholidays"]

actual = sorted(r.tableName for r in spark.sql("SHOW TABLES IN dbo").collect())  # noqa: F821
missing = [t for t in EXPECTED_TABLES if t not in actual]
if missing:
    raise RuntimeError(f"Missing tables in dbo: {missing}. Found: {actual}")

print(f"OK — dbo has {actual}")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }
