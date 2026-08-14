# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {
# META     "lakehouse": {
# META       "default_lakehouse": "1ccc26bf-c5d1-44d7-a29b-258be3c3cb07",
# META       "default_lakehouse_name": "test_LH",
# META       "default_lakehouse_workspace_id": "27838171-f92c-48b6-937f-84f5c60bd09f",
# META       "known_lakehouses": [
# META         {
# META           "id": "1ccc26bf-c5d1-44d7-a29b-258be3c3cb07"
# META         }
# META       ]
# META     }
# META   }
# META }

# CELL ********************

# Welcome to your new notebook
# Type here in the cell editor to add code!
spark.sql("""CREATE SCHEMA IF NOT EXISTS raw""")
sql_query = """
    CREATE TABLE IF NOT EXISTS raw.dim_customer (
    CustomerKey        BIGINT,
    CustomerID         STRING,
    CustomerName       STRING,
    Email              STRING,
    Phone              STRING,
    IsActive           INT,
    CreatedDate        TIMESTAMP
)
USING DELTA
"""

spark.sql(sql_query)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }
