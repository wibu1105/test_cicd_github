-- Fabric notebook source

-- METADATA ********************

-- META {
-- META   "kernel_info": {
-- META     "name": "sqldatawarehouse"
-- META   },
-- META   "dependencies": {
-- META     "warehouse": {
-- META       "default_warehouse": "bffd60c6-9791-985f-41e0-8c375e59288a",
-- META       "known_warehouses": [
-- META         {
-- META           "id": "bffd60c6-9791-985f-41e0-8c375e59288a",
-- META           "type": "Datawarehouse"
-- META         }
-- META       ]
-- META     }
-- META   }
-- META }

-- CELL ********************

DELETE FROM Gold.fact_sales_monthly_snapshot;
DELETE FROM Gold.fact_sales;

DELETE FROM Gold.dim_order_status;
DELETE FROM Gold.dim_geography;
DELETE FROM Gold.dim_product;
DELETE FROM Gold.dim_customer;
DELETE FROM Gold.dim_date;

-- METADATA ********************

-- META {
-- META   "language": "sql",
-- META   "language_group": "sqldatawarehouse"
-- META }

-- CELL ********************

WITH n10 AS (
    SELECT n
    FROM (VALUES
        (0), (1), (2), (3), (4),
        (5), (6), (7), (8), (9)
    ) v(n)
),

tally AS (
    SELECT
        (a.n * 1000 + b.n * 100 + c.n * 10 + d.n) AS offset_days
    FROM n10 a
    CROSS JOIN n10 b
    CROSS JOIN n10 c
    CROSS JOIN n10 d
),

calendar AS (
    SELECT
        DATEADD(DAY, offset_days, CAST('2022-01-01' AS DATE)) AS full_date
    FROM tally
    WHERE offset_days <= DATEDIFF(
        DAY,
        CAST('2022-01-01' AS DATE),
        CAST('2024-12-31' AS DATE)
    )
),

enriched AS (
    SELECT
        full_date,
        (DATEDIFF(DAY, CAST('1900-01-01' AS DATE), full_date) % 7) + 1 AS day_of_week,
        DATEPART(QUARTER, full_date) AS quarter_number,
        MONTH(full_date) AS month_number,
        YEAR(full_date) AS year_number
    FROM calendar
)

INSERT INTO Gold.dim_date
SELECT
    -- Date Key (YYYYMMDD)
    year_number * 10000 + month_number * 100 + DAY(full_date) AS date_key,

    -- Date
    full_date,

    -- Day
    CAST(day_of_week AS SMALLINT) AS day_of_week,

    CASE day_of_week
        WHEN 1 THEN 'Monday'
        WHEN 2 THEN 'Tuesday'
        WHEN 3 THEN 'Wednesday'
        WHEN 4 THEN 'Thursday'
        WHEN 5 THEN 'Friday'
        WHEN 6 THEN 'Saturday'
        ELSE 'Sunday'
    END AS day_name,

    CAST(DAY(full_date) AS SMALLINT) AS day_number,

    CAST(DATEPART(DAYOFYEAR, full_date) AS SMALLINT) AS day_of_year,

    CAST(DATEPART(WEEK, full_date) AS SMALLINT) AS week_number,

    -- Month
    CAST(month_number AS SMALLINT) AS month_number,

    CASE month_number
        WHEN 1 THEN 'January'
        WHEN 2 THEN 'February'
        WHEN 3 THEN 'March'
        WHEN 4 THEN 'April'
        WHEN 5 THEN 'May'
        WHEN 6 THEN 'June'
        WHEN 7 THEN 'July'
        WHEN 8 THEN 'August'
        WHEN 9 THEN 'September'
        WHEN 10 THEN 'October'
        WHEN 11 THEN 'November'
        ELSE 'December'
    END AS month_name,

    CASE month_number
        WHEN 1 THEN 'Jan'
        WHEN 2 THEN 'Feb'
        WHEN 3 THEN 'Mar'
        WHEN 4 THEN 'Apr'
        WHEN 5 THEN 'May'
        WHEN 6 THEN 'Jun'
        WHEN 7 THEN 'Jul'
        WHEN 8 THEN 'Aug'
        WHEN 9 THEN 'Sep'
        WHEN 10 THEN 'Oct'
        WHEN 11 THEN 'Nov'
        ELSE 'Dec'
    END AS month_short_name,

    -- Quarter
    CAST(quarter_number AS SMALLINT) AS quarter_number,

    CONCAT('Q', quarter_number) AS quarter_name,

    -- Year
    CAST(year_number AS SMALLINT) AS year_number,

    -- Flags
    CAST(
        CASE
            WHEN day_of_week >= 6 THEN 1
            ELSE 0
        END AS SMALLINT
    ) AS is_weekend,

    CAST(0 AS SMALLINT) AS is_holiday,

    -- Fiscal Calendar
    CAST(year_number AS SMALLINT) AS fiscal_year,
    CAST(quarter_number AS SMALLINT) AS fiscal_quarter,
    CAST(month_number AS SMALLINT) AS fiscal_month

FROM enriched;

-- METADATA ********************

