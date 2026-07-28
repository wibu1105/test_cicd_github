CREATE TABLE [Gold].[dim_customer] (

	[customer_key] int NOT NULL, 
	[customer_id] int NOT NULL, 
	[first_name] varchar(100) NOT NULL, 
	[last_name] varchar(100) NOT NULL, 
	[full_name] varchar(200) NOT NULL, 
	[email] varchar(255) NOT NULL, 
	[phone] varchar(30) NULL, 
	[date_of_birth] date NULL, 
	[age_band] varchar(20) NULL, 
	[city] varchar(100) NOT NULL, 
	[state] varchar(100) NOT NULL, 
	[state_code] char(2) NOT NULL, 
	[country] varchar(100) NOT NULL, 
	[country_code] char(2) NOT NULL, 
	[postal_code] varchar(20) NOT NULL, 
	[effective_from] date NOT NULL, 
	[effective_to] date NULL, 
	[is_current] smallint NOT NULL
);


GO
ALTER TABLE [Gold].[dim_customer] ADD CONSTRAINT PK_dim_customer primary key NONCLUSTERED ([customer_key]);