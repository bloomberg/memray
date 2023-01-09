"""Test the performance of pprint.PrettyPrinter.

This benchmark was available as `python -m pprint` until Python 3.12.

Authors: Fred Drake (original), Oleg Iarygin (pyperformance port).
"""

import pyperf
from pprint import PrettyPrinter
from memray_helper import get_tracker


printable = [("string", (1, 2), [3, 4], {5: 6, 7: 8})] * 100_000
p = PrettyPrinter()


def format(*args, **kwrags):
    with get_tracker():
        p.pformat(*args, **kwrags)


def safe_repr(*args, **kwargs):
    with get_tracker():
        p._safe_repr(*args, **kwargs)


if __name__ == "__main__":
    runner = pyperf.Runner()
    runner.metadata["description"] = "pprint benchmark"

    if hasattr(p, "_safe_repr"):
        runner.bench_func("pprint_safe_repr", safe_repr, printable, {}, None, 0)
    runner.bench_func("pprint_pformat", format, printable)
