import pytest


@pytest.fixture(autouse=True)
def use_80_columns(monkeypatch):
    """Override the COLUMNS environment variable to 80.

    This matches the assumed terminal width that is hardcoded in the tests.
    """
    monkeypatch.setenv("COLUMNS", "80")
