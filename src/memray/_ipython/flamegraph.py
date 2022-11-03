import argparse
import shlex
import tempfile
from pathlib import Path
from textwrap import dedent
from textwrap import indent

from IPython.core.error import UsageError
from IPython.core.magic import Magics
from IPython.core.magic import cell_magic
from IPython.core.magic import magics_class
from IPython.display import IFrame
from IPython.display import display
from rich import print as pprint

from memray import FileReader
from memray.commands.common import warn_if_not_enough_symbols
from memray.reporters.flamegraph import FlameGraphReporter

TEMPLATE = """\
from memray import Tracker
with Tracker(
    "{dump_file!s}",
    native_traces={native_traces},
    trace_python_allocators={trace_python_allocators},
    follow_fork={follow_fork},
) as tracker:
{code}
"""


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="%%memray_flamegraph")
    parser.add_argument(
        "--native",
        help="Track native (C/C++) stack frames as well",
        action="store_true",
        dest="native",
        default=False,
    )
    parser.add_argument(
        "--follow-fork",
        action="store_true",
        help="Record allocations in child processes forked from the tracked script",
        default=False,
    )
    parser.add_argument(
        "--trace-python-allocators",
        action="store_true",
        help="Record allocations made by the Pymalloc allocator",
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

    return parser


@magics_class
class FlamegraphMagics(Magics):  # type: ignore
    def parse_options(self, string: str) -> argparse.Namespace:
        return argument_parser().parse_args(shlex.split(string))

    @cell_magic  # type: ignore
    def memray_flamegraph(self, line: str, cell: str) -> None:
        """Memory profile the code in the cell and display a flame graph."""
        if self.shell is None:
            raise UsageError("Cannot profile code when not in a shell")

        try:
            options = self.parse_options(line)
        except SystemExit:
            # argparse wants to bail if the options aren't valid.
            # It already printed a message, just return control to IPython.
            return

        results_dir = Path("memray-results")
        results_dir.mkdir(exist_ok=True)

        tempdir = Path(tempfile.mkdtemp(dir=results_dir))
        dump_file = Path(tempdir) / "memray.dump"
        code = TEMPLATE.format(
            dump_file=dump_file,
            native_traces=options.native,
            trace_python_allocators=options.trace_python_allocators,
            follow_fork=options.follow_fork,
            code=indent(cell, " " * 4),
        )
        self.shell.run_cell(code)

        merge_threads = not options.split_threads

        reporter = None

        with FileReader(dump_file, report_progress=True) as reader:
            if reader.metadata.has_native_traces:
                warn_if_not_enough_symbols()

            if options.show_memory_leaks:
                snapshot = reader.get_leaked_allocation_records(
                    merge_threads=merge_threads
                )
            elif options.temporary_allocation_threshold >= 0:
                snapshot = reader.get_temporary_allocation_records(
                    threshold=options.temporary_allocation_threshold,
                    merge_threads=merge_threads,
                )
            else:
                snapshot = reader.get_high_watermark_allocation_records(
                    merge_threads=merge_threads
                )
            memory_records = tuple(reader.get_memory_snapshots())
            reporter = FlameGraphReporter.from_snapshot(
                snapshot,
                memory_records=memory_records,
                native_traces=options.native,
            )
        assert reporter is not None
        flamegraph_path = Path(tempdir) / "flamegraph.html"
        with open(flamegraph_path, "w") as f:
            reporter.render(
                outfile=f,
                metadata=reader.metadata,
                show_memory_leaks=options.show_memory_leaks,
                merge_threads=merge_threads,
            )
        dump_file.unlink()
        pprint(f"Results saved to [bold blue]{flamegraph_path}[/bold blue]")
        display(IFrame(flamegraph_path, width="100%", height="600"))


assert FlamegraphMagics.memray_flamegraph.__doc__ is not None
FlamegraphMagics.memray_flamegraph.__doc__ += "\n\n" + argument_parser().format_help()
