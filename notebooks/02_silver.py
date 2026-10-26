# Databricks notebook source
# MAGIC %md
# MAGIC # 02 — Silver + contrôles qualité
# MAGIC `olist.bronze.*` → `olist.silver.*`, puis contrôles → `olist.gold.dq_results`. Un contrôle `error` en échec fait échouer la tâche.

# COMMAND ----------

import os
import sys

sys.path.insert(0, os.path.abspath("../src"))

from olist.quality import check_silver
from olist.silver import build
from olist.spark import get_spark

spark = get_spark()
for table, n in build(spark).items():
    print(f"{table:<16}{n:>10}")
check_silver(spark)
