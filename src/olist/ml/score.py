"""Batch scoring: the `champion` model scores every order → gold.fact_late_predictions (ADR-010)."""

import mlflow
import mlflow.sklearn
import pandas as pd
from mlflow import MlflowClient

from olist.config import write_table
from olist.ml.features import FEATURES, dataset_label, load
from olist.ml.train import MODEL_NAME, setup_mlflow
from olist.spark import get_spark


def score(features: pd.DataFrame, model, threshold: float, version: int) -> pd.DataFrame:
    """`dataset` tells Power BI which rows the model never saw: judge it on `test` only."""
    proba = model.predict_proba(features[FEATURES])[:, 1]
    return pd.DataFrame({
        "order_id": features["order_id"].to_numpy(),
        "model_version": version,
        "proba_late": proba,
        "predicted_late": proba >= threshold,
        "dataset": dataset_label(features).to_numpy(),
        "scored_at": pd.Timestamp.now(tz="UTC").tz_localize(None),
    })


def main() -> pd.DataFrame:
    setup_mlflow()
    champion = MlflowClient().get_model_version_by_alias(MODEL_NAME, "champion")
    model = mlflow.sklearn.load_model(f"models:/{MODEL_NAME}@champion")
    spark = get_spark("olist-ml-score")
    predictions = score(load(spark), model, float(champion.tags["threshold"]), int(champion.version))
    write_table(spark.createDataFrame(predictions), "gold", "fact_late_predictions")
    print(predictions.groupby("dataset")["predicted_late"].agg(["count", "mean"]).round(3).to_string())
    return predictions


if __name__ == "__main__":
    main()
