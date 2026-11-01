"""Train late-delivery models, compare them in MLflow, register the best one as `champion` (ADR-010).

The champion is chosen by a rolling backtest before the test period; the test period is only read for the
final report. The final model is fitted on everything before the test, its threshold set on the backtest's
out-of-fold predictions.
"""

from pathlib import Path

import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from mlflow import MlflowClient
from mlflow.models import infer_signature
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, confusion_matrix, precision_recall_curve, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, StandardScaler

from olist.config import ON_DATABRICKS
from olist.ml.features import CATEGORICAL, FEATURES, NUMERIC, backtest_folds, load, split
from olist.spark import get_spark

EXPERIMENT = "/Shared/olist_late_delivery" if ON_DATABRICKS else "olist_late_delivery"
MODEL_NAME = "olist.ml.late_delivery" if ON_DATABRICKS else "olist_late_delivery"
LOCAL_MLRUNS = Path(__file__).resolve().parents[3] / "mlruns"


def setup_mlflow() -> None:
    if ON_DATABRICKS:
        mlflow.set_registry_uri("databricks-uc")  # register models in Unity Catalog
    else:
        mlflow.set_tracking_uri(LOCAL_MLRUNS.as_uri())


class KmPerPromisedDay:
    """Baseline rule, nothing learned: the more kilometres per promised day, the riskier the order."""

    def fit(self, X, y):
        return self

    def predict_proba(self, X):
        s = (X["distance_km"] / X["estimated_days"].clip(lower=1)).fillna(0).to_numpy()
        return np.column_stack([-s, s])  # a ranking score, not a probability: only column 1 is used


def logistic():
    pre = ColumnTransformer([
        ("num", make_pipeline(SimpleImputer(strategy="median"), StandardScaler()), NUMERIC),
        ("cat", OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=50), CATEGORICAL),
    ])
    return make_pipeline(pre, LogisticRegression(class_weight="balanced", max_iter=2000))


def lightgbm(scale_pos_weight: float = 1.0, numeric: list[str] = NUMERIC):
    # Categories → integer codes; -1 (unseen or missing) is read as missing by LightGBM.
    pre = ColumnTransformer([
        ("num", "passthrough", numeric),
        ("cat", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1), CATEGORICAL),
    ])
    # ponytail: fixed hyperparameters, no search. Add an Optuna search on the validation set if PR-AUC matters more.
    model = LGBMClassifier(n_estimators=400, learning_rate=0.03, num_leaves=31, min_child_samples=50,
                           subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
                           scale_pos_weight=scale_pos_weight, random_state=42, verbose=-1)
    return make_pipeline(pre, model)


def best_threshold(y, score) -> float:
    """Threshold with the best F1 on the validation period."""
    precision, recall, thresholds = precision_recall_curve(y, score)
    f1 = 2 * precision * recall / np.maximum(precision + recall, 1e-12)
    return float(thresholds[np.argmax(f1[:-1])])


def metrics(y, score, threshold) -> dict[str, float]:
    tn, fp, fn, tp = confusion_matrix(y, score >= threshold, labels=[False, True]).ravel()
    m = {
        "pr_auc": average_precision_score(y, score), "roc_auc": roc_auc_score(y, score),
        "precision": tp / max(tp + fp, 1), "recall": tp / max(tp + fn, 1),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn, "late_rate": np.mean(y),
    }
    return {k: float(v) for k, v in m.items()}


def candidates(y_train) -> dict:
    """Fresh, unfitted models (called once per backtest fold and once for the final fit)."""
    return {
        "baseline_rule": KmPerPromisedDay(),
        "logistic_regression": logistic(),
        "lightgbm": lightgbm(),
        "lightgbm_weighted": lightgbm(scale_pos_weight=float((~y_train).sum() / y_train.sum())),
        "lightgbm_no_recent": lightgbm(numeric=[c for c in NUMERIC if c != "recent_late_rate_30d"]),
    }


def fit(name: str, model, X, y):
    if name.startswith("lightgbm"):
        n_numeric = len(model[0].transformers[0][2])  # categories come right after the numeric columns
        return model.fit(X, y, lgbmclassifier__categorical_feature=list(range(n_numeric, n_numeric + len(CATEGORICAL))))
    return model.fit(X, y)


def labels(d: pd.DataFrame):
    return d["is_late"].astype(bool).to_numpy()


