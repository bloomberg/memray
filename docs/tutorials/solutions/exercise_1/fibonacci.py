import operator
from functools import reduce
from itertools import chain


def fibonacci(length):
    # edge cases
    if length < 1:
        return
    if length == 1:
        yield 1
        return

    left = right = 1
    yield left
    yield right

    for _ in range(length - 2):
        left, right = right, left + right
        yield right


def generate_fibonacci_hash(length_1, length_2, length_3):
    # We could have used sum(...) here instead of reduce(operator.add, ...),
    # but we choose to use reduce since it yields a more descriptive example
    # of the generated flamegraph for this specific example
    return (
        reduce(
            operator.add,
            chain(fibonacci(length_1), fibonacci(length_2), fibonacci(length_3)),
            0,
        )
        % 10000
    )


if __name__ == "__main__":
    # DO NOT CHANGE
    LENGTH_OF_SEQUENCE_1 = 33333
    LENGTH_OF_SEQUENCE_2 = 30000
    LENGTH_OF_SEQUENCE_3 = 34567
    # DO NOT CHANGE
    generate_fibonacci_hash(
        LENGTH_OF_SEQUENCE_1, LENGTH_OF_SEQUENCE_2, LENGTH_OF_SEQUENCE_3
    )
