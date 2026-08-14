CREATE TABLE [Bronze].[product] (

	[product_id] int NOT NULL, 
	[sku] varchar(50) NOT NULL, 
	[product_name] varchar(200) NOT NULL, 
	[brand_id] int NOT NULL, 
	[category_id] int NOT NULL, 
	[status_id] int NOT NULL, 
	[unit_price] decimal(10,2) NOT NULL, 
	[uom_id] int NOT NULL, 
	[weight_kg] decimal(8,3) NULL, 
	[warranty_months] smallint NULL, 
	[introduced_date] date NULL
);


GO
ALTER TABLE [Bronze].[product] ADD CONSTRAINT PK_product primary key NONCLUSTERED ([product_id]);
GO
ALTER TABLE [Bronze].[product] ADD CONSTRAINT UQ_product_sku unique NONCLUSTERED ([sku]);
GO
ALTER TABLE [Bronze].[product] ADD CONSTRAINT FK_product_brand FOREIGN KEY ([brand_id]) REFERENCES [Bronze].[brand]([brand_id]);
GO
ALTER TABLE [Bronze].[product] ADD CONSTRAINT FK_product_category FOREIGN KEY ([category_id]) REFERENCES [Bronze].[product_category]([category_id]);
GO
ALTER TABLE [Bronze].[product] ADD CONSTRAINT FK_product_status FOREIGN KEY ([status_id]) REFERENCES [Bronze].[product_status]([status_id]);
GO
ALTER TABLE [Bronze].[product] ADD CONSTRAINT FK_product_uom FOREIGN KEY ([uom_id]) REFERENCES [Bronze].[unit_of_measure]([uom_id]);