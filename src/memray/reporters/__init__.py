import sys
from typing import TextIO

from memray import Metadata

if sys.version_info >= (3, 8):
    from typing import Protocol
else:
    from typing_extensions import Protocol


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
