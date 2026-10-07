from ..reporters.flamegraph import FlameGraphReporter
from .common import HighWatermarkCommand


class FlamegraphCommand(HighWatermarkCommand):
    def __init__(self) -> None:
        super().__init__(
            reporter_factory=FlameGraphReporter.from_snapshot,
            temporal_reporter_factory=FlameGraphReporter.from_temporal_snapshot,
            reporter_name="flamegraph",
        )
