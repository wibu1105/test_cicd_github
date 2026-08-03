# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {}
# META }

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
# MAGIC     holidayName           STRING,
# MAGIC     normalizeHolidayName  STRING,
# MAGIC     isPaidTimeOff         BOOLEAN,
# MAGIC     countryRegionCode     STRING,
# MAGIC     date                  TIMESTAMP
# MAGIC )
# MAGIC USING DELTA


# METADATA ********************

# META {
# META   "language": "sparksql",
# META   "language_group": "synapse_pyspark"
# META }
