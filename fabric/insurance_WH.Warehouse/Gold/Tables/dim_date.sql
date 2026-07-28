CREATE TABLE [Gold].[dim_date] (

	[date_key] int NOT NULL, 
	[full_date] date NOT NULL, 
	[day_of_week] smallint NOT NULL, 
	[day_name] varchar(10) NOT NULL, 
	[day_of_month] smallint NOT NULL, 
	[day_of_year] smallint NOT NULL, 
	[week_of_year] smallint NOT NULL, 
	[month_number] smallint NOT NULL, 
	[month_name] varchar(10) NOT NULL, 
	[month_short] char(3) NOT NULL, 
	[quarter_number] smallint NOT NULL, 
	[quarter_name] char(2) NOT NULL, 
	[year_number] smallint NOT NULL, 
	[is_weekend] smallint NOT NULL, 
	[is_holiday] smallint NOT NULL, 
	[fiscal_year] smallint NOT NULL, 
	[fiscal_quarter] smallint NOT NULL, 
	[fiscal_month] smallint NOT NULL
);


GO
ALTER TABLE [Gold].[dim_date] ADD CONSTRAINT PK_dim_date primary key NONCLUSTERED ([date_key]);
GO
ALTER TABLE [Gold].[dim_date] ADD CONSTRAINT UQ_dim_date_full_date unique NONCLUSTERED ([full_date]);