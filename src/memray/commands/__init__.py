import argparse
import logging
import sys
import textwrap
from contextlib import suppress
from typing import List
from typing import Optional

from memray._errors import MemrayCommandError
from memray._errors import MemrayError
from memray._memray import set_log_level
from memray._version import __version__

from .protocol import Command

# With the intent of progressively reducing the minimal dependency footprint
# of memray we import only the commands whose dependencies are installed.
# If a dependency is missing for a command that command will not show up in
# the cli help.

_COMMANDS: List[Command] = []
_EXAMPLES: List[str] = []
_can_import_jinja = False
with suppress(ModuleNotFoundError):
    from . import run

    _COMMANDS.append(run.RunCommand())
    _EXAMPLES.append("$ python3 -m memray run -o output.bin my_script.py")
with suppress(ModuleNotFoundError):
    from . import attach

    _COMMANDS.append(attach.AttachCommand())
with suppress(ModuleNotFoundError):
    from . import flamegraph

    _COMMANDS.append(flamegraph.FlamegraphCommand())
    _EXAMPLES.append("$ python3 -m memray flamegraph output.bin")
    _can_import_jinja = True
with suppress(ModuleNotFoundError):
    from . import live

    _COMMANDS.append(live.LiveCommand())
with suppress(ModuleNotFoundError):
    from . import parse

    _COMMANDS.append(parse.ParseCommand())
with suppress(ModuleNotFoundError):
    from . import stats

    _COMMANDS.append(stats.StatsCommand())
    _EXAMPLES.append("$ python3 -m memray stats capture.bin")
with suppress(ModuleNotFoundError):
    from . import summary

    _COMMANDS.append(summary.SummaryCommand())
with suppress(ModuleNotFoundError):
    from . import table

    _COMMANDS.append(table.TableCommand())
with suppress(ModuleNotFoundError):
    from . import transform

    _COMMANDS.append(transform.TransformCommand())
with suppress(ModuleNotFoundError):
    from . import tree

    _COMMANDS.append(tree.TreeCommand())

_EPILOG = textwrap.dedent(
    """\
    Please submit feedback, ideas, and bug reports by filing a new issue at
    https://github.com/bloomberg/memray/issues
    """
)


def usage_description() -> str:
    description = "Run `memray run` to generate a memory profile report"
    if _can_import_jinja:
        description += (
            ", then use a reporter command such as `memray "
            "flamegraph` or `memray table` to convert the results into HTML."
        )
    else:
        description += "."
    return "\n".join(textwrap.wrap(description))


_DESCRIPTION = f"""\
Memory profiler for Python applications

{usage_description()}

    Example:

    """ + """
    """.join(
    _EXAMPLES
)


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
            name, help=command.__doc__, description=command.__doc__, epilog=_EPILOG
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
