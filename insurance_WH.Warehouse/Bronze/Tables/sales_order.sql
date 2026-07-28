CREATE TABLE [Bronze].[sales_order] (

	[order_id] int NOT NULL, 
	[customer_id] int NOT NULL, 
	[order_date] date NOT NULL, 
	[ship_date] date NULL, 
	[order_status] varchar(20) NOT NULL
);


GO
ALTER TABLE [Bronze].[sales_order] ADD CONSTRAINT PK_sales_order primary key NONCLUSTERED ([order_id]);
GO
ALTER TABLE [Bronze].[sales_order] ADD CONSTRAINT FK_sales_order_customer FOREIGN KEY ([customer_id]) REFERENCES [Bronze].[customer]([customer_id]);