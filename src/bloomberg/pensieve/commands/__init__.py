import argparse
import logging
import sys
import textwrap
from typing import List
from typing import Optional
from typing import cast

from typing_extensions import Protocol

from . import flamegraph
from . import run

_EPILOG = textwrap.dedent(
    """\
    This is *EXPERIMENTAL* software.

    Please submit feedback, ideas and bugs by filing a new issue at
    https://bbgithub.dev.bloomberg.com/python/bloomberg-pensieve/issues
    """
)


class Command(Protocol):
    def prepare_parser(self, parser: argparse.ArgumentParser) -> None:
        ...

    def main(self, args: argparse.Namespace) -> int:
        ...


_COMMANDS: List[Command] = [
    run.RunCommand(),
    flamegraph.FlamegraphCommand(),
]


def get_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Memory profiler for Python applications",
        prog="pensieve",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=_EPILOG,
    )
    parser.add_argument("-v", "--verbose", action="count", default=0)

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
        command_parser.set_defaults(entrypoint=command.main)
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

    logging.basicConfig(
        level=determine_logging_level_from_verbosity(arg_values.verbose),
        format="%(levelname)s(%(funcName)s): %(message)s",
    )

    return cast(int, arg_values.entrypoint(arg_values))
