from ..reporters.flamegraph import FlameGraphReporter
from .common import HighWatermarkCommand


class FlamegraphCommand(HighWatermarkCommand):
    """Generate an HTML flame graph for peak memory usage."""

    def __init__(self) -> None:
        super().__init__(
            reporter_factory=FlameGraphReporter.from_snapshot,
            reporter_name="flamegraph",
        )
