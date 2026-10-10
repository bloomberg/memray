import sys

import testext


def foo():
    with open(sys.argv[1], "w") as fifo:
        fifo.write("ready")
    testext.sleep10()


foo()
