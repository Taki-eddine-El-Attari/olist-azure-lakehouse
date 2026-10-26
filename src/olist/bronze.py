"""Bronze: raw Olist CSVs -> Delta, typed by an explicit schema, plus ingestion metadata."""

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from olist.spark import get_spark

RAW_DIR = "data/raw"
BRONZE_DIR = "data/lake/bronze"

# Bronze table -> (CSV file, schema in CSV column order). Source column names are kept as is
# (typos included). Zip prefixes stay strings to keep leading zeros; money is DECIMAL, not DOUBLE.
TABLES = {
    "orders": (
        "olist_orders_dataset.csv",
        "order_id STRING, customer_id STRING, order_status STRING, "
        "order_purchase_timestamp TIMESTAMP, order_approved_at TIMESTAMP, "
        "order_delivered_carrier_date TIMESTAMP, order_delivered_customer_date TIMESTAMP, "
        "order_estimated_delivery_date TIMESTAMP",
    ),
    "order_items": (
        "olist_order_items_dataset.csv",
        "order_id STRING, order_item_id INT, product_id STRING, seller_id STRING, "
        "shipping_limit_date TIMESTAMP, price DECIMAL(10,2), freight_value DECIMAL(10,2)",
    ),
    "order_payments": (
        "olist_order_payments_dataset.csv",
        "order_id STRING, payment_sequential INT, payment_type STRING, "
        "payment_installments INT, payment_value DECIMAL(10,2)",
    ),
    "order_reviews": (
        "olist_order_reviews_dataset.csv",
        "review_id STRING, order_id STRING, review_score INT, review_comment_title STRING, "
        "review_comment_message STRING, review_creation_date TIMESTAMP, "
        "review_answer_timestamp TIMESTAMP",
    ),
    "customers": (
        "olist_customers_dataset.csv",
        "customer_id STRING, customer_unique_id STRING, customer_zip_code_prefix STRING, "
        "customer_city STRING, customer_state STRING",
    ),
    "products": (
        "olist_products_dataset.csv",
        "product_id STRING, product_category_name STRING, product_name_lenght INT, "
        "product_description_lenght INT, product_photos_qty INT, product_weight_g INT, "
        "product_length_cm INT, product_height_cm INT, product_width_cm INT",
    ),
    "sellers": (
        "olist_sellers_dataset.csv",
        "seller_id STRING, seller_zip_code_prefix STRING, seller_city STRING, seller_state STRING",
    ),
    "geolocation": (
        "olist_geolocation_dataset.csv",
        "geolocation_zip_code_prefix STRING, geolocation_lat DOUBLE, geolocation_lng DOUBLE, "
        "geolocation_city STRING, geolocation_state STRING",
    ),
    "category_translation": (
        "product_category_name_translation.csv",
        "product_category_name STRING, product_category_name_english STRING",
    ),
}


def read_csv(spark: SparkSession, path: str, schema: str) -> DataFrame:
    """Read one Olist CSV. FAILFAST: a value that does not fit the schema stops the run."""
    return (
        spark.read.schema(schema)
        .option("header", True)
        # Review comments contain line breaks inside quotes: without multiLine, 99 224 reviews
        # become 104 719 broken rows.
        .option("multiLine", True)
        .option("quote", '"')
        .option("escape", '"')
        .option("timestampFormat", "yyyy-MM-dd HH:mm:ss")
        .option("mode", "FAILFAST")
        .csv(path)
        .withColumn("_ingested_at", F.current_timestamp())
        .withColumn("_source_file", F.col("_metadata.file_path"))
    )


def ingest(spark: SparkSession, raw_dir: str = RAW_DIR, bronze_dir: str = BRONZE_DIR) -> dict[str, int]:
    """Overwrite every Bronze table from its CSV (the source is a full snapshot). Returns row counts."""
    counts = {}
    for table, (file_name, schema) in TABLES.items():
        path = f"{bronze_dir}/{table}"
        read_csv(spark, f"{raw_dir}/{file_name}", schema).write.format("delta").mode("overwrite").save(path)
        counts[table] = spark.read.format("delta").load(path).count()
    return counts


if __name__ == "__main__":
    for table, n in ingest(get_spark("olist-bronze")).items():
        print(f"{table:<22}{n:>10}")
