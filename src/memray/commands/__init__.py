import argparse
import logging
import sys
import textwrap
from typing import List
from typing import Optional

from memray._version import __version__

try:
    from typing import Protocol
except ImportError:
    from typing_extensions import Protocol  # type: ignore

from memray._errors import MemrayCommandError
from memray._errors import MemrayError
from memray._memray import set_log_level

from . import attach
from . import flamegraph
from . import live
from . import parse
from . import run
from . import stats
from . import summary
from . import table
from . import transform
from . import tree

_EPILOG = textwrap.dedent(
    """\
    Please submit feedback, ideas, and bug reports by filing a new issue at
    https://github.com/bloomberg/memray/issues
    """
)

_DESCRIPTION = textwrap.dedent(
    """\
    Memory profiler for Python applications

    Run `memray run` to generate a memory profile report, then use a reporter command
    such as `memray flamegraph` or `memray table` to convert the results into HTML.

    Example:

        $ python3 -m memray run -o output.bin my_script.py
        $ python3 -m memray flamegraph output.bin
    """
)


class Command(Protocol):
    def prepare_parser(self, parser: argparse.ArgumentParser) -> None:
        ...

    def run(self, args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
        ...


_COMMANDS: List[Command] = [
    run.RunCommand(),
    flamegraph.FlamegraphCommand(),
    table.TableCommand(),
    live.LiveCommand(),
    tree.TreeCommand(),
    parse.ParseCommand(),
    summary.SummaryCommand(),
    stats.StatsCommand(),
    transform.TransformCommand(),
    attach.AttachCommand(),
]


def get_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=_DESCRIPTION,
        prog="memray",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=_EPILOG,
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

    for command in _COMMANDS:
        # Extract the CLI command name from the classes' names
        assert command.__class__.__name__.endswith("Command")
        name = command.__class__.__name__[: -len("Command")].lower()

        # Add the subcommand
        command_parser = subparsers.add_parser(
            name, help=command.__doc__, epilog=_EPILOG
        )
        command_parser.set_defaults(entrypoint=command.run)
        command.prepare_parser(command_parser)

    return parser


def determine_logging_level_from_verbosity(
    verbose_level: int,
) -> int:  # pragma: no cover
    if verbose_level == 0:
        return logging.WARNING
    elif verbose_level == 1:
        return logging.INFO
    else:
        return logging.DEBUG


def main(args: Optional[List[str]] = None) -> int:
    if args is None:
        args = sys.argv[1:]

    parser = get_argument_parser()
    arg_values = parser.parse_args(args=args)
    set_log_level(determine_logging_level_from_verbosity(arg_values.verbose))

    try:
        arg_values.entrypoint(arg_values, parser)
    except MemrayCommandError as e:
        print(e, file=sys.stderr)
        return e.exit_code
    except MemrayError as e:
        print(e, file=sys.stderr)
        return 1
    else:
        return 0
