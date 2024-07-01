# pylint: disable=C0114 C0115 C0116 R0903 C0103

import functools
from collections import Counter

# DO NOT CHANGE
FIRST_COUNTER_RANGE = 500
SECOND_COUNTER_RANGE = 1000
# DO NOT CHANGE


class Algorithms:
    def __init__(self, inc: int):
        self.inc = inc

    @functools.cache  # pylint: disable=W1518
    def factorial_plus(self, n: int) -> int:
        return n * self.factorial_plus(n - 1) + self.inc if n > 1 else 1 + self.inc


def generate_factorial_plus_last_digit(plus_range: int, factorial_range: int):
    for i in range(plus_range):
        A = Algorithms(i)
        for j in range(factorial_range):
            yield A.factorial_plus(j) % 10


def compare_counts_different_factorials():
    counts_500 = Counter(
        generate_factorial_plus_last_digit(FIRST_COUNTER_RANGE, FIRST_COUNTER_RANGE)
    )
    counts_1000 = Counter(
        generate_factorial_plus_last_digit(SECOND_COUNTER_RANGE, SECOND_COUNTER_RANGE)
    )

    print(counts_500.most_common())
    print(counts_1000.most_common())


if __name__ == "__main__":
    compare_counts_different_factorials()
