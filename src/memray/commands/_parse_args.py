"""Construction of the ``memray`` command line parser.

Every subcommand's parser is configured here, instead of by the module that
implements it, so that building the parser needn't import all those modules.
"""

import argparse
from textwrap import dedent

from memray._version import __version__

EPILOG = dedent(
    """\
    Please submit feedback, ideas, and bug reports by filing a new issue at
    https://github.com/bloomberg/memray/issues
    """
)

DESCRIPTION = dedent(
    """\
    Memory profiler for Python applications

    Run `memray run` to generate a memory profile report, then use a reporter command
    such as `memray flamegraph` or `memray table` to convert the results into HTML.

    Example:

        $ python3 -m memray run -o output.bin my_script.py
        $ python3 -m memray flamegraph output.bin
    """
)

# The formats that `memray transform` can generate, and each one's suffix.
# Defined here to avoid needing to always import `transform.py` to parse args.
TRANSFORM_SUFFIX_MAP = {
    "gprof2dot": ".json",
    "csv": ".csv",
    "speedscope": ".speedscope.json",
}


def _add_temporary_allocation_args(group: argparse._ArgumentGroup) -> None:
    group.add_argument(
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
    group.add_argument(
        "--temporary-allocations",
        help="Equivalent to --temporary-allocation-threshold=1",
        action="store_const",
        dest="temporary_allocation_threshold",
        const=1,
    )


def _add_high_watermark_args(
    parser: argparse.ArgumentParser, *, temporal: bool
) -> None:
    """Add the arguments shared by every `HighWatermarkCommand` reporter."""
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
    if temporal:
        parser.add_argument(
            "--temporal",
            help=(
                "Generate a dynamic flame graph that can analyze"
                " allocations in a user-selected time range."
            ),
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
    _add_temporary_allocation_args(alloc_type_group)
    parser.add_argument("results", help="Results of the tracker run")


def _add_debugger_args(parser: argparse.ArgumentParser) -> None:
    """Add the arguments shared by `memray attach` and `memray detach`."""
    parser.add_argument(
        "--method",
        help="Method to use for injecting commands into the remote process",
        type=str,
        default="auto",
        choices=["auto", "sys.remote_exec", "gdb", "lldb"],
    )

    parser.add_argument(
        "-v",
        "--verbose",
        help="Print verbose debugging information.",
        action="store_true",
    )

    parser.add_argument(
        "pid",
        help="Process id to affect",
        type=int,
    )


def _add_tracking_args(parser: argparse.ArgumentParser) -> None:
    """Add the tracking options shared by `memray run` and `memray attach`."""
    parser.add_argument(
        "--aggregate",
        help="Write aggregated stats to the output file instead of all allocations",
        action="store_true",
        default=False,
    )

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


def _add_compression_args(parser: argparse.ArgumentParser) -> None:
    compression = parser.add_mutually_exclusive_group()
    compression.add_argument(
        "--compress-on-exit",
        help="Compress the resulting file using lz4 after tracking completes",
        default=True,
        action="store_true",
    )
    compression.add_argument(
        "--no-compress",
        help="Do not compress the resulting file using lz4",
        default=False,
        action="store_true",
    )


def prepare_run_parser(parser: argparse.ArgumentParser) -> None:
    """Run the specified application and track memory usage"""
    parser.usage = "%(prog)s [-m module | -c cmd | file] [args]"
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "-o",
        "--output",
        help="Output file name (default: memray-<script>.<pid>.bin)",
    )
    output_group.add_argument(
        "--live",
        help="Start a live tracking session and immediately connect a live server",
        action="store_true",
        dest="live_mode",
        default=False,
    )
    output_group.add_argument(
        "--live-remote",
        help="Start a live tracking session and wait until a client connects",
        action="store_true",
        dest="live_remote_mode",
        default=False,
    )
    parser.add_argument(
        "--live-port",
        "-p",
        help="Port to use when starting live tracking (default: random free port)",
        default=None,
        type=int,
    )
    _add_tracking_args(parser)
    parser.add_argument(
        "-q",
        "--quiet",
        help="Don't show any tracking-specific output while running",
        action="store_true",
    )
    parser.add_argument(
        "-f",
        "--force",
        help="If the output file already exists, overwrite it",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--buffered-file-io",
        help="Buffer captured records in memory instead of using memory mapped IO",
        action="store_true",
        dest="buffered_file_io",
        default=False,
    )
    _add_compression_args(parser)
    parser.add_argument(
        "-c",
        help="Program passed in as string",
        action="store_true",
        dest="run_as_cmd",
        default=False,
    )
    parser.add_argument(
        "-m",
        help="Run library module as a script (terminates option list)",
        action="store_true",
        dest="run_as_module",
    )
    parser.add_argument("script", help=argparse.SUPPRESS, metavar="file")
    parser.add_argument(
        "script_args",
        help=argparse.SUPPRESS,
        nargs=argparse.REMAINDER,
        metavar="module",
    )


def prepare_flamegraph_parser(parser: argparse.ArgumentParser) -> None:
    """Generate an HTML flame graph for peak memory usage"""
    _add_high_watermark_args(parser, temporal=True)
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


def prepare_table_parser(parser: argparse.ArgumentParser) -> None:
    """Generate an HTML table with all records in the peak memory usage"""
    _add_high_watermark_args(parser, temporal=False)
    parser.add_argument(
        "--split-threads",
        help="Do not merge allocations across threads",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--no-web",
        help="Use local assets instead of fetching from CDN",
        action="store_true",
        default=False,
    )


def prepare_transform_parser(parser: argparse.ArgumentParser) -> None:
    """Generate reports files in different formats"""
    formats = ", ".join(TRANSFORM_SUFFIX_MAP)
    parser.add_argument(
        "format",
        help=f"Format to use for the report. Available formats: {formats}",
    )
    _add_high_watermark_args(parser, temporal=False)


def prepare_live_parser(parser: argparse.ArgumentParser) -> None:
    """Remotely monitor allocations in a text-based interface"""
    parser.add_argument(
        "port",
        help="Remote port to connect to",
        default=None,
        type=int,
    )


def prepare_tree_parser(parser: argparse.ArgumentParser) -> None:
    """Generate a tree view in the terminal for peak memory usage"""
    parser.add_argument("results", help="Results of the tracker run")
    parser.add_argument(
        "-b",
        "--biggest-allocs",
        help="Show n biggest allocations (defaults to 200)",
        type=int,
        default=200,
    )
    _add_temporary_allocation_args(parser.add_mutually_exclusive_group())


def prepare_parse_parser(parser: argparse.ArgumentParser) -> None:
    """Debug a results file by parsing and printing each record in it"""
    parser.add_argument("results", help="Results of the tracker run")


def prepare_summary_parser(parser: argparse.ArgumentParser) -> None:
    """Generate a terminal-based summary report of the functions that allocate most memory"""
    parser.add_argument("results", help="Results of the tracker run")
    parser.add_argument(
        "-s",
        "--sort-column",
        help="Column number to sort on",
        type=int,
        default=1,
    )
    parser.add_argument(
        "-r",
        "--max-rows",
        help="Maximum number of rows to display",
        type=int,
        default=None,
    )
    _add_temporary_allocation_args(parser.add_mutually_exclusive_group())


def _valid_positive_int(value: str) -> int:
    try:
        ivalue = int(value)
        if ivalue <= 0:
            raise ValueError
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value} is an invalid positive int value")

    return ivalue


