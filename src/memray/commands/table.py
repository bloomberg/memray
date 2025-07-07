import argparse

from ..reporters.table import TableReporter
from .common import HighWatermarkCommand


class TableCommand(HighWatermarkCommand):
    """Generate an HTML table with all records in the peak memory usage"""

    def __init__(self) -> None:
        super().__init__(
            reporter_factory=TableReporter.from_snapshot,
            reporter_name="table",
        )

    def prepare_parser(self, parser: argparse.ArgumentParser) -> None:
        super().prepare_parser(parser)
        parser.add_argument(
            "--no-web",
            help="Use local assets instead of fetching from CDN",
            action="store_true",
            default=False,
        )
