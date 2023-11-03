import argparse

from ..reporters.flamegraph import FlameGraphReporter
from .common import HighWatermarkCommand


class FlamegraphCommand(HighWatermarkCommand):
    """Generate an HTML flame graph for peak memory usage"""

    def __init__(self) -> None:
        super().__init__(
            reporter_factory=FlameGraphReporter.from_snapshot,
            temporal_reporter_factory=FlameGraphReporter.from_temporal_snapshot,
            reporter_name="flamegraph",
        )

    def prepare_parser(self, parser: argparse.ArgumentParser) -> None:
        super().prepare_parser(parser)
        parser.add_argument(
            "--split-threads",
            help="Do not merge allocations across threads",
            action="store_true",
            default=False,
        )

        parser.add_argument(
            "--inverted",
            help="Invert flame graph",
            action="store_true",
            default=False,
        )

        parser.add_argument(
            "--max-memory-records",
            help="Maximum number of memory records to display",
            type=int,
            default=None,
        )
