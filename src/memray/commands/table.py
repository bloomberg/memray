import argparse
from typing import cast

from ..reporters.table import TableReporter
from .common import HighWatermarkCommand
from .common import ReporterFactory


class TableCommand(HighWatermarkCommand):
    """Generate an HTML table with all records in the peak memory usage"""

    def __init__(self) -> None:
        super().__init__(
            reporter_factory=cast(ReporterFactory, TableReporter.from_snapshot),
            reporter_name="table",
        )

    def prepare_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "-o",
            "--output",
            help="Output file name",
            default=None,
        )
        parser.add_argument(
            "-f",
            "--force",
            help="If the output file already exists, overwrite it",
            action="store_true",
            default=False,
        )
        parser.add_argument(
            "--leaks",
            help="Show memory leaks, instead of peak memory usage",
            action="store_true",
            dest="show_memory_leaks",
            default=False,
        )
        parser.add_argument("results", help="Results of the tracker run")
