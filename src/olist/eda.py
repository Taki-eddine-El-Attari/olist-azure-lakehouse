"""Phase 1 EDA: measure on Bronze the data defects listed in CAHIER_DES_CHARGES.md §3.

Run: python -m olist.eda (after python -m olist.bronze). Prints one number per check.
"""

from olist.bronze import TABLES
from olist.config import read_table
from olist.spark import get_spark

CHECKS = {
    "orders without customer delivery date": """
        SELECT count(*) FROM orders WHERE order_delivered_customer_date IS NULL""",
    "  of which status = delivered": """
        SELECT count(*) FROM orders
        WHERE order_delivered_customer_date IS NULL AND order_status = 'delivered'""",
    "orders without approval date": """
        SELECT count(*) FROM orders WHERE order_approved_at IS NULL""",
    "orders delivered before purchase/approval": """
        SELECT count(*) FROM orders
        WHERE order_delivered_customer_date < order_purchase_timestamp
           OR order_delivered_customer_date < order_approved_at""",
    "orders handed to carrier before approval": """
        SELECT count(*) FROM orders WHERE order_delivered_carrier_date < order_approved_at""",
    "products without category": """
        SELECT count(*) FROM products WHERE product_category_name IS NULL""",
    "categories missing from translation": """
        SELECT concat_ws(', ', sort_array(collect_set(p.product_category_name)))
        FROM products p LEFT ANTI JOIN category_translation t USING (product_category_name)
        WHERE p.product_category_name IS NOT NULL""",
    "products without weight/dimensions": """
        SELECT count(*) FROM products WHERE product_weight_g IS NULL""",
    "review_id appearing more than once": """
        SELECT count(*) FROM (SELECT review_id FROM order_reviews GROUP BY 1 HAVING count(*) > 1)""",
    "review rows minus distinct review_id": """
        SELECT count(*) - count(DISTINCT review_id) FROM order_reviews""",
    "orders with more than one review": """
        SELECT count(*) FROM (SELECT order_id FROM order_reviews GROUP BY 1 HAVING count(*) > 1)""",
    "orders without review": """
        SELECT count(*) FROM orders o LEFT ANTI JOIN order_reviews r USING (order_id)""",
    "geolocation rows / distinct zip prefixes": """
        SELECT concat(count(*), ' / ', count(DISTINCT geolocation_zip_code_prefix)) FROM geolocation""",
    "customer zip prefixes missing from geolocation": """
        SELECT count(DISTINCT customer_zip_code_prefix) FROM customers c
        LEFT ANTI JOIN geolocation g ON c.customer_zip_code_prefix = g.geolocation_zip_code_prefix""",
    "customer_id / distinct customer_unique_id": """
        SELECT concat(count(*), ' / ', count(DISTINCT customer_unique_id)) FROM customers""",
    "orders without any item": """
        SELECT count(*) FROM orders o LEFT ANTI JOIN order_items i USING (order_id)""",
    "orders paid but without any item": """
        SELECT count(DISTINCT order_id) FROM order_payments p LEFT ANTI JOIN order_items i USING (order_id)""",
    "payments minus (price + freight), BRL": """
        SELECT (SELECT sum(payment_value) FROM order_payments)
             - (SELECT sum(price + freight_value) FROM order_items)""",
    "payments with value 0": """
        SELECT count(*) FROM order_payments WHERE payment_value = 0""",
    "late rate among delivered orders, %": """
        SELECT round(100 * avg(CAST(order_delivered_customer_date > order_estimated_delivery_date AS INT)), 2)
        FROM orders WHERE order_status = 'delivered' AND order_delivered_customer_date IS NOT NULL""",
    "avg review: late / on time": """
        SELECT concat(round(avg(CASE WHEN late THEN review_score END), 2), ' / ',
                      round(avg(CASE WHEN NOT late THEN review_score END), 2))
        FROM (SELECT r.review_score,
                     o.order_delivered_customer_date > o.order_estimated_delivery_date AS late
              FROM orders o JOIN order_reviews r USING (order_id)
              WHERE o.order_status = 'delivered' AND o.order_delivered_customer_date IS NOT NULL)""",
}


def main() -> None:
    spark = get_spark("olist-eda")
    for table in TABLES:
        read_table(spark, "bronze", table).createOrReplaceTempView(table)
    for label, query in CHECKS.items():
        print(f"{label:<48}{spark.sql(query).first()[0]}")


if __name__ == "__main__":
    main()
