import csv
from pathlib import Path

import pytest
from pyspark.sql import functions as F

from olist.bronze import TABLES, read_csv
from olist.config import LAKE_DIR, RAW_DIR, read_table

REVIEWS_SCHEMA = TABLES["order_reviews"][1]
HEADER = "review_id,order_id,review_score,review_comment_title,review_comment_message,review_creation_date,review_answer_timestamp\n"


def test_multiline_quotes_and_dates_survive_delta(spark, tmp_path):
    src = tmp_path / "reviews.csv"
    src.write_text(
        HEADER
        + 'r1,o1,5,,"line one\nline two, ""quoted""",2018-01-18 00:00:00,2018-01-18 21:46:59\n'
        + "r2,o2,1,,,2017-12-31 23:59:59,2018-01-01 00:00:01\n",
        encoding="utf-8",
    )
    delta = str(tmp_path / "delta")
    read_csv(spark, str(src), REVIEWS_SCHEMA).write.format("delta").save(delta)

    rows = {
        r.review_id: r
        for r in spark.read.format("delta").load(delta)
        .select(
            "review_id",
            "review_comment_message",
            F.date_format("review_creation_date", "yyyy-MM-dd HH:mm:ss").alias("created"),
            "_source_file",
        )
        .collect()
    }
    assert len(rows) == 2
    assert rows["r1"].review_comment_message == 'line one\nline two, "quoted"'
    # A date read back must equal the CSV text: no time-zone shift around midnight / new year.
    assert rows["r1"].created == "2018-01-18 00:00:00"
    assert rows["r2"].created == "2017-12-31 23:59:59"
    assert rows["r1"]._source_file.endswith("reviews.csv")


def test_failfast_on_value_outside_schema(spark, tmp_path):
    src = tmp_path / "bad.csv"
    src.write_text(HEADER + "r1,o1,five,,,2018-01-18 00:00:00,2018-01-18 21:46:59\n", encoding="utf-8")
    # collect(), not count(): Spark counts CSV rows without parsing the columns, so it never fails.
    with pytest.raises(Exception, match="MALFORMED"):
        read_csv(spark, str(src), REVIEWS_SCHEMA).collect()


def csv_record_count(path: Path) -> int:
    """Independent count: the csv module handles quoted line breaks."""
    with path.open(encoding="utf-8-sig", newline="") as f:
        return sum(1 for _ in csv.reader(f)) - 1


@pytest.mark.skipif(not Path(LAKE_DIR, "bronze").exists(), reason="run `python -m olist.bronze` first")
@pytest.mark.parametrize("table", TABLES)
def test_bronze_count_equals_csv(spark, table):
    expected = csv_record_count(Path(RAW_DIR) / TABLES[table][0])
    assert read_table(spark, "bronze", table).count() == expected


def test_known_counts():
    """Guards the two counts other Olist projects got wrong (see docs/benchmark.md)."""
    if not Path(RAW_DIR).exists():
        pytest.skip("no raw data")
    assert csv_record_count(Path(RAW_DIR) / TABLES["order_reviews"][0]) == 99_224
    assert csv_record_count(Path(RAW_DIR) / TABLES["category_translation"][0]) == 71
