CREATE TABLE [Bronze].[product_category] (

	[category_id] int NOT NULL, 
	[category_name] varchar(100) NOT NULL
);


GO
ALTER TABLE [Bronze].[product_category] ADD CONSTRAINT PK_product_category primary key NONCLUSTERED ([category_id]);
GO
ALTER TABLE [Bronze].[product_category] ADD CONSTRAINT UQ_product_category_name unique NONCLUSTERED ([category_name]);