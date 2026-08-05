CREATE TABLE [Bronze].[state] (

	[state_id] int NOT NULL, 
	[state_name] varchar(100) NOT NULL, 
	[state_code] char(2) NOT NULL, 
	[country_id] int NOT NULL
);


GO
ALTER TABLE [Bronze].[state] ADD CONSTRAINT PK_state primary key NONCLUSTERED ([state_id]);
GO
ALTER TABLE [Bronze].[state] ADD CONSTRAINT FK_state_country FOREIGN KEY ([country_id]) REFERENCES [Bronze].[country]([country_id]);