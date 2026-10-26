from datetime import date, datetime

import pytest

from olist.gold import build_dim_customer, build_dim_date, build_fact_orders, run_sql_checks

T = datetime.fromisoformat
ORDERS_SCHEMA = (
    "order_id STRING, customer_id STRING, order_status STRING, delivery_status STRING, "
    "order_purchase_timestamp TIMESTAMP, order_delivered_customer_date TIMESTAMP, "
    "order_estimated_delivery_date TIMESTAMP"
)


@pytest.fixture
def star(spark):
    orders = spark.createDataFrame(
        [
            # delivered ON the promised day (late by timestamp, on time by day)
            ("o1", "c1", "delivered", "delivered", T("2018-01-01 10:00:00"), T("2018-01-10 15:00:00"), T("2018-01-10 00:00:00")),
            # delivered the day after the promise
            ("o2", "c2", "delivered", "delivered", T("2018-02-01 10:00:00"), T("2018-02-11 09:00:00"), T("2018-02-10 00:00:00")),
            # never delivered, no item, no payment, no review
            ("o3", "c3", "canceled", "not_delivered", T("2018-03-01 10:00:00"), None, T("2018-03-10 00:00:00")),
        ],
        ORDERS_SCHEMA,
    )
    customers = spark.createDataFrame(
        [("c1", "u1", "01037", "sao paulo", "SP"), ("c2", "u1", "20000", "rio de janeiro", "RJ"),
         ("c3", "u2", "99999", "x", "RS")],
        "customer_id STRING, customer_unique_id STRING, customer_zip_code_prefix STRING, customer_city STRING, "
        "customer_state STRING",
    )
    geolocation = spark.createDataFrame(
        [("01037", -23.5, -46.6), ("20000", -22.9, -43.2)],
        "geolocation_zip_code_prefix STRING, geolocation_lat DOUBLE, geolocation_lng DOUBLE",
    )
    items = spark.createDataFrame(
        [("o1", 1, 10.0, 2.0), ("o1", 2, 20.0, 3.0), ("o2", 1, 50.0, 5.0)],
        "order_id STRING, order_item_id INT, price DOUBLE, freight_value DOUBLE",
    )
    payments = spark.createDataFrame(
        [("o1", 1, "voucher", 1, 5.0), ("o1", 2, "credit_card", 3, 30.0), ("o2", 1, "boleto", 1, 55.0)],
        "order_id STRING, payment_sequential INT, payment_type STRING, payment_installments INT, payment_value DOUBLE",
    )
    reviews = spark.createDataFrame([("o1", 5), ("o2", 1)], "order_id STRING, review_score INT")
    dim_customer = build_dim_customer(customers, orders, geolocation)
    fact = build_fact_orders(orders, items, payments, reviews, customers, dim_customer)
    return dim_customer, {r.order_id: r for r in fact.collect()}


def test_late_is_counted_by_day_not_by_timestamp(star):
    _, f = star
    assert (f["o1"].delay_days, f["o1"].is_late) == (0, False)
    assert (f["o2"].delay_days, f["o2"].is_late) == (1, True)
    assert f["o3"].is_late is None and f["o3"].delivery_days is None


def test_fact_orders_aggregates_items_payments_and_reviews(star):
    _, f = star
    o1 = f["o1"]
    assert (o1.nb_items, o1.order_value, o1.freight_total, o1.payment_total) == (2, 30.0, 5.0, 35.0)
    assert (o1.payment_type_main, o1.installments_max) == ("credit_card", 3)  # biggest payment wins
    assert (o1.review_score, o1.is_negative_review, f["o2"].is_negative_review) == (5, False, True)
    o3 = f["o3"]
    assert (o3.nb_items, o3.order_value, o3.payment_total, o3.review_score) == (0, 0, 0, None)


def test_dim_customer_one_row_per_real_customer_with_latest_address(star):
    dim_customer, f = star
    rows = {r.customer_unique_id: r for r in dim_customer.collect()}
    assert set(rows) == {"u1", "u2"}
    assert (rows["u1"].city, rows["u1"].lat) == ("rio de janeiro", -22.9)  # o2 is u1's latest order
    assert rows["u2"].lat is None  # zip prefix without geolocation stays, lat/lng null
    assert f["o1"].customer_key == f["o2"].customer_key == rows["u1"].customer_key


def test_dim_date_covers_whole_years_monday_is_1(spark):
    orders = spark.createDataFrame([(T("2016-09-04 21:15:19"),), (T("2018-10-17 17:30:18"),)],
                                   "order_purchase_timestamp TIMESTAMP")
    days = {r.date: r for r in build_dim_date(orders).collect()}
    assert min(days) == date(2016, 1, 1) and max(days) == date(2018, 12, 31) and len(days) == 366 + 365 + 365
    monday = days[date(2018, 1, 1)]
    assert (monday.date_key, monday.day_of_week, monday.is_weekend) == (20180101, 1, False)
    assert days[date(2018, 1, 7)].day_of_week == 7 and days[date(2018, 1, 7)].is_weekend


def test_a_failing_sql_check_stops_the_run(spark, tmp_path):
    checks = tmp_path / "checks.sql"
    checks.write_text(
        "-- comment\nSELECT 'ok' AS check_name, '1' AS actual, true AS passed;\n"
        "SELECT 'broken', '0', false;\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="broken"):
        run_sql_checks(spark, str(checks))
