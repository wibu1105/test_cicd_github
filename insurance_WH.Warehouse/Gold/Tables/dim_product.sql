CREATE TABLE [Gold].[dim_product] (

	[product_key] int NOT NULL, 
	[product_id] int NOT NULL, 
	[sku] varchar(50) NOT NULL, 
	[product_name] varchar(200) NOT NULL, 
	[brand] varchar(100) NOT NULL, 
	[brand_country] varchar(100) NOT NULL, 
	[category] varchar(100) NOT NULL, 
	[product_status] varchar(50) NOT NULL, 
	[unit_of_measure] varchar(20) NOT NULL, 
	[current_unit_price] decimal(10,2) NOT NULL, 
	[weight_kg] decimal(8,3) NULL, 
	[warranty_months] smallint NULL, 
	[introduced_date] date NULL, 
	[effective_from] date NOT NULL, 
	[effective_to] date NULL, 
	[is_current] smallint NOT NULL
);


GO
ALTER TABLE [Gold].[dim_product] ADD CONSTRAINT PK_dim_product primary key NONCLUSTERED ([product_key]);