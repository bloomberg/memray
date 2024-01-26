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
from memray import Tracker, FileFormat
with Tracker(
    "{dump_file!s}",
    native_traces={native_traces},
    trace_python_allocators={trace_python_allocators},
    follow_fork={follow_fork},
    file_format=FileFormat.{file_format},
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
        help="Record allocations made by the pymalloc allocator",
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
        "--temporal",
        help=(
            "Generate a dynamic flame graph that can analyze"
            " allocations in a user-selected time range."
        ),
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--split-threads",
        help="Do not merge allocations across threads",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--inverted",
        help=(
            "Invert the flame graph: "
            "use allocators as roots instead of thread entry points"
        ),
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--max-memory-records",
        help="Maximum number of memory records to display",
        type=int,
        default=None,
    )

    return parser


@magics_class
class FlamegraphMagics(Magics):
    @cell_magic  # type: ignore
    def memray_flamegraph(self, line: str, cell: str) -> None:
        """Memory profile the code in the cell and display a flame graph."""
        if self.shell is None:
            raise UsageError("Cannot profile code when not in a shell")

        try:
            options = argument_parser().parse_args(shlex.split(line))
        except SystemExit:
            # argparse wants to bail if the options aren't valid.
            # It already printed a message, just return control to IPython.
            return

        if options.temporal and options.temporary_allocation_threshold >= 0:
            raise UsageError(
                "Can't create a temporal flame graph of temporary allocations"
            )
        elif options.temporal or options.temporary_allocation_threshold >= 0:
            file_format = "ALL_ALLOCATIONS"
        else:
            file_format = "AGGREGATED_ALLOCATIONS"

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
            file_format=file_format,
        )
        self.shell.run_cell(code)

        merge_threads = not options.split_threads

        reporter = None

        kwargs = {}
        if options.max_memory_records is not None:
            kwargs["max_memory_records"] = options.max_memory_records

        with FileReader(dump_file, report_progress=True, **kwargs) as reader:
            if reader.metadata.has_native_traces:
                warn_if_not_enough_symbols()

            if options.temporal:
                if options.show_memory_leaks:
                    temporal_snapshot = reader.get_temporal_allocation_records(
                        merge_threads=merge_threads
                    )
                    reporter = FlameGraphReporter.from_temporal_snapshot(
                        temporal_snapshot,
                        memory_records=tuple(reader.get_memory_snapshots()),
                        native_traces=reader.metadata.has_native_traces,
                        high_water_mark_by_snapshot=None,
                        inverted=options.inverted,
                    )
                else:
                    recs, hwms = reader.get_temporal_high_water_mark_allocation_records(
                        merge_threads=merge_threads
                    )
                    reporter = FlameGraphReporter.from_temporal_snapshot(
                        recs,
                        memory_records=tuple(reader.get_memory_snapshots()),
                        native_traces=reader.metadata.has_native_traces,
                        high_water_mark_by_snapshot=hwms,
                        inverted=options.inverted,
                    )
            else:
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
                    inverted=options.inverted,
                )

        assert reporter is not None
        flamegraph_path = Path(tempdir) / "flamegraph.html"
        with open(flamegraph_path, "w") as f:
            reporter.render(
                outfile=f,
                metadata=reader.metadata,
                show_memory_leaks=options.show_memory_leaks,
                merge_threads=merge_threads,
                inverted=options.inverted,
            )
        dump_file.unlink()
        pprint(f"Results saved to [bold cyan]{flamegraph_path}")
        display(IFrame(flamegraph_path, width="100%", height="600"))  # type: ignore


assert FlamegraphMagics.memray_flamegraph.__doc__ is not None
FlamegraphMagics.memray_flamegraph.__doc__ += "\n\n" + argument_parser().format_help()
