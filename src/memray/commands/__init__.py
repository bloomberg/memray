import argparse
import importlib
import logging
import sys
import textwrap
from typing import List
from typing import Optional

from memray._version import __version__

try:
    from typing import Protocol
except ImportError:
    from typing_extensions import Protocol

from memray._errors import MemrayCommandError
from memray._errors import MemrayError
from memray._memray import set_log_level

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


# Map each subcommand name to the class that implements it. Kept as plain
# strings so that building the parser (or importing this package, e.g. in the
# `memray run --live` child) never imports a command module -- and therefore
# never imports rich/textual/jinja2 -- until the selected command actually runs.
_COMMANDS = {
    "run": "memray.commands.run.RunCommand",
    "flamegraph": "memray.commands.flamegraph.FlamegraphCommand",
    "table": "memray.commands.table.TableCommand",
    "live": "memray.commands.live.LiveCommand",
    "tree": "memray.commands.tree.TreeCommand",
    "parse": "memray.commands.parse.ParseCommand",
    "summary": "memray.commands.summary.SummaryCommand",
    "stats": "memray.commands.stats.StatsCommand",
    "transform": "memray.commands.transform.TransformCommand",
    "attach": "memray.commands.attach.AttachCommand",
    "detach": "memray.commands.attach.DetachCommand",
}


def _find_command(args: List[str]) -> Optional[str]:
    """Return the subcommand named in ``args`` without invoking argparse.

    This lets ``main`` configure (and import) only the selected subcommand.
    Returns None when no command is found, so that the full parser can render
    top-level help, the version, or an error. Only the global options that take
    no value (``-v/--verbose``, ``-V/--version``, ``-h/--help``) are understood
    here; a new value-taking global option would need to be handled too.
    """
    for token in args:
        if token in _COMMANDS:
            return token
        if token in ("-h", "--help", "-V", "--version"):
            return None
        if token.startswith("-"):
            continue
        return None
    return None


def get_argument_parser(command: Optional[str] = None) -> argparse.ArgumentParser:
    """Build the CLI parser.

    When *command* is None (the default, and how docs/manpage generation calls
    this) every subcommand is fully configured. When *command* names a specific
    subcommand, only that one is imported and configured; the others are added
    as bare subparsers so they remain valid choices in usage/error messages.
    """
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

    load_all_commands = command is None
    for name in _COMMANDS:
        if load_all_commands or name == command:
            module_name, _, class_name = _COMMANDS[name].rpartition(".")
            module = importlib.import_module(module_name)
            cmd = getattr(module, class_name)()
            command_parser = subparsers.add_parser(
                name, help=cmd.__doc__, description=cmd.__doc__, epilog=_EPILOG
            )
            command_parser.set_defaults(entrypoint=cmd.run)
            cmd.prepare_parser(command_parser)
        else:
            # Register the name without importing it, so it stays a valid
            # choice and appears in the top-level usage listing.
            subparsers.add_parser(name, epilog=_EPILOG)

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

    parser = get_argument_parser(_find_command(args))
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
