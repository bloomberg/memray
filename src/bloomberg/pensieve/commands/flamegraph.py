from typing import cast

from ..reporters.flamegraph import FlameGraphReporter
from .common import HighWatermarkCommand
from .common import ReporterFactory


class FlamegraphCommand(HighWatermarkCommand):
    """Generate an HTML flame graph for peak memory usage."""

    def __init__(self) -> None:
        super().__init__(
            reporter_factory=cast(ReporterFactory, FlameGraphReporter.from_snapshot),
            reporter_name="flamegraph",
        )
