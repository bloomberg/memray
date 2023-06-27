import sys


def fib1(n):
    my_list = [0, 1]
    for i in range(2, n + 1):
        my_list.append(my_list[i - 1] + my_list[i - 2])
    return my_list[-1]


def fib2(n, cache={0: 0, 1: 1}):
    if n in cache:
        return cache[n]
    cache[n] = fib2(n - 1) + fib2(n - 2)
    return cache[n]


def run():
    sys.setrecursionlimit(100000)
    n = 99900
    a = fib1(n)
    b = fib2(n)

    assert a == b


run()
