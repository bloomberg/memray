import functools
from collections import Counter


class Algorithms:
    def __init__(self, inc: int):
        self.inc = inc
        self.factorial_plus = functools.cache(self._uncached_factorial_plus)

    def _uncached_factorial_plus(self, n: int) -> int:
        return n * self.factorial_plus(n - 1) + self.inc if n > 1 else 1 + self.inc


def generate_factorial_plus_last_digit(plus_range: int, factorial_range: int):
    for i in range(plus_range):
        A = Algorithms(i)
        for j in range(factorial_range):
            yield A.factorial_plus(j) % 10


def compare_counts_different_factorials():
    counts_500 = Counter(generate_factorial_plus_last_digit(500, 500))
    counts_1000 = Counter(generate_factorial_plus_last_digit(1000, 1000))
    print(counts_500.most_common())
    print(counts_1000.most_common())


if __name__ == "__main__":
    compare_counts_different_factorials()
