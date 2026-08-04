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

        parser.add_argument(
            "--no-web",
            help="Use local assets instead of fetching from CDN",
            action="store_true",
            default=False,
        )

        parser.add_argument(
            "--confidential-files",
            help=(
                "Control what source code is included in the flame graph."
                " If set to 'all', all files are treated as confidential and"
                " no source code is included in the report (only function"
                " names, file names, and line numbers). If set to 'none',"
                " no files are treated as confidential and lines from any file"
                " may be included in the report. If set to 'default' (the"
                " default) Memray uses heuristics to guess whether each file"
                " is likely to contain secrets. It includes source lines from"
                " .py files and from any file that is world-readable or"
                " executable, and excludes lines from other files."
            ),
            choices=["all", "none", "default"],
            default="default",
        )
