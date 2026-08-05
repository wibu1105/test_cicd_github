CREATE TABLE [Bronze].[city] (

	[city_id] int NOT NULL, 
	[city_name] varchar(100) NOT NULL, 
	[state_id] int NOT NULL
);


GO
ALTER TABLE [Bronze].[city] ADD CONSTRAINT PK_city primary key NONCLUSTERED ([city_id]);
GO
ALTER TABLE [Bronze].[city] ADD CONSTRAINT FK_city_state FOREIGN KEY ([state_id]) REFERENCES [Bronze].[state]([state_id]);