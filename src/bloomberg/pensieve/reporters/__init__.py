from typing import TextIO

try:
    from typing import Protocol
except ImportError:
    from typing_extensions import Protocol  # type: ignore


class BaseReporter(Protocol):
    def render(self, outfile: TextIO) -> None:
        ...
