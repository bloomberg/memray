from ..reporters.flamegraph import FlameGraphReporter
from .common import HighWatermarkCommand


class FlamegraphCommand(HighWatermarkCommand):
    """Generate an HTML flame graph for peak memory usage."""

    def __init__(self) -> None:
        super().__init__(
            default_output_file="pensieve-flamegraph.html",
            reporter_factory=FlameGraphReporter.from_snapshot,
        )
