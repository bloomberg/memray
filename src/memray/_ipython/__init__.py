from typing import Any


def load_ipython_extension(ipython: Any) -> None:
    from .flamegraph import FlamegraphMagics

    ipython.register_magics(FlamegraphMagics)


__all__ = ["load_ipython_extension"]
