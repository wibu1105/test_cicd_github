CREATE TABLE [Bronze].[country] (

	[country_id] int NOT NULL, 
	[country_name] varchar(100) NOT NULL, 
	[country_code] char(2) NOT NULL
);


GO
ALTER TABLE [Bronze].[country] ADD CONSTRAINT PK_country primary key NONCLUSTERED ([country_id]);
GO
ALTER TABLE [Bronze].[country] ADD CONSTRAINT UQ_country_code unique NONCLUSTERED ([country_code]);