"""Data quality checks on Silver -> dq_results. An 'error' check that fails stops the run."""

import uuid

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from olist.config import read_table, write_table
from olist.spark import get_spark

SILVER_TABLES = ["orders", "order_items", "order_payments", "order_reviews", "customers", "sellers",
                 "products", "geolocation", "quarantine"]

# (table, check, severity, SQL returning the number of failing rows). 0 = pass.
# 'warn' = known, explained defect we keep (ADR-004/005): counted every run, never blocking.
CHECKS = [
    # Keys: unique and not null
    ("orders", "order_id_unique_not_null", "error",
     "SELECT count(*) - count(DISTINCT order_id) FROM orders"),
    ("order_items", "pk_unique", "error",
     "SELECT count(*) - count(DISTINCT order_id, order_item_id) FROM order_items"),
    ("order_payments", "pk_unique", "error",
     "SELECT count(*) - count(DISTINCT order_id, payment_sequential) FROM order_payments"),
    ("order_reviews", "one_review_per_order", "error",
     "SELECT count(*) - count(DISTINCT order_id) FROM order_reviews"),
    ("customers", "customer_id_unique_not_null", "error",
     "SELECT count(*) - count(DISTINCT customer_id) FROM customers"),
    ("sellers", "seller_id_unique_not_null", "error",
     "SELECT count(*) - count(DISTINCT seller_id) FROM sellers"),
    ("products", "product_id_unique_not_null", "error",
     "SELECT count(*) - count(DISTINCT product_id) FROM products"),
    ("geolocation", "zip_prefix_unique", "error",
     "SELECT count(*) - count(DISTINCT geolocation_zip_code_prefix) FROM geolocation"),
    # Referential integrity
    ("order_items", "fk_orders", "error",
     "SELECT count(*) FROM order_items LEFT ANTI JOIN orders USING (order_id)"),
    ("order_items", "fk_products", "error",
     "SELECT count(*) FROM order_items LEFT ANTI JOIN products USING (product_id)"),
    ("order_items", "fk_sellers", "error",
     "SELECT count(*) FROM order_items LEFT ANTI JOIN sellers USING (seller_id)"),
    ("order_payments", "fk_orders", "error",
     "SELECT count(*) FROM order_payments LEFT ANTI JOIN orders USING (order_id)"),
    ("order_reviews", "fk_orders", "error",
     "SELECT count(*) FROM order_reviews LEFT ANTI JOIN orders USING (order_id)"),
    ("orders", "fk_customers", "error",
     "SELECT count(*) FROM orders LEFT ANTI JOIN customers USING (customer_id)"),
    # Cleaning worked
    ("products", "category_filled", "error",
     "SELECT count(*) FROM products WHERE product_category_name IS NULL OR product_category_name_english IS NULL"),
    ("orders", "delivered_after_purchase", "error",
     "SELECT count(*) FROM orders WHERE order_delivered_customer_date < order_purchase_timestamp"),
    # Known defects, kept and tracked
    ("orders", "delivered_before_approval", "warn",
     "SELECT count(*) FROM orders WHERE order_delivered_customer_date < order_approved_at"),
    ("orders", "carrier_before_purchase", "warn",
     "SELECT count(*) FROM orders WHERE order_delivered_carrier_date < order_purchase_timestamp"),
    ("orders", "paid_without_items", "warn",
     "SELECT count(DISTINCT order_id) FROM order_payments LEFT ANTI JOIN order_items USING (order_id)"),
    ("orders", "without_payment", "warn",
     "SELECT count(*) FROM orders LEFT ANTI JOIN order_payments USING (order_id)"),
    ("order_payments", "zero_value", "warn",
     "SELECT count(*) FROM order_payments WHERE payment_value = 0"),
    ("customers", "zip_prefix_without_geolocation", "warn",
     "SELECT count(*) FROM customers c LEFT ANTI JOIN geolocation g "
     "ON c.customer_zip_code_prefix = g.geolocation_zip_code_prefix"),
    ("quarantine", "quarantined_rows", "warn", "SELECT count(*) FROM quarantine"),
]


def run_checks(spark: SparkSession, tables: dict[str, DataFrame], checks=CHECKS) -> DataFrame:
    """Run checks against the given tables (registered as temp views). Returns one row per check."""
    for name, df in tables.items():
        df.createOrReplaceTempView(name)
    run_id = str(uuid.uuid4())
    rows = []
    for table, check, severity, sql in checks:
        failed = spark.sql(sql).first()[0]
        status = "pass" if failed == 0 else ("fail" if severity == "error" else "warn")
        rows.append((run_id, table, check, severity, failed, status))
    return spark.createDataFrame(
        rows, "run_id STRING, table STRING, check_name STRING, severity STRING, failed_rows BIGINT, status STRING"
    ).withColumn("run_ts", F.current_timestamp())


def check_silver(spark: SparkSession) -> None:
    """Run CHECKS on Silver, append the results to gold.dq_results, raise if an 'error' check fails."""
    tables = {t: read_table(spark, "silver", t) for t in SILVER_TABLES}
    results = run_checks(spark, tables)  # no .cache(): unsupported on serverless, rows are already computed
    write_table(results, "gold", "dq_results", mode="append")  # history: one batch per run
    results.select("table", "check_name", "severity", "failed_rows", "status").show(len(CHECKS), truncate=False)
    failed = [r.check_name for r in results.where("status = 'fail'").collect()]
    if failed:
        raise RuntimeError(f"Blocking data quality checks failed: {failed}")


if __name__ == "__main__":
    check_silver(get_spark("olist-quality"))
