-- Gold.usp_populate_new_columns
--
-- Chạy bởi deploy-warehouse.yml (qua cicd/run_sql.py) ngay sau khi SqlPackage
-- publish schema. Nhiệm vụ: điền giá trị cho các cột vừa được ALTER TABLE thêm
-- vào, cho những dòng đã tồn tại từ trước.
--
-- Procedure này nằm trong .sqlproj nên được deploy bởi chính dacpac chứa schema
-- mà nó backfill — không bao giờ lệch phiên bản với schema.
--
-- Mọi statement ở đây phải idempotent (chạy lại nhiều lần không đổi kết quả),
-- vì nó chạy lại ở MỌI lần deploy warehouse, không chỉ lần thêm cột.

CREATE PROCEDURE Gold.usp_populate_new_columns
AS
BEGIN

SET NOCOUNT ON;

-- ----------------------------------------------------------------------
-- dim_customer.email_domain — phần sau dấu '@' của email, viết thường.
-- Chỉ đụng vào dòng còn NULL nên chạy lại không ghi đè dữ liệu đã có.
-- Email không có '@' được để NULL thay vì gán nhầm cả chuỗi email.
-- ----------------------------------------------------------------------
UPDATE Gold.dim_customer
SET email_domain = LOWER(SUBSTRING(email, CHARINDEX('@', email) + 1, LEN(email)))
WHERE email_domain IS NULL
  AND email LIKE '%@%';

-- Cho log của bước "Populate new columns" thấy được kết quả thực tế.
SELECT
    'Gold.dim_customer.email_domain' AS backfilled_column,
    COUNT(*)                         AS total_rows,
    SUM(CASE WHEN email_domain IS NULL THEN 1 ELSE 0 END) AS still_null
FROM Gold.dim_customer;

END;