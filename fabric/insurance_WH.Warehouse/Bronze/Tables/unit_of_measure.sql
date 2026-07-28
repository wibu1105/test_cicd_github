CREATE TABLE [Bronze].[unit_of_measure] (

	[uom_id] int NOT NULL, 
	[uom_code] varchar(20) NOT NULL, 
	[uom_desc] varchar(100) NOT NULL
);


GO
ALTER TABLE [Bronze].[unit_of_measure] ADD CONSTRAINT PK_unit_of_measure primary key NONCLUSTERED ([uom_id]);
GO
ALTER TABLE [Bronze].[unit_of_measure] ADD CONSTRAINT UQ_uom_code unique NONCLUSTERED ([uom_code]);