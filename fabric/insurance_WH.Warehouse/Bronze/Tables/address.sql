CREATE TABLE [Bronze].[address] (

	[address_id] int NOT NULL, 
	[street_line1] varchar(200) NOT NULL, 
	[street_line2] varchar(200) NULL, 
	[postal_code] varchar(20) NOT NULL, 
	[city_id] int NOT NULL
);


GO
ALTER TABLE [Bronze].[address] ADD CONSTRAINT PK_address primary key NONCLUSTERED ([address_id]);
GO
ALTER TABLE [Bronze].[address] ADD CONSTRAINT FK_address_city FOREIGN KEY ([city_id]) REFERENCES [Bronze].[city]([city_id]);