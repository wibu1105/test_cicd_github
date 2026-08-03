# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {
# META     "lakehouse": {
# META       "default_lakehouse": "f28bbe6d-0dd5-92eb-450f-1444b55ebcb9",
# META       "default_lakehouse_name": "test_LH",
# META       "known_lakehouses": [
# META         {
# META           "id": "f28bbe6d-0dd5-92eb-450f-1444b55ebcb9"
# META         }
# META       ]
# META     }
# META   }
# META }

# MARKDOWN ********************

# # Lakehouse schema
#
# Declares the schema of `test_LH`. Run by `deploy-lakehouse.yml` after the
# Lakehouse item is published — the Lakehouse equivalent of the dacpac publish
# on the warehouse side.
#
# The GUID in `default_lakehouse` above is the **logicalId** from
# `fabric/test_LH.Lakehouse/.platform`, not a workspace-specific item id. That
# is the same thing `nb_transform` does with `insurance_WH`: the logicalId is
# the repo-level identity of the item, and Fabric resolves it to whichever real
# lakehouse carries that logicalId in the workspace being deployed to. So one
# file attaches correctly in dev and in test, with no `parameter.yml` rule and
# nothing to re-pin by hand.
#
# Note there is deliberately no `default_lakehouse_workspace_id` — pinning one
# would send every environment back to the workspace this was authored in.
#
# Every statement is idempotent: this runs on every lakehouse deploy, not only
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
