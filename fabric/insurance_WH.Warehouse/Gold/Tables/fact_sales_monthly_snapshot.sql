CREATE TABLE [Gold].[fact_sales_monthly_snapshot] (

	[snapshot_key] int NOT NULL, 
	[snapshot_date_key] int NOT NULL, 
	[customer_key] int NOT NULL, 
	[product_key] int NOT NULL, 
	[geography_key] int NOT NULL, 
	[order_count] int NOT NULL, 
	[quantity_sold] int NOT NULL, 
	[gross_sales_amount] decimal(12,2) NOT NULL, 
	[discount_amount] decimal(12,2) NOT NULL, 
	[net_sales_amount] decimal(12,2) NOT NULL, 
	[gross_margin_amount] decimal(12,2) NULL, 
	[ytd_order_count] int NOT NULL, 
	[ytd_quantity_sold] int NOT NULL, 
	[ytd_net_sales] decimal(12,2) NOT NULL
);


GO
ALTER TABLE [Gold].[fact_sales_monthly_snapshot] ADD CONSTRAINT PK_fact_sales_monthly_snapshot primary key NONCLUSTERED ([snapshot_key]);
GO
ALTER TABLE [Gold].[fact_sales_monthly_snapshot] ADD CONSTRAINT FK_fsms_customer FOREIGN KEY ([customer_key]) REFERENCES [Gold].[dim_customer]([customer_key]);
GO
ALTER TABLE [Gold].[fact_sales_monthly_snapshot] ADD CONSTRAINT FK_fsms_geography FOREIGN KEY ([geography_key]) REFERENCES [Gold].[dim_geography]([geography_key]);
GO
ALTER TABLE [Gold].[fact_sales_monthly_snapshot] ADD CONSTRAINT FK_fsms_product FOREIGN KEY ([product_key]) REFERENCES [Gold].[dim_product]([product_key]);
GO
ALTER TABLE [Gold].[fact_sales_monthly_snapshot] ADD CONSTRAINT FK_fsms_snapshot_date FOREIGN KEY ([snapshot_date_key]) REFERENCES [Gold].[dim_date]([date_key]);