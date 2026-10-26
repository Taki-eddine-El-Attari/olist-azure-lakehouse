def test_delta_roundtrip(spark, tmp_path):
    path = str(tmp_path / "t")
    spark.range(5).write.format("delta").save(path)
    assert spark.read.format("delta").load(path).count() == 5
