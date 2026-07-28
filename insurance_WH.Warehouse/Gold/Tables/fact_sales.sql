CREATE TABLE [Gold].[fact_sales] (

	[sales_key] int NOT NULL, 
	[order_line_id] int NOT NULL, 
	[order_id] int NOT NULL, 
	[order_date_key] int NOT NULL, 
	[ship_date_key] int NULL, 
	[customer_key] int NOT NULL, 
	[product_key] int NOT NULL, 
	[geography_key] int NOT NULL, 
	[order_status_key] int NOT NULL, 
	[quantity] smallint NOT NULL, 
	[unit_price] decimal(10,2) NOT NULL, 
	[discount_pct] decimal(5,2) NOT NULL, 
	[discount_amount] decimal(10,2) NOT NULL, 
	[gross_sales_amount] decimal(10,2) NOT NULL, 
	[net_sales_amount] decimal(10,2) NOT NULL, 
	[cost_amount] decimal(10,2) NULL, 
	[gross_margin_amount] decimal(10,2) NULL, 
	[days_to_ship] smallint NULL
);


GO
ALTER TABLE [Gold].[fact_sales] ADD CONSTRAINT PK_fact_sales primary key NONCLUSTERED ([sales_key]);
GO
ALTER TABLE [Gold].[fact_sales] ADD CONSTRAINT FK_fact_sales_customer FOREIGN KEY ([customer_key]) REFERENCES [Gold].[dim_customer]([customer_key]);
GO
ALTER TABLE [Gold].[fact_sales] ADD CONSTRAINT FK_fact_sales_geography FOREIGN KEY ([geography_key]) REFERENCES [Gold].[dim_geography]([geography_key]);
GO
ALTER TABLE [Gold].[fact_sales] ADD CONSTRAINT FK_fact_sales_order_date FOREIGN KEY ([order_date_key]) REFERENCES [Gold].[dim_date]([date_key]);
GO
ALTER TABLE [Gold].[fact_sales] ADD CONSTRAINT FK_fact_sales_order_status FOREIGN KEY ([order_status_key]) REFERENCES [Gold].[dim_order_status]([order_status_key]);
GO
ALTER TABLE [Gold].[fact_sales] ADD CONSTRAINT FK_fact_sales_product FOREIGN KEY ([product_key]) REFERENCES [Gold].[dim_product]([product_key]);
GO
ALTER TABLE [Gold].[fact_sales] ADD CONSTRAINT FK_fact_sales_ship_date FOREIGN KEY ([ship_date_key]) REFERENCES [Gold].[dim_date]([date_key]);