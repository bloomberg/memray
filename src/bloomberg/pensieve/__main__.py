import argparse
import logging
import os
import runpy
import sys
import textwrap
import typing
from typing import List

from bloomberg.pensieve import Tracker


def _verbose_to_log_level(verbose_level: int) -> int:  # pragma: no cover
    if verbose_level == 0:
        return logging.WARNING
    elif verbose_level == 1:
        return logging.INFO
    else:
        return logging.DEBUG


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    results_file = (
        args.output
        if args.output is not None
        else f"{args.command[0]}.{os.getpid()}.out"
    )
    print(f"Writing profile results into {results_file}")
    with Tracker(results_file):
        sys.argv = args.command
        runpy.run_module(args.command[0], run_name="__main__")

    return 0


def main(argv: List[str]) -> int:
    epilog = textwrap.dedent(
        """
        This is *EXPERIMENTAL* software.

        Please submit feedback, ideas and bugs by filing a new issue at
        https://bbgithub.dev.bloomberg.com/python/bloomberg-pensieve/issues
        """
    )
    parser = argparse.ArgumentParser(
        description="Memory profiler for Python applications",
        prog="pensieve",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=epilog,
    )
    subparsers = parser.add_subparsers(help="Mode of operation", dest="command")
    subparsers.required = True
    run_parser = subparsers.add_parser(
        "run", help="Run the specified application and track memory usage"
    )
    run_parser.set_defaults(func=run)
    run_parser.add_argument("-v", "--verbose", action="count", default=0)
    run_parser.add_argument(
        "-o", "--output", help="Output file name (default: <process_name>.<pid>.out)"
    )

    run_parser.add_argument("command", help="Command to run", nargs=argparse.REMAINDER)

    args = parser.parse_args(args=argv[1:])
    logging.basicConfig(
        level=_verbose_to_log_level(args.verbose),
        format="%(levelname)s(%(funcName)s): %(message)s",
    )

    return typing.cast(int, args.func(parser, args))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
