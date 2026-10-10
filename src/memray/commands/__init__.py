import importlib
import logging
import sys
from typing import List
from typing import Optional

from memray._errors import MemrayCommandError
from memray._errors import MemrayError
from memray._memray import set_log_level

from ._parse_args import SUBCOMMANDS
from ._parse_args import get_argument_parser

__all__ = ["get_argument_parser", "main"]


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
        # Only import the one module providing the subcommand we're running
        module_name, _, class_name = SUBCOMMANDS[arg_values.command][0].rpartition(".")
        module = importlib.import_module(f"memray.commands.{module_name}")
        getattr(module, class_name)().run(arg_values, parser)
    except MemrayCommandError as e:
        print(e, file=sys.stderr)
        return e.exit_code
    except MemrayError as e:
        print(e, file=sys.stderr)
        return 1
    else:
        return 0
