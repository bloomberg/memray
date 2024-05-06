import math

import pytest
from exercise_3.lru_cache import Algorithms
from exercise_3.lru_cache import compare_counts_different_factorials
from exercise_3.lru_cache import generate_factorial_plus_last_digit

# Memory tests


@pytest.mark.limit_memory("75 MB")
def test_lru_cache():
    compare_counts_different_factorials()


# Correctness tests


@pytest.mark.parametrize("value", [1, 4, 10])
def test_algorithms_0(value):
    a = Algorithms(0)  # This is equivalent to the standard factorial function
    assert a.factorial_plus(value) == math.factorial(value)


def test_algorithms_5():
    a = Algorithms(5)

    # 3 * (2 * (1 + 5) + 5) + 5
    assert a.factorial_plus(3) == 56

    # 4 * (3 * (2 * (1 + 5) + 5) + 5) + 5
    assert a.factorial_plus(4) == 229


def test_generate_factorial_plus_last_digit_0():
    values = list(generate_factorial_plus_last_digit(1, 6))
    assert values == [1, 1, 2, 6, 4, 0]  # last digits of 1 1 2 6 24 120, i.e. 0! to 5!


def test_generate_factorial_plus_0_last_digit():
    values = list(generate_factorial_plus_last_digit(5, 1))
    assert values == [
        1,
        2,
        3,
        4,
        5,
    ]  # last digits of the first fac_plus_n factorial of 0, which is always n+1


def test_generate_factorial_plus():
    values = list(generate_factorial_plus_last_digit(3, 5))
    expected = (
        [1, 1, 2, 6, 4]
        + [2, 2, 5, 6, 5]  # last digits of the first fac_plus_0 factorial of n, i.e. n!
        + [3, 3, 8, 6, 6]  # fac_plus_1 values are [2, 2, 5, 16, 65]
    )  # fac_plus_1 values are [3, 3, 8, 26, 106]
    assert (
        values == expected
    )  # last digits of the first fac_plus(n) factorial of 0, which is always n+1
