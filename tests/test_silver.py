from datetime import datetime

from olist.quality import run_checks
from olist.silver import clean_geolocation, clean_orders, clean_products, clean_reviews, split_invalid

T = datetime.fromisoformat


def test_delivery_status_follows_the_date_not_the_status(spark):
    orders = spark.createDataFrame(
        [("o1", "delivered", T("2018-01-05 10:00:00")), ("o2", "delivered", None), ("o3", "canceled", None)],
        "order_id STRING, order_status STRING, order_delivered_customer_date TIMESTAMP",
    )
    got = {r.order_id: r.delivery_status for r in clean_orders(orders).collect()}
    assert got == {"o1": "delivered", "o2": "not_delivered", "o3": "not_delivered"}


def test_reviews_keep_latest_per_order_and_never_drop_a_shared_review_id(spark):
    reviews = spark.createDataFrame(
        [
            ("old", "o1", 1, T("2018-01-01 00:00:00"), T("2018-01-02 00:00:00")),
            ("new", "o1", 5, T("2018-02-01 00:00:00"), T("2018-02-02 00:00:00")),
            ("shared", "o2", 4, T("2018-03-01 00:00:00"), T("2018-03-02 00:00:00")),
            ("shared", "o3", 4, T("2018-03-01 00:00:00"), T("2018-03-02 00:00:00")),
        ],
        "review_id STRING, order_id STRING, review_score INT, review_creation_date TIMESTAMP, "
        "review_answer_timestamp TIMESTAMP",
    )
    got = {r.order_id: r.review_id for r in clean_reviews(reviews).collect()}
    assert got == {"o1": "new", "o2": "shared", "o3": "shared"}


def test_products_unknown_category_manual_translation_and_renamed_columns(spark):
    products = spark.createDataFrame(
        [("p1", "beleza_saude", 40, 200), ("p2", None, None, None), ("p3", "pc_gamer", 10, 50)],
        "product_id STRING, product_category_name STRING, product_name_lenght INT, product_description_lenght INT",
    )
    translation = spark.createDataFrame(
        [("beleza_saude", "health_beauty")], "product_category_name STRING, product_category_name_english STRING"
    )
    out = clean_products(products, translation)
    got = {r.product_id: (r.product_category_name, r.product_category_name_english) for r in out.collect()}
    assert got == {"p1": ("beleza_saude", "health_beauty"), "p2": ("unknown", "unknown"), "p3": ("pc_gamer", "pc_gamer")}
    assert {"product_name_length", "product_description_length"} <= set(out.columns)
    assert not any("lenght" in c for c in out.columns)


def test_geolocation_quarantines_points_outside_brazil_then_takes_the_median(spark):
    geo = spark.createDataFrame(
        [("01037", -23.0, -46.0), ("01037", -23.2, -46.2), ("01037", -23.4, -46.4), ("01037", 42.0, 2.0)],
        "geolocation_zip_code_prefix STRING, geolocation_lat DOUBLE, geolocation_lng DOUBLE",
    )
    valid, quarantine = split_invalid(geo, "geolocation")
    [q] = quarantine.collect()
    assert (q.table, q._rule) == ("geolocation", "outside_brazil") and '"geolocation_lat":42.0' in q.record
    [point] = clean_geolocation(valid).collect()
    assert (point.geolocation_lat, point.geolocation_lng) == (-23.2, -46.2)


def test_error_check_fails_and_warn_check_only_warns(spark):
    orders = spark.createDataFrame([("o1",), ("o1",), ("o2",)], "order_id STRING")
    checks = [
        ("orders", "dup", "error", "SELECT count(*) - count(DISTINCT order_id) FROM orders"),
        ("orders", "dup_warn", "warn", "SELECT count(*) - count(DISTINCT order_id) FROM orders"),
        ("orders", "ok", "error", "SELECT count(*) FROM orders WHERE order_id IS NULL"),
    ]
    got = {r.check_name: (r.failed_rows, r.status) for r in run_checks(spark, {"orders": orders}, checks).collect()}
    assert got == {"dup": (1, "fail"), "dup_warn": (1, "warn"), "ok": (0, "pass")}
