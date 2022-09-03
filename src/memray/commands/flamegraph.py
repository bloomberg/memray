import argparse
from textwrap import dedent
from typing import cast

from ..reporters.flamegraph import FlameGraphReporter
from .common import HighWatermarkCommand
from .common import ReporterFactory


class FlamegraphCommand(HighWatermarkCommand):
    """Generate an HTML flame graph for peak memory usage"""

    def __init__(self) -> None:
        super().__init__(
            reporter_factory=cast(ReporterFactory, FlameGraphReporter.from_snapshot),
            reporter_name="flamegraph",
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
        alloc_type_group = parser.add_mutually_exclusive_group()
        alloc_type_group.add_argument(
            "--leaks",
            help="Show memory leaks, instead of peak memory usage",
            action="store_true",
            dest="show_memory_leaks",
            default=False,
        )
        alloc_type_group.add_argument(
            "--temporary-allocation-threshold",
            metavar="N",
            help=dedent(
                """
                Report temporary allocations, as opposed to leaked allocations
                or high watermark allocations.  An allocation is considered
                temporary if at most N other allocations occur before it is
                deallocated.  With N=0, an allocation is temporary only if it
                is immediately deallocated before any other allocation occurs.
                """
            ),
            action="store",
            dest="temporary_allocation_threshold",
            type=int,
            default=-1,
        )
        alloc_type_group.add_argument(
            "--temporary-allocations",
            help="Equivalent to --temporary-allocation-threshold=1",
            action="store_const",
            dest="temporary_allocation_threshold",
            const=1,
        )

        parser.add_argument(
            "--split-threads",
            help="Do not merge allocations across threads",
            action="store_true",
            default=False,
        )
        parser.add_argument("results", help="Results of the tracker run")
