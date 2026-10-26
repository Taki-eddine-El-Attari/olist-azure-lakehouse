"""Where data lives. Locally (Docker): Delta folders under data/lake. On Databricks: Unity Catalog
tables olist.<layer>.<table>, and raw CSVs in the UC volume olist.landing.raw (= landing/olist/ in ADLS)."""

import os

from pyspark.sql import DataFrame, SparkSession

ON_DATABRICKS = "DATABRICKS_RUNTIME_VERSION" in os.environ
CATALOG = "olist"
LAKE_DIR = "data/lake"
RAW_DIR = "/Volumes/olist/landing/raw" if ON_DATABRICKS else "data/raw"


def read_table(spark: SparkSession, layer: str, name: str) -> DataFrame:
    if ON_DATABRICKS:
        return spark.read.table(f"{CATALOG}.{layer}.{name}")
    return spark.read.format("delta").load(f"{LAKE_DIR}/{layer}/{name}")


def write_table(df: DataFrame, layer: str, name: str, mode: str = "overwrite") -> None:
    writer = df.write.format("delta").mode(mode)
    if mode == "overwrite":
        writer = writer.option("overwriteSchema", True)
    if ON_DATABRICKS:
        writer.saveAsTable(f"{CATALOG}.{layer}.{name}")
    else:
        writer.save(f"{LAKE_DIR}/{layer}/{name}")