-- META {
-- META   "language": "sql",
-- META   "language_group": "sqldatawarehouse"
-- META }

-- CELL ********************

INSERT INTO Gold.dim_customer
SELECT
    ROW_NUMBER() OVER (ORDER BY c.customer_id),
    c.customer_id,
    c.first_name,
    c.last_name,
    CONCAT(c.first_name, ' ', c.last_name),
    c.email,
    c.phone,
    c.date_of_birth,
    CASE
        WHEN DATEDIFF(YEAR, c.date_of_birth, GETDATE()) < 25 THEN '18-24'
        WHEN DATEDIFF(YEAR, c.date_of_birth, GETDATE()) < 35 THEN '25-34'
        WHEN DATEDIFF(YEAR, c.date_of_birth, GETDATE()) < 45 THEN '35-44'
        WHEN DATEDIFF(YEAR, c.date_of_birth, GETDATE()) < 55 THEN '45-54'
        ELSE '55+'
    END,
    ci.city_name,
    s.state_name,
    s.state_code,
    co.country_name,
    co.country_code,
    a.postal_code,
    CAST('2022-01-01' AS DATE),
    NULL,
    CAST(1 AS SMALLINT),
    CASE WHEN c.email LIKE '%@%'
         THEN LOWER(SUBSTRING(c.email, CHARINDEX('@', c.email) + 1, LEN(c.email)))
    END
FROM       Bronze.customer  c
INNER JOIN Bronze.address   a  ON a.address_id  = c.address_id
INNER JOIN Bronze.city      ci ON ci.city_id    = a.city_id
INNER JOIN Bronze.state     s  ON s.state_id    = ci.state_id
INNER JOIN Bronze.country   co ON co.country_id = s.country_id;

-- METADATA ********************

-- META {
-- META   "language": "sql",
-- META   "language_group": "sqldatawarehouse"
-- META }

-- CELL ********************

INSERT INTO Gold.dim_product
SELECT
    ROW_NUMBER() OVER (ORDER BY p.product_id),
    p.product_id,
    p.sku,
    p.product_name,
    b.brand_name,
    co.country_name,
    pc.category_name,
    ps.status_name,
    u.uom_code,
    p.unit_price,
    p.weight_kg,
    p.warranty_months,
    p.introduced_date,
    CAST('2022-01-01' AS DATE),
    NULL,
    CAST(1 AS SMALLINT)
FROM       Bronze.product          p
INNER JOIN Bronze.brand            b  ON b.brand_id     = p.brand_id
INNER JOIN Bronze.country          co ON co.country_id  = b.country_id
INNER JOIN Bronze.product_category pc ON pc.category_id = p.category_id
INNER JOIN Bronze.product_status   ps ON ps.status_id   = p.status_id
INNER JOIN Bronze.unit_of_measure  u  ON u.uom_id       = p.uom_id;

-- METADATA ********************

-- META {
-- META   "language": "sql",
-- META   "language_group": "sqldatawarehouse"
-- META }

-- CELL ********************

INSERT INTO Gold.dim_geography
SELECT
    ROW_NUMBER() OVER (ORDER BY co.country_name, s.state_name, ci.city_name),
    ci.city_name,
    s.state_name,
    s.state_code,
    co.country_name,
    co.country_code
FROM       Bronze.city    ci
INNER JOIN Bronze.state   s  ON s.state_id    = ci.state_id
INNER JOIN Bronze.country co ON co.country_id = s.country_id;

-- METADATA ********************

-- META {
-- META   "language": "sql",
-- META   "language_group": "sqldatawarehouse"
-- META }

-- CELL ********************

INSERT INTO Gold.dim_order_status
SELECT
    ROW_NUMBER() OVER (ORDER BY order_status),
    order_status
FROM (SELECT DISTINCT order_status FROM Bronze.sales_order) s;

-- METADATA ********************

-- META {
-- META   "language": "sql",
-- META   "language_group": "sqldatawarehouse"
-- META }

-- CELL ********************

INSERT INTO Gold.fact_sales
SELECT
    ROW_NUMBER() OVER (ORDER BY sol.order_line_id),
    sol.order_line_id,
    so.order_id,
    YEAR(so.order_date) * 10000 + MONTH(so.order_date) * 100 + DAY(so.order_date),
    CASE WHEN so.ship_date IS NOT NULL
         THEN YEAR(so.ship_date) * 10000 + MONTH(so.ship_date) * 100 + DAY(so.ship_date) END,
    dc.customer_key,
    dp.product_key,
    dg.geography_key,
    dos.order_status_key,
    sol.quantity,
    sol.unit_price,
    sol.discount_pct,
    ROUND(sol.unit_price * sol.quantity * sol.discount_pct / 100, 2),
    ROUND(sol.unit_price * sol.quantity, 2),
    sol.line_total,
    NULL,
    NULL,
    CASE WHEN so.ship_date IS NOT NULL
         THEN CAST(DATEDIFF(DAY, so.order_date, so.ship_date) AS SMALLINT) END
