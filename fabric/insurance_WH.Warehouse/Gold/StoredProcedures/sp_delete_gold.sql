CREATE   PROCEDURE Gold.sp_delete_gold
AS
BEGIN

SET NOCOUNT ON;

DELETE FROM Gold.fact_sales_monthly_snapshot;
DELETE FROM Gold.fact_sales;

DELETE FROM Gold.dim_order_status;
DELETE FROM Gold.dim_geography;
DELETE FROM Gold.dim_product;
DELETE FROM Gold.dim_customer;
DELETE FROM Gold.dim_date;

END;