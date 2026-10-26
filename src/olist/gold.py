"""Gold: star schema (2 facts sharing 4 dimensions) built from Silver, then checked by sql/checks.sql.

Diagram: docs/star_schema.svg. Decisions: ADR-006.
"""

import shutil
from pathlib import Path

from pyspark.sql import Column, DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from olist.config import read_table, write_table
from olist.spark import get_spark

POWERBI_DIR = "data/powerbi"
# Relative to the repo, not the working directory: a Databricks notebook runs from notebooks/.
CHECKS_SQL = str(Path(__file__).resolve().parents[2] / "sql" / "checks.sql")


def with_key(df: DataFrame, key: str, natural_key: str) -> DataFrame:
    """Surrogate key 1..n in natural-key order: a rebuild on the same data gives the same keys."""
    # ponytail: global window = one partition. Fine for 100k rows, use xxhash64(natural_key) beyond millions.
    return df.withColumn(key, F.row_number().over(Window.orderBy(natural_key))).select(key, *df.columns)


def date_key(col: str) -> Column:
    return F.date_format(col, "yyyyMMdd").cast("int")


def geo(prefix_col: str, geolocation: DataFrame) -> DataFrame:
    return geolocation.select(
        F.col("geolocation_zip_code_prefix").alias(prefix_col),
        F.col("geolocation_lat").alias("lat"),
        F.col("geolocation_lng").alias("lng"),
    )


def build_dim_customer(customers: DataFrame, orders: DataFrame, geolocation: DataFrame) -> DataFrame:
    """One row per real customer (customer_unique_id), with the address of their latest order."""
    latest = Window.partitionBy("customer_unique_id").orderBy(F.desc("order_purchase_timestamp"), "customer_id")
    df = (
        customers.join(orders.select("customer_id", "order_purchase_timestamp"), "customer_id")
        .withColumn("_rn", F.row_number().over(latest))
        .where("_rn = 1")
        .join(geo("customer_zip_code_prefix", geolocation), "customer_zip_code_prefix", "left")
        .select(
            "customer_unique_id",
            F.col("customer_city").alias("city"),
            F.col("customer_state").alias("state"),
            "lat",
            "lng",
        )
    )
    return with_key(df, "customer_key", "customer_unique_id")


def build_dim_seller(sellers: DataFrame, geolocation: DataFrame) -> DataFrame:
    df = sellers.join(geo("seller_zip_code_prefix", geolocation), "seller_zip_code_prefix", "left").select(
        "seller_id", F.col("seller_city").alias("city"), F.col("seller_state").alias("state"), "lat", "lng"
    )
    return with_key(df, "seller_key", "seller_id")


def build_dim_product(products: DataFrame) -> DataFrame:
    df = products.select(
        "product_id",
        F.col("product_category_name").alias("category_pt"),
        F.col("product_category_name_english").alias("category_en"),
        F.col("product_weight_g").alias("weight_g"),
        (F.col("product_length_cm") * F.col("product_height_cm") * F.col("product_width_cm")).alias("volume_cm3"),
    )
    return with_key(df, "product_key", "product_id")


def build_dim_date(orders: DataFrame) -> DataFrame:
    """Every day of every full year with purchases (Power BI time intelligence needs whole years)."""
    first, last = F.to_date(F.min("order_purchase_timestamp")), F.to_date(F.max("order_purchase_timestamp"))
    days = orders.agg(
        F.sequence(F.trunc(first, "year"), F.date_sub(F.add_months(F.trunc(last, "year"), 12), 1)).alias("d")
    ).select(F.explode("d").alias("date"))
    return days.select(
        date_key("date").alias("date_key"),
        "date",
        F.year("date").alias("year"),
        F.quarter("date").alias("quarter"),
        F.month("date").alias("month"),
        F.weekofyear("date").alias("week"),
        ((F.dayofweek("date") + 5) % 7 + 1).alias("day_of_week"),  # 1 = Monday ... 7 = Sunday
        F.dayofweek("date").isin(1, 7).alias("is_weekend"),
    )


def build_fact_order_items(
    items: DataFrame, orders: DataFrame, customers: DataFrame,
    dim_customer: DataFrame, dim_product: DataFrame, dim_seller: DataFrame,
) -> DataFrame:
    # Inner joins are safe: Silver checks guarantee every foreign key exists (quality.py).
    return (
        items.join(orders.select("order_id", "customer_id", "order_purchase_timestamp"), "order_id")
        .join(customers.select("customer_id", "customer_unique_id"), "customer_id")
        .join(dim_customer.select("customer_key", "customer_unique_id"), "customer_unique_id")
        .join(dim_product.select("product_key", "product_id"), "product_id")
        .join(dim_seller.select("seller_key", "seller_id"), "seller_id")
        .select(
            "order_id", "order_item_id", "product_key", "seller_key", "customer_key",
            date_key("order_purchase_timestamp").alias("purchase_date_key"), "price", "freight_value",
        )
    )