FROM       Bronze.sales_order_line  sol
INNER JOIN Bronze.sales_order       so  ON so.order_id    = sol.order_id
INNER JOIN Bronze.customer          c   ON c.customer_id  = so.customer_id
INNER JOIN Bronze.address           a   ON a.address_id   = c.address_id
INNER JOIN Bronze.city              ci  ON ci.city_id     = a.city_id
INNER JOIN Bronze.state             s   ON s.state_id     = ci.state_id
INNER JOIN Bronze.country           co  ON co.country_id  = s.country_id
INNER JOIN Gold.dim_customer     dc  ON dc.customer_id  = c.customer_id  AND dc.is_current = 1
INNER JOIN Gold.dim_product      dp  ON dp.product_id   = sol.product_id AND dp.is_current = 1
INNER JOIN Gold.dim_geography    dg  ON dg.city          = ci.city_name
                                     AND dg.state_code   = s.state_code
                                     AND dg.country_code = co.country_code
INNER JOIN Gold.dim_order_status dos ON dos.order_status = so.order_status;

-- METADATA ********************

-- META {
-- META   "language": "sql",
-- META   "language_group": "sqldatawarehouse"
-- META }

-- CELL ********************

INSERT INTO Gold.fact_sales_monthly_snapshot
SELECT
    ROW_NUMBER() OVER (ORDER BY customer_key, product_key, geography_key, year_number, month_number),
    YEAR(EOMONTH(DATEFROMPARTS(year_number, month_number, 1))) * 10000
      + MONTH(EOMONTH(DATEFROMPARTS(year_number, month_number, 1))) * 100
      + DAY(EOMONTH(DATEFROMPARTS(year_number, month_number, 1))),
    customer_key,
    product_key,
    geography_key,
    order_count,
    quantity_sold,
    gross_sales_amount,
    discount_amount,
    net_sales_amount,
    NULL,
    SUM(order_count)      OVER (PARTITION BY customer_key, product_key, geography_key, year_number ORDER BY month_number ROWS UNBOUNDED PRECEDING),
    SUM(quantity_sold)    OVER (PARTITION BY customer_key, product_key, geography_key, year_number ORDER BY month_number ROWS UNBOUNDED PRECEDING),
    SUM(net_sales_amount) OVER (PARTITION BY customer_key, product_key, geography_key, year_number ORDER BY month_number ROWS UNBOUNDED PRECEDING)
FROM (
    SELECT
        dc.customer_key,
        dp.product_key,
        dg.geography_key,
        YEAR(so.order_date)                                                   AS year_number,
        MONTH(so.order_date)                                                  AS month_number,
        COUNT(sol.order_line_id)                                              AS order_count,
        SUM(sol.quantity)                                                     AS quantity_sold,
        ROUND(SUM(sol.unit_price * sol.quantity), 2)                          AS gross_sales_amount,
        ROUND(SUM(sol.unit_price * sol.quantity * sol.discount_pct / 100), 2) AS discount_amount,
        ROUND(SUM(sol.line_total), 2)                                         AS net_sales_amount
    FROM       Bronze.sales_order_line  sol
    INNER JOIN Bronze.sales_order       so  ON so.order_id    = sol.order_id
    INNER JOIN Bronze.customer          c   ON c.customer_id  = so.customer_id
    INNER JOIN Bronze.address           a   ON a.address_id   = c.address_id
    INNER JOIN Bronze.city              ci  ON ci.city_id     = a.city_id
    INNER JOIN Bronze.state             s   ON s.state_id     = ci.state_id
    INNER JOIN Bronze.country           co  ON co.country_id  = s.country_id
    INNER JOIN Gold.dim_customer  dc ON dc.customer_id  = c.customer_id  AND dc.is_current = 1
    INNER JOIN Gold.dim_product   dp ON dp.product_id   = sol.product_id AND dp.is_current = 1
    INNER JOIN Gold.dim_geography dg ON dg.city          = ci.city_name
                                     AND dg.state_code   = s.state_code
                                     AND dg.country_code = co.country_code
    GROUP BY
        dc.customer_key, dp.product_key, dg.geography_key,
        YEAR(so.order_date), MONTH(so.order_date)
) monthly;

-- METADATA ********************

-- META {
-- META   "language": "sql",
-- META   "language_group": "sqldatawarehouse"
-- META }

-- CELL ********************

SELECT 'dim_date'                   AS table_name, COUNT(*) AS row_count FROM Gold.dim_date
UNION ALL SELECT 'dim_customer',                   COUNT(*) FROM Gold.dim_customer
UNION ALL SELECT 'dim_product',                    COUNT(*) FROM Gold.dim_product
UNION ALL SELECT 'dim_geography',                  COUNT(*) FROM Gold.dim_geography
UNION ALL SELECT 'dim_order_status',               COUNT(*) FROM Gold.dim_order_status
UNION ALL SELECT 'fact_sales',                     COUNT(*) FROM Gold.fact_sales
UNION ALL SELECT 'fact_sales_monthly_snapshot',    COUNT(*) FROM Gold.fact_sales_monthly_snapshot;

-- METADATA ********************

-- META {
-- META   "language": "sql",
-- META   "language_group": "sqldatawarehouse"
-- META }
