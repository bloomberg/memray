import sys

__all__ = ["InputReader"]

WINDOWS = sys.platform == "win32"

if WINDOWS:
    from memray._vendor.textual.drivers._input_reader_windows import InputReader
else:
    from memray._vendor.textual.drivers._input_reader_linux import InputReader
