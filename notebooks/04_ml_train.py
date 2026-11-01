# Databricks notebook source
# MAGIC %md
# MAGIC # 04 — Entraînement du modèle de retard
# MAGIC Features au moment de l'achat → 5 modèles comparés dans l'expérience MLflow `/Shared/olist_late_delivery` →
# MAGIC le meilleur au backtest glissant devient `olist.ml.late_delivery@champion`. Logique : `src/olist/ml/`.
# MAGIC Environnement serverless : **base ML** (LightGBM n'est pas dans la base standard).

# COMMAND ----------

import os
import sys

sys.path.insert(0, os.path.abspath("../src"))

from olist.ml.train import main

_ = main()  # the metrics table is printed; `_ =` stops the notebook echoing the DataFrame
