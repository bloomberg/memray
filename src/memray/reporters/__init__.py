from typing import Protocol
from typing import TextIO

from memray import Metadata


class BaseReporter(Protocol):
    def render(
        self,
        outfile: TextIO,
        metadata: Metadata,
        show_memory_leaks: bool,
        merge_threads: bool,
        inverted: bool,
    ) -> None:
        ...
