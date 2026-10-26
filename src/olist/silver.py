"""Silver: cleaned, conformed tables built from Bronze. One pure function per rule set (see ADR-005)."""

from functools import reduce

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from olist.config import read_table, write_table
from olist.spark import get_spark

# Two categories used by products are missing from the translation file (ADR-004).
MANUAL_TRANSLATIONS = [
    ("pc_gamer", "pc_gamer"),
    ("portateis_cozinha_e_preparadores_de_alimentos", "portable_kitchen_and_food_preparers"),
]

# Row rules: a row matching the condition is invalid and goes to quarantine instead of Silver.
ROW_RULES = {
    "geolocation": {
        "outside_brazil": "NOT (geolocation_lat BETWEEN -34 AND 6 AND geolocation_lng BETWEEN -74 AND -34)",
    },
    "order_items": {"negative_amount": "price < 0 OR freight_value < 0"},
    "order_payments": {"negative_amount": "payment_value < 0"},
}


def split_invalid(df: DataFrame, table: str) -> tuple[DataFrame, DataFrame]:
    """Return (valid rows, quarantine rows). Quarantine keeps the full row as JSON + the rule broken."""
    rules = ROW_RULES.get(table, {})
    if not rules:
        return df, None
    broken = F.concat_ws(",", *[F.when(F.expr(cond), F.lit(name)) for name, cond in rules.items()])
    flagged = df.withColumn("_rule", broken)
    quarantine = flagged.where("_rule != ''").select(
        F.lit(table).alias("table"),
        "_rule",
        F.to_json(F.struct(*df.columns)).alias("record"),
        F.current_timestamp().alias("_quarantined_at"),
    )
    return flagged.where("_rule = ''").drop("_rule"), quarantine


def clean_orders(orders: DataFrame) -> DataFrame:
    # 8 orders are 'delivered' with no delivery date: the date, not the status, decides.
    return orders.withColumn(
        "delivery_status",
        F.when(F.col("order_delivered_customer_date").isNotNull(), "delivered").otherwise("not_delivered"),
    )


def clean_reviews(reviews: DataFrame) -> DataFrame:
    """One review per order: the most recent. Key is (review_id, order_id), so a review_id
    shared by several orders is kept once per order, never dropped."""
    latest_first = Window.partitionBy("order_id").orderBy(
        F.desc("review_creation_date"), F.desc("review_answer_timestamp"), "review_id"
    )
    return reviews.withColumn("_rn", F.row_number().over(latest_first)).where("_rn = 1").drop("_rn")


def clean_products(products: DataFrame, translation: DataFrame) -> DataFrame:
    manual = translation.sparkSession.createDataFrame(MANUAL_TRANSLATIONS, translation.columns)
    return (
        products.join(F.broadcast(translation.unionByName(manual)), "product_category_name", "left")
        .withColumn("product_category_name", F.coalesce("product_category_name", F.lit("unknown")))
        .withColumn(
            "product_category_name_english", F.coalesce("product_category_name_english", F.lit("unknown"))
        )
        # Fix the source's typos once, here, so Gold and the ML code use clean names.
        .withColumnRenamed("product_name_lenght", "product_name_length")
        .withColumnRenamed("product_description_lenght", "product_description_length")
    )


def clean_geolocation(geolocation: DataFrame) -> DataFrame:
    """One point per zip prefix: median lat/lng (robust to the remaining stray points)."""
    return geolocation.groupBy("geolocation_zip_code_prefix").agg(
        F.median("geolocation_lat").alias("geolocation_lat"),
        F.median("geolocation_lng").alias("geolocation_lng"),
    )


def build(spark: SparkSession) -> dict[str, int]:
    """Rebuild every Silver table and the quarantine table from Bronze. Returns row counts."""

    def bronze(table: str) -> DataFrame:
        return read_table(spark, "bronze", table).drop("_ingested_at", "_source_file")

    valid, quarantines = {}, []
    for table in ["orders", "order_items", "order_payments", "order_reviews", "customers", "sellers",
                  "products", "geolocation"]:
        valid[table], quarantine = split_invalid(bronze(table), table)
        if quarantine is not None:
            quarantines.append(quarantine)

    tables = {
        "orders": clean_orders(valid["orders"]),
        "order_items": valid["order_items"],
        "order_payments": valid["order_payments"],
        "order_reviews": clean_reviews(valid["order_reviews"]),
        "customers": valid["customers"],
        "sellers": valid["sellers"],
        "products": clean_products(valid["products"], bronze("category_translation")),
        "geolocation": clean_geolocation(valid["geolocation"]),
        "quarantine": reduce(DataFrame.unionByName, quarantines),
    }
    counts = {}
    for table, df in tables.items():
        write_table(df, "silver", table)
        counts[table] = read_table(spark, "silver", table).count()
    return counts


if __name__ == "__main__":
    for table, n in build(get_spark("olist-silver")).items():
        print(f"{table:<16}{n:>10}")
