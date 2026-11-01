import numpy as np
import pandas as pd
import pytest

from olist.ml.features import (
    backtest_folds,
    build_features,
    dataset_label,
    haversine_km,
    prior_history,
    recent_late_rate,
)

T = pd.Timestamp


def test_haversine_sao_paulo_rio():
    assert haversine_km(-23.55, -46.63, -22.91, -43.17) == pytest.approx(357, abs=10)


def test_seller_history_only_counts_deliveries_known_at_purchase():
    lines = pd.DataFrame({
        "order_id": ["a", "b", "c", "d"],
        "seller_id": ["s"] * 4,
        "purchase_ts": [T("2018-01-01"), T("2018-01-05"), T("2018-01-15"), T("2018-01-14")],
    })
    outcomes = pd.DataFrame({
        "order_id": ["a", "b", "c", "d"],
        # a: delivered late on the 10th. b: still on its way when c is bought. d: delivered exactly at c's purchase.
        "delivered_ts": [T("2018-01-10"), T("2018-01-20"), T("2018-01-25"), T("2018-01-15")],
        "is_late": [True, False, False, False],
    })
    h = prior_history(lines, outcomes, by="seller_id").set_index("order_id")
    assert h.loc["b", "prior_orders"] == 0  # a was bought before b but not delivered yet
    assert pd.isna(h.loc["b", "prior_late_rate"])
    assert h.loc["c", "prior_orders"] == 1  # only a; b not delivered, d delivered at the same instant
    assert h.loc["c", "prior_late_rate"] == 1.0


def test_recent_late_rate_uses_the_30_days_before_purchase_only():
    outcomes = pd.DataFrame({
        "delivered_ts": [T("2018-01-01"), T("2018-01-20"), T("2018-01-25"), T("2018-02-10")],
        "is_late": [True, True, False, True],
    })
    rates = recent_late_rate(pd.Series([T("2018-02-05"), T("2017-12-01")]), outcomes)
    assert rates[0] == pytest.approx(0.5)  # 20th (late) and 25th (on time); the 1st is >30 days, the 10th is later
    assert np.isnan(rates[1])  # nothing delivered yet


def test_dataset_label_is_temporal_and_skips_unlabeled():
    df = pd.DataFrame({
        "purchase_ts": [T("2018-05-31 23:59"), T("2018-06-01"), T("2018-07-01")],
        "order_status": ["delivered", "delivered", "canceled"],
        "is_late": [True, False, None],
    })
    assert dataset_label(df).tolist() == ["fit", "test", "unlabeled"]


def test_backtest_folds_train_on_the_past_and_stop_before_test():
    df = pd.DataFrame({
        "purchase_ts": pd.date_range("2017-01-01", "2018-08-31", freq="7D"),
        "order_status": "delivered", "is_late": False,
    })
    folds = backtest_folds(df)
    assert len(folds) == 8
    for train, month in folds:
        assert train["purchase_ts"].max() < month["purchase_ts"].min()
        assert month["purchase_ts"].max() < T("2018-06-01")


def test_build_features_one_row_per_order_with_main_item():
    orders = pd.DataFrame({
        "order_id": ["o1", "o2"], "customer_id": ["c1", "c2"],
        "order_purchase_timestamp": [T("2018-02-01 10:00"), T("2018-02-02")],
        "order_estimated_delivery_date": [T("2018-02-11 10:00"), T("2018-02-20")],
        "order_delivered_customer_date": [T("2018-02-09"), pd.NaT],
    })
    items = pd.DataFrame({  # o1: 2 items from 2 sellers, the RJ one is pricier. o2: no item.
        "order_id": ["o1", "o1"], "order_item_id": [1, 2], "product_id": ["p1", "p2"],
        "seller_id": ["s_sp", "s_rj"], "price": [10.0, 50.0],
    })
    customers = pd.DataFrame({"customer_id": ["c1", "c2"], "customer_zip_code_prefix": ["01000", "01000"],
                              "customer_state": ["SP", "SP"]})
    sellers = pd.DataFrame({"seller_id": ["s_sp", "s_rj"], "seller_zip_code_prefix": ["01000", "20000"],
                            "seller_state": ["SP", "RJ"]})
    products = pd.DataFrame({"product_id": ["p1", "p2"], "product_category_name_english": ["toys", "audio"],
                             "product_weight_g": [100, 200], "product_length_cm": [10, 10],
                             "product_height_cm": [10, 10], "product_width_cm": [10, 10]})
    geolocation = pd.DataFrame({"geolocation_zip_code_prefix": ["01000", "20000"],
                                "geolocation_lat": [-23.55, -22.91], "geolocation_lng": [-46.63, -43.17]})
    fact_orders = pd.DataFrame({
        "order_id": ["o1", "o2"], "order_status": ["delivered", "unavailable"], "is_late": [False, None],
        "order_value": [60.0, 0.0], "freight_total": [6.0, 0.0], "nb_items": [2, 0],
        "payment_type_main": ["credit_card", "boleto"], "installments_max": [3, 1],
    })
    df = build_features(orders, items, customers, sellers, products, geolocation, fact_orders).set_index("order_id")

    assert len(df) == 2
    o1 = df.loc["o1"]
    assert (o1["seller_state"], o1["category"], o1["nb_sellers"]) == ("RJ", "audio", 2)
    assert o1["distance_km"] == pytest.approx(357, abs=10)  # max over the order's sellers
    assert o1["estimated_days"] == pytest.approx(10.0)
    assert o1["weight_g"] == 300 and o1["freight_ratio"] == pytest.approx(0.1)
    assert df.loc["o2", "seller_state"] == "unknown"  # undelivered order without items is kept for scoring
