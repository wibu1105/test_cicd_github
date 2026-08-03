CREATE TABLE [Bronze].[customer] (

	[customer_id] int NOT NULL, 
	[first_name] varchar(100) NOT NULL, 
	[last_name] varchar(100) NOT NULL, 
	[email] varchar(255) NOT NULL, 
	[phone] varchar(30) NULL, 
	[date_of_birth] date NULL, 
	[address_id] int NOT NULL, 
	[created_at] datetime2(0) NOT NULL,
	[loyalty_signup_channel] varchar(50) NULL
);


GO
ALTER TABLE [Bronze].[customer] ADD CONSTRAINT PK_customer primary key NONCLUSTERED ([customer_id]);
GO
ALTER TABLE [Bronze].[customer] ADD CONSTRAINT UQ_customer_email unique NONCLUSTERED ([email]);
GO
ALTER TABLE [Bronze].[customer] ADD CONSTRAINT FK_customer_address FOREIGN KEY ([address_id]) REFERENCES [Bronze].[address]([address_id]);