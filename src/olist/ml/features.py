"""ML features: one row per order, built only from what is known at purchase time (ADR-010).

The target `is_late` is read from gold.fact_orders, so the model learns the exact definition used by
checks.sql and Power BI (late = delivered after the promised day, ADR-006). pandas is enough for 100k orders.
"""

import numpy as np
import pandas as pd
from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from olist.config import read_table

# Temporal split on the purchase date, never random: the model is always tested on later orders.
# Before TEST_START: rolling backtest (model choice, threshold), then the final fit. From TEST_START: test only.
TEST_START = pd.Timestamp("2018-06-01")

# No purchase month: with a temporal split it only memorises 2018's February-March spike (14-19 % late),
# which never repeats in validation or test. recent_late_rate_30d carries that kind of shock instead.
NUMERIC = [
    "estimated_days", "distance_km", "order_value", "freight_total", "freight_ratio", "nb_items", "nb_sellers",
    "weight_g", "volume_cm3", "installments_max", "purchase_dow", "purchase_hour",
    "seller_prior_orders", "seller_prior_late_rate", "route_prior_orders", "route_prior_late_rate",
    "recent_late_rate_30d",
]
CATEGORICAL = ["customer_state", "seller_state", "category", "payment_type"]
FEATURES = NUMERIC + CATEGORICAL

# Order-level columns allowed from gold.fact_orders: all known at checkout. Delivery dates, final status
# and review are deliberately absent; order_status / is_late only select and label the training rows.
FACT_ORDERS_COLUMNS = ["order_id", "order_status", "is_late", "order_value", "freight_total", "nb_items",
                       "payment_type_main", "installments_max"]


