# Local dev image aligned on Databricks Runtime 18 LTS ML (Python 3.12, Java 21, Spark 4.1, Delta 4.2).
FROM python:3.12-slim-trixie

RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-21-jre-headless \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Pre-download the Delta JARs from Maven so sessions start offline.
RUN python -c "from delta import configure_spark_with_delta_pip; from pyspark.sql import SparkSession; configure_spark_with_delta_pip(SparkSession.builder.master('local[1]')).getOrCreate().stop()"

WORKDIR /workspace
