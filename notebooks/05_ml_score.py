# Databricks notebook source
# MAGIC %md
# MAGIC # 05 — Scoring batch
# MAGIC `olist.ml.late_delivery@champion` score toutes les commandes → `olist.gold.fact_late_predictions`.
# MAGIC Environnement serverless : version 6 + dépendance `lightgbm==4.6.0` (pour recharger le modèle).

# COMMAND ----------

import os
import sys

sys.path.insert(0, os.path.abspath("../src"))

from olist.ml.score import main

_ = main()
