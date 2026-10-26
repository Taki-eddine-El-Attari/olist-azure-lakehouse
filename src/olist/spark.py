import os

from pyspark.sql import SparkSession


def get_spark(app_name: str = "olist") -> SparkSession:
    """On Databricks, return the cluster session. Locally, start Spark with Delta."""
    if "DATABRICKS_RUNTIME_VERSION" in os.environ:
        spark = SparkSession.builder.getOrCreate()
        spark.conf.set("spark.sql.session.timeZone", "UTC")  # same as local: dates must not shift
        return spark

    from delta import configure_spark_with_delta_pip

    builder = (
        SparkSession.builder.appName(app_name)
        .master("local[*]")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        # Olist timestamps carry no zone: keep UTC everywhere, like Databricks, so nothing shifts.
        .config("spark.sql.session.timeZone", "UTC")
    )
    return configure_spark_with_delta_pip(builder).getOrCreate()
