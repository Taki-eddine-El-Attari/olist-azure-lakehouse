# Databricks notebook source
# MAGIC %md
# MAGIC # 03 — Gold
# MAGIC `olist.silver.*` → schéma en étoile `olist.gold.*`, puis `sql/checks.sql` : un contrôle en échec fait échouer la tâche.

# COMMAND ----------

import os
import sys

sys.path.insert(0, os.path.abspath("../src"))

from olist.gold import build, run_sql_checks
from olist.spark import get_spark

spark = get_spark()
for name, df in build(spark).items():
    print(f"{name:<18}{df.count():>8}")
run_sql_checks(spark)
