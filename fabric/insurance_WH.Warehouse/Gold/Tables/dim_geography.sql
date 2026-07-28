CREATE TABLE [Gold].[dim_geography] (

	[geography_key] int NOT NULL, 
	[city] varchar(100) NOT NULL, 
	[state] varchar(100) NOT NULL, 
	[state_code] char(2) NOT NULL, 
	[country] varchar(100) NOT NULL, 
	[country_code] char(2) NOT NULL
);


GO
ALTER TABLE [Gold].[dim_geography] ADD CONSTRAINT PK_dim_geography primary key NONCLUSTERED ([geography_key]);