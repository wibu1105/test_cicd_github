CREATE TABLE [Bronze].[brand] (

	[brand_id] int NOT NULL, 
	[brand_name] varchar(100) NOT NULL, 
	[country_id] int NOT NULL
);


GO
ALTER TABLE [Bronze].[brand] ADD CONSTRAINT PK_brand primary key NONCLUSTERED ([brand_id]);
GO
ALTER TABLE [Bronze].[brand] ADD CONSTRAINT UQ_brand_name unique NONCLUSTERED ([brand_name]);
GO
ALTER TABLE [Bronze].[brand] ADD CONSTRAINT FK_brand_country FOREIGN KEY ([country_id]) REFERENCES [Bronze].[country]([country_id]);