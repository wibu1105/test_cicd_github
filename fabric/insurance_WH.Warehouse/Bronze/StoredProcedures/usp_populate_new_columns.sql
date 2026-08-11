-- Bronze.usp_populate_new_columns
--
-- Chạy bởi deploy-warehouse.yml (qua cicd/run_sql.py) ngay sau khi SqlPackage
-- publish schema, và chạy TRƯỚC proc cùng tên bên Gold — vì Gold đọc dữ liệu
-- từ Bronze, nên Bronze phải đầy đủ trước.
--
-- Khác biệt so với Gold.usp_populate_new_columns:
-- Bronze là raw/landing layer, không có công thức để "suy ra" giá trị cho dữ
-- liệu cũ từ chính dữ liệu đang có. Nên backfill ở đây chỉ có thể gán một giá
-- trị quy ước ('unknown'), đánh dấu rằng những dòng đó có trước khi cột được
-- thêm vào. Dữ liệu nạp mới sau này mang giá trị thật (xem usp_seed_demo_data).
--
-- Mọi statement phải idempotent: proc này chạy lại ở MỌI lần deploy warehouse,
-- không riêng lần thêm cột.

CREATE PROCEDURE Bronze.usp_populate_new_columns
AS
BEGIN

SET NOCOUNT ON;

-- ----------------------------------------------------------------------
-- customer.loyalty_signup_channel — kênh khách hàng đăng ký chương trình
-- khách hàng thân thiết. Dòng có trước khi cột này tồn tại thì không thể
-- biết kênh thật, nên đánh 'unknown' thay vì để NULL (phân biệt được với
-- "chưa backfill" khi soi dữ liệu).
-- ----------------------------------------------------------------------
UPDATE Bronze.customer
SET loyalty_signup_channel = 'unknown'
WHERE loyalty_signup_channel IS NULL;

-- Cho log của bước "Populate new columns" thấy được kết quả thực tế.
SELECT
    'Bronze.customer.loyalty_signup_channel' AS backfilled_column,
    COUNT(*)                                 AS total_rows,
    SUM(CASE WHEN loyalty_signup_channel = 'unknown' THEN 1 ELSE 0 END) AS backfilled_unknown,
    SUM(CASE WHEN loyalty_signup_channel IS NULL THEN 1 ELSE 0 END)     AS still_null
FROM Bronze.customer;

END;