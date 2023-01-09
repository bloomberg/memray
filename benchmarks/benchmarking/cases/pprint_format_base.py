"""Test the performance of pprint.PrettyPrinter.

This benchmark was available as `python -m pprint` until Python 3.12.

Authors: Fred Drake (original), Oleg Iarygin (pyperformance port).
"""

from pprint import PrettyPrinter

printable = [("string", (1, 2), [3, 4], {5: 6, 7: 8})] * 100_000
p = PrettyPrinter()


def run_benchmark():
    if hasattr(p, "_safe_repr"):
        p._safe_repr(printable, {}, None, 0)
    p.pformat(printable)


if __name__ == "__main__":
    run_benchmark()
