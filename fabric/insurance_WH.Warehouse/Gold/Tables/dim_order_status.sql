CREATE TABLE [Gold].[dim_order_status] (

	[order_status_key] int NOT NULL, 
	[order_status] varchar(20) NOT NULL
);


GO
ALTER TABLE [Gold].[dim_order_status] ADD CONSTRAINT PK_dim_order_status primary key NONCLUSTERED ([order_status_key]);
GO
ALTER TABLE [Gold].[dim_order_status] ADD CONSTRAINT UQ_dim_order_status unique NONCLUSTERED ([order_status]);