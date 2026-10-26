# Databricks notebook source
# MAGIC %md
# MAGIC # 01 — Bronze
# MAGIC CSV du volume `olist.landing.files` → tables `olist.bronze.*`. La logique est dans `src/olist/bronze.py`.

# COMMAND ----------

import os
import sys

sys.path.insert(0, os.path.abspath("../src"))  # the notebook runs from notebooks/ in the Git folder

from olist.bronze import ingest
from olist.spark import get_spark

for table, n in ingest(get_spark()).items():
    print(f"{table:<22}{n:>10}")