def haversine_km(lat1, lng1, lat2, lng2):
    lat1, lng1, lat2, lng2 = map(np.radians, (lat1, lng1, lat2, lng2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lng2 - lng1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def prior_history(lines: pd.DataFrame, outcomes: pd.DataFrame, by: str) -> pd.DataFrame:
    """For each (order_id, <by>, purchase_ts): how many orders of the same <by> (a seller, a route) were
    delivered strictly before this purchase, and the late share among them. An order bought earlier but still
    on its way is not counted: its outcome was unknown when this customer clicked "buy"."""
    events = (
        lines[["order_id", by]].merge(outcomes, on="order_id")
        .dropna(subset=["delivered_ts", "is_late"])
        .sort_values("delivered_ts")
    )
    events["prior_orders"] = events.groupby(by).cumcount() + 1
    events["prior_late"] = events["is_late"].astype(float).groupby(events[by]).cumsum()
    hist = pd.merge_asof(
        lines.sort_values("purchase_ts"),
        events[[by, "delivered_ts", "prior_orders", "prior_late"]],
        left_on="purchase_ts", right_on="delivered_ts", by=by,
        direction="backward", allow_exact_matches=False,
    )
    hist["prior_orders"] = hist["prior_orders"].fillna(0)
    hist["prior_late_rate"] = hist["prior_late"] / hist["prior_orders"].where(hist["prior_orders"] > 0)
    return hist[["order_id", "prior_orders", "prior_late_rate"]]


def recent_late_rate(purchase_ts: pd.Series, outcomes: pd.DataFrame, days: int = 30) -> np.ndarray:
    """Late share of all deliveries completed in the `days` before each purchase (state of the network)."""
    events = outcomes.dropna(subset=["delivered_ts", "is_late"]).sort_values("delivered_ts")
    delivered = events["delivered_ts"].to_numpy()
    late_before = np.concatenate([[0.0], np.cumsum(events["is_late"].astype(float).to_numpy())])

    def counts(ts):  # deliveries and late ones strictly before ts
        n = np.searchsorted(delivered, ts.to_numpy(), side="left")
        return n, late_before[n]

    n_now, late_now = counts(purchase_ts)
    n_then, late_then = counts(purchase_ts - pd.Timedelta(days=days))
    n = n_now - n_then
    return np.where(n > 0, (late_now - late_then) / np.maximum(n, 1), np.nan)


def build_features(orders, items, customers, sellers, products, geolocation, fact_orders) -> pd.DataFrame:
    """One row per order (all orders, also the undelivered ones, so they can be scored)."""
    geo = geolocation.set_index("geolocation_zip_code_prefix")[["geolocation_lat", "geolocation_lng"]]
    o = orders.rename(columns={"order_purchase_timestamp": "purchase_ts",
                               "order_estimated_delivery_date": "estimated_ts",
                               "order_delivered_customer_date": "delivered_ts"})
    # The customer's address at the time of this order (customer_id is per order), not their latest one.
    o = o.merge(customers[["customer_id", "customer_zip_code_prefix", "customer_state"]], on="customer_id")
    o = o.join(geo, on="customer_zip_code_prefix").rename(columns={"geolocation_lat": "c_lat",
                                                                   "geolocation_lng": "c_lng"})

    lines = (
        items.merge(sellers[["seller_id", "seller_zip_code_prefix", "seller_state"]], on="seller_id")
        .join(geo, on="seller_zip_code_prefix")
        .merge(products, on="product_id", how="left")
        .merge(o[["order_id", "purchase_ts", "c_lat", "c_lng"]], on="order_id")
    )
    lines["distance_km"] = haversine_km(lines["c_lat"], lines["c_lng"],
                                        lines["geolocation_lat"], lines["geolocation_lng"])
    lines["volume_cm3"] = lines["product_length_cm"] * lines["product_height_cm"] * lines["product_width_cm"]
    per_order = lines.groupby("order_id").agg(
        distance_km=("distance_km", "max"), nb_sellers=("seller_id", "nunique"),
        weight_g=("product_weight_g", "sum"), volume_cm3=("volume_cm3", "sum"),
    )
    # The most expensive item gives the order its main seller and category.
    main = (lines.sort_values(["order_id", "price", "order_item_id"], ascending=[True, False, True])
            .drop_duplicates("order_id")
            [["order_id", "seller_id", "seller_state", "product_category_name_english", "purchase_ts"]]
            .rename(columns={"product_category_name_english": "category"}))
    outcomes = o[["order_id", "delivered_ts"]].merge(fact_orders[["order_id", "is_late"]], on="order_id")
    main = main.merge(o[["order_id", "customer_state"]], on="order_id")
    main["route"] = main["seller_state"] + ">" + main["customer_state"]
    for key, prefix in [("seller_id", "seller"), ("route", "route")]:
        hist = prior_history(main[["order_id", key, "purchase_ts"]], outcomes, by=key)
        main = main.merge(hist.add_prefix(f"{prefix}_").rename(columns={f"{prefix}_order_id": "order_id"}),
                          on="order_id")

    df = (
        o[["order_id", "purchase_ts", "estimated_ts", "customer_state"]]
        .merge(fact_orders[FACT_ORDERS_COLUMNS], on="order_id")
        .merge(per_order, on="order_id", how="left")
        .merge(main.drop(columns=["seller_id", "purchase_ts", "customer_state", "route"]), on="order_id", how="left")
        .rename(columns={"payment_type_main": "payment_type"})
    )
    df["estimated_days"] = (df["estimated_ts"] - df["purchase_ts"]).dt.total_seconds() / 86400
    df["freight_ratio"] = df["freight_total"] / df["order_value"].where(df["order_value"] > 0)
    df["recent_late_rate_30d"] = recent_late_rate(df["purchase_ts"], outcomes)
    df["purchase_dow"] = df["purchase_ts"].dt.dayofweek
    df["purchase_hour"] = df["purchase_ts"].dt.hour
    df[CATEGORICAL] = df[CATEGORICAL].fillna("unknown")
    return df[["order_id", "purchase_ts", "order_status", "is_late", *FEATURES]]


def dataset_label(df: pd.DataFrame) -> pd.Series:
    """fit / test for labeled orders (same population as Late Rate %), unlabeled otherwise."""
    labeled = (df["order_status"] == "delivered") & df["is_late"].notna()
    return pd.Series(np.select([~labeled, df["purchase_ts"] < TEST_START], ["unlabeled", "fit"], "test"),
                     index=df.index)


def split(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    label = dataset_label(df)
    return {part: df[label == part] for part in ("fit", "test")}


def backtest_folds(df: pd.DataFrame, months: int = 8) -> list[tuple[pd.DataFrame, pd.DataFrame]]:
    """Rolling origin before the test period: for each of the last `months` months before TEST_START,
    train on every labeled order bought earlier and evaluate on that month. Never touches the test period."""
    labeled = split(df)["fit"]
    starts = pd.date_range(end=TEST_START, periods=months + 1, freq="MS")
    return [(labeled[labeled["purchase_ts"] < start],
             labeled[(labeled["purchase_ts"] >= start) & (labeled["purchase_ts"] < end)])
            for start, end in zip(starts[:-1], starts[1:])]


def load(spark: SparkSession) -> pd.DataFrame:
    def table(layer, name, cols, decimals=()):
        # DECIMAL would arrive in pandas as Python Decimal objects: cast to double first.
        return read_table(spark, layer, name).select(
            *[F.col(c).cast("double") if c in decimals else F.col(c) for c in cols]).toPandas()

    return build_features(
        orders=table("silver", "orders", ["order_id", "customer_id", "order_purchase_timestamp",
                                          "order_estimated_delivery_date", "order_delivered_customer_date"]),
        items=table("silver", "order_items", ["order_id", "order_item_id", "product_id", "seller_id", "price"],
                    decimals=["price"]),
        customers=table("silver", "customers", ["customer_id", "customer_zip_code_prefix", "customer_state"]),
        sellers=table("silver", "sellers", ["seller_id", "seller_zip_code_prefix", "seller_state"]),
        products=table("silver", "products", ["product_id", "product_category_name_english", "product_weight_g",
                                              "product_length_cm", "product_height_cm", "product_width_cm"]),
        geolocation=table("silver", "geolocation", ["geolocation_zip_code_prefix", "geolocation_lat",
                                                    "geolocation_lng"]),
        fact_orders=table("gold", "fact_orders", FACT_ORDERS_COLUMNS,
                          decimals=["order_value", "freight_total"]),
    )