def prepare_stats_parser(parser: argparse.ArgumentParser) -> None:
    """Generate high level stats of the memory usage in the terminal"""
    parser.add_argument("results", help="Results of the tracker run")

    parser.add_argument(
        "-n",
        "--num-largest",
        help="Displays the top 'n' largest allocating functions. Default is 5",
        type=_valid_positive_int,
        default=5,
    )

    parser.add_argument(
        "--json",
        help="Exports stats to a JSON file",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output file name for JSON output",
        default=None,
    )
    parser.add_argument(
        "-f",
        "--force",
        help="If the JSON output file already exists, overwrite it",
        action="store_true",
        default=False,
    )


def prepare_attach_parser(parser: argparse.ArgumentParser) -> None:
    """Begin tracking allocations in an already-started process"""
    parser.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        help=(
            "Capture allocations into the given file"
            " instead of starting a live tracking session"
        ),
    )
    parser.add_argument(
        "-f",
        "--force",
        help="If the output file already exists, overwrite it",
        action="store_true",
        default=False,
    )

    _add_tracking_args(parser)
    _add_compression_args(parser)

    parser.add_argument(
        "--duration", type=int, help="Duration to track for (in seconds)"
    )

    _add_debugger_args(parser)


def prepare_detach_parser(parser: argparse.ArgumentParser) -> None:
    """End the tracking started by a previous ``memray attach`` call"""
    _add_debugger_args(parser)


# Maps each subcommand to the class implementing it and the function that
# configures its parser. The class is named by a string, relative to this
# package, so that nothing imports a command module until it is about to run.
SUBCOMMANDS = {
    "run": ("run.RunCommand", prepare_run_parser),
    "flamegraph": ("flamegraph.FlamegraphCommand", prepare_flamegraph_parser),
    "table": ("table.TableCommand", prepare_table_parser),
    "live": ("live.LiveCommand", prepare_live_parser),
    "tree": ("tree.TreeCommand", prepare_tree_parser),
    "parse": ("parse.ParseCommand", prepare_parse_parser),
    "summary": ("summary.SummaryCommand", prepare_summary_parser),
    "stats": ("stats.StatsCommand", prepare_stats_parser),
    "transform": ("transform.TransformCommand", prepare_transform_parser),
    "attach": ("attach.AttachCommand", prepare_attach_parser),
    "detach": ("attach.DetachCommand", prepare_detach_parser),
}


def get_argument_parser() -> argparse.ArgumentParser:
    """Build the fully configured `memray` command line parser."""
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        prog="memray",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=EPILOG,
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity. Option is additive and can be specified up to 3 times",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=__version__,
        help="Displays the current version of Memray",
    )

    subparsers = parser.add_subparsers(
        help="Mode of operation",
        dest="command",
        required=True,
    )

    for name, (_, prepare_parser) in SUBCOMMANDS.items():
        command_parser = subparsers.add_parser(
            name,
            help=prepare_parser.__doc__,
            description=prepare_parser.__doc__,
            epilog=EPILOG,
        )
        prepare_parser(command_parser)

    return parser
