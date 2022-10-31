import argparse
import importlib.util
import shutil
import sys
from textwrap import dedent
from typing import Any
from typing import cast

from rich import print as pprint

from memray._errors import MemrayCommandError

from ..reporters.transform import TransformReporter
from .common import HighWatermarkCommand
from .common import ReporterFactory


class TransformCommand(HighWatermarkCommand):
    """Generate reports files in different formats"""

    def __init__(self) -> None:
        super().__init__(
            reporter_factory=cast(ReporterFactory, TransformReporter),
            reporter_name="transform",
        )

    def prepare_parser(self, parser: argparse.ArgumentParser) -> None:
        formats = ", ".join(TransformReporter.SUFFIX_MAP)
        parser.add_argument(
            "format",
            help=f"Format to use for the report. Available formats: {formats}",
        )
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
        parser.add_argument("results", help="Results of the tracker run")

    def run(
        self, args: argparse.Namespace, parser: argparse.ArgumentParser, **kwargs: Any
    ) -> None:
        the_format = args.format.lower()
        suffix = TransformReporter.SUFFIX_MAP.get(the_format)
        if not suffix:
            raise MemrayCommandError(
                f"Format not supported: {args.format}", exit_code=1
            )

        self.suffix = suffix
        self.reporter_name = the_format
        super().run(args, parser, format=the_format)

        post_run_callable = getattr(self, f"post_run_{the_format}", None)
        if post_run_callable:
            post_run_callable()

    def post_run_gprof2dot(self) -> None:
        assert self.output_file is not None
        command = ""
        if shutil.which("gprof2dot") is not None:
            command = "gprof2dot"
        elif importlib.util.find_spec("gprof2dot") is not None:
            command = f"{sys.executable} -m gprof2dot"
        else:
            pprint(
                ":exclamation: [red]gprof2dot doesn't seem to be installed. "
                "Please install it to be able to process the transform.[/red]"
                "\n:point_right: Check out https://github.com/jrfonseca/gprof2dot for "
                "installation instructions"
            )

        if not shutil.which("dot"):
            pprint(
                ":exclamation: [red]Graphviz doesn't seem to be installed. "
                "Please install it to be able to process the transform.[/red]"
                "\n:point_right: Check out https://graphviz.org/download/ for "
                "installation instructions"
            )

        print()
        print("To generate a graph from the transform file, run for example:")
        print(f"{command} -f json {self.output_file} | dot -Tpng -o output.png")
