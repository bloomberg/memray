import pytest
from exercise_1.fibonacci import generate_fibonacci_hash

# Memory tests


@pytest.mark.limit_memory("100 KB")
def test_fibonacci():
    LENGTH_OF_SEQUENCE_1 = 33333  # pylint: disable=invalid-name
    LENGTH_OF_SEQUENCE_2 = 30000  # pylint: disable=invalid-name
    LENGTH_OF_SEQUENCE_3 = 34567  # pylint: disable=invalid-name

    generate_fibonacci_hash(
        LENGTH_OF_SEQUENCE_1, LENGTH_OF_SEQUENCE_2, LENGTH_OF_SEQUENCE_3
    )


# Correctness tests


def test_fibonacci_empty():
    h = generate_fibonacci_hash(0, 0, 0)
    assert h == 0


@pytest.mark.parametrize(
    ("length", "expected"),
    [
        (1, 1),
        (2, 2),  # 1 + 1
        (6, 20),  # 1 + 1 + 2 + 3 + 5 + 8
    ],
)
def test_fibonacci_short(length, expected):
    h = generate_fibonacci_hash(0, 0, length)
    assert h == expected


@pytest.mark.parametrize(
    ("length", "expected"),
    [
        (1, 1),
        (2, 2),  # 1 + 1
        (6, 20),  # 1 + 1 + 2 + 3 + 5 + 8
    ],
)
def test_fibonacci_multiple(length, expected):
    h = generate_fibonacci_hash(length, length, length)
    assert h == expected * 3


def test_hash_modulo_10000():
    # 1 + 1 + 2 +3 + 5 + 8 + 13 + 21 + 34 + 55 + 89 + 144 + 233 + 377 + 610
    # + 987 + 1597 + 2584 + 4181 == 10945
    h = generate_fibonacci_hash(0, 0, 19)
    assert h == 945  # 10945 % 10000
