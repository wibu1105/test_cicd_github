CREATE TABLE [Bronze].[product_status] (

	[status_id] int NOT NULL, 
	[status_name] varchar(50) NOT NULL
);


GO
ALTER TABLE [Bronze].[product_status] ADD CONSTRAINT PK_product_status primary key NONCLUSTERED ([status_id]);
GO
ALTER TABLE [Bronze].[product_status] ADD CONSTRAINT UQ_product_status_name unique NONCLUSTERED ([status_name]);