def build_fact_orders(
    orders: DataFrame, items: DataFrame, payments: DataFrame, reviews: DataFrame,
    customers: DataFrame, dim_customer: DataFrame,
) -> DataFrame:
    item_totals = items.groupBy("order_id").agg(
        F.count("*").alias("nb_items"), F.sum("price").alias("order_value"), F.sum("freight_value").alias("freight_total")
    )
    biggest_first = Window.partitionBy("order_id").orderBy(F.desc("payment_value"), "payment_sequential")
    payment_totals = (
        payments.withColumn("_rn", F.row_number().over(biggest_first))
        .groupBy("order_id")
        .agg(
            F.sum("payment_value").alias("payment_total"),
            F.max(F.when(F.col("_rn") == 1, F.col("payment_type"))).alias("payment_type_main"),
            F.max("payment_installments").alias("installments_max"),
        )
    )
    purchased, estimated = F.to_date("order_purchase_timestamp"), F.to_date("order_estimated_delivery_date")
    delivered = F.to_date("order_delivered_customer_date")
    # Late = delivered after the promised DAY (the estimate is always at midnight), ADR-006.
    delay_days = F.datediff(delivered, estimated)
    return (
        orders.join(customers.select("customer_id", "customer_unique_id"), "customer_id")
        .join(dim_customer.select("customer_key", "customer_unique_id"), "customer_unique_id")
        .join(item_totals, "order_id", "left")
        .join(payment_totals, "order_id", "left")
        .join(reviews.select("order_id", "review_score"), "order_id", "left")
        .select(
            "order_id",
            "customer_key",
            date_key("order_purchase_timestamp").alias("purchase_date_key"),
            "order_status",
            "delivery_status",
            F.coalesce("nb_items", F.lit(0)).alias("nb_items"),
            F.coalesce("order_value", F.lit(0)).alias("order_value"),
            F.coalesce("freight_total", F.lit(0)).alias("freight_total"),
            F.coalesce("payment_total", F.lit(0)).alias("payment_total"),
            "payment_type_main",
            "installments_max",
            F.datediff(delivered, purchased).alias("delivery_days"),
            F.datediff(estimated, purchased).alias("estimated_days"),
            delay_days.alias("delay_days"),
            (delay_days > 0).alias("is_late"),  # null when not delivered
            "review_score",
            (F.col("review_score") <= 2).alias("is_negative_review"),  # null when no review
        )
    )


def run_sql_checks(spark: SparkSession, path: str = CHECKS_SQL) -> list:
    """Run each query of the checks file (one row: check_name, actual, passed). Raise if one fails."""
    sql = "\n".join(line for line in Path(path).read_text(encoding="utf-8").splitlines()
                    if not line.strip().startswith("--"))
    # By position: only the first query of the file needs to name its columns.
    results = [tuple(spark.sql(stmt).first()) for stmt in sql.split(";") if stmt.strip()]
    for name, actual, passed in results:
        print(f"{'PASS' if passed else 'FAIL'}  {name:<44}{actual}")
    failed = [name for name, _, passed in results if not passed]
    if failed:
        raise RuntimeError(f"Gold checks failed: {failed}")
    return results


def export_for_powerbi(tables: dict[str, DataFrame], out_dir: str = POWERBI_DIR) -> None:
    """Power BI Desktop has no built-in reader for a local Delta folder: write one plain Parquet file per table."""
    for name, df in tables.items():
        tmp = f"{out_dir}/_tmp_{name}"
        df.coalesce(1).write.mode("overwrite").parquet(tmp)
        shutil.move(next(Path(tmp).glob("part-*.parquet")), f"{out_dir}/{name}.parquet")
        shutil.rmtree(tmp)


def build(spark: SparkSession) -> dict[str, DataFrame]:
    s = {t: read_table(spark, "silver", t) for t in
         ["orders", "order_items", "order_payments", "order_reviews", "customers", "sellers", "products", "geolocation"]}
    dim_customer = build_dim_customer(s["customers"], s["orders"], s["geolocation"])
    dim_seller = build_dim_seller(s["sellers"], s["geolocation"])
    dim_product = build_dim_product(s["products"])
    tables = {
        "dim_date": build_dim_date(s["orders"]),
        "dim_customer": dim_customer,
        "dim_seller": dim_seller,
        "dim_product": dim_product,
        "fact_orders": build_fact_orders(s["orders"], s["order_items"], s["order_payments"], s["order_reviews"],
                                         s["customers"], dim_customer),
        "fact_order_items": build_fact_order_items(s["order_items"], s["orders"], s["customers"],
                                                   dim_customer, dim_product, dim_seller),
    }
    for name, df in tables.items():
        write_table(df, "gold", name)
    # Re-read from Delta so checks and export see exactly what was written.
    written = {name: read_table(spark, "gold", name) for name in tables}
    for name, df in {**written, **{f"silver_{t}": df for t, df in s.items()}}.items():
        df.createOrReplaceTempView(name)
    return written


if __name__ == "__main__":
    spark = get_spark("olist-gold")
    gold = build(spark)
    run_sql_checks(spark)
    export_for_powerbi(gold)
    for name, df in gold.items():
        print(f"{name:<18}{df.count():>8}")
