from bloomberg.pensieve import test


def test_smoke():
    assert test() == 42
