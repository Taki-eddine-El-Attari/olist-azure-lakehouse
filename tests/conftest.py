import pytest

from olist.spark import get_spark


@pytest.fixture(scope="session")
def spark():
    session = get_spark("olist-tests")
    yield session
    session.stop()