def backtest(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Per backtest month and model: PR-AUC lift (PR-AUC / late rate, comparable across months).
    Also returns the pooled out-of-fold (y, score) per model, used to set the threshold.
    One fixed 2-month validation window was too unstable to pick a model (late rate 7.9 % → 5.5 % → 3.6 %)."""
    rows, oof = [], {}
    for train, month in backtest_folds(df):
        y_train, y_month = labels(train), labels(month)
        for name, model in candidates(y_train).items():
            score = fit(name, model, train[FEATURES], y_train).predict_proba(month[FEATURES])[:, 1]
            rows.append({"month": month["purchase_ts"].min().strftime("%Y-%m"), "model": name,
                         "lift": average_precision_score(y_month, score) / y_month.mean()})
            ys, scores = oof.setdefault(name, ([], []))
            ys.append(y_month)
            scores.append(score)
    oof = {name: (np.concatenate(ys), np.concatenate(scores)) for name, (ys, scores) in oof.items()}
    return pd.DataFrame(rows).pivot(index="month", columns="model", values="lift"), oof


def run(df: pd.DataFrame) -> pd.DataFrame:
    lifts, oof = backtest(df)
    print(lifts.round(2).to_string())
    parts = split(df)
    X = {p: d[FEATURES] for p, d in parts.items()}
    y = {p: labels(d) for p, d in parts.items()}

    mlflow.set_experiment(EXPERIMENT)
    rows = []
    for name, model in candidates(y["fit"]).items():
        with mlflow.start_run(run_name=name) as active:
            fit(name, model, X["fit"], y["fit"])  # same recipe as each backtest fold: all the past
            threshold = best_threshold(*oof[name])
            result = {f"test_{k}": v for k, v in metrics(y["test"], model.predict_proba(X["test"])[:, 1],
                                                          threshold).items()}
            result["backtest_lift"] = float(lifts[name].mean())
            result["backtest_wins"] = float((lifts[name] > lifts["baseline_rule"]).sum())
            result["backtest_pr_auc"] = float(average_precision_score(*oof[name]))
            mlflow.log_params({"model": name, "threshold": threshold, "features": ",".join(FEATURES),
                               "test_start": "2018-06-01", "backtest_months": ",".join(lifts.index),
                               **{f"{p}_rows": len(X[p]) for p in X}})
            mlflow.log_metrics(result)
            if name.startswith("lightgbm"):
                used = model[0].transformers[0][2] + CATEGORICAL
                gain = model[-1].booster_.feature_importance("gain").round(1).tolist()
                mlflow.log_dict(dict(zip(used, gain)), "feature_importance_gain.json")
            if name != "baseline_rule":
                # Unity Catalog requires a signature. No input example: it holds NaN, awkward to serialize.
                sample = X["fit"].head(200)
                mlflow.sklearn.log_model(model, name="model", signature=infer_signature(sample, model.predict(sample)))
            rows.append({"model": name, "run_id": active.info.run_id, "threshold": threshold, **result})
    return pd.DataFrame(rows)


def register_champion(results: pd.DataFrame) -> int:
    """Best mean backtest lift wins. The test period plays no part in the choice."""
    learned = results[results["model"] != "baseline_rule"]
    best = learned.loc[learned["backtest_lift"].idxmax()]
    baseline = results.loc[results["model"] == "baseline_rule", "backtest_lift"].item()
    if best["backtest_lift"] <= baseline:
        raise RuntimeError(f"No model beats the baseline rule in the backtest (mean lift {baseline:.2f})")
    version = mlflow.register_model(f"runs:/{best['run_id']}/model", MODEL_NAME).version
    client = MlflowClient()
    client.set_model_version_tag(MODEL_NAME, version, "threshold", str(best["threshold"]))
    client.set_registered_model_alias(MODEL_NAME, "champion", version)
    print(f"champion: {best['model']} → {MODEL_NAME} v{version}")
    return int(version)


def main() -> pd.DataFrame:
    setup_mlflow()
    results = run(load(get_spark("olist-ml-train")))
    cols = ["model", "backtest_lift", "backtest_wins", "test_pr_auc", "test_late_rate", "test_roc_auc",
            "test_precision", "test_recall", "threshold"]
    print(results[cols].round(3).to_string(index=False))
    register_champion(results)
    return results


if __name__ == "__main__":
    main()
