-- Gold reconciliation checks, run by `python -m olist.gold` after the build.
-- Each query returns one row: check_name, actual, passed. One passed = false fails the run.
-- Views: Gold tables by name (fact_orders...), Silver tables prefixed with silver_.
-- Never put a semicolon inside a comment: the runner splits the file on semicolons.

-- 1. Volumes: Gold keeps every Silver row
SELECT 'fact_orders rows = Silver orders' AS check_name,
       CAST((SELECT count(*) FROM fact_orders) AS STRING) AS actual,
       (SELECT count(*) FROM fact_orders) = (SELECT count(*) FROM silver_orders) AS passed;

SELECT 'fact_order_items rows = Silver items',
       CAST((SELECT count(*) FROM fact_order_items) AS STRING),
       (SELECT count(*) FROM fact_order_items) = (SELECT count(*) FROM silver_order_items);

SELECT 'dim_customer rows = distinct real customers',
       CAST((SELECT count(*) FROM dim_customer) AS STRING),
       (SELECT count(*) FROM dim_customer) = (SELECT count(DISTINCT customer_unique_id) FROM silver_customers);

-- 2. Money: no amount lost or doubled between layers and between the two facts
SELECT 'sum(price) Gold = Silver',
       CAST((SELECT sum(price) FROM fact_order_items) AS STRING),
       (SELECT sum(price) FROM fact_order_items) = (SELECT sum(price) FROM silver_order_items);

SELECT 'sum(order_value) = sum(price) (grain)',
       CAST((SELECT sum(order_value) FROM fact_orders) AS STRING),
       (SELECT sum(order_value) FROM fact_orders) = (SELECT sum(price) FROM fact_order_items);

SELECT 'sum(payment_total) Gold = Silver',
       CAST((SELECT sum(payment_total) FROM fact_orders) AS STRING),
       (SELECT sum(payment_total) FROM fact_orders) = (SELECT sum(payment_value) FROM silver_order_payments);

-- 3. Keys: every fact row finds its dimensions
SELECT 'fact keys not null',
       CAST((SELECT count(*) FROM fact_order_items
             WHERE customer_key IS NULL OR product_key IS NULL OR seller_key IS NULL OR purchase_date_key IS NULL)
          + (SELECT count(*) FROM fact_orders WHERE customer_key IS NULL OR purchase_date_key IS NULL) AS STRING),
       (SELECT count(*) FROM fact_order_items
        WHERE customer_key IS NULL OR product_key IS NULL OR seller_key IS NULL OR purchase_date_key IS NULL)
     + (SELECT count(*) FROM fact_orders WHERE customer_key IS NULL OR purchase_date_key IS NULL) = 0;

SELECT 'purchase dates exist in dim_date',
       CAST((SELECT count(*) FROM fact_orders f LEFT ANTI JOIN dim_date d ON f.purchase_date_key = d.date_key) AS STRING),
       (SELECT count(*) FROM fact_orders f LEFT ANTI JOIN dim_date d ON f.purchase_date_key = d.date_key) = 0;

-- 4. The story (non-regression, ADR-006): late = delivered after the promised day
SELECT 'late rate % (expected 6.77)',
       CAST(round(100 * avg(CAST(is_late AS INT)), 2) AS STRING),
       round(100 * avg(CAST(is_late AS INT)), 2) BETWEEN 6.72 AND 6.82
FROM fact_orders WHERE order_status = 'delivered';

SELECT 'avg review late (expected 2.27)',
       CAST(round(avg(review_score), 2) AS STRING),
       round(avg(review_score), 2) BETWEEN 2.25 AND 2.29
FROM fact_orders WHERE order_status = 'delivered' AND is_late;

SELECT 'avg review on time (expected 4.29)',
       CAST(round(avg(review_score), 2) AS STRING),
       round(avg(review_score), 2) BETWEEN 4.27 AND 4.31
FROM fact_orders WHERE order_status = 'delivered' AND NOT is_late;
