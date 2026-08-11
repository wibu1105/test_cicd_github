CREATE TABLE [Bronze].[sales_order_line] (

	[order_line_id] int NOT NULL, 
	[order_id] int NOT NULL, 
	[product_id] int NOT NULL, 
	[quantity] smallint NOT NULL, 
	[unit_price] decimal(10,2) NOT NULL, 
	[discount_pct] decimal(5,2) NOT NULL, 
	[line_total] decimal(10,2) NOT NULL
);


GO
ALTER TABLE [Bronze].[sales_order_line] ADD CONSTRAINT PK_sales_order_line primary key NONCLUSTERED ([order_line_id]);
GO
ALTER TABLE [Bronze].[sales_order_line] ADD CONSTRAINT FK_sol_order FOREIGN KEY ([order_id]) REFERENCES [Bronze].[sales_order]([order_id]);
GO
ALTER TABLE [Bronze].[sales_order_line] ADD CONSTRAINT FK_sol_product FOREIGN KEY ([product_id]) REFERENCES [Bronze].[product]([product_id]);