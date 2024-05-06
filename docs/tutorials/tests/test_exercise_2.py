import numpy as np
import pytest
from exercise_2.holding_onto_memory import process_data


@pytest.mark.limit_memory("230 MB")
def test_holding_in_memory():
    process_data()


def test_result():
    result = process_data()
    assert np.all(result == 18)